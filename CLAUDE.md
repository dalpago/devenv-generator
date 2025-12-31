# CLAUDE.md

## Overview

Development environment generator for running Claude Code in isolated Docker containers with auto-configured Python environments.

## Index

| File/Directory | Contents (WHAT) | Read When (WHEN) |
|----------------|-----------------|------------------|
| `README.md` | User guide, quick start, architecture | Understanding tool capabilities, setup troubleshooting |
| `pyproject.toml` | Package metadata, dependencies, entry points | Modifying dependencies, build configuration |
| `src/mirustech/devenv_generator/cli.py` | CLI orchestrator, main entry point, command registration | Debugging CLI routing, adding new command groups |
| `src/mirustech/devenv_generator/commands/` | Command group modules | Adding/modifying CLI commands |
| `src/mirustech/devenv_generator/commands/profiles.py` | Profile management (list, show, create, edit, delete) | Working with profiles, profile validation |
| `src/mirustech/devenv_generator/commands/config.py` | Global configuration (show, set-registry, edit) | Modifying config management, registry setup |
| `src/mirustech/devenv_generator/commands/lifecycle.py` | Sandbox lifecycle (run, attach, stop, start, cd) | Debugging sandbox startup/shutdown, mount handling |
| `src/mirustech/devenv_generator/commands/management.py` | Sandbox management (status, rm, clean) | Debugging sandbox listing, cleanup operations |
| `src/mirustech/devenv_generator/commands/diagnostics.py` | Health checks, auto-fixes, diagnostic registry | Adding diagnostics, debugging doctor command |
| `src/mirustech/devenv_generator/utils/` | Shared utilities | Modifying subprocess execution, process management |
| `src/mirustech/devenv_generator/utils/subprocess.py` | Subprocess wrapper with logging, timeouts | Changing subprocess behavior, adding logging |
| `src/mirustech/devenv_generator/utils/process_manager.py` | Background process lifecycle (GPG, Serena) | Debugging background process cleanup, timeout issues |
| `src/mirustech/devenv_generator/generator.py` | Container generation, profile loading | Modifying Dockerfile generation, template rendering |
| `src/mirustech/devenv_generator/models.py` | Pydantic models (ProfileConfig, MountSpec, ImageSpec) | Adding profile fields, validation rules |
| `src/mirustech/devenv_generator/settings.py` | Configuration management, environment variables | Modifying global settings, config paths |
| `src/mirustech/devenv_generator/use_cases/` | Business logic, domain operations | Adding features that span multiple adapters |
| `src/mirustech/devenv_generator/adapters/` | External system integrations (Docker, Git) | Modifying Docker/Git interactions |
| `tests/` | Test suite | Writing tests, understanding test coverage |
| `tests/test_diagnostics.py` | Diagnostic registry tests | Testing check/fix registration and execution |
| `tests/test_process_manager.py` | Process manager tests | Testing background process cleanup |
| `tests/test_subprocess.py` | Subprocess wrapper tests | Testing subprocess execution, timeouts |
