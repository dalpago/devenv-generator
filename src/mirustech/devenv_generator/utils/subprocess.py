"""Subprocess execution wrapper for consistent error handling and logging.

Provides a single point for subprocess execution with standard defaults
(capture_output, text mode, timeout). Ensures all subprocess calls are
observable via structlog without requiring each call site to add logging.
"""

import subprocess
import time
from typing import Any, Callable

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


def wait_with_exponential_backoff(
    check_fn: Callable[[], bool],
    max_wait: int = 60,
    initial_delay: int = 1,
    max_delay: int = 16,
) -> bool:
    """Poll check_fn with exponential backoff until success or timeout.

    Exponential backoff (1s, 2s, 4s, 8s, 16s, 16s...) detects fast startup
    quickly (completes in ~7s when Docker starts in 5s) while maintaining
    full timeout coverage (reaches 60s total wait for slow startup). Pattern
    minimizes wait time for fast startup while tolerating slow startup without
    timeout failures.

    Args:
        check_fn: Function returning True on success, False to retry.
                 Exceptions treated as check failure (continues retrying).
        max_wait: Maximum total wait time in seconds.
        initial_delay: Starting delay (doubles each iteration).
        max_delay: Cap prevents excessive wait gaps between retries. 16s allows 4-5
                   retry attempts within 60s timeout window, balancing responsiveness
                   (frequent retries) with timeout coverage (reaches 60s total).

    Returns:
        True if check_fn succeeded within max_wait, False on timeout.
    """
    elapsed = 0
    delay = initial_delay
    while elapsed < max_wait:
        try:
            if check_fn():
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError, ConnectionError, OSError):
            # Docker availability checks fail with platform-specific errors:
            # - TimeoutExpired: docker info hangs on unresponsive daemon
            # - FileNotFoundError: Docker CLI binary not in PATH
            # - PermissionError: socket lacks user permissions (not in docker group)
            # - ConnectionError: daemon unreachable (stopped, crashed)
            # - OSError: I/O errors (disk full, broken socket)
            pass
        except Exception as e:
            # Broad handler catches unexpected exceptions (JSONDecodeError from malformed docker info output,
            # rare transient errors) to prevent crash. Warning log provides visibility for debugging.
            # Tradeoff: broader exception handling (slower debugging of programming errors) vs defensive
            # production behavior (no crash on Docker CLI output corruption)
            logger.warning("check_fn_unexpected_exception", error=str(e), error_type=type(e).__name__)
            pass

        # Final iteration exits without sleeping (prevents exceeding max_wait timeout)
        if elapsed + delay >= max_wait:
            break

        time.sleep(delay)
        elapsed += delay
        delay = min(delay * 2, max_delay)
    return False
