"""Tests for build_or_pull use case."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mirustech.devenv_generator.application.use_cases.build_or_pull import (
    BuildOrPullImageUseCase,
    BuildOrPullResult,
    build_or_pull_image,
)
from mirustech.devenv_generator.models import ImageSpec
from mirustech.devenv_generator.settings import RegistryConfig


class TestBuildOrPullResult:
    """Tests for BuildOrPullResult dataclass."""

    def test_result_with_image(self) -> None:
        """Test result with an image spec."""
        spec = ImageSpec(registry="registry.io", project="myproject", tag="abc123")
        result = BuildOrPullResult(
            image_spec=spec,
            pulled=True,
            built=False,
            pushed=False,
        )
        assert result.image_spec == spec
        assert result.pulled is True
        assert result.built is False
        assert result.pushed is False
        assert result.error is None

    def test_result_with_error(self) -> None:
        """Test result with an error."""
        result = BuildOrPullResult(
            image_spec=None,
            pulled=False,
            built=False,
            pushed=False,
            error="Build failed",
        )
        assert result.image_spec is None
        assert result.error == "Build failed"


class TestBuildOrPullImageUseCase:
    """Tests for BuildOrPullImageUseCase."""

    @pytest.fixture
    def mock_registry_client(self) -> MagicMock:
        """Create a mock registry client."""
        return MagicMock()

    @pytest.fixture
    def mock_git_client(self) -> MagicMock:
        """Create a mock git client."""
        return MagicMock()

    @pytest.fixture
    def registry_config(self) -> RegistryConfig:
        """Create a test registry config."""
        return RegistryConfig(
            enabled=True,
            url="registry.example.com",
        )

    def test_init_creates_default_clients(self) -> None:
        """Test that default clients are created if not provided."""
        use_case = BuildOrPullImageUseCase()
        assert use_case.registry_client is not None
        assert use_case.git_client is not None

    def test_init_uses_provided_clients(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
    ) -> None:
        """Test that provided clients are used."""
        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )
        assert use_case.registry_client is mock_registry_client
        assert use_case.git_client is mock_git_client

    def test_get_tag_with_git_sha(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test _get_tag returns git SHA when available."""
        mock_git_client.is_git_repository.return_value = True
        mock_git_client.get_commit_sha.return_value = "abc123def456789012345678901234567890abcd"

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        tag = use_case._get_tag(tmp_path)
        assert tag == "abc123def456789012345678901234567890abcd"
        mock_git_client.is_git_repository.assert_called_once_with(tmp_path)
        mock_git_client.get_commit_sha.assert_called_once_with(tmp_path)

    def test_get_tag_without_git(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test _get_tag returns 'latest' when not a git repo."""
        mock_git_client.is_git_repository.return_value = False

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        tag = use_case._get_tag(tmp_path)
        assert tag == "latest"

    def test_get_tag_git_sha_none(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test _get_tag returns 'latest' when SHA is None."""
        mock_git_client.is_git_repository.return_value = True
        mock_git_client.get_commit_sha.return_value = None

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        tag = use_case._get_tag(tmp_path)
        assert tag == "latest"

    def test_execute_auth_failed_builds_locally(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        registry_config: RegistryConfig,
        tmp_path: Path,
    ) -> None:
        """Test that auth failure falls back to local build."""
        mock_git_client.is_git_repository.return_value = False
        mock_registry_client.authenticate.return_value = False

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            mock_registry_client.tag_image.return_value = True

            result = use_case.execute(
                project_path=tmp_path,
                project_name="test-project",
                registry_config=registry_config,
                sandbox_dir=sandbox_dir,
                sandbox_name="test-sandbox",
                auto_push=False,
            )

        assert result.built is True
        assert result.pulled is False

    def test_execute_pull_succeeds(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        registry_config: RegistryConfig,
        tmp_path: Path,
    ) -> None:
        """Test successful pull from registry."""
        mock_git_client.is_git_repository.return_value = True
        mock_git_client.get_commit_sha.return_value = "abc123def456789012345678901234567890abcd"
        mock_registry_client.authenticate.return_value = True
        mock_registry_client.pull_image.return_value = True

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()

        result = use_case.execute(
            project_path=tmp_path,
            project_name="test-project",
            registry_config=registry_config,
            sandbox_dir=sandbox_dir,
            sandbox_name="test-sandbox",
            auto_push=False,
        )

        assert result.pulled is True
        assert result.built is False
        assert result.pushed is False
        assert result.image_spec is not None
        assert result.image_spec.project == "test-project"

    def test_execute_pull_fails_builds_locally(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        registry_config: RegistryConfig,
        tmp_path: Path,
    ) -> None:
        """Test that pull failure falls back to local build."""
        mock_git_client.is_git_repository.return_value = False
        mock_registry_client.authenticate.return_value = True
        mock_registry_client.pull_image.return_value = False
        mock_registry_client.tag_image.return_value = True

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = use_case.execute(
                project_path=tmp_path,
                project_name="test-project",
                registry_config=registry_config,
                sandbox_dir=sandbox_dir,
                sandbox_name="test-sandbox",
                auto_push=False,
            )

        assert result.built is True
        assert result.pulled is False

    def test_build_locally_failure(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test build failure returns error result."""
        image_spec = ImageSpec(registry="registry.io", project="test", tag="latest")

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)

            result = use_case._build_locally(
                image_spec=image_spec,
                sandbox_dir=sandbox_dir,
                sandbox_name="test-sandbox",
                auto_push=False,
            )

        assert result.built is False
        assert result.error == "Build failed"
        assert result.image_spec is None

    def test_build_locally_success_no_push(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test successful local build without push."""
        image_spec = ImageSpec(registry="registry.io", project="test", tag="latest")
        mock_registry_client.tag_image.return_value = True

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = use_case._build_locally(
                image_spec=image_spec,
                sandbox_dir=sandbox_dir,
                sandbox_name="test-sandbox",
                auto_push=False,
            )

        assert result.built is True
        assert result.pushed is False
        assert result.image_spec == image_spec

    def test_build_locally_with_push(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test successful local build with push."""
        image_spec = ImageSpec(registry="registry.io", project="test", tag="abc123")
        mock_registry_client.tag_image.return_value = True
        mock_registry_client.push_image.return_value = True

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = use_case._build_locally(
                image_spec=image_spec,
                sandbox_dir=sandbox_dir,
                sandbox_name="test-sandbox",
                auto_push=True,
            )

        assert result.built is True
        assert result.pushed is True
        # Verify push was called for both SHA and latest tags
        assert mock_registry_client.push_image.call_count == 2

    def test_build_locally_push_fails(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test that push failure still returns success for build."""
        image_spec = ImageSpec(registry="registry.io", project="test", tag="abc123")
        mock_registry_client.tag_image.return_value = True
        mock_registry_client.push_image.return_value = False

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = use_case._build_locally(
                image_spec=image_spec,
                sandbox_dir=sandbox_dir,
                sandbox_name="test-sandbox",
                auto_push=True,
            )

        assert result.built is True
        assert result.pushed is False  # Push failed

    def test_build_locally_tag_fails(
        self,
        mock_registry_client: MagicMock,
        mock_git_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test that tag failure still returns success for build."""
        image_spec = ImageSpec(registry="registry.io", project="test", tag="abc123")
        mock_registry_client.tag_image.return_value = False

        use_case = BuildOrPullImageUseCase(
            registry_client=mock_registry_client,
            git_client=mock_git_client,
        )

        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = use_case._build_locally(
                image_spec=image_spec,
                sandbox_dir=sandbox_dir,
                sandbox_name="test-sandbox",
                auto_push=True,
            )

        assert result.built is True
        assert result.pushed is False  # No push if tag failed


class TestBuildOrPullImageFunction:
    """Tests for the convenience function."""

    def test_build_or_pull_image_creates_use_case(self, tmp_path: Path) -> None:
        """Test that the function creates and executes a use case."""
        registry_config = RegistryConfig(enabled=True, url="registry.example.com")
        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()

        with (
            patch.object(BuildOrPullImageUseCase, "execute") as mock_execute,
            patch.object(BuildOrPullImageUseCase, "__init__", return_value=None) as mock_init,
        ):
            mock_execute.return_value = BuildOrPullResult(
                image_spec=None,
                pulled=False,
                built=True,
                pushed=False,
            )

            result = build_or_pull_image(
                project_path=tmp_path,
                project_name="test-project",
                registry_config=registry_config,
                sandbox_dir=sandbox_dir,
                sandbox_name="test-sandbox",
                auto_push=False,
            )

            mock_init.assert_called_once()
            mock_execute.assert_called_once()
            assert result.built is True
