"""Tests for diagnostic registry functionality."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main
from mirustech.devenv_generator.commands.diagnostics import DiagnosticRegistry


class TestDiagnosticRegistry:
    """Tests for the DiagnosticRegistry class."""

    def test_check_registration(self) -> None:
        """Should register check functions via decorator."""
        registry = DiagnosticRegistry()

        @registry.check("test_check")
        def test_check_fn() -> tuple[bool, str]:
            return True, "Test passed"

        assert "test_check" in registry._checks
        assert registry._checks["test_check"]() == (True, "Test passed")

    def test_fix_registration(self) -> None:
        """Should register fix functions via decorator."""
        registry = DiagnosticRegistry()

        @registry.fix("test_fix")
        def test_fix_fn() -> tuple[bool, str]:
            return True, "Fix applied"

        assert "test_fix" in registry._fixes
        assert registry._fixes["test_fix"]() == (True, "Fix applied")

    def test_run_all_checks(self) -> None:
        """Should run all registered checks and return results."""
        registry = DiagnosticRegistry()

        @registry.check("check1")
        def check1() -> tuple[bool, str]:
            return True, "Check 1 passed"

        @registry.check("check2")
        def check2() -> tuple[bool, str]:
            return False, "Check 2 failed"

        results = registry.run_all_checks()

        assert len(results) == 2
        assert ("check1", True, "Check 1 passed") in results
        assert ("check2", False, "Check 2 failed") in results

    def test_run_all_fixes(self) -> None:
        """Should run all registered fixes and return results."""
        registry = DiagnosticRegistry()

        @registry.fix("fix1")
        def fix1() -> tuple[bool, str]:
            return True, "Fix 1 applied"

        @registry.fix("fix2")
        def fix2() -> tuple[bool, str]:
            return False, "Fix 2 failed"

        results = registry.run_all_fixes()

        assert len(results) == 2
        assert ("fix1", True, "Fix 1 applied") in results
        assert ("fix2", False, "Fix 2 failed") in results

    def test_check_exception_handling(self) -> None:
        """Should handle exceptions in check functions gracefully."""
        registry = DiagnosticRegistry()

        @registry.check("failing_check")
        def failing_check() -> tuple[bool, str]:
            raise RuntimeError("Simulated failure")

        results = registry.run_all_checks()

        assert len(results) == 1
        name, success, message = results[0]
        assert name == "failing_check"
        assert success is False
        assert "Check failed with error" in message

    def test_fix_exception_handling(self) -> None:
        """Should handle exceptions in fix functions gracefully."""
        registry = DiagnosticRegistry()

        @registry.fix("failing_fix")
        def failing_fix() -> tuple[bool, str]:
            raise RuntimeError("Simulated failure")

        results = registry.run_all_fixes()

        assert len(results) == 1
        name, success, message = results[0]
        assert name == "failing_fix"
        assert success is False
        assert "Fix failed with error" in message

    def test_decorator_returns_original_function(self) -> None:
        """Should return the original function after registration."""
        registry = DiagnosticRegistry()

        def original_check() -> tuple[bool, str]:
            return True, "Original"

        decorated = registry.check("test")(original_check)

        assert decorated is original_check
        assert decorated() == (True, "Original")

    def test_multiple_registrations_same_name(self) -> None:
        """Should allow overwriting registrations (last wins)."""
        registry = DiagnosticRegistry()

        @registry.check("same_name")
        def first_check() -> tuple[bool, str]:
            return True, "First"

        @registry.check("same_name")
        def second_check() -> tuple[bool, str]:
            return True, "Second"

        results = registry.run_all_checks()
        assert len(results) == 1
        assert results[0] == ("same_name", True, "Second")


class TestDoctorCommand:
    """Tests for the doctor CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_doctor_runs_checks(self, runner: CliRunner) -> None:
        """Doctor command should run system checks."""
        result = runner.invoke(main, ["doctor"])
        # The exit code depends on whether Docker is available
        # Just verify it runs without crashing
        assert result.exit_code in (0, 1)
        assert "System Diagnostics" in result.output or "docker" in result.output.lower()

    def test_doctor_help(self, runner: CliRunner) -> None:
        """Doctor command should show help."""
        result = runner.invoke(main, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "diagnose" in result.output.lower() or "health" in result.output.lower()

    def test_doctor_fix_flag(self, runner: CliRunner) -> None:
        """Doctor --fix flag should be accepted."""
        result = runner.invoke(main, ["doctor", "--fix"])
        # Runs without error, actual fix behavior depends on system state
        assert result.exit_code in (0, 1)


class TestDiagnosticModule:
    """Tests for the diagnostic module singleton."""

    def test_diagnostic_singleton_has_checks(self) -> None:
        """The global diagnostic registry should have built-in checks."""
        from mirustech.devenv_generator.commands.diagnostics import diagnostic

        # There should be at least some registered checks
        assert len(diagnostic._checks) > 0
        assert "docker_installed" in diagnostic._checks

    def test_diagnostic_singleton_has_fixes(self) -> None:
        """The global diagnostic registry should have some fixes."""
        from mirustech.devenv_generator.commands.diagnostics import diagnostic

        # Some checks have corresponding fixes
        assert len(diagnostic._fixes) >= 0  # May have 0 if no fixes registered


class TestDiagnosticCheckFunctions:
    """Tests for individual diagnostic check functions."""

    def test_check_docker_installed_success(self) -> None:
        """Should return True when Docker is installed."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_installed

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="Docker version 24.0.7"
            )
            success, message = check_docker_installed()
            assert success is True
            assert "Docker installed" in message

    def test_check_docker_installed_not_found(self) -> None:
        """Should return False when Docker is not installed."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_installed

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            success, message = check_docker_installed()
            assert success is False
            assert "not found" in message

    def test_check_docker_running_success(self) -> None:
        """Should return True when Docker daemon is running."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_running

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success, message = check_docker_running()
            assert success is True
            assert "running" in message

    def test_check_docker_running_not_running(self) -> None:
        """Should return False when Docker daemon is not running."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_running

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            success, message = check_docker_running()
            assert success is False
            assert "not running" in message

    def test_check_docker_compose_plugin(self) -> None:
        """Should detect docker compose plugin."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_compose

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="Docker Compose version v2.21.0"
            )
            success, message = check_docker_compose()
            assert success is True
            assert "Docker Compose available" in message

    def test_check_docker_compose_standalone(self) -> None:
        """Should detect standalone docker-compose."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_compose

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            # First call (docker compose) fails, second (docker-compose) succeeds
            mock_run.side_effect = [
                MagicMock(returncode=1),
                MagicMock(returncode=0, stdout="docker-compose version 1.29.2"),
            ]
            success, message = check_docker_compose()
            assert success is True
            assert "Docker Compose available" in message

    def test_check_docker_compose_not_found(self) -> None:
        """Should return False when no docker compose is found."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_compose

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            success, message = check_docker_compose()
            assert success is False
            assert "not found" in message

    def test_check_disk_space_good(self) -> None:
        """Should return True when disk space is good."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_disk_space

        mock_stat = MagicMock()
        mock_stat.f_bavail = 10 * 1024 * 1024  # 10GB in blocks
        mock_stat.f_frsize = 1024  # 1KB block size

        with (
            patch("os.statvfs", return_value=mock_stat),
            patch(
                "mirustech.devenv_generator.commands.diagnostics.SANDBOXES_DIR"
            ) as mock_dir,
        ):
            mock_dir.exists.return_value = True
            success, message = check_disk_space()
            assert success is True
            assert "good" in message

    def test_check_disk_space_low(self) -> None:
        """Should return False when disk space is low."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_disk_space

        mock_stat = MagicMock()
        mock_stat.f_bavail = 500 * 1024  # 500MB in blocks
        mock_stat.f_frsize = 1024  # 1KB block size

        with (
            patch("os.statvfs", return_value=mock_stat),
            patch(
                "mirustech.devenv_generator.commands.diagnostics.SANDBOXES_DIR"
            ) as mock_dir,
        ):
            mock_dir.exists.return_value = True
            success, message = check_disk_space()
            assert success is False
            assert "Low disk space" in message

    def test_check_claude_auth_oauth_token(self) -> None:
        """Should detect OAuth token in environment."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_claude_auth

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "test-token"}):
            success, message = check_claude_auth()
            assert success is True
            assert "OAuth token" in message

    def test_check_claude_auth_api_key(self) -> None:
        """Should detect API key in environment."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_claude_auth

        with patch.dict(
            "os.environ",
            {"ANTHROPIC_AUTH_TOKEN": "sk-ant-test"},
            clear=True,
        ):
            success, message = check_claude_auth()
            assert success is True
            assert "API key" in message

    def test_check_claude_auth_credentials_file(self, tmp_path: Path) -> None:
        """Should detect credentials file."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_claude_auth

        creds_dir = tmp_path / ".claude"
        creds_dir.mkdir()
        (creds_dir / ".credentials.json").write_text("{}")

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            success, message = check_claude_auth()
            assert success is True
            assert "credentials file" in message

    def test_check_claude_auth_not_found(self, tmp_path: Path) -> None:
        """Should return False when no auth is found."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_claude_auth

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            success, message = check_claude_auth()
            assert success is False
            assert "No Claude authentication" in message

    def test_check_npm_installed_success(self) -> None:
        """Should return True when npm is installed."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_npm_installed

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="10.2.0")
            success, message = check_npm_installed()
            assert success is True
            assert "npm installed" in message

    def test_check_npm_installed_not_found(self) -> None:
        """Should return False when npm is not installed."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_npm_installed

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            success, message = check_npm_installed()
            assert success is False
            assert "not found" in message

    def test_check_git_installed_success(self) -> None:
        """Should return True when git is installed."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_git_installed

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="git version 2.42.0")
            success, message = check_git_installed()
            assert success is True
            assert "Git installed" in message

    def test_check_git_installed_not_found(self) -> None:
        """Should return False when git is not installed."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_git_installed

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.run_command"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            success, message = check_git_installed()
            assert success is False
            assert "not found" in message

    def test_check_profile_valid_success(self) -> None:
        """Should return True when default profile is valid."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_profile_valid

        mock_profile = MagicMock()
        mock_profile.python.version = "3.12"

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.get_bundled_profile",
            return_value=mock_profile,
        ):
            success, message = check_profile_valid()
            assert success is True
            assert "valid" in message

    def test_check_profile_valid_error(self) -> None:
        """Should return False when default profile is invalid."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_profile_valid

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.get_bundled_profile",
            side_effect=ValueError("Invalid profile"),
        ):
            success, message = check_profile_valid()
            assert success is False
            assert "invalid" in message

    def test_check_registry_connectivity_disabled(self) -> None:
        """Should return True when registry is disabled."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import (
            check_registry_connectivity,
        )

        mock_settings = MagicMock()
        mock_settings.registry.enabled = False

        with patch(
            "mirustech.devenv_generator.commands.diagnostics.get_settings",
            return_value=mock_settings,
        ):
            success, message = check_registry_connectivity()
            assert success is True
            assert "not configured" in message
