"""Template rendering and file generation."""

import hashlib
import json
from importlib.resources import files
from pathlib import Path

import structlog
import yaml
from jinja2 import Environment, PackageLoader

from mirustech.devenv_generator.models import ImageSpec, MountSpec, ProfileConfig

logger = structlog.get_logger()


def load_profile(profile_path: Path) -> ProfileConfig:
    """Load a profile from a YAML file.

    Args:
        profile_path: Path to the YAML profile file.

    Returns:
        Validated ProfileConfig instance.

    Raises:
        FileNotFoundError: If profile file doesn't exist.
        ValueError: If profile is invalid.
    """
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    with profile_path.open() as f:
        data = yaml.safe_load(f)

    return ProfileConfig.model_validate(data)


def get_bundled_profile(profile_name: str) -> ProfileConfig:
    """Load a bundled profile from the package.

    Args:
        profile_name: Name of the bundled profile (e.g., 'default').

    Returns:
        Validated ProfileConfig instance.

    Raises:
        FileNotFoundError: If bundled profile doesn't exist.
    """
    # Backward compatibility: map "mirustech" to "default"
    if profile_name == "mirustech":
        profile_name = "default"
        logger.warning(
            "profile_deprecated",
            old_name="mirustech",
            new_name="default",
            message="Profile 'mirustech' is deprecated, use 'default' instead",
        )

    # Try multiple locations for the profile
    # __file__ is src/mirustech/devenv_generator/generator.py
    # Repo root is 4 levels up: generator.py -> devenv_generator -> mirustech -> src -> repo_root
    repo_root = Path(__file__).parent.parent.parent.parent
    search_paths = [
        # Package resources (if bundled)
        None,  # Placeholder for importlib.resources approach
        # Repo root profiles directory (development)
        repo_root / "profiles" / f"{profile_name}.yaml",
        # User config directory
        Path("~/.config/devenv-generator/profiles").expanduser() / f"{profile_name}.yaml",
    ]

    # Try importlib.resources first
    try:
        profiles_dir = files("mirustech.devenv_generator").joinpath("profiles")
        profile_file = profiles_dir.joinpath(f"{profile_name}.yaml")
        content = profile_file.read_text()
        data = yaml.safe_load(content)
        return ProfileConfig.model_validate(data)
    except (FileNotFoundError, TypeError, AttributeError):
        pass

    # Try file paths
    for path in search_paths[1:]:  # Skip None placeholder
        if path and path.exists():
            return load_profile(path)

    raise FileNotFoundError(f"Profile not found: {profile_name}")


def get_docker_socket_gid() -> int:
    """Get the GID of the docker socket on the host.

    Returns:
        GID of /var/run/docker.sock, or 999 as fallback.
    """

    docker_socket = Path("/var/run/docker.sock")
    if docker_socket.exists():
        try:
            st = docker_socket.stat()
            gid = st.st_gid
            logger.debug("detected_docker_gid", gid=gid)
            return gid
        except (OSError, AttributeError):
            pass

    # Fallback to common default
    logger.debug("docker_gid_fallback", gid=999)
    return 999


def get_host_user_ids() -> tuple[int, int]:
    """Get the UID and GID of the host user running the command.

    Returns:
        Tuple of (uid, gid). Matches the host user to ensure proper file permissions.
    """
    import os

    uid = os.getuid()
    gid = os.getgid()

    logger.debug("detected_host_user", uid=uid, gid=gid)
    return uid, gid


def compute_build_hash(profile: ProfileConfig) -> str:
    """Compute a hash representing the build configuration.

    This hash includes:
    - Profile configuration (name, packages, system packages, etc.)
    - Dockerfile template content
    - docker-compose template content

    If any of these change, the hash will be different and a rebuild is needed.

    Args:
        profile: Profile configuration to hash.

    Returns:
        MD5 hash hex string.
    """
    hasher = hashlib.md5()

    # Hash the profile data (serialize to JSON for deterministic ordering)
    profile_dict = profile.model_dump(mode="json")
    profile_json = json.dumps(profile_dict, sort_keys=True)
    hasher.update(profile_json.encode("utf-8"))

    # Hash the Dockerfile template content
    templates_dir = files("mirustech.devenv_generator").joinpath("templates")
    dockerfile_template = templates_dir.joinpath("Dockerfile.j2").read_text()
    hasher.update(dockerfile_template.encode("utf-8"))

    # Hash the docker-compose template content
    compose_template = templates_dir.joinpath("docker-compose.sandbox.yml.j2").read_text()
    hasher.update(compose_template.encode("utf-8"))

    return hasher.hexdigest()


