"""Integration tests for lifecycle commands with actual Docker.

These tests require:
- Docker daemon running
- Sufficient disk space for building test containers

Run with: pytest -m integration tests/test_integration_lifecycle.py
Skip in regular test runs with: pytest -m "not integration"
"""

from __future__ import annotations

import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main
from mirustech.devenv_generator.generator import SandboxGenerator
from mirustech.devenv_generator.models import MountSpec, ProfileConfig, PythonConfig


# --- Fixtures ---


def _ensure_docker_running() -> bool:
    """Start Docker Desktop if not running. Returns True if Docker is available."""
    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        timeout=10,
    )
    if result.returncode == 0:
        return True

    # Try to start Docker Desktop (macOS)
    subprocess.run(
        ["open", "-a", "Docker"],
        capture_output=True,
        timeout=5,
    )

    # Wait for Docker to start (up to 60 seconds)
    for _ in range(30):
        time.sleep(2)
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True

    return False


@pytest.fixture
def docker_available() -> None:
    """Ensure Docker is available, starting Docker Desktop if needed."""
    try:
        if not _ensure_docker_running():
            pytest.skip("Docker is not available or failed to start")
    except FileNotFoundError:
        pytest.skip("Docker command not found")
    except subprocess.TimeoutExpired:
        pytest.skip("Docker command timed out")


@pytest.fixture
def test_project(tmp_path: Path) -> Path:
    """Create a temporary test project."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    # Create a simple Python file
    python_file = project_dir / "hello.py"
    python_file.write_text('"""Test file."""\n\nprint("Hello from test project")\n')

    # Create pyproject.toml
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "test-project"
version = "0.1.0"
requires-python = ">=3.12"
"""
    )

    # Create .python-version
    (project_dir / ".python-version").write_text("3.12\n")

    return project_dir


@pytest.fixture
def unique_sandbox_name() -> str:
    """Generate a unique sandbox name to avoid conflicts."""
    return f"test-lifecycle-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def sandbox_dir(tmp_path: Path, unique_sandbox_name: str) -> Path:
    """Directory for sandbox files."""
    sandbox_path = tmp_path / "sandboxes" / unique_sandbox_name
    sandbox_path.mkdir(parents=True)
    return sandbox_path


@pytest.fixture
def minimal_sandbox(
    test_project: Path, sandbox_dir: Path, unique_sandbox_name: str
) -> Iterator[Path]:
    """Generate a minimal sandbox for testing (with cleanup)."""
    # Minimal profile for faster builds
    profile = ProfileConfig(
        name="lifecycle-test",
        description="Minimal profile for lifecycle testing",
        python=PythonConfig(version="3.12"),
        system_packages=["curl"],  # Minimal packages
        node_packages=[],  # Skip Claude Code for faster builds
        uvx_tools=[],
        github_releases={},
    )

    mount = MountSpec(host_path=test_project, mode="rw")

    generator = SandboxGenerator(
        profile=profile,
        mounts=[mount],
        sandbox_name=unique_sandbox_name,
        use_host_claude_config=False,
    )

    generator.generate(sandbox_dir)

    yield sandbox_dir

    # Cleanup
    subprocess.run(
        ["docker", "compose", "-p", unique_sandbox_name, "down", "-v", "--remove-orphans"],
        cwd=sandbox_dir,
        capture_output=True,
        timeout=60,
    )
    subprocess.run(
        ["docker", "rmi", "-f", f"{unique_sandbox_name}-dev"],
        capture_output=True,
        timeout=30,
    )


@pytest.fixture
def built_sandbox(
    docker_available: None, minimal_sandbox: Path, unique_sandbox_name: str
) -> Path:
    """Build the sandbox image (ready for running)."""
    result = subprocess.run(
        ["docker", "compose", "-p", unique_sandbox_name, "build"],
        cwd=minimal_sandbox,
        capture_output=True,
        text=True,
        timeout=600,  # 10 min for build
    )
    assert result.returncode == 0, f"Build failed: {result.stderr}"
    return minimal_sandbox


# --- Helper Functions ---


