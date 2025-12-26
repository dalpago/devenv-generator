"""Adapters for external systems."""

from mirustech.devenv_generator.adapters.docker_registry import DockerRegistryClient
from mirustech.devenv_generator.adapters.git_client import SubprocessGitClient

__all__ = ["DockerRegistryClient", "SubprocessGitClient"]
