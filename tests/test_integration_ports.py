"""Integration tests for port exposure feature.

Requires Docker and Claude Code configuration.
Run with: pytest -m integration tests/test_integration_ports.py

Note: These are end-to-end tests that actually start Docker containers.
They may be skipped in CI or when Docker is not available.
"""

import json
import random
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main
from mirustech.devenv_generator.models import PortConfig, PortsConfig, ProfileConfig


def _get_random_port() -> int:
    """Get a random high port number unlikely to be in use."""
    return random.randint(49152, 65535)


@pytest.fixture
def docker_available():
    """Check Docker availability, skip tests if not available."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    pytest.skip("Docker not available")


@pytest.fixture
def test_profile_with_ports(tmp_path: Path) -> Path:
    """Create test profile YAML with port configuration using random ports."""
    port1 = _get_random_port()
    port2 = _get_random_port()

    profile_path = tmp_path / "test-ports.yaml"
    profile_data = {
        "name": "test-ports",
        "description": "Test profile with ports",
        "python": {"version": "3.12"},
        "ports": {
            "ports": [
                {"container": port1, "host": port1, "description": "Test server"},
                {"container": port2, "host": port2, "description": "Vite dev"},
            ]
        }
    }
    profile_path.write_text(yaml.dump(profile_data))
    return profile_path


@pytest.mark.integration
class TestStaticPortExposure:
    """Integration tests for static port configuration."""

    def test_profile_with_ports_loads(self, test_profile_with_ports: Path) -> None:
        """Profile with ports loads correctly."""
        from mirustech.devenv_generator.generator import load_profile

        config = load_profile(test_profile_with_ports)
        assert len(config.ports.ports) == 2
        assert config.ports.ports[0].description == "Test server"
        assert config.ports.ports[1].description == "Vite dev"
        # Verify ports are in valid range
        assert 49152 <= config.ports.ports[0].container <= 65535
        assert 49152 <= config.ports.ports[1].container <= 65535

    def test_docker_compose_generated_with_ports(
        self,
        test_profile_with_ports: Path,
        tmp_path: Path,
        docker_available
    ) -> None:
        """Generated docker-compose includes port mappings."""
        from mirustech.devenv_generator.generator import DevEnvGenerator, load_profile

        config = load_profile(test_profile_with_ports)
        generator = DevEnvGenerator(config, project_name="test-ports")

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        generator.generate(output_dir)

        compose_file = output_dir / "docker-compose.yml"
        assert compose_file.exists()

        compose_content = compose_file.read_text()
        # Just check that ports section exists and has localhost binding
        assert "ports:" in compose_content
        assert "127.0.0.1:" in compose_content
        assert "/tcp" in compose_content
        assert "# Test server" in compose_content


@pytest.mark.integration
@pytest.mark.skip(reason="Requires manual testing with running Docker containers")
class TestDynamicPortExposure:
    """Integration tests for dynamic port commands.

    These tests require a running Docker environment and are meant for
    manual testing. Run them explicitly when needed:
    pytest -m integration --runxfail tests/test_integration_ports.py::TestDynamicPortExposure
    """

    def test_expose_port_command_workflow(self) -> None:
        """Manual test workflow for expose command.

        To test manually:
        1. devenv run --detach --no-ports ~/test-project
        2. devenv expose <sandbox-name> 8000
        3. Verify port appears in 'devenv ports'
        4. devenv unexpose <sandbox-name> 8000
        5. Verify port removed from 'devenv ports'
        """
        pytest.skip("Manual test - see docstring for workflow")


@pytest.mark.integration
@pytest.mark.skip(reason="Requires manual testing with Docker")
class TestRuntimePortOverrides:
    """Integration tests for --expose-port and --no-ports flags.

    These tests require Docker and may conflict with existing containers.
    Run manually when needed to verify end-to-end functionality.
    """

    def test_expose_port_flag_workflow(self) -> None:
        """Manual test workflow for --expose-port flag.

        To test manually:
        1. devenv run --detach --expose-port 8000 ~/test-project
        2. Verify container running with 'docker ps'
        3. Check port 8000 is exposed with 'docker inspect'
        """
        pytest.skip("Manual test - see docstring for workflow")

    def test_no_ports_flag_workflow(self) -> None:
        """Manual test workflow for --no-ports flag.

        To test manually:
        1. Create profile with ports defined
        2. devenv run --detach --no-ports ~/test-project
        3. Verify no ports are exposed with 'docker inspect'
        """
        pytest.skip("Manual test - see docstring for workflow")
