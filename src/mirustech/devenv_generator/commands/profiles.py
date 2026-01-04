"""Profile management commands."""

import os
from pathlib import Path

import rich_click as click
import yaml
from rich.console import Console
from rich.table import Table

from mirustech.devenv_generator.generator import get_bundled_profile, load_profile

console = Console()


@click.group()
def profiles() -> None:
    """Manage profiles."""
    pass


@profiles.command("help")
def profiles_help() -> None:
    """Show detailed help about profiles and how to use them."""
    console.print("[bold cyan]What are profiles?[/bold cyan]")
    console.print(
        "Profiles define the base container environment: Python version, packages, and tools."
    )
    console.print()

    console.print("[bold cyan]Profile locations:[/bold cyan]")
    console.print("  • Bundled: Built into devenv (read-only)")
    console.print("  • User: ~/.config/devenv-generator/profiles/ (customizable)")
    console.print()

    console.print("[bold cyan]Common workflows:[/bold cyan]")
    console.print()
    console.print("[bold]1. View available profiles:[/bold]")
    console.print("   devenv profiles list")
    console.print()
    console.print("[bold]2. Inspect a profile:[/bold]")
    console.print("   devenv profiles show          # Show default profile")
    console.print("   devenv profiles show myprofile")
    console.print()
    console.print("[bold]3. Create a custom profile:[/bold]")
    console.print("   devenv profiles create myprofile")
    console.print("   # Creates a copy of 'default' in ~/.config/devenv-generator/profiles/")
    console.print()
    console.print("[bold]4. Edit a profile:[/bold]")
    console.print("   devenv profiles edit myprofile")
    console.print("   # Opens in $EDITOR, copies bundled profiles to ~/.config first")
    console.print()
    console.print("[bold]5. Use a profile:[/bold]")
    console.print("   devenv run ~/myproject --profile myprofile")
    console.print("   devenv new ~/newproject --profile myprofile")
    console.print()
    console.print("[bold cyan]Tips:[/bold cyan]")
    console.print("  • Bundled profiles are read-only - 'edit' will copy them to ~/.config first")
    console.print("  • User profiles override bundled profiles with the same name")
    console.print("  • Use 'devenv profiles path <name>' to see where a profile is loaded from")
    console.print()
    console.print("Run 'devenv profiles <command> --help' for detailed command help.")


@profiles.command("list")
def list_profiles() -> None:
    """List available profiles."""
    table = Table(title="Available Profiles")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Python")

    # Bundled profiles
    bundled = ["default"]
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
@click.argument("name", default="default", required=False)
def show_profile(name: str) -> None:
    """Show profile details (defaults to 'default' profile)."""
    try:
        profile = get_bundled_profile(name)
    except FileNotFoundError:
        profile_path = Path(f"~/.config/devenv-generator/profiles/{name}.yaml").expanduser()
        try:
            profile = load_profile(profile_path)
        except FileNotFoundError:
            console.print(f"[red]Profile not found:[/red] {name}")
            raise SystemExit(1) from None

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

    console.print()
    console.print("[bold]MCP Servers:[/bold]")
    console.print(f"  Serena: {'enabled' if profile.mcp.enable_serena else 'disabled'}")
    if profile.mcp.enable_serena:
        console.print(f"    Port: {profile.mcp.serena_port}")
        console.print(f"    Browser: {'enabled' if profile.mcp.serena_browser else 'disabled'}")
    console.print(f"  context7: {'enabled' if profile.mcp.enable_context7 else 'disabled'}")


@profiles.command("create")
@click.argument("name")
@click.option(
    "--from-profile",
    "-f",
    default="default",
    help="Profile to copy from (default: default)",
)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output path (default: ~/.config/devenv-generator/profiles/)",
)
def create_profile(name: str, from_profile: str, output: str | None) -> None:
    """Create a new profile by copying an existing one.

    By default, copies from the 'default' bundled profile.
    """
    if output:
        output_path = Path(output)
    else:
        output_path = Path(f"~/.config/devenv-generator/profiles/{name}.yaml").expanduser()

    # Check if output file already exists
    if output_path.exists():
        console.print(f"[red]Profile already exists:[/red] {output_path}")
        console.print("Use a different name or delete the existing profile first")
        raise SystemExit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load the source profile
    try:
        source_profile = get_bundled_profile(from_profile)
        console.print(f"[dim]Copying from bundled profile:[/dim] {from_profile}")
    except FileNotFoundError:
        # Try user profile
        user_profile_path = Path(
            f"~/.config/devenv-generator/profiles/{from_profile}.yaml"
        ).expanduser()
        if user_profile_path.exists():
            source_profile = load_profile(user_profile_path)
            console.print(f"[dim]Copying from user profile:[/dim] {from_profile}")
        else:
            console.print(f"[red]Source profile not found:[/red] {from_profile}")
            console.print("Use 'devenv profiles list' to see available profiles")
            raise SystemExit(1) from None

    # Update name and description for the new profile
    source_profile.name = name
    source_profile.description = f"Custom profile based on {from_profile}"

    # Write to output file
    with output_path.open("w") as f:
        yaml.dump(source_profile.model_dump(), f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]✓ Created profile:[/green] {output_path}")
    console.print(f"[dim]Based on:[/dim] {from_profile}")
    console.print()
    console.print("Edit this file to customize your development environment:")
    console.print(f"  devenv profiles edit {name}")


