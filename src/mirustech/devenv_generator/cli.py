"""CLI entry point for devenv-generator."""

import atexit
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import rich_click as click
import structlog
import yaml
from rich.console import Console
from rich.table import Table

from mirustech.devenv_generator.application.use_cases.build_or_pull import (
    BuildOrPullImageUseCase,
)
from mirustech.devenv_generator.generator import (
    DevEnvGenerator,
    SandboxGenerator,
    compute_build_hash,
    get_bundled_profile,
    load_profile,
)
from mirustech.devenv_generator.models import ImageSpec, MountSpec, ProfileConfig
from mirustech.devenv_generator.settings import (
    AuthMethod,
    ensure_config_dir,
    get_config_path,
    get_settings,
)

# Configure structlog for CLI
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
)

console = Console()
logger = structlog.get_logger()

# Default sandbox location
SANDBOXES_DIR = Path("~/.local/share/devenv-sandboxes").expanduser()


def _get_sandbox_dir(name: str) -> Path:
    """Get the sandbox directory for a given name."""
    return SANDBOXES_DIR / name


def _list_sandboxes() -> list[tuple[str, Path, bool]]:
    """List all sandboxes with their running status.

    Returns list of (name, path, is_running) tuples.
    """
    if not SANDBOXES_DIR.exists():
        return []

    sandboxes = []
    for path in SANDBOXES_DIR.iterdir():
        if path.is_dir() and (path / "docker-compose.yml").exists():
            name = path.name
            is_running = _is_sandbox_running(name, path)
            sandboxes.append((name, path, is_running))

    return sorted(sandboxes, key=lambda x: x[0])


