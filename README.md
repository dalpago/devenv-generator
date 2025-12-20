# devenv-generator

Generate Docker-based development environments for Claude Code YOLO mode.

## Installation

```bash
# Install with uv
uv pip install devenv-generator

# Or install from source
git clone https://github.com/mirustech/devenv-generator
cd devenv-generator
uv pip install -e .
```

## Usage

### Generate from default profile

```bash
# Generate in current directory
devenv generate

# Generate in specific directory
devenv generate --output ./my-project

# Use custom project name
devenv generate --output ./my-project --project-name my-awesome-project
```

### Use custom profile

```bash
# Generate from profile file
devenv generate --profile ./my-profile.yaml

# Override Python version
devenv generate --profile mirustech --python-version 3.13
```

### Manage profiles

```bash
# List available profiles
devenv profiles list

# Show profile details
devenv profiles show mirustech

# Create new profile template
devenv profiles create my-custom-profile
```

## Generated Files

The generator creates:

```
your-project/
├── .devcontainer/
│   ├── Dockerfile        # Full dev environment
│   ├── devcontainer.json # VS Code integration
│   └── init-env.sh       # Post-create setup
└── docker-compose.yml    # CLI-first usage
```

## Running the Container

### Docker Compose (recommended)

```bash
docker-compose run --rm dev

# Inside container
claude --dangerously-skip-permissions
```

### Direct Docker

```bash
docker build -t my-dev .devcontainer/
docker run -it --rm \
  -v $(pwd):/workspace \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  my-dev
```

### VS Code Dev Containers

1. Install the "Dev Containers" extension
2. Open the project folder
3. Click "Reopen in Container"

## Profile Format

Profiles are YAML files:

```yaml
name: my-profile
description: "My custom development environment"

python:
  version: "3.12"
  packages:
    - pytest
    - polars

uvx_tools:
  - pre-commit
  - ruff
  - mypy

system_packages:
  - git
  - vim
  - zsh

node_packages:
  - "@anthropic-ai/claude-code"

environment:
  ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"

network:
  mode: full  # full, restricted, or none

mounts:
  gitconfig: false
  ssh_keys: false
  claude_config: volume  # volume, bind, or none
```

## Default Profile: mirustech

The bundled `mirustech` profile includes:

- **Python 3.12** with pytest, polars, pydantic, structlog
- **Dev tools**: pre-commit, ruff, deptry, mypy (via uvx)
- **Shell**: zsh with delta (git diffs), bat (syntax highlighting)
- **Search**: ripgrep (rg), fd
- **Claude Code CLI** for YOLO mode

## License

MIT
