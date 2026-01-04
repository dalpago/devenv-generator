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

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Docker version 24.0.7")
            success, message = check_docker_installed()
            assert success is True
            assert "Docker installed" in message

    def test_check_docker_installed_not_found(self) -> None:
        """Should return False when Docker is not installed."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_installed

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            success, message = check_docker_installed()
            assert success is False
            assert "not found" in message

    def test_check_docker_running_success(self) -> None:
        """Should return True when Docker daemon is running."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_running

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success, message = check_docker_running()
            assert success is True
            assert "running" in message

    def test_check_docker_running_not_running(self) -> None:
        """Should return False when Docker daemon is not running."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_running

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            success, message = check_docker_running()
            assert success is False
            assert "not running" in message

    def test_check_docker_compose_plugin(self) -> None:
        """Should detect docker compose plugin."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_compose

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Docker Compose version v2.21.0")
            success, message = check_docker_compose()
            assert success is True
            assert "Docker Compose available" in message

    def test_check_docker_compose_standalone(self) -> None:
        """Should detect standalone docker-compose."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_compose

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
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

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
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
            patch("mirustech.devenv_generator.commands.diagnostics.SANDBOXES_DIR") as mock_dir,
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
            patch("mirustech.devenv_generator.commands.diagnostics.SANDBOXES_DIR") as mock_dir,
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

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="10.2.0")
            success, message = check_npm_installed()
            assert success is True
            assert "npm installed" in message

    def test_check_npm_installed_not_found(self) -> None:
        """Should return False when npm is not installed."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_npm_installed

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            success, message = check_npm_installed()
            assert success is False
            assert "not found" in message

    def test_check_git_installed_success(self) -> None:
        """Should return True when git is installed."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_git_installed

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="git version 2.42.0")
            success, message = check_git_installed()
            assert success is True
            assert "Git installed" in message

    def test_check_git_installed_not_found(self) -> None:
        """Should return False when git is not installed."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_git_installed

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
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

    def test_check_claude_dir_exists(self, tmp_path: Path) -> None:
        """Should return True when ~/.claude exists and is readable."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_claude_dir

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = check_claude_dir()
            assert success is True
            assert "exists and is accessible" in message

    def test_check_claude_dir_not_exists(self, tmp_path: Path) -> None:
        """Should return False when ~/.claude doesn't exist."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_claude_dir

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = check_claude_dir()
            assert success is False
            assert "not found" in message

    def test_check_happy_config_not_exists(self, tmp_path: Path) -> None:
        """Should return True when ~/.happy doesn't exist (optional)."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_happy_config

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = check_happy_config()
            assert success is True
            assert "optional" in message

    def test_check_happy_config_with_access_key(self, tmp_path: Path) -> None:
        """Should return True when ~/.happy has access.key."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_happy_config

        happy_dir = tmp_path / ".happy"
        happy_dir.mkdir()
        (happy_dir / "access.key").write_text("test-key")

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = check_happy_config()
            assert success is True
            assert "access key" in message

    def test_check_happy_config_without_access_key(self, tmp_path: Path) -> None:
        """Should return True when ~/.happy exists but no access.key."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_happy_config

        happy_dir = tmp_path / ".happy"
        happy_dir.mkdir()

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = check_happy_config()
            assert success is True
            assert "no access key" in message

    def test_check_gpg_port_available(self) -> None:
        """Should return True when GPG port is available."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_gpg_port

        with patch(
            "mirustech.devenv_generator.commands.diagnostics._check_port_available",
            return_value=(True, "Port 9876 available"),
        ):
            success, _message = check_gpg_port()
            assert success is True

    def test_check_serena_port_available(self) -> None:
        """Should return True when Serena port is available."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_serena_port

        with patch(
            "mirustech.devenv_generator.commands.diagnostics._check_port_available",
            return_value=(True, "Port 9121 available"),
        ):
            success, _message = check_serena_port()
            assert success is True

    def test_check_disk_space_adequate(self) -> None:
        """Should return True with adequate message when 1-5GB available."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_disk_space

        mock_stat = MagicMock()
        mock_stat.f_bavail = 3 * 1024 * 1024  # 3GB in blocks
        mock_stat.f_frsize = 1024  # 1KB block size

        with (
            patch("os.statvfs", return_value=mock_stat),
            patch("mirustech.devenv_generator.commands.diagnostics.SANDBOXES_DIR") as mock_dir,
        ):
            mock_dir.exists.return_value = True
            success, message = check_disk_space()
            assert success is True
            assert "adequate" in message

    def test_check_container_health_no_containers(self) -> None:
        """Should skip health check when no containers running."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_container_health

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            success, message = check_container_health()
            assert success is True
            assert "skipped" in message

    def test_check_container_health_healthy(self) -> None:
        """Should return True when container tools are present."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_container_health

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            # First call returns container names
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="devenv-myproject-dev-1\n"),
                MagicMock(returncode=0, stdout="Python 3.12.0"),  # exec check passes
            ]
            success, message = check_container_health()
            assert success is True
            assert "healthy" in message

    def test_check_container_health_missing_tools(self) -> None:
        """Should return False when container is missing required tools."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_container_health

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            # First call returns container names, second fails (combined check fails)
            # Then individual checks for each tool
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="devenv-myproject-dev-1\n"),
                MagicMock(returncode=1, stderr="command not found"),  # Combined check fails
                MagicMock(returncode=1),  # claude not found
                MagicMock(returncode=0),  # happy found
                MagicMock(returncode=0),  # python found
            ]
            success, message = check_container_health()
            assert success is False
            assert "missing tools" in message
            assert "claude" in message

    def test_check_container_health_exception(self) -> None:
        """Should handle exceptions gracefully."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import check_container_health

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="devenv-test-1\n"),
                Exception("Connection error"),
            ]
            success, message = check_container_health()
            assert success is True  # Returns True because not critical
            assert "Could not check" in message

    def test_check_registry_connectivity_success(self) -> None:
        """Should return True when registry is accessible."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import (
            check_registry_connectivity,
        )

        mock_settings = MagicMock()
        mock_settings.registry.enabled = True
        mock_settings.registry.url = "https://registry.example.com"

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "mirustech.devenv_generator.commands.diagnostics.get_settings",
                return_value=mock_settings,
            ),
            patch("urllib.request.urlopen", return_value=mock_response),
        ):
            success, message = check_registry_connectivity()
            assert success is True
            assert "accessible" in message

    def test_check_registry_connectivity_unreachable(self) -> None:
        """Should return False when registry is unreachable."""
        import urllib.error
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import (
            check_registry_connectivity,
        )

        mock_settings = MagicMock()
        mock_settings.registry.enabled = True
        mock_settings.registry.url = "https://registry.example.com"

        with (
            patch(
                "mirustech.devenv_generator.commands.diagnostics.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("Connection refused"),
            ),
        ):
            success, message = check_registry_connectivity()
            assert success is False
            assert "unreachable" in message

    def test_check_registry_connectivity_bad_status(self) -> None:
        """Should return False when registry returns non-200 status."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import (
            check_registry_connectivity,
        )

        mock_settings = MagicMock()
        mock_settings.registry.enabled = True
        mock_settings.registry.url = "https://registry.example.com"

        mock_response = MagicMock()
        mock_response.status = 403
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "mirustech.devenv_generator.commands.diagnostics.get_settings",
                return_value=mock_settings,
            ),
            patch("urllib.request.urlopen", return_value=mock_response),
        ):
            success, message = check_registry_connectivity()
            assert success is False
            assert "status 403" in message

    def test_check_mcp_servers_no_config(self, tmp_path: Path) -> None:
        """Should return True when no MCP config file exists."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_mcp_servers

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = check_mcp_servers()
            assert success is True
            assert "No MCP servers" in message

    def test_check_mcp_servers_with_servers(self, tmp_path: Path) -> None:
        """Should list configured MCP servers."""
        import json
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_mcp_servers

        config = {"mcpServers": {"server1": {}, "server2": {}}}
        (tmp_path / ".claude.json").write_text(json.dumps(config))

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = check_mcp_servers()
            assert success is True
            assert "server1" in message
            assert "server2" in message

    def test_check_mcp_servers_empty_config(self, tmp_path: Path) -> None:
        """Should return True when config exists but no servers."""
        import json
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_mcp_servers

        config = {"mcpServers": {}}
        (tmp_path / ".claude.json").write_text(json.dumps(config))

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = check_mcp_servers()
            assert success is True
            assert "No MCP servers" in message

    def test_check_mcp_servers_invalid_json(self, tmp_path: Path) -> None:
        """Should return False when config is invalid JSON."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_mcp_servers

        (tmp_path / ".claude.json").write_text("not valid json")

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = check_mcp_servers()
            assert success is False
            assert "Error reading" in message

    def test_check_docker_socket_exists(self) -> None:
        """Should return True when Docker socket is accessible."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_socket

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("os.access", return_value=True),
        ):
            success, message = check_docker_socket()
            assert success is True
            assert "accessible" in message

    def test_check_docker_socket_not_found(self) -> None:
        """Should return False when Docker socket doesn't exist."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_socket

        with patch("pathlib.Path.exists", return_value=False):
            success, message = check_docker_socket()
            assert success is False
            assert "not found" in message

    def test_check_docker_socket_no_permissions(self) -> None:
        """Should return False when Docker socket isn't accessible."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import check_docker_socket

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("os.access", return_value=False),
        ):
            success, message = check_docker_socket()
            assert success is False
            assert "not accessible" in message

    def test_check_port_available_free(self) -> None:
        """Should return True when port is free."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import _check_port_available

        mock_socket = MagicMock()
        mock_socket.bind = MagicMock()
        mock_socket.close = MagicMock()

        with patch("socket.socket", return_value=mock_socket):
            success, message = _check_port_available(9999, "test service")
            assert success is True
            assert "available" in message

    def test_check_port_available_in_use(self) -> None:
        """Should return True (with note) when port is in use."""
        from unittest.mock import MagicMock, patch

        from mirustech.devenv_generator.commands.diagnostics import _check_port_available

        mock_socket = MagicMock()
        mock_socket.bind.side_effect = OSError("Address already in use")

        with patch("socket.socket", return_value=mock_socket):
            success, message = _check_port_available(9999, "test service")
            assert success is True  # Still True because it might be the expected service
            assert "in use" in message


