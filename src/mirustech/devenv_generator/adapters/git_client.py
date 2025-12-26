"""Git client adapter using subprocess."""

import subprocess
from pathlib import Path
from typing import Protocol

import structlog

logger = structlog.get_logger()


class GitService(Protocol):
    """Protocol for git operations."""

    def get_commit_sha(self, path: Path) -> str | None:
        """Get the current commit SHA for a git repository.

        Args:
            path: Path to the git repository.

        Returns:
            The commit SHA as a string, or None if not a git repo.
        """
        ...

    def is_git_repository(self, path: Path) -> bool:
        """Check if a path is within a git repository.

        Args:
            path: Path to check.

        Returns:
            True if the path is in a git repository.
        """
        ...


class SubprocessGitClient:
    """Git client implementation using subprocess calls."""

    def __init__(self, timeout: int = 5) -> None:
        """Initialize the git client.

        Args:
            timeout: Timeout in seconds for git commands.
        """
        self.timeout = timeout
        self.logger = logger.bind(component="git_client")

    def is_git_repository(self, path: Path) -> bool:
        """Check if a path is within a git repository.

        Args:
            path: Path to check.

        Returns:
            True if the path is in a git repository.
        """
        # Check for .git directory or file (submodules use files)
        git_path = path / ".git"
        if git_path.exists():
            return True

        # Also check parent directories
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def get_commit_sha(self, path: Path) -> str | None:
        """Get the current commit SHA for a git repository.

        Args:
            path: Path to the git repository.

        Returns:
            The full commit SHA as a string, or None if not available.
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if result.returncode == 0:
                sha = result.stdout.strip()
                self.logger.debug("git_sha_detected", path=str(path), sha=sha[:12])
                return sha

            self.logger.debug(
                "git_sha_failed",
                path=str(path),
                error=result.stderr.strip(),
            )
            return None

        except subprocess.TimeoutExpired:
            self.logger.warning("git_command_timeout", path=str(path))
            return None
        except FileNotFoundError:
            self.logger.warning("git_not_installed")
            return None
        except OSError as e:
            self.logger.warning("git_command_error", path=str(path), error=str(e))
            return None

    def get_short_sha(self, path: Path, length: int = 12) -> str | None:
        """Get a shortened commit SHA.

        Args:
            path: Path to the git repository.
            length: Number of characters to include (default 12).

        Returns:
            The shortened commit SHA, or None if not available.
        """
        sha = self.get_commit_sha(path)
        if sha:
            return sha[:length]
        return None
