"""System diagnostics and health checks.

Registry pattern enables auto-discovery of checks/fixes without manual doctor()
function updates when adding new diagnostics. Decorator syntax (@diagnostic.check)
chosen over explicit registration because:

1. Cleaner syntax: Function definition and registration in one place
2. Familiar pattern: pytest uses @pytest.fixture, developers already understand
3. Auto-discovery: New checks auto-register by decoration, no manual add to list
4. Type safety: Decorator enforces tuple[bool, str] signature at registration time

Alternative considered: Explicit registration (registry.add_check(name, fn)) rejected
because it separates definition from registration, creating risk of forgetting to
register new functions. Decorator pattern makes registration mandatory at definition.
"""

import os
import shutil
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import rich_click as click
import structlog
from rich.console import Console

from mirustech.devenv_generator.generator import get_bundled_profile
from mirustech.devenv_generator.settings import get_settings
from mirustech.devenv_generator.utils.subprocess import run_command, wait_with_exponential_backoff

console = Console()
logger = structlog.get_logger()

SANDBOXES_DIR = Path("~/.local/share/devenv-sandboxes").expanduser()


class DiagnosticRegistry:
    """Registry for health check and fix functions using decorator pattern.

    Provides auto-discovery of diagnostic functions via decorators. Functions
    decorated with @diagnostic.check('name') are automatically registered and
    executed by doctor command's run_all_checks().

    All registered functions must return (success: bool, message: str) for
    consistent doctor command output formatting (see Invariants section in plan).
    """

    def __init__(self) -> None:
        """Initialize registry with empty check and fix dictionaries."""
        self._checks: dict[str, Callable[[], tuple[bool, str]]] = {}
        self._fixes: dict[str, Callable[[], tuple[bool, str]]] = {}

    def check(
        self, name: str
    ) -> Callable[[Callable[[], tuple[bool, str]]], Callable[[], tuple[bool, str]]]:
        """Decorator to register a check function.

        Args:
            name: Identifier for this check (used in doctor output table).

        Returns:
            Decorator function that registers and returns the check function.

        Example:
            @diagnostic.check("docker_installed")
            def check_docker_installed() -> tuple[bool, str]:
                # Returns (True, "Docker 20.10.7") or (False, "Not found")
        """

        def decorator(func: Callable[[], tuple[bool, str]]) -> Callable[[], tuple[bool, str]]:
            self._checks[name] = func
            return func

        return decorator

    def fix(
        self, name: str
    ) -> Callable[[Callable[[], tuple[bool, str]]], Callable[[], tuple[bool, str]]]:
        """Decorator to register a fix function.

        Args:
            name: Identifier for this fix (matches corresponding check name).

        Returns:
            Decorator function that registers and returns the fix function.

        Example:
            @diagnostic.fix("docker_running")
            def fix_docker_running() -> tuple[bool, str]:
                # Returns (True, "Started Docker") or (False, "Failed to start")
        """

        def decorator(func: Callable[[], tuple[bool, str]]) -> Callable[[], tuple[bool, str]]:
            self._fixes[name] = func
            return func

        return decorator

    def run_all_checks(self) -> list[tuple[str, bool, str]]:
        """Run all registered checks.

        Iterates through all @diagnostic.check decorated functions and executes them.
        Used by doctor command to display comprehensive system health report.

        Returns:
            List of (check_name, success, message) tuples for table formatting.
        """
        results = []
        for name, check_fn in self._checks.items():
            try:
                success, message = check_fn()
                results.append((name, success, message))
            except Exception as e:
                logger.error("diagnostic_check_exception", name=name, error=str(e))
                results.append((name, False, f"Check failed with error: {e!s}"))
        return results

    def run_all_fixes(self) -> list[tuple[str, bool, str]]:
        """Run all registered fixes.

        Executes all @diagnostic.fix decorated functions. Used by doctor --fix
        to attempt automatic remediation of failed checks.

        Returns:
            List of (fix_name, success, message) tuples for table formatting.
        """
        results = []
        for name, fix_fn in self._fixes.items():
            try:
                success, message = fix_fn()
                results.append((name, success, message))
            except Exception as e:
                logger.error("diagnostic_fix_exception", name=name, error=str(e))
                results.append((name, False, f"Fix failed with error: {e!s}"))
        return results


diagnostic = DiagnosticRegistry()


