"""Global settings for devenv-generator using pydantic-settings."""

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthMethod(str, Enum):
    """Registry authentication methods."""

    EXISTING = "existing"  # Assume docker login already done
    STORED = "stored"  # Use credentials from config
    PROMPT = "prompt"  # Prompt for credentials when needed


class RegistryConfig(BaseModel):
    """Container registry configuration."""

    enabled: bool = Field(default=False, description="Enable registry support")
    url: str = Field(default="git.mirus-tech.com", description="Registry URL")
    auth_method: AuthMethod = Field(
        default=AuthMethod.EXISTING,
        description="Authentication method",
    )
    username: str | None = Field(
        default=None,
        description="Registry username (for stored auth)",
    )
    password: SecretStr | None = Field(
        default=None,
        description="Registry password/token (for stored auth)",
    )
    auto_push: bool = Field(
        default=False,
        description="Automatically push images after build",
    )
    timeout: int = Field(
        default=300,
        description="Pull/push timeout in seconds",
    )


class DevEnvSettings(BaseSettings):
    """Global settings for devenv-generator.

    Settings are loaded from:
    1. Environment variables with DEVENV_ prefix
    2. ~/.config/devenv-generator/config.env file

    Example environment variables:
        DEVENV_REGISTRY__ENABLED=true
        DEVENV_REGISTRY__URL=git.mirus-tech.com
        DEVENV_REGISTRY__AUTH_METHOD=existing
    """

    model_config = SettingsConfigDict(
        env_prefix="DEVENV_",
        env_nested_delimiter="__",
        env_file=Path("~/.config/devenv-generator/config.env").expanduser(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    registry: RegistryConfig = Field(default_factory=RegistryConfig)


def get_settings() -> DevEnvSettings:
    """Load and return the global settings.

    Returns:
        DevEnvSettings instance with values from environment and config file.
    """
    return DevEnvSettings()


def get_config_path() -> Path:
    """Get the path to the config file.

    Returns:
        Path to ~/.config/devenv-generator/config.env
    """
    return Path("~/.config/devenv-generator/config.env").expanduser()


def ensure_config_dir() -> Path:
    """Ensure the config directory exists.

    Returns:
        Path to ~/.config/devenv-generator/
    """
    config_dir = Path("~/.config/devenv-generator").expanduser()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir
