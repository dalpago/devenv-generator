"""Tests for the generator module."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from mirustech.devenv_generator.generator import DevEnvGenerator, load_profile
from mirustech.devenv_generator.models import NetworkConfig, ProfileConfig, PythonConfig


class TestLoadProfile:
    """Tests for profile loading."""

    def test_load_profile_not_found(self) -> None:
        """Should raise FileNotFoundError for missing profile."""
        with pytest.raises(FileNotFoundError):
            load_profile(Path("/nonexistent/profile.yaml"))

    def test_load_profile_valid(self, tmp_path: Path) -> None:
        """Should load valid YAML profile."""
        profile_content = """
name: test-profile
description: Test description
python:
  version: "3.12"
"""
        profile_path = tmp_path / "test.yaml"
        profile_path.write_text(profile_content)

        config = load_profile(profile_path)
        assert config.name == "test-profile"
        assert config.description == "Test description"


class TestDevEnvGenerator:
    """Tests for DevEnvGenerator class."""

    @pytest.fixture
    def profile(self) -> ProfileConfig:
        """Create a test profile."""
        return ProfileConfig(
            name="test",
            description="Test profile",
            python=PythonConfig(version="3.12"),
        )

    @pytest.fixture
    def generator(self, profile: ProfileConfig) -> DevEnvGenerator:
        """Create a generator with test profile."""
        return DevEnvGenerator(profile, project_name="test-project")

    def test_render_dockerfile(self, generator: DevEnvGenerator) -> None:
        """Should render Dockerfile with correct content."""
        content = generator.render_dockerfile()

        assert "FROM python:3.12-slim" in content
        assert "# Profile: test" in content
        assert "uv" in content  # Should install uv

    def test_render_dockerfile_zsh(self, generator: DevEnvGenerator) -> None:
        """Should configure zsh if in system packages."""
        content = generator.render_dockerfile()

        # Default profile includes zsh
        assert "zsh" in content
        # Should set zsh as default shell via env var and user shell
        assert "SHELL=/bin/zsh" in content
        assert "-s /bin/zsh" in content  # useradd shell option

    def test_render_docker_compose(self, generator: DevEnvGenerator) -> None:
        """Should render docker-compose.yml with correct content."""
        content = generator.render_docker_compose()

        assert "services:" in content
        assert "dev:" in content
        # Default claude_config is 'bind', so should mount ~/.claude
        assert "~/.claude:/home/developer/.claude" in content

    def test_render_devcontainer_json(self, generator: DevEnvGenerator) -> None:
        """Should render devcontainer.json with correct content."""
        content = generator.render_devcontainer_json()

        assert '"name": "test-project-dev"' in content
        assert "Dockerfile" in content

    def test_render_init_script(self, generator: DevEnvGenerator) -> None:
        """Should render init-env.sh with correct content."""
        content = generator.render_init_script()

        assert "#!/bin/bash" in content
        assert "uv sync" in content
        assert "pre-commit install" in content

    def test_generate_creates_files(self, generator: DevEnvGenerator) -> None:
        """Should create all expected files."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir)
            generated = generator.generate(output_path)

            assert len(generated) == 7

            # Check files exist
            assert (output_path / ".devcontainer" / "Dockerfile").exists()
            assert (output_path / "docker-compose.yml").exists()
            assert (output_path / ".devcontainer" / "devcontainer.json").exists()
            assert (output_path / ".devcontainer" / "init-env.sh").exists()
            assert (output_path / ".env.example").exists()
            assert (output_path / ".sops.yaml").exists()
            assert (output_path / ".gitignore").exists()

            # Check init script is executable
            init_script = output_path / ".devcontainer" / "init-env.sh"
            assert init_script.stat().st_mode & 0o100  # Has execute bit

    def test_generate_with_custom_python_version(self) -> None:
        """Should respect custom Python version."""
        profile = ProfileConfig(
            name="custom",
            python=PythonConfig(version="3.13"),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_dockerfile()

        assert "FROM python:3.13-slim" in content


class TestNetworkRestriction:
    """Tests for network restriction in generated files."""

    def test_dockerfile_includes_iptables_for_restricted_mode(self) -> None:
        """Dockerfile should install iptables for restricted network mode."""
        profile = ProfileConfig(
            name="restricted-test",
            network=NetworkConfig(mode="restricted"),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_dockerfile()

        assert "iptables" in content
        assert "network-entrypoint" in content
        assert "iptables -P OUTPUT DROP" in content

    def test_dockerfile_no_iptables_for_full_mode(self) -> None:
        """Dockerfile should NOT install iptables for full network mode."""
        profile = ProfileConfig(
            name="full-test",
            network=NetworkConfig(mode="full"),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_dockerfile()

        # iptables should not be in system packages for full mode
        assert "network-entrypoint" not in content

    def test_dockerfile_no_iptables_for_none_mode(self) -> None:
        """Dockerfile should NOT install iptables for none mode (Docker handles it)."""
        profile = ProfileConfig(
            name="none-test",
            network=NetworkConfig(mode="none"),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_dockerfile()

        assert "network-entrypoint" not in content

    def test_dockerfile_includes_allowed_domains(self) -> None:
        """Dockerfile should include the allowed domains in the entrypoint script."""
        profile = ProfileConfig(
            name="restricted-test",
            network=NetworkConfig(mode="restricted"),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_dockerfile()

        # Should include default allowed domains
        assert "api.anthropic.com" in content
        assert "pypi.org" in content
        assert "github.com" in content

    def test_dockerfile_includes_custom_domains(self) -> None:
        """Dockerfile should include custom allowed domains."""
        profile = ProfileConfig(
            name="restricted-test",
            network=NetworkConfig(
                mode="restricted",
                allowed_domains=["custom.example.com"],
            ),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_dockerfile()

        assert "custom.example.com" in content
        # Should NOT include defaults when custom domains specified
        assert "api.anthropic.com" not in content

    def test_compose_includes_network_mode_none(self) -> None:
        """docker-compose should use network_mode: none for none mode."""
        profile = ProfileConfig(
            name="none-test",
            network=NetworkConfig(mode="none"),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_docker_compose()

        assert 'network_mode: "none"' in content

    def test_compose_includes_cap_net_admin_for_restricted(self) -> None:
        """docker-compose should add NET_ADMIN capability for restricted mode."""
        profile = ProfileConfig(
            name="restricted-test",
            network=NetworkConfig(mode="restricted"),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_docker_compose()

        assert "cap_add:" in content
        assert "NET_ADMIN" in content

    def test_compose_no_network_config_for_full_mode(self) -> None:
        """docker-compose should have no special network config for full mode."""
        profile = ProfileConfig(
            name="full-test",
            network=NetworkConfig(mode="full"),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_docker_compose()

        assert 'network_mode: "none"' not in content
        assert "NET_ADMIN" not in content
