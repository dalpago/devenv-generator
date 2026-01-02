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
    stream_output: bool = False,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run subprocess command with consistent parameters and logging.

    Provides single point for subprocess execution with standard defaults:
    - capture_output=True (capture stdout/stderr for error reporting, unless stream_output=True)
    - text=True (return strings, not bytes - CLI assumes text mode)
    - timeout=10 (prevent infinite hangs on external tool failures)

    Args:
        cmd: Command and arguments as list.
        timeout: Timeout in seconds (default: 10 for CLI responsiveness).
        text: Return stdout/stderr as strings (default: True).
        stream_output: If True, stream output to terminal instead of capturing (default: False).
        **kwargs: Additional arguments passed to subprocess.run.

    Returns:
        CompletedProcess with stdout, stderr, returncode.
    """
    logger.debug("running_command", cmd=cmd, timeout=timeout, stream_output=stream_output)

    # For streaming, don't capture output - let it flow to terminal
    if stream_output:
        return subprocess.run(cmd, text=text, timeout=timeout, **kwargs)

    # Default: capture output for programmatic use
    return subprocess.run(cmd, capture_output=True, text=text, timeout=timeout, **kwargs)
