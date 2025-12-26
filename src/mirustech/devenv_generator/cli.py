"""CLI entry point for devenv-generator."""

import os
import subprocess
import sys
from pathlib import Path

import rich_click as click
import structlog
import yaml
from rich.console import Console
from rich.table import Table

from mirustech.devenv_generator.generator import (
    DevEnvGenerator,
    SandboxGenerator,
    get_bundled_profile,
    load_profile,
)
from mirustech.devenv_generator.models import MountSpec, ProfileConfig

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


def _run_sandbox(
    sandbox_name: str,
    sandbox_dir: Path,
    detach: bool = False,
    shell: bool = False,
) -> None:
    """Run a sandbox container."""
    if not _ensure_docker_running():
        console.print("[red]Docker is not available. Please start Docker.[/red]")
        raise SystemExit(1)

    # Build if needed
    console.print("[dim]Building container...[/dim]")
    build_result = subprocess.run(
        ["docker", "compose", "-p", sandbox_name, "build"],
        cwd=sandbox_dir,
        capture_output=True,
        text=True,
    )
    if build_result.returncode != 0:
        console.print(f"[red]Build failed:[/red]\n{build_result.stderr}")
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
            cmd = ["docker", "compose", "-p", sandbox_name, "run", "--rm", "dev", "/bin/zsh"]
        else:
            console.print(f"[bold green]Starting Claude Code in {sandbox_name}...[/bold green]")
            cmd = ["docker", "compose", "-p", sandbox_name, "run", "--rm", "dev"]

        console.print("[dim]Press Ctrl+D to exit[/dim]")
        console.print()

        # Replace current process with docker compose
        os.execvp(cmd[0], cmd)


@click.group(invoke_without_command=True)
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
@click.version_option()
@click.pass_context
def main(
    ctx: click.Context,
    paths: tuple[str, ...],
    profile: str,
    output: str | None,
    name: str | None,
    no_host_config: bool,
    detach: bool,
    shell: bool,
    python_version: str | None,
) -> None:
    """Run Claude Code on your projects in an isolated Docker container.

    \b
    Usage:
        devenv                      # Current directory, starts Claude
        devenv ~/dev/myproject      # Specific project
        devenv --shell              # Drop to shell instead of Claude
        devenv -d                   # Run in background

    \b
    Mount modes:
        /path           Read-write (default)
        /path:ro        Read-only (safe exploration)
        /path:cow       Copy-on-write (changes discarded on exit)

    \b
    Container management:
        devenv attach [name]        # Attach to running sandbox
        devenv stop [name]          # Stop running sandbox
        devenv status               # List sandboxes
        devenv rm [name]            # Remove sandbox
    """
    # If a subcommand was invoked, let it handle things
    if ctx.invoked_subcommand is not None:
        return

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

    # Generate sandbox
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

    # Run the sandbox
    _run_sandbox(sandbox_name, output_path, detach=detach, shell=shell)


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
    table.add_column("Path", style="dim")

    for name, path, is_running in sandboxes:
        status_str = "[green]running[/green]" if is_running else "[dim]stopped[/dim]"
        table.add_row(name, status_str, str(path))

    console.print(table)


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
    import shutil
    shutil.rmtree(sandbox_dir)

    console.print(f"[bold green]✓ Removed:[/bold green] {name}")


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
