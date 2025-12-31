"""CLI entry point for devenv-generator.

This module is the thin orchestrator for the CLI, importing and registering
commands from the commands/ subpackage. The main() function is the entry point
defined in pyproject.toml.
"""

from pathlib import Path

import rich_click as click
import structlog
from rich.console import Console

from mirustech.devenv_generator.commands.config import config
from mirustech.devenv_generator.commands.diagnostics import doctor
from mirustech.devenv_generator.commands.lifecycle import (
    attach_sandbox,
    cd_sandbox,
    run,
    start_sandbox,
    stop_sandbox,
)
from mirustech.devenv_generator.commands.management import clean, remove_sandbox, status
from mirustech.devenv_generator.commands.profiles import profiles
from mirustech.devenv_generator.generator import (
    DevEnvGenerator,
    get_bundled_profile,
    load_profile,
)
from mirustech.devenv_generator.models import ProfileConfig

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

SANDBOXES_DIR = Path("~/.local/share/devenv-sandboxes").expanduser()


class DefaultToRunGroup(click.RichGroup):
    """Custom Click group that forwards unknown commands to 'run' subcommand.

    This allows 'devenv ~/path' to work as a shortcut for 'devenv run ~/path'.
    """

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        """Resolve command, falling back to 'run' for unknown commands."""
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            # Unknown command - treat all args as paths for 'run'
            return "run", self.commands.get("run"), args


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
        raise SystemExit(1) from None


