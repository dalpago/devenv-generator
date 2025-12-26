"""Docker registry adapter using subprocess calls."""

import subprocess
from typing import Protocol

import structlog
from rich.console import Console
from rich.prompt import Prompt

from mirustech.devenv_generator.models import ImageSpec
from mirustech.devenv_generator.settings import AuthMethod, RegistryConfig

logger = structlog.get_logger()
console = Console()


class RegistryClient(Protocol):
    """Protocol for container registry operations."""

    def authenticate(self, registry: str, config: RegistryConfig) -> bool:
        """Authenticate with the registry.

        Args:
            registry: Registry URL.
            config: Registry configuration.

        Returns:
            True if authentication succeeded.
        """
        ...

    def pull_image(self, image: ImageSpec) -> bool:
        """Pull an image from the registry.

        Args:
            image: Image specification to pull.

        Returns:
            True if pull succeeded.
        """
        ...

    def push_image(self, image: ImageSpec) -> bool:
        """Push an image to the registry.

        Args:
            image: Image specification to push.

        Returns:
            True if push succeeded.
        """
        ...

    def tag_image(self, source: str, target: ImageSpec) -> bool:
        """Tag an image with a new name.

        Args:
            source: Source image name.
            target: Target image specification.

        Returns:
            True if tagging succeeded.
        """
        ...


