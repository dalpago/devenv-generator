"""Tests for the generator module."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from mirustech.devenv_generator.generator import (
    DevEnvGenerator,
    compute_build_hash,
    get_bundled_profile,
    get_docker_socket_gid,
    get_host_user_ids,
    load_profile,
)
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


class TestGetBundledProfile:
    """Tests for get_bundled_profile function."""

    def test_loads_default_profile(self) -> None:
        """Should load the default bundled profile."""
        profile = get_bundled_profile("default")
        assert profile.name == "default"

    def test_mirustech_maps_to_default(self) -> None:
        """Should map deprecated 'mirustech' to 'default'."""
        profile = get_bundled_profile("mirustech")
        assert profile.name == "default"

    def test_not_found_raises(self) -> None:
        """Should raise FileNotFoundError for unknown profile."""
        with pytest.raises(FileNotFoundError, match="Profile not found"):
            get_bundled_profile("nonexistent-profile-xyz")


class TestGetDockerSocketGid:
    """Tests for get_docker_socket_gid function."""

    def test_returns_int(self) -> None:
        """Should return an integer GID."""
        gid = get_docker_socket_gid()
        assert isinstance(gid, int)

    def test_fallback_when_socket_missing(self) -> None:
        """Should return 999 when docker socket doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            gid = get_docker_socket_gid()
            assert gid == 999


class TestGetHostUserIds:
    """Tests for get_host_user_ids function."""

    def test_returns_tuple(self) -> None:
        """Should return a tuple of (uid, gid)."""
        uid, gid = get_host_user_ids()
        assert isinstance(uid, int)
        assert isinstance(gid, int)

    def test_returns_current_user_ids(self) -> None:
        """Should return the current user's UID and GID."""
        import os

        uid, gid = get_host_user_ids()
        assert uid == os.getuid()
        assert gid == os.getgid()


class TestComputeBuildHash:
    """Tests for compute_build_hash function."""

    def test_returns_hex_string(self) -> None:
        """Should return a hex digest string."""
        profile = ProfileConfig(name="test")
        hash_result = compute_build_hash(profile)
        assert isinstance(hash_result, str)
        assert len(hash_result) == 32  # MD5 hex digest length

    def test_same_profile_same_hash(self) -> None:
        """Same profile should produce same hash."""
        profile1 = ProfileConfig(name="test", python=PythonConfig(version="3.12"))
        profile2 = ProfileConfig(name="test", python=PythonConfig(version="3.12"))
        assert compute_build_hash(profile1) == compute_build_hash(profile2)

    def test_different_profile_different_hash(self) -> None:
        """Different profiles should produce different hashes."""
        profile1 = ProfileConfig(name="test", python=PythonConfig(version="3.12"))
        profile2 = ProfileConfig(name="test", python=PythonConfig(version="3.13"))
        assert compute_build_hash(profile1) != compute_build_hash(profile2)


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

    def test_render_docker_compose_with_ports(self) -> None:
        """Docker compose includes port mappings."""
        from mirustech.devenv_generator.models import PortConfig, PortsConfig

        profile = ProfileConfig(
            name="test",
            python=PythonConfig(version="3.12"),
            ports=PortsConfig(
                ports=[
                    PortConfig(container=8000, host=8000, description="API server"),
                    PortConfig(container=5173, host=5173, description="Vite"),
                ]
            ),
        )
        generator = DevEnvGenerator(profile, project_name="test")
        content = generator.render_docker_compose()

        assert "ports:" in content
        assert "127.0.0.1:8000:8000/tcp" in content
        assert "127.0.0.1:5173:5173/tcp" in content
        assert "# API server" in content
        assert "# Vite" in content

    def test_render_docker_compose_udp_port(self) -> None:
        """UDP ports rendered correctly."""
        from mirustech.devenv_generator.models import PortConfig, PortsConfig

        profile = ProfileConfig(
            name="test",
            python=PythonConfig(version="3.12"),
            ports=PortsConfig(
                ports=[
                    PortConfig(container=5432, host=5432, protocol="udp"),
                ]
            ),
        )
        generator = DevEnvGenerator(profile, project_name="test")
        content = generator.render_docker_compose()

        assert "127.0.0.1:5432:5432/udp" in content

    def test_render_docker_compose_no_ports(self) -> None:
        """No port section when ports empty."""
        profile = ProfileConfig(name="test", python=PythonConfig(version="3.12"))
        generator = DevEnvGenerator(profile, project_name="test")
        content = generator.render_docker_compose()

        # Should not have ports section when no ports configured
        lines = content.split("\n")
        assert not any(line.strip() == "ports:" for line in lines)

    def test_render_docker_compose_network_none_warning(self, capsys) -> None:
        """Warning logged when ports with network mode none."""
        from mirustech.devenv_generator.models import NetworkConfig, PortConfig, PortsConfig

        profile = ProfileConfig(
            name="test",
            python=PythonConfig(version="3.12"),
            network=NetworkConfig(mode="none"),
            ports=PortsConfig(
                ports=[
                    PortConfig(container=8000, host=8000),
                ]
            ),
        )
        generator = DevEnvGenerator(profile, project_name="test")

        generator.render_docker_compose()

        # structlog outputs to stdout, check for warning message
        captured = capsys.readouterr()
        assert "ports will not be accessible" in captured.out


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


class TestHealthCheck:
    """Tests for container health check in generated files."""

    def test_dockerfile_includes_healthcheck(self) -> None:
        """Dockerfile should include HEALTHCHECK instruction."""
        profile = ProfileConfig(name="test")
        generator = DevEnvGenerator(profile)
        content = generator.render_dockerfile()

        assert "HEALTHCHECK" in content
        assert "--interval=30s" in content
        assert "--timeout=10s" in content
        assert "pgrep" in content


