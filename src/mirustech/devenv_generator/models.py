"""Pydantic models for devenv-generator configuration."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PythonConfig(BaseModel):
    """Python configuration for the development environment."""

    version: str = Field(default="3.12", description="Python version")
    packages: list[str] = Field(
        default_factory=list,
        description="Python packages to install in project venv via uv",
    )


class NetworkConfig(BaseModel):
    """Network configuration for the container."""

    mode: Literal["full", "restricted", "none"] = Field(
        default="full",
        description="Network access mode: full (all access), restricted (allowlist), none",
    )
    allowed_domains: list[str] = Field(
        default_factory=list,
        description="Domains to allowlist when mode is 'restricted'",
    )


class MountsConfig(BaseModel):
    """Mount configuration for the container."""

    gitconfig: bool = Field(default=True, description="Mount host ~/.gitconfig")
    ssh_keys: bool = Field(default=False, description="Mount host ~/.ssh")
    claude_config: Literal["volume", "bind", "none"] = Field(
        default="bind",
        description="How to persist Claude config: volume (Docker), bind (host), none",
    )
    happy_config: bool = Field(
        default=True, description="Mount host ~/.happy for Happy Coder mobile client"
    )


class ProfileConfig(BaseModel):
    """Complete profile configuration for a development environment."""

    name: str = Field(..., description="Profile name")
    description: str = Field(default="", description="Profile description")
    python: PythonConfig = Field(default_factory=PythonConfig)
    uvx_tools: list[str] = Field(
        default_factory=lambda: ["pre-commit", "ruff", "deptry", "mypy"],
        description="Python tools to install globally via uvx",
    )
    system_packages: list[str] = Field(
        default_factory=lambda: [
            "git",
            "curl",
            "wget",
            "vim",
            "zsh",
            "make",
            "build-essential",
            "ripgrep",
            "fd-find",
            "jq",
            "tree",
            "less",
        ],
        description="System packages to install via apt",
    )
    node_packages: list[str] = Field(
        default_factory=lambda: ["@anthropic-ai/claude-code", "happy-coder"],
        description="Node.js packages to install globally via npm",
    )
    github_releases: dict[str, str] = Field(
        default_factory=lambda: {
            "delta": "https://github.com/dandavison/delta/releases/download/0.18.2/git-delta_0.18.2_amd64.deb",
            "bat": "https://github.com/sharkdp/bat/releases/download/v0.24.0/bat_0.24.0_amd64.deb",
        },
        description="Tools to install from GitHub releases (name -> URL)",
    )
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Additional environment variables to set (CLAUDE_CODE_OAUTH_TOKEN is always included)",
    )
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    mounts: MountsConfig = Field(default_factory=MountsConfig)
    docker_cli: bool = Field(
        default=True,
        description="Install Docker CLI and mount docker.sock for Docker-in-Docker",
    )


class GeneratorConfig(BaseModel):
    """Configuration for the generator itself."""

    profiles_dir: Path = Field(
        default=Path("~/.config/devenv-generator/profiles").expanduser(),
        description="Directory containing profile YAML files",
    )
    default_profile: str = Field(
        default="mirustech",
        description="Default profile to use if none specified",
    )


class MountSpec(BaseModel):
    """Specification for a project mount in sandbox mode."""

    host_path: Path = Field(..., description="Path on host to mount")
    mode: Literal["rw", "ro", "cow"] = Field(
        default="rw",
        description="Mount mode: rw (read-write), ro (read-only), cow (copy-on-write)",
    )
    name: str | None = Field(
        default=None,
        description="Name for the mount point (default: directory name)",
    )

    @field_validator("host_path", mode="before")
    @classmethod
    def expand_path(cls, v: str | Path) -> Path:
        """Expand ~ and resolve to absolute path."""
        return Path(v).expanduser().resolve()

    @property
    def container_path(self) -> str:
        """Get the container path for this mount."""
        mount_name = self.name or self.host_path.name
        return f"/workspace/{mount_name}"

    @classmethod
    def from_string(cls, spec: str) -> "MountSpec":
        """Parse a mount spec string like '/path/to/project:ro'.

        Format: path[:mode]
        - path: Host path to mount
        - mode: Optional, one of 'rw', 'ro', 'cow' (default: 'rw')

        Examples:
            /path/to/project -> MountSpec(path, mode='rw')
            /path/to/project:ro -> MountSpec(path, mode='ro')
            /path/to/project:cow -> MountSpec(path, mode='cow')
        """
        parts = spec.rsplit(":", 1)
        path = parts[0]

        mode: Literal["rw", "ro", "cow"] = "rw"
        if len(parts) == 2 and parts[1] in ("rw", "ro", "cow"):
            mode = parts[1]  # type: ignore[assignment]

        return cls(host_path=Path(path), mode=mode)


class SandboxConfig(BaseModel):
    """Configuration for a sandbox environment."""

    name: str = Field(..., description="Sandbox name")
    mounts: list[MountSpec] = Field(
        default_factory=list,
        description="Project directories to mount",
    )
    profile: ProfileConfig = Field(..., description="Profile configuration")
    use_host_claude_config: bool = Field(
        default=True,
        description="Mount host ~/.claude for CLAUDE.md, MCP servers, and settings",
    )


def sanitize_project_name(name: str) -> str:
    """Sanitize a project name for use in container registry.

    Container registries typically require lowercase alphanumeric names
    with dashes. This function converts project names to be registry-compliant.

    Args:
        name: The original project name.

    Returns:
        A sanitized name suitable for container registry use.

    Examples:
        >>> sanitize_project_name("MyProject")
        'myproject'
        >>> sanitize_project_name("my_project")
        'my-project'
        >>> sanitize_project_name("my project")
        'my-project'
        >>> sanitize_project_name("123project")
        'devenv-123project'
    """
    # Convert to lowercase
    result = name.lower()

    # Replace underscores and spaces with dashes
    result = result.replace("_", "-").replace(" ", "-")

    # Remove any characters that aren't alphanumeric or dash
    result = re.sub(r"[^a-z0-9-]", "", result)

    # Collapse multiple dashes into one
    result = re.sub(r"-+", "-", result)

    # Strip leading/trailing dashes
    result = result.strip("-")

    # If name starts with a number, prepend 'devenv-'
    if result and result[0].isdigit():
        result = f"devenv-{result}"

    # If empty after sanitization, use a default
    if not result:
        result = "devenv-project"

    return result


@dataclass(frozen=True)
class ImageSpec:
    """Immutable value object for container image specification.

    Represents a fully qualified container image reference including
    registry, project name, and tag.

    Attributes:
        registry: The container registry URL (e.g., 'git.mirus-tech.com').
        project: The sanitized project name.
        tag: The image tag (e.g., git SHA or 'latest').
    """

    registry: str
    project: str
    tag: str

    @property
    def full_name(self) -> str:
        """Get the fully qualified image name.

        Returns:
            Full image reference in format 'registry/project:tag'.

        Example:
            >>> spec = ImageSpec('git.mirus-tech.com', 'myproject', 'abc123')
            >>> spec.full_name
            'git.mirus-tech.com/myproject:abc123'
        """
        return f"{self.registry}/{self.project}:{self.tag}"

    def with_tag(self, new_tag: str) -> "ImageSpec":
        """Create a new ImageSpec with a different tag.

        Args:
            new_tag: The new tag to use.

        Returns:
            A new ImageSpec with the updated tag.
        """
        return ImageSpec(registry=self.registry, project=self.project, tag=new_tag)
