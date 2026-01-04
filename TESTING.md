# Testing Guide

## Overview

The test suite includes both unit tests and integration tests:

- **Unit tests**: Fast tests with mocked dependencies (default)
- **Integration tests**: Slower tests with actual Docker containers

## Running Tests

### Run All Unit Tests (Default)

```bash
pytest
# or
uv run pytest
```

By default, integration tests are skipped. This is configured in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-v --tb=short -m 'not integration'"
```

### Run Integration Tests

Integration tests require:
- Docker daemon running
- Sufficient disk space for building test containers
- For some tests: ANTHROPIC_AUTH_TOKEN or Claude Code configured

```bash
# Run all integration tests
pytest -m integration

# Run specific integration test file
pytest -m integration tests/test_integration_lifecycle.py

# Run specific integration test class
pytest -m integration tests/test_integration_lifecycle.py::TestContainerLifecycle

# Run specific integration test
pytest -m integration tests/test_integration_lifecycle.py::TestContainerLifecycle::test_container_starts_in_detached_mode
```

### Run All Tests (Unit + Integration)

```bash
pytest -m ""
```

## Test Organization

### Unit Tests

Located in `tests/test_*.py` files without the `@pytest.mark.integration` decorator:

- `test_lifecycle.py`: Lifecycle command utilities and CLI (unit tests)
- `test_config.py`: Configuration management
- `test_diagnostics.py`: Diagnostic checks
- `test_generator.py`: Sandbox generation
- `test_models.py`: Data models
- `test_ports.py`: Port configuration
- `test_profiles.py`: Profile management

### Integration Tests

Located in `tests/test_integration_*.py` and marked with `@pytest.mark.integration`:

#### `test_integration_lifecycle.py`

Comprehensive lifecycle testing with actual Docker:

- **TestDockerBuild**: Building sandbox images
  - `test_sandbox_builds_successfully`: Verifies Docker image builds without errors
  - `test_docker_compose_config_valid`: Validates docker-compose configuration

- **TestContainerLifecycle**: Container start/stop/restart workflows
  - `test_container_starts_in_detached_mode`: Detached mode startup
  - `test_container_stops_cleanly`: Clean shutdown
  - `test_container_restarts_after_stop`: Stop → start workflow
  - `test_python_version_correct_in_container`: Python version verification

- **TestMountPersistence**: File system mount persistence
  - `test_file_modifications_persist_after_restart`: Verifies mounts persist across container lifecycle

- **TestContainerExecution**: Command execution in containers
  - `test_container_can_execute_python_script`: Script execution
  - `test_container_has_required_tools`: Tool availability (python, git, curl, zsh)

- **TestErrorHandling**: Error scenarios
  - `test_build_fails_with_invalid_dockerfile`: Invalid Dockerfile handling
  - `test_cannot_start_without_image`: Missing image error handling

- **TestPortExposure**: Port configuration
  - `test_container_exposes_configured_ports`: Port mapping verification

- **TestCLIIntegration**: End-to-end CLI workflows
  - `test_run_command_creates_sandbox`: Full `devenv run` workflow

#### `test_lifecycle.py` (Integration Tests)

Additional integration tests mixed with unit tests:

- **TestRunCommandIntegration**: CLI validation and detection
  - `test_run_validates_nonexistent_path`: Path validation
  - `test_run_validates_file_not_directory`: Directory validation
  - `test_run_detects_python_version_from_file`: Auto-detection

- **TestLifecycleWorkflows**: Complete workflows
  - `test_complete_lifecycle_workflow_mocked`: Full lifecycle orchestration

- **TestPortConflictDetection**: Port parsing and conflicts
  - `test_parse_port_with_udp_protocol`: UDP protocol support
  - `test_parse_complex_port_mapping`: Complex mappings

- **TestBackgroundProcessManagement**: Serena and GPG
  - `test_serena_server_respects_port_option`: Serena port configuration
  - `test_gpg_forwarder_handles_missing_socket`: GPG socket handling

- **TestMountSpecParsing**: Mount mode parsing
  - `test_mount_spec_with_cow_mode`: Copy-on-write mode
  - `test_mount_spec_with_readonly_mode`: Read-only mode
  - `test_mount_spec_default_readwrite`: Default mode

#### `test_integration_sandbox.py`

Sandbox generation and Claude Code execution:

- `test_sandbox_generates_valid_docker_config`: Config file generation
- `test_sandbox_docker_compose_validates`: Docker Compose validation
- `test_sandbox_container_builds`: Container build verification
- `test_claude_code_modifies_file`: Claude Code functionality (requires auth)

#### `test_integration_ports.py`

Port exposure features:

- `test_profile_with_ports_loads`: Profile loading with ports
- `test_docker_compose_generated_with_ports`: Port mapping in generated config

## Test Fixtures

### Common Fixtures

- `docker_available`: Ensures Docker is running, auto-starts Docker Desktop if needed
- `test_project`: Creates a temporary test project with Python files
- `unique_sandbox_name`: Generates unique sandbox names to avoid conflicts
- `sandbox_dir`: Creates sandbox directory structure
- `minimal_sandbox`: Generates minimal sandbox (auto-cleanup)
- `built_sandbox`: Pre-built sandbox image ready for testing

### Cleanup

Integration test fixtures handle cleanup automatically:
- Stop and remove containers
- Remove Docker images
- Clean up temporary directories

## Writing New Tests

### Unit Test Example

```python
def test_parse_port_spec_simple() -> None:
    """Should parse simple port number."""
    result = _parse_port_spec("8000")
    assert result.container == 8000
    assert result.host_port == 8000
    assert result.protocol == "tcp"
