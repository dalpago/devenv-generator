"""Tests for the generator module."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from mirustech.devenv_generator.generator import DevEnvGenerator, load_profile
from mirustech.devenv_generator.models import ProfileConfig, PythonConfig


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
        assert 'CMD ["/bin/zsh"]' in content

    def test_render_docker_compose(self, generator: DevEnvGenerator) -> None:
        """Should render docker-compose.yml with correct content."""
        content = generator.render_docker_compose()

        assert "services:" in content
        assert "dev:" in content
        assert "test-project-claude-config" in content

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

            assert len(generated) == 4

            # Check files exist
            assert (output_path / ".devcontainer" / "Dockerfile").exists()
            assert (output_path / "docker-compose.yml").exists()
            assert (output_path / ".devcontainer" / "devcontainer.json").exists()
            assert (output_path / ".devcontainer" / "init-env.sh").exists()

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
