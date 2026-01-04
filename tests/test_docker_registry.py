"""Tests for docker registry adapter."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from mirustech.devenv_generator.adapters.docker_registry import (
    DockerRegistryClient,
)
from mirustech.devenv_generator.models import ImageSpec
from mirustech.devenv_generator.settings import AuthMethod, RegistryConfig


class TestDockerRegistryClientInit:
    """Tests for DockerRegistryClient initialization."""

    def test_default_timeout(self) -> None:
        """Test default timeout is 300 seconds."""
        client = DockerRegistryClient()
        assert client.timeout == 300

    def test_custom_timeout(self) -> None:
        """Test custom timeout can be set."""
        client = DockerRegistryClient(timeout=600)
        assert client.timeout == 600


class TestDockerRegistryClientAuthenticate:
    """Tests for authenticate method."""

    def test_authenticate_existing_method(self) -> None:
        """Test authenticate routes to existing auth method."""
        client = DockerRegistryClient()
        config = RegistryConfig(
            enabled=True,
            url="registry.example.com",
            auth_method=AuthMethod.EXISTING,
        )

        with patch.object(client, "_check_existing_auth", return_value=True) as mock:
            result = client.authenticate("registry.example.com", config)
            assert result is True
            mock.assert_called_once_with("registry.example.com")

    def test_authenticate_stored_method(self) -> None:
        """Test authenticate routes to stored auth method."""
        client = DockerRegistryClient()
        config = RegistryConfig(
            enabled=True,
            url="registry.example.com",
            auth_method=AuthMethod.STORED,
            username="user",
            password=SecretStr("pass"),
        )

        with patch.object(client, "_login_with_stored", return_value=True) as mock:
            result = client.authenticate("registry.example.com", config)
            assert result is True
            mock.assert_called_once_with("registry.example.com", config)

    def test_authenticate_prompt_method(self) -> None:
        """Test authenticate routes to prompt auth method."""
        client = DockerRegistryClient()
        config = RegistryConfig(
            enabled=True,
            url="registry.example.com",
            auth_method=AuthMethod.PROMPT,
        )

        with patch.object(client, "_login_with_prompt", return_value=True) as mock:
            result = client.authenticate("registry.example.com", config)
            assert result is True
            mock.assert_called_once_with("registry.example.com")


class TestCheckExistingAuth:
    """Tests for _check_existing_auth method."""

    def test_existing_auth_valid(self) -> None:
        """Test returns True when auth is valid."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = client._check_existing_auth("registry.example.com")
            assert result is True

    def test_existing_auth_not_found(self) -> None:
        """Test returns False when auth not found."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = client._check_existing_auth("registry.example.com")
            assert result is False

    def test_existing_auth_timeout(self) -> None:
        """Test returns False on timeout."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=10)
            result = client._check_existing_auth("registry.example.com")
            assert result is False

    def test_existing_auth_docker_not_found(self) -> None:
        """Test returns False when docker not installed."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = client._check_existing_auth("registry.example.com")
            assert result is False

    def test_existing_auth_os_error(self) -> None:
        """Test returns False on OS error."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Permission denied")
            result = client._check_existing_auth("registry.example.com")
            assert result is False


