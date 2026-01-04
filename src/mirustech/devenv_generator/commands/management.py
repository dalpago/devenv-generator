"""Sandbox management commands (status, rm, clean)."""

import contextlib
import shutil
import time
from pathlib import Path

import rich_click as click
import structlog
from rich.console import Console
from rich.table import Table

from mirustech.devenv_generator.utils.subprocess import run_command

console = Console()
logger = structlog.get_logger()

SANDBOXES_DIR = Path("~/.local/share/devenv-sandboxes").expanduser()


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
        result = run_command(
            ["docker", "compose", "-p", name, "ps", "-q"],
            cwd=sandbox_dir,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _get_dir_size(path: Path) -> int:
    """Get total size of a directory in bytes."""
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            with contextlib.suppress(OSError):
                total += entry.stat().st_size
    return total


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    size: float = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _get_image_size(image_name: str) -> int | None:
    """Get the size of a Docker image in bytes."""
    result = run_command(["docker", "image", "inspect", image_name, "--format", "{{.Size}}"])
    if result.returncode == 0:
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None
    return None


@click.command("status")
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


@click.command("rm")
@click.argument("name", required=False)
@click.option("--force", "-f", is_flag=True, help="Force removal even if running")
def remove_sandbox(name: str | None, force: bool) -> None:
    """Remove a sandbox.

    If no name is provided, removes the sandbox matching the current directory name.
    """
    if name is None:
        name = Path.cwd().name

    sandbox_dir = SANDBOXES_DIR / name

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
        run_command(["docker", "compose", "-p", name, "down", "-v"], cwd=sandbox_dir, timeout=60)

    # Remove the directory
    shutil.rmtree(sandbox_dir)

    console.print(f"[bold green]✓ Removed:[/bold green] {name}")


@click.command("clean")
@click.option("--stopped", "-s", is_flag=True, help="Remove stopped sandboxes")
@click.option("--images", "-i", is_flag=True, help="Remove unused devenv images")
@click.option(
    "--all", "-a", "all_", is_flag=True, help="Remove everything (stopped sandboxes + images)"
)
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be removed without removing")
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
    result = run_command(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.ID}}"]
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
    dangling_result = run_command(
        ["docker", "images", "-f", "dangling=true", "--format", "{{.ID}}\t{{.Size}}"]
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
            for name, size, _id in unused_images:
                if dry_run:
                    console.print(f"  [dim]Would remove:[/dim] {name} ({size})")
                else:
                    result = run_command(["docker", "rmi", name], timeout=60)
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
                    result = run_command(["docker", "rmi", id_], timeout=60)
                    if result.returncode == 0:
                        console.print(f"  [green]✓[/green] Removed {id_[:12]} ({size})")
                        removed_count += 1

    if dry_run:
        console.print("\n[dim]Dry run - nothing was removed[/dim]")
    elif removed_count > 0:
        console.print(f"\n[bold green]✓ Cleaned up {removed_count} items[/bold green]")
    else:
        console.print("\n[dim]Nothing to clean[/dim]")