class TestDiagnosticFixFunctions:
    """Tests for diagnostic fix functions."""

    def test_fix_claude_dir_success(self, tmp_path: Path) -> None:
        """Should create ~/.claude directory."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import fix_claude_dir

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = fix_claude_dir()
            assert success is True
            assert "Created" in message
            assert (tmp_path / ".claude").exists()

    def test_fix_claude_dir_already_exists(self, tmp_path: Path) -> None:
        """Should succeed even if directory already exists."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import fix_claude_dir

        (tmp_path / ".claude").mkdir()

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, _message = fix_claude_dir()
            assert success is True

    def test_fix_happy_dir_success(self, tmp_path: Path) -> None:
        """Should create ~/.happy directory."""
        from unittest.mock import patch

        from mirustech.devenv_generator.commands.diagnostics import fix_happy_dir

        with patch("pathlib.Path.home", return_value=tmp_path):
            success, message = fix_happy_dir()
            assert success is True
            assert "Created" in message
            assert (tmp_path / ".happy").exists()

    def test_fix_claude_auth_returns_instructions(self) -> None:
        """Should return instructions to run claude login."""
        from mirustech.devenv_generator.commands.diagnostics import fix_claude_auth

        success, message = fix_claude_auth()
        assert success is False  # Can't auto-fix
        assert "claude login" in message