@click.group(cls=DefaultToRunGroup, invoke_without_command=True)
@click.version_option()
@click.pass_context
def main(ctx: click.Context) -> None:
    """Run Claude Code on your projects in an isolated Docker container.

    \b
    Usage:
        devenv                      # Current directory, starts Claude
        devenv ~/dev/myproject      # Specific project
        devenv --shell              # Drop to shell instead of Claude

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
    # Default to 'run' subcommand if no subcommand given (e.g., just 'devenv')
    if ctx.invoked_subcommand is None:
        # No arguments at all - invoke run with current directory
        ctx.invoke(run)


# Register command groups
main.add_command(profiles)
main.add_command(config)

# Register lifecycle commands
main.add_command(run)
main.add_command(attach_sandbox, name="attach")
main.add_command(stop_sandbox, name="stop")
main.add_command(start_sandbox, name="start")
main.add_command(cd_sandbox, name="cd")

# Register management commands
main.add_command(status)
main.add_command(remove_sandbox)
main.add_command(clean)

# Register diagnostics
main.add_command(doctor)


@main.command("help")
def help_command() -> None:
    """Show comprehensive help and usage guide."""
    console.print("[bold cyan]devenv - Isolated Docker environments for Claude Code[/bold cyan]")
    console.print()
    console.print("Run Claude Code on your projects in isolated, reproducible Docker containers.")
    console.print()

    console.print("[bold]Quick Start:[/bold]")
    console.print("  devenv                      # Run in current directory")
    console.print("  devenv run ~/dev/myproject  # Run in specific project")
    console.print("  devenv new ~/newproject     # Create new project with devcontainer")
    console.print()

    console.print("[bold]Common Commands:[/bold]")
    console.print()
    console.print("  [cyan]run[/cyan] [PATH...]        Run sandbox (default if no command given)")
    console.print("  [cyan]new[/cyan] PATH            Create new project with devcontainer")
    console.print("  [cyan]attach[/cyan] [NAME]       Attach to running sandbox")
    console.print("  [cyan]stop[/cyan] [NAME]         Stop running sandbox")
    console.print("  [cyan]status[/cyan]              List all sandboxes")
    console.print("  [cyan]rm[/cyan] [NAME]           Remove sandbox and volumes")
    console.print("  [cyan]clean[/cyan]               Clean up stopped sandboxes")
    console.print()

    console.print("[bold]Profile Management:[/bold]")
    console.print("  [cyan]profiles list[/cyan]       List available profiles")
    console.print("  [cyan]profiles show[/cyan]       Show default profile details")
    console.print("  [cyan]profiles create[/cyan]     Create custom profile")
    console.print()

    console.print("[bold]Configuration:[/bold]")
    console.print("  [cyan]config show[/cyan]         Show registry configuration")
    console.print("  [cyan]config set-registry[/cyan] Configure container registry")
    console.print()

    console.print("[bold]Diagnostics:[/bold]")
    console.print("  [cyan]doctor[/cyan]              Run system diagnostics")
    console.print("  [cyan]completions[/cyan]         Generate shell completions")
    console.print()


@main.command("completions")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completions(shell: str) -> None:
    """Generate shell completion script."""
    env_var = "_DEVENV_COMPLETE"

    if shell == "bash":
        script = f'''
_devenv_completion() {{
    local IFS=$'\\n'
    COMPREPLY=( $( env COMP_WORDS="${{COMP_WORDS[*]}}" \\
                   COMP_CWORD=$COMP_CWORD \\
                   {env_var}=bash_complete $1 ) )
    return 0
}}

complete -F _devenv_completion -o default devenv
'''
    elif shell == "zsh":
        script = '''
#compdef devenv

_devenv() {
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
                'new:Create a new project with devcontainer'
                'profiles:Manage profiles'
                'config:Manage configuration'
            )
            _describe 'command' commands
            ;;
    esac
}

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

complete -c devenv -f
complete -c devenv -n "__fish_use_subcommand" -a "run" -d "Run a sandbox"
complete -c devenv -n "__fish_use_subcommand" -a "attach" -d "Attach to sandbox"
complete -c devenv -n "__fish_use_subcommand" -a "stop" -d "Stop sandbox"
complete -c devenv -n "__fish_use_subcommand" -a "start" -d "Start a sandbox"
complete -c devenv -n "__fish_use_subcommand" -a "rm" -d "Remove a sandbox"
complete -c devenv -n "__fish_use_subcommand" -a "status" -d "List sandboxes"
complete -c devenv -n "__fish_use_subcommand" -a "clean" -d "Clean up sandboxes"
complete -c devenv -n "__fish_use_subcommand" -a "cd" -d "Change to sandbox directory"
complete -c devenv -n "__fish_use_subcommand" -a "new" -d "Create new project"
complete -c devenv -n "__fish_use_subcommand" -a "profiles" -d "Manage profiles"
complete -c devenv -n "__fish_use_subcommand" -a "config" -d "Manage configuration"
complete -c devenv -n "__fish_seen_subcommand_from attach stop start rm cd" \\
    -a "(__fish_devenv_sandbox_names)"
'''
    else:
        console.print(f"[red]Unsupported shell: {shell}[/red]")
        raise SystemExit(1)

    click.echo(script.strip())


@main.command("new")
@click.argument("path", type=click.Path())
@click.option("--profile", "-p", default="default")
@click.option("--name", "-n", default=None)
@click.option("--python-version", default=None)
def new_project(path: str, profile: str, name: str | None, python_version: str | None) -> None:
    """Create a new project with dev environment."""
    output_path = Path(path).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    project_name = name or output_path.name
    config = _load_profile(profile)

    if python_version:
        config.python.version = python_version

    generator = DevEnvGenerator(config, project_name=project_name)
    generated = generator.generate(output_path)

    console.print()
    console.print(f"[bold green]Created:[/bold green] {project_name}")
    console.print(f"[dim]Location: {output_path}[/dim]")
    console.print()
    for file_path in generated:
        rel_path = file_path.relative_to(output_path)
        console.print(f"  {rel_path}")


# Hidden commands for backwards compatibility
@main.command("generate", hidden=True)
@click.option("--profile", "-p", default="default")
@click.option("--output", "-o", default=".")
@click.option("--project-name", "-n", default=None)
@click.option("--python-version", default=None)
@click.pass_context
def generate(
    ctx: click.Context,
    profile: str,
    output: str,
    project_name: str | None,
    python_version: str | None,
) -> None:
    """[Deprecated] Use 'devenv new' instead."""
    msg = "[yellow]Note: 'devenv generate' is deprecated. Use 'devenv new' instead.[/yellow]"
    console.print(msg)
    ctx.invoke(
        new_project,
        path=output,
        profile=profile,
        name=project_name,
        python_version=python_version,
    )


@main.command("sandbox", hidden=True)
@click.option("--mount", "-m", "mounts", multiple=True, required=True)
@click.option("--name", "-n", "sandbox_name", default=None)
@click.option("--output", "-o", default=None)
@click.option("--profile", "-p", default="default")
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
    msg = "[yellow]Note: 'devenv sandbox' is deprecated. Use 'devenv /path' instead.[/yellow]"
    console.print(msg)
    ctx.invoke(
        run,
        paths=mounts,
        profile=profile,
        output=output,
        name=sandbox_name,
        no_host_config=not use_host_claude_config,
        detach=False,
        shell=False,
        python_version=None,
        push_to_registry=False,
        no_registry=False,
        start_serena=None,
        serena_port=None,
        serena_browser=None,
        no_cache=False,
    )


if __name__ == "__main__":
    main()
