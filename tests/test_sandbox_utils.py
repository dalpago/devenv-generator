"""Tests for shared sandbox utility functions."""

import pytest

from mirustech.devenv_generator.models import ProfileConfig
from mirustech.devenv_generator.utils.sandbox import (
    SANDBOXES_DIR,
    compose_project_name,
    get_sandbox_dir,
    load_profile_by_name,
)


def test_compose_project_name_prefixes_devenv() -> None:
    """compose_project_name should prefix the sandbox name with 'devenv-'."""
    assert compose_project_name("foo") == "devenv-foo"


def test_get_sandbox_dir_returns_expected_path() -> None:
    """get_sandbox_dir should return SANDBOXES_DIR / name."""
    expected = SANDBOXES_DIR / "foo"
    assert get_sandbox_dir("foo") == expected


def test_load_profile_by_name_default_returns_valid_config() -> None:
    """load_profile_by_name('default') should return a valid ProfileConfig."""
    config = load_profile_by_name("default")
    assert isinstance(config, ProfileConfig)


def test_load_profile_by_name_nonexistent_raises_system_exit() -> None:
    """load_profile_by_name with a nonexistent profile should raise SystemExit."""
    with pytest.raises(SystemExit):
        load_profile_by_name("nonexistent-profile-xyz")
