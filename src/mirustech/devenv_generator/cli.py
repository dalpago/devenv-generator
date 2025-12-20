"""CLI entry point for devenv-generator."""

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


@click.group()
@click.version_option()
def main() -> None:
    """Generate Docker-based development environments for Claude Code YOLO mode."""
    pass


@main.command()
@click.option(
    "--profile",
    "-p",
    default="mirustech",
    help="Profile name or path to YAML file",
)
@click.option(
    "--output",
    "-o",
    default=".",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Output directory (default: current directory)",
)
@click.option(
    "--project-name",
    "-n",
    default=None,
    help="Project name (default: directory name)",
)
@click.option(
    "--python-version",
    default=None,
    help="Override Python version",
)
def generate(
    profile: str,
    output: str,
    project_name: str | None,
    python_version: str | None,
) -> None:
    """Generate development environment files.

    Example:
        devenv generate --profile mirustech --output ./my-project
    """
    output_path = Path(output).resolve()

    # Determine project name
    if project_name is None:
        project_name = output_path.name

    # Load profile
    profile_path = Path(profile)
    if profile_path.exists() and profile_path.suffix in (".yaml", ".yml"):
        # Load from file
        config = load_profile(profile_path)
        console.print(f"[green]Loaded profile from:[/green] {profile_path}")
    else:
        # Try bundled profile
        try:
            config = get_bundled_profile(profile)
            console.print(f"[green]Using bundled profile:[/green] {profile}")
        except FileNotFoundError:
            console.print(f"[red]Profile not found:[/red] {profile}")
            console.print("Use 'devenv profiles list' to see available profiles")
            raise SystemExit(1)

    # Apply overrides
    if python_version:
        config.python.version = python_version

    # Generate files
    generator = DevEnvGenerator(config, project_name=project_name)
    generated = generator.generate(output_path)

    console.print()
    console.print("[bold green]Generated files:[/bold green]")
    for path in generated:
        rel_path = path.relative_to(output_path)
        console.print(f"  [cyan]{rel_path}[/cyan]")

    console.print()
    console.print("[bold]Usage:[/bold]")
    console.print("  docker-compose run --rm dev")
    console.print("  # Inside container:")
    console.print("  claude --dangerously-skip-permissions")


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
    for name in bundled:
        try:
            profile = get_bundled_profile(name)
            table.add_row(
                name,
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

    # Create default profile
    profile = ProfileConfig(
        name=name,
        description=f"Custom profile: {name}",
    )

    with output_path.open("w") as f:
        yaml.dump(profile.model_dump(), f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]Created profile:[/green] {output_path}")
    console.print("Edit this file to customize your development environment.")


@main.command()
@click.option(
    "--mount",
    "-m",
    "mounts",
    multiple=True,
    required=True,
    help="Project directory to mount (format: /path[:mode] where mode is rw|ro|cow)",
)
@click.option(
    "--name",
    "-n",
    "sandbox_name",
    default=None,
    help="Sandbox name (default: first mount directory name)",
)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output directory (default: ~/.local/share/devenv-sandboxes/<name>)",
)
@click.option(
    "--profile",
    "-p",
    default="mirustech",
    help="Profile name or path to YAML file",
)
@click.option(
    "--use-host-claude-config",
    is_flag=True,
    default=False,
    help="Mount host ~/.claude for CLAUDE.md, MCP servers, and settings",
)
def sandbox(
    mounts: tuple[str, ...],
    sandbox_name: str | None,
    output: str | None,
    profile: str,
    use_host_claude_config: bool,
) -> None:
    """Create a sandbox environment for running Claude Code against existing projects.

    Mount one or more project directories with optional access modes:

    \b
    Examples:
        # Mount single project (read-write)
        devenv sandbox --mount /path/to/project

        # Mount read-only (safe for exploration)
        devenv sandbox --mount /path/to/project:ro

        # Mount copy-on-write (changes isolated, discarded on exit)
        devenv sandbox --mount /path/to/project:cow

        # Mount multiple projects
        devenv sandbox -m /path/to/proj1 -m /path/to/proj2:ro

        # Use host Claude config (CLAUDE.md, MCP servers, settings)
        devenv sandbox --mount /path/to/project --use-host-claude-config
    """
    # Parse mount specifications
    mount_specs = []
    for mount_str in mounts:
        try:
            spec = MountSpec.from_string(mount_str)
            if not spec.host_path.exists():
                console.print(f"[red]Mount path does not exist:[/red] {spec.host_path}")
                raise SystemExit(1)
            if not spec.host_path.is_dir():
                console.print(f"[red]Mount path is not a directory:[/red] {spec.host_path}")
                raise SystemExit(1)
            mount_specs.append(spec)
        except Exception as e:
            console.print(f"[red]Invalid mount specification:[/red] {mount_str}")
            console.print(f"  Error: {e}")
            raise SystemExit(1)

    # Determine sandbox name
    if sandbox_name is None:
        sandbox_name = mount_specs[0].host_path.name + "-sandbox"

    # Determine output directory
    if output is None:
        output_path = Path(f"~/.local/share/devenv-sandboxes/{sandbox_name}").expanduser()
    else:
        output_path = Path(output).resolve()

    # Load profile
    profile_path = Path(profile)
    if profile_path.exists() and profile_path.suffix in (".yaml", ".yml"):
        config = load_profile(profile_path)
        console.print(f"[green]Loaded profile from:[/green] {profile_path}")
    else:
        try:
            config = get_bundled_profile(profile)
            console.print(f"[green]Using bundled profile:[/green] {profile}")
        except FileNotFoundError:
            console.print(f"[red]Profile not found:[/red] {profile}")
            raise SystemExit(1)

    # Generate sandbox
    generator = SandboxGenerator(
        profile=config,
        mounts=mount_specs,
        sandbox_name=sandbox_name,
        use_host_claude_config=use_host_claude_config,
    )
    generated = generator.generate(output_path)

    console.print()
    console.print(f"[bold green]Sandbox created:[/bold green] {sandbox_name}")
    console.print(f"[dim]Location: {output_path}[/dim]")
    console.print()

    console.print("[bold]Mounted projects:[/bold]")
    for spec in mount_specs:
        mode_str = {"rw": "read-write", "ro": "read-only", "cow": "copy-on-write"}[spec.mode]
        console.print(f"  [cyan]{spec.host_path}[/cyan] -> {spec.container_path} ({mode_str})")

    console.print()
    console.print("[bold]Generated files:[/bold]")
    for path in generated:
        rel_path = path.relative_to(output_path)
        console.print(f"  [cyan]{rel_path}[/cyan]")

    console.print()
    console.print("[bold]Usage:[/bold]")
    console.print(f"  cd {output_path}")
    console.print("  # Set up .env with your ANTHROPIC_AUTH_TOKEN")
    console.print("  cp .env.example .env && sops encrypt --in-place .env")
    console.print()
    console.print("  # Run sandbox")
    console.print("  SOPS_AGE_KEY_FILE=~/.config/chezmoi/key.txt sops exec-env .env 'docker-compose run --rm dev'")


if __name__ == "__main__":
    main()
