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

## Architecture

### Module Organization

The CLI is organized by **feature domain** (not technical layer), mirroring user mental models:

```
cli.py (~345 lines - orchestrator)
  ├── Imports command groups and registers them
  ├── main() Click group with entry point
  └── Remaining commands: help, completions, new, generate, sandbox

commands/
  ├── profiles.py (7 commands: profiles group)
  ├── config.py (3 commands: config group)
  ├── lifecycle.py (5 commands: run, attach, stop, start, cd)
  ├── management.py (3 commands: status, rm, clean)
  └── diagnostics.py (doctor command + DiagnosticRegistry with 17 checks, 5 fixes)

utils/
  ├── subprocess.py (run_command wrapper for subprocess.run)
  └── process_manager.py (ProcessManager for background processes)
```

### Data Flow

**Subprocess execution:**
```
Command → run_command(["docker", ...])
         → Add defaults (capture_output=True, text=True, timeout=10)
         → subprocess.run()
         → CompletedProcess
         → Command handler parses output
```

**Process management (GPG agent, Serena):**
```
devenv run --start-serena
  → lifecycle.py:run()
  → ProcessManager.start("serena", ["uvx", "serena", ...])
  → subprocess.Popen() stored in _processes dict
  → atexit.register(cleanup_all)
  → On exit: terminate → wait(5s) → kill if needed
```

**Diagnostics:**
```
devenv doctor
  → diagnostics.py:doctor()
  → DiagnosticRegistry.run_all_checks()
  → Executes all @diagnostic.check decorated functions
  → Display results table
  → If --fix: DiagnosticRegistry.run_all_fixes()
```

### Design Decisions

**Why feature-based organization?** Commands are grouped by user intent ("I want to manage profiles") rather than technical layer ("all Click groups together"). This aligns with existing `@profiles` and `@config` group boundaries and matches user mental models.

**Why subprocess wrapper?** The original cli.py had 33 identical `subprocess.run(capture_output=True, text=True, timeout=10)` calls. The wrapper provides single point for logging, error handling, and timeout defaults. Maintainability benefit outweighs the microscopic overhead (~1μs per call).

**Why ProcessManager class?** Replaces global `_gpg_forwarder_process` and `_serena_process` variables. Encapsulates state in testable class matching adapter pattern (DockerRegistryClient, SubprocessGitClient). Enables test isolation and mocking.

**Why diagnostic registry with decorators?** 17 check functions + 5 fix functions all return `tuple[bool, str]`. Registry with `@diagnostic.check('name')` decorator provides auto-discovery without manual registration. Mirrors pytest's `@pytest.fixture` pattern (familiar to developers).

### Invariants

- **Entry point:** `cli.py` MUST contain callable `main()` function (pyproject.toml entry point: `devenv = cli:main`)
- **Command signatures:** Parameter names, types, defaults preserved (breaking changes affect user scripts)
- **Diagnostic signatures:** All check/fix functions MUST return `tuple[bool, str]` (doctor command depends on this)
- **Test imports:** When code moves, test imports MUST update to match

### Tradeoffs

| Decision | Cost | Benefit | Choice Rationale |
|----------|------|---------|------------------|
| Incremental refactoring | More commits, longer calendar time | Lower risk, easier rollback, independently testable | Risk reduction > calendar time |
| Decorator registry | Less explicit (must find decorators) | Cleaner syntax, auto-discovery | Code clarity > discoverability (pytest uses same pattern) |
| Subprocess wrapper | Extra function call (~1μs) | Eliminates 33 duplications, single point for logging | Maintainability >> microscopic performance cost |
| ProcessManager class | More code than globals | Testable in isolation, matches adapter pattern | Testability > simplicity |

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