class TestLoginWithStored:
    """Tests for _login_with_stored method."""

    def test_stored_login_success(self) -> None:
        """Test successful login with stored credentials."""
        client = DockerRegistryClient()
        config = RegistryConfig(
            enabled=True,
            url="registry.example.com",
            auth_method=AuthMethod.STORED,
            username="testuser",
            password=SecretStr("testpass"),
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = client._login_with_stored("registry.example.com", config)
            assert result is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args.kwargs["input"] == "testpass"

    def test_stored_login_missing_username(self) -> None:
        """Test returns False when username is missing."""
        client = DockerRegistryClient()
        config = RegistryConfig(
            enabled=True,
            url="registry.example.com",
            auth_method=AuthMethod.STORED,
            password=SecretStr("testpass"),
        )

        result = client._login_with_stored("registry.example.com", config)
        assert result is False

    def test_stored_login_missing_password(self) -> None:
        """Test returns False when password is missing."""
        client = DockerRegistryClient()
        config = RegistryConfig(
            enabled=True,
            url="registry.example.com",
            auth_method=AuthMethod.STORED,
            username="testuser",
        )

        result = client._login_with_stored("registry.example.com", config)
        assert result is False

    def test_stored_login_failed(self) -> None:
        """Test returns False when login fails."""
        client = DockerRegistryClient()
        config = RegistryConfig(
            enabled=True,
            url="registry.example.com",
            auth_method=AuthMethod.STORED,
            username="testuser",
            password=SecretStr("testpass"),
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="Invalid credentials")
            result = client._login_with_stored("registry.example.com", config)
            assert result is False

    def test_stored_login_timeout(self) -> None:
        """Test returns False on timeout."""
        client = DockerRegistryClient()
        config = RegistryConfig(
            enabled=True,
            url="registry.example.com",
            auth_method=AuthMethod.STORED,
            username="testuser",
            password=SecretStr("testpass"),
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=30)
            result = client._login_with_stored("registry.example.com", config)
            assert result is False

    def test_stored_login_os_error(self) -> None:
        """Test returns False on OS error."""
        client = DockerRegistryClient()
        config = RegistryConfig(
            enabled=True,
            url="registry.example.com",
            auth_method=AuthMethod.STORED,
            username="testuser",
            password=SecretStr("testpass"),
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Error")
            result = client._login_with_stored("registry.example.com", config)
            assert result is False


class TestPullImage:
    """Tests for pull_image method."""

    @pytest.fixture
    def image_spec(self) -> ImageSpec:
        """Create a test image spec."""
        return ImageSpec(registry="registry.io", project="myproject", tag="abc123")

    def test_pull_success(self, image_spec: ImageSpec) -> None:
        """Test successful image pull."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = client.pull_image(image_spec)
            assert result is True

    def test_pull_not_found(self, image_spec: ImageSpec) -> None:
        """Test pull when image not found."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="manifest unknown: not found",
            )
            result = client.pull_image(image_spec)
            assert result is False

    def test_pull_other_failure(self, image_spec: ImageSpec) -> None:
        """Test pull with other failure."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="permission denied",
            )
            result = client.pull_image(image_spec)
            assert result is False

    def test_pull_timeout(self, image_spec: ImageSpec) -> None:
        """Test pull timeout."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=300)
            result = client.pull_image(image_spec)
            assert result is False

    def test_pull_os_error(self, image_spec: ImageSpec) -> None:
        """Test pull OS error."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Error")
            result = client.pull_image(image_spec)
            assert result is False


class TestPushImage:
    """Tests for push_image method."""

    @pytest.fixture
    def image_spec(self) -> ImageSpec:
        """Create a test image spec."""
        return ImageSpec(registry="registry.io", project="myproject", tag="abc123")

    def test_push_success(self, image_spec: ImageSpec) -> None:
        """Test successful image push."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = client.push_image(image_spec)
            assert result is True

    def test_push_failure(self, image_spec: ImageSpec) -> None:
        """Test push failure."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="access denied",
            )
            result = client.push_image(image_spec)
            assert result is False

    def test_push_timeout(self, image_spec: ImageSpec) -> None:
        """Test push timeout."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=300)
            result = client.push_image(image_spec)
            assert result is False

    def test_push_os_error(self, image_spec: ImageSpec) -> None:
        """Test push OS error."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Error")
            result = client.push_image(image_spec)
            assert result is False


class TestTagImage:
    """Tests for tag_image method."""

    @pytest.fixture
    def target_spec(self) -> ImageSpec:
        """Create a target image spec."""
        return ImageSpec(registry="registry.io", project="myproject", tag="abc123")

    def test_tag_success(self, target_spec: ImageSpec) -> None:
        """Test successful image tagging."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = client.tag_image("source-image", target_spec)
            assert result is True

    def test_tag_failure(self, target_spec: ImageSpec) -> None:
        """Test tag failure."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="Error: No such image",
            )
            result = client.tag_image("source-image", target_spec)
            assert result is False

    def test_tag_timeout(self, target_spec: ImageSpec) -> None:
        """Test tag timeout."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=30)
            result = client.tag_image("source-image", target_spec)
            assert result is False

    def test_tag_os_error(self, target_spec: ImageSpec) -> None:
        """Test tag OS error."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Error")
            result = client.tag_image("source-image", target_spec)
            assert result is False


class TestImageExistsLocally:
    """Tests for image_exists_locally method."""

    @pytest.fixture
    def image_spec(self) -> ImageSpec:
        """Create a test image spec."""
        return ImageSpec(registry="registry.io", project="myproject", tag="abc123")

    def test_image_exists(self, image_spec: ImageSpec) -> None:
        """Test when image exists locally."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = client.image_exists_locally(image_spec)
            assert result is True

    def test_image_not_exists(self, image_spec: ImageSpec) -> None:
        """Test when image does not exist locally."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = client.image_exists_locally(image_spec)
            assert result is False

    def test_image_check_timeout(self, image_spec: ImageSpec) -> None:
        """Test timeout returns False."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=10)
            result = client.image_exists_locally(image_spec)
            assert result is False

    def test_image_check_os_error(self, image_spec: ImageSpec) -> None:
        """Test OS error returns False."""
        client = DockerRegistryClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Error")
            result = client.image_exists_locally(image_spec)
            assert result is False


class TestLoginWithPrompt:
    """Tests for _login_with_prompt method."""

    def test_prompt_login_success(self) -> None:
        """Test successful login with prompted credentials."""
        client = DockerRegistryClient()

        with (
            patch(
                "mirustech.devenv_generator.adapters.docker_registry.Prompt.ask"
            ) as mock_prompt,
            patch("subprocess.run") as mock_run,
        ):
            mock_prompt.side_effect = ["testuser", "testpass"]
            mock_run.return_value = MagicMock(returncode=0)

            result = client._login_with_prompt("registry.example.com")
            assert result is True

    def test_prompt_login_failure(self) -> None:
        """Test failed login with prompted credentials."""
        client = DockerRegistryClient()

        with (
            patch(
                "mirustech.devenv_generator.adapters.docker_registry.Prompt.ask"
            ) as mock_prompt,
            patch("subprocess.run") as mock_run,
        ):
            mock_prompt.side_effect = ["testuser", "wrongpass"]
            mock_run.return_value = MagicMock(
                returncode=1, stderr="Invalid credentials"
            )

            result = client._login_with_prompt("registry.example.com")
            assert result is False

    def test_prompt_login_timeout(self) -> None:
        """Test timeout during prompted login."""
        client = DockerRegistryClient()

        with (
            patch(
                "mirustech.devenv_generator.adapters.docker_registry.Prompt.ask"
            ) as mock_prompt,
            patch("subprocess.run") as mock_run,
        ):
            mock_prompt.side_effect = ["testuser", "testpass"]
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=30)

            result = client._login_with_prompt("registry.example.com")
            assert result is False

    def test_prompt_login_os_error(self) -> None:
        """Test OS error during prompted login."""
        client = DockerRegistryClient()

        with (
            patch(
                "mirustech.devenv_generator.adapters.docker_registry.Prompt.ask"
            ) as mock_prompt,
            patch("subprocess.run") as mock_run,
        ):
            mock_prompt.side_effect = ["testuser", "testpass"]
            mock_run.side_effect = OSError("Error")

            result = client._login_with_prompt("registry.example.com")
            assert result is False


class TestRegistryClientProtocol:
    """Tests for the RegistryClient protocol."""

    def test_docker_registry_client_implements_protocol(self) -> None:
        """DockerRegistryClient should implement RegistryClient protocol."""
        client = DockerRegistryClient()

        # Check that all protocol methods exist
        assert hasattr(client, "authenticate")
        assert hasattr(client, "pull_image")
        assert hasattr(client, "push_image")
        assert hasattr(client, "tag_image")

        # Check they are callable
        assert callable(client.authenticate)
        assert callable(client.pull_image)
        assert callable(client.push_image)
        assert callable(client.tag_image)
