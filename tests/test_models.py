"""Tests for configuration models."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from mirustech.devenv_generator.models import (
    ImageSpec,
    MountsConfig,
    MountSpec,
    NetworkConfig,
    PortConfig,
    PortsConfig,
    ProfileConfig,
    PythonConfig,
    sanitize_project_name,
)


class TestPythonConfig:
    """Tests for PythonConfig model."""

    def test_default_version(self) -> None:
        """Default Python version should be 3.12."""
        config = PythonConfig()
        assert config.version == "3.12"

    def test_custom_version(self) -> None:
        """Custom Python version should be accepted."""
        config = PythonConfig(version="3.13")
        assert config.version == "3.13"

    def test_packages_default_empty(self) -> None:
        """Packages should default to empty list."""
        config = PythonConfig()
        assert config.packages == []

    def test_packages_custom(self) -> None:
        """Custom packages should be accepted."""
        config = PythonConfig(packages=["pytest", "polars"])
        assert config.packages == ["pytest", "polars"]


class TestNetworkConfig:
    """Tests for NetworkConfig model."""

    def test_default_mode(self) -> None:
        """Default network mode should be 'full'."""
        config = NetworkConfig()
        assert config.mode == "full"

    def test_restricted_mode(self) -> None:
        """Restricted mode should be accepted."""
        config = NetworkConfig(
            mode="restricted",
            allowed_domains=["github.com", "pypi.org"],
        )
        assert config.mode == "restricted"
        assert "github.com" in config.allowed_domains

    def test_none_mode(self) -> None:
        """None mode should be accepted."""
        config = NetworkConfig(mode="none")
        assert config.mode == "none"

    def test_effective_allowed_domains_returns_defaults_when_empty(self) -> None:
        """Should return sensible defaults when no domains specified."""
        config = NetworkConfig(mode="restricted")
        domains = config.effective_allowed_domains
        # Should include essential services
        assert "api.anthropic.com" in domains
        assert "pypi.org" in domains
        assert "github.com" in domains
        assert "registry.npmjs.org" in domains

    def test_effective_allowed_domains_returns_custom_when_specified(self) -> None:
        """Should use custom domains when specified."""
        config = NetworkConfig(
            mode="restricted",
            allowed_domains=["custom.example.com", "another.example.org"],
        )
        domains = config.effective_allowed_domains
        assert domains == ["custom.example.com", "another.example.org"]
        # Should NOT include defaults
        assert "api.anthropic.com" not in domains

    def test_effective_allowed_domains_full_mode_still_returns_defaults(self) -> None:
        """Full mode should still have effective_allowed_domains for consistency."""
        config = NetworkConfig(mode="full")
        domains = config.effective_allowed_domains
        # Property works regardless of mode
        assert "api.anthropic.com" in domains


class TestMountsConfig:
    """Tests for MountsConfig model."""

    def test_defaults(self) -> None:
        """Default mounts should have expected values."""
        config = MountsConfig()
        assert config.gitconfig is True
        assert config.ssh_keys is False
        assert config.claude_config == "bind"
        assert config.happy_config is True


class TestProfileConfig:
    """Tests for ProfileConfig model."""

    def test_minimal_profile(self) -> None:
        """Minimal profile with just name should work."""
        config = ProfileConfig(name="test")
        assert config.name == "test"
        assert config.python.version == "3.12"

    def test_default_uvx_tools(self) -> None:
        """Default uvx tools should include standard dev tools."""
        config = ProfileConfig(name="test")
        assert "pre-commit" in config.uvx_tools
        assert "ruff" in config.uvx_tools
        assert "mypy" in config.uvx_tools

    def test_default_node_packages(self) -> None:
        """Default node packages should include Claude Code."""
        config = ProfileConfig(name="test")
        assert "@anthropic-ai/claude-code" in config.node_packages

    def test_full_profile(self) -> None:
        """Full profile with all options should work."""
        config = ProfileConfig(
            name="full-test",
            description="Test profile",
            python=PythonConfig(version="3.13", packages=["pytest"]),
            uvx_tools=["ruff"],
            system_packages=["git", "vim"],
            node_packages=["@anthropic-ai/claude-code"],
            environment={"MY_VAR": "value"},
            network=NetworkConfig(mode="full"),
            mounts=MountsConfig(gitconfig=True),
        )
        assert config.name == "full-test"
        assert config.python.version == "3.13"
        assert config.mounts.gitconfig is True

    def test_ports_default_empty(self) -> None:
        """Ports config is empty by default."""
        config = ProfileConfig(name="test")
        assert config.ports.ports == []

    def test_ports_from_dict(self) -> None:
        """Ports can be loaded from dictionary."""
        config = ProfileConfig(
            name="test",
            ports=PortsConfig(ports=[PortConfig(container=8000, host=8000, description="API")]),
        )
        assert len(config.ports.ports) == 1
        assert config.ports.ports[0].description == "API"


class TestPortConfig:
    """Tests for PortConfig model."""

    def test_container_port_required(self) -> None:
        """Container port is required."""
        with pytest.raises(ValidationError):
            PortConfig()

    def test_host_port_defaults_to_container(self) -> None:
        """Host port defaults to container port if not specified."""
        config = PortConfig(container=8000)
        assert config.host_port == 8000

    def test_host_port_explicit(self) -> None:
        """Host port can be explicitly set."""
        config = PortConfig(container=3000, host=8080)
        assert config.host_port == 8080
        assert config.container == 3000

    def test_protocol_defaults_to_tcp(self) -> None:
        """Protocol defaults to tcp."""
        config = PortConfig(container=8000)
        assert config.protocol == "tcp"

    def test_protocol_udp(self) -> None:
        """Protocol can be set to udp."""
        config = PortConfig(container=5432, protocol="udp")
        assert config.protocol == "udp"

    def test_invalid_protocol(self) -> None:
        """Invalid protocol raises ValidationError."""
        with pytest.raises(ValidationError):
            PortConfig(container=8000, protocol="sctp")

    def test_description_optional(self) -> None:
        """Description is optional."""
        config = PortConfig(container=8000)
        assert config.description == ""

        config_with_desc = PortConfig(container=8000, description="API server")
        assert config_with_desc.description == "API server"


class TestPortsConfig:
    """Tests for PortsConfig model."""

    def test_empty_ports_by_default(self) -> None:
        """Ports list is empty by default."""
        config = PortsConfig()
        assert config.ports == []

    def test_single_port(self) -> None:
        """Can configure single port."""
        config = PortsConfig(ports=[PortConfig(container=8000, host=8000)])
        assert len(config.ports) == 1
        assert config.ports[0].container == 8000

    def test_multiple_ports(self) -> None:
        """Can configure multiple ports."""
        config = PortsConfig(
            ports=[
                PortConfig(container=8000, host=8000),
                PortConfig(container=5173, host=5173),
                PortConfig(container=3000, host=3000),
            ]
        )
        assert len(config.ports) == 3

    def test_duplicate_host_ports_rejected(self) -> None:
        """Duplicate host ports are rejected."""
        with pytest.raises(ValueError, match="Duplicate host ports"):
            PortsConfig(
                ports=[
                    PortConfig(container=8000, host=8080),
                    PortConfig(container=3000, host=8080),  # Duplicate host port
                ]
            )

    def test_duplicate_container_ports_allowed(self) -> None:
        """Duplicate container ports are allowed (different hosts)."""
        config = PortsConfig(
            ports=[
                PortConfig(container=8000, host=8080),
                PortConfig(container=8000, host=9080),  # Same container, different host
            ]
        )
        assert len(config.ports) == 2

    def test_auto_assigned_host_ports_unique(self) -> None:
        """Auto-assigned host ports don't conflict."""
        config = PortsConfig(
            ports=[
                PortConfig(container=8000),  # Auto: host=8000
                PortConfig(container=5173),  # Auto: host=5173
            ]
        )
        assert len(config.ports) == 2


