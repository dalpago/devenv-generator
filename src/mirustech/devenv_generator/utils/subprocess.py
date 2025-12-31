"""Subprocess execution wrapper for consistent error handling and logging.

Provides a single point for subprocess execution with standard defaults
(capture_output, text mode, timeout). Ensures all subprocess calls are
observable via structlog without requiring each call site to add logging.
"""

import subprocess
from typing import Any

import structlog

logger = structlog.get_logger()


def run_command(
    cmd: list[str],
    timeout: int = 10,
    text: bool = True,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run subprocess command with consistent parameters and logging.

    Provides single point for subprocess execution with standard defaults:
    - capture_output=True (always capture stdout/stderr for error reporting)
    - text=True (return strings, not bytes - CLI assumes text mode)
    - timeout=10 (prevent infinite hangs on external tool failures)

    Args:
        cmd: Command and arguments as list.
        timeout: Timeout in seconds (default: 10 for CLI responsiveness).
        text: Return stdout/stderr as strings (default: True).
        **kwargs: Additional arguments passed to subprocess.run.

    Returns:
        CompletedProcess with stdout, stderr, returncode.
    """
    logger.debug("running_command", cmd=cmd, timeout=timeout)
    return subprocess.run(cmd, capture_output=True, text=text, timeout=timeout, **kwargs)
