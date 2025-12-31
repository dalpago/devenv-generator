"""Tests for CLI commands and helper functions."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main
from mirustech.devenv_generator.commands.management import _format_size, _get_dir_size


class TestHelperFunctions:
    """Tests for CLI helper functions."""

    def test_format_size_bytes(self) -> None:
        """Should format bytes correctly."""
        assert _format_size(500) == "500.0B"

    def test_format_size_kilobytes(self) -> None:
        """Should format kilobytes correctly."""
        assert _format_size(1024) == "1.0KB"
        assert _format_size(1536) == "1.5KB"

    def test_format_size_megabytes(self) -> None:
        """Should format megabytes correctly."""
        assert _format_size(1024 * 1024) == "1.0MB"
        assert _format_size(1024 * 1024 * 5) == "5.0MB"

    def test_format_size_gigabytes(self) -> None:
        """Should format gigabytes correctly."""
        assert _format_size(1024 * 1024 * 1024) == "1.0GB"

    def test_get_dir_size_empty(self, tmp_path: Path) -> None:
        """Should return 0 for empty directory."""
        assert _get_dir_size(tmp_path) == 0

    def test_get_dir_size_with_files(self, tmp_path: Path) -> None:
        """Should calculate total size of files."""
        # Create some test files
        (tmp_path / "file1.txt").write_text("hello")  # 5 bytes
        (tmp_path / "file2.txt").write_text("world!")  # 6 bytes

        size = _get_dir_size(tmp_path)
        assert size == 11

    def test_get_dir_size_recursive(self, tmp_path: Path) -> None:
        """Should include files in subdirectories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested content")  # 14 bytes

        size = _get_dir_size(tmp_path)
        assert size == 14


class TestCompletionsCommand:
    """Tests for the completions command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_bash_completions(self, runner: CliRunner) -> None:
        """Should generate bash completion script."""
        result = runner.invoke(main, ["completions", "bash"])

        assert result.exit_code == 0
        assert "_devenv_completion" in result.output
        assert "complete -F" in result.output

    def test_zsh_completions(self, runner: CliRunner) -> None:
        """Should generate zsh completion script."""
        result = runner.invoke(main, ["completions", "zsh"])

        assert result.exit_code == 0
        assert "#compdef devenv" in result.output
        assert "_devenv()" in result.output
        assert "compdef _devenv devenv" in result.output

    def test_fish_completions(self, runner: CliRunner) -> None:
        """Should generate fish completion script."""
        result = runner.invoke(main, ["completions", "fish"])

        assert result.exit_code == 0
        assert "__fish_devenv_sandbox_names" in result.output
        assert "complete -c devenv" in result.output

    def test_invalid_shell(self, runner: CliRunner) -> None:
        """Should reject invalid shell names."""
        result = runner.invoke(main, ["completions", "powershell"])

        assert result.exit_code != 0


class TestCleanCommand:
    """Tests for the clean command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_clean_shows_status_by_default(self, runner: CliRunner) -> None:
        """Should show cleanup status when no flags provided."""
        result = runner.invoke(main, ["clean"])

        assert result.exit_code == 0
        assert "Available for cleanup" in result.output

    def test_clean_dry_run(self, runner: CliRunner) -> None:
        """Should support dry-run mode."""
        result = runner.invoke(main, ["clean", "--dry-run", "--all"])

        assert result.exit_code == 0
        assert "Dry run" in result.output or "Nothing to clean" in result.output


class TestStatusCommand:
    """Tests for the status command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_status_no_sandboxes(self, runner: CliRunner) -> None:
        """Should show message when no sandboxes exist."""
        result = runner.invoke(main, ["status"])

        # Either shows sandboxes or "No sandboxes found"
        assert result.exit_code == 0
