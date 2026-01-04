"""Tests for utils.process_manager module."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from mirustech.devenv_generator.utils.process_manager import ProcessManager


@pytest.fixture
def manager():
    """Create a ProcessManager instance for testing."""
    # Don't let atexit registration interfere with tests
    with patch("mirustech.devenv_generator.utils.process_manager.atexit.register"):
        return ProcessManager()


def test_process_manager_initialization():
    """Test that ProcessManager initializes with empty process dict."""
    with patch("mirustech.devenv_generator.utils.process_manager.atexit.register") as mock_atexit:
        manager = ProcessManager()

        assert manager._processes == {}
        # Verify cleanup_all registered with atexit
        mock_atexit.assert_called_once()


def test_start_process_success(manager):
    """Test starting a process successfully."""
    with patch("mirustech.devenv_generator.utils.process_manager.subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        result = manager.start("test_proc", ["echo", "hello"])

        assert result == mock_proc
        assert "test_proc" in manager._processes
        assert manager._processes["test_proc"] == mock_proc
        mock_popen.assert_called_once_with(["echo", "hello"])


def test_start_process_with_kwargs(manager):
    """Test starting a process with additional kwargs."""
    with patch("mirustech.devenv_generator.utils.process_manager.subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        manager.start(
            "test_proc",
            ["sleep", "10"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        mock_popen.assert_called_once_with(
            ["sleep", "10"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def test_start_process_failure(manager):
    """Test that start returns None when process fails to start."""
    with patch("mirustech.devenv_generator.utils.process_manager.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = Exception("Failed to start")

        result = manager.start("failing_proc", ["nonexistent"])

        assert result is None
        assert "failing_proc" not in manager._processes


def test_stop_process_graceful(manager):
    """Test stopping a process gracefully."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # Process is running
    manager._processes["test_proc"] = mock_proc

    manager.stop("test_proc")

    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once_with(timeout=5)
    assert "test_proc" not in manager._processes


def test_stop_process_force_kill_on_timeout(manager):
    """Test that process is killed if termination times out."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="test", timeout=5), None]
    manager._processes["test_proc"] = mock_proc

    manager.stop("test_proc")

    mock_proc.terminate.assert_called_once()
    # First wait times out, then kill, then wait again
    assert mock_proc.wait.call_count == 2
    mock_proc.kill.assert_called_once()
    assert "test_proc" not in manager._processes


def test_stop_nonexistent_process(manager):
    """Test that stopping a nonexistent process is a no-op."""
    # Should not raise an error
    manager.stop("nonexistent")


def test_cleanup_all(manager):
    """Test that cleanup_all stops all tracked processes."""
    mock_proc1 = MagicMock()
    mock_proc1.poll.return_value = None
    mock_proc2 = MagicMock()
    mock_proc2.poll.return_value = None

    manager._processes = {
        "proc1": mock_proc1,
        "proc2": mock_proc2,
    }

    manager.cleanup_all()

    # Both processes should be terminated
    mock_proc1.terminate.assert_called_once()
    mock_proc2.terminate.assert_called_once()
    assert manager._processes == {}


def test_cleanup_all_empty(manager):
    """Test that cleanup_all with no processes is a no-op."""
    # Should not raise an error
    manager.cleanup_all()
    assert manager._processes == {}