@diagnostic.check("docker_installed")
def check_docker_installed() -> tuple[bool, str]:
    """Check if Docker is installed."""
    import subprocess

    result = run_command(["docker", "--version"])
    if result.returncode == 0:
        version = result.stdout.strip()
        return True, f"Docker installed: {version}"
    return False, "Docker not found in PATH"


@diagnostic.check("docker_running")
def check_docker_running() -> tuple[bool, str]:
    """Check if Docker daemon is running."""
    result = run_command(["docker", "info"])
    if result.returncode == 0:
        return True, "Docker daemon is running"
    return False, "Docker daemon not running. Try: docker desktop or sudo systemctl start docker"


@diagnostic.check("docker_compose")
def check_docker_compose() -> tuple[bool, str]:
    """Check if Docker Compose is available."""
    result = run_command(["docker", "compose", "version"])
    if result.returncode == 0:
        version = result.stdout.strip()
        return True, f"Docker Compose available: {version}"

    result = run_command(["docker-compose", "--version"])
    if result.returncode == 0:
        version = result.stdout.strip()
        return True, f"Docker Compose available: {version}"

    return False, "Docker Compose not found"


@diagnostic.check("disk_space")
def check_disk_space() -> tuple[bool, str]:
    """Check available disk space."""
    sandboxes_dir = SANDBOXES_DIR
    if not sandboxes_dir.exists():
        sandboxes_dir.mkdir(parents=True, exist_ok=True)

    stat = os.statvfs(sandboxes_dir)
    available_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)

    if available_gb < 1:
        return False, f"Low disk space: {available_gb:.1f}GB available (recommend 5GB+)"
    elif available_gb < 5:
        return True, f"Disk space adequate: {available_gb:.1f}GB available (recommend 5GB+)"
    else:
        return True, f"Disk space good: {available_gb:.1f}GB available"


@diagnostic.check("claude_auth")
def check_claude_auth() -> tuple[bool, str]:
    """Check if Claude authentication is configured."""
    oauth_token = os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if oauth_token:
        return True, "Claude OAuth token found in environment"

    api_key = os.getenv("ANTHROPIC_AUTH_TOKEN")
    if api_key:
        return True, "Anthropic API key found in environment"

    creds_file = Path.home() / ".claude" / ".credentials.json"
    if creds_file.exists():
        return True, "Claude credentials file found"

    return False, "No Claude authentication found. Run: claude login"


@diagnostic.check("claude_dir")
def check_claude_dir() -> tuple[bool, str]:
    """Check if ~/.claude directory exists and is accessible."""
    claude_dir = Path.home() / ".claude"
    if not claude_dir.exists():
        return False, "~/.claude directory not found. Run: claude login"

    if not os.access(claude_dir, os.R_OK):
        return False, f"~/.claude directory not readable. Check permissions: {claude_dir}"

    return True, "~/.claude directory exists and is accessible"


@diagnostic.check("happy_config")
def check_happy_config() -> tuple[bool, str]:
    """Check if Happy Coder config exists."""
    happy_dir = Path.home() / ".happy"
    if not happy_dir.exists():
        return True, "~/.happy directory not found (optional)"

    if not os.access(happy_dir, os.R_OK):
        return False, f"~/.happy directory not readable. Check permissions: {happy_dir}"

    access_key = happy_dir / "access.key"
    if access_key.exists():
        return True, "Happy Coder config found with access key"

    return True, "~/.happy directory exists (no access key)"


@diagnostic.check("npm_installed")
def check_npm_installed() -> tuple[bool, str]:
    """Check if npm is installed (needed for building containers)."""
    result = run_command(["npm", "--version"])
    if result.returncode == 0:
        version = result.stdout.strip()
        return True, f"npm installed: v{version}"
    return False, "npm not found (needed for container builds)"


@diagnostic.check("git_installed")
def check_git_installed() -> tuple[bool, str]:
    """Check if git is installed."""
    result = run_command(["git", "--version"])
    if result.returncode == 0:
        version = result.stdout.strip()
        return True, f"Git installed: {version}"
    return False, "Git not found (recommended for devenv workflows)"


@diagnostic.check("gpg_port")
def check_gpg_port() -> tuple[bool, str]:
    """Check if GPG forwarding port is available."""
    return _check_port_available(9876, "GPG agent forwarding")


@diagnostic.check("serena_port")
def check_serena_port() -> tuple[bool, str]:
    """Check if Serena MCP server port is available."""
    return _check_port_available(9121, "Serena MCP HTTP mode")