class DevEnvGenerator:
    """Generate development environment files from profiles."""

    def __init__(
        self,
        profile: ProfileConfig,
        project_name: str | None = None,
        image_spec: ImageSpec | None = None,
    ) -> None:
        """Initialize the generator.

        Args:
            profile: Profile configuration.
            project_name: Name for the project (used in volume names, etc.).
                         Defaults to 'project'.
            image_spec: Optional image specification for registry support.
        """
        self.profile = profile
        self.project_name = project_name or "project"
        self.image_spec = image_spec
        self.env = Environment(
            loader=PackageLoader("mirustech.devenv_generator", "templates"),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.logger = logger.bind(profile=profile.name, project=self.project_name)

    def render_dockerfile(self) -> str:
        """Render the Dockerfile template.

        Returns:
            Rendered Dockerfile content.
        """
        template = self.env.get_template("Dockerfile.j2")
        return template.render(profile=self.profile, project_name=self.project_name)

    def render_docker_compose(self) -> str:
        """Render the docker-compose.yml template.

        Returns:
            Rendered docker-compose.yml content.
        """
        # Warn if ports configured with network mode 'none'
        if self.profile.ports.ports and self.profile.network.mode == "none":
            logger.warning(
                "ports_with_network_none",
                message="Port mappings configured but network mode is 'none' - "
                "ports will not be accessible",
            )

        template = self.env.get_template("docker-compose.yml.j2")
        docker_gid = get_docker_socket_gid()
        user_uid, user_gid = get_host_user_ids()
        return template.render(
            profile=self.profile,
            project_name=self.project_name,
            image_spec=self.image_spec,
            docker_gid=docker_gid,
            user_uid=user_uid,
            user_gid=user_gid,
        )

    def render_devcontainer_json(self) -> str:
        """Render the devcontainer.json template.

        Returns:
            Rendered devcontainer.json content.
        """
        template = self.env.get_template("devcontainer.json.j2")
        return template.render(profile=self.profile, project_name=self.project_name)

    def render_init_script(self) -> str:
        """Render the init-env.sh template.

        Returns:
            Rendered init-env.sh content.
        """
        template = self.env.get_template("init-env.sh.j2")
        return template.render(profile=self.profile, project_name=self.project_name)

    def render_env_example(self) -> str:
        """Render the .env.example file.

        Returns:
            Rendered .env.example content.
        """
        lines = [
            "# Environment variables for devenv container",
            "# ",
            "# Setup:",
            "#   1. Copy this file: cp .env.example .env",
            "#   2. Fill in your token below",
            "#   3. Encrypt with SOPS: sops encrypt --in-place .env",
            "#   4. Commit the encrypted .env file",
            "#",
            "# To edit later: sops .env",
            "",
            "# Claude Code auth token (required for authentication)",
            "# Get token: Run 'claude setup-token' on your host machine",
            "ANTHROPIC_AUTH_TOKEN=",
            "",
        ]
        # Add any profile-specific environment variables
        for key in self.profile.environment:
            if key != "ANTHROPIC_API_KEY":  # Skip deprecated API key approach
                lines.append(f"{key}=")
        return "\n".join(lines)

    def render_sops_yaml(self, age_public_key: str | None = None) -> str:
        """Render the .sops.yaml configuration file.

        Args:
            age_public_key: The age public key for encryption. If None, uses placeholder.

        Returns:
            Rendered .sops.yaml content.
        """
        key = age_public_key or "age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        return f"""# SOPS configuration for encrypting secrets
# Documentation: https://github.com/getsops/sops
#
# Setup:
#   1. Generate age key: age-keygen -o ~/.config/sops/age/keys.txt
#   2. Replace the public key below with your key (starts with age1...)
#   3. Encrypt .env: sops encrypt --in-place .env

creation_rules:
  - path_regex: \\.env$
    age: {key}
"""

    def render_gitignore(self) -> str:
        """Render the .gitignore additions.

        Returns:
            .gitignore content for devenv files.
        """
        # .env is safe to commit when SOPS-encrypted
        # .env.example is the template (not encrypted)
        return (
            "# devenv - unencrypted secrets (should not exist if following workflow)\n"
            ".env.unencrypted\n"
        )

    def _detect_age_public_key(self) -> str | None:
        """Try to detect the user's age public key.

        Looks in standard locations for age keys.

        Returns:
            The age public key if found, None otherwise.
        """
        key_paths = [
            Path("~/.config/sops/age/keys.txt").expanduser(),
            Path("~/.config/chezmoi/key.txt").expanduser(),  # chezmoi uses age
            Path("~/.age/key.txt").expanduser(),
        ]

        for key_path in key_paths:
            if key_path.exists():
                try:
                    content = key_path.read_text()
                    for line in content.splitlines():
                        line = line.strip()
                        # Public key line starts with "# public key:"
                        if line.startswith("# public key:"):
                            return line.split(":", 1)[1].strip()
                        # Or it might be just the public key on a line
                        if line.startswith("age1") and not line.startswith("AGE-SECRET-KEY"):
                            return line
                except OSError:
                    continue

        return None

    def generate(self, output_dir: Path) -> list[Path]:
        """Generate all development environment files.

        Args:
            output_dir: Directory to write files to.

        Returns:
            List of paths to generated files.
        """
        output_dir = Path(output_dir)
        devcontainer_dir = output_dir / ".devcontainer"
        devcontainer_dir.mkdir(parents=True, exist_ok=True)

        generated_files: list[Path] = []

        # Dockerfile
        dockerfile_path = devcontainer_dir / "Dockerfile"
        dockerfile_path.write_text(self.render_dockerfile())
        generated_files.append(dockerfile_path)
        self.logger.info("generated_file", path=str(dockerfile_path))

        # docker-compose.yml (in project root)
        compose_path = output_dir / "docker-compose.yml"
        compose_path.write_text(self.render_docker_compose())
        generated_files.append(compose_path)
        self.logger.info("generated_file", path=str(compose_path))

        # devcontainer.json
        devcontainer_json_path = devcontainer_dir / "devcontainer.json"
        devcontainer_json_path.write_text(self.render_devcontainer_json())
        generated_files.append(devcontainer_json_path)
        self.logger.info("generated_file", path=str(devcontainer_json_path))

        # init-env.sh
        init_script_path = devcontainer_dir / "init-env.sh"
        init_script_path.write_text(self.render_init_script())
        init_script_path.chmod(0o755)  # Make executable
        generated_files.append(init_script_path)
        self.logger.info("generated_file", path=str(init_script_path))

        # .env.example
        env_example_path = output_dir / ".env.example"
        env_example_path.write_text(self.render_env_example())
        env_example_path.chmod(0o644)
        generated_files.append(env_example_path)
        self.logger.info("generated_file", path=str(env_example_path))

        # .sops.yaml - try to detect user's age public key
        age_public_key = self._detect_age_public_key()
        sops_yaml_path = output_dir / ".sops.yaml"
        sops_yaml_path.write_text(self.render_sops_yaml(age_public_key))
        generated_files.append(sops_yaml_path)
        self.logger.info("generated_file", path=str(sops_yaml_path))
        if not age_public_key:
            self.logger.warning(
                "age_key_not_found",
                message="No age key found. Update .sops.yaml with your public key.",
            )

        # .gitignore (append if exists, create if not)
        gitignore_path = output_dir / ".gitignore"
        gitignore_content = self.render_gitignore()
        if gitignore_path.exists():
            existing = gitignore_path.read_text()
            if ".env" not in existing:
                gitignore_path.write_text(existing.rstrip() + "\n\n" + gitignore_content)
                self.logger.info("updated_file", path=str(gitignore_path))
        else:
            gitignore_path.write_text(gitignore_content)
            gitignore_path.chmod(0o600)
            generated_files.append(gitignore_path)
            self.logger.info("generated_file", path=str(gitignore_path))

        return generated_files


class SandboxGenerator:
    """Generate sandbox environment for running Claude Code against existing projects."""

    def __init__(
        self,
        profile: ProfileConfig,
        mounts: list[MountSpec],
        sandbox_name: str,
        use_host_claude_config: bool = True,
        image_spec: ImageSpec | None = None,
    ) -> None:
        """Initialize the sandbox generator.

        Args:
            profile: Profile configuration.
            mounts: List of project directories to mount.
            sandbox_name: Name for the sandbox.
            use_host_claude_config: Whether to mount host ~/.claude.
            image_spec: Optional image specification for registry support.
        """
        self.profile = profile
        self.mounts = mounts
        self.sandbox_name = sandbox_name
        self.use_host_claude_config = use_host_claude_config
        self.image_spec = image_spec
        self.env = Environment(
            loader=PackageLoader("mirustech.devenv_generator", "templates"),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.logger = logger.bind(
            sandbox=sandbox_name,
            profile=profile.name,
            mount_count=len(mounts),
        )

    def render_docker_compose(self) -> str:
        """Render the sandbox docker-compose.yml template.

        Returns:
            Rendered docker-compose.yml content.
        """
        # Warn if ports configured with network mode 'none'
        if self.profile.ports.ports and self.profile.network.mode == "none":
            logger.warning(
                "ports_with_network_none",
                message="Port mappings configured but network mode is 'none' - "
                "ports will not be accessible",
            )

        template = self.env.get_template("docker-compose.sandbox.yml.j2")
        has_cow_mounts = any(m.mode == "cow" for m in self.mounts)
        default_workdir = self.mounts[0].host_path.name if self.mounts else ""
        docker_gid = get_docker_socket_gid()
        user_uid, user_gid = get_host_user_ids()

        return template.render(
            profile=self.profile,
            sandbox_name=self.sandbox_name,
            mounts=self.mounts,
            has_cow_mounts=has_cow_mounts,
            default_workdir=default_workdir,
            use_host_claude_config=self.use_host_claude_config,
            image_spec=self.image_spec,
            docker_gid=docker_gid,
            user_uid=user_uid,
            user_gid=user_gid,
        )

    def render_dockerfile(self) -> str:
        """Render the Dockerfile template (reuses standard template).

        Returns:
            Rendered Dockerfile content.
        """
        template = self.env.get_template("Dockerfile.j2")
        return template.render(profile=self.profile, project_name=self.sandbox_name)

    def render_env_example(self) -> str:
        """Render the .env.example file.

        Returns:
            Rendered .env.example content.
        """
        lines = [
            "# Environment variables for sandbox",
            "#",
            "# Setup:",
            "#   1. Fill in your token below",
            "#   2. Encrypt with SOPS: sops encrypt --in-place .env",
            "#",
            "# To edit later: sops .env",
            "",
            "# Claude Code auth token (required for authentication)",
            "# Get token: Run 'claude setup-token' on your host machine",
            "ANTHROPIC_AUTH_TOKEN=",
            "",
        ]
        return "\n".join(lines)

    def _detect_age_public_key(self) -> str | None:
        """Try to detect the user's age public key."""
        key_paths = [
            Path("~/.config/sops/age/keys.txt").expanduser(),
            Path("~/.config/chezmoi/key.txt").expanduser(),
            Path("~/.age/key.txt").expanduser(),
        ]

        for key_path in key_paths:
            if key_path.exists():
                try:
                    content = key_path.read_text()
                    for line in content.splitlines():
                        line = line.strip()
                        if line.startswith("# public key:"):
                            return line.split(":", 1)[1].strip()
                        if line.startswith("age1") and not line.startswith("AGE-SECRET-KEY"):
                            return line
                except OSError:
                    continue

        return None

    def render_sops_yaml(self) -> str:
        """Render the .sops.yaml configuration file.

        Returns:
            Rendered .sops.yaml content.
        """
        key = (
            self._detect_age_public_key()
            or "age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        )
        return f"""# SOPS configuration for encrypting secrets
creation_rules:
  - path_regex: \\.env$
    age: {key}
"""

    def generate(self, output_dir: Path) -> list[Path]:
        """Generate all sandbox files.

        Args:
            output_dir: Directory to write files to.

        Returns:
            List of paths to generated files.
        """
        output_dir = Path(output_dir)
        devcontainer_dir = output_dir / ".devcontainer"
        devcontainer_dir.mkdir(parents=True, exist_ok=True)

        generated_files: list[Path] = []

        # Dockerfile
        dockerfile_path = devcontainer_dir / "Dockerfile"
        dockerfile_path.write_text(self.render_dockerfile())
        generated_files.append(dockerfile_path)
        self.logger.info("generated_file", path=str(dockerfile_path))

        # docker-compose.yml (in sandbox root)
        compose_path = output_dir / "docker-compose.yml"
        compose_path.write_text(self.render_docker_compose())
        generated_files.append(compose_path)
        self.logger.info("generated_file", path=str(compose_path))

        # .env.example
        env_example_path = output_dir / ".env.example"
        env_example_path.write_text(self.render_env_example())
        generated_files.append(env_example_path)
        self.logger.info("generated_file", path=str(env_example_path))

        # .sops.yaml
        sops_yaml_path = output_dir / ".sops.yaml"
        sops_yaml_path.write_text(self.render_sops_yaml())
        generated_files.append(sops_yaml_path)
        self.logger.info("generated_file", path=str(sops_yaml_path))

        # Build hash (for detecting when rebuild is needed)
        build_hash = compute_build_hash(self.profile)
        build_hash_path = devcontainer_dir / ".build-hash"
        build_hash_path.write_text(build_hash)
        generated_files.append(build_hash_path)
        self.logger.info("generated_build_hash", hash=build_hash, path=str(build_hash_path))

        return generated_files
