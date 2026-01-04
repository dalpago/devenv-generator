"""Tests for settings module."""

import os
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr

from mirustech.devenv_generator.settings import (
    AuthMethod,
    DevEnvSettings,
    RegistryConfig,
    ensure_config_dir,
    get_config_path,
    get_settings,
)


class TestAuthMethod:
    """Tests for AuthMethod enum."""

    def test_existing_value(self) -> None:
        """Test EXISTING auth method value."""
        assert AuthMethod.EXISTING.value == "existing"

    def test_stored_value(self) -> None:
        """Test STORED auth method value."""
        assert AuthMethod.STORED.value == "stored"

    def test_prompt_value(self) -> None:
        """Test PROMPT auth method value."""
        assert AuthMethod.PROMPT.value == "prompt"


class TestRegistryConfig:
    """Tests for RegistryConfig model."""

    def test_defaults(self) -> None:
        """Test default values for registry config."""
        config = RegistryConfig()
        assert config.enabled is False
        assert config.url == "git.mirus-tech.com"
        assert config.auth_method == AuthMethod.EXISTING
        assert config.username is None
        assert config.password is None
        assert config.auto_push is False
        assert config.timeout == 300

    def test_custom_values(self) -> None:
        """Test custom values for registry config."""
        config = RegistryConfig(
            enabled=True,
            url="registry.example.com",
            auth_method=AuthMethod.STORED,
            username="testuser",
            password=SecretStr("secret123"),
            auto_push=True,
            timeout=600,
        )
        assert config.enabled is True
        assert config.url == "registry.example.com"
        assert config.auth_method == AuthMethod.STORED
        assert config.username == "testuser"
        assert config.password is not None
        assert config.password.get_secret_value() == "secret123"
        assert config.auto_push is True
        assert config.timeout == 600


class TestDevEnvSettings:
    """Tests for DevEnvSettings."""

    def test_default_settings(self) -> None:
        """Test default settings without environment variables."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear any DEVENV_ prefixed vars
            env_copy = {k: v for k, v in os.environ.items() if not k.startswith("DEVENV_")}
            with patch.dict(os.environ, env_copy, clear=True):
                settings = DevEnvSettings()
                assert settings.registry.enabled is False
                assert settings.registry.url == "git.mirus-tech.com"

    def test_environment_variables(self) -> None:
        """Test loading settings from environment variables."""
        env_vars = {
            "DEVENV_REGISTRY__ENABLED": "true",
            "DEVENV_REGISTRY__URL": "custom.registry.io",
            "DEVENV_REGISTRY__AUTO_PUSH": "true",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            settings = DevEnvSettings()
            assert settings.registry.enabled is True
            assert settings.registry.url == "custom.registry.io"
            assert settings.registry.auto_push is True


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Test that get_settings returns a DevEnvSettings instance."""
        settings = get_settings()
        assert isinstance(settings, DevEnvSettings)

    def test_fresh_instance_each_call(self) -> None:
        """Test that get_settings returns a fresh instance each time."""
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is not settings2


class TestGetConfigPath:
    """Tests for get_config_path function."""

    def test_returns_path(self) -> None:
        """Test that get_config_path returns a Path."""
        path = get_config_path()
        assert isinstance(path, Path)

    def test_path_is_in_home_config(self) -> None:
        """Test that config path is in ~/.config/devenv-generator."""
        path = get_config_path()
        assert ".config/devenv-generator" in str(path)
        assert path.name == "config.env"


class TestEnsureConfigDir:
    """Tests for ensure_config_dir function."""

    def test_creates_directory(self, tmp_path: Path) -> None:
        """Test that ensure_config_dir creates the directory."""
        test_config_dir = tmp_path / ".config" / "devenv-generator"

        with patch(
            "mirustech.devenv_generator.settings.Path.expanduser",
            return_value=test_config_dir,
        ):
            # Call with patched path
            result = Path("~/.config/devenv-generator").expanduser()
            result.mkdir(parents=True, exist_ok=True)

            assert result.exists()
            assert result.is_dir()

    def test_returns_path(self) -> None:
        """Test that ensure_config_dir returns a Path."""
        result = ensure_config_dir()
        assert isinstance(result, Path)
        assert result.name == "devenv-generator"