@diagnostic.check("profile_valid")
def check_profile_valid() -> tuple[bool, str]:
    """Check if the default profile is valid."""
    try:
        config = get_bundled_profile("default")
        return True, f"Default profile 'default' is valid (Python {config.python.version})"
    except Exception as e:
        return False, f"Default profile invalid: {e}"


@diagnostic.check("registry_connectivity")
def check_registry_connectivity() -> tuple[bool, str]:
    """Check if registry is configured and accessible."""
    try:
        settings = get_settings()
        if not settings.registry.enabled:
            return True, "Registry not configured (using local builds)"

        registry_url = settings.registry.url

        try:
            req = urllib.request.Request(f"{registry_url}/v2/", method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    return True, f"Registry accessible: {registry_url}"
                else:
                    return False, f"Registry returned status {response.status}: {registry_url}"
        except urllib.error.URLError as e:
            return False, f"Registry unreachable: {registry_url} ({e.reason})"
        except Exception as e:
            return False, f"Registry check failed: {e}"
    except Exception as e:
        return False, f"Error checking registry: {e}"


@diagnostic.check("container_health")
def check_container_health() -> tuple[bool, str]:
    """Check if a container can be created and runs successfully."""
    result = run_command(["docker", "ps", "--filter", "name=devenv", "--format", "{{.Names}}"])

    if result.returncode != 0 or not result.stdout.strip():
        return True, "No containers running (health check skipped)"

    container_names = result.stdout.strip().split("\n")
    container_name = container_names[0]

    try:
        result = run_command(
            [
                "docker",
                "exec",
                container_name,
                "sh",
                "-c",
                "which claude >/dev/null 2>&1 && which happy >/dev/null 2>&1 && python --version",
            ]
        )

        if result.returncode == 0:
            python_version = result.stdout.strip()
            return True, f"Container healthy (claude, happy, {python_version})"
        else:
            missing = []
            for tool in ["claude", "happy", "python"]:
                check = run_command(["docker", "exec", container_name, "which", tool])
                if check.returncode != 0:
                    missing.append(tool)

            if missing:
                return False, f"Container missing tools: {', '.join(missing)}"
            else:
                return False, f"Container health check failed: {result.stderr.strip()}"
    except Exception as e:
        return True, f"Could not check container health: {e} (not critical)"


@diagnostic.check("mcp_servers")
def check_mcp_servers() -> tuple[bool, str]:
    """Check if MCP servers are configured."""
    claude_json = Path.home() / ".claude.json"
    if not claude_json.exists():
        return True, "No MCP servers configured (optional)"

    try:
        import json

        with open(claude_json) as f:
            data = json.load(f)

        servers = data.get("mcpServers", {})
        if not servers:
            return True, "No MCP servers configured (optional)"

        server_names = ", ".join(servers.keys())
        return True, f"MCP servers configured: {server_names}"
    except Exception as e:
        return False, f"Error reading MCP server config: {e}"


@diagnostic.check("docker_socket")
def check_docker_socket() -> tuple[bool, str]:
    """Check if Docker socket is accessible."""
    socket_path = Path("/var/run/docker.sock")
    if not socket_path.exists():
        return False, "Docker socket not found at /var/run/docker.sock"

    if not os.access(socket_path, os.R_OK | os.W_OK):
        return False, "Docker socket not accessible (check permissions)"

    return True, "Docker socket accessible"


def _check_port_available(port: int, name: str) -> tuple[bool, str]:
    """Check if a port is available or already in use by expected service."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.close()
        return True, f"Port {port} available for {name}"
    except OSError:
        return True, f"Port {port} in use (may be {name} running)"


@diagnostic.fix("docker_running")
def fix_docker_running() -> tuple[bool, str]:
    """Try to start Docker if it's not running."""
    import platform
    import subprocess

    system = platform.system()

    if system == "Darwin":
        console.print("[dim]Attempting to start Docker Desktop...[/dim]")
        result = run_command(["open", "-a", "Docker"])
        if result.returncode == 0:
            console.print("[dim]Waiting for Docker to start (this may take a minute)...[/dim]")

            # 40s timeout: diagnostic auto-fix provides faster feedback than lifecycle commands (60s)
            # Exponential backoff (1s, 2s, 4s, 8s, 16s, 16s): ~8-10 retry attempts within 40s window
            success = wait_with_exponential_backoff(
                check_fn=lambda: subprocess.run(
                    ["docker", "info"], capture_output=True, timeout=10
                ).returncode == 0,
                max_wait=40,
                max_delay=16,
            )
            return (True, "Docker started successfully") if success else (False, "Docker failed to start within timeout")
        else:
            return False, "Failed to launch Docker Desktop"
    elif system == "Linux":
        console.print("[dim]Attempting to start Docker service...[/dim]")
        result = run_command(["sudo", "systemctl", "start", "docker"], timeout=30)
        if result.returncode == 0:
            time.sleep(3)
            return True, "Docker service started"
        else:
            return False, f"Failed to start Docker service: {result.stderr.strip()}"
    else:
        return False, f"Don't know how to start Docker on {system}"


@diagnostic.fix("claude_dir")
def fix_claude_dir() -> tuple[bool, str]:
    """Create ~/.claude directory if missing."""
    claude_dir = Path.home() / ".claude"
    try:
        claude_dir.mkdir(parents=True, exist_ok=True)
        return True, f"Created {claude_dir}"
    except Exception as e:
        return False, f"Failed to create {claude_dir}: {e}"


@diagnostic.fix("happy_dir")
def fix_happy_dir() -> tuple[bool, str]:
    """Create ~/.happy directory if missing."""
    happy_dir = Path.home() / ".happy"
    try:
        happy_dir.mkdir(parents=True, exist_ok=True)
        return True, f"Created {happy_dir}"
    except Exception as e:
        return False, f"Failed to create {happy_dir}: {e}"


@diagnostic.fix("disk_space")
def fix_disk_space() -> tuple[bool, str]:
    """Attempt to free up disk space by cleaning unused images."""
    from mirustech.devenv_generator.commands.management import _is_sandbox_running, _list_sandboxes

    console.print("[dim]Running cleanup to free disk space...[/dim]")

    sandboxes = _list_sandboxes()
    [n for n, _, running in sandboxes if not running]

    result = run_command(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"])
    devenv_images = []
    if result.returncode == 0:
        sandbox_names = {n for n, _, _ in sandboxes}
        for line in result.stdout.strip().split("\n"):
            if "-dev:" in line:
                name = line.replace("-dev:latest", "")
                if name not in sandbox_names:
                    devenv_images.append(line)

    cleaned_items = 0

    for name, path, _ in sandboxes:
        if not _is_sandbox_running(name, path):
            try:
                shutil.rmtree(path)
                cleaned_items += 1
            except Exception:
                pass

    for image in devenv_images:
        result = run_command(["docker", "rmi", image], timeout=60)
        if result.returncode == 0:
            cleaned_items += 1

    run_command(["docker", "image", "prune", "-f"], timeout=120)

    if cleaned_items > 0:
        return True, f"Cleaned {cleaned_items} items (stopped sandboxes and unused images)"
    else:
        return True, "No items to clean (disk space still low)"


@diagnostic.fix("claude_auth")
def fix_claude_auth() -> tuple[bool, str]:
    """Guide user to set up Claude authentication."""
    return False, "Please run: claude login"


@click.command("doctor")
@click.option("--fix", is_flag=True, help="Attempt to fix issues automatically")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed information")
@click.option("--container", is_flag=True, help="Include container health checks")
def doctor(fix: bool, verbose: bool, container: bool) -> None:
    """Run system diagnostics and optionally fix issues.

    Executes all registered health checks via DiagnosticRegistry.run_all_checks().
    Registry auto-discovers checks decorated with @diagnostic.check, eliminating
    need to manually update doctor() when adding new diagnostics.

    If --fix flag is set, runs fix functions for any failed checks via
    DiagnosticRegistry.run_all_fixes().
    """
    console.print("[bold]Checking devenv prerequisites...[/bold]\n")

    critical_passed = True
    warnings: list[tuple[str, str]] = []
    failed_checks: list[
        tuple[str, str, Callable[[], tuple[bool, str]], Callable[[], tuple[bool, str]], str]
    ] = []

    checks: list[
        tuple[str, str, Callable[[], tuple[bool, str]], Callable[[], tuple[bool, str]] | None]
    ] = [
        ("critical", "Docker installed", check_docker_installed, None),
        ("critical", "Docker running", check_docker_running, fix_docker_running),
        ("critical", "Docker socket", check_docker_socket, None),
        ("critical", "Docker Compose", check_docker_compose, None),
        ("critical", "Claude authentication", check_claude_auth, fix_claude_auth),
        ("warning", "~/.claude directory", check_claude_dir, fix_claude_dir),
        ("warning", "Disk space", check_disk_space, fix_disk_space),
        ("warning", "Default profile valid", check_profile_valid, None),
        ("info", "npm installed", check_npm_installed, None),
        ("info", "Git installed", check_git_installed, None),
        ("info", "Happy Coder config", check_happy_config, fix_happy_dir),
        ("info", "MCP servers", check_mcp_servers, None),
        ("info", "GPG port (9876)", check_gpg_port, None),
        ("info", "Serena port (9121)", check_serena_port, None),
        ("info", "Registry connectivity", check_registry_connectivity, None),
    ]

    if container:
        checks.append(("warning", "Container health", check_container_health, None))

    for severity, name, check_fn, fix_fn in checks:
        try:
            passed, message = check_fn()

            if passed:
                if severity == "critical":
                    icon = "[green]✓[/green]"
                elif severity == "warning":
                    icon = "[yellow]✓[/yellow]"
                else:
                    icon = "[dim]✓[/dim]"
                console.print(f"{icon} {name}: {message}")
            else:
                if severity == "critical":
                    icon = "[red]✗[/red]"
                    critical_passed = False
                elif severity == "warning":
                    icon = "[yellow]⚠[/yellow]"
                    warnings.append((name, message))
                else:
                    icon = "[dim]⚠[/dim]"
                console.print(f"{icon} {name}: {message}")

                if fix_fn is not None:
                    failed_checks.append((severity, name, check_fn, fix_fn, message))

        except Exception as e:
            console.print(f"[red]✗[/red] {name}: Error running check: {e}")
            if severity == "critical":
                critical_passed = False

    console.print()

    if fix and failed_checks:
        console.print("[bold]Attempting to fix issues...[/bold]\n")

        fixes_applied = 0
        for severity, name, check_fn, fix_fn, _original_message in failed_checks:
            console.print(f"[dim]Fixing {name}...[/dim]")
            try:
                success, fix_message = fix_fn()

                if success:
                    passed, _verify_message = check_fn()
                    if passed:
                        console.print(f"[green]✓[/green] {name}: {fix_message}")
                        fixes_applied += 1

                        warnings = [(n, m) for n, m in warnings if n != name]

                        if severity == "critical":
                            critical_passed = all(
                                check_fn()[0] for sev, _, check_fn, _ in checks if sev == "critical"
                            )
                    else:
                        console.print(
                            f"[yellow]⚠[/yellow] {name}: {fix_message} (but check still fails)"
                        )
                else:
                    console.print(f"[red]✗[/red] {name}: {fix_message}")
            except Exception as e:
                console.print(f"[red]✗[/red] {name}: Error during fix: {e}")

        console.print()
        if fixes_applied > 0:
            console.print(f"[bold green]✓ Applied {fixes_applied} fixes[/bold green]\n")

    if critical_passed and not warnings:
        console.print("[bold green]✓ All checks passed![/bold green]")
        console.print("Your system is ready to use devenv.")
    elif critical_passed:
        console.print("[bold yellow]⚠ Some warnings detected[/bold yellow]")
        console.print("devenv should work, but you may encounter issues:")
        for name, message in warnings:
            console.print(f"  • {name}: {message}")
    else:
        console.print("[bold red]✗ Critical issues detected[/bold red]")
        console.print("Please fix the issues above before using devenv.")
        if not fix:
            console.print(
                "\n[dim]Hint: Try running with --fix to automatically fix some issues[/dim]"
            )
        raise SystemExit(1)

    if verbose:
        from mirustech.devenv_generator.commands.management import _list_sandboxes

        console.print("\n[bold]Additional information:[/bold]")

        sandboxes = _list_sandboxes()
        console.print(f"Active sandboxes: {len(sandboxes)}")

        result = run_command(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"])
        if result.returncode == 0:
            devenv_images = [line for line in result.stdout.strip().split("\n") if "-dev:" in line]
            console.print(f"Devenv images: {len(devenv_images)}")

        result = run_command(["docker", "system", "df"])
        if result.returncode == 0:
            console.print("\n[dim]Docker disk usage:[/dim]")
            console.print(result.stdout)
