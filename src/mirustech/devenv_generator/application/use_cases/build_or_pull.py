"""Use case for building or pulling container images."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog
from rich.console import Console

from mirustech.devenv_generator.adapters.docker_registry import DockerRegistryClient
from mirustech.devenv_generator.adapters.git_client import SubprocessGitClient
from mirustech.devenv_generator.models import ImageSpec, sanitize_project_name
from mirustech.devenv_generator.settings import RegistryConfig

logger = structlog.get_logger()
console = Console()


@dataclass
class BuildOrPullResult:
    """Result of the build or pull operation."""

    image_spec: ImageSpec | None
    pulled: bool
    built: bool
    pushed: bool
    error: str | None = None


class BuildOrPullImageUseCase:
    """Orchestrates the pull → fallback to build → optional push workflow.

    This use case:
    1. Detects git SHA from project directory (falls back to 'latest')
    2. Sanitizes project name for registry compliance
    3. Creates an ImageSpec with registry/project:tag format
    4. Tries to authenticate with registry
    5. Attempts to pull from registry
    6. Falls back to local build if pull fails
    7. Optionally pushes newly built images to registry
    """

    def __init__(
        self,
        registry_client: DockerRegistryClient | None = None,
        git_client: SubprocessGitClient | None = None,
    ) -> None:
        """Initialize the use case.

        Args:
            registry_client: Docker registry client (created if not provided).
            git_client: Git client (created if not provided).
        """
        self.registry_client = registry_client or DockerRegistryClient()
        self.git_client = git_client or SubprocessGitClient()
        self.logger = logger.bind(component="build_or_pull")

    def execute(
        self,
        project_path: Path,
        project_name: str,
        registry_config: RegistryConfig,
        sandbox_dir: Path,
        sandbox_name: str,
        auto_push: bool = False,
    ) -> BuildOrPullResult:
        """Execute the build or pull workflow.

        Args:
            project_path: Path to the project (for git SHA detection).
            project_name: Name of the project.
            registry_config: Registry configuration.
            sandbox_dir: Directory containing docker-compose.yml.
            sandbox_name: Name of the sandbox (used for docker compose).
            auto_push: Whether to push after building.

        Returns:
            BuildOrPullResult with image spec and operation status.
        """
        # Detect git SHA
        tag = self._get_tag(project_path)

        # Create image spec
        sanitized_name = sanitize_project_name(project_name)
        image_spec = ImageSpec(
            registry=registry_config.url,
            project=sanitized_name,
            tag=tag,
        )

        self.logger.info(
            "registry_workflow_start",
            image=image_spec.full_name,
            project_path=str(project_path),
        )

        # Try to authenticate
        if not self.registry_client.authenticate(registry_config.url, registry_config):
            self.logger.warning(
                "registry_auth_failed",
                registry=registry_config.url,
                fallback="building_locally",
            )
            console.print("[yellow]Registry auth failed, building locally...[/yellow]")
            return self._build_locally(image_spec, sandbox_dir, sandbox_name, auto_push=False)

        # Try to pull
        console.print(f"[dim]Pulling from registry: {image_spec.full_name}[/dim]")
        if self.registry_client.pull_image(image_spec):
            console.print(f"[green]✓ Using cached image:[/green] {image_spec.full_name}")
            return BuildOrPullResult(
                image_spec=image_spec,
                pulled=True,
                built=False,
                pushed=False,
            )

        # Pull failed, build locally
        console.print("[dim]Image not found in registry, building locally...[/dim]")
        return self._build_locally(image_spec, sandbox_dir, sandbox_name, auto_push)

    def _get_tag(self, project_path: Path) -> str:
        """Get the tag for the image.

        Uses git SHA if available, otherwise 'latest'.

        Args:
            project_path: Path to the project.

        Returns:
            Tag string (git SHA or 'latest').
        """
        if self.git_client.is_git_repository(project_path):
            sha = self.git_client.get_commit_sha(project_path)
            if sha:
                self.logger.debug("using_git_sha", sha=sha[:12])
                return sha

        self.logger.debug("using_latest_tag", reason="no_git_sha")
        return "latest"

    def _build_locally(
        self,
        image_spec: ImageSpec,
        sandbox_dir: Path,
        sandbox_name: str,
        auto_push: bool,
    ) -> BuildOrPullResult:
        """Build the image locally.

        Args:
            image_spec: Target image specification.
            sandbox_dir: Directory containing docker-compose.yml.
            sandbox_name: Name of the sandbox.
            auto_push: Whether to push after building.

        Returns:
            BuildOrPullResult with operation status.
        """
        console.print("[dim]Building container...[/dim]")

        # Build using docker compose
        build_result = subprocess.run(
            ["docker", "compose", "-p", sandbox_name, "build"],
            cwd=sandbox_dir,
        )

        if build_result.returncode != 0:
            self.logger.error("build_failed", sandbox_name=sandbox_name)
            return BuildOrPullResult(
                image_spec=None,
                pulled=False,
                built=False,
                pushed=False,
                error="Build failed",
            )

        console.print("[green]✓ Built successfully[/green]")

        # Get the built image name (docker compose uses project_service format)
        local_image_name = f"{sandbox_name}-dev"

        # Tag with registry name
        if not self.registry_client.tag_image(local_image_name, image_spec):
            self.logger.warning(
                "tag_failed",
                source=local_image_name,
                target=image_spec.full_name,
            )
            # Continue without registry tagging - local build still works
            return BuildOrPullResult(
                image_spec=image_spec,
                pulled=False,
                built=True,
                pushed=False,
            )

        # Also tag as latest
        latest_spec = image_spec.with_tag("latest")
        self.registry_client.tag_image(local_image_name, latest_spec)

        # Push if requested
        pushed = False
        if auto_push:
            console.print("[dim]Pushing to registry...[/dim]")
            if self.registry_client.push_image(image_spec):
                console.print(f"[green]✓ Pushed {image_spec.full_name}[/green]")
                pushed = True

                # Also push latest
                if self.registry_client.push_image(latest_spec):
                    console.print(f"[green]✓ Pushed {latest_spec.full_name}[/green]")
            else:
                console.print("[yellow]Push failed, continuing with local image[/yellow]")

        return BuildOrPullResult(
            image_spec=image_spec,
            pulled=False,
            built=True,
            pushed=pushed,
        )


def build_or_pull_image(
    project_path: Path,
    project_name: str,
    registry_config: RegistryConfig,
    sandbox_dir: Path,
    sandbox_name: str,
    auto_push: bool = False,
) -> BuildOrPullResult:
    """Convenience function to execute the build or pull workflow.

    Args:
        project_path: Path to the project (for git SHA detection).
        project_name: Name of the project.
        registry_config: Registry configuration.
        sandbox_dir: Directory containing docker-compose.yml.
        sandbox_name: Name of the sandbox.
        auto_push: Whether to push after building.

    Returns:
        BuildOrPullResult with image spec and operation status.
    """
    use_case = BuildOrPullImageUseCase()
    return use_case.execute(
        project_path=project_path,
        project_name=project_name,
        registry_config=registry_config,
        sandbox_dir=sandbox_dir,
        sandbox_name=sandbox_name,
        auto_push=auto_push,
    )
