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
# Current directory
devenv

# Specific project
devenv ~/dev/my-project

# Multiple projects (second is read-only)
devenv ~/proj1 ~/proj2:ro

# Drop to shell instead of Claude
devenv --shell

# Copy-on-write mode (changes discarded on exit)
devenv ~/proj:cow
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
- **uv** for fast dependency management
- **Shell**: zsh with syntax highlighting
- **Search**: ripgrep (`rg`), fd
- **Git tools**: delta (better diffs), bat (syntax highlighting)
- **Utilities**: jq, yq, tree, curl

## How It Works

1. **Auto-detects** Python version from `.python-version` or `pyproject.toml`
2. **Mounts** your project at `/workspace/<project-name>`
3. **Mounts** your `~/.claude` for OAuth authentication and settings
4. **Runs** `uv sync` to install project dependencies
5. **Starts** Claude Code with `--dangerously-skip-permissions`

Container files are stored in `~/.local/share/devenv-sandboxes/<project>/`.

## Options

```bash
devenv [PATHS...] [OPTIONS]

Options:
  --shell              Drop to shell instead of starting Claude
  --no-host-config     Don't mount ~/.claude (isolated Claude config)
  --python VERSION     Override Python version
  --profile, -p NAME   Use a specific profile (default: auto-detect from project)
  -o, --output PATH    Custom output directory for sandbox files
  -n, --name NAME      Custom sandbox name
```

## Profiles

For existing projects, the container auto-detects Python version and installs
dependencies from your project. Profiles are optional overrides.

For new projects (`devenv new`), profiles define the starting environment.

```bash
# List available profiles
devenv profiles list

# Show profile details
devenv profiles show mirustech

# Create custom profile
devenv profiles create my-profile
```

Profiles are YAML files defining Python version, packages, and dev tools.
Custom profiles live in `~/.config/devenv-generator/profiles/`.

## Creating New Projects

For creating a fresh project (not mounting existing code):

```bash
devenv new ~/dev/my-new-app
```

This creates the project directory with Docker and VS Code devcontainer configs.

## Requirements

- Docker (will auto-start Docker Desktop on macOS if needed)
- Claude Code configured on host (`~/.claude` with OAuth credentials)

## License

MIT
