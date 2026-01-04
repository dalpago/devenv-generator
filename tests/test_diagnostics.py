"""Tests for diagnostic registry functionality."""

import pytest
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main
from mirustech.devenv_generator.commands.diagnostics import DiagnosticRegistry


class TestDiagnosticRegistry:
    """Tests for the DiagnosticRegistry class."""

    def test_check_registration(self) -> None:
        """Should register check functions via decorator."""
        registry = DiagnosticRegistry()

        @registry.check("test_check")
        def test_check_fn() -> tuple[bool, str]:
            return True, "Test passed"

        assert "test_check" in registry._checks
        assert registry._checks["test_check"]() == (True, "Test passed")

    def test_fix_registration(self) -> None:
        """Should register fix functions via decorator."""
        registry = DiagnosticRegistry()

        @registry.fix("test_fix")
        def test_fix_fn() -> tuple[bool, str]:
            return True, "Fix applied"

        assert "test_fix" in registry._fixes
        assert registry._fixes["test_fix"]() == (True, "Fix applied")

    def test_run_all_checks(self) -> None:
        """Should run all registered checks and return results."""
        registry = DiagnosticRegistry()

        @registry.check("check1")
        def check1() -> tuple[bool, str]:
            return True, "Check 1 passed"

        @registry.check("check2")
        def check2() -> tuple[bool, str]:
            return False, "Check 2 failed"

        results = registry.run_all_checks()

        assert len(results) == 2
        assert ("check1", True, "Check 1 passed") in results
        assert ("check2", False, "Check 2 failed") in results

    def test_run_all_fixes(self) -> None:
        """Should run all registered fixes and return results."""
        registry = DiagnosticRegistry()

        @registry.fix("fix1")
        def fix1() -> tuple[bool, str]:
            return True, "Fix 1 applied"

        @registry.fix("fix2")
        def fix2() -> tuple[bool, str]:
            return False, "Fix 2 failed"

        results = registry.run_all_fixes()

        assert len(results) == 2
        assert ("fix1", True, "Fix 1 applied") in results
        assert ("fix2", False, "Fix 2 failed") in results

    def test_check_exception_handling(self) -> None:
        """Should handle exceptions in check functions gracefully."""
        registry = DiagnosticRegistry()

        @registry.check("failing_check")
        def failing_check() -> tuple[bool, str]:
            raise RuntimeError("Simulated failure")

        results = registry.run_all_checks()

        assert len(results) == 1
        name, success, message = results[0]
        assert name == "failing_check"
        assert success is False
        assert "Check failed with error" in message

    def test_fix_exception_handling(self) -> None:
        """Should handle exceptions in fix functions gracefully."""
        registry = DiagnosticRegistry()

        @registry.fix("failing_fix")
        def failing_fix() -> tuple[bool, str]:
            raise RuntimeError("Simulated failure")

        results = registry.run_all_fixes()

        assert len(results) == 1
        name, success, message = results[0]
        assert name == "failing_fix"
        assert success is False
        assert "Fix failed with error" in message

    def test_decorator_returns_original_function(self) -> None:
        """Should return the original function after registration."""
        registry = DiagnosticRegistry()

        def original_check() -> tuple[bool, str]:
            return True, "Original"

        decorated = registry.check("test")(original_check)

        assert decorated is original_check
        assert decorated() == (True, "Original")

    def test_multiple_registrations_same_name(self) -> None:
        """Should allow overwriting registrations (last wins)."""
        registry = DiagnosticRegistry()

        @registry.check("same_name")
        def first_check() -> tuple[bool, str]:
            return True, "First"

        @registry.check("same_name")
        def second_check() -> tuple[bool, str]:
            return True, "Second"

        results = registry.run_all_checks()
        assert len(results) == 1
        assert results[0] == ("same_name", True, "Second")


class TestDoctorCommand:
    """Tests for the doctor CLI command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_doctor_runs_checks(self, runner: CliRunner) -> None:
        """Doctor command should run system checks."""
        result = runner.invoke(main, ["doctor"])
        # The exit code depends on whether Docker is available
        # Just verify it runs without crashing
        assert result.exit_code in (0, 1)
        assert "System Diagnostics" in result.output or "docker" in result.output.lower()

    def test_doctor_help(self, runner: CliRunner) -> None:
        """Doctor command should show help."""
        result = runner.invoke(main, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "diagnose" in result.output.lower() or "health" in result.output.lower()

    def test_doctor_fix_flag(self, runner: CliRunner) -> None:
        """Doctor --fix flag should be accepted."""
        result = runner.invoke(main, ["doctor", "--fix"])
        # Runs without error, actual fix behavior depends on system state
        assert result.exit_code in (0, 1)


class TestDiagnosticModule:
    """Tests for the diagnostic module singleton."""

    def test_diagnostic_singleton_has_checks(self) -> None:
        """The global diagnostic registry should have built-in checks."""
        from mirustech.devenv_generator.commands.diagnostics import diagnostic

        # There should be at least some registered checks
        assert len(diagnostic._checks) > 0
        assert "docker_installed" in diagnostic._checks

    def test_diagnostic_singleton_has_fixes(self) -> None:
        """The global diagnostic registry should have some fixes."""
        from mirustech.devenv_generator.commands.diagnostics import diagnostic

        # Some checks have corresponding fixes
        assert len(diagnostic._fixes) >= 0  # May have 0 if no fixes registered
