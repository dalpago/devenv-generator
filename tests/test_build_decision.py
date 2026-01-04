"""Tests for BuildDecisionUseCase."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from mirustech.devenv_generator.application.use_cases.build_decision import (
    BuildDecisionResult,
    BuildDecisionUseCase,
)
from mirustech.devenv_generator.application.use_cases.build_or_pull import BuildOrPullResult
from mirustech.devenv_generator.models import ImageSpec, MountSpec, ProfileConfig, PythonConfig
from mirustech.devenv_generator.settings import RegistryConfig


@pytest.fixture
def mock_profile():
    """Create a mock profile configuration."""
    return ProfileConfig(
        name="test",
        description="Test profile",
        python=PythonConfig(version="3.12"),
    )


@pytest.fixture
def mount_specs(tmp_path):
    """Create mock mount specifications."""
    project_path = tmp_path / "project"
    project_path.mkdir()
    return [MountSpec(host_path=project_path, container_path="/workspace", mode="rw")]


@pytest.fixture
def registry_config():
    """Create a mock registry configuration."""
    return RegistryConfig(
        enabled=True,
        url="registry.example.com",
        username="testuser",
        password="testpass",
        auto_push=False,
    )


@pytest.fixture
def sandbox_dir(tmp_path):
    """Create a sandbox directory."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    devcontainer = sandbox / ".devcontainer"
    devcontainer.mkdir()
    return sandbox