def _is_sandbox_running(name: str, sandbox_dir: Path) -> bool:
    """Check if a sandbox container is running."""
    try:
        result = subprocess.run(
            ["docker", "compose", "-p", name, "ps", "-q"],
            cwd=sandbox_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _detect_python_version(project_path: Path) -> str | None:
    """Auto-detect Python version from project files."""
    # Check .python-version
    python_version_file = project_path / ".python-version"
    if python_version_file.exists():
        version = python_version_file.read_text().strip()
        if version:
            return version

    # Check pyproject.toml
    pyproject_file = project_path / "pyproject.toml"
    if pyproject_file.exists():
        try:
            import tomllib
            with open(pyproject_file, "rb") as f:
                data = tomllib.load(f)

            # Try requires-python
            requires_python = data.get("project", {}).get("requires-python", "")
            if requires_python:
                # Parse ">=3.12" or ">=3.12,<4" etc.
                import re
                match = re.search(r"(\d+\.\d+)", requires_python)
                if match:
                    return match.group(1)
        except Exception:
            pass

    return None


def _load_profile(profile: str) -> ProfileConfig:
    """Load profile from file or bundled profiles."""
    profile_path = Path(profile)
    if profile_path.exists() and profile_path.suffix in (".yaml", ".yml"):
        config = load_profile(profile_path)
        console.print(f"[dim]Profile:[/dim] {profile_path}")
        return config

    try:
        config = get_bundled_profile(profile)
        console.print(f"[dim]Profile:[/dim] {profile}")
        return config
    except FileNotFoundError:
        console.print(f"[red]Profile not found:[/red] {profile}")
        console.print("Use 'devenv profiles list' to see available profiles")
        raise SystemExit(1)


def _ensure_docker_running() -> bool:
    """Ensure Docker is running, starting Docker Desktop if needed."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Try to start Docker Desktop (macOS)
    console.print("[dim]Starting Docker Desktop...[/dim]")
    try:
        subprocess.run(["open", "-a", "Docker"], capture_output=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Wait for Docker to start
    import time
    for _ in range(30):
        time.sleep(2)
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return False


# Global reference to GPG forwarder process for cleanup
_gpg_forwarder_process: subprocess.Popen | None = None

# Global reference to Serena MCP server process for cleanup
_serena_process: subprocess.Popen | None = None


def _start_serena_server(port: int = 9121) -> subprocess.Popen | None:
    """Start Serena MCP server in HTTP mode on host.

    Returns the subprocess if started, None if failed.
    """
    global _serena_process

    # Check if uvx is available
    if not shutil.which("uvx"):
        console.print("[yellow]Warning: uvx not installed, Serena server disabled[/yellow]")
        console.print("[dim]Install with: curl -LsSf https://astral.sh/uv/install.sh | sh[/dim]")
        return None

    # Check if already running on the port
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            console.print(f"[dim]Serena already running on port {port}[/dim]")
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Start Serena in HTTP mode
    try:
        console.print(f"[dim]Starting Serena MCP server on port {port}...[/dim]")
        proc = subprocess.Popen(
            [
                "uvx",
                "--from", "git+https://github.com/oraios/serena",
                "serena", "start-mcp-server",
                "--transport", "streamable-http",
                "--port", str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _serena_process = proc

        # Register cleanup
        def cleanup_serena():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()

        atexit.register(cleanup_serena)

        # Wait for server to start
        time.sleep(3)

        console.print(f"[dim]Serena MCP server running on http://localhost:{port}[/dim]")
        return proc
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to start Serena server: {e}[/yellow]")
        return None


def _start_gpg_forwarder(port: int = 9876) -> subprocess.Popen | None:
    """Start GPG agent socket forwarder on the host.

    Returns the subprocess if started, None if GPG agent socket not found.
    """
    global _gpg_forwarder_process

    # Check if socat is available
    if not shutil.which("socat"):
        console.print("[yellow]Warning: socat not installed, GPG forwarding disabled[/yellow]")
        console.print("[dim]Install with: brew install socat[/dim]")
        return None

    # Find GPG agent socket
    gpg_socket = None
    possible_paths = [
        Path("~/.gnupg/onlykey/S.gpg-agent").expanduser(),
        Path("~/.gnupg/S.gpg-agent").expanduser(),
    ]

    for path in possible_paths:
        if path.exists():
            gpg_socket = path
            break

    if not gpg_socket:
        # No GPG agent socket found, skip forwarding silently
        return None

    # Check if already listening on the port
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "socat" in result.stdout:
            # Already running
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Start socat forwarder
    try:
        proc = subprocess.Popen(
            [
                "socat",
                f"TCP-LISTEN:{port},fork,reuseaddr,bind=127.0.0.1",
                f"UNIX-CONNECT:{gpg_socket}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _gpg_forwarder_process = proc

        # Register cleanup
        def cleanup_forwarder():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()

        atexit.register(cleanup_forwarder)

        console.print(f"[dim]GPG agent forwarding: {gpg_socket} → port {port}[/dim]")
        return proc
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to start GPG forwarder: {e}[/yellow]")
        return None


def _run_sandbox(
    sandbox_name: str,
    sandbox_dir: Path,
    detach: bool = False,
    shell: bool = False,
    skip_build: bool = False,
    serena_port: int | None = None,
    no_cache: bool = False,
) -> None:
    """Run a sandbox container.

    Args:
        sandbox_name: Name of the sandbox.
        sandbox_dir: Directory containing docker-compose.yml.
        detach: Run in background.
        shell: Drop to shell instead of Claude.
        skip_build: Skip the build step (used when image was pulled from registry).
        serena_port: If set, pass SERENA_MCP_URL to container for HTTP mode.
        no_cache: Force rebuild without using Docker cache.
    """
    # Set Serena MCP URL if port is specified (server running on host)
    if serena_port:
        os.environ["SERENA_MCP_URL"] = f"http://host.docker.internal:{serena_port}/mcp"
    if not _ensure_docker_running():
        console.print("[red]Docker is not available. Please start Docker.[/red]")
        raise SystemExit(1)

    # Start GPG agent forwarder if available
    _start_gpg_forwarder()

    # Build if needed (skip if already pulled from registry)
    if not skip_build:
        console.print("[dim]Building container...[/dim]")
        build_cmd = ["docker", "compose", "-p", sandbox_name, "build"]
        if no_cache:
            build_cmd.append("--no-cache")
            console.print("[dim]  (forcing rebuild without cache)[/dim]")
        build_result = subprocess.run(
            build_cmd,
            cwd=sandbox_dir,
        )
        if build_result.returncode != 0:
            console.print("[red]Build failed[/red]")
            raise SystemExit(1)

    if detach:
        # Start in background
        console.print(f"[dim]Starting {sandbox_name} in background...[/dim]")
        result = subprocess.run(
            ["docker", "compose", "-p", sandbox_name, "up", "-d"],
            cwd=sandbox_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]Failed to start:[/red]\n{result.stderr}")
            raise SystemExit(1)

        console.print()
        console.print(f"[bold green]✓ Sandbox running:[/bold green] {sandbox_name}")
        console.print()
        console.print("[bold]Attach:[/bold]")
        console.print(f"  devenv attach {sandbox_name}")
        console.print()
        console.print("[bold]Stop:[/bold]")
        console.print(f"  devenv stop {sandbox_name}")
    else:
        # Run in foreground (exec into container)
        console.print()
        if shell:
            console.print(f"[bold green]Starting shell in {sandbox_name}...[/bold green]")
            console.print("[dim]Press Ctrl+D to exit[/dim]")
            cmd = ["docker", "compose", "-p", sandbox_name, "run", "--rm", "dev", "/bin/zsh"]
        else:
            console.print(f"[bold green]Starting Claude Code in {sandbox_name}...[/bold green]")
            console.print("[dim]Installing dependencies and starting Claude...[/dim]")
            # No args = entrypoint runs uv sync then starts Claude
            cmd = ["docker", "compose", "-p", sandbox_name, "run", "--rm", "dev"]

        console.print()

        # Replace current process with docker compose
        os.chdir(sandbox_dir)
        os.execvp(cmd[0], cmd)


@click.group(invoke_without_command=True)
@click.version_option()
@click.pass_context
def main(ctx: click.Context) -> None:
    """Run Claude Code on your projects in an isolated Docker container.

    \b
    Usage:
        devenv                      # Current directory, starts Claude
        devenv run ~/dev/myproject  # Specific project
        devenv run --shell          # Drop to shell instead of Claude

    \b
    Container management:
        devenv attach [name]        # Attach to running sandbox
        devenv stop [name]          # Stop running sandbox
        devenv status               # List sandboxes
        devenv rm [name]            # Remove sandbox

    \b
    Profiles:
        devenv profiles list        # List available profiles
        devenv profiles show NAME   # Show profile details
    """
    # Default to 'run' subcommand if no subcommand given
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@main.command("run")
@click.argument("paths", nargs=-1, type=click.Path())
@click.option(
    "--profile",
    "-p",
    default="mirustech",
    help="Profile name or path to YAML file (optional, auto-detects from project)",
)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output directory for sandbox files",
)
@click.option(
    "--name",
    "-n",
    default=None,
    help="Sandbox name",
)
@click.option(
    "--no-host-config",
    is_flag=True,
    default=False,
    help="Don't mount host ~/.claude (isolate from host Claude config)",
)
@click.option(
    "--detach",
    "-d",
    is_flag=True,
    default=False,
    help="Run container in background",
)
@click.option(
    "--shell",
    "-s",
    is_flag=True,
    default=False,
    help="Drop to shell instead of starting Claude",
)
@click.option(
    "--python",
    "python_version",
    default=None,
    help="Override Python version",
)
@click.option(
    "--push-to-registry",
    is_flag=True,
    default=False,
    help="Push image to registry after building",
)
@click.option(
    "--no-registry",
    is_flag=True,
    default=False,
    help="Disable registry even if configured",
)
@click.option(
    "--start-serena",
    is_flag=True,
    default=False,
    help="Start Serena MCP server on host in HTTP mode",
)
@click.option(
    "--serena-port",
    default=9121,
    help="Port for Serena HTTP server (default: 9121)",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Force rebuild without Docker cache",
)
def run(
    paths: tuple[str, ...],
    profile: str,
    output: str | None,
    name: str | None,
    no_host_config: bool,
    detach: bool,
    shell: bool,
    python_version: str | None,
    push_to_registry: bool,
    no_registry: bool,
    start_serena: bool,
    serena_port: int,
    no_cache: bool,
) -> None:
    """Run a sandbox with the specified project paths.

    \b
    Usage:
        devenv run                  # Current directory
        devenv run ~/dev/myproject  # Specific project
        devenv run --shell          # Drop to shell instead of Claude
        devenv run -d               # Run in background

    \b
    Mount modes:
        /path           Read-write (default)
        /path:ro        Read-only (safe exploration)
        /path:cow       Copy-on-write (changes discarded on exit)
    """
    # Default to current directory if no paths given
    if not paths:
        paths = (".",)

    # Parse mount specifications
    mount_specs = []
    for path_str in paths:
        try:
            spec = MountSpec.from_string(path_str)
            if not spec.host_path.exists():
                console.print(f"[red]Path does not exist:[/red] {spec.host_path}")
                raise SystemExit(1)
            if not spec.host_path.is_dir():
                console.print(f"[red]Path is not a directory:[/red] {spec.host_path}")
                raise SystemExit(1)
            mount_specs.append(spec)
        except Exception as e:
            console.print(f"[red]Invalid path:[/red] {path_str}")
            console.print(f"  Error: {e}")
            raise SystemExit(1)

    # Determine sandbox name
    sandbox_name = name or mount_specs[0].host_path.name

    # Determine output directory
    if output is None:
        output_path = _get_sandbox_dir(sandbox_name)
    else:
        output_path = Path(output).resolve()

    # Auto-detect Python version if not specified
    if python_version is None:
        detected = _detect_python_version(mount_specs[0].host_path)
        if detected:
            python_version = detected
            console.print(f"[dim]Detected Python:[/dim] {python_version}")

    # Load profile
    config = _load_profile(profile)

    # Override Python version if detected or specified
    if python_version:
        config.python.version = python_version

    # Load settings to check for registry configuration
    settings = get_settings()
    image_spec: ImageSpec | None = None

    # Check if build configuration changed BEFORE generating files
    # The build hash includes: profile config + Dockerfile template + docker-compose template
    build_hash_path = output_path / ".devcontainer" / ".build-hash"
    current_build_hash = compute_build_hash(config)
    auto_no_cache = False
    skip_build = False
    config_changed = False

    # Check if Docker image already exists
    image_result = subprocess.run(
        ["docker", "images", "-q", f"{sandbox_name}-dev:latest"],
        capture_output=True,
        text=True,
    )
    image_exists = bool(image_result.stdout.strip())

    # If image doesn't exist, we definitely need to build
    if not image_exists:
        console.print("[dim]No image found, will build[/dim]")
        config_changed = True
    # Compare with stored hash (before generating new files)
    elif build_hash_path.exists():
        stored_hash = build_hash_path.read_text().strip()
        if stored_hash != current_build_hash:
            console.print(
                "[yellow]⚠ Build configuration changed - rebuild required[/yellow]"
            )
            console.print("[dim]Changes detected in profile or templates[/dim]")
            config_changed = True
            auto_no_cache = True
        elif not no_cache:
            # Image exists and config unchanged - can potentially skip build
            console.print("[dim]Build configuration unchanged[/dim]")
    else:
        # No stored hash - first build or old sandbox
        # Image exists but no hash - force rebuild to be safe
        console.print(
            "[yellow]No build hash found - forcing rebuild for safety[/yellow]"
        )
        auto_no_cache = True
        config_changed = True

    # Use registry if enabled and not disabled via flag
    if settings.registry.enabled and not no_registry:
        use_case = BuildOrPullImageUseCase()
        auto_push = push_to_registry or settings.registry.auto_push

        # Generate sandbox first so we have the docker-compose.yml
        generator = SandboxGenerator(
            profile=config,
            mounts=mount_specs,
            sandbox_name=sandbox_name,
            use_host_claude_config=not no_host_config,
        )
        generator.generate(output_path)

        # Try to pull or build with registry support
        result = use_case.execute(
            project_path=mount_specs[0].host_path,
            project_name=sandbox_name,
            registry_config=settings.registry,
            sandbox_dir=output_path,
            sandbox_name=sandbox_name,
            auto_push=auto_push,
        )

        if result.image_spec:
            image_spec = result.image_spec
            skip_build = True  # Image pulled from registry
            # Regenerate docker-compose with image_spec
            generator = SandboxGenerator(
                profile=config,
                mounts=mount_specs,
                sandbox_name=sandbox_name,
                use_host_claude_config=not no_host_config,
                image_spec=image_spec,
            )
            generator.generate(output_path)
    else:
        # Generate sandbox without registry support
        generator = SandboxGenerator(
            profile=config,
            mounts=mount_specs,
            sandbox_name=sandbox_name,
            use_host_claude_config=not no_host_config,
        )
        generator.generate(output_path)

    console.print()
    console.print(f"[bold green]✓ Sandbox ready:[/bold green] {sandbox_name}")

    console.print("[dim]Mounts:[/dim]")
    for spec in mount_specs:
        mode_str = {"rw": "", "ro": " (ro)", "cow": " (cow)"}[spec.mode]
        console.print(f"  {spec.host_path} → {spec.container_path}{mode_str}")

    # Start Serena MCP server on host if requested
    if start_serena:
        _start_serena_server(port=serena_port)

    # Determine if we can skip the build
    if not config_changed and image_exists and not no_cache and not skip_build:
        console.print("[dim]Image up-to-date, skipping build[/dim]")
        skip_build = True

    # Run the sandbox
    _run_sandbox(
        sandbox_name,
        output_path,
        detach=detach,
        shell=shell,
        skip_build=skip_build,
        serena_port=serena_port if start_serena else None,
        no_cache=no_cache or auto_no_cache,
    )


@main.command("attach")
@click.argument("name", required=False)
def attach_sandbox(name: str | None) -> None:
    """Attach to a running sandbox.

    If no name is provided, attaches to the sandbox matching the current directory name.
    """
    if name is None:
        name = Path.cwd().name

    sandbox_dir = _get_sandbox_dir(name)

    if not sandbox_dir.exists():
        console.print(f"[red]Sandbox not found:[/red] {name}")
        console.print("Use 'devenv status' to list available sandboxes")
        raise SystemExit(1)

    if not _is_sandbox_running(name, sandbox_dir):
        console.print(f"[yellow]Sandbox is not running:[/yellow] {name}")
        console.print(f"Start it with: devenv {name}")
        raise SystemExit(1)

    console.print(f"[bold green]Attaching to {name}...[/bold green]")
    console.print("[dim]Press Ctrl+P, Ctrl+Q to detach[/dim]")
    console.print()

    # Exec into the running container
    os.execvp(
        "docker",
        ["docker", "compose", "-p", name, "exec", "dev", "/bin/zsh"],
    )


@main.command("stop")
@click.argument("name", required=False)
def stop_sandbox(name: str | None) -> None:
    """Stop a running sandbox.

    If no name is provided, stops the sandbox matching the current directory name.
    """
    if name is None:
        name = Path.cwd().name

    sandbox_dir = _get_sandbox_dir(name)

    if not sandbox_dir.exists():
        console.print(f"[red]Sandbox not found:[/red] {name}")
        raise SystemExit(1)

    console.print(f"[dim]Stopping {name}...[/dim]")
    result = subprocess.run(
        ["docker", "compose", "-p", name, "down"],
        cwd=sandbox_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        console.print(f"[bold green]✓ Stopped:[/bold green] {name}")
    else:
        console.print(f"[red]Failed to stop:[/red]\n{result.stderr}")
        raise SystemExit(1)


@main.command("start")
@click.argument("name", required=False)
@click.option(
    "--detach",
    "-d",
    is_flag=True,
    default=False,
    help="Run container in background",
)
@click.option(
    "--shell",
    "-s",
    is_flag=True,
    default=False,
    help="Drop to shell instead of starting Claude",
)
def start_sandbox(name: str | None, detach: bool, shell: bool) -> None:
    """Start an existing sandbox without regenerating config.

    If no name is provided, starts the sandbox matching the current directory name.

    \b
    Examples:
        devenv start myproject      # Start existing sandbox
        devenv start myproject -d   # Start in background
        devenv start myproject -s   # Start with shell
    """
    if name is None:
        name = Path.cwd().name

    sandbox_dir = _get_sandbox_dir(name)

    if not sandbox_dir.exists():
        console.print(f"[red]Sandbox not found:[/red] {name}")
        console.print(f"Create it with: devenv run {name}")
        raise SystemExit(1)

    if not (sandbox_dir / "docker-compose.yml").exists():
        console.print(f"[red]No docker-compose.yml in sandbox:[/red] {name}")
        console.print(f"Regenerate with: devenv run {name}")
        raise SystemExit(1)

    if _is_sandbox_running(name, sandbox_dir):
        console.print(f"[yellow]Sandbox already running:[/yellow] {name}")
        console.print(f"Attach with: devenv attach {name}")
        raise SystemExit(1)

    console.print(f"[bold green]Starting {name}...[/bold green]")
    _run_sandbox(name, sandbox_dir, detach=detach, shell=shell, skip_build=False, no_cache=False)


@main.command("cd")
@click.argument("name", required=False)
def cd_sandbox(name: str | None) -> None:
    """Spawn a subshell in the sandbox directory.

    If no name is provided, uses the sandbox matching the current directory name.

    \b
    Examples:
        devenv cd myproject    # Opens shell in ~/.local/share/devenv-sandboxes/myproject
        devenv cd              # Uses current directory name
    """
    if name is None:
        name = Path.cwd().name

    sandbox_dir = _get_sandbox_dir(name)

    if not sandbox_dir.exists():
        console.print(f"[red]Sandbox not found:[/red] {name}")
        console.print(f"Create it with: devenv run {name}")
        raise SystemExit(1)

    # Get user's shell
    shell = os.environ.get("SHELL", "/bin/bash")

    console.print(f"[dim]Entering {sandbox_dir}[/dim]")
    console.print("[dim]Type 'exit' to return[/dim]")

    # Spawn subshell in sandbox directory
    os.chdir(sandbox_dir)
    os.execvp(shell, [shell])


def _get_dir_size(path: Path) -> int:
    """Get total size of a directory in bytes."""
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    return total


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


def _check_docker_installed() -> tuple[bool, str]:
    """Check if Docker is installed."""
    result = subprocess.run(
        ["docker", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        version = result.stdout.strip()
        return True, f"Docker installed: {version}"
    return False, "Docker not found in PATH"


def _check_docker_running() -> tuple[bool, str]:
    """Check if Docker daemon is running."""
    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, "Docker daemon is running"
    return False, "Docker daemon not running. Try: docker desktop or sudo systemctl start docker"


def _check_docker_compose() -> tuple[bool, str]:
    """Check if Docker Compose is available."""
    # Try compose plugin first
    result = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        version = result.stdout.strip()
        return True, f"Docker Compose available: {version}"
    
    # Try standalone docker-compose
    result = subprocess.run(
        ["docker-compose", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        version = result.stdout.strip()
        return True, f"Docker Compose available: {version}"
    
    return False, "Docker Compose not found"


def _check_disk_space() -> tuple[bool, str]:
    """Check available disk space."""
    sandboxes_dir = SANDBOXES_DIR
    if not sandboxes_dir.exists():
        sandboxes_dir.mkdir(parents=True, exist_ok=True)
    
    stat = os.statvfs(sandboxes_dir)
    available_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
    
    if available_gb < 1:
        return False, f"Low disk space: {available_gb:.1f}GB available (recommend 5GB+)"
    elif available_gb < 5:
        return True, f"Disk space adequate: {available_gb:.1f}GB available (recommend 5GB+)"
    else:
        return True, f"Disk space good: {available_gb:.1f}GB available"


def _check_claude_auth() -> tuple[bool, str]:
    """Check if Claude authentication is configured."""
    # Check for OAuth token
    oauth_token = os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if oauth_token:
        return True, "Claude OAuth token found in environment"
    
    # Check for API key
    api_key = os.getenv("ANTHROPIC_AUTH_TOKEN")
    if api_key:
        return True, "Anthropic API key found in environment"
    
    # Check for credentials file
    creds_file = Path.home() / ".claude" / ".credentials.json"
    if creds_file.exists():
        return True, "Claude credentials file found"
    
    return False, "No Claude authentication found. Run: claude login"


def _check_claude_dir() -> tuple[bool, str]:
    """Check if ~/.claude directory exists and is accessible."""
    claude_dir = Path.home() / ".claude"
    if not claude_dir.exists():
        return False, "~/.claude directory not found. Run: claude login"
    
    if not os.access(claude_dir, os.R_OK):
        return False, f"~/.claude directory not readable. Check permissions: {claude_dir}"
    
    return True, "~/.claude directory exists and is accessible"


def _check_happy_config() -> tuple[bool, str]:
    """Check if Happy Coder config exists."""
    happy_dir = Path.home() / ".happy"
    if not happy_dir.exists():
        return True, "~/.happy directory not found (optional)"
    
    if not os.access(happy_dir, os.R_OK):
        return False, f"~/.happy directory not readable. Check permissions: {happy_dir}"
    
    # Check for access key
    access_key = happy_dir / "access.key"
    if access_key.exists():
        return True, "Happy Coder config found with access key"
    
    return True, "~/.happy directory exists (no access key)"


def _check_npm_installed() -> tuple[bool, str]:
    """Check if npm is installed (needed for building containers)."""
    result = subprocess.run(
        ["npm", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        version = result.stdout.strip()
        return True, f"npm installed: v{version}"
    return False, "npm not found (needed for container builds)"


def _check_git_installed() -> tuple[bool, str]:
    """Check if git is installed."""
    result = subprocess.run(
        ["git", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        version = result.stdout.strip()
        return True, f"Git installed: {version}"
    return False, "Git not found (recommended for devenv workflows)"



def _check_port_available(port: int, name: str) -> tuple[bool, str]:
    """Check if a port is available or already in use by expected service."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.close()
        return True, f"Port {port} available for {name}"
    except OSError:
        # Port in use - this is OK if it's being used by the expected service
        return True, f"Port {port} in use (may be {name} running)"


def _check_gpg_port() -> tuple[bool, str]:
    """Check if GPG forwarding port is available."""
    return _check_port_available(9876, "GPG agent forwarding")


def _check_serena_port() -> tuple[bool, str]:
    """Check if Serena MCP server port is available."""
    return _check_port_available(9121, "Serena MCP HTTP mode")


def _check_profile_valid() -> tuple[bool, str]:
    """Check if the default profile is valid."""
    try:
        config = get_bundled_profile("mirustech")
        return True, f"Default profile 'mirustech' is valid (Python {config.python.version})"
    except Exception as e:
        return False, f"Default profile invalid: {e}"


def _check_registry_connectivity() -> tuple[bool, str]:
    """Check if registry is configured and accessible."""
    try:
        settings = get_settings()
        if not settings.registry.enabled:
            return True, "Registry not configured (using local builds)"
        
        # Try to ping the registry
        registry_url = settings.registry.url
        import urllib.request
        import urllib.error
        
        try:
            # Just check if registry URL is reachable
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


def _check_container_health(sandbox_name: str | None = None) -> tuple[bool, str]:
    """Check if a container can be created and runs successfully."""
    # Find any devenv container
    result = subprocess.run(
        ["docker", "ps", "--filter", "name=devenv", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or not result.stdout.strip():
        return True, "No containers running (health check skipped)"

    container_names = result.stdout.strip().split("\n")
    container_name = container_names[0]

    try:
        # Try to run a simple command in the container
        result = subprocess.run(
            ["docker", "exec", container_name, "sh", "-c",
             "which claude >/dev/null 2>&1 && which happy >/dev/null 2>&1 && python --version"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            python_version = result.stdout.strip()
            return True, f"Container healthy (claude, happy, {python_version})"
        else:
            # Check what's missing
            missing = []
            for tool in ["claude", "happy", "python"]:
                check = subprocess.run(
                    ["docker", "exec", container_name, "which", tool],
                    capture_output=True,
                )
                if check.returncode != 0:
                    missing.append(tool)

            if missing:
                return False, f"Container missing tools: {', '.join(missing)}"
            else:
                return False, f"Container health check failed: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "Container health check timed out"
    except Exception as e:
        return True, f"Could not check container health: {e} (not critical)"


def _check_mcp_servers() -> tuple[bool, str]:
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


def _check_docker_socket() -> tuple[bool, str]:
    """Check if Docker socket is accessible."""
    socket_path = Path("/var/run/docker.sock")
    if not socket_path.exists():
        return False, "Docker socket not found at /var/run/docker.sock"
    
    if not os.access(socket_path, os.R_OK | os.W_OK):
        return False, "Docker socket not accessible (check permissions)"
    
    return True, "Docker socket accessible"


def _get_image_size(image_name: str) -> int | None:
    """Get the size of a Docker image in bytes."""
    result = subprocess.run(
        ["docker", "image", "inspect", image_name, "--format", "{{.Size}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None
    return None


@main.command("status")
def status() -> None:
    """List all sandboxes and their status."""
    sandboxes = _list_sandboxes()

    if not sandboxes:
        console.print("[dim]No sandboxes found.[/dim]")
        console.print("Create one with: devenv /path/to/project")
        return

    table = Table(title="Sandboxes")
    table.add_column("Name", style="cyan")
    table.add_column("Status")
    table.add_column("Size", justify="right")
    table.add_column("Image", justify="right")
    table.add_column("Modified", style="dim")

    for name, path, is_running in sandboxes:
        status_str = "[green]running[/green]" if is_running else "[dim]stopped[/dim]"

        # Get directory size
        dir_size = _get_dir_size(path)
        size_str = _format_size(dir_size)

        # Get image size
        image_name = f"{name}-dev:latest"
        image_size = _get_image_size(image_name)
        image_str = _format_size(image_size) if image_size else "[dim]—[/dim]"

        # Get last modified time
        try:
            mtime = path.stat().st_mtime
            modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
        except OSError:
            modified = "—"

        table.add_row(name, status_str, size_str, image_str, modified)

    console.print(table)

    # Show total disk usage
    total_sandbox_size = sum(_get_dir_size(path) for _, path, _ in sandboxes)
    console.print(f"\n[dim]Total sandbox configs: {_format_size(total_sandbox_size)}[/dim]")


@main.command("rm")
@click.argument("name", required=False)
@click.option("--force", "-f", is_flag=True, help="Force removal even if running")
def remove_sandbox(name: str | None, force: bool) -> None:
    """Remove a sandbox.

    If no name is provided, removes the sandbox matching the current directory name.
    """
    if name is None:
        name = Path.cwd().name

    sandbox_dir = _get_sandbox_dir(name)

    if not sandbox_dir.exists():
        console.print(f"[red]Sandbox not found:[/red] {name}")
        raise SystemExit(1)

    # Check if running
    if _is_sandbox_running(name, sandbox_dir):
        if not force:
            console.print(f"[yellow]Sandbox is running:[/yellow] {name}")
            console.print("Stop it first with: devenv stop")
            console.print("Or use --force to stop and remove")
            raise SystemExit(1)

        # Stop first
        console.print(f"[dim]Stopping {name}...[/dim]")
        subprocess.run(
            ["docker", "compose", "-p", name, "down", "-v"],
            cwd=sandbox_dir,
            capture_output=True,
        )

    # Remove the directory
    shutil.rmtree(sandbox_dir)

    console.print(f"[bold green]✓ Removed:[/bold green] {name}")


@main.command("clean")
@click.option(
    "--stopped", "-s", is_flag=True, help="Remove stopped sandboxes"
)
@click.option(
    "--images", "-i", is_flag=True, help="Remove unused devenv images"
)
@click.option(
    "--all", "-a", "all_", is_flag=True, help="Remove everything (stopped sandboxes + images)"
)
@click.option(
    "--dry-run", "-n", is_flag=True, help="Show what would be removed without removing"
)
def clean(stopped: bool, images: bool, all_: bool, dry_run: bool) -> None:
    """Clean up unused sandboxes and images.

    By default, shows what can be cleaned. Use flags to specify what to remove.

    Examples:

        devenv clean              # Show what can be cleaned

        devenv clean --stopped    # Remove stopped sandboxes

        devenv clean --images     # Remove unused devenv images

        devenv clean --all        # Remove everything
    """
    if all_:
        stopped = True
        images = True

    # If no flags, just show status
    show_only = not (stopped or images)

    sandboxes = _list_sandboxes()
    stopped_sandboxes = [(n, p) for n, p, running in sandboxes if not running]

    # Get devenv images
    result = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.ID}}"],
        capture_output=True,
        text=True,
    )
    devenv_images: list[tuple[str, str, str]] = []
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if line and "-dev:" in line:
                parts = line.split("\t")
                if len(parts) >= 3:
                    devenv_images.append((parts[0], parts[1], parts[2]))

    # Find unused images (no matching sandbox)
    sandbox_names = {n for n, _, _ in sandboxes}
    unused_images = [
        (name, size, id_)
        for name, size, id_ in devenv_images
        if name.replace("-dev:latest", "") not in sandbox_names
    ]

    # Get dangling images
    dangling_result = subprocess.run(
        ["docker", "images", "-f", "dangling=true", "--format", "{{.ID}}\t{{.Size}}"],
        capture_output=True,
        text=True,
    )
    dangling_images: list[tuple[str, str]] = []
    if dangling_result.returncode == 0:
        for line in dangling_result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t")
                if len(parts) >= 2:
                    dangling_images.append((parts[0], parts[1]))

    if show_only:
        console.print("[bold]Available for cleanup:[/bold]\n")

        if stopped_sandboxes:
            console.print(f"[yellow]Stopped sandboxes:[/yellow] {len(stopped_sandboxes)}")
            for name, path in stopped_sandboxes:
                size = _format_size(_get_dir_size(path))
                console.print(f"  • {name} ({size})")
        else:
            console.print("[dim]No stopped sandboxes[/dim]")

        console.print()

        if unused_images:
            console.print(f"[yellow]Unused devenv images:[/yellow] {len(unused_images)}")
            for name, size, _ in unused_images:
                console.print(f"  • {name} ({size})")
        else:
            console.print("[dim]No unused devenv images[/dim]")

        if dangling_images:
            console.print(f"\n[yellow]Dangling images:[/yellow] {len(dangling_images)}")

        console.print("\n[dim]Use --stopped, --images, or --all to clean up[/dim]")
        return

    removed_count = 0

    # Remove stopped sandboxes
    if stopped and stopped_sandboxes:
        console.print("[bold]Removing stopped sandboxes...[/bold]")
        for name, path in stopped_sandboxes:
            if dry_run:
                console.print(f"  [dim]Would remove:[/dim] {name}")
            else:
                shutil.rmtree(path)
                console.print(f"  [green]✓[/green] Removed {name}")
                removed_count += 1

    # Remove unused images
    if images:
        if unused_images:
            console.print("[bold]Removing unused devenv images...[/bold]")
            for name, size, id_ in unused_images:
                if dry_run:
                    console.print(f"  [dim]Would remove:[/dim] {name} ({size})")
                else:
                    result = subprocess.run(
                        ["docker", "rmi", name],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        console.print(f"  [green]✓[/green] Removed {name} ({size})")
                        removed_count += 1
                    else:
                        console.print(f"  [red]✗[/red] Failed to remove {name}")

        if dangling_images:
            console.print("[bold]Removing dangling images...[/bold]")
            for id_, size in dangling_images:
                if dry_run:
                    console.print(f"  [dim]Would remove:[/dim] {id_[:12]} ({size})")
                else:
                    result = subprocess.run(
                        ["docker", "rmi", id_],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        console.print(f"  [green]✓[/green] Removed {id_[:12]} ({size})")
                        removed_count += 1

    if dry_run:
        console.print("\n[dim]Dry run - nothing was removed[/dim]")
    elif removed_count > 0:
        console.print(f"\n[bold green]✓ Cleaned up {removed_count} items[/bold green]")
    else:
        console.print("\n[dim]Nothing to clean[/dim]")



@main.command("doctor")
@click.option(
    "--fix", is_flag=True, help="Attempt to fix issues automatically"
)
@click.option(
    "--verbose", "-v", is_flag=True, help="Show detailed information"
)
@click.option(
    "--container", is_flag=True, help="Include container health checks"
)
def doctor(fix: bool, verbose: bool, container: bool) -> None:
    """Check system prerequisites and diagnose issues.
    
    Verifies that your system has all the necessary components for devenv
    to work properly, including Docker, authentication, and disk space.
    
    Examples:
    
        devenv doctor              # Check all prerequisites
        
        devenv doctor --verbose    # Show detailed information
        
        devenv doctor --container  # Include container health checks
        
        devenv doctor --fix        # Attempt to fix issues automatically
    """
    console.print("[bold]Checking devenv prerequisites...[/bold]\n")
    
    # Track results
    critical_passed = True
    warnings = []
    
    # Define checks with severity levels
    checks = [
        # Critical checks (must pass)
        ("critical", "Docker installed", _check_docker_installed),
        ("critical", "Docker running", _check_docker_running),
        ("critical", "Docker socket", _check_docker_socket),
        ("critical", "Docker Compose", _check_docker_compose),
        ("critical", "Claude authentication", _check_claude_auth),
        
        # Warning checks (should pass)
        ("warning", "~/.claude directory", _check_claude_dir),
        ("warning", "Disk space", _check_disk_space),
        ("warning", "Default profile valid", _check_profile_valid),
        
        # Info checks (nice to have)
        ("info", "npm installed", _check_npm_installed),
        ("info", "Git installed", _check_git_installed),
        ("info", "Happy Coder config", _check_happy_config),
        ("info", "MCP servers", _check_mcp_servers),
        ("info", "GPG port (9876)", _check_gpg_port),
        ("info", "Serena port (9121)", _check_serena_port),
        ("info", "Registry connectivity", _check_registry_connectivity),
    ]
    
    # Add container check if requested
    if container:
        checks.append(("warning", "Container health", _check_container_health))
    
    # Run checks
    for severity, name, check_fn in checks:
        try:
            passed, message = check_fn()
            
            # Format output based on result
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
                
        except Exception as e:
            console.print(f"[red]✗[/red] {name}: Error running check: {e}")
            if severity == "critical":
                critical_passed = False
    
    console.print()
    
    # Summary
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
        raise SystemExit(1)
    
    # Check for stale images if verbose
    if verbose:
        console.print("\n[bold]Additional information:[/bold]")
        
        # List sandboxes
        sandboxes = _list_sandboxes()
        console.print(f"Active sandboxes: {len(sandboxes)}")
        
        # Check for unused images
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            devenv_images = [line for line in result.stdout.strip().split("\n") if "-dev:" in line]
            console.print(f"Devenv images: {len(devenv_images)}")
        
        # Check Docker disk usage
        result = subprocess.run(
            ["docker", "system", "df"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("\n[dim]Docker disk usage:[/dim]")
            console.print(result.stdout)


@main.command("completions")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completions(shell: str) -> None:
    """Generate shell completion script.

    Outputs a shell script that enables tab completion for devenv commands.

    Examples:

        # Bash (add to ~/.bashrc):
        eval "$(devenv completions bash)"

        # Zsh (add to ~/.zshrc):
        eval "$(devenv completions zsh)"

        # Fish (add to ~/.config/fish/config.fish):
        devenv completions fish | source
    """
    import os
    import re

    # Get the completion script from click
    env_var = f"_{main.name.upper()}_COMPLETE"

    if shell == "bash":
        script = f'''
_devenv_completion() {{
    local IFS=$'\\n'
    COMPREPLY=( $( env COMP_WORDS="${{COMP_WORDS[*]}}" \\
                   COMP_CWORD=$COMP_CWORD \\
                   {env_var}=bash_complete $1 ) )
    return 0
}}

_devenv_sandbox_names() {{
    local sandboxes_dir="$HOME/.local/share/devenv-sandboxes"
    if [ -d "$sandboxes_dir" ]; then
        ls -1 "$sandboxes_dir" 2>/dev/null
    fi
}}

complete -F _devenv_completion -o default devenv
'''
    elif shell == "zsh":
        script = f'''
#compdef devenv

_devenv_sandbox_names() {{
    local sandboxes_dir="$HOME/.local/share/devenv-sandboxes"
    if [[ -d "$sandboxes_dir" ]]; then
        local sandboxes=($(ls -1 "$sandboxes_dir" 2>/dev/null))
        _describe 'sandbox' sandboxes
    fi
}}

_devenv() {{
    local state

    _arguments -C \\
        '1: :->command' \\
        '*: :->args'

    case $state in
        command)
            local commands=(
                'run:Run a sandbox for the given project paths'
                'attach:Attach to a running sandbox'
                'stop:Stop a running sandbox'
                'start:Start a stopped sandbox'
                'rm:Remove a sandbox'
                'status:List all sandboxes and their status'
                'clean:Clean up unused sandboxes and images'
                'cd:Change to sandbox directory'
                'new:Create a new project with devcontainer'
                'profiles:Manage profiles'
                'config:Manage configuration'
                'completions:Generate shell completion script'
            )
            _describe 'command' commands
            ;;
        args)
            case $words[2] in
                attach|stop|start|rm|cd)
                    _devenv_sandbox_names
                    ;;
                run|new)
                    _files -/
                    ;;
            esac
            ;;
    esac
}}

compdef _devenv devenv
'''
    elif shell == "fish":
        script = '''
function __fish_devenv_sandbox_names
    set -l sandboxes_dir "$HOME/.local/share/devenv-sandboxes"
    if test -d "$sandboxes_dir"
        ls -1 "$sandboxes_dir" 2>/dev/null
    end
end

# Disable file completion by default
complete -c devenv -f

# Commands
complete -c devenv -n "__fish_use_subcommand" -a "run" -d "Run a sandbox for the given project paths"
complete -c devenv -n "__fish_use_subcommand" -a "attach" -d "Attach to a running sandbox"
complete -c devenv -n "__fish_use_subcommand" -a "stop" -d "Stop a running sandbox"
complete -c devenv -n "__fish_use_subcommand" -a "start" -d "Start a stopped sandbox"
complete -c devenv -n "__fish_use_subcommand" -a "rm" -d "Remove a sandbox"
complete -c devenv -n "__fish_use_subcommand" -a "status" -d "List all sandboxes and their status"
complete -c devenv -n "__fish_use_subcommand" -a "clean" -d "Clean up unused sandboxes and images"
complete -c devenv -n "__fish_use_subcommand" -a "cd" -d "Change to sandbox directory"
complete -c devenv -n "__fish_use_subcommand" -a "new" -d "Create a new project with devcontainer"
complete -c devenv -n "__fish_use_subcommand" -a "profiles" -d "Manage profiles"
complete -c devenv -n "__fish_use_subcommand" -a "config" -d "Manage configuration"
complete -c devenv -n "__fish_use_subcommand" -a "completions" -d "Generate shell completion script"

# Sandbox name completion for relevant commands
complete -c devenv -n "__fish_seen_subcommand_from attach stop start rm cd" -a "(__fish_devenv_sandbox_names)"

# Directory completion for run and new
complete -c devenv -n "__fish_seen_subcommand_from run new" -a "(__fish_complete_directories)"
'''
    else:
        console.print(f"[red]Unsupported shell: {shell}[/red]")
        raise SystemExit(1)

    # Output the script
    click.echo(script.strip())


@main.command("new")
@click.argument("path", type=click.Path())
@click.option(
    "--profile",
    "-p",
    default="mirustech",
    help="Profile name or path to YAML file",
)
@click.option(
    "--name",
    "-n",
    default=None,
    help="Project name (default: directory name)",
)
@click.option(
    "--python-version",
    default=None,
    help="Override Python version",
)
def new_project(
    path: str,
    profile: str,
    name: str | None,
    python_version: str | None,
) -> None:
    """Create a new project with dev environment.

    This creates the dev environment files directly in the project directory,
    including VS Code devcontainer support.

    \b
    Example:
        devenv new ~/dev/my-new-app
    """
    output_path = Path(path).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    project_name = name or output_path.name
    config = _load_profile(profile)

    if python_version:
        config.python.version = python_version

    generator = DevEnvGenerator(config, project_name=project_name)
    generated = generator.generate(output_path)

    console.print()
    console.print(f"[bold green]✓ Project created:[/bold green] {project_name}")
    console.print(f"[dim]Location: {output_path}[/dim]")
    console.print()

    console.print("[bold]Generated:[/bold]")
    for file_path in generated:
        rel_path = file_path.relative_to(output_path)
        console.print(f"  {rel_path}")

    console.print()
    console.print("[bold]Run:[/bold]")
    console.print(f"  cd {output_path} && docker compose run --rm dev")


@main.group()
def profiles() -> None:
    """Manage profiles."""
    pass


@profiles.command("list")
def list_profiles() -> None:
    """List available profiles."""
    table = Table(title="Available Profiles")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Python")

    # Bundled profiles
    bundled = ["mirustech"]
    for profile_name in bundled:
        try:
            profile = get_bundled_profile(profile_name)
            table.add_row(
                profile_name,
                profile.description or "(no description)",
                profile.python.version,
            )
        except FileNotFoundError:
            pass

    # User profiles
    user_profiles_dir = Path("~/.config/devenv-generator/profiles").expanduser()
    if user_profiles_dir.exists():
        for yaml_file in user_profiles_dir.glob("*.yaml"):
            try:
                profile = load_profile(yaml_file)
                table.add_row(
                    yaml_file.stem,
                    profile.description or "(no description)",
                    profile.python.version,
                )
            except Exception:
                pass

    console.print(table)


@profiles.command("show")
@click.argument("name")
def show_profile(name: str) -> None:
    """Show profile details."""
    try:
        profile = get_bundled_profile(name)
    except FileNotFoundError:
        profile_path = Path(f"~/.config/devenv-generator/profiles/{name}.yaml").expanduser()
        try:
            profile = load_profile(profile_path)
        except FileNotFoundError:
            console.print(f"[red]Profile not found:[/red] {name}")
            raise SystemExit(1)

    console.print(f"[bold cyan]{profile.name}[/bold cyan]")
    if profile.description:
        console.print(f"[dim]{profile.description}[/dim]")
    console.print()

    console.print("[bold]Python:[/bold]")
    console.print(f"  Version: {profile.python.version}")
    if profile.python.packages:
        console.print("  Packages:")
        for pkg in profile.python.packages:
            console.print(f"    - {pkg}")

    console.print()
    console.print("[bold]uvx Tools:[/bold]")
    for tool in profile.uvx_tools:
        console.print(f"  - {tool}")

    console.print()
    console.print("[bold]System Packages:[/bold]")
    for pkg in profile.system_packages:
        console.print(f"  - {pkg}")

    console.print()
    console.print("[bold]Node Packages:[/bold]")
    for pkg in profile.node_packages:
        console.print(f"  - {pkg}")


@profiles.command("create")
@click.argument("name")
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output path (default: ~/.config/devenv-generator/profiles/)",
)
def create_profile(name: str, output: str | None) -> None:
    """Create a new profile template."""
    if output:
        output_path = Path(output)
    else:
        output_path = Path(f"~/.config/devenv-generator/profiles/{name}.yaml").expanduser()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    profile = ProfileConfig(
        name=name,
        description=f"Custom profile: {name}",
    )

    with output_path.open("w") as f:
        yaml.dump(profile.model_dump(), f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]Created profile:[/green] {output_path}")
    console.print("Edit this file to customize your development environment.")


# Config command group
@main.group()
def config() -> None:
    """Manage devenv configuration."""
    pass


@config.command("show")
def config_show() -> None:
    """Display current configuration."""
    settings = get_settings()
    config_path = get_config_path()

    console.print("[bold]Registry Configuration:[/bold]")
    console.print(f"  Enabled: {settings.registry.enabled}")
    console.print(f"  URL: {settings.registry.url}")
    console.print(f"  Auth Method: {settings.registry.auth_method.value}")
    console.print(f"  Auto-push: {settings.registry.auto_push}")
    console.print(f"  Timeout: {settings.registry.timeout}s")

    if settings.registry.username:
        console.print(f"  Username: {settings.registry.username}")

    console.print()
    if config_path.exists():
        console.print(f"[dim]Config file: {config_path}[/dim]")
    else:
        console.print(f"[dim]Config file: {config_path} (not created yet)[/dim]")


@config.command("set-registry")
def config_set_registry() -> None:
    """Configure container registry settings interactively."""
    from rich.prompt import Confirm, Prompt

    console.print()
    console.print("[bold]Registry Setup Wizard[/bold]")
    console.print("─" * 25)
    console.print()

    # Get registry URL
    registry_url = Prompt.ask(
        "Registry URL",
        default="git.mirus-tech.com",
    )

    # Get auth method
    console.print()
    console.print("[bold]Authentication method:[/bold]")
    console.print("  1. existing - Use existing docker login (recommended)")
    console.print("  2. stored   - Store credentials in config file")
    console.print("  3. prompt   - Prompt for credentials each time")
    auth_choice = Prompt.ask(
        "Choice",
        choices=["1", "2", "3", "existing", "stored", "prompt"],
        default="1",
    )

    auth_map = {"1": "existing", "2": "stored", "3": "prompt"}
    auth_method = auth_map.get(auth_choice, auth_choice)

    username = None
    password = None
    if auth_method == "stored":
        console.print()
        username = Prompt.ask("Username")
        password = Prompt.ask("Password/Token", password=True)

    # Auto-push setting
    console.print()
    auto_push = Confirm.ask("Auto-push after build?", default=False)

    # Write config file
    config_dir = ensure_config_dir()
    config_path = config_dir / "config.env"

    lines = [
        "# devenv-generator configuration",
        "# Generated by: devenv config set-registry",
        "",
        "DEVENV_REGISTRY__ENABLED=true",
        f"DEVENV_REGISTRY__URL={registry_url}",
        f"DEVENV_REGISTRY__AUTH_METHOD={auth_method}",
        f"DEVENV_REGISTRY__AUTO_PUSH={str(auto_push).lower()}",
    ]

    if username:
        lines.append(f"DEVENV_REGISTRY__USERNAME={username}")
    if password:
        lines.append(f"DEVENV_REGISTRY__PASSWORD={password}")
        console.print()
        console.print("[yellow]Warning: Password stored in plaintext.[/yellow]")
        console.print("[dim]Consider encrypting with SOPS: sops encrypt --in-place ~/.config/devenv-generator/config.env[/dim]")

    config_path.write_text("\n".join(lines) + "\n")

    console.print()
    console.print(f"[green]✓ Configuration saved to {config_path}[/green]")


@config.command("edit")
def config_edit() -> None:
    """Open config file in editor."""
    config_dir = ensure_config_dir()
    config_path = config_dir / "config.env"

    # Create default config if doesn't exist
    if not config_path.exists():
        default_content = """# devenv-generator configuration
# See: devenv config set-registry

# Enable registry support
DEVENV_REGISTRY__ENABLED=false

# Registry URL
DEVENV_REGISTRY__URL=git.mirus-tech.com

# Authentication method: existing, stored, prompt
DEVENV_REGISTRY__AUTH_METHOD=existing

# Auto-push after build
DEVENV_REGISTRY__AUTO_PUSH=false
"""
        config_path.write_text(default_content)
        console.print(f"[dim]Created default config at {config_path}[/dim]")

    editor = os.environ.get("EDITOR", "vi")
    console.print(f"[dim]Opening {config_path} with {editor}...[/dim]")
    os.execvp(editor, [editor, str(config_path)])


# Keep old commands as aliases for backwards compatibility
@main.command("generate", hidden=True)
@click.option("--profile", "-p", default="mirustech")
@click.option("--output", "-o", default=".")
@click.option("--project-name", "-n", default=None)
@click.option("--python-version", default=None)
@click.pass_context
def generate(ctx: click.Context, profile: str, output: str, project_name: str | None, python_version: str | None) -> None:
    """[Deprecated] Use 'devenv new' instead."""
    console.print("[yellow]Note: 'devenv generate' is deprecated. Use 'devenv new' instead.[/yellow]")
    ctx.invoke(new_project, path=output, profile=profile, name=project_name, python_version=python_version)


@main.command("sandbox", hidden=True)
@click.option("--mount", "-m", "mounts", multiple=True, required=True)
@click.option("--name", "-n", "sandbox_name", default=None)
@click.option("--output", "-o", default=None)
@click.option("--profile", "-p", default="mirustech")
@click.option("--use-host-claude-config", is_flag=True, default=False)
@click.pass_context
def sandbox_cmd(
    ctx: click.Context,
    mounts: tuple[str, ...],
    sandbox_name: str | None,
    output: str | None,
    profile: str,
    use_host_claude_config: bool,
) -> None:
    """[Deprecated] Just use 'devenv /path/to/project' instead."""
    console.print("[yellow]Note: 'devenv sandbox' is deprecated. Just use 'devenv /path' instead.[/yellow]")
    ctx.invoke(
        main,
        paths=mounts,
        profile=profile,
        output=output,
        name=sandbox_name,
        no_host_config=not use_host_claude_config,
        detach=False,
        shell=False,
        python_version=None,
    )


if __name__ == "__main__":
    main()
