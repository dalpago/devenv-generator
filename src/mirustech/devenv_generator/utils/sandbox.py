"""Shared sandbox constants and helpers used across command modules.

Single definition point for SANDBOXES_DIR, compose_project_name, get_sandbox_dir,
and load_profile_by_name. All command modules import from here; none define their own.
Multiple independent definitions of these values cause silent divergence when one
definition is updated but others are not.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from mirustech.devenv_generator.generator import get_bundled_profile, load_profile
from mirustech.devenv_generator.models import ProfileConfig

console = Console()

SANDBOXES_DIR = Path("~/.local/share/devenv-sandboxes").expanduser()


def compose_project_name(name: str) -> str:
    """Return the Docker Compose project name for a sandbox.

    Prefixed with 'devenv-' so devenv projects never collide with
    user-started compose projects that share the same directory name.
    """
    return f"devenv-{name}"


def get_sandbox_dir(name: str) -> Path:
    """Return the sandbox state directory for the given sandbox name."""
    return SANDBOXES_DIR / name


def load_profile_by_name(profile: str) -> ProfileConfig:
    """Load a bundled or user profile by name, exiting on failure.

    Tries bundled profiles first (shipped with the package), then
    user profiles from settings.profiles_dir. Calls SystemExit on
    missing or invalid profiles so callers do not need error handling.
    """
    profile_path = Path(profile)
    if profile_path.exists() and profile_path.suffix in (".yaml", ".yml"):
        config = load_profile(profile_path)
        console.print(f"[dim]Profile:[/dim] {profile_path}")
        return config

    try:
        config = get_bundled_profile(profile)
        console.print(f"[dim]Profile:[/dim] {profile}")
        return config
    except FileNotFoundError:
        console.print(f"[red]Profile not found:[/red] {profile}")
        console.print("Use 'devenv profiles list' to see available profiles")
        raise SystemExit(1) from None
