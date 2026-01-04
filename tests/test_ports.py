"""Tests for ports command module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main
from mirustech.devenv_generator.commands.ports import (
    _get_sandbox_dir,
    _load_dynamic_ports,
    _save_dynamic_ports,
    _update_compose_ports,
)
from mirustech.devenv_generator.models import PortConfig


class TestGetSandboxDir:
    """Tests for _get_sandbox_dir function."""

    def test_returns_path_under_sandboxes_dir(self) -> None:
        """Should return path under sandboxes directory."""
        result = _get_sandbox_dir("myproject")
        assert result.name == "myproject"
        assert "devenv-sandboxes" in str(result)


class TestLoadDynamicPorts:
    """Tests for _load_dynamic_ports function."""

    def test_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        """Should return empty dict when file doesn't exist."""
        result = _load_dynamic_ports(tmp_path)
        assert result == {}

    def test_loads_existing_ports_file(self, tmp_path: Path) -> None:
        """Should load ports from existing JSON file."""
        ports_data = {
            "8080": {"host_port": "8080", "protocol": "tcp"},
            "3000": {"host_port": "3001", "protocol": "tcp"},
        }
        ports_file = tmp_path / ".dynamic-ports.json"
        ports_file.write_text(json.dumps(ports_data))

        result = _load_dynamic_ports(tmp_path)
        assert result == ports_data


class TestSaveDynamicPorts:
    """Tests for _save_dynamic_ports function."""

    def test_saves_ports_to_json_file(self, tmp_path: Path) -> None:
        """Should save ports to JSON file."""
        ports_data = {
            "8080": {"host_port": "8080", "protocol": "tcp"},
        }

        _save_dynamic_ports(tmp_path, ports_data)

        ports_file = tmp_path / ".dynamic-ports.json"
        assert ports_file.exists()

        loaded = json.loads(ports_file.read_text())
        assert loaded == ports_data

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """Should overwrite existing ports file."""
        ports_file = tmp_path / ".dynamic-ports.json"
        ports_file.write_text('{"old": {}}')

        new_ports = {"new": {"host_port": "9000", "protocol": "tcp"}}
        _save_dynamic_ports(tmp_path, new_ports)

        loaded = json.loads(ports_file.read_text())
        assert "old" not in loaded
        assert "new" in loaded


class TestExposeCommand:
    """Tests for the expose CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_expose_help(self, runner: CliRunner) -> None:
        """Should show help for expose command."""
        result = runner.invoke(main, ["expose", "--help"])
        assert result.exit_code == 0
        assert "Expose additional ports" in result.output

    def test_expose_requires_port_spec(self, runner: CliRunner) -> None:
        """Should require at least one port spec."""
        result = runner.invoke(main, ["expose"])
        assert result.exit_code != 0


class TestPortsCommand:
    """Tests for the ports CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_ports_help(self, runner: CliRunner) -> None:
        """Should show help for ports command."""
        result = runner.invoke(main, ["ports", "--help"])
        assert result.exit_code == 0
        assert "List all exposed ports" in result.output


class TestUnexposeCommand:
    """Tests for the unexpose CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_unexpose_help(self, runner: CliRunner) -> None:
        """Should show help for unexpose command."""
        result = runner.invoke(main, ["unexpose", "--help"])
        assert result.exit_code == 0
        assert "Remove dynamically exposed ports" in result.output

    def test_unexpose_requires_port(self, runner: CliRunner) -> None:
        """Should require at least one port."""
        result = runner.invoke(main, ["unexpose"])
        assert result.exit_code != 0


class TestUpdateComposePorts:
    """Tests for _update_compose_ports function."""

    def test_adds_new_ports_to_compose_file(self, tmp_path: Path) -> None:
        """Should add new port mappings to docker-compose.yml."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            """
services:
  dev:
    image: test:latest
"""
        )

        new_ports = [PortConfig(container=8000, host_port=8000, protocol="tcp")]

        with patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _update_compose_ports(tmp_path, "test-sandbox", new_ports)

        # Read and parse the updated compose file
        with compose_file.open() as f:
            config = yaml.safe_load(f)

        assert "ports" in config["services"]["dev"]
        assert "127.0.0.1:8000:8000/tcp" in config["services"]["dev"]["ports"]

    def test_avoids_duplicate_port_mappings(self, tmp_path: Path) -> None:
        """Should not add duplicate port mappings."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            """
services:
  dev:
    image: test:latest
    ports:
      - "127.0.0.1:8000:8000/tcp"
