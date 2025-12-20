"""Tests for configuration models."""

import pytest

from mirustech.devenv_generator.models import (
    MountsConfig,
    NetworkConfig,
    ProfileConfig,
    PythonConfig,
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


class TestMountsConfig:
    """Tests for MountsConfig model."""

    def test_defaults_isolated(self) -> None:
        """Default mounts should be isolated."""
        config = MountsConfig()
        assert config.gitconfig is False
        assert config.ssh_keys is False
        assert config.claude_config == "volume"


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
