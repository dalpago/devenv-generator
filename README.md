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

# Run with ports exposed (for web development)
devenv run --expose-port 8000 --expose-port 5173

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

## Port Exposure

Expose ports from your container to access web servers, APIs, or other services running inside:

```bash
# Start with ports exposed
devenv run --expose-port 8000
devenv run --expose-port 8000 --expose-port 5173  # Multiple ports

# Dynamically expose ports on running container
devenv expose 8000
devenv expose 8080:3000        # Map host:container
devenv expose 5432/udp         # UDP protocol

# List exposed ports
devenv ports

# Remove exposed port
devenv unexpose 8000

# Start without any ports (even if profile defines them)
devenv run --no-ports
```

**Port Formats:**
- `8000` - Expose container port 8000 on host port 8000 (TCP)
- `8080:3000` - Map host port 8080 to container port 3000
- `5432/udp` - Expose UDP port
- `8080:3000/udp` - Full format with host, container, and protocol

**Static Configuration:**

Define default ports in your profile YAML:

```yaml
name: webapp
ports:
  ports:
    - container: 8000
      host: 8000
      description: "Django dev server"
      protocol: tcp
    - container: 5173
      host: 5173
      description: "Vite dev server"
```

All ports bind to `127.0.0.1` (localhost only) for security.

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

## Environment Parity

Containers can mirror your host shell environment via profile configuration.

### Starship Prompt

When `shell.starship` is enabled, the container installs Starship and applies the specified preset at build time. The prompt in the container matches your host.

```yaml
shell:
  starship: true
  starship_preset: "catppuccin-powerline"  # Any preset from starship.rs/presets
```

### Dotfiles via chezmoi

When `dotfiles.chezmoi_repo` is set, the container entrypoint runs `chezmoi init --apply --exclude=scripts` on first start, applying configuration files (.zshrc, starship.toml, git config) without executing install scripts. Package installation remains the Dockerfile's responsibility. For SOPS-encrypted dotfiles, mount your host age key with `chezmoi_age_key: true`.

```yaml
dotfiles:
  chezmoi_repo: "https://github.com/youruser/dotfiles.git"
  chezmoi_age_key: false  # Set true to mount ~/.config/sops/age/keys.txt from host
```

Both features are opt-in and disabled by default. Enable them in a profile with `devenv profiles edit`.

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
  ├── ports.py (3 commands: expose, unexpose, ports)
  └── diagnostics.py (doctor command + DiagnosticRegistry with 17 checks, 5 fixes)

utils/
  ├── subprocess.py (run_command wrapper + exponential backoff)
  └── process_manager.py (ProcessManager for background processes)

application/use_cases/
  └── build_decision.py (BuildDecisionUseCase - build skip/rebuild logic)
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
  → wait_with_exponential_backoff(check_fn, timeout=30)
      → Retry with delays: 1s → 2s → 4s → 8s → 16s (capped at 16s)
  → atexit.register(cleanup_all)
  → On exit: terminate → wait(5s) → kill if needed
```

**Build decision:**
```
devenv run
  → lifecycle.py:run()
  → BuildDecisionUseCase(docker_client, generator)
  → should_build() checks:
      - Image exists?
      - Profile changed?
      - Dockerfile changed?
  → Return: (should_build: bool, reason: str)
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

**Why exponential backoff?** Background processes (Serena, GPG) need health checks before Docker start. Linear delays (1s, 1s, 1s...) waste time on fast starts; exponential (1s→2s→4s→8s→16s capped at 16s) provides quick feedback for fast starts while handling slow systems.

**Why BuildDecisionUseCase?** Encapsulates complex build skip logic (image existence, profile changes, Dockerfile changes) in single testable component. Separates decision logic from command layer following use case pattern.