"""
        )

        new_ports = [PortConfig(container=8000, host_port=8000, protocol="tcp")]

        with patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _update_compose_ports(tmp_path, "test-sandbox", new_ports)

        with compose_file.open() as f:
            config = yaml.safe_load(f)

        # Should still have only one port mapping
        assert len(config["services"]["dev"]["ports"]) == 1

    def test_exits_on_docker_failure(self, tmp_path: Path) -> None:
        """Should exit if docker compose fails."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            """
services:
  dev:
    image: test:latest
"""
        )

        new_ports = [PortConfig(container=8000, host_port=8000, protocol="tcp")]

        with patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="Error")
            with pytest.raises(SystemExit):
                _update_compose_ports(tmp_path, "test-sandbox", new_ports)


class TestExposeCommandExtended:
    """Extended tests for the expose CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_expose_sandbox_not_found(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when sandbox doesn't exist."""
        with patch(
            "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
            tmp_path,
        ):
            result = runner.invoke(main, ["expose", "8000", "--name", "nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_expose_sandbox_not_running(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when sandbox is not running."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch(
                "mirustech.devenv_generator.commands.ports._is_sandbox_running",
                return_value=False,
            ),
        ):
            result = runner.invoke(main, ["expose", "8000", "--name", "my-sandbox"])
            assert result.exit_code == 1
            assert "not running" in result.output.lower()

    def test_expose_success(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should successfully expose port."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text(
            """
services:
  dev:
    image: test:latest
"""
        )

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch(
                "mirustech.devenv_generator.commands.ports._is_sandbox_running",
                return_value=True,
            ),
            patch("mirustech.devenv_generator.commands.lifecycle.run_command") as mock_check,
            patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run,
        ):
            # Port check returns no conflict
            mock_check.return_value = MagicMock(returncode=1, stdout="")
            # Docker compose succeeds
            mock_run.return_value = MagicMock(returncode=0)

            result = runner.invoke(main, ["expose", "8000", "--name", "my-sandbox"])
            assert result.exit_code == 0
            assert "exposed" in result.output.lower()


class TestPortsCommandExtended:
    """Extended tests for the ports CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_ports_sandbox_not_found(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when sandbox doesn't exist."""
        with patch(
            "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
            tmp_path,
        ):
            result = runner.invoke(main, ["ports", "--name", "nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_ports_sandbox_not_running(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should show message when sandbox not running."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1)
            result = runner.invoke(main, ["ports", "--name", "my-sandbox"])
            assert result.exit_code == 0
            assert "not running" in result.output.lower()

    def test_ports_no_containers(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should show message when no containers found."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = runner.invoke(main, ["ports", "--name", "my-sandbox"])
            assert result.exit_code == 0
            assert "no containers" in result.output.lower()

    def test_ports_invalid_json(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should handle invalid JSON from docker."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="not valid json")
            result = runner.invoke(main, ["ports", "--name", "my-sandbox"])
            assert result.exit_code == 0
            assert "could not parse" in result.output.lower()

    def test_ports_with_publishers(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should display ports when containers have publishers."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")

        container_info = {
            "ID": "abc123",
            "Name": "my-sandbox-dev-1",
            "Publishers": [
                {"TargetPort": 8000, "PublishedPort": 8000, "Protocol": "tcp"},
            ],
        }

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(container_info))
            result = runner.invoke(main, ["ports", "--name", "my-sandbox"])
            assert result.exit_code == 0
            assert "8000" in result.output

    def test_ports_with_list_of_containers(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should handle list of containers."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")

        containers = [
            {
                "ID": "abc123",
                "Name": "my-sandbox-dev-1",
                "Publishers": [
                    {"TargetPort": 8000, "PublishedPort": 8000, "Protocol": "tcp"},
                ],
            },
        ]

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(containers))
            result = runner.invoke(main, ["ports", "--name", "my-sandbox"])
            assert result.exit_code == 0
            assert "8000" in result.output


class TestUnexposeCommandExtended:
    """Extended tests for the unexpose CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_unexpose_sandbox_not_found(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when sandbox doesn't exist."""
        with patch(
            "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
            tmp_path,
        ):
            result = runner.invoke(main, ["unexpose", "8000", "--name", "nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_unexpose_port_not_dynamic(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error when port is not dynamically exposed."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text("services:\n  dev:\n")
        # No dynamic ports file means no dynamic ports

        with patch(
            "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
            tmp_path,
        ):
            result = runner.invoke(main, ["unexpose", "8000", "--name", "my-sandbox"])
            assert result.exit_code == 1
            assert "not dynamically exposed" in result.output.lower()

    def test_unexpose_success_stopped_sandbox(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should remove port mapping even if sandbox is stopped."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text(
            """
services:
  dev:
    image: test:latest
    ports:
      - "127.0.0.1:8000:8000/tcp"
"""
        )
        # Add dynamic ports file
        dynamic_ports_file = sandbox_dir / ".dynamic-ports.json"
        dynamic_ports_file.write_text(
            json.dumps(
                {
                    "8000": {
                        "host_port": "8000",
                        "protocol": "tcp",
                        "exposed_at": "2024-01-01T00:00:00",
                        "method": "docker-port",
                    }
                }
            )
        )

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch(
                "mirustech.devenv_generator.commands.ports._is_sandbox_running",
                return_value=False,
            ),
        ):
            result = runner.invoke(main, ["unexpose", "8000", "--name", "my-sandbox"])
            assert result.exit_code == 0
            assert "removed" in result.output.lower()

        # Verify port was removed from compose file
        with (sandbox_dir / "docker-compose.yml").open() as f:
            config = yaml.safe_load(f)
        assert len(config["services"]["dev"]["ports"]) == 0

        # Verify port was removed from dynamic ports
        loaded = json.loads(dynamic_ports_file.read_text())
        assert "8000" not in loaded

    def test_unexpose_success_running_sandbox(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should remove port and recreate container if running."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text(
            """
services:
  dev:
    image: test:latest
    ports:
      - "127.0.0.1:8000:8000/tcp"
"""
        )
        dynamic_ports_file = sandbox_dir / ".dynamic-ports.json"
        dynamic_ports_file.write_text(
            json.dumps({"8000": {"host_port": "8000", "protocol": "tcp"}})
        )

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch(
                "mirustech.devenv_generator.commands.ports._is_sandbox_running",
                return_value=True,
            ),
            patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(main, ["unexpose", "8000", "--name", "my-sandbox"])
            assert result.exit_code == 0
            assert "removed" in result.output.lower()
            # Verify docker compose was called to recreate
            mock_run.assert_called()

    def test_unexpose_docker_failure(self, runner: CliRunner, tmp_path: Path) -> None:
        """Should error if docker compose fails during unexpose."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text(
            """
services:
  dev:
    image: test:latest
    ports:
      - "127.0.0.1:8000:8000/tcp"
"""
        )
        dynamic_ports_file = sandbox_dir / ".dynamic-ports.json"
        dynamic_ports_file.write_text(
            json.dumps({"8000": {"host_port": "8000", "protocol": "tcp"}})
        )

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch(
                "mirustech.devenv_generator.commands.ports._is_sandbox_running",
                return_value=True,
            ),
            patch("mirustech.devenv_generator.commands.ports.run_command") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stderr="Error")
            result = runner.invoke(main, ["unexpose", "8000", "--name", "my-sandbox"])
            assert result.exit_code == 1
            assert "failed" in result.output.lower()

    def test_unexpose_handles_different_port_formats(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should handle various port mapping formats in compose file."""
        sandbox_dir = tmp_path / "my-sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "docker-compose.yml").write_text(
            """
services:
  dev:
    image: test:latest
    ports:
      - "127.0.0.1:8000:8000/tcp"
      - "9000:9000/tcp"
"""
        )
        dynamic_ports_file = sandbox_dir / ".dynamic-ports.json"
        dynamic_ports_file.write_text(
            json.dumps(
                {
                    "8000": {"host_port": "8000", "protocol": "tcp"},
                    "9000": {"host_port": "9000", "protocol": "tcp"},
                }
            )
        )

        with (
            patch(
                "mirustech.devenv_generator.commands.ports.SANDBOXES_DIR",
                tmp_path,
            ),
            patch(
                "mirustech.devenv_generator.commands.ports._is_sandbox_running",
                return_value=False,
            ),
        ):
            result = runner.invoke(main, ["unexpose", "9000", "--name", "my-sandbox"])
            assert result.exit_code == 0

        # Verify only port 8000 remains
        with (sandbox_dir / "docker-compose.yml").open() as f:
            config = yaml.safe_load(f)
        assert len(config["services"]["dev"]["ports"]) == 1
        assert "8000" in config["services"]["dev"]["ports"][0]
