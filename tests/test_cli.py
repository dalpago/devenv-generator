"""Tests for CLI commands and helper functions."""

from pathlib import Path

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


@pytest.mark.integration
class TestCleanCommand:
    """Tests for the clean command (requires Docker)."""

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


# Port Parsing Tests


def test_parse_port_spec_simple() -> None:
    """Parse simple port spec (8000)."""
    from mirustech.devenv_generator.commands.lifecycle import _parse_port_spec

    port = _parse_port_spec("8000")
    assert port.container == 8000
    assert port.host_port == 8000
    assert port.protocol == "tcp"


def test_parse_port_spec_host_container() -> None:
    """Parse host:container spec (8080:3000)."""
    from mirustech.devenv_generator.commands.lifecycle import _parse_port_spec

    port = _parse_port_spec("8080:3000")
    assert port.container == 3000
    assert port.host_port == 8080
    assert port.protocol == "tcp"


def test_parse_port_spec_with_protocol() -> None:
    """Parse spec with protocol (5432/tcp)."""
    from mirustech.devenv_generator.commands.lifecycle import _parse_port_spec

    port = _parse_port_spec("5432/tcp")
    assert port.container == 5432
    assert port.host_port == 5432
    assert port.protocol == "tcp"


def test_parse_port_spec_udp() -> None:
    """Parse UDP port spec (8080:3000/udp)."""
    from mirustech.devenv_generator.commands.lifecycle import _parse_port_spec

    port = _parse_port_spec("8080:3000/udp")
    assert port.container == 3000
    assert port.host_port == 8080
    assert port.protocol == "udp"


def test_parse_port_spec_invalid_protocol() -> None:
    """Invalid protocol exits with error."""
    from mirustech.devenv_generator.commands.lifecycle import _parse_port_spec

    with pytest.raises(SystemExit):
        _parse_port_spec("8000/sctp")


def test_parse_port_spec_invalid_format() -> None:
    """Invalid port format exits with error."""
    from mirustech.devenv_generator.commands.lifecycle import _parse_port_spec

    with pytest.raises(SystemExit):
        _parse_port_spec("not-a-port")

    with pytest.raises(SystemExit):
        _parse_port_spec("abc:8000")


# Port Conflict Detection Tests


def test_check_port_conflicts_no_conflict() -> None:
    """No conflict when port is free."""
    from unittest.mock import MagicMock, patch

    from mirustech.devenv_generator.commands.lifecycle import _check_port_conflicts
    from mirustech.devenv_generator.models import PortConfig

    with patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run:
        # lsof returns non-zero when port is free
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        ports = [PortConfig(container=8000, host=8000)]
        _check_port_conflicts(ports, "test-sandbox")

        mock_run.assert_called_once()


def test_check_port_conflicts_with_conflict() -> None:
    """SystemExit when port is in use."""
    from unittest.mock import MagicMock, patch

    from mirustech.devenv_generator.commands.lifecycle import _check_port_conflicts
    from mirustech.devenv_generator.models import PortConfig

    with patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run:
        # lsof returns zero when port is in use
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "python  12345 user   TCP *:8000 (LISTEN)"
        mock_run.return_value = mock_result

        ports = [PortConfig(container=8000, host=8000)]

        with pytest.raises(SystemExit):
            _check_port_conflicts(ports, "test-sandbox")


def test_check_port_conflicts_multiple_ports() -> None:
    """Checks all ports in list."""
    from unittest.mock import MagicMock, patch

    from mirustech.devenv_generator.commands.lifecycle import _check_port_conflicts
    from mirustech.devenv_generator.models import PortConfig

    with patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        ports = [
            PortConfig(container=8000, host=8000),
            PortConfig(container=5173, host=5173),
            PortConfig(container=3000, host=3000),
        ]
        _check_port_conflicts(ports, "test-sandbox")

        assert mock_run.call_count == 3


# CLI Help Text Test


class TestRunCommandPorts:
    """Tests for devenv run with port flags."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_run_help_shows_port_options(self, runner: CliRunner) -> None:
        """Help text includes port options."""
        result = runner.invoke(main, ["run", "--help"])
        assert "--expose-port" in result.output
        assert "--no-ports" in result.output


class TestHelpCommand:
    """Tests for the help command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_help_shows_usage_guide(self, runner: CliRunner) -> None:
        """Help command shows comprehensive guide."""
        result = runner.invoke(main, ["help"])
        assert result.exit_code == 0
        assert "Quick Start" in result.output
        assert "Common Commands" in result.output

    def test_main_help_flag(self, runner: CliRunner) -> None:
        """--help flag shows main help."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "devenv" in result.output.lower()


class TestVersionCommand:
    """Tests for version output."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_version_flag(self, runner: CliRunner) -> None:
        """--version shows version."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        # Version format: "devenv, version X.Y.Z"
        assert "version" in result.output.lower()


class TestProfilesCommand:
    """Tests for profiles commands."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_profiles_list(self, runner: CliRunner) -> None:
        """List available profiles."""
        result = runner.invoke(main, ["profiles", "list"])
        assert result.exit_code == 0
        assert "default" in result.output

    def test_profiles_show(self, runner: CliRunner) -> None:
        """Show profile details."""
        result = runner.invoke(main, ["profiles", "show", "default"])
        assert result.exit_code == 0
        assert "default" in result.output