class TestMountSpec:
    """Tests for MountSpec model."""

    def test_expand_path_tilde(self, tmp_path: Path) -> None:
        """Test that ~ is expanded in paths."""
        spec = MountSpec(host_path=tmp_path)
        assert spec.host_path.is_absolute()

    def test_container_path_default(self, tmp_path: Path) -> None:
        """Test container path uses host path name."""
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        spec = MountSpec(host_path=project_dir)
        assert spec.container_path == "/workspace/myproject"

    def test_container_path_with_custom_name(self, tmp_path: Path) -> None:
        """Test container path uses custom name when provided."""
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        spec = MountSpec(host_path=project_dir, name="custom")
        assert spec.container_path == "/workspace/custom"

    def test_from_string_simple_path(self, tmp_path: Path) -> None:
        """Test from_string with simple path."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        spec = MountSpec.from_string(str(project_dir))
        assert spec.host_path == project_dir
        assert spec.mode == "rw"

    def test_from_string_readonly(self, tmp_path: Path) -> None:
        """Test from_string with :ro suffix."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        spec = MountSpec.from_string(f"{project_dir}:ro")
        assert spec.host_path == project_dir
        assert spec.mode == "ro"

    def test_from_string_cow(self, tmp_path: Path) -> None:
        """Test from_string with :cow suffix."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        spec = MountSpec.from_string(f"{project_dir}:cow")
        assert spec.host_path == project_dir
        assert spec.mode == "cow"

    def test_from_string_rw_explicit(self, tmp_path: Path) -> None:
        """Test from_string with explicit :rw suffix."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        spec = MountSpec.from_string(f"{project_dir}:rw")
        assert spec.mode == "rw"


