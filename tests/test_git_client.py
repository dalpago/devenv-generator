"""Tests for git client adapter."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from mirustech.devenv_generator.adapters.git_client import SubprocessGitClient


class TestSubprocessGitClient:
    """Tests for SubprocessGitClient."""

    def test_init_default_timeout(self) -> None:
        """Test default timeout is 5 seconds."""
        client = SubprocessGitClient()
        assert client.timeout == 5

    def test_init_custom_timeout(self) -> None:
        """Test custom timeout can be set."""
        client = SubprocessGitClient(timeout=10)
        assert client.timeout == 10

    def test_is_git_repository_with_git_dir(self, tmp_path: Path) -> None:
        """Test is_git_repository returns True when .git exists."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        client = SubprocessGitClient()
        assert client.is_git_repository(tmp_path) is True

    def test_is_git_repository_with_git_file(self, tmp_path: Path) -> None:
        """Test is_git_repository returns True for git submodule (.git file)."""
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: ../.git/modules/submodule")

        client = SubprocessGitClient()
        assert client.is_git_repository(tmp_path) is True

    def test_is_git_repository_not_git(self, tmp_path: Path) -> None:
        """Test is_git_repository returns False for non-git directory."""
        client = SubprocessGitClient()
        # Mock subprocess to return failure
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128)
            assert client.is_git_repository(tmp_path) is False

    def test_is_git_repository_timeout(self, tmp_path: Path) -> None:
        """Test is_git_repository handles timeout."""
        client = SubprocessGitClient()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=5)
            assert client.is_git_repository(tmp_path) is False

    def test_is_git_repository_git_not_found(self, tmp_path: Path) -> None:
        """Test is_git_repository handles missing git command."""
        client = SubprocessGitClient()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            assert client.is_git_repository(tmp_path) is False

    def test_get_commit_sha_success(self, tmp_path: Path) -> None:
        """Test get_commit_sha returns SHA on success."""
        client = SubprocessGitClient()
        expected_sha = "abc123def456789012345678901234567890abcd"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=f"{expected_sha}\n",
            )
            sha = client.get_commit_sha(tmp_path)
            assert sha == expected_sha

    def test_get_commit_sha_failure(self, tmp_path: Path) -> None:
        """Test get_commit_sha returns None on failure."""
        client = SubprocessGitClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128,
                stderr="fatal: not a git repository",
            )
            sha = client.get_commit_sha(tmp_path)
            assert sha is None

    def test_get_commit_sha_timeout(self, tmp_path: Path) -> None:
        """Test get_commit_sha handles timeout."""
        client = SubprocessGitClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=5)
            sha = client.get_commit_sha(tmp_path)
            assert sha is None

    def test_get_commit_sha_git_not_found(self, tmp_path: Path) -> None:
        """Test get_commit_sha handles missing git command."""
        client = SubprocessGitClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            sha = client.get_commit_sha(tmp_path)
            assert sha is None

    def test_get_commit_sha_os_error(self, tmp_path: Path) -> None:
        """Test get_commit_sha handles OS errors."""
        client = SubprocessGitClient()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Permission denied")
            sha = client.get_commit_sha(tmp_path)
            assert sha is None

    def test_get_short_sha_success(self, tmp_path: Path) -> None:
        """Test get_short_sha returns shortened SHA."""
        client = SubprocessGitClient()
        full_sha = "abc123def456789012345678901234567890abcd"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=f"{full_sha}\n",
            )
            short_sha = client.get_short_sha(tmp_path)
            assert short_sha == "abc123def456"
            assert len(short_sha) == 12

    def test_get_short_sha_custom_length(self, tmp_path: Path) -> None:
        """Test get_short_sha with custom length."""
        client = SubprocessGitClient()
        full_sha = "abc123def456789012345678901234567890abcd"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=f"{full_sha}\n",
            )
            short_sha = client.get_short_sha(tmp_path, length=7)
            assert short_sha == "abc123d"
            assert len(short_sha) == 7

    def test_get_short_sha_returns_none_on_failure(self, tmp_path: Path) -> None:
        """Test get_short_sha returns None when get_commit_sha fails."""
        client = SubprocessGitClient()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stderr="error")
            short_sha = client.get_short_sha(tmp_path)
            assert short_sha is None
