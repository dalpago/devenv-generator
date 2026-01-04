"""Port exposure management commands."""

import json
from datetime import datetime
from pathlib import Path

import rich_click as click
import structlog
import yaml
from rich.console import Console
from rich.table import Table

from mirustech.devenv_generator.commands.management import _is_sandbox_running
from mirustech.devenv_generator.models import PortConfig
from mirustech.devenv_generator.utils.subprocess import run_command

console = Console()
logger = structlog.get_logger()

SANDBOXES_DIR = Path("~/.local/share/devenv-sandboxes").expanduser()


def _get_sandbox_dir(name: str) -> Path:
    """Get the sandbox directory for a given name."""
    return SANDBOXES_DIR / name


def _load_dynamic_ports(sandbox_dir: Path) -> dict[str, dict]:
    """Load dynamic port mappings from JSON file."""
    ports_file = sandbox_dir / ".dynamic-ports.json"
    if ports_file.exists():
        return json.loads(ports_file.read_text())
    return {}


def _save_dynamic_ports(sandbox_dir: Path, ports: dict[str, dict]) -> None:
    """Save dynamic port mappings to JSON file."""
    ports_file = sandbox_dir / ".dynamic-ports.json"
    ports_file.write_text(json.dumps(ports, indent=2))


def _update_compose_ports(
    sandbox_dir: Path, sandbox_name: str, new_ports: list[PortConfig]
) -> None:
    """Update docker-compose.yml with new port mappings and recreate container.

    This modifies the docker-compose.yml file to add new port mappings,
    then uses 'docker compose up -d --force-recreate' to apply changes.
    The recreation is fast (~2-5 seconds) and preserves container state.
    """
    compose_file = sandbox_dir / "docker-compose.yml"

    # Read current compose file
    with compose_file.open() as f:
        compose_config = yaml.safe_load(f)

    # Get existing ports or initialize
    if "ports" not in compose_config["services"]["dev"]:
        compose_config["services"]["dev"]["ports"] = []

    # Add new ports (avoiding duplicates)
    existing_mappings = set(compose_config["services"]["dev"]["ports"])
    for port in new_ports:
        mapping = f"127.0.0.1:{port.host_port}:{port.container}/{port.protocol}"
        if mapping not in existing_mappings:
            compose_config["services"]["dev"]["ports"].append(mapping)

    # Write updated compose file
    with compose_file.open("w") as f:
        yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False)

    # Recreate container with new ports
    console.print("[dim]Updating container with new port mappings...[/dim]")
    result = run_command(
        ["docker", "compose", "-p", sandbox_name, "up", "-d", "--force-recreate"],
        cwd=sandbox_dir,
        timeout=60,
    )

    if result.returncode != 0:
        console.print(f"[red]Failed to update ports:[/red]\n{result.stderr}")
        raise SystemExit(1)


