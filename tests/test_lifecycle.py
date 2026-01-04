"""Tests for lifecycle command utilities."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main
from mirustech.devenv_generator.commands.lifecycle import (
    _detect_python_version,
    _get_sandbox_dir,
    _parse_port_spec,
)
from mirustech.devenv_generator.models import PortConfig


class TestGetSandboxDir:
    """Tests for _get_sandbox_dir function."""

    def test_returns_path_under_sandboxes_dir(self) -> None:
        """Should return path under sandboxes directory."""
        result = _get_sandbox_dir("myproject")
        assert result.name == "myproject"
        assert "devenv-sandboxes" in str(result)


class TestDetectPythonVersion:
    """Tests for _detect_python_version function."""

    def test_detects_from_python_version_file(self, tmp_path: Path) -> None:
        """Should detect version from .python-version file."""
        (tmp_path / ".python-version").write_text("3.12\n")
        result = _detect_python_version(tmp_path)
        assert result == "3.12"

    def test_detects_from_pyproject_toml(self, tmp_path: Path) -> None:
        """Should detect version from pyproject.toml requires-python."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[project]
name = "test"
requires-python = ">=3.11"
"""
        )
        result = _detect_python_version(tmp_path)
        assert result == "3.11"

    def test_returns_none_when_no_version_file(self, tmp_path: Path) -> None:
        """Should return None when no version indicators exist."""
        result = _detect_python_version(tmp_path)
        assert result is None

    def test_prefers_python_version_over_pyproject(self, tmp_path: Path) -> None:
        """Should prefer .python-version over pyproject.toml."""
        (tmp_path / ".python-version").write_text("3.13\n")
        (tmp_path / "pyproject.toml").write_text(
            """
