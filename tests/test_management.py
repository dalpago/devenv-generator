"""Tests for management commands module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main
from mirustech.devenv_generator.commands.management import (
    _format_size,
    _get_dir_size,
    _get_image_size,
    _is_sandbox_running,
    _list_sandboxes,
)


class TestFormatSize:
    """Tests for _format_size function."""

    def test_bytes(self) -> None:
        """Should format bytes."""
        assert _format_size(100) == "100.0B"

    def test_kilobytes(self) -> None:
        """Should format kilobytes."""
        assert _format_size(1024) == "1.0KB"
        assert _format_size(2048) == "2.0KB"

    def test_megabytes(self) -> None:
        """Should format megabytes."""
        assert _format_size(1024 * 1024) == "1.0MB"
        assert _format_size(5 * 1024 * 1024) == "5.0MB"

    def test_gigabytes(self) -> None:
        """Should format gigabytes."""
        assert _format_size(1024 * 1024 * 1024) == "1.0GB"

    def test_terabytes(self) -> None:
        """Should format terabytes."""
        assert _format_size(1024 * 1024 * 1024 * 1024) == "1.0TB"


class TestGetDirSize:
    """Tests for _get_dir_size function."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Should return 0 for empty directory."""
        assert _get_dir_size(tmp_path) == 0

    def test_directory_with_files(self, tmp_path: Path) -> None:
        """Should return total size of files."""
        (tmp_path / "file1.txt").write_text("hello")  # 5 bytes
        (tmp_path / "file2.txt").write_text("world!")  # 6 bytes

        size = _get_dir_size(tmp_path)
        assert size == 11

    def test_recursive_directory(self, tmp_path: Path) -> None:
        """Should include files in subdirectories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "file1.txt").write_text("abc")  # 3 bytes
        (subdir / "file2.txt").write_text("defgh")  # 5 bytes

        size = _get_dir_size(tmp_path)
        assert size == 8


class TestIsSandboxRunning:
    """Tests for _is_sandbox_running function."""

    def test_returns_true_when_container_running(self, tmp_path: Path) -> None:
        """Should return True when docker compose returns container IDs."""
        with patch(
            "mirustech.devenv_generator.commands.management.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(stdout="container123\n")
            result = _is_sandbox_running("myproject", tmp_path)
            assert result is True

    def test_returns_false_when_no_containers(self, tmp_path: Path) -> None:
        """Should return False when no containers running."""
        with patch(
            "mirustech.devenv_generator.commands.management.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(stdout="")
            result = _is_sandbox_running("myproject", tmp_path)
            assert result is False

    def test_returns_false_on_exception(self, tmp_path: Path) -> None:
        """Should return False on any exception."""
        with patch(
            "mirustech.devenv_generator.commands.management.run_command"
        ) as mock_run:
            mock_run.side_effect = RuntimeError("Docker not available")
            result = _is_sandbox_running("myproject", tmp_path)
            assert result is False


class TestListSandboxes:
    """Tests for _list_sandboxes function."""

    def test_returns_empty_when_dir_missing(self, tmp_path: Path) -> None:
        """Should return empty list when sandboxes dir doesn't exist."""
        with patch(
            "mirustech.devenv_generator.commands.management.SANDBOXES_DIR",
            tmp_path / "nonexistent",
        ):
            result = _list_sandboxes()
            assert result == []

    def test_returns_sandboxes_with_compose_file(self, tmp_path: Path) -> None:
        """Should only include directories with docker-compose.yml."""
        sandboxes_dir = tmp_path / "sandboxes"
        sandboxes_dir.mkdir()

        # Valid sandbox
        valid = sandboxes_dir / "valid-sandbox"
        valid.mkdir()
        (valid / "docker-compose.yml").write_text("services:\n  dev:\n")

        # Invalid - no compose file
        invalid = sandboxes_dir / "no-compose"
        invalid.mkdir()

        with (
            patch(
                "mirustech.devenv_generator.commands.management.SANDBOXES_DIR",
                sandboxes_dir,
            ),
            patch(
                "mirustech.devenv_generator.commands.management._is_sandbox_running",
                return_value=False,
            ),
        ):
            result = _list_sandboxes()
            assert len(result) == 1
            assert result[0][0] == "valid-sandbox"


class TestGetImageSize:
    """Tests for _get_image_size function."""

    def test_returns_size_on_success(self) -> None:
        """Should return image size as int."""
        with patch(
            "mirustech.devenv_generator.commands.management.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="123456789\n")
            result = _get_image_size("myimage:latest")
            assert result == 123456789

    def test_returns_none_on_failure(self) -> None:
        """Should return None when docker command fails."""
        with patch(
            "mirustech.devenv_generator.commands.management.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = _get_image_size("nonexistent:latest")
            assert result is None

    def test_returns_none_on_invalid_output(self) -> None:
        """Should return None when output isn't a number."""
        with patch(
            "mirustech.devenv_generator.commands.management.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="not a number\n")
            result = _get_image_size("myimage:latest")
            assert result is None


class TestStatusCommand:
    """Tests for the status CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_status_shows_no_sandboxes(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should show message when no sandboxes exist."""
        with patch(
            "mirustech.devenv_generator.commands.management.SANDBOXES_DIR",
            tmp_path / "nonexistent",
        ):
            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0
            assert "No sandboxes found" in result.output

    def test_status_help(self, runner: CliRunner) -> None:
        """Should show help for status command."""
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0
        assert "List all sandboxes" in result.output


class TestRemoveCommand:
    """Tests for the rm CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_rm_help(self, runner: CliRunner) -> None:
        """Should show help for rm command."""
        result = runner.invoke(main, ["rm", "--help"])
        assert result.exit_code == 0
        assert "Remove a sandbox" in result.output

    def test_rm_nonexistent_sandbox(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when sandbox doesn't exist."""
        with patch(
            "mirustech.devenv_generator.commands.management.SANDBOXES_DIR",
            tmp_path,
        ):
            result = runner.invoke(main, ["rm", "nonexistent"])
            assert result.exit_code == 1
            assert "Sandbox not found" in result.output


class TestCleanCommand:
    """Tests for the clean CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_clean_help(self, runner: CliRunner) -> None:
        """Should show help for clean command."""
        result = runner.invoke(main, ["clean", "--help"])
        assert result.exit_code == 0
        assert "Clean up unused sandboxes" in result.output
        assert "--stopped" in result.output
        assert "--images" in result.output
        assert "--all" in result.output
        assert "--dry-run" in result.output

    def test_clean_shows_status(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should show cleanup status without flags."""
        with (
            patch(
                "mirustech.devenv_generator.commands.management.SANDBOXES_DIR",
                tmp_path,
            ),
            patch(
                "mirustech.devenv_generator.commands.management.run_command"
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = runner.invoke(main, ["clean"])
            assert result.exit_code == 0
            assert "Available for cleanup" in result.output