class DockerRegistryClient:
    """Docker registry client implementation using Docker CLI."""

    def __init__(self, timeout: int = 300) -> None:
        """Initialize the registry client.

        Args:
            timeout: Timeout in seconds for registry operations.
        """
        self.timeout = timeout
        self.logger = logger.bind(component="docker_registry")

    def authenticate(self, registry: str, config: RegistryConfig) -> bool:
        """Authenticate with the registry.

        Args:
            registry: Registry URL.
            config: Registry configuration.

        Returns:
            True if authentication succeeded.
        """
        match config.auth_method:
            case AuthMethod.EXISTING:
                return self._check_existing_auth(registry)
            case AuthMethod.STORED:
                return self._login_with_stored(registry, config)
            case AuthMethod.PROMPT:
                return self._login_with_prompt(registry)

    def _check_existing_auth(self, registry: str) -> bool:
        """Check if user is already logged in to the registry.

        Args:
            registry: Registry URL.

        Returns:
            True if already authenticated.
        """
        try:
            # Try to get login status - this is a quick way to check
            # if credentials exist for the registry
            result = subprocess.run(
                ["docker", "login", "--get-login", registry],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self.logger.debug("existing_auth_valid", registry=registry)
                return True

            self.logger.debug(
                "existing_auth_not_found",
                registry=registry,
                hint="Run 'docker login' to authenticate",
            )
            return False

        except subprocess.TimeoutExpired:
            self.logger.warning("auth_check_timeout", registry=registry)
            return False
        except FileNotFoundError:
            self.logger.error("docker_not_installed")
            return False
        except OSError as e:
            self.logger.warning("auth_check_error", registry=registry, error=str(e))
            return False

    def _login_with_stored(self, registry: str, config: RegistryConfig) -> bool:
        """Login using stored credentials.

        Args:
            registry: Registry URL.
            config: Registry configuration with credentials.

        Returns:
            True if login succeeded.
        """
        if not config.username or not config.password:
            self.logger.error(
                "stored_auth_missing_credentials",
                registry=registry,
            )
            return False

        try:
            # Use --password-stdin for security
            password = config.password.get_secret_value()
            result = subprocess.run(
                ["docker", "login", "-u", config.username, "--password-stdin", registry],
                input=password,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                self.logger.info("stored_auth_success", registry=registry)
                return True

            self.logger.error(
                "stored_auth_failed",
                registry=registry,
                error=result.stderr.strip(),
            )
            return False

        except subprocess.TimeoutExpired:
            self.logger.warning("login_timeout", registry=registry)
            return False
        except OSError as e:
            self.logger.warning("login_error", registry=registry, error=str(e))
            return False

    def _login_with_prompt(self, registry: str) -> bool:
        """Login with interactive prompts.

        Args:
            registry: Registry URL.

        Returns:
            True if login succeeded.
        """
        console.print(f"\n[bold]Registry authentication:[/bold] {registry}")
        username = Prompt.ask("Username")
        password = Prompt.ask("Password", password=True)

        try:
            result = subprocess.run(
                ["docker", "login", "-u", username, "--password-stdin", registry],
                input=password,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                self.logger.info("prompt_auth_success", registry=registry)
                console.print("[green]Authentication successful[/green]")
                return True

            self.logger.error(
                "prompt_auth_failed",
                registry=registry,
                error=result.stderr.strip(),
            )
            console.print(f"[red]Authentication failed:[/red] {result.stderr.strip()}")
            return False

        except subprocess.TimeoutExpired:
            self.logger.warning("login_timeout", registry=registry)
            console.print("[red]Authentication timed out[/red]")
            return False
        except OSError as e:
            self.logger.warning("login_error", registry=registry, error=str(e))
            console.print(f"[red]Authentication error:[/red] {e}")
            return False

    def pull_image(self, image: ImageSpec) -> bool:
        """Pull an image from the registry.

        Args:
            image: Image specification to pull.

        Returns:
            True if pull succeeded.
        """
        image_name = image.full_name
        self.logger.info("pulling_image", image=image_name)

        try:
            result = subprocess.run(
                ["docker", "pull", image_name],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if result.returncode == 0:
                self.logger.info("pull_success", image=image_name)
                return True

            # Check for common error patterns
            stderr = result.stderr.lower()
            if "not found" in stderr or "manifest unknown" in stderr:
                self.logger.info("image_not_found", image=image_name)
            else:
                self.logger.warning(
                    "pull_failed",
                    image=image_name,
                    error=result.stderr.strip(),
                )
            return False

        except subprocess.TimeoutExpired:
            self.logger.warning("pull_timeout", image=image_name)
            return False
        except OSError as e:
            self.logger.warning("pull_error", image=image_name, error=str(e))
            return False

    def push_image(self, image: ImageSpec) -> bool:
        """Push an image to the registry.

        Args:
            image: Image specification to push.

        Returns:
            True if push succeeded.
        """
        image_name = image.full_name
        self.logger.info("pushing_image", image=image_name)

        try:
            result = subprocess.run(
                ["docker", "push", image_name],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if result.returncode == 0:
                self.logger.info("push_success", image=image_name)
                return True

            self.logger.error(
                "push_failed",
                image=image_name,
                error=result.stderr.strip(),
            )
            return False

        except subprocess.TimeoutExpired:
            self.logger.warning("push_timeout", image=image_name)
            return False
        except OSError as e:
            self.logger.warning("push_error", image=image_name, error=str(e))
            return False

    def tag_image(self, source: str, target: ImageSpec) -> bool:
        """Tag an image with a new name.

        Args:
            source: Source image name.
            target: Target image specification.

        Returns:
            True if tagging succeeded.
        """
        target_name = target.full_name
        self.logger.debug("tagging_image", source=source, target=target_name)

        try:
            result = subprocess.run(
                ["docker", "tag", source, target_name],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                self.logger.debug("tag_success", source=source, target=target_name)
                return True

            self.logger.error(
                "tag_failed",
                source=source,
                target=target_name,
                error=result.stderr.strip(),
            )
            return False

        except subprocess.TimeoutExpired:
            self.logger.warning("tag_timeout", source=source, target=target_name)
            return False
        except OSError as e:
            self.logger.warning("tag_error", source=source, target=target_name, error=str(e))
            return False

    def image_exists_locally(self, image: ImageSpec) -> bool:
        """Check if an image exists locally.

        Args:
            image: Image specification to check.

        Returns:
            True if the image exists locally.
        """
        image_name = image.full_name

        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image_name],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0

        except (subprocess.TimeoutExpired, OSError):
            return False