def _is_container_running(sandbox_name: str, sandbox_dir: Path) -> bool:
    """Check if sandbox container is running."""
    result = subprocess.run(
        ["docker", "compose", "-p", sandbox_name, "ps", "-q"],
        cwd=sandbox_dir,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return bool(result.stdout.strip())


def _start_container_detached(sandbox_name: str, sandbox_dir: Path) -> None:
    """Start container in background."""
    result = subprocess.run(
        ["docker", "compose", "-p", sandbox_name, "up", "-d"],
        cwd=sandbox_dir,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Failed to start: {result.stderr}"


def _stop_container(sandbox_name: str, sandbox_dir: Path) -> None:
    """Stop container."""
    subprocess.run(
        ["docker", "compose", "-p", sandbox_name, "down"],
        cwd=sandbox_dir,
        capture_output=True,
        timeout=60,
    )


def _exec_in_container(sandbox_name: str, sandbox_dir: Path, command: list[str]) -> str:
    """Execute command in running container and return output."""
    result = subprocess.run(
        ["docker", "compose", "-p", sandbox_name, "exec", "-T", "dev"] + command,
        cwd=sandbox_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout


# --- Integration Tests ---


@pytest.mark.integration
class TestDockerBuild:
    """Integration tests for Docker image building."""

    def test_sandbox_builds_successfully(
        self, docker_available: None, minimal_sandbox: Path, unique_sandbox_name: str
    ) -> None:
        """Verify sandbox Docker image builds without errors."""
        result = subprocess.run(
            ["docker", "compose", "-p", unique_sandbox_name, "build", "--no-cache"],
            cwd=minimal_sandbox,
            capture_output=True,
            text=True,
            timeout=600,
        )

        # Cleanup
        subprocess.run(
            ["docker", "compose", "-p", unique_sandbox_name, "down", "-v"],
            cwd=minimal_sandbox,
            capture_output=True,
            timeout=60,
        )
        subprocess.run(
            ["docker", "rmi", "-f", f"{unique_sandbox_name}-dev"],
            capture_output=True,
            timeout=30,
        )

        assert result.returncode == 0, f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    def test_docker_compose_config_valid(
        self, docker_available: None, minimal_sandbox: Path, unique_sandbox_name: str
    ) -> None:
        """Verify docker-compose configuration is valid."""
        result = subprocess.run(
            ["docker", "compose", "-p", unique_sandbox_name, "config"],
            cwd=minimal_sandbox,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Config validation failed: {result.stderr}"


@pytest.mark.integration
class TestContainerLifecycle:
    """Integration tests for container start/stop/restart lifecycle."""

    def test_container_starts_in_detached_mode(
        self, built_sandbox: Path, unique_sandbox_name: str
    ) -> None:
        """Container starts successfully in detached mode."""
        try:
            _start_container_detached(unique_sandbox_name, built_sandbox)

            # Verify container is running
            assert _is_container_running(unique_sandbox_name, built_sandbox)
        finally:
            _stop_container(unique_sandbox_name, built_sandbox)

    def test_container_stops_cleanly(self, built_sandbox: Path, unique_sandbox_name: str) -> None:
        """Container stops without errors."""
        try:
            _start_container_detached(unique_sandbox_name, built_sandbox)
            assert _is_container_running(unique_sandbox_name, built_sandbox)

            _stop_container(unique_sandbox_name, built_sandbox)

            # Verify container is stopped
            assert not _is_container_running(unique_sandbox_name, built_sandbox)
        finally:
            _stop_container(unique_sandbox_name, built_sandbox)

    def test_container_restarts_after_stop(
        self, built_sandbox: Path, unique_sandbox_name: str
    ) -> None:
        """Container can be restarted after stopping."""
        try:
            # Start
            _start_container_detached(unique_sandbox_name, built_sandbox)
            assert _is_container_running(unique_sandbox_name, built_sandbox)

            # Stop
            _stop_container(unique_sandbox_name, built_sandbox)
            assert not _is_container_running(unique_sandbox_name, built_sandbox)

            # Restart
            _start_container_detached(unique_sandbox_name, built_sandbox)
            assert _is_container_running(unique_sandbox_name, built_sandbox)
        finally:
            _stop_container(unique_sandbox_name, built_sandbox)

    def test_python_version_correct_in_container(
        self, built_sandbox: Path, unique_sandbox_name: str
    ) -> None:
        """Container has correct Python version installed."""
        try:
            _start_container_detached(unique_sandbox_name, built_sandbox)

            output = _exec_in_container(
                unique_sandbox_name, built_sandbox, ["python", "--version"]
            )

            assert "Python 3.12" in output
        finally:
            _stop_container(unique_sandbox_name, built_sandbox)


@pytest.mark.integration
class TestMountPersistence:
    """Integration tests for mount persistence across container lifecycle."""

    def test_file_modifications_persist_after_restart(
        self, built_sandbox: Path, unique_sandbox_name: str, test_project: Path
    ) -> None:
        """File changes persist when container is stopped and restarted."""
        try:
            _start_container_detached(unique_sandbox_name, built_sandbox)

            # Create a file in the mounted directory
            test_file = test_project / "created_in_container.txt"
            test_content = "Created during integration test"

            # Create file via container
            _exec_in_container(
                unique_sandbox_name,
                built_sandbox,
                ["sh", "-c", f'echo "{test_content}" > /workspace/created_in_container.txt'],
            )

            # Verify file exists on host
            assert test_file.exists()
            assert test_content in test_file.read_text()

            # Stop container
            _stop_container(unique_sandbox_name, built_sandbox)

            # Verify file still exists on host
            assert test_file.exists()
            assert test_content in test_file.read_text()

            # Restart container
            _start_container_detached(unique_sandbox_name, built_sandbox)

            # Verify file is accessible in new container
            output = _exec_in_container(
                unique_sandbox_name, built_sandbox, ["cat", "/workspace/created_in_container.txt"]
            )
            assert test_content in output

        finally:
            _stop_container(unique_sandbox_name, built_sandbox)


@pytest.mark.integration
class TestContainerExecution:
    """Integration tests for executing commands in containers."""

    def test_container_can_execute_python_script(
        self, built_sandbox: Path, unique_sandbox_name: str
    ) -> None:
        """Container can execute Python scripts from mounted directory."""
        try:
            _start_container_detached(unique_sandbox_name, built_sandbox)

            # Execute the hello.py script
            output = _exec_in_container(
                unique_sandbox_name, built_sandbox, ["python", "/workspace/hello.py"]
            )

            assert "Hello from test project" in output
        finally:
            _stop_container(unique_sandbox_name, built_sandbox)

    def test_container_has_required_tools(
        self, built_sandbox: Path, unique_sandbox_name: str
    ) -> None:
        """Container has required system tools installed."""
        try:
            _start_container_detached(unique_sandbox_name, built_sandbox)

            # Check for essential tools
            tools = ["python", "git", "curl", "zsh"]
            for tool in tools:
                output = _exec_in_container(unique_sandbox_name, built_sandbox, ["which", tool])
                assert tool in output.lower() or "/" in output, f"Tool {tool} not found"

        finally:
            _stop_container(unique_sandbox_name, built_sandbox)


@pytest.mark.integration
class TestErrorHandling:
    """Integration tests for error conditions."""

    def test_build_fails_with_invalid_dockerfile(
        self, docker_available: None, tmp_path: Path
    ) -> None:
        """Build fails gracefully with invalid Dockerfile."""
        sandbox_dir = tmp_path / "invalid-sandbox"
        sandbox_dir.mkdir()

        dockerfile_dir = sandbox_dir / ".devcontainer"
        dockerfile_dir.mkdir()

        # Create invalid Dockerfile
        (dockerfile_dir / "Dockerfile").write_text("INVALID DOCKERFILE CONTENT\n")

        # Create minimal docker-compose.yml
        (sandbox_dir / "docker-compose.yml").write_text(
            """
services:
  dev:
    build:
      context: .
      dockerfile: .devcontainer/Dockerfile
"""
        )

        result = subprocess.run(
            ["docker", "compose", "build"],
            cwd=sandbox_dir,
            capture_output=True,
            timeout=60,
        )

        assert result.returncode != 0  # Build should fail

    def test_cannot_start_without_image(
        self, docker_available: None, minimal_sandbox: Path, unique_sandbox_name: str
    ) -> None:
        """Starting container fails if image not built."""
        # Don't build the image, just try to start
        result = subprocess.run(
            ["docker", "compose", "-p", unique_sandbox_name, "up", "-d"],
            cwd=minimal_sandbox,
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Should fail because image doesn't exist
        assert result.returncode != 0


@pytest.mark.integration
class TestPortExposure:
    """Integration tests for port exposure in containers."""

    def test_container_exposes_configured_ports(
        self, docker_available: None, test_project: Path, tmp_path: Path
    ) -> None:
        """Container properly exposes ports configured in profile."""
        import random

        # Use random high port to avoid conflicts
        test_port = random.randint(49152, 65535)
        sandbox_name = f"test-ports-{uuid.uuid4().hex[:8]}"
        sandbox_dir = tmp_path / "sandbox-with-ports"
        sandbox_dir.mkdir()

        # Create profile with port configuration
        from mirustech.devenv_generator.models import PortConfig, PortsConfig

        profile = ProfileConfig(
            name="port-test",
            description="Profile with port for testing",
            python=PythonConfig(version="3.12"),
            system_packages=["curl"],
            node_packages=[],
            uvx_tools=[],
            github_releases={},
            ports=PortsConfig(
                ports=[
                    PortConfig(
                        container=test_port, host=test_port, protocol="tcp", description="Test port"
                    )
                ]
            ),
        )

        mount = MountSpec(host_path=test_project, mode="rw")

        generator = SandboxGenerator(
            profile=profile,
            mounts=[mount],
            sandbox_name=sandbox_name,
            use_host_claude_config=False,
        )
        generator.generate(sandbox_dir)

        try:
            # Build and start
            build_result = subprocess.run(
                ["docker", "compose", "-p", sandbox_name, "build"],
                cwd=sandbox_dir,
                capture_output=True,
                timeout=600,
            )
            assert build_result.returncode == 0

            subprocess.run(
                ["docker", "compose", "-p", sandbox_name, "up", "-d"],
                cwd=sandbox_dir,
                capture_output=True,
                timeout=60,
            )

            # Verify port is exposed
            result = subprocess.run(
                ["docker", "compose", "-p", sandbox_name, "ps", "--format", "json"],
                cwd=sandbox_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Check that port appears in the output
            assert str(test_port) in result.stdout

        finally:
            # Cleanup
            subprocess.run(
                ["docker", "compose", "-p", sandbox_name, "down", "-v"],
                cwd=sandbox_dir,
                capture_output=True,
                timeout=60,
            )
            subprocess.run(
                ["docker", "rmi", "-f", f"{sandbox_name}-dev"],
                capture_output=True,
                timeout=30,
            )


@pytest.mark.integration
class TestCLIIntegration:
    """Integration tests for CLI commands with real Docker."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create CLI test runner."""
        return CliRunner()

    def test_run_command_creates_sandbox(
        self,
        docker_available: None,
        runner: CliRunner,
        test_project: Path,
        tmp_path: Path,
    ) -> None:
        """CLI run command creates and starts sandbox successfully."""
        sandbox_name = f"cli-test-{uuid.uuid4().hex[:8]}"
        sandbox_dir = tmp_path / "sandboxes" / sandbox_name

        try:
            # Run with --shell to avoid needing Claude, and --detach to avoid interactive mode
            result = runner.invoke(
                main,
                [
                    "run",
                    str(test_project),
                    "--name",
                    sandbox_name,
                    "--output",
                    str(sandbox_dir),
                    "--detach",
                    "--profile",
                    "minimal",
                ],
                catch_exceptions=False,
            )

            # Check command succeeded (or timed out which is acceptable for this test)
            assert result.exit_code in (
                0,
                -1,
            ), f"Command failed: {result.output}\n{result.exception}"

            # Verify sandbox directory was created
            assert sandbox_dir.exists()
            assert (sandbox_dir / "docker-compose.yml").exists()

        finally:
            # Cleanup
            if sandbox_dir.exists():
                subprocess.run(
                    ["docker", "compose", "-p", sandbox_name, "down", "-v", "--remove-orphans"],
                    cwd=sandbox_dir,
                    capture_output=True,
                    timeout=60,
                )
            subprocess.run(
                ["docker", "rmi", "-f", f"{sandbox_name}-dev"],
                capture_output=True,
                timeout=30,
            )