@click.command("expose")
@click.argument("port_specs", nargs=-1, required=True)
@click.option("--name", "-n", default=None, help="Sandbox name (default: current directory)")
def expose_port(port_specs: tuple[str, ...], name: str | None) -> None:
    """Expose additional ports from a running container.

    This updates the container's port mappings dynamically. The container
    will be briefly recreated (~2-5 seconds) to apply the changes.

    \b
    Examples:
        devenv expose 8000              # Expose container port 8000 to host 8000
        devenv expose 8080:3000         # Expose container port 3000 to host 8080
        devenv expose 5173 3000 8080    # Expose multiple ports
        devenv expose --name myproject 8000  # Expose port for specific sandbox
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
        console.print(f"Start it with: devenv start {name}")
        raise SystemExit(1)

    # Parse port specifications
    from mirustech.devenv_generator.commands.lifecycle import (
        _check_port_conflicts,
        _parse_port_spec,
    )

    new_ports = [_parse_port_spec(spec) for spec in port_specs]

    # Check for port conflicts
    _check_port_conflicts(new_ports, name)

    # Update docker-compose.yml and recreate container
    _update_compose_ports(sandbox_dir, name, new_ports)

    # Track dynamic ports
    dynamic_ports = _load_dynamic_ports(sandbox_dir)
    for port in new_ports:
        dynamic_ports[str(port.container)] = {
            "host_port": port.host_port,
            "protocol": port.protocol,
            "exposed_at": datetime.now().isoformat(),
            "method": "docker-port",
        }
    _save_dynamic_ports(sandbox_dir, dynamic_ports)

    console.print(f"[bold green]✓ Ports exposed for {name}:[/bold green]")
    for port in new_ports:
        console.print(f"  localhost:{port.host_port} → container:{port.container}/{port.protocol}")


@click.command("ports")
@click.option("--name", "-n", default=None, help="Sandbox name (default: current directory)")
def list_ports(name: str | None) -> None:
    """List all exposed ports for a sandbox.

    Shows both static ports (from profile) and dynamically exposed ports.

    \b
    Examples:
        devenv ports                    # List ports for current directory sandbox
        devenv ports --name myproject   # List ports for specific sandbox
    """
    if name is None:
        name = Path.cwd().name

    sandbox_dir = _get_sandbox_dir(name)

    if not sandbox_dir.exists():
        console.print(f"[red]Sandbox not found:[/red] {name}")
        raise SystemExit(1)

    # Get ports from docker inspect
    result = run_command(
        ["docker", "compose", "-p", name, "ps", "--format", "json"], cwd=sandbox_dir
    )

    if result.returncode != 0:
        console.print("[yellow]Sandbox not running[/yellow]")
        return

    containers_json = result.stdout.strip()
    if not containers_json:
        console.print("[yellow]No containers found[/yellow]")
        return

    # Parse container info
    try:
        # Handle both single container (dict) and multiple containers (list)
        if containers_json.startswith("["):
            containers = json.loads(containers_json)
        else:
            containers = [json.loads(containers_json)]
    except json.JSONDecodeError:
        console.print("[yellow]Could not parse container info[/yellow]")
        return

    # Create table
    table = Table(title=f"Port Mappings - {name}")
    table.add_column("Host Port", style="cyan")
    table.add_column("Container Port", style="green")
    table.add_column("Protocol", style="blue")
    table.add_column("Type", style="yellow")

    # Get dynamic ports for labeling
    dynamic_ports = _load_dynamic_ports(sandbox_dir)

    # Extract port mappings
    for container in containers:
        if container.get("Publishers"):
            for publisher in container["Publishers"]:
                container_port = publisher.get("TargetPort")
                host_port = publisher.get("PublishedPort")
                protocol = publisher.get("Protocol", "tcp")

                if container_port and host_port:
                    port_type = "dynamic" if str(container_port) in dynamic_ports else "static"
                    table.add_row(str(host_port), str(container_port), protocol, port_type)

    if table.row_count == 0:
        console.print(f"[dim]No ports exposed for {name}[/dim]")
    else:
        console.print(table)


@click.command("unexpose")
@click.argument("container_ports", nargs=-1, required=True, type=int)
@click.option("--name", "-n", default=None, help="Sandbox name (default: current directory)")
def unexpose_port(container_ports: tuple[int, ...], name: str | None) -> None:
    """Remove dynamically exposed ports.

    Removes port mappings that were added with 'devenv expose'. Static ports
    from the profile cannot be removed this way.

    \b
    Examples:
        devenv unexpose 8000                 # Remove port 8000 mapping
        devenv unexpose 8000 3000            # Remove multiple ports
        devenv unexpose --name myproject 8000 # Remove from specific sandbox
    """
    if name is None:
        name = Path.cwd().name

    sandbox_dir = _get_sandbox_dir(name)

    if not sandbox_dir.exists():
        console.print(f"[red]Sandbox not found:[/red] {name}")
        raise SystemExit(1)

    # Load dynamic ports
    dynamic_ports = _load_dynamic_ports(sandbox_dir)

    # Check if ports are dynamic
    not_dynamic = [p for p in container_ports if str(p) not in dynamic_ports]
    if not_dynamic:
        ports_list = ", ".join(map(str, not_dynamic))
        console.print(f"[yellow]These ports are not dynamically exposed:[/yellow] {ports_list}")
        console.print("[dim]Only ports added with 'devenv expose' can be removed[/dim]")
        raise SystemExit(1)

    # Remove from docker-compose.yml
    compose_file = sandbox_dir / "docker-compose.yml"
    with compose_file.open() as f:
        compose_config = yaml.safe_load(f)

    # Filter out the specified ports
    if "ports" in compose_config["services"]["dev"]:
        current_ports = compose_config["services"]["dev"]["ports"]
        filtered_ports = []
        for mapping in current_ports:
            # Parse mapping like "127.0.0.1:8080:3000/tcp" or "8080:3000/tcp"
            # Extract container port from the mapping
            parts = mapping.split(":")
            if len(parts) == 3:  # "127.0.0.1:8080:3000/tcp"
                container_part = parts[2].split("/")[0]
            elif len(parts) == 2:  # "8080:3000/tcp"
                container_part = parts[1].split("/")[0]
            else:
                continue

            try:
                container_port = int(container_part)
                if container_port not in container_ports:
                    filtered_ports.append(mapping)
            except ValueError:
                filtered_ports.append(mapping)

        compose_config["services"]["dev"]["ports"] = filtered_ports

    # Write updated compose file
    with compose_file.open("w") as f:
        yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False)

    # Recreate container if running
    if _is_sandbox_running(name, sandbox_dir):
        console.print("[dim]Updating container...[/dim]")
        result = run_command(
            ["docker", "compose", "-p", name, "up", "-d", "--force-recreate"],
            cwd=sandbox_dir,
            timeout=60,
        )

        if result.returncode != 0:
            console.print(f"[red]Failed to update:[/red]\n{result.stderr}")
            raise SystemExit(1)

    # Remove from dynamic ports tracking
    for port in container_ports:
        if str(port) in dynamic_ports:
            del dynamic_ports[str(port)]
    _save_dynamic_ports(sandbox_dir, dynamic_ports)

    console.print(
        f"[bold green]✓ Ports removed:[/bold green] {', '.join(map(str, container_ports))}"
    )