@profiles.command("edit")
@click.argument("name", default="default", required=False)
def edit_profile(name: str) -> None:
    """Edit a profile in your default editor (defaults to 'default' profile).

    If the profile is bundled (read-only), it will be copied to
    ~/.config/devenv-generator/profiles/ first, then opened for editing.
    """
    user_profiles_dir = Path("~/.config/devenv-generator/profiles").expanduser()
    user_profile_path = user_profiles_dir / f"{name}.yaml"

    # Check if user profile already exists
    if user_profile_path.exists():
        profile_path = user_profile_path
        console.print(f"[dim]Editing user profile:[/dim] {name}")
    else:
        # Check if it's a bundled profile
        try:
            bundled_profile = get_bundled_profile(name)
            # Copy to user directory first
            user_profiles_dir.mkdir(parents=True, exist_ok=True)
            with user_profile_path.open("w") as f:
                yaml.dump(
                    bundled_profile.model_dump(), f, default_flow_style=False, sort_keys=False
                )
            profile_path = user_profile_path
            console.print(f"[yellow]Copied bundled profile to:[/yellow] {user_profile_path}")
            console.print("[dim]You can now edit this local copy[/dim]")
        except FileNotFoundError:
            console.print(f"[red]Profile not found:[/red] {name}")
            console.print("Use 'devenv profiles list' to see available profiles")
            console.print(f"Or create a new one with: devenv profiles create {name}")
            raise SystemExit(1) from None

    # Open in editor
    editor = os.environ.get("VISUAL", os.environ.get("EDITOR", "vi"))
    console.print(f"[dim]Opening {profile_path} with {editor}...[/dim]")
    os.execvp(editor, [editor, str(profile_path)])


@profiles.command("path")
@click.argument("name", default="default", required=False)
@click.option(
    "--exists-only",
    is_flag=True,
    help="Exit with code 0 if profile exists, 1 otherwise (for scripting)",
)
def profile_path(name: str, exists_only: bool) -> None:
    """Show the file path where a profile is loaded from (defaults to 'default' profile).

    Useful for finding where a profile is defined, whether it's
    bundled with devenv or in your user config directory.
    """
    # Check user profiles first
    user_profile_path = Path(f"~/.config/devenv-generator/profiles/{name}.yaml").expanduser()
    if user_profile_path.exists():
        if exists_only:
            raise SystemExit(0)
        console.print(str(user_profile_path))
        console.print("[dim](user profile)[/dim]")
        return

    # Check bundled profiles
    try:
        # Try to get the actual file path from importlib.resources
        from importlib.resources import files

        profiles_dir = files("mirustech.devenv_generator").joinpath("profiles")
        bundled_path = profiles_dir.joinpath(f"{name}.yaml")

        # Verify it exists by trying to load it
        _ = get_bundled_profile(name)

        if exists_only:
            raise SystemExit(0)

        # For bundled profiles, show the package location
        console.print(str(bundled_path))
        console.print("[dim](bundled profile)[/dim]")
        return
    except (FileNotFoundError, TypeError, AttributeError):
        pass

    # Profile not found
    if exists_only:
        raise SystemExit(1)

    console.print(f"[red]Profile not found:[/red] {name}")
    console.print("Use 'devenv profiles list' to see available profiles")
    raise SystemExit(1)


@profiles.command("delete")
@click.argument("name")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Skip confirmation prompt",
)
def delete_profile(name: str, force: bool) -> None:
    """Delete a user profile from ~/.config/devenv-generator/profiles/.

    Note: You cannot delete bundled profiles. This only removes profiles
    you have created or edited in your user config directory.
    """
    user_profile_path = Path(f"~/.config/devenv-generator/profiles/{name}.yaml").expanduser()

    # Check if it exists as user profile
    if not user_profile_path.exists():
        # Check if it's a bundled profile
        try:
            _ = get_bundled_profile(name)
            console.print(f"[red]Cannot delete bundled profile:[/red] {name}")
            console.print(
                "[dim]Bundled profiles are read-only and part of devenv installation[/dim]"
            )
            raise SystemExit(1) from None
        except FileNotFoundError:
            console.print(f"[red]Profile not found:[/red] {name}")
            console.print("Use 'devenv profiles list' to see available profiles")
            raise SystemExit(1) from None

    # Confirm deletion
    if not force:
        from rich.prompt import Confirm

        console.print(f"[yellow]This will delete:[/yellow] {user_profile_path}")
        if not Confirm.ask("Are you sure?", default=False):
            console.print("[dim]Cancelled[/dim]")
            return

    # Delete the file
    user_profile_path.unlink()
    console.print(f"[green]✓ Deleted profile:[/green] {name}")
    console.print(f"[dim]Removed:[/dim] {user_profile_path}")