class TestSanitizeProjectName:
    """Tests for sanitize_project_name function."""

    def test_lowercase(self) -> None:
        """Test that uppercase is converted to lowercase."""
        assert sanitize_project_name("MyProject") == "myproject"

    def test_underscores_to_dashes(self) -> None:
        """Test that underscores are replaced with dashes."""
        assert sanitize_project_name("my_project") == "my-project"

    def test_spaces_to_dashes(self) -> None:
        """Test that spaces are replaced with dashes."""
        assert sanitize_project_name("my project") == "my-project"

    def test_removes_special_chars(self) -> None:
        """Test that special characters are removed."""
        assert sanitize_project_name("my@project!test") == "myprojecttest"

    def test_collapses_multiple_dashes(self) -> None:
        """Test that multiple dashes are collapsed."""
        assert sanitize_project_name("my--project---test") == "my-project-test"

    def test_strips_leading_trailing_dashes(self) -> None:
        """Test that leading/trailing dashes are stripped."""
        assert sanitize_project_name("-myproject-") == "myproject"

    def test_prepends_devenv_for_numeric_start(self) -> None:
        """Test that 'devenv-' is prepended when name starts with number."""
        assert sanitize_project_name("123project") == "devenv-123project"

    def test_empty_name_uses_default(self) -> None:
        """Test that empty name uses default."""
        assert sanitize_project_name("!!!") == "devenv-project"


class TestImageSpec:
    """Tests for ImageSpec dataclass."""

    def test_full_name(self) -> None:
        """Test full_name property."""
        spec = ImageSpec(registry="git.mirus-tech.com", project="myproject", tag="abc123")
        assert spec.full_name == "git.mirus-tech.com/myproject:abc123"

    def test_with_tag(self) -> None:
        """Test with_tag method returns new instance."""
        spec = ImageSpec(registry="git.mirus-tech.com", project="myproject", tag="abc123")
        new_spec = spec.with_tag("latest")
        assert new_spec.tag == "latest"
        assert new_spec.registry == spec.registry
        assert new_spec.project == spec.project
        # Original unchanged
        assert spec.tag == "abc123"

    def test_immutable(self) -> None:
        """Test that ImageSpec is frozen (immutable)."""
        spec = ImageSpec(registry="registry", project="proj", tag="tag")
        with pytest.raises(AttributeError):
            spec.tag = "new"  # type: ignore[misc]