class TestBuildDecisionUseCase:
    """Tests for BuildDecisionUseCase."""

    def test_no_image_triggers_build(
        self, mock_profile, mount_specs, sandbox_dir
    ):
        """Test that missing image triggers a build."""
        use_case = BuildDecisionUseCase()

        with patch("mirustech.devenv_generator.application.use_cases.build_decision.run_command") as mock_run, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.compute_build_hash") as mock_hash, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.SandboxGenerator"):
            # No image exists
            mock_run.return_value = Mock(stdout="")
            mock_hash.return_value = "abc123"

            result = use_case.execute(
                sandbox_name="test-sandbox",
                sandbox_dir=sandbox_dir,
                config=mock_profile,
                mount_specs=mount_specs,
                registry_config=None,
                no_cache=False,
                no_registry=True,
                no_host_config=False,
                push_to_registry=False,
            )

            assert result.skip_build is False
            assert result.auto_no_cache is False
            assert result.image_spec is None

    def test_image_exists_config_unchanged_skips_build(
        self, mock_profile, mount_specs, sandbox_dir
    ):
        """Test that existing image with unchanged config skips build."""
        use_case = BuildDecisionUseCase()

        # Create build hash file
        build_hash_path = sandbox_dir / ".devcontainer" / ".build-hash"
        build_hash_path.write_text("abc123")

        with patch("mirustech.devenv_generator.application.use_cases.build_decision.run_command") as mock_run, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.compute_build_hash") as mock_hash, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.SandboxGenerator"):
            # Image exists
            mock_run.return_value = Mock(stdout="image-id-123")
            # Hash unchanged
            mock_hash.return_value = "abc123"

            result = use_case.execute(
                sandbox_name="test-sandbox",
                sandbox_dir=sandbox_dir,
                config=mock_profile,
                mount_specs=mount_specs,
                registry_config=None,
                no_cache=False,
                no_registry=True,
                no_host_config=False,
                push_to_registry=False,
            )

            assert result.skip_build is True
            assert result.auto_no_cache is False
            assert result.image_spec is None

    def test_config_changed_triggers_rebuild_with_no_cache(
        self, mock_profile, mount_specs, sandbox_dir
    ):
        """Test that configuration change triggers rebuild with --no-cache."""
        use_case = BuildDecisionUseCase()

        # Create build hash file with old hash
        build_hash_path = sandbox_dir / ".devcontainer" / ".build-hash"
        build_hash_path.write_text("old-hash")

        with patch("mirustech.devenv_generator.application.use_cases.build_decision.run_command") as mock_run, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.compute_build_hash") as mock_hash, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.SandboxGenerator"):
            # Image exists
            mock_run.return_value = Mock(stdout="image-id-123")
            # Hash changed
            mock_hash.return_value = "new-hash"

            result = use_case.execute(
                sandbox_name="test-sandbox",
                sandbox_dir=sandbox_dir,
                config=mock_profile,
                mount_specs=mount_specs,
                registry_config=None,
                no_cache=False,
                no_registry=True,
                no_host_config=False,
                push_to_registry=False,
            )

            assert result.skip_build is False
            assert result.auto_no_cache is True
            assert result.image_spec is None

    def test_missing_build_hash_forces_rebuild(
        self, mock_profile, mount_specs, sandbox_dir
    ):
        """Test that missing build hash forces rebuild with --no-cache."""
        use_case = BuildDecisionUseCase()

        with patch("mirustech.devenv_generator.application.use_cases.build_decision.run_command") as mock_run, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.compute_build_hash") as mock_hash, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.SandboxGenerator"):
            # Image exists
            mock_run.return_value = Mock(stdout="image-id-123")
            mock_hash.return_value = "abc123"

            result = use_case.execute(
                sandbox_name="test-sandbox",
                sandbox_dir=sandbox_dir,
                config=mock_profile,
                mount_specs=mount_specs,
                registry_config=None,
                no_cache=False,
                no_registry=True,
                no_host_config=False,
                push_to_registry=False,
            )

            assert result.skip_build is False
            assert result.auto_no_cache is True
            assert result.image_spec is None

    def test_user_no_cache_flag_respected(
        self, mock_profile, mount_specs, sandbox_dir
    ):
        """Test that user --no-cache flag is respected."""
        use_case = BuildDecisionUseCase()

        # Create build hash file
        build_hash_path = sandbox_dir / ".devcontainer" / ".build-hash"
        build_hash_path.write_text("abc123")

        with patch("mirustech.devenv_generator.application.use_cases.build_decision.run_command") as mock_run, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.compute_build_hash") as mock_hash, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.SandboxGenerator"):
            # Image exists, config unchanged
            mock_run.return_value = Mock(stdout="image-id-123")
            mock_hash.return_value = "abc123"

            result = use_case.execute(
                sandbox_name="test-sandbox",
                sandbox_dir=sandbox_dir,
                config=mock_profile,
                mount_specs=mount_specs,
                registry_config=None,
                no_cache=True,  # User requested no-cache
                no_registry=True,
                no_host_config=False,
                push_to_registry=False,
            )

            # Should not skip build because user requested no-cache
            assert result.skip_build is False
            assert result.auto_no_cache is False

    def test_registry_pull_success_skips_build(
        self, mock_profile, mount_specs, sandbox_dir, registry_config
    ):
        """Test that successful registry pull skips build."""
        use_case = BuildDecisionUseCase()

        image_spec = ImageSpec(
            registry="registry.example.com",
            project="test-project",
            tag="abc123",
        )

        with patch("mirustech.devenv_generator.application.use_cases.build_decision.run_command") as mock_run, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.compute_build_hash") as mock_hash, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.SandboxGenerator"), \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.BuildOrPullImageUseCase") as mock_use_case:
            # Image exists locally
            mock_run.return_value = Mock(stdout="image-id-123")
            mock_hash.return_value = "abc123"

            # Registry pull succeeds
            mock_instance = mock_use_case.return_value
            mock_instance.execute.return_value = BuildOrPullResult(
                image_spec=image_spec,
                pulled=True,
                built=False,
                pushed=False,
            )

            result = use_case.execute(
                sandbox_name="test-sandbox",
                sandbox_dir=sandbox_dir,
                config=mock_profile,
                mount_specs=mount_specs,
                registry_config=registry_config,
                no_cache=False,
                no_registry=False,
                no_host_config=False,
                push_to_registry=False,
            )

            assert result.skip_build is True
            assert result.image_spec == image_spec
            # Verify BuildOrPullImageUseCase was called
            mock_instance.execute.assert_called_once()

    def test_registry_pull_fail_falls_back_to_build(
        self, mock_profile, mount_specs, sandbox_dir, registry_config
    ):
        """Test that failed registry pull falls back to build."""
        use_case = BuildDecisionUseCase()

        with patch("mirustech.devenv_generator.application.use_cases.build_decision.run_command") as mock_run, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.compute_build_hash") as mock_hash, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.SandboxGenerator"), \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.BuildOrPullImageUseCase") as mock_use_case:
            # No image exists
            mock_run.return_value = Mock(stdout="")
            mock_hash.return_value = "abc123"

            # Registry pull fails
            mock_instance = mock_use_case.return_value
            mock_instance.execute.return_value = BuildOrPullResult(
                image_spec=None,
                pulled=False,
                built=False,
                pushed=False,
                error="Pull failed",
            )

            result = use_case.execute(
                sandbox_name="test-sandbox",
                sandbox_dir=sandbox_dir,
                config=mock_profile,
                mount_specs=mount_specs,
                registry_config=registry_config,
                no_cache=False,
                no_registry=False,
                no_host_config=False,
                push_to_registry=False,
            )

            # Should not skip build
            assert result.skip_build is False
            assert result.image_spec is None

    def test_registry_disabled_by_flag(
        self, mock_profile, mount_specs, sandbox_dir, registry_config
    ):
        """Test that --no-registry flag disables registry."""
        use_case = BuildDecisionUseCase()

        with patch("mirustech.devenv_generator.application.use_cases.build_decision.run_command") as mock_run, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.compute_build_hash") as mock_hash, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.SandboxGenerator"), \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.BuildOrPullImageUseCase") as mock_use_case:
            # Image exists
            mock_run.return_value = Mock(stdout="image-id-123")
            mock_hash.return_value = "abc123"

            # Create build hash file
            build_hash_path = sandbox_dir / ".devcontainer" / ".build-hash"
            build_hash_path.write_text("abc123")

            result = use_case.execute(
                sandbox_name="test-sandbox",
                sandbox_dir=sandbox_dir,
                config=mock_profile,
                mount_specs=mount_specs,
                registry_config=registry_config,
                no_cache=False,
                no_registry=True,  # Registry disabled by flag
                no_host_config=False,
                push_to_registry=False,
            )

            # Should skip build (image exists, config unchanged)
            assert result.skip_build is True
            # BuildOrPullImageUseCase should not be called
            mock_use_case.return_value.execute.assert_not_called()

    def test_generator_called_with_correct_parameters(
        self, mock_profile, mount_specs, sandbox_dir
    ):
        """Test that SandboxGenerator is called with correct parameters."""
        use_case = BuildDecisionUseCase()

        with patch("mirustech.devenv_generator.application.use_cases.build_decision.run_command") as mock_run, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.compute_build_hash") as mock_hash, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.SandboxGenerator") as mock_generator:
            # No image exists
            mock_run.return_value = Mock(stdout="")
            mock_hash.return_value = "abc123"

            use_case.execute(
                sandbox_name="test-sandbox",
                sandbox_dir=sandbox_dir,
                config=mock_profile,
                mount_specs=mount_specs,
                registry_config=None,
                no_cache=False,
                no_registry=True,
                no_host_config=False,
                push_to_registry=False,
            )

            # Verify generator was called
            mock_generator.assert_called_once_with(
                profile=mock_profile,
                mounts=mount_specs,
                sandbox_name="test-sandbox",
                use_host_claude_config=True,  # no_host_config=False
            )
            # Verify generate was called
            mock_generator.return_value.generate.assert_called_once_with(sandbox_dir)

    def test_generator_respects_no_host_config(
        self, mock_profile, mount_specs, sandbox_dir
    ):
        """Test that no_host_config is properly passed to generator."""
        use_case = BuildDecisionUseCase()

        with patch("mirustech.devenv_generator.application.use_cases.build_decision.run_command") as mock_run, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.compute_build_hash") as mock_hash, \
             patch("mirustech.devenv_generator.application.use_cases.build_decision.SandboxGenerator") as mock_generator:
            # No image exists
            mock_run.return_value = Mock(stdout="")
            mock_hash.return_value = "abc123"

            use_case.execute(
                sandbox_name="test-sandbox",
                sandbox_dir=sandbox_dir,
                config=mock_profile,
                mount_specs=mount_specs,
                registry_config=None,
                no_cache=False,
                no_registry=True,
                no_host_config=True,  # Disable host config
                push_to_registry=False,
            )

            # Verify generator was called with use_host_claude_config=False
            mock_generator.assert_called_once_with(
                profile=mock_profile,
                mounts=mount_specs,
                sandbox_name="test-sandbox",
                use_host_claude_config=False,  # no_host_config=True
            )
