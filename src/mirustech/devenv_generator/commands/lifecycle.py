"""Sandbox lifecycle commands (run, attach, stop, start, cd)."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import rich_click as click
import structlog
from rich.console import Console

from mirustech.devenv_generator.application.use_cases.build_decision import (
    BuildDecisionUseCase,
)
from mirustech.devenv_generator.commands.management import (
    _force_cleanup_project_containers,
    _is_sandbox_running,
)
from mirustech.devenv_generator.models import MountSpec, PortConfig
from mirustech.devenv_generator.settings import get_settings
from mirustech.devenv_generator.utils.process_manager import ProcessManager
from mirustech.devenv_generator.utils.sandbox import (
    compose_project_name,
    get_sandbox_dir,
    load_profile_by_name,
)
from mirustech.devenv_generator.utils.subprocess import run_command, wait_with_exponential_backoff

console = Console()
logger = structlog.get_logger()

process_manager = ProcessManager()


def _detect_python_version(project_path: Path) -> str | None:
    """Auto-detect Python version from project files."""
    python_version_file = project_path / ".python-version"
    if python_version_file.exists():
        version = python_version_file.read_text().strip()
        if version:
            return version

    pyproject_file = project_path / "pyproject.toml"
    if pyproject_file.exists():
        try:
            import tomllib

            with open(pyproject_file, "rb") as f:
                data = tomllib.load(f)

            requires_python = data.get("project", {}).get("requires-python", "")
            if requires_python:
                import re

                match = re.search(r"(\d+\.\d+)", requires_python)
                if match:
                    return match.group(1)
        except (tomllib.TOMLDecodeError, KeyError):
            pass

    return None


def _parse_port_spec(spec: str) -> PortConfig:
    """Parse port specification string.

    Formats:
        8000              -> PortConfig(container=8000, host=8000, protocol='tcp')
        8080:3000         -> PortConfig(container=3000, host=8080, protocol='tcp')
        5432/tcp          -> PortConfig(container=5432, host=5432, protocol='tcp')
        8080:3000/udp     -> PortConfig(container=3000, host=8080, protocol='udp')
    """
    from typing import Literal

    # Parse protocol suffix
    protocol: Literal["tcp", "udp"] = "tcp"
    if "/" in spec:
        spec, proto_str = spec.rsplit("/", 1)
        if proto_str not in ("tcp", "udp"):
            console.print(f"[red]Invalid protocol:[/red] {proto_str}. Must be 'tcp' or 'udp'")
            console.print("[dim]Valid formats:[/dim]")
            console.print("  8000              Container and host both use 8000")
            console.print("  8080:3000         Host 8080 → container 3000")
            console.print("  5432/tcp          Explicit protocol")
            console.print("  8080:3000/udp     Host 8080 → container 3000 via UDP")
            raise SystemExit(1) from None
        protocol = proto_str  # type: ignore[assignment]  # Validated above

    # Parse host:container mapping
    try:
        if ":" in spec:
            host_str, container_str = spec.split(":", 1)
            host = int(host_str)
            container = int(container_str)
        else:
            container = int(spec)
            host = container
    except ValueError:
        console.print(f"[red]Invalid port specification:[/red] {spec}")
        console.print("[dim]Valid formats:[/dim]")
        console.print("  8000              Container and host both use 8000")
        console.print("  8080:3000         Host 8080 → container 3000")
        console.print("  5432/tcp          Explicit protocol")
        console.print("  8080:3000/udp     Host 8080 → container 3000 via UDP")
        raise SystemExit(1) from None

    return PortConfig(container=container, host=host, protocol=protocol)


def _check_port_conflicts(ports: list[PortConfig], sandbox_name: str) -> None:
    """Check if host ports are already in use.

    Raises:
        SystemExit: If any port is already bound.
    """

    for port_config in ports:
        host_port = port_config.host_port
        result = run_command(["lsof", "-i", f":{host_port}"], timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            console.print(f"[red]Port {host_port} already in use[/red]")
            console.print(f"[dim]Process using port:[/dim]\n{result.stdout}")
            console.print("\n[yellow]Options:[/yellow]")
            console.print(f"  1. Stop the process using port {host_port}")
            alt_port = host_port + 1
            console.print(
                f"  2. Use different host port: --expose-port {alt_port}:{port_config.container}"
            )
            console.print("  3. Disable ports: --no-ports")
            raise SystemExit(1)


def _ensure_docker_running() -> bool:
    """Ensure Docker is running, starting Docker Desktop if needed."""
    try:
        result = run_command(["docker", "info"])
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    console.print("[dim]Starting Docker Desktop...[/dim]")
    with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError):
        run_command(["open", "-a", "Docker"], timeout=5)

    # Exponential backoff (1s, 2s, 4s, 8s, 16s): detects fast startup in ~7s when ready
    # 60s timeout: accommodates macOS Docker Desktop startup (typically 15-45s)
    # 16s cap: allows 4-5 retry attempts within 60s window
    return wait_with_exponential_backoff(
        check_fn=lambda: run_command(["docker", "info"]).returncode == 0,
        max_wait=60,
        max_delay=16,
    )


def _start_serena_server(
    port: int = 9121, no_browser: bool = False
) -> subprocess.Popen[bytes] | None:
    """Start Serena MCP server in HTTP mode on host.

    Args:
        port: Port to run server on.
        no_browser: If True, don't open browser window.

    Returns the subprocess if started, None if failed.
    """
    if not shutil.which("uvx"):
        console.print("[yellow]Warning: uvx not installed, Serena server disabled[/yellow]")
        console.print("[dim]Install with: curl -LsSf https://astral.sh/uv/install.sh | sh[/dim]")
        return None

    try:
        result = run_command(["lsof", "-i", f":{port}"], timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            console.print(f"[dim]Serena already running on port {port}[/dim]")
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        console.print(f"[dim]Starting Serena MCP server on port {port}...[/dim]")
        cmd = [
            "uvx",
            "--from",
            "git+https://github.com/oraios/serena",
            "serena",
            "start-mcp-server",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
        ]

        if no_browser:
            cmd.extend(["--enable-web-dashboard", "False"])

        log_dir = Path("~/.local/share/devenv-sandboxes").expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        serena_log = log_dir / ".serena.log"
        log_file = serena_log.open("w")

        proc = process_manager.start(
            "serena",
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=log_file,
        )

        if proc is None:
            log_file.close()
            return None

        import urllib.error
        import urllib.request

        def _serena_responds(port: int) -> bool:
            """Return True when Serena's HTTP server accepts connections.

            A 406/405 response means uvicorn is up — Serena rejects GET /mcp with
            a method-not-allowed error, which is a successful startup signal.
            URLError means the port is not yet bound.
            """
            try:
                urllib.request.urlopen(f"http://localhost:{port}/mcp", timeout=2)
                return True
            except urllib.error.HTTPError:
                return True  # 4xx: server responded, startup complete
            except (urllib.error.URLError, OSError):
                return False  # port not yet bound

        # Fixed 3s sleep undershoots slow startup and overshoots fast startup.
        # wait_with_exponential_backoff (1s, 2s, 4s...) returns immediately when
        # Serena responds and tolerates startup up to max_wait without adding latency.
        started = wait_with_exponential_backoff(
            lambda: _serena_responds(port),
            max_wait=30,
        )
        if not started:
            console.print("[yellow]Warning: Serena started but is not responding[/yellow]")

        console.print(f"[dim]Serena MCP server running on http://localhost:{port}[/dim]")
        return proc
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to start Serena server: {e}[/yellow]")
        return None


def _start_gpg_forwarder(port: int = 9876) -> subprocess.Popen[bytes] | None:
    """Start GPG agent socket forwarder on the host.

    Args:
        port: Port to forward GPG agent to.

    Returns the subprocess if started, None if GPG agent socket not found.
    """
    if not shutil.which("socat"):
        console.print("[yellow]Warning: socat not installed, GPG forwarding disabled[/yellow]")
        console.print("[dim]Install with: brew install socat[/dim]")
        return None

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
        return None

    try:
        result = run_command(["lsof", "-i", f":{port}"], timeout=5)
        if "socat" in result.stdout:
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        proc = process_manager.start(
            "gpg_forwarder",
            [
                "socat",
                f"TCP-LISTEN:{port},fork,reuseaddr,bind=127.0.0.1",
                f"UNIX-CONNECT:{gpg_socket}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if proc is None:
            return None

        console.print(f"[dim]GPG agent forwarding: {gpg_socket} → port {port}[/dim]")
        return proc
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to start GPG forwarder: {e}[/yellow]")
        return None


def _export_keychain_credentials() -> bool:
    """Export Claude Code credentials from macOS Keychain to ~/.claude/.credentials.json.

    The native installer stores credentials in the OS keychain instead of a file.
    The container can't access macOS Keychain, so we export to a file that gets
    mounted into the container via the existing .claude-host bind mount.

    Returns True if credentials were exported, False otherwise.
    """
    import json
    import platform

    if platform.system() != "Darwin":
        return False

    creds_path = Path("~/.claude/.credentials.json").expanduser()

    try:
        result = run_command(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False

        # Validate it's proper JSON before writing
        creds = json.loads(result.stdout.strip())
        if "claudeAiOauth" not in creds:
            return False

        creds_path.write_text(json.dumps(creds))
        console.print("[dim]Exported Claude credentials from keychain[/dim]")
        return True
    except Exception as e:
        console.print(f"[yellow]Warning: Could not export keychain credentials: {e}[/yellow]")
        return False


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
    if serena_port:
        os.environ["SERENA_MCP_URL"] = f"http://host.docker.internal:{serena_port}/mcp"
    if not _ensure_docker_running():
        console.print("[red]Docker is not available. Please start Docker.[/red]")
        raise SystemExit(1)

    if not skip_build:
        console.print("[dim]Building container...[/dim]")
        build_cmd = ["docker", "compose", "-p", compose_project_name(sandbox_name), "build"]
        if no_cache:
            build_cmd.append("--no-cache")
            console.print("[dim]  (forcing rebuild without cache)[/dim]")
        console.print()  # Add blank line before build output
        build_result = run_command(build_cmd, cwd=sandbox_dir, timeout=600, stream_output=True)
        console.print()  # Add blank line after build output
        if build_result.returncode != 0:
            console.print("[red]Build failed - check output above for details[/red]")
            raise SystemExit(1)

    if detach:
        console.print(f"[dim]Starting {sandbox_name} in background...[/dim]")
        result = run_command(
            ["docker", "compose", "-p", compose_project_name(sandbox_name), "up", "-d"],
            cwd=sandbox_dir,
            timeout=300,
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
        console.print()
        if shell:
            console.print(f"[bold green]Starting shell in {sandbox_name}...[/bold green]")
            console.print("[dim]Press Ctrl+D to exit[/dim]")
            cmd = [
                "docker", "compose", "-p", compose_project_name(sandbox_name),
                "run", "--rm", "--service-ports", "dev", "/bin/zsh",
            ]
        else:
            console.print(f"[bold green]Starting Claude Code in {sandbox_name}...[/bold green]")
            console.print("[dim]Installing dependencies and starting Claude...[/dim]")
            cmd = [
                "docker", "compose", "-p", compose_project_name(sandbox_name),
                "run", "--rm", "--service-ports", "dev",
            ]

        console.print()

        # Sentinel: if subprocess.run raises (e.g. docker not in PATH),
        # result is still bound for sys.exit below
        run_result: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(cmd, returncode=1)
        try:
            # subprocess.run keeps Python alive; os.execvp would replace
            # the process, preventing finally-block cleanup of host-side
            # Serena and GPG forwarder processes
            run_result = subprocess.run(cmd, cwd=sandbox_dir)
        finally:
            process_manager.cleanup_all()
        sys.exit(run_result.returncode)


@click.command("run")
@click.argument("paths", nargs=-1, type=click.Path())
@click.option(
    "--profile",
    "-p",
    default="default",
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
    "--start-serena/--no-serena",
    default=None,
    help="Start Serena MCP server (default: from profile, usually enabled)",
)
@click.option(
    "--serena-port",
    type=int,
    default=None,
    help="Port for Serena HTTP server (default: from profile, usually 9121)",
)
@click.option(
    "--serena-browser/--no-serena-browser",
    default=None,
    help="Open/disable browser dashboard (default: from profile, usually disabled)",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Force rebuild without Docker cache",
)
@click.option(
    "--expose-port",
    "expose_ports",
    multiple=True,
    help="Expose additional ports (format: [host:]container[/protocol]).",
)
@click.option(
    "--no-ports",
    is_flag=True,
    default=False,
    help="Disable all port mappings from profile",
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
    start_serena: bool | None,
    serena_port: int | None,
    serena_browser: bool | None,
    no_cache: bool,
    expose_ports: tuple[str, ...],
    no_ports: bool,
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
    if not paths:
        paths = (".",)

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
            raise SystemExit(1) from None

    sandbox_name = name or mount_specs[0].host_path.name

    output_path = get_sandbox_dir(sandbox_name) if output is None else Path(output).resolve()

    if python_version is None:
        detected = _detect_python_version(mount_specs[0].host_path)
        if detected:
            python_version = detected
            console.print(f"[dim]Detected Python:[/dim] {python_version}")

    config = load_profile_by_name(profile)

    if python_version:
        config.python.version = python_version

    # Apply port overrides
    if no_ports:
        config.ports.ports = []
    elif expose_ports:
        runtime_ports = [_parse_port_spec(spec) for spec in expose_ports]
        config.ports.ports.extend(runtime_ports)

    # Check for port conflicts before starting
    if config.ports.ports:
        _check_port_conflicts(config.ports.ports, sandbox_name)

    effective_start_serena = start_serena if start_serena is not None else config.mcp.enable_serena
    effective_serena_port = serena_port if serena_port is not None else config.mcp.serena_port
    effective_serena_browser = (
        serena_browser if serena_browser is not None else config.mcp.serena_browser
    )

    settings = get_settings()

    # Execute build decision logic
    build_decision = BuildDecisionUseCase()
    decision_result = build_decision.execute(
        sandbox_name=sandbox_name,
        sandbox_dir=output_path,
        config=config,
        mount_specs=mount_specs,
        registry_config=settings.registry if settings.registry.enabled else None,
        no_cache=no_cache,
        no_registry=no_registry,
        no_host_config=no_host_config,
        push_to_registry=push_to_registry,
    )

    skip_build = decision_result.skip_build
    auto_no_cache = decision_result.auto_no_cache

    console.print()
    console.print(f"[bold green]✓ Sandbox ready:[/bold green] {sandbox_name}")

    console.print("[dim]Mounts:[/dim]")
    for spec in mount_specs:
        mode_str = {"rw": "", "ro": " (ro)", "cow": " (cow)"}[spec.mode]
        console.print(f"  {spec.host_path} → {spec.container_path}{mode_str}")

    if effective_start_serena:
        _start_serena_server(port=effective_serena_port, no_browser=not effective_serena_browser)

    _start_gpg_forwarder()

    if not no_host_config:
        _export_keychain_credentials()

    _run_sandbox(
        sandbox_name,
        output_path,
        detach=detach,
        shell=shell,
        skip_build=skip_build,
        serena_port=effective_serena_port if effective_start_serena else None,
        no_cache=no_cache or auto_no_cache,
    )


@click.command("attach")
@click.argument("name", required=False)
def attach_sandbox(name: str | None) -> None:
    """Attach to a running sandbox.

    If no name is provided, attaches to the sandbox matching the current directory name.
    """
    if name is None:
        name = Path.cwd().name

    sandbox_dir = get_sandbox_dir(name)

    if not sandbox_dir.exists():
        console.print(f"[red]Sandbox not found:[/red] {name}")
        console.print("Use 'devenv status' to list available sandboxes")
        raise SystemExit(1)

    if not _is_sandbox_running(name, sandbox_dir):
        console.print(f"[yellow]Sandbox is not running:[/yellow] {name}")
        console.print(f"Start it with: devenv {name}")
        raise SystemExit(1)

    console.print(f"[bold green]Attaching to {name}...[/bold green]")
    console.print("[dim]Exit the shell with 'exit' or Ctrl+D[/dim]")
    console.print("[dim]Note: If Claude Code exits unexpectedly, type 'claude' to restart[/dim]")
    console.print()

    # Use docker compose exec with interactive TTY
    cmd = ["docker", "compose", "-p", compose_project_name(name), "exec", "-it", "dev", "/bin/zsh"]
    result: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(cmd, returncode=1)
    try:
        result = subprocess.run(cmd)
    finally:
        process_manager.cleanup_all()
    sys.exit(result.returncode)


@click.command("stop")
@click.argument("name", required=False)
def stop_sandbox(name: str | None) -> None:
    """Stop a running sandbox.

    If no name is provided, stops the sandbox matching the current directory name.
    """
    if name is None:
        name = Path.cwd().name

    sandbox_dir = get_sandbox_dir(name)

    if not sandbox_dir.exists():
        console.print(f"[red]Sandbox not found:[/red] {name}")
        raise SystemExit(1)

    console.print(f"[dim]Stopping {name}...[/dim]")
    if _force_cleanup_project_containers(name, sandbox_dir):
        console.print(f"[bold green]✓ Stopped:[/bold green] {name}")
    else:
        console.print(f"[red]Failed to stop all containers for:[/red] {name}")
        console.print("Some containers may still be running. Check with: docker ps")
        raise SystemExit(1)


@click.command("start")
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
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Force rebuild without Docker cache",
)
def start_sandbox(name: str | None, detach: bool, shell: bool, no_cache: bool) -> None:
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

    sandbox_dir = get_sandbox_dir(name)

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

    # Host-side setup using profile defaults
    config = load_profile_by_name("default")

    if config.mcp.enable_serena:
        _start_serena_server(
            port=config.mcp.serena_port, no_browser=not config.mcp.serena_browser
        )
    _start_gpg_forwarder()
    _export_keychain_credentials()

    console.print(f"[bold green]Starting {name}...[/bold green]")
    _run_sandbox(
        name,
        sandbox_dir,
        detach=detach,
        shell=shell,
        skip_build=False,
        serena_port=config.mcp.serena_port if config.mcp.enable_serena else None,
        no_cache=no_cache,
    )


@click.command("cd")
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

    sandbox_dir = get_sandbox_dir(name)

    if not sandbox_dir.exists():
        console.print(f"[red]Sandbox not found:[/red] {name}")
        console.print(f"Create it with: devenv run {name}")
        raise SystemExit(1)

    shell = os.environ.get("SHELL", "/bin/bash")

    console.print(f"[dim]Entering {sandbox_dir}[/dim]")
    console.print("[dim]Type 'exit' to return[/dim]")

    cmd = [shell]
    result: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(cmd, returncode=1)
    try:
        result = subprocess.run(cmd, cwd=sandbox_dir)
    finally:
        process_manager.cleanup_all()
    sys.exit(result.returncode)
