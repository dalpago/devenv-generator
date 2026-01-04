"""Tests for ports command module."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main
from mirustech.devenv_generator.commands.ports import (
    _get_sandbox_dir,
    _load_dynamic_ports,
    _save_dynamic_ports,
)


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