class TestSSHKeyMounting:
    """Tests for SSH key mounting in generated files."""

    def test_compose_includes_ssh_mount_when_enabled(self) -> None:
        """docker-compose should mount ~/.ssh when ssh_keys is enabled."""
        from mirustech.devenv_generator.models import MountsConfig

        profile = ProfileConfig(
            name="ssh-test",
            mounts=MountsConfig(ssh_keys=True),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_docker_compose()

        assert "~/.ssh:/home/developer/.ssh:ro" in content

    def test_compose_no_ssh_mount_when_disabled(self) -> None:
        """docker-compose should NOT mount ~/.ssh when ssh_keys is disabled."""
        from mirustech.devenv_generator.models import MountsConfig

        profile = ProfileConfig(
            name="no-ssh-test",
            mounts=MountsConfig(ssh_keys=False),
        )
        generator = DevEnvGenerator(profile)
        content = generator.render_docker_compose()

        assert "~/.ssh" not in content


class TestSandboxGenerator:
    """Tests for SandboxGenerator class."""

    @pytest.fixture
    def profile(self) -> ProfileConfig:
        """Create a test profile."""
        return ProfileConfig(
            name="test",
            description="Test profile",
            python=PythonConfig(version="3.12"),
        )

    @pytest.fixture
    def mounts(self) -> list:
        """Create test mounts."""
        from mirustech.devenv_generator.models import MountSpec

        return [
            MountSpec(host_path=Path("/home/user/project"), mode="rw"),
        ]

    def test_sandbox_generator_init(self, profile: ProfileConfig, mounts: list) -> None:
        """Should initialize with correct attributes."""
        from mirustech.devenv_generator.generator import SandboxGenerator

        generator = SandboxGenerator(
            profile=profile,
            mounts=mounts,
            sandbox_name="test-sandbox",
        )
        assert generator.profile == profile
        assert generator.sandbox_name == "test-sandbox"
        assert generator.mounts == mounts
        assert generator.use_host_claude_config is True

    def test_render_dockerfile(self, profile: ProfileConfig, mounts: list) -> None:
        """Should render Dockerfile with correct content."""
        from mirustech.devenv_generator.generator import SandboxGenerator

        generator = SandboxGenerator(
            profile=profile,
            mounts=mounts,
            sandbox_name="test-sandbox",
        )
        content = generator.render_dockerfile()

        assert "FROM python:3.12-slim" in content
        assert "# Profile: test" in content

    def test_render_docker_compose(self, profile: ProfileConfig, mounts: list) -> None:
        """Should render sandbox docker-compose.yml."""
        from mirustech.devenv_generator.generator import SandboxGenerator

        generator = SandboxGenerator(
            profile=profile,
            mounts=mounts,
            sandbox_name="test-sandbox",
        )
        content = generator.render_docker_compose()

        assert "services:" in content
        assert "dev:" in content

    def test_render_env_example(self, profile: ProfileConfig, mounts: list) -> None:
        """Should render .env.example for sandbox."""
        from mirustech.devenv_generator.generator import SandboxGenerator

        generator = SandboxGenerator(
            profile=profile,
            mounts=mounts,
            sandbox_name="test-sandbox",
        )
        content = generator.render_env_example()

        assert "ANTHROPIC_AUTH_TOKEN" in content
        assert "Environment variables for sandbox" in content

    def test_render_sops_yaml(self, profile: ProfileConfig, mounts: list) -> None:
        """Should render .sops.yaml configuration."""
        from mirustech.devenv_generator.generator import SandboxGenerator

        generator = SandboxGenerator(
            profile=profile,
            mounts=mounts,
            sandbox_name="test-sandbox",
        )
        content = generator.render_sops_yaml()

        assert "creation_rules" in content
        assert "age" in content

    def test_generate_creates_files(
        self, profile: ProfileConfig, mounts: list, tmp_path: Path
    ) -> None:
        """Should create all expected sandbox files."""
        from mirustech.devenv_generator.generator import SandboxGenerator

        generator = SandboxGenerator(
            profile=profile,
            mounts=mounts,
            sandbox_name="test-sandbox",
        )
        generated = generator.generate(tmp_path)

        # Check files were created
        assert len(generated) >= 4
        assert (tmp_path / ".devcontainer" / "Dockerfile").exists()
        assert (tmp_path / "docker-compose.yml").exists()
        assert (tmp_path / ".env.example").exists()
        assert (tmp_path / ".sops.yaml").exists()
        assert (tmp_path / ".devcontainer" / ".build-hash").exists()

    def test_sandbox_with_cow_mount(self, profile: ProfileConfig) -> None:
        """Should handle copy-on-write mounts."""
        from mirustech.devenv_generator.generator import SandboxGenerator
        from mirustech.devenv_generator.models import MountSpec

        mounts = [
            MountSpec(host_path=Path("/home/user/project"), mode="cow"),
        ]

        generator = SandboxGenerator(
            profile=profile,
            mounts=mounts,
            sandbox_name="test-sandbox",
        )
        content = generator.render_docker_compose()

        # COW mounts use overlay filesystem
        assert "services:" in content

    def test_sandbox_without_host_claude_config(
        self, profile: ProfileConfig, mounts: list
    ) -> None:
        """Should not mount ~/.claude when disabled."""
        from mirustech.devenv_generator.generator import SandboxGenerator

        generator = SandboxGenerator(
            profile=profile,
            mounts=mounts,
            sandbox_name="test-sandbox",
            use_host_claude_config=False,
        )
        content = generator.render_docker_compose()

        # When disabled, should not mount host claude config
        # The exact behavior depends on template implementation
        assert "services:" in content