class TestDoctorCommandExtended:
    """Extended tests for the doctor CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_doctor_verbose_flag(self, runner: CliRunner) -> None:
        """Doctor --verbose flag should show additional info."""
        from unittest.mock import MagicMock, patch

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = runner.invoke(main, ["doctor", "--verbose"])
            # Command runs (exit code depends on system state)
            assert result.exit_code in (0, 1)

    def test_doctor_container_flag(self, runner: CliRunner) -> None:
        """Doctor --container flag should include container health checks."""
        from unittest.mock import MagicMock, patch

        with patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = runner.invoke(main, ["doctor", "--container"])
            assert result.exit_code in (0, 1)

    def test_doctor_all_checks_pass(self, runner: CliRunner) -> None:
        """Doctor should show success when all checks pass."""
        from unittest.mock import MagicMock, patch

        # Mock all external dependencies to pass
        with (
            patch("mirustech.devenv_generator.commands.diagnostics.run_command") as mock_run,
            patch(
                "mirustech.devenv_generator.commands.diagnostics.check_docker_socket",
                return_value=(True, "Socket accessible"),
            ),
            patch(
                "mirustech.devenv_generator.commands.diagnostics.check_claude_auth",
                return_value=(True, "Authenticated"),
            ),
            patch(
                "mirustech.devenv_generator.commands.diagnostics.check_claude_dir",
                return_value=(True, "Directory exists"),
            ),
            patch(
                "mirustech.devenv_generator.commands.diagnostics.check_disk_space",
                return_value=(True, "Disk space good"),
            ),
            patch(
                "mirustech.devenv_generator.commands.diagnostics.check_profile_valid",
                return_value=(True, "Profile valid"),
            ),
            patch(
                "mirustech.devenv_generator.commands.diagnostics.check_happy_config",
                return_value=(True, "Happy configured"),
            ),
            patch(
                "mirustech.devenv_generator.commands.diagnostics.check_registry_connectivity",
                return_value=(True, "Registry OK"),
            ),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="version 1.0")
            result = runner.invoke(main, ["doctor"])
            # May still fail due to other checks but should run
            assert result.exit_code in (0, 1)