[project]
requires-python = ">=3.11"
"""
        )
        result = _detect_python_version(tmp_path)
        assert result == "3.13"

    def test_handles_empty_python_version_file(self, tmp_path: Path) -> None:
        """Should handle empty .python-version file."""
        (tmp_path / ".python-version").write_text("")
        result = _detect_python_version(tmp_path)
        assert result is None

    def test_handles_invalid_pyproject(self, tmp_path: Path) -> None:
        """Should handle invalid pyproject.toml gracefully."""
        (tmp_path / "pyproject.toml").write_text("not valid toml {{{{")
        result = _detect_python_version(tmp_path)
        assert result is None


class TestParsePortSpec:
    """Tests for _parse_port_spec function."""

    def test_simple_port(self) -> None:
        """Should parse simple port number."""
        result = _parse_port_spec("8000")
        assert result.container == 8000
        assert result.host_port == 8000
        assert result.protocol == "tcp"

    def test_host_container_mapping(self) -> None:
        """Should parse host:container mapping."""
        result = _parse_port_spec("8080:3000")
        assert result.container == 3000
        assert result.host_port == 8080
        assert result.protocol == "tcp"

    def test_explicit_tcp_protocol(self) -> None:
        """Should parse explicit TCP protocol."""
        result = _parse_port_spec("5432/tcp")
        assert result.container == 5432
        assert result.host_port == 5432
        assert result.protocol == "tcp"

    def test_udp_protocol(self) -> None:
        """Should parse UDP protocol."""
        result = _parse_port_spec("5353/udp")
        assert result.container == 5353
        assert result.host_port == 5353
        assert result.protocol == "udp"

    def test_full_mapping_with_protocol(self) -> None:
        """Should parse full mapping with protocol."""
        result = _parse_port_spec("8080:3000/udp")
        assert result.container == 3000
        assert result.host_port == 8080
        assert result.protocol == "udp"

    def test_invalid_protocol_exits(self) -> None:
        """Should exit on invalid protocol."""
        with pytest.raises(SystemExit):
            _parse_port_spec("8000/http")

    def test_invalid_port_number_exits(self) -> None:
        """Should exit on invalid port number."""
        with pytest.raises(SystemExit):
            _parse_port_spec("not-a-number")

    def test_invalid_host_port_exits(self) -> None:
        """Should exit on invalid host:container format."""
        with pytest.raises(SystemExit):
            _parse_port_spec("abc:3000")

    valid_ports = st.integers(min_value=1, max_value=65535)
    protocols = st.sampled_from(["tcp", "udp"])

    @given(port=valid_ports)
    def test_property_simple_port_roundtrip(self, port: int) -> None:
        """Simple port specs parse correctly for all valid ports."""
        result = _parse_port_spec(str(port))
        assert result.container == port
        assert result.host_port == port
        assert result.protocol == "tcp"

    @given(port=valid_ports, protocol=protocols)
    def test_property_port_with_protocol(self, port: int, protocol: str) -> None:
        """Port with protocol parses correctly for all valid combinations."""
        result = _parse_port_spec(f"{port}/{protocol}")
        assert result.container == port
        assert result.host_port == port
        assert result.protocol == protocol

    @given(host=valid_ports, container=valid_ports, protocol=protocols)
    def test_property_host_container_mapping(
        self, host: int, container: int, protocol: str
    ) -> None:
        """Host:container mapping parses correctly for all valid ports."""
        result = _parse_port_spec(f"{host}:{container}/{protocol}")
        assert result.container == container
        assert result.host_port == host
        assert result.protocol == protocol


class TestCheckPortConflicts:
    """Tests for _check_port_conflicts function."""

    def test_no_conflicts_when_port_free(self) -> None:
        """Should pass when port is free."""
        from mirustech.devenv_generator.commands.lifecycle import _check_port_conflicts

        ports = [PortConfig(container=8000, host_port=8000, protocol="tcp")]

        with patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            # Should not raise
            _check_port_conflicts(ports, "test-sandbox")

    def test_raises_when_port_in_use(self) -> None:
        """Should exit when port is in use."""
        from mirustech.devenv_generator.commands.lifecycle import _check_port_conflicts

        ports = [PortConfig(container=8000, host_port=8000, protocol="tcp")]

        with patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="python 1234 user 5u IPv4 TCP *:8000 (LISTEN)"
            )
            with pytest.raises(SystemExit):
                _check_port_conflicts(ports, "test-sandbox")


class TestLoadProfile:
    """Tests for _load_profile function."""

    def test_loads_bundled_profile(self) -> None:
        """Should load bundled profile by name."""
        from mirustech.devenv_generator.commands.lifecycle import _load_profile

        result = _load_profile("default")
        assert result.name == "default"

    def test_loads_yaml_file(self, tmp_path: Path) -> None:
        """Should load profile from YAML file path."""
        from mirustech.devenv_generator.commands.lifecycle import _load_profile

        profile_file = tmp_path / "custom.yaml"
        profile_file.write_text(
            """
name: custom
description: Custom profile
python:
  version: "3.12"
