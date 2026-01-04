"""Use case for making build decisions based on image state and configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from mirustech.devenv_generator.application.use_cases.build_or_pull import (
    BuildOrPullImageUseCase,
)
from mirustech.devenv_generator.generator import SandboxGenerator, compute_build_hash
from mirustech.devenv_generator.models import ImageSpec, MountSpec, ProfileConfig
from mirustech.devenv_generator.settings import RegistryConfig
from mirustech.devenv_generator.utils.subprocess import run_command

console = Console()


@dataclass
class BuildDecisionResult:
    """Result of build decision analysis."""

    skip_build: bool
    auto_no_cache: bool
    image_spec: ImageSpec | None


class BuildDecisionUseCase:
    """Determines whether to skip build, force rebuild, or use registry.

    This use case encapsulates the sequential decision algorithm for container builds:
    1. Check if image exists locally
    2. Compare build hash to detect configuration changes
    3. Attempt registry pull if enabled
    4. Decide whether to skip build or what cache strategy to use

    This is a ~140 line sequential algorithm accepted as exception to decomposition rules.
    """

    def execute(
        self,
        sandbox_name: str,
        sandbox_dir: Path,
        config: ProfileConfig,
        mount_specs: list[MountSpec],
        registry_config: RegistryConfig | None,
        no_cache: bool,
        no_registry: bool,
        no_host_config: bool,
        push_to_registry: bool,
    ) -> BuildDecisionResult:
        """Execute build decision logic.

        Args:
            sandbox_name: Name of the sandbox.
            sandbox_dir: Path to sandbox output directory.
            config: Profile configuration.
            mount_specs: List of mount specifications.
            registry_config: Registry configuration (None if disabled).
            no_cache: User requested no cache.
            no_registry: User disabled registry.
            no_host_config: User disabled host config mounting.
            push_to_registry: User requested registry push.

        Returns:
            BuildDecisionResult with skip_build, auto_no_cache, and image_spec.
        """
        build_hash_path = sandbox_dir / ".devcontainer" / ".build-hash"
        current_build_hash = compute_build_hash(config)
        auto_no_cache = False
        skip_build = False
        config_changed = False
        image_spec: ImageSpec | None = None

        # Check if image exists locally
        image_result = run_command(["docker", "images", "-q", f"{sandbox_name}-dev:latest"])
        image_exists = bool(image_result.stdout.strip())

        if not image_exists:
            console.print("[dim]No image found, will build[/dim]")
            config_changed = True
        elif build_hash_path.exists():
            stored_hash = build_hash_path.read_text().strip()
            if stored_hash != current_build_hash:
                console.print("[yellow]⚠ Build configuration changed - rebuild required[/yellow]")
                console.print("[dim]Changes detected in profile or templates[/dim]")
                config_changed = True
                # Force fresh build when configuration changes
                auto_no_cache = True
            elif not no_cache:
                console.print("[dim]Build configuration unchanged[/dim]")
        else:
            console.print("[yellow]No build hash found - forcing rebuild for safety[/yellow]")
            auto_no_cache = True
            config_changed = True

        # Registry workflow if enabled
        if registry_config and registry_config.enabled and not no_registry:
            use_case = BuildOrPullImageUseCase()
            auto_push = push_to_registry or registry_config.auto_push

            # Generate sandbox with initial configuration
            generator = SandboxGenerator(
                profile=config,
                mounts=mount_specs,
                sandbox_name=sandbox_name,
                use_host_claude_config=not no_host_config,
            )
            generator.generate(sandbox_dir)

            # Attempt pull from registry
            result = use_case.execute(
                project_path=mount_specs[0].host_path,
                project_name=sandbox_name,
                registry_config=registry_config,
                sandbox_dir=sandbox_dir,
                sandbox_name=sandbox_name,
                auto_push=auto_push,
            )

            # If pull succeeded, regenerate with image spec
            if result.image_spec:
                image_spec = result.image_spec
                skip_build = True
                generator = SandboxGenerator(
                    profile=config,
                    mounts=mount_specs,
                    sandbox_name=sandbox_name,
                    use_host_claude_config=not no_host_config,
                    image_spec=image_spec,
                )
                generator.generate(sandbox_dir)
        else:
            # No registry, just generate with default configuration
            generator = SandboxGenerator(
                profile=config,
                mounts=mount_specs,
                sandbox_name=sandbox_name,
                use_host_claude_config=not no_host_config,
            )
            generator.generate(sandbox_dir)

        # Final skip_build decision: skip if image exists, config unchanged, and not using registry
        if not config_changed and image_exists and not no_cache and not skip_build:
            console.print("[dim]Image up-to-date, skipping build[/dim]")
            skip_build = True

        return BuildDecisionResult(
            skip_build=skip_build,
            auto_no_cache=auto_no_cache,
            image_spec=image_spec,
        )
