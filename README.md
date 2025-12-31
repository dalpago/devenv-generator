# devenv-generator

Run Claude Code on your projects in an isolated Docker container.

## Quick Start

```bash
# Install
uv tool install devenv-generator

# Run on current project
devenv
```

That's it. This will:
1. Detect your Python version from the project
2. Build a container with Claude Code and dev tools
3. Install your project dependencies (`uv sync`)
4. Start Claude Code in YOLO mode

## Usage

```bash
# Current directory - starts Claude immediately
devenv

# Specific project
devenv run ~/dev/my-project

# Drop to shell instead of Claude
devenv run --shell

# Run in background
devenv run -d

# Multiple projects (second is read-only)
devenv run ~/proj1 ~/proj2:ro

# Copy-on-write (changes discarded on exit)
devenv run ~/proj:cow
```

## Container Management

```bash
# List all sandboxes
devenv status

# Attach to running sandbox
devenv attach [name]

# Stop a sandbox
devenv stop [name]

# Remove a sandbox
devenv rm [name]

# Clean up unused sandboxes and images
devenv clean --all
```

## Diagnostics & Troubleshooting

Use `devenv doctor` to diagnose and fix common setup issues:

```bash
# Check system health
devenv doctor

# Check and auto-fix issues
devenv doctor --fix

# Include container health checks
devenv doctor --container

# Show detailed information
devenv doctor --verbose
```

**What it checks:**

- ✅ Docker installed and running
- ✅ Docker Compose available
- ✅ Claude authentication configured
- ✅ Disk space (warns if < 5GB)
- ✅ Required directories (`~/.claude`, `~/.happy`)
- ✅ Default profile validity
- ✅ Container health (with `--container` flag)
- ✅ Port availability (GPG, Serena)
- ✅ MCP servers configured

**Auto-fix capabilities:**

- Starts Docker if not running (macOS/Linux)
- Creates missing directories (`~/.claude`, `~/.happy`)
- Cleans up disk space (removes stopped sandboxes, unused images)
- Guides Claude authentication setup

**Example output:**

```
✓ Docker installed: Docker version 28.4.0
✓ Docker running: Docker daemon is running
✓ Claude authentication: OAuth token found
✓ Disk space: 92.1GB available
✓ All checks passed!
Your system is ready to use devenv.
```

## Mount Modes

| Mode | Description |
|------|-------------|
| `/path` or `/path:rw` | Read-write (default) — changes persist |
| `/path:ro` | Read-only — safe exploration |
| `/path:cow` | Copy-on-write — changes discarded on exit |

## What's in the Container

- **Python** (auto-detected from your project, or 3.12)
- **Claude Code** with YOLO mode enabled
- **Happy Coder** (mobile client support)
- **uv** for fast dependency management
- **Shell**: zsh with syntax highlighting
- **Search**: ripgrep (`rg`), fd
- **Git tools**: delta (better diffs), bat (syntax highlighting)
- **Utilities**: jq, yq, tree, curl
- **SSH**: SSH client with agent forwarding support (`ssh-add -l` works)
- **MCP Servers**: Auto-configured from host (context7, serena, etc.)

## How It Works

1. **Auto-detects** Python version from `.python-version` or `pyproject.toml`
2. **Mounts** your project at `/workspace/<project-name>`
3. **Copies** from host into container:
   - `~/.claude` (OAuth, CLAUDE.md, MCP servers, agents, skills, output-styles)
   - `~/.happy` (Happy Coder config and credentials)
   - `~/.ssh` (SSH keys, config, known_hosts with agent forwarding support)
4. **Runs** `uv sync` to install project dependencies
5. **Starts** Claude Code with `--dangerously-skip-permissions`

Container files are stored in `~/.local/share/devenv-sandboxes/<project>/`.

## Quick Reference

```bash
# Get comprehensive help
devenv help

# Quick start
devenv                      # Run in current directory
devenv run ~/dev/myproject  # Run specific project
```

## Options

```
devenv run [PATHS...] [OPTIONS]

Options:
  --shell, -s            Drop to shell instead of starting Claude
  --detach, -d           Run in background
  --python VERSION       Override Python version
  --profile, -p NAME         Use a specific profile (default: default)
  --no-host-config           Don't mount ~/.claude (isolated Claude config)
  -o, --output PATH          Custom output directory
  -n, --name NAME            Custom sandbox name
  --start-serena/--no-serena Start/disable Serena MCP server (default: enabled)
  --serena-port PORT         Port for Serena (default: from profile, usually 9121)
  --serena-browser           Open browser dashboard (default: disabled)
```

## MCP Servers

**Serena** and **context7** MCP servers are enabled by default for enhanced Claude Code functionality:
- **Serena**: Semantic code navigation and refactoring
- **context7**: Library documentation lookup

These settings are configured in your profile and can be overridden with CLI flags:

```bash
# Default: Both enabled, no browser
devenv run

# Disable Serena
devenv run --no-serena

# Enable Serena browser dashboard
devenv run --serena-browser
```

## Profiles

Profiles define the base container environment (Python version, packages, tools, MCP servers).

For existing projects, Python version is auto-detected. Profiles are optional overrides.

For new projects (`devenv new`), profiles define the starting environment.

```bash
# Get help about profiles
devenv profiles help

# List all available profiles
devenv profiles list

# Show profile details (defaults to 'default' if not specified)
devenv profiles show
devenv profiles show myprofile

# Create new profile (copies from default)
devenv profiles create myprofile

# Create from specific profile
devenv profiles create myprofile --from-profile default

# Edit a profile (copies bundled profiles to user dir first)
devenv profiles edit          # Edits default profile
devenv profiles edit myprofile

# Show where a profile file is located
devenv profiles path          # Shows default profile path
devenv profiles path myprofile

# Delete a user profile
devenv profiles delete myprofile
```

Profiles are stored in:
- Bundled: `<package>/mirustech/devenv_generator/profiles/`
- User: `~/.config/devenv-generator/profiles/`

## Creating New Projects

```bash
devenv new ~/dev/my-new-app
```

This creates a new project directory with Docker configuration files.

## Requirements

- Docker (auto-starts Docker Desktop on macOS if needed)
- Claude Code configured on host (`~/.claude` with OAuth credentials)

## License

MIT