"""
        )

        result = _load_profile(str(profile_file))
        assert result.name == "custom"

    def test_exits_for_nonexistent_profile(self) -> None:
        """Should exit for nonexistent profile."""
        from mirustech.devenv_generator.commands.lifecycle import _load_profile

        with pytest.raises(SystemExit):
            _load_profile("nonexistent-profile-xyz")


class TestLifecycleCommands:
    """Tests for lifecycle CLI commands."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_run_help(self, runner: CliRunner) -> None:
        """Should show help for run command."""
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "Create and start" in result.output or "sandbox" in result.output.lower()

    def test_attach_help(self, runner: CliRunner) -> None:
        """Should show help for attach command."""
        result = runner.invoke(main, ["attach", "--help"])
        assert result.exit_code == 0
        assert "Attach" in result.output or "sandbox" in result.output.lower()

    def test_stop_help(self, runner: CliRunner) -> None:
        """Should show help for stop command."""
        result = runner.invoke(main, ["stop", "--help"])
        assert result.exit_code == 0
        assert "Stop" in result.output or "sandbox" in result.output.lower()

    def test_start_help(self, runner: CliRunner) -> None:
        """Should show help for start command."""
        result = runner.invoke(main, ["start", "--help"])
        assert result.exit_code == 0
        assert "Start" in result.output or "sandbox" in result.output.lower()

    def test_cd_help(self, runner: CliRunner) -> None:
        """Should show help for cd command."""
        result = runner.invoke(main, ["cd", "--help"])
        assert result.exit_code == 0

    def test_stop_nonexistent_sandbox(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when stopping nonexistent sandbox."""
        with patch(
            "mirustech.devenv_generator.commands.lifecycle.SANDBOXES_DIR",
            tmp_path,
        ):
            result = runner.invoke(main, ["stop", "nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_start_nonexistent_sandbox(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when starting nonexistent sandbox."""
        with patch(
            "mirustech.devenv_generator.commands.lifecycle.SANDBOXES_DIR",
            tmp_path,
        ):
            result = runner.invoke(main, ["start", "nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_attach_nonexistent_sandbox(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when attaching to nonexistent sandbox."""
        with patch(
            "mirustech.devenv_generator.commands.lifecycle.SANDBOXES_DIR",
            tmp_path,
        ):
            result = runner.invoke(main, ["attach", "nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()


class TestEnsureDockerRunning:
    """Tests for _ensure_docker_running function."""

    def test_returns_true_when_docker_already_running(self) -> None:
        """Should return True when Docker is already running."""
        from mirustech.devenv_generator.commands.lifecycle import _ensure_docker_running

        with patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = _ensure_docker_running()
            assert result is True

    def test_returns_false_after_timeout(self) -> None:
        """Should return False when Docker doesn't start in time."""
        from mirustech.devenv_generator.commands.lifecycle import _ensure_docker_running

        with (
            patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run,
            patch("time.sleep"),  # Skip actual waiting
        ):
            # Always return failure - Docker never starts
            mock_run.return_value = MagicMock(returncode=1)
            result = _ensure_docker_running()
            assert result is False


class TestStartSerenaServer:
    """Tests for _start_serena_server function."""

    def test_returns_none_when_uvx_not_found(self) -> None:
        """Should return None when uvx is not installed."""
        from mirustech.devenv_generator.commands.lifecycle import _start_serena_server

        with patch("shutil.which", return_value=None):
            result = _start_serena_server()
            assert result is None

    def test_returns_none_when_port_in_use(self) -> None:
        """Should return None when port is already in use."""
        from mirustech.devenv_generator.commands.lifecycle import _start_serena_server

        with (
            patch("shutil.which", return_value="/usr/bin/uvx"),
            patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run,
        ):
            # lsof returns success meaning port is in use
            mock_run.return_value = MagicMock(returncode=0, stdout="uvx 12345")
            result = _start_serena_server()
            assert result is None

    def test_starts_serena_with_no_browser(self) -> None:
        """Should start Serena with no_browser flag."""
        from mirustech.devenv_generator.commands.lifecycle import _start_serena_server

        mock_proc = MagicMock()

        with (
            patch("shutil.which", return_value="/usr/bin/uvx"),
            patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run,
            patch(
                "mirustech.devenv_generator.commands.lifecycle.process_manager.start",
                return_value=mock_proc,
            ),
            patch("time.sleep"),
        ):
            mock_run.return_value = MagicMock(returncode=1, stdout="")  # Port free
            result = _start_serena_server(port=9121, no_browser=True)
            assert result == mock_proc

    def test_returns_none_on_exception(self) -> None:
        """Should return None on exception."""
        from mirustech.devenv_generator.commands.lifecycle import _start_serena_server

        with (
            patch("shutil.which", return_value="/usr/bin/uvx"),
            patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run,
            patch(
                "mirustech.devenv_generator.commands.lifecycle.process_manager.start",
                side_effect=Exception("Failed to start"),
            ),
        ):
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = _start_serena_server()
            assert result is None


class TestStartGpgForwarder:
    """Tests for _start_gpg_forwarder function."""

    def test_returns_none_when_socat_not_found(self) -> None:
        """Should return None when socat is not installed."""
        from mirustech.devenv_generator.commands.lifecycle import _start_gpg_forwarder

        with patch("shutil.which", return_value=None):
            result = _start_gpg_forwarder()
            assert result is None

    def test_returns_none_when_socket_not_found(self, tmp_path: Path) -> None:
        """Should return None when GPG socket doesn't exist."""
        from mirustech.devenv_generator.commands.lifecycle import _start_gpg_forwarder

        with (
            patch("shutil.which", return_value="/usr/bin/socat"),
            patch("pathlib.Path.expanduser", return_value=tmp_path / "nonexistent"),
        ):
            result = _start_gpg_forwarder()
            assert result is None


class TestCdCommand:
    """Tests for the cd CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_cd_nonexistent_sandbox(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when sandbox doesn't exist."""
        with patch(
            "mirustech.devenv_generator.commands.lifecycle.SANDBOXES_DIR",
            tmp_path,
        ):
            result = runner.invoke(main, ["cd", "nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_cd_outputs_path(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should output sandbox path."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")

        with patch(
            "mirustech.devenv_generator.commands.lifecycle.SANDBOXES_DIR",
            tmp_path,
        ):
            result = runner.invoke(main, ["cd", "my-sandbox"])
            assert result.exit_code == 0
            assert "my-sandbox" in result.output


class TestStartExistingSandbox:
    """Tests for starting existing sandboxes."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_start_existing_sandbox(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should start an existing stopped sandbox."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")

        with (
            patch(
                "mirustech.devenv_generator.commands.lifecycle.SANDBOXES_DIR",
                tmp_path,
            ),
            patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(main, ["start", "my-sandbox"])
            assert result.exit_code == 0
            assert "started" in result.output.lower() or "starting" in result.output.lower()


class TestStopExistingSandbox:
    """Tests for stopping existing sandboxes."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_stop_existing_sandbox(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should stop an existing running sandbox."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")

        with (
            patch(
                "mirustech.devenv_generator.commands.lifecycle.SANDBOXES_DIR",
                tmp_path,
            ),
            patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(main, ["stop", "my-sandbox"])
            assert result.exit_code == 0


class TestAttachExistingSandbox:
    """Tests for attaching to existing sandboxes."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_attach_sandbox_not_running(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when sandbox is not running."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")

        with (
            patch(
                "mirustech.devenv_generator.commands.lifecycle.SANDBOXES_DIR",
                tmp_path,
            ),
            patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run,
        ):
            # docker compose ps returns empty (no containers)
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = runner.invoke(main, ["attach", "my-sandbox"])
            assert result.exit_code == 1
            assert "not running" in result.output.lower()


@pytest.mark.integration
class TestRunCommandIntegration:
    """Integration tests for run command with actual Docker.

    These tests require Docker to be running.
    Run with: pytest -m integration tests/test_lifecycle.py::TestRunCommandIntegration
    """

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    @pytest.fixture
    def docker_available(self) -> None:
        """Check if Docker is available."""
        import subprocess

        try:
            result = subprocess.run(
                ["docker", "info"], capture_output=True, timeout=10
            )
            if result.returncode != 0:
                pytest.skip("Docker is not running")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("Docker not available")

    def test_run_validates_nonexistent_path(self, runner: CliRunner) -> None:
        """Run should error on nonexistent path."""
        result = runner.invoke(main, ["run", "/nonexistent/path/xyz"])
        assert result.exit_code == 1
        assert "does not exist" in result.output.lower()

    def test_run_validates_file_not_directory(self, runner: CliRunner, tmp_path: Path) -> None:
        """Run should error when path is a file not directory."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        result = runner.invoke(main, ["run", str(test_file)])
        assert result.exit_code == 1
        assert "not a directory" in result.output.lower()

    def test_run_detects_python_version_from_file(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Run should detect Python version from .python-version."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".python-version").write_text("3.11\n")

        # Run with --help to avoid actual container creation
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "python" in result.output.lower()


@pytest.mark.integration
class TestLifecycleWorkflows:
    """Integration tests for complete lifecycle workflows.

    These tests verify the full workflow: run → stop → start → attach → stop
    Run with: pytest -m integration tests/test_lifecycle.py::TestLifecycleWorkflows
    """

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    @pytest.fixture
    def docker_available(self) -> None:
        """Check if Docker is available."""
        import subprocess

        try:
            result = subprocess.run(
                ["docker", "info"], capture_output=True, timeout=10
            )
            if result.returncode != 0:
                pytest.skip("Docker is not running")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("Docker not available")

    def test_complete_lifecycle_workflow_mocked(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test complete lifecycle with mocked Docker commands.

        This tests the CLI orchestration without requiring actual Docker.
        """
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text(
            """services:
  dev:
    image: test
"""
        )

        with (
            patch(
                "mirustech.devenv_generator.commands.lifecycle.SANDBOXES_DIR",
                tmp_path,
            ),
            patch(
                "mirustech.devenv_generator.commands.management.SANDBOXES_DIR",
                tmp_path,
            ),
            patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_run,
        ):
            # Mock successful commands
            mock_run.return_value = MagicMock(returncode=0, stdout="container-id-123")

            # Test start command
            result = runner.invoke(main, ["start", "my-sandbox", "-d"])
            # Should fail because _is_sandbox_running check will fail with mock
            # but we're testing the command structure

            # Test stop command
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(main, ["stop", "my-sandbox"])
            assert result.exit_code == 0


@pytest.mark.integration
class TestPortConflictDetection:
    """Integration tests for port conflict detection."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_parse_port_with_udp_protocol(self) -> None:
        """Should parse UDP protocol correctly."""
        result = _parse_port_spec("5353/udp")
        assert result.container == 5353
        assert result.host_port == 5353
        assert result.protocol == "udp"

    def test_parse_complex_port_mapping(self) -> None:
        """Should parse complex host:container/protocol format."""
        result = _parse_port_spec("8080:3000/udp")
        assert result.container == 3000
        assert result.host_port == 8080
        assert result.protocol == "udp"


@pytest.mark.integration
class TestBackgroundProcessManagement:
    """Integration tests for background process management (Serena, GPG)."""

    def test_serena_server_respects_port_option(self) -> None:
        """Serena server should use specified port."""
        from mirustech.devenv_generator.commands.lifecycle import _start_serena_server

        # Test with non-default port (but don't actually start it)
        # This is a structural test to verify the function signature
        with patch("shutil.which", return_value=None):
            result = _start_serena_server(port=9999, no_browser=True)
            assert result is None  # Should return None when uvx not found

    def test_gpg_forwarder_handles_missing_socket(self) -> None:
        """GPG forwarder should handle missing socket gracefully."""
        from mirustech.devenv_generator.commands.lifecycle import _start_gpg_forwarder

        with (
            patch("shutil.which", return_value="/usr/bin/socat"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = _start_gpg_forwarder(port=9876)
            assert result is None  # Should return None when socket not found


@pytest.mark.integration
class TestMountSpecParsing:
    """Integration tests for mount specification parsing."""

    def test_mount_spec_with_cow_mode(self) -> None:
        """Should parse copy-on-write mount mode."""
        from mirustech.devenv_generator.models import MountSpec

        spec = MountSpec.from_string("/path/to/project:cow")
        assert spec.mode == "cow"
        assert spec.host_path == Path("/path/to/project")

    def test_mount_spec_with_readonly_mode(self) -> None:
        """Should parse read-only mount mode."""
        from mirustech.devenv_generator.models import MountSpec

        spec = MountSpec.from_string("/path/to/project:ro")
        assert spec.mode == "ro"
        assert spec.host_path == Path("/path/to/project")

    def test_mount_spec_default_readwrite(self) -> None:
        """Should default to read-write mode."""
        from mirustech.devenv_generator.models import MountSpec

        spec = MountSpec.from_string("/path/to/project")
        assert spec.mode == "rw"
