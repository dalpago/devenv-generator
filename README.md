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
- **MCP Servers**: Auto-configured from host (context7, serena, etc.)

## How It Works

1. **Auto-detects** Python version from `.python-version` or `pyproject.toml`
2. **Mounts** your project at `/workspace/<project-name>`
3. **Copies** from host into container:
   - `~/.claude` (OAuth, CLAUDE.md, MCP servers, agents, skills, output-styles)
   - `~/.happy` (Happy Coder config and credentials)
4. **Runs** `uv sync` to install project dependencies
5. **Starts** Claude Code with `--dangerously-skip-permissions`

Container files are stored in `~/.local/share/devenv-sandboxes/<project>/`.

## Options

```
devenv run [PATHS...] [OPTIONS]

Options:
  --shell, -s         Drop to shell instead of starting Claude
  --detach, -d        Run in background
  --python VERSION    Override Python version
  --profile, -p NAME  Use a specific profile (default: mirustech)
  --no-host-config    Don't mount ~/.claude (isolated Claude config)
  -o, --output PATH   Custom output directory
  -n, --name NAME     Custom sandbox name
```

## Profiles

For existing projects, Python version is auto-detected. Profiles are optional
overrides for the base container.

For new projects (`devenv new`), profiles define the starting environment.

```bash
devenv profiles list          # List profiles
devenv profiles show mirustech # Show details
devenv profiles create custom  # Create new profile
```

Profiles are stored in `~/.config/devenv-generator/profiles/`.

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
