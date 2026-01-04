"""Integration tests for SandboxGenerator with real Docker and Claude Code.

These tests require:
- Docker daemon running
- ANTHROPIC_AUTH_TOKEN environment variable OR Claude Code configured

Run with: pytest -m integration
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mirustech.devenv_generator.generator import SandboxGenerator
from mirustech.devenv_generator.models import MountSpec, ProfileConfig, PythonConfig

if TYPE_CHECKING:
    pass


# --- Fixtures ---


@pytest.fixture
def claude_config_available() -> None:
    """Check that Claude Code is configured on the host."""
    credentials_path = Path.home() / ".claude" / ".credentials.json"
    if not credentials_path.exists():
        pytest.skip("Claude Code not configured (no ~/.claude/.credentials.json)")

    # Verify credentials have a token
    try:
        credentials = json.loads(credentials_path.read_text())
        oauth = credentials.get("claudeAiOauth", {})
        if not oauth.get("accessToken"):
            pytest.skip("Claude Code credentials missing access token")
    except (json.JSONDecodeError, KeyError):
        pytest.skip("Claude Code credentials file is invalid")


def _ensure_docker_running() -> bool:
    """Start Docker Desktop if not running. Returns True if Docker is available."""
    # Check if Docker is already running
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
    """Create a temporary test project with a simple Python file to modify."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    # Create a simple Python file that Claude will modify
    python_file = project_dir / "calculator.py"
    python_file.write_text('''"""Simple calculator module."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
''')

    # Create a minimal pyproject.toml
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text("""[project]
name = "test-project"
version = "0.1.0"
requires-python = ">=3.12"
""")

    return project_dir


@pytest.fixture
def sandbox_dir(tmp_path: Path, test_project: Path) -> Path:
    """Generate sandbox configuration in a temporary directory (isolated Claude config)."""
    return _create_sandbox(tmp_path, test_project, use_host_claude_config=False)


@pytest.fixture
def sandbox_dir_with_host_claude(tmp_path: Path, test_project: Path) -> Path:
    """Generate sandbox configuration that mounts host's ~/.claude for OAuth auth."""
    return _create_sandbox(tmp_path, test_project, use_host_claude_config=True)


def _create_sandbox(tmp_path: Path, test_project: Path, use_host_claude_config: bool) -> Path:
    """Helper to create sandbox configuration."""
    sandbox_path = tmp_path / "sandbox"
    sandbox_path.mkdir()

    # Minimal profile for faster builds
    profile = ProfileConfig(
        name="integration-test",
        description="Minimal profile for integration testing",
        python=PythonConfig(version="3.12"),
        system_packages=["git", "curl"],
        node_packages=["@anthropic-ai/claude-code"],
        uvx_tools=[],
        github_releases={},
    )

    mount = MountSpec(host_path=test_project, mode="rw")

    generator = SandboxGenerator(
        profile=profile,
        mounts=[mount],
        sandbox_name="integration-test",
        use_host_claude_config=use_host_claude_config,
    )

    generator.generate(sandbox_path)
    return sandbox_path


@pytest.fixture
def unique_project_name() -> str:
    """Generate a unique project name to avoid container conflicts."""
    return f"integration-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def docker_cleanup(sandbox_dir: Path, unique_project_name: str) -> Iterator[None]:
    """Clean up Docker resources after test."""
    yield

    # Stop and remove container
    subprocess.run(
        ["docker", "compose", "-p", unique_project_name, "down", "-v", "--remove-orphans"],
        cwd=sandbox_dir,
        capture_output=True,
        timeout=60,
    )

    # Remove image
    subprocess.run(
        ["docker", "rmi", "-f", f"{unique_project_name}-dev"],
        capture_output=True,
        timeout=30,
    )


# --- Tests ---


@pytest.mark.integration
class TestSandboxIntegration:
    """Integration tests for SandboxGenerator with real Docker execution."""

    # Timeouts
    BUILD_TIMEOUT = 600  # 10 minutes for Docker build
    CLAUDE_TIMEOUT = 180  # 3 minutes for Claude execution

    def test_sandbox_generates_valid_docker_config(
        self,
        sandbox_dir: Path,
    ) -> None:
        """Verify sandbox generates valid Docker Compose configuration."""
        # Verify all expected files exist
        assert (sandbox_dir / ".devcontainer" / "Dockerfile").exists()
        assert (sandbox_dir / "docker-compose.yml").exists()
        assert (sandbox_dir / ".env.example").exists()
        assert (sandbox_dir / ".sops.yaml").exists()

    def test_sandbox_docker_compose_validates(
        self,
        docker_available: None,
        sandbox_dir: Path,
    ) -> None:
        """Verify docker compose config is valid."""
        result = subprocess.run(
            ["docker", "compose", "config"],
            cwd=sandbox_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"docker compose config failed: {result.stderr}"

    def test_sandbox_container_builds(
        self,
        docker_available: None,
        sandbox_dir: Path,
        unique_project_name: str,
        docker_cleanup: None,
    ) -> None:
        """Verify sandbox Docker container builds successfully."""
        result = subprocess.run(
            ["docker", "compose", "-p", unique_project_name, "build", "--no-cache"],
            cwd=sandbox_dir,
            capture_output=True,
            text=True,
            timeout=self.BUILD_TIMEOUT,
        )
        assert result.returncode == 0, f"Docker build failed: {result.stderr}"

    def test_claude_code_modifies_file(
        self,
        docker_available: None,
        claude_config_available: None,
        sandbox_dir_with_host_claude: Path,
        test_project: Path,
        unique_project_name: str,
    ) -> None:
        """Test that Claude Code can modify a file inside the container.

        Uses host's ~/.claude config for OAuth authentication.
        """
        sandbox_dir = sandbox_dir_with_host_claude

        # Cleanup fixture - register cleanup to run after test
        def cleanup() -> None:
            subprocess.run(
                ["docker", "compose", "-p", unique_project_name, "down", "-v", "--remove-orphans"],
                cwd=sandbox_dir,
                capture_output=True,
                timeout=60,
            )
            subprocess.run(
                ["docker", "rmi", "-f", f"{unique_project_name}-dev"],
                capture_output=True,
                timeout=30,
            )

        try:
            # Build the container first
            build_result = subprocess.run(
                ["docker", "compose", "-p", unique_project_name, "build"],
                cwd=sandbox_dir,
                capture_output=True,
                text=True,
                timeout=self.BUILD_TIMEOUT,
            )
            assert build_result.returncode == 0, f"Build failed: {build_result.stderr}"

            # The task for Claude Code - add a subtract function
            task = (
                "Add a subtract function to calculator.py that takes two integers "
                "a and b, and returns a - b. Include a docstring. "
                "Do not ask questions, just make the change and exit."
            )

            # Run Claude Code non-interactively (uses mounted ~/.claude for auth)
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-p",
                    unique_project_name,
                    "run",
                    "--rm",
                    "-T",
                    "dev",
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    task,
                ],
                cwd=sandbox_dir,
                capture_output=True,
                text=True,
                timeout=self.CLAUDE_TIMEOUT,
            )

            # Log output for debugging
            print(f"Claude stdout:\n{result.stdout}")
            print(f"Claude stderr:\n{result.stderr}")
            print(f"Claude exit code: {result.returncode}")

            # Verify the modification was made
            calculator_path = test_project / "calculator.py"
            content = calculator_path.read_text()

            # Assert the subtract function was added
            assert "def subtract" in content, (
                f"subtract function not found in modified file.\n"
                f"File content:\n{content}\n"
                f"Claude output:\n{result.stdout}"
            )
        finally:
            cleanup()
