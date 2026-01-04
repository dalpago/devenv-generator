"""Tests for profiles command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main


class TestProfilesHelp:
    """Tests for the profiles help command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_profiles_help_shows_content(self, runner: CliRunner) -> None:
        """Help command shows profile guidance."""
        result = runner.invoke(main, ["profiles", "help"])
        assert result.exit_code == 0
        assert "What are profiles?" in result.output
        assert "Profile locations:" in result.output
        assert "Common workflows:" in result.output
        assert "Tips:" in result.output


class TestProfilesList:
    """Tests for the profiles list command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_profiles_list_shows_default(self, runner: CliRunner) -> None:
        """Should list the default bundled profile."""
        result = runner.invoke(main, ["profiles", "list"])
        assert result.exit_code == 0
        assert "default" in result.output
        assert "Available Profiles" in result.output

    def test_profiles_list_shows_user_profiles(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should list user profiles from config directory."""
        # Create a user profile
        user_profiles = tmp_path / ".config" / "devenv-generator" / "profiles"
        user_profiles.mkdir(parents=True)
        profile_file = user_profiles / "myprofile.yaml"
        profile_file.write_text(
            """
name: myprofile
description: My test profile
python:
  version: "3.12"
"""
        )

        # Run with mocked home directory
        result = runner.invoke(
            main, ["profiles", "list"], env={"HOME": str(tmp_path)}
        )
        assert result.exit_code == 0
        assert "myprofile" in result.output


class TestProfilesShow:
    """Tests for the profiles show command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_show_default_profile(self, runner: CliRunner) -> None:
        """Should show the default profile details."""
        result = runner.invoke(main, ["profiles", "show", "default"])
        assert result.exit_code == 0
        assert "default" in result.output
        assert "Python:" in result.output
        assert "uvx Tools:" in result.output
        assert "System Packages:" in result.output

    def test_show_without_argument_shows_default(self, runner: CliRunner) -> None:
        """Should show default profile when no argument given."""
        result = runner.invoke(main, ["profiles", "show"])
        assert result.exit_code == 0
        assert "default" in result.output

    def test_show_nonexistent_profile(self, runner: CliRunner) -> None:
        """Should error for nonexistent profile."""
        result = runner.invoke(main, ["profiles", "show", "nonexistent-xyz"])
        assert result.exit_code == 1
        assert "Profile not found" in result.output

    def test_show_user_profile(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should show user profile from config directory."""
        user_profiles = tmp_path / ".config" / "devenv-generator" / "profiles"
        user_profiles.mkdir(parents=True)
        profile_file = user_profiles / "custom.yaml"
        profile_file.write_text(
            """
name: custom
description: Custom profile for testing
python:
  version: "3.13"
uvx_tools:
  - ruff
  - mypy
system_packages:
  - git
node_packages:
  - "@anthropic-ai/claude-code"
"""
        )

        result = runner.invoke(
            main, ["profiles", "show", "custom"], env={"HOME": str(tmp_path)}
        )
        assert result.exit_code == 0
        assert "custom" in result.output
        assert "Custom profile for testing" in result.output


class TestProfilesCreate:
    """Tests for the profiles create command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_create_profile_from_default(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should create a new profile from default."""
        result = runner.invoke(
            main,
            ["profiles", "create", "newprofile"],
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 0
        assert "Created profile" in result.output

        # Verify file was created
        profile_path = (
            tmp_path / ".config" / "devenv-generator" / "profiles" / "newprofile.yaml"
        )
        assert profile_path.exists()

    def test_create_profile_already_exists(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should error if profile already exists."""
        user_profiles = tmp_path / ".config" / "devenv-generator" / "profiles"
        user_profiles.mkdir(parents=True)
        (user_profiles / "existing.yaml").write_text("name: existing\n")

        result = runner.invoke(
            main,
            ["profiles", "create", "existing"],
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 1
        assert "Profile already exists" in result.output

    def test_create_profile_from_nonexistent(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should error when source profile doesn't exist."""
        result = runner.invoke(
            main,
            ["profiles", "create", "new", "--from-profile", "nonexistent-xyz"],
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 1
        assert "Source profile not found" in result.output

    def test_create_profile_custom_output(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should create profile at custom output path."""
        output_path = tmp_path / "custom" / "myprofile.yaml"

        result = runner.invoke(
            main,
            ["profiles", "create", "myprofile", "--output", str(output_path)],
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 0
        assert output_path.exists()


class TestProfilesPath:
    """Tests for the profiles path command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_path_bundled_profile(self, runner: CliRunner) -> None:
        """Should show path for bundled profile."""
        result = runner.invoke(main, ["profiles", "path", "default"])
        assert result.exit_code == 0
        assert "bundled profile" in result.output

    def test_path_user_profile(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should show path for user profile."""
        user_profiles = tmp_path / ".config" / "devenv-generator" / "profiles"
        user_profiles.mkdir(parents=True)
        (user_profiles / "myprofile.yaml").write_text("name: myprofile\n")

        result = runner.invoke(
            main,
            ["profiles", "path", "myprofile"],
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 0
        assert "user profile" in result.output
        # Path may be split across lines due to terminal width
        assert "myprofile.yaml" in result.output

    def test_path_nonexistent_profile(self, runner: CliRunner) -> None:
        """Should error for nonexistent profile."""
        result = runner.invoke(main, ["profiles", "path", "nonexistent-xyz"])
        assert result.exit_code == 1
        assert "Profile not found" in result.output

    def test_path_exists_only_success(self, runner: CliRunner) -> None:
        """Should exit 0 when profile exists with --exists-only."""
        result = runner.invoke(main, ["profiles", "path", "default", "--exists-only"])
        assert result.exit_code == 0

    def test_path_exists_only_failure(self, runner: CliRunner) -> None:
        """Should exit 1 when profile doesn't exist with --exists-only."""
        result = runner.invoke(
            main, ["profiles", "path", "nonexistent-xyz", "--exists-only"]
        )
        assert result.exit_code == 1


class TestProfilesDelete:
    """Tests for the profiles delete command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_delete_user_profile_with_force(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should delete user profile with --force flag."""
        user_profiles = tmp_path / ".config" / "devenv-generator" / "profiles"
        user_profiles.mkdir(parents=True)
        profile_path = user_profiles / "deleteme.yaml"
        profile_path.write_text("name: deleteme\n")

        result = runner.invoke(
            main,
            ["profiles", "delete", "deleteme", "--force"],
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 0
        assert "Deleted profile" in result.output
        assert not profile_path.exists()

    def test_delete_bundled_profile_fails(self, runner: CliRunner) -> None:
        """Should not allow deleting bundled profiles."""
        result = runner.invoke(main, ["profiles", "delete", "default", "--force"])
        assert result.exit_code == 1
        assert "Cannot delete bundled profile" in result.output

    def test_delete_nonexistent_profile(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should error for nonexistent profile."""
        result = runner.invoke(
            main,
            ["profiles", "delete", "nonexistent-xyz", "--force"],
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 1
        assert "Profile not found" in result.output

    def test_delete_without_force_cancelled(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should cancel deletion without confirmation."""
        user_profiles = tmp_path / ".config" / "devenv-generator" / "profiles"
        user_profiles.mkdir(parents=True)
        profile_path = user_profiles / "keepme.yaml"
        profile_path.write_text("name: keepme\n")

        # Simulate user saying "n" to confirmation
        result = runner.invoke(
            main,
            ["profiles", "delete", "keepme"],
            input="n\n",
            env={"HOME": str(tmp_path)},
        )
        # File should still exist
        assert profile_path.exists()
        assert "Cancelled" in result.output
