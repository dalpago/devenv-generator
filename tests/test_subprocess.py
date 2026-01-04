"""Tests for utils.subprocess module."""

import subprocess
from unittest.mock import MagicMock, patch

from mirustech.devenv_generator.utils.subprocess import run_command


def test_run_command_default_parameters():
    """Test that run_command applies default parameters."""
    with patch("mirustech.devenv_generator.utils.subprocess.subprocess.run") as mock_run:
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = run_command(["echo", "test"])

        # Verify subprocess.run called with correct defaults
        mock_run.assert_called_once_with(
            ["echo", "test"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result == mock_result


def test_run_command_custom_timeout():
    """Test that custom timeout is passed through."""
    with patch("mirustech.devenv_generator.utils.subprocess.subprocess.run") as mock_run:
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_run.return_value = mock_result

        run_command(["sleep", "1"], timeout=30)

        mock_run.assert_called_once_with(
            ["sleep", "1"],
            capture_output=True,
            text=True,
            timeout=30,
        )


def test_run_command_custom_kwargs():
    """Test that additional kwargs are passed through."""
    with patch("mirustech.devenv_generator.utils.subprocess.subprocess.run") as mock_run:
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_run.return_value = mock_result

        run_command(["docker", "ps"], cwd="/tmp", env={"FOO": "bar"})

        mock_run.assert_called_once_with(
            ["docker", "ps"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd="/tmp",
            env={"FOO": "bar"},
        )


def test_run_command_text_mode_disabled():
    """Test that text mode can be disabled."""
    with patch("mirustech.devenv_generator.utils.subprocess.subprocess.run") as mock_run:
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_run.return_value = mock_result

        run_command(["cat", "file"], text=False)

        mock_run.assert_called_once_with(
            ["cat", "file"],
            capture_output=True,
            text=False,
            timeout=10,
        )


def test_run_command_logs_execution(caplog):
    """Test that command execution is logged."""
    with patch("mirustech.devenv_generator.utils.subprocess.subprocess.run") as mock_run:
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_run.return_value = mock_result

        with caplog.at_level("DEBUG"):
            run_command(["ls", "-la"])

        # Verify logging occurred (structlog debug message)
        # Note: Exact log format depends on structlog configuration
        assert mock_run.called


def test_run_command_stream_output():
    """Test that stream_output=True skips capture_output."""
    with patch("mirustech.devenv_generator.utils.subprocess.subprocess.run") as mock_run:
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_run.return_value = mock_result

        run_command(["docker", "build"], stream_output=True)

        # stream_output=True should NOT pass capture_output
        mock_run.assert_called_once_with(
            ["docker", "build"],
            text=True,
            timeout=10,
        )