**Why property-based tests?** Port and mount specs accept diverse formats (8000, 8080:3000, /path:ro). Property-based tests using hypothesis generate thousands of valid/invalid inputs to verify parsing robustness beyond manual examples.

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
2. **Mounts** your project at `/workspace/<project-name>` and at its real host path (host-path mirror — required for Docker-in-Docker; see below)
3. **Copies** from host into container:
   - `~/.claude` (OAuth, CLAUDE.md, MCP servers, agents, skills, output-styles)
   - `~/.happy` (Happy Coder config and credentials)
   - `~/.ssh` (SSH keys, config, known_hosts with agent forwarding support)
4. **Runs** `uv sync` to install project dependencies
5. **Starts** Claude Code with `--dangerously-skip-permissions`

Container files are stored in `~/.local/share/devenv-sandboxes/<project>/`.

### Docker-in-Docker / sibling containers

The sandbox shares the host's `/var/run/docker.sock`, so `docker run` and `docker compose build` issued from inside the sandbox are served by the **host** Docker daemon. The host daemon only knows host filesystem paths — it has no concept of `/workspace`. To make sibling-container bind mounts and build contexts work, every project mount is exposed at **two** paths inside the sandbox:

- `/workspace/<name>` — the conventional UX path. Use this for editors, scripts, in-sandbox tooling.
- `<host_path>` (e.g. `/Users/you/Code/myproject`) — the host-path mirror. Use this whenever a Docker command needs to reach the host daemon.

```bash
# Inside the sandbox, for sibling containers:
docker run --rm -v /Users/you/Code/myproject/data:/data alpine ls /data   # works
docker run --rm -v /workspace/myproject/data:/data alpine ls /data        # FAILS

# For docker compose build / docker build with a relative context:
cd /Users/you/Code/myproject     # not /workspace/myproject
docker compose build
```

Both paths are bind mounts of the same host source — anything you write under either is reflected on the host immediately and visible to siblings.

`cow`-mode mounts mirror only the read-only base on the host path; the writable upper layer is sandbox-local tmpfs and is not DinD-shareable.

To reach **already-running** sibling containers by service name (instead of via host-path bind mounts), attach the sandbox to their Docker network with `--network`:

```bash
# Sibling stack 'jmz-data-gen' is already up on network jmz-data-gen_api-network
devenv run --network jmz-data-gen_api-network ~/Code/myproject
# Inside the sandbox, service-name DNS now resolves:
curl http://metadata-api:8000/health
```

The network must already exist (it is declared `external`). A container's network membership is fixed at creation, so pass `--network` at `devenv run` time — repeat the flag for multiple networks. Ignored when the profile's network mode is `none`.

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
  --shell, -s                Drop to shell instead of starting Claude
  --detach, -d               Run in background
  --python VERSION           Override Python version
  --profile, -p NAME         Use a specific profile (default: default)
  --no-host-config           Don't mount ~/.claude (isolated Claude config)
  -o, --output PATH          Custom output directory
  -n, --name NAME            Custom sandbox name
  --expose-port PORT         Expose port at startup (can be used multiple times)
  --no-ports                 Disable all ports (overrides profile configuration)
  --network NAME             Attach to an existing external Docker network (repeatable)
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

**Available Templates:**

- **default**: General-purpose Python development with comprehensive tooling
- **minimal**: Fast iteration (<2min build) — Python + essentials only, ideal for small projects and prototyping
- **web-dev**: Modern web development — Node.js 22, Vite, TypeScript, ESLint, Tailwind CSS for frontend/fullstack work
- **data-science**: ML and data analysis — numpy, pandas, scikit-learn, jupyter for data science workflows

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

# Use a specific profile
devenv run --profile minimal        # Fast iteration
devenv run --profile web-dev         # Web development
devenv run --profile data-science    # ML/data analysis
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

## Development

### Testing

The project includes comprehensive unit and integration tests:

```bash
# Run unit tests (fast, no Docker required)
pytest

# Run integration tests (requires Docker)
pytest -m integration

# Run all tests
pytest -m ""

# Run specific test file
pytest tests/test_lifecycle.py

# Generate coverage report
pytest --cov=src/mirustech/devenv_generator --cov-report=html
```

### Project Structure

See the Architecture section above for detailed information about:
- Command organization
- Data flow
- Design decisions
- Invariants and tradeoffs

## License

MIT
