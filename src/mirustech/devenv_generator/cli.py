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


@click.group(invoke_without_command=True)
@click.argument("paths", nargs=-1, type=click.Path())
@click.option(
    "--profile",
    "-p",
    default="mirustech",
    help="Profile name or path to YAML file",
)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output directory",
)
@click.option(
    "--name",
    "-n",
    default=None,
    help="Sandbox/project name",
)
@click.option(
    "--no-host-config",
    is_flag=True,
    default=False,
    help="Don't mount host ~/.claude (isolate from host Claude config)",
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
) -> None:
    """Generate Docker-based development environments for Claude Code.

    \b
    Usage:
        devenv                      # Mount current directory
        devenv .                    # Same as above
        devenv ~/dev/myproject      # Mount specific project
        devenv ~/proj1 ~/proj2:ro   # Multiple projects (second is read-only)

    \b
    Mount modes:
        /path           Read-write (default)
        /path:ro        Read-only (safe exploration)
        /path:cow       Copy-on-write (changes discarded on exit)

    \b
    Examples:
        devenv                              # Quick start on current project
        devenv --no-host-config             # Isolated Claude config
        devenv ~/proj -o ~/sandboxes/proj   # Custom output location
        devenv new ~/dev/new-app            # Create new project (rare)
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
        output_path = Path(f"~/.local/share/devenv-sandboxes/{sandbox_name}").expanduser()
    else:
        output_path = Path(output).resolve()

    # Load profile
    config = _load_profile(profile)

    # Generate sandbox
    generator = SandboxGenerator(
        profile=config,
        mounts=mount_specs,
        sandbox_name=sandbox_name,
        use_host_claude_config=not no_host_config,
    )
    generated = generator.generate(output_path)

    console.print()
    console.print(f"[bold green]✓ Sandbox ready:[/bold green] {sandbox_name}")
    console.print()

    console.print("[bold]Mounts:[/bold]")
    for spec in mount_specs:
        mode_str = {"rw": "", "ro": " [dim](read-only)[/dim]", "cow": " [dim](copy-on-write)[/dim]"}[spec.mode]
        console.print(f"  {spec.host_path} → {spec.container_path}{mode_str}")

    console.print()
    console.print("[bold]Run:[/bold]")
    console.print(f"  cd {output_path} && docker compose run --rm dev")


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
def sandbox(
    ctx: click.Context,
    mounts: tuple[str, ...],
    sandbox_name: str | None,
    output: str | None,
    profile: str,
    use_host_claude_config: bool,
) -> None:
    """[Deprecated] Just use 'devenv /path/to/project' instead."""
    console.print("[yellow]Note: 'devenv sandbox' is deprecated. Just use 'devenv /path' instead.[/yellow]")
    # Invoke main with the paths
    ctx.invoke(
        main,
        paths=mounts,
        profile=profile,
        output=output,
        name=sandbox_name,
        no_host_config=not use_host_claude_config,
    )


if __name__ == "__main__":
    main()
