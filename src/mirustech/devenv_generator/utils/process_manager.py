"""Background process lifecycle management.

Manages long-running background processes (GPG agent forwarding, Serena MCP server)
with automatic cleanup on exit. ProcessManager encapsulates process state in a dict,
enabling test isolation (can mock ProcessManager instance) and matching the existing
adapter pattern (DockerRegistryClient, SubprocessGitClient).

Uses atexit for cleanup to handle both normal exit and signals (SIGTERM, SIGINT).
Python's atexit runs cleanup handlers before interpreter shutdown, ensuring
background processes don't leak when user stops sandbox with Ctrl-C.
"""

import atexit
import subprocess
from typing import Any

import structlog

logger = structlog.get_logger()


class ProcessManager:
    """Manages background processes with automatic cleanup on exit.

    Tracks long-running background processes (GPG agent forwarding, Serena MCP server)
    and ensures they are terminated when the CLI exits. Uses atexit for cleanup to
    handle both normal exit and interrupt signals.
    """

    def __init__(self) -> None:
        """Initialize process manager with cleanup registration.

        Registers cleanup_all() with atexit immediately to ensure cleanup runs
        even if processes are started later. This prevents process leaks if
        user interrupts CLI after process start but before normal exit.
        """
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        atexit.register(self.cleanup_all)
        logger.debug("process_manager_initialized")

    def start(self, name: str, cmd: list[str], **kwargs: Any) -> subprocess.Popen[bytes] | None:
        """Start a background process and track it for cleanup.

        Args:
            name: Identifier for this process (used in logs, stop() calls).
            cmd: Command and arguments as list.
            **kwargs: Additional arguments passed to subprocess.Popen.

        Returns:
            Popen instance or None if start failed.
        """
        try:
            proc = subprocess.Popen(cmd, **kwargs)
            self._processes[name] = proc
            logger.info("process_started", name=name, pid=proc.pid)
            return proc
        except Exception as e:
            logger.error("process_start_failed", name=name, error=str(e))
            return None

    def stop(self, name: str) -> None:
        """Stop and remove a tracked process.

        Sends SIGTERM to allow graceful shutdown, then waits up to 5 seconds.
        If process doesn't exit in time, sends SIGKILL to prevent orphaned processes.

        Args:
            name: Identifier of process to stop.
        """
        if name in self._processes:
            proc = self._processes[name]
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("process_termination_timeout", name=name)
                proc.kill()
                proc.wait()
            del self._processes[name]
            logger.info("process_stopped", name=name)

    def cleanup_all(self) -> None:
        """Terminate all tracked processes.

        Called automatically by atexit when Python interpreter shuts down.
        Handles both normal exit and signal interrupts (Ctrl-C).
        """
        for name in list(self._processes.keys()):
            self.stop(name)
        logger.debug("process_manager_cleanup_complete")