```

### Integration Test Example

```python
@pytest.mark.integration
class TestMyFeature:
    """Integration tests for my feature."""

    def test_feature_with_docker(
        self, docker_available: None, built_sandbox: Path, unique_sandbox_name: str
    ) -> None:
        """Test feature with actual Docker container."""
        try:
            # Start container
            _start_container_detached(unique_sandbox_name, built_sandbox)

            # Test your feature
            assert _is_container_running(unique_sandbox_name, built_sandbox)

        finally:
            # Cleanup
            _stop_container(unique_sandbox_name, built_sandbox)
```

## CI/CD

The `.forgejo/workflows/ci.yml` workflow:

1. Runs unit tests on every push/PR
2. Runs integration tests on dedicated runners with Docker
3. Generates coverage reports

To run the same checks locally:

```bash
# Run what CI runs
pytest -v --cov=src/mirustech/devenv_generator --cov-report=term-missing

# Include integration tests (requires Docker)
pytest -m integration -v
```

## Coverage

Check test coverage:

```bash
# Unit tests only
pytest --cov=src/mirustech/devenv_generator --cov-report=html

# All tests (including integration)
pytest -m "" --cov=src/mirustech/devenv_generator --cov-report=html

# Open coverage report
open htmlcov/index.html
```

## Debugging Tests

### Verbose output

```bash
pytest -vv tests/test_lifecycle.py
```

### Show print statements

```bash
pytest -s tests/test_lifecycle.py
```

### Stop on first failure

```bash
pytest -x tests/test_lifecycle.py
```

### Run specific test with full traceback

```bash
pytest -vv --tb=long tests/test_lifecycle.py::TestClass::test_method
```

### Keep Docker containers for debugging

Modify the cleanup fixture or remove the cleanup:

```python
# Comment out cleanup in fixture
# subprocess.run(["docker", "compose", "down", "-v"], ...)
```

Then inspect the container:

```bash
docker ps -a
docker logs <container-id>
docker exec -it <container-id> /bin/bash
```

## Performance

Integration tests are slower:
- Unit tests: ~1-2 seconds total
- Integration tests: ~5-10 minutes (building images, running containers)

To speed up integration tests during development:
1. Run specific test classes instead of all tests
2. Use cached Docker layers (avoid `--no-cache`)
3. Run tests in parallel with `pytest-xdist`:
   ```bash
   pytest -m integration -n auto
   ```

## Troubleshooting

### "Docker is not available"

Ensure Docker Desktop is running:

```bash
docker info
```

If not running, start it manually or the test fixture will attempt to start it.

### "Build timeout"

Increase the timeout in the test:

```python
BUILD_TIMEOUT = 600  # 10 minutes
```

### Port conflicts

Integration tests use random high ports (49152-65535) to avoid conflicts.
If you still see conflicts, ensure no services are using those ports.

### Cleanup failures

If containers aren't cleaned up:

```bash
# List all containers
docker ps -a | grep test-lifecycle

# Remove manually
docker rm -f <container-id>
docker rmi -f <image-name>
```

## Best Practices

1. **Use unit tests for most logic**: Fast, reliable, no external dependencies
2. **Use integration tests for critical paths**: Actual Docker workflows
3. **Keep integration tests focused**: Test one thing at a time
4. **Always clean up resources**: Use fixtures with proper cleanup
5. **Make tests independent**: Each test should work in isolation
6. **Use descriptive names**: Test names should describe what they verify
7. **Document requirements**: Note when tests need Docker, auth, etc.
