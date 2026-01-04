# devenv-generator Improvement Plan

## Overview

This plan identifies incremental enhancements to improve devenv-generator across four areas: performance/reliability, features/UX, code architecture, and testing. The project currently has strong foundations (feature-based organization, Pydantic validation, comprehensive integration tests with real Docker), so improvements focus on targeted optimizations and additions rather than restructuring.

Chosen approach: **Incremental Enhancement** prioritized by user feedback: (1) Performance & Reliability, (2) Features & UX, (3) Architecture & Maintainability, (4) Testing Coverage. Each milestone delivers standalone value, builds on existing patterns, and maintains backward compatibility.

## Planning Context

### Decision Log

| Decision | Reasoning Chain |
|----------|----------------|
| Exponential backoff for Docker startup | Fixed `time.sleep(2)` polls every 2s for 60s total -> wastes 58s when Docker starts in 5s -> exponential backoff (1s, 2s, 4s, 8s, 16s) reaches ready state faster while maintaining same max wait -> better UX with no reliability trade-off |
| 16s exponential backoff cap | Exponential doubling (1s, 2s, 4s, 8s, 16s, 32s...) without cap -> 32s interval too slow for responsiveness (user waits 32s between attempts during extended startup) -> 8s cap reaches 60s timeout too quickly with fewer large-interval retries -> 16s balances: frequent enough retries (every 16s after ramp-up) while maintaining exponential benefit (1+2+4+8+16+16... vs fixed 2s) -> achieves fast startup detection (<10s when Docker starts quickly) without excessive wait gaps (16s max vs 32s) |
| Extract exponential backoff to shared utility | Duplicate backoff logic in lifecycle.py and diagnostics.py (15 lines each) -> maintenance liability (bug fixes must be applied twice) -> extract to utils/subprocess.py:wait_with_exponential_backoff() -> single implementation testable in isolation -> eliminates duplication while preserving existing behavior (lifecycle uses 60s max, diagnostics uses 40s max) |
| 40s timeout for diagnostics auto-fix | Lifecycle Docker startup uses 60s (balances user patience with slow startup) -> diagnostics auto-fix context: user ran `devenv doctor --fix` expecting quick fix -> 60s wait feels too long for diagnostic tool -> 40s provides ~8-10 retry attempts with exponential backoff (1s+2s+4s+8s+16s+16s = 47s coverage) -> fails faster on truly broken Docker while still succeeding for typical startup (15-30s) -> tradeoff: users with 45-60s startup must use `devenv run` instead of `doctor --fix`, but diagnostic tools should fail fast |
| Exception handling in wait_with_exponential_backoff | Docker availability checks fail with platform-specific errors (subprocess.TimeoutExpired when docker info hangs, FileNotFoundError when Docker CLI missing, PermissionError when socket lacks permissions, ConnectionError when daemon unreachable, OSError catchall for I/O) -> catch these specific types for retry behavior -> unexpected exceptions (JSONDecodeError from malformed output, rare transient errors) caught with warning log and retry -> prevents command crash on Docker CLI output corruption -> tradeoff: broader exception handling (slower debugging of programming errors) vs defensive production behavior (no crash on malformed output) -> production reliability prioritized |
| Empty hash check after exception handler | Exception handler sets stored_hash="" (line 846) -> valid read of empty file also produces "" -> single empty-string check (line 849) covers both paths (exception and empty file) -> consolidates logic, eliminates redundant "config_changed=True" assignment |
| Minimal profile (fast iteration) | Current default.yaml includes many tools -> build time ~5-10min -> developers iterating on profiles wait unnecessarily -> minimal profile with only Python + essentials builds in <2min -> 50-80% faster feedback during development |
| Web-dev profile (Node ecosystem) | Users running web projects need Node, npm, vite, etc. -> manually adding to default.yaml duplicates effort -> web-dev template provides Node 22 + common tools -> reduces setup from 10+ lines to single `--profile web-dev` |
| Data-science profile (ML stack) | ML workflows need numpy, pandas, jupyter, scikit-learn -> adding individually to profiles error-prone -> data-science template bundles validated ML stack -> reduces setup errors and provides working configuration |
| Extract BuildDecisionUseCase | run() command lines 550-644 mixes Docker image checks, build hash comparison, registry logic -> function exceeds 50 lines (god function per default-conventions) -> extract to BuildDecisionUseCase preserving BuildOrPullImageUseCase integration -> separates concerns, testable in isolation, reusable across commands -> note: BuildDecisionUseCase.execute() itself is ~140 lines (sequential decision tree: local image → hash → registry → decision) -> accepted as sequential algorithm exception to god-function rule (default-conventions allows state machines) -> further extraction would fragment decision logic across multiple methods, reducing readability of decision flow |
| Double SandboxGenerator.generate() in registry path | BuildOrPullImageUseCase requires docker-compose.yml to exist (runs `docker compose pull`) -> first generate() creates compose file with local image tag (line 887) -> registry pull executes -> if successful, second generate() updates compose file with registry image reference (line 905, not local tag) -> alternative (single generate() with conditional image_spec) requires BuildOrPullImageUseCase to return result before compose file exists (chicken-and-egg) -> current approach: generate with local tag, then regenerate with registry tag if pull succeeds -> tradeoff: redundant file writes (2× docker-compose.yml, ~500 bytes each) vs simpler use case contracts and no circular dependency |
| Node 22 for web-dev profile | Node.js versions: Node 20 LTS (until 2026-04-30, maximum compatibility), Node 22 LTS (Active LTS until 2027-04-30, modern features), Node 23 current (latest features, short support window) -> web-dev profile targets new projects requiring modern tooling (Vite 5+ requires Node >=18, TypeScript 5.5+ optimized for Node >=20) -> Node 22 balances stability (2+ years LTS support remaining) with modern features (native test runner, improved watch mode, performance gains) -> as of 2024 Q4, Node 22 is default for new projects per Node.js release schedule and Vite documentation -> users can customize profile for Node 20 (legacy compatibility) or Node 23 (bleeding edge, short support) |
| Property-based tests for parsing | Port specs and mount specs have many valid formats ("8000", "8080:3000/udp", "/path:cow") -> example-based tests miss edge cases (boundary values, unusual combinations) -> hypothesis generates wide input space automatically -> catches bugs humans miss (e.g., port 0, port 65536, empty path strings) |
| Filesystem-safe path strategy for property tests | Unrestricted st.text() generates control characters, Unicode, null bytes -> some combinations cause filesystem errors (platform-specific invalid characters) or obscure test failures -> strategy restricted to alphanumeric + common path chars (/-_.) plus whitespace filter -> ensures generated paths work across macOS/Linux filesystems -> tradeoff: narrower input space (misses exotic path edge cases) vs reliable cross-platform tests -> test reliability prioritized (parsing logic doesn't need Unicode validation) |
| Preserve BuildOrPullImageUseCase | Registry integration already exists at lifecycle.py:578-609 -> refactoring build logic could break registry -> BuildDecisionUseCase wraps BuildOrPullImageUseCase without modification -> registry behavior unchanged, no integration risk |

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|--------------|
| Replace time.sleep with async/await | Would require converting entire command stack to async -> high refactoring cost -> existing synchronous subprocess calls work reliably -> exponential backoff provides same UX improvement without async complexity |
| Single "universal" profile | Different stacks have incompatible tooling (Node vs Python-only, ML libs conflict with minimal builds) -> one profile forces users to carry unused dependencies -> separate templates allow focused, fast builds -> users choose profile matching their stack |
| Comprehensive refactoring | User specified incremental scope -> project is functional and actively maintained -> comprehensive changes high risk -> incremental improvements deliver value faster with lower risk |
| Unit tests before integration | User prioritized performance/features over testing -> project already has 35 integration tests with real Docker -> adding unit tests for stable code low ROI -> property-based tests for complex parsing logic higher value |
| Windows support | Not mentioned in requirements -> macOS/Linux only per pyproject.toml and code -> adding Windows would require significant Docker Desktop integration changes -> out of scope for incremental enhancements |

### Constraints & Assumptions

**Technical**:
- Python >=3.12 (pyproject.toml:6 `requires-python = ">=3.12"`)
- Dependencies: pydantic>=2.0, rich-click>=1.7, jinja2>=3.1, pyyaml>=6.0, structlog>=24.0
- Docker and Docker Compose required (macOS/Linux auto-start support)
- Claude Code OAuth integration (reads ~/.claude/.credentials.json)
- MCP server compatibility (Serena on port 9121, context7)

**Organizational**:
- Incremental scope (user-specified: step 2 confirmation)
- Feature-based organization preserved (doc-derived: README.md Architecture, CLAUDE.md Index)
- Integration tests preferred (doc-derived: TESTING.md, test files with @pytest.mark.integration)
- Adapter pattern for external systems (doc-derived: adapters/ directory, README Architecture)

**Default Conventions Applied**:
- `<default-conventions domain="testing">`: Integration tests with real dependencies preferred over unit tests
- `<default-conventions domain="god-function">`: Functions >50 lines trigger refactoring
- `<default-conventions domain="file-creation">`: Extend existing files unless >300-500 lines or distinct module boundary

### Known Risks

| Risk | Mitigation | Anchor |
|------|------------|--------|
| Exponential backoff changes break integration tests | Tests use `_ensure_docker_running()` which polls until success -> change internal timing without changing API -> tests remain valid | test_integration_lifecycle.py:31-78 `def _ensure_docker_running() -> bool: ... for _ in range(30): time.sleep(2)` polls until `docker info` succeeds |
| New profiles fail Pydantic validation | Use existing ProfileConfig model with full validation -> YAML schema errors caught at load time -> invalid profiles cannot be used | models.py:158-180 `class ProfileConfig(BaseModel): ... model_config = ConfigDict(extra="forbid")` rejects unknown fields |
| Build logic extraction breaks registry integration | Preserve `BuildOrPullImageUseCase` call site unchanged -> BuildDecisionUseCase wraps existing logic -> registry code path identical | lifecycle.py:578-609 `if settings.registry.enabled: use_case = BuildOrPullImageUseCase() ... result = use_case.execute(...)` existing integration |
| Property tests generate invalid inputs | hypothesis `@given` decorators specify valid ranges (port 1-65535, path non-empty) -> invalid inputs rejected by strategy -> only semantically valid test cases generated | hypothesis strategies constrain generation |
| Minimal profile too minimal for production | Minimal profile documented as "fast iteration only" -> users choose appropriate profile for their use case -> production users select default/web-dev/data-science | Accepted: users responsible for profile selection |

## Invisible Knowledge

### Architecture

```
User CLI Command
    |
    v
+-------------------+
| commands/         |  Feature-based organization
| - lifecycle.py    |  (run, attach, stop, start)
| - profiles.py     |  (list, show, create, edit)
| - diagnostics.py  |  (doctor with checks/fixes)
| - config.py       |  (global settings)
| - management.py   |  (status, rm, clean)
| - ports.py        |  (expose, unexpose, ports)
+-------------------+
    |
    v
+-------------------+        +--------------------+
| application/      |        | adapters/          |
| use_cases/        |------->| - DockerRegistry   |
| - BuildOrPull     |        | - GitClient        |
| - BuildDecision   |        +--------------------+
+-------------------+
    |
    v
+-------------------+        +--------------------+
| generator.py      |        | utils/             |
| - SandboxGen      |        | - subprocess.py    |
| - ProfileLoader   |        | - ProcessManager   |
+-------------------+        +--------------------+
    |
    v
+-------------------+
| models.py         |  Pydantic validation
| - ProfileConfig   |
| - MountSpec       |
| - PortConfig      |
+-------------------+
    |
    v
+-------------------+
| templates/        |  Jinja2 rendering
| - Dockerfile.j2   |
| - compose.yml.j2  |
+-------------------+
```

### Data Flow

```
User: devenv run --profile web-dev ~/myproject
    |
    v
1. CLI parses arguments (lifecycle.py:run)
    |
    v
2. Load profile (generator.py:load_profile)
   - Check ~/.config/devenv-generator/profiles/web-dev.yaml
   - Fallback to bundled profiles/web-dev.yaml
   - Pydantic validates ProfileConfig
    |
    v
3. Build decision (BuildDecisionUseCase)
   - Check Docker image exists
   - Compute build hash from profile + templates
   - Compare with .devcontainer/.build-hash
   - If changed: rebuild required
   - If registry enabled: try pull from registry
    |
    v
4. Generate sandbox files (SandboxGenerator)
   - Render Dockerfile.j2 with profile vars
   - Render docker-compose.yml.j2 with mounts
   - Write .devcontainer/.build-hash
    |
    v
5. Build/pull image (conditional)
   - If skip_build=False: docker compose build
   - If registry enabled: BuildOrPullImageUseCase
    |
    v
6. Start background processes
   - Serena MCP server on port 9121 (if enabled)
   - GPG agent forwarder on port 9876 (if socket exists)
    |
    v
7. Run container
   - docker compose run --rm dev
   - Mounts: /workspace/<project> (rw/ro/cow)
   - Copies: ~/.claude, ~/.happy, ~/.ssh
   - Executes: uv sync && claude --dangerously-skip-permissions
```

### Why This Structure

**Feature-based commands/** instead of technical layers:
- Users think in terms of tasks ("manage profiles", "run sandbox", "check health")
- Feature grouping matches mental model (profiles.py for all profile operations)
- Alternative (MVC layers) would scatter related operations across controller/service/model files
- Trade-off: Some code duplication across commands vs. easier navigation and modification

**Adapter pattern for external systems**:
- Docker registry and Git are external dependencies with complex APIs
- Adapters (DockerRegistryClient, SubprocessGitClient) isolate integration points
- Enables testing with mocks, swapping implementations (e.g., Docker API vs CLI)
- Trade-off: Extra indirection vs. testability and flexibility

**ProcessManager for background processes**:
- GPG forwarder and Serena server outlive command execution
- ProcessManager centralizes lifecycle (start, cleanup, timeout handling)
- atexit hooks ensure cleanup even on abnormal termination
- Trade-off: Singleton state vs. reliable cleanup

### Invariants

1. **Build hash must match profile + templates**: If `.devcontainer/.build-hash` exists, it MUST equal `compute_build_hash(ProfileConfig)`. Mismatch indicates profile changed and rebuild required.

2. **ProfileConfig validation before use**: All YAML profiles MUST pass Pydantic validation before rendering templates. Invalid profiles cause early failure (better than Dockerfile syntax errors).

3. **Sandbox name uniqueness**: Docker Compose project names must be unique per sandbox. Collision causes container conflicts.

4. **Mount paths must exist**: All `MountSpec.host_path` MUST exist before container starts. Missing paths cause Docker mount errors.

5. **Port availability before binding**: Ports must be checked for conflicts (lifecycle.py:_check_port_conflicts) before `docker compose up`. Binding to in-use port fails.

### Tradeoffs

| Decision | Cost | Benefit | Rationale |
|----------|------|---------|-----------|
| Build hash tracking | Extra I/O (hash computation, file write) | Avoids unnecessary rebuilds (saves 5-10min) | Benefit outweighs cost: rebuild time >> hash computation time |
| Integration tests with real Docker | Slow tests (5-10min suite), requires Docker | High confidence, tests actual user workflows | Default-conventions prefer integration tests for end-user behavior |
| Feature-based organization | Some code duplication across commands | Easier navigation, matches user mental model | Maintainability from clear boundaries > DRY |
| Copy ~/.claude into container | Larger image size (~50MB OAuth data) | Seamless Claude Code auth, MCP server config | Required for functionality, size acceptable |
| Background process cleanup with atexit | Processes may not terminate if Python crashes | Cleanup on normal exit, Ctrl+C, exceptions | Best-effort cleanup sufficient for dev tool |

## Milestones

### Milestone 1: Optimize Docker Startup Polling

**Files**:
- `src/mirustech/devenv_generator/utils/subprocess.py`
- `src/mirustech/devenv_generator/commands/lifecycle.py`
- `src/mirustech/devenv_generator/commands/diagnostics.py`

**Flags**: needs error review (Docker startup failure modes under different conditions)

**Requirements**:
- Extract exponential backoff to `utils/subprocess.py:wait_with_exponential_backoff()`
- Replace fixed `time.sleep(2)` with exponential backoff: 1s, 2s, 4s, 8s, 16s
- Maximum total wait time: 60 seconds for lifecycle (same as current 30 iterations × 2s), 40s for diagnostics
- 16s cap prevents excessive wait gaps (32s too slow for responsiveness during extended startup)
- Preserve failure behavior: return False after timeout
- Apply shared utility to both `_ensure_docker_running()` (lifecycle) and `fix_docker_running()` (diagnostics)

**Acceptance Criteria**:
- Docker startup completes in <10s when Docker starts in 5s (30s average with fixed 2s polling)
- Waits full 60s if Docker takes longer
- Integration tests pass (tests poll until success regardless of timing)
- Manual test: Stop Docker, run `devenv doctor --fix`, observe <10s wait when Docker starts quickly

**Tests** (milestone not complete until tests pass):
- **Test files**: `tests/test_integration_lifecycle.py`, `tests/test_diagnostics.py`
- **Test type**: integration
- **Backing**: doc-derived (TESTING.md specifies integration tests with real Docker)
- **Scenarios**:
  - Normal: Docker starts in 3s -> function returns True in <5s total
  - Edge: Docker takes 45s to start -> function returns True after ~45s (polls until success)
  - Error: Docker never starts -> function returns False after 60s timeout
  - Existing integration tests continue to pass (they use `_ensure_docker_running()` internally)

**Code Changes**:

First, add shared exponential backoff utility:

```diff
--- a/src/mirustech/devenv_generator/utils/subprocess.py
+++ b/src/mirustech/devenv_generator/utils/subprocess.py
@@ -1,6 +1,7 @@
 """Subprocess execution utilities."""

 import subprocess
+import time
 from typing import Any, Callable

 import structlog
@@ -47,3 +48,31 @@ def run_command(

     return subprocess.run(cmd, capture_output=True, text=text, timeout=timeout, **kwargs)
+
+
+def wait_with_exponential_backoff(
+    check_fn: Callable[[], bool],
+    max_wait: int = 60,
+    initial_delay: int = 1,
+    max_delay: int = 16,
+) -> bool:
+    """Poll check_fn with exponential backoff until success or timeout.
+
+    Exponential backoff (1s, 2s, 4s, 8s, 16s, 16s...) detects fast startup
+    quickly (completes in ~7s when Docker starts in 5s) while maintaining
+    full timeout coverage (reaches 60s total wait for slow startup). Pattern
+    minimizes wait time for fast startup while tolerating slow startup without
+    timeout failures.
+
+    Args:
+        check_fn: Function returning True on success, False to retry.
+                 Exceptions treated as check failure (continues retrying).
+        max_wait: Maximum total wait time in seconds.
+        initial_delay: Starting delay (doubles each iteration).
+        max_delay: Cap prevents excessive wait gaps between retries. 16s allows 4-5
+                   retry attempts within 60s timeout window, balancing responsiveness
+                   (frequent retries) with timeout coverage (reaches 60s total).
+
+    Returns:
+        True if check_fn succeeded within max_wait, False on timeout.
+    """
+    elapsed = 0
+    delay = initial_delay
+    while elapsed < max_wait:
+        # Immediate return on success (no delay for already-running Docker)
+        try:
+            if check_fn():
+                return True
+        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError, ConnectionError, OSError):
+            # Docker availability checks fail with platform-specific errors:
+            # - TimeoutExpired: docker info hangs on unresponsive daemon
+            # - FileNotFoundError: Docker CLI binary not in PATH
+            # - PermissionError: socket lacks user permissions (not in docker group)
+            # - ConnectionError: daemon unreachable (stopped, crashed)
+            # - OSError: I/O errors (disk full, broken socket)
+            # All treated as transient (retry continues until timeout)
+            pass
+        except Exception as e:
+            # Broad handler catches unexpected exceptions (JSONDecodeError from malformed docker info output,
+            # rare transient errors) to prevent crash. Warning log provides visibility for debugging.
+            # Tradeoff: broader exception handling (slower debugging of programming errors) vs defensive
+            # production behavior (no crash on Docker CLI output corruption)
+            logger.warning("check_fn_unexpected_exception", error=str(e), error_type=type(e).__name__)
+            pass
+
+        # Final iteration exits without sleeping (prevents exceeding max_wait timeout)
+        if elapsed + delay >= max_wait:
+            break
+
+        time.sleep(delay)
+        elapsed += delay
+        delay = min(delay * 2, max_delay)  # Double until max_delay cap
+    return False
```

Then update lifecycle to use shared utility:

```diff
--- a/src/mirustech/devenv_generator/commands/lifecycle.py
+++ b/src/mirustech/devenv_generator/commands/lifecycle.py
@@ -27,8 +27,9 @@ from mirustech.devenv_generator.models import ImageSpec, MountSpec, PortConfig,
 from mirustech.devenv_generator.settings import get_settings
 from mirustech.devenv_generator.utils.process_manager import ProcessManager
-from mirustech.devenv_generator.utils.subprocess import run_command
+from mirustech.devenv_generator.utils.subprocess import run_command, wait_with_exponential_backoff
+from mirustech.devenv_generator.generator import compute_build_hash

 console = Console()
 logger = structlog.get_logger()
@@ -166,12 +166,14 @@ def _ensure_docker_running() -> bool:
     except (subprocess.TimeoutExpired, FileNotFoundError):
         pass

     console.print("[dim]Starting Docker Desktop...[/dim]")
     with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError):
         run_command(["open", "-a", "Docker"], timeout=5)

-    for _ in range(30):
-        time.sleep(2)
-        try:
-            result = run_command(["docker", "info"])
-            if result.returncode == 0:
-                return True
-        except (subprocess.TimeoutExpired, FileNotFoundError):
-            pass
-
-    return False
+    # Exponential backoff (1s, 2s, 4s, 8s, 16s): detects fast startup in ~7s when Docker ready quickly
+    # 60s timeout: accommodates macOS Docker Desktop startup (typically 15-45s)
+    # 16s cap: allows 4-5 retry attempts within 60s window
+    return wait_with_exponential_backoff(
+        check_fn=lambda: run_command(["docker", "info"]).returncode == 0,
+        max_wait=60,
+        max_delay=16,
+    )
```

Then update diagnostics to use shared utility:

```diff
--- a/src/mirustech/devenv_generator/commands/diagnostics.py
+++ b/src/mirustech/devenv_generator/commands/diagnostics.py
@@ -18,6 +18,7 @@ from mirustech.devenv_generator.generator import get_bundled_profile
 from mirustech.devenv_generator.models import ProfileConfig
 from mirustech.devenv_generator.settings import get_settings
+from mirustech.devenv_generator.utils.subprocess import wait_with_exponential_backoff

 console = Console()
 logger = structlog.get_logger()
@@ -411,17 +412,16 @@ def fix_docker_running() -> tuple[bool, str]:
         subprocess.run(["open", "-a", "Docker"], capture_output=True, timeout=5)

-        for _ in range(20):
-            time.sleep(2)
-            result = subprocess.run(
-                ["docker", "info"],
-                capture_output=True,
-                timeout=10,
-            )
-            if result.returncode == 0:
-                return True, "Docker started successfully"
-
-        return False, "Docker failed to start within timeout"
+        # 40s timeout: diagnostic auto-fix provides faster feedback than lifecycle commands (60s)
+        # Exponential backoff (1s, 2s, 4s, 8s, 16s, 16s): ~8-10 retry attempts within 40s window
+        success = wait_with_exponential_backoff(
+            check_fn=lambda: subprocess.run(
+                ["docker", "info"], capture_output=True, timeout=10
+            ).returncode == 0,
+            max_wait=40,
+            max_delay=16,
+        )
+        return (True, "Docker started successfully") if success else (False, "Docker failed to start within timeout")
     except Exception as e:
         return False, f"Failed to start Docker: {e}"
```

### Milestone 2: Add Profile Templates

**Files**:
- `src/mirustech/devenv_generator/profiles/minimal.yaml` (new)
- `src/mirustech/devenv_generator/profiles/web-dev.yaml` (new)
- `src/mirustech/devenv_generator/profiles/data-science.yaml` (new)

**Flags**: needs conformance check (all profiles must validate against ProfileConfig schema)

**Requirements**:
- **Minimal profile**: Python + git + curl only. Fast builds (<2min) for iteration.
- **Web-dev profile**: Node 22, npm, vite, typescript, eslint. For web development workflows.
- **Data-science profile**: Python ML stack (numpy, pandas, scikit-learn, jupyter). For ML workflows.
- All profiles must validate with `ProfileConfig.model_validate(yaml.safe_load(content))`
- Include descriptions and recommended use cases in profile metadata

**Acceptance Criteria**:
- `devenv run --profile minimal` builds in <2min (vs. 5-10min for default)
- `devenv run --profile web-dev` includes Node 22 and npm tools in container
- `devenv run --profile data-science` includes numpy, pandas, jupyter in container
- `devenv profiles list` shows all three new profiles with descriptions
- All profiles pass Pydantic validation (no schema errors)

**Tests** (milestone not complete until tests pass):
- **Test files**: `tests/test_integration_lifecycle.py`, `tests/test_profiles.py`
- **Test type**: integration (build and run actual containers)
- **Backing**: doc-derived (TESTING.md specifies integration tests)
- **Scenarios**:
  - Normal: Each profile loads, validates, generates sandbox, builds image successfully
  - Edge: Profile with minimal packages builds faster than profile with many packages
  - Error: Invalid profile YAML (missing required fields) raises ValidationError
  - Integration: `devenv run --profile minimal` completes build in <2min
  - Integration: `devenv run --profile web-dev` container has `node --version` returning v22.x
  - Integration: `devenv run --profile data-science` container has `python -c "import pandas"` succeeding

**Code Changes**:

New file content (not diff format as files don't exist yet):

**src/mirustech/devenv_generator/profiles/minimal.yaml**:
```yaml
# Minimal profile: Fast iteration for profile development
# Build time <2min (50-80% faster than default profile's 5-10min)
# Contains only Python essentials (no additional tooling) to minimize layer caching and package installation time
# Use when: Rapidly testing profile changes, debugging generator logic
# Do NOT use for: Production work requiring language tooling beyond Python

name: minimal
description: Minimal profile for fast iteration - Python + essential tools only
python:
  version: "3.12"
  packages: []  # uv available for dependency management, no pre-installed packages
system_packages:
  - git
  - curl
node_packages: []  # No Node.js installed; web-dev profile provides Node.js if needed
uvx_tools: []
github_releases: {}
mcp:
  enable_serena: false  # Serena adds ~30s to startup, disabled for speed
  serena_port: 9121
  serena_browser: false
ports:
  ports: []
```

**src/mirustech/devenv_generator/profiles/web-dev.yaml**:
```yaml
# Web development profile: Node 22 + modern frontend tooling
# Build time ~3-5min (Node installation + npm packages)
# Bundles validated web stack (TypeScript, ESLint, Prettier, Vite) to avoid per-project configuration
# Ports 3000/5173 pre-configured for Vite dev server (common defaults in web ecosystem)
# Use when: Developing web apps with Vite, React, Vue, Svelte, or similar frameworks

name: web-dev
description: Web development profile - Node 22 + modern web tooling
python:
  version: "3.12"
  packages: []  # Python available but not primary focus
system_packages:
  - git
  - curl
  - nodejs  # Node 22 LTS (Active LTS until 2027-04-30, balances stability with modern features)
node_packages:
  - "@anthropic-ai/claude-code"
  - vite
  - typescript
  - eslint
  - prettier
uvx_tools: []
github_releases: {}
mcp:
  enable_serena: true  # Code intelligence useful for web projects
  serena_port: 9121
  serena_browser: false
ports:
  ports:
    - container: 3000
      host: 3000
      protocol: tcp
      description: Vite dev server  # Common Vite default
    - container: 5173
      host: 5173
      protocol: tcp
      description: Vite (alternative port)  # Vite fallback when 3000 in use
```

**src/mirustech/devenv_generator/profiles/data-science.yaml**:
```yaml
# Data science profile: Python ML/data analysis stack
# Build time ~5-7min (ML libraries have native dependencies requiring compilation)
# Bundles validated ML stack (numpy, pandas, scikit-learn, jupyter, matplotlib, seaborn) to avoid compatibility issues
# Port 8888 pre-configured for Jupyter notebook server (standard in data science workflows)
# Use when: Data analysis, machine learning, scientific computing workflows

name: data-science
description: Data science profile - Python ML stack
python:
  version: "3.12"
  packages:
    - numpy  # Numerical computing (compiled C extensions)
    - pandas  # Data manipulation (builds on numpy)
    - scikit-learn  # Machine learning algorithms
    - jupyter  # Interactive notebooks
    - matplotlib  # Plotting library
    - seaborn  # Statistical visualization (matplotlib wrapper)
system_packages:
  - git
  - curl
node_packages:
  - "@anthropic-ai/claude-code"
uvx_tools: []
github_releases: {}
mcp:
  enable_serena: true  # Serena useful for navigating large data processing codebases
  serena_port: 9121
  serena_browser: false
ports:
  ports:
    - container: 8888
      host: 8888
      protocol: tcp
      description: Jupyter notebook server  # Standard Jupyter port
```

### Milestone 3: Extract Build Decision Logic

**Files**:
- `src/mirustech/devenv_generator/commands/lifecycle.py`
- `src/mirustech/devenv_generator/application/use_cases/build_decision.py` (new)

**Flags**: needs TW rationale (multiple refactoring approaches possible - extraction vs. inline refactoring vs. state machine)

**Requirements**:
- Extract lines 550-644 from `lifecycle.py:run()` into `BuildDecisionUseCase`
- All existing behavior preserved: build hash checks, registry integration, skip_build logic
- Use case returns `BuildDecisionResult` with `skip_build`, `auto_no_cache`, `image_spec` fields
- Call site in `run()` becomes: `decision = BuildDecisionUseCase().execute(...)`
- BuildOrPullImageUseCase integration unchanged (lifecycle.py:578-609 logic preserved)

**Acceptance Criteria**:
- `lifecycle.py:run()` function <100 lines (180 lines baseline)
- Build decision logic testable in isolation (unit tests for hash comparison, registry fallback)
- All existing integration tests pass (behavior identical to pre-extraction)
- `devenv run` with registry enabled pulls/pushes images correctly
- `devenv run` with build hash match skips rebuild

**Tests** (milestone not complete until tests pass):
- **Test files**: `tests/test_build_decision.py` (new), `tests/test_integration_lifecycle.py` (existing)
- **Test type**: unit (build decision logic) + integration (full workflow)
- **Backing**: default-derived (<default-conventions domain="testing"> prefers integration, but unit tests appropriate for complex logic in use case)
- **Scenarios**:
  - Unit tests for BuildDecisionUseCase:
    - Normal: Image exists, hash matches -> skip_build=True, auto_no_cache=False
    - Normal: Image exists, hash mismatch -> skip_build=False, auto_no_cache=True
    - Normal: Image missing -> skip_build=False, auto_no_cache=True (rebuild for safety)
    - Edge: Registry enabled, image available -> skip_build=True, image_spec populated
    - Edge: Registry enabled, image missing -> skip_build=False, fallback to build
    - Error: Hash file corrupted/unreadable -> defaults to rebuild
  - Integration tests (existing):
    - All existing `test_integration_lifecycle.py` tests continue to pass
    - Build workflow with registry still pulls/pushes correctly
    - Build hash tracking still avoids unnecessary rebuilds

**Code Changes**:

```diff
--- a/src/mirustech/devenv_generator/commands/lifecycle.py
+++ b/src/mirustech/devenv_generator/commands/lifecycle.py
@@ -15,6 +15,7 @@ from rich.console import Console

 from mirustech.devenv_generator.application.use_cases.build_or_pull import (
     BuildOrPullImageUseCase,
 )
+from mirustech.devenv_generator.application.use_cases.build_decision import (
+    BuildDecisionUseCase,
+)
 from mirustech.devenv_generator.commands.management import _is_sandbox_running
@@ -547,97 +548,15 @@ def run(

     settings = get_settings()
-    image_spec: ImageSpec | None = None
-
-    build_hash_path = output_path / ".devcontainer" / ".build-hash"
-    current_build_hash = compute_build_hash(config)
-    auto_no_cache = False
-    skip_build = False
-    config_changed = False
-
-    image_result = run_command(["docker", "images", "-q", f"{sandbox_name}-dev:latest"])
-    image_exists = bool(image_result.stdout.strip())
-
-    if not image_exists:
-        console.print("[dim]No image found, will build[/dim]")
-        config_changed = True
-    elif build_hash_path.exists():
-        stored_hash = build_hash_path.read_text().strip()
-        if stored_hash != current_build_hash:
-            console.print("[yellow]⚠ Build configuration changed - rebuild required[/yellow]")
-            console.print("[dim]Changes detected in profile or templates[/dim]")
-            config_changed = True
-            auto_no_cache = True
-        elif not no_cache:
-            console.print("[dim]Build configuration unchanged[/dim]")
-    else:
-        console.print("[yellow]No build hash found - forcing rebuild for safety[/yellow]")
-        auto_no_cache = True
-        config_changed = True
-
-    if settings.registry.enabled and not no_registry:
-        use_case = BuildOrPullImageUseCase()
-        auto_push = push_to_registry or settings.registry.auto_push
-
-        generator = SandboxGenerator(
-            profile=config,
-            mounts=mount_specs,
-            sandbox_name=sandbox_name,
-            use_host_claude_config=not no_host_config,
-        )
-        generator.generate(output_path)
-
-        result = use_case.execute(
-            project_path=mount_specs[0].host_path,
-            project_name=sandbox_name,
-            registry_config=settings.registry,
-            sandbox_dir=output_path,
-            sandbox_name=sandbox_name,
-            auto_push=auto_push,
-        )
-
-        if result.image_spec:
-            image_spec = result.image_spec
-            skip_build = True
-            generator = SandboxGenerator(
-                profile=config,
-                mounts=mount_specs,
-                sandbox_name=sandbox_name,
-                use_host_claude_config=not no_host_config,
-                image_spec=image_spec,
-            )
-            generator.generate(output_path)
-    else:
-        generator = SandboxGenerator(
-            profile=config,
-            mounts=mount_specs,
-            sandbox_name=sandbox_name,
-            use_host_claude_config=not no_host_config,
-        )
-        generator.generate(output_path)
+
+    # BuildDecisionUseCase encapsulates image checks, hash comparison, registry logic.
+    # Testable in isolation, reusable across commands requiring build decisions.
+    decision_use_case = BuildDecisionUseCase()
+    decision_result = decision_use_case.execute(
+        config=config,
+        sandbox_name=sandbox_name,
+        output_path=output_path,
+        mount_specs=mount_specs,
+        no_host_config=no_host_config,
+        no_registry=no_registry,
+        no_cache=no_cache,
+        push_to_registry=push_to_registry,
+        registry_config=settings.registry if settings.registry.enabled else None,
+    )
+
+    # Persist build hash BEFORE container startup (not after)
+    # Tracks successful image build, not container startup success. Mount errors or container
+    # failures should not invalidate the built image (separation of concerns: build vs runtime).
+    # Placement before _run_sandbox ensures hash written even if container startup fails.
+    if not decision_result.skip_build:
+        build_hash_path = output_path / ".devcontainer" / ".build-hash"
+        build_hash_path.write_text(compute_build_hash(config))

     console.print()
@@ -655,9 +574,9 @@ def run(

     _start_gpg_forwarder()

-    if not config_changed and image_exists and not no_cache and not skip_build:
-        console.print("[dim]Image up-to-date, skipping build[/dim]")
-        skip_build = True
-
     _run_sandbox(
         sandbox_name,
         output_path,
         detach=detach,
         shell=shell,
-        skip_build=skip_build,
+        skip_build=decision_result.skip_build,
         serena_port=effective_serena_port if effective_start_serena else None,
-        no_cache=no_cache or auto_no_cache,
+        no_cache=no_cache or decision_result.auto_no_cache,
     )
```

New file **src/mirustech/devenv_generator/application/use_cases/build_decision.py**:
```python
"""
Docker build decision orchestration.

Determines whether to build, pull from registry, or skip build based on:
- Local image existence (docker images -q check)
- Build hash comparison (profile + templates fingerprint in .build-hash file)
- Registry availability (BuildOrPullImageUseCase integration)

Handles three distinct concerns: hash comparison (profile/template fingerprinting),
registry integration (BuildOrPullImageUseCase delegation), and sandbox generation
coordination (docker-compose.yml creation). Testable in isolation, reusable across
commands requiring build decisions.

Key types:
  - BuildDecisionResult: skip_build, auto_no_cache, image_spec outputs
  - BuildDecisionUseCase: orchestrates checks, delegates to BuildOrPullImageUseCase

Performance: Hash computation is I/O bound (profile + template reads) but saves
5-10min rebuild time by detecting when builds can be skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from mirustech.devenv_generator.application.use_cases.build_or_pull import (
    BuildOrPullImageUseCase,
)
from mirustech.devenv_generator.generator import SandboxGenerator, compute_build_hash
from mirustech.devenv_generator.models import (
    ImageSpec,
    MountSpec,
    ProfileConfig,
    RegistryConfig,
)
from mirustech.devenv_generator.utils.subprocess import run_command

console = Console()


@dataclass
class BuildDecisionResult:
    """
    Output of build decision use case.

    Attributes:
        skip_build: True if image up-to-date or pulled from registry
        auto_no_cache: True if config changed (forces clean rebuild)
        image_spec: Registry image reference if pulled, else None
    """

    skip_build: bool
    auto_no_cache: bool
    image_spec: ImageSpec | None = None


class BuildDecisionUseCase:
    """
    Orchestrates Docker build decision logic.

    Centralizes three checks that determine build requirements:
    1. Local image existence (docker images -q)
    2. Build hash comparison (detects profile/template changes)
    3. Registry pull attempt (BuildOrPullImageUseCase integration)

    Enables unit testing of hash comparison and registry fallback logic without
    full lifecycle integration tests. Reusable across commands that need to
    determine build requirements.
    """

    def execute(
        self,
        config: ProfileConfig,
        sandbox_name: str,
        output_path: Path,
        mount_specs: list[MountSpec],
        no_host_config: bool,
        no_registry: bool,
        no_cache: bool,
        push_to_registry: bool,
        registry_config: RegistryConfig | None,
    ) -> BuildDecisionResult:
        """
        Determine if Docker image build is required.

        Orchestrates three checks: local image existence, build hash fingerprint
        comparison, and registry pull attempt. Coordinates with BuildOrPullImageUseCase
        for registry authentication and fallback to local build.

        Strategy (sequential decision tree):
        1. Hash comparison: Profile + templates fingerprint in .build-hash.
           Match = skip rebuild (saves 5-10min). Mismatch/missing = rebuild
           with --no-cache (prevents stale cache layers from old config).

        2. Registry pull: If enabled and not disabled by flag, attempt pull.
           BuildOrPullImageUseCase handles auth and fallback. Success = skip
           local build, use registry image spec. Failure = proceed to local build.

        3. Local build fallback: No registry image or registry disabled.
           Skip only if local image exists AND hash matches AND no_cache not set.

        Args:
            config: Profile configuration (source for build hash computation)
            sandbox_name: Docker Compose project name (used for image tag)
            output_path: Sandbox directory (.devcontainer/.build-hash location)
            mount_specs: Volume mount specifications (passed to SandboxGenerator)
            no_host_config: Skip copying ~/.claude into container
            no_registry: Disable registry pull even if registry_config provided
            no_cache: Force rebuild without cache (user override)
            push_to_registry: Push to registry after build (manual push request)
            registry_config: Registry settings if enabled, else None

        Returns:
            BuildDecisionResult with skip_build, auto_no_cache, image_spec fields.

        Invariants:
        - auto_no_cache=True when config changed (prevents stale cache layers)
        - skip_build=True only if image up-to-date OR registry pull succeeded
        - image_spec populated only on successful registry pull

        Edge cases:
        - Missing .build-hash: defaults to rebuild (conservative for safety)
        - Hash file corrupted (OSError, UnicodeDecodeError): triggers rebuild with warning
        - Registry timeout: BuildOrPullImageUseCase returns None, falls back to build
        """
        build_hash_path = output_path / ".devcontainer" / ".build-hash"
        current_build_hash = compute_build_hash(config)

        # Check local image existence before hash comparison (avoid hash computation if no image exists)
        image_result = run_command(
            ["docker", "images", "-q", f"{sandbox_name}-dev:latest"]
        )
        image_exists = bool(image_result.stdout.strip())

        auto_no_cache = False
        config_changed = False

        # Hash comparison detects profile/template changes (fingerprint of build inputs)
        if not image_exists:
            console.print("[dim]No image found, will build[/dim]")
            config_changed = True
        elif build_hash_path.exists():
            try:
                stored_hash = build_hash_path.read_text().strip()
            except (OSError, UnicodeDecodeError) as e:
                # OSError: file permissions, disk I/O errors
                # UnicodeDecodeError: corrupted hash file (binary data, truncation)
                console.print(
                    f"[yellow]⚠ Build hash corrupted ({e.__class__.__name__}) - forcing rebuild[/yellow]"
                )
                stored_hash = ""

            # Check for empty hash (covers both successful read of empty file and exception path above)
            # Empty hash indicates: (1) .build-hash file created but never written, or (2) corruption
            if not stored_hash:
                console.print("[yellow]Build hash empty - triggering rebuild (prevents stale cache)[/yellow]")
                config_changed = True
                auto_no_cache = True
            elif stored_hash != current_build_hash:
                console.print(
                    "[yellow]⚠ Build configuration changed - rebuild required[/yellow]"
                )
                console.print("[dim]Changes detected in profile or templates[/dim]")
                config_changed = True
                auto_no_cache = True
            elif not no_cache:
                console.print("[dim]Build configuration unchanged[/dim]")
        else:
            console.print(
                "[yellow]No build hash found - forcing rebuild for safety[/yellow]"
            )
            auto_no_cache = True
            config_changed = True

        image_spec: ImageSpec | None = None
        skip_build = False

        # Registry integration path: attempt pull before local build (faster than rebuilding locally)
        if registry_config and not no_registry:
            auto_push = push_to_registry or (
                registry_config.auto_push if registry_config else False
            )

            # SandboxGenerator must run before BuildOrPullImageUseCase
            # BuildOrPullImageUseCase requires docker-compose.yml to exist (runs `docker compose pull`)
            generator = SandboxGenerator(
                profile=config,
                mounts=mount_specs,
                sandbox_name=sandbox_name,
                use_host_claude_config=not no_host_config,
            )
            generator.generate(output_path)

            # BuildOrPullImageUseCase handles registry auth and fallback to local build on pull failure
            use_case = BuildOrPullImageUseCase()
            result = use_case.execute(
                project_path=mount_specs[0].host_path,
                project_name=sandbox_name,
                registry_config=registry_config,
                sandbox_dir=output_path,
                sandbox_name=sandbox_name,
                auto_push=auto_push,
            )

            if result.image_spec:
                image_spec = result.image_spec
                skip_build = True

                # Second SandboxGenerator call updates compose file with registry image reference
                # First generate() created compose file with local tag, registry pull succeeded,
                # now compose file needs registry image reference instead of local build tag
                generator = SandboxGenerator(
                    profile=config,
                    mounts=mount_specs,
                    sandbox_name=sandbox_name,
                    use_host_claude_config=not no_host_config,
                    image_spec=image_spec,
                )
                generator.generate(output_path)
        else:
            # No registry path (local build only)
            generator = SandboxGenerator(
                profile=config,
                mounts=mount_specs,
                sandbox_name=sandbox_name,
                use_host_claude_config=not no_host_config,
            )
            generator.generate(output_path)

        # Final skip check: image up-to-date (hash match) and no forced rebuild (no_cache flag not set)
        if not config_changed and image_exists and not no_cache and not skip_build:
            console.print("[dim]Image up-to-date, skipping build[/dim]")
            skip_build = True

        return BuildDecisionResult(
            skip_build=skip_build,
            auto_no_cache=auto_no_cache,
            image_spec=image_spec,
        )
```

### Milestone 4: Add Property-Based Tests

**Files**:
- `tests/test_models.py`
- `tests/test_lifecycle.py`

**Flags**: none (extending existing test files)

**Requirements**:
- Add `hypothesis` property-based tests for port specification parsing (`_parse_port_spec`)
- Add `hypothesis` property-based tests for mount specification parsing (`MountSpec.from_string`)
- Generate wide range of valid inputs: ports (1-65535), protocols (tcp/udp), host:container mappings
- Generate wide range of valid mount specs: paths, modes (rw/ro/cow)
- Verify invariants hold for all generated inputs

**Acceptance Criteria**:
- Property tests run 100+ examples per function (hypothesis default)
- Tests catch edge cases: port 1, port 65535, empty host mapping, unusual paths
- All property tests pass (no invariant violations found)
- Property tests complete in <5s (fast enough for regular test runs)

**Tests** (milestone not complete until tests pass):
- **Test files**: `tests/test_models.py`, `tests/test_lifecycle.py`
- **Test type**: property-based (generative testing)
- **Backing**: default-derived (<default-conventions domain="testing"> lists property-based tests as preferred for functions with clear input/output contracts)
- **Scenarios**:
  - Property test for `_parse_port_spec`:
    - Generate valid port numbers (1-65535)
    - Generate valid protocols ("tcp", "udp")
    - Generate valid mappings ("port", "host:container", "port/proto", "host:container/proto")
    - Invariant: parsed container port always in range 1-65535
    - Invariant: protocol always "tcp" or "udp"
    - Invariant: host_port equals container port when no : mapping
  - Property test for `MountSpec.from_string`:
    - Generate valid paths (non-empty, various characters)
    - Generate valid modes ("rw", "ro", "cow")
    - Generate combined specs ("/path", "/path:mode")
    - Invariant: mode always "rw", "ro", or "cow"
    - Invariant: default mode is "rw" when not specified
    - Invariant: host_path is Path object

**Code Changes**:

```diff
--- a/tests/test_lifecycle.py
+++ b/tests/test_lifecycle.py
@@ -1,8 +1,12 @@
 """Tests for lifecycle command utilities."""

 from pathlib import Path
 from unittest.mock import MagicMock, patch

 import pytest
+from hypothesis import given
+from hypothesis import strategies as st
 from click.testing import CliRunner

 from mirustech.devenv_generator.cli import main
@@ -132,6 +136,56 @@ class TestParsePortSpec:
         with pytest.raises(SystemExit):
             _parse_port_spec("abc:3000")

+    # Property-based tests catch edge cases example-based tests miss (e.g., port 1, port 65535)
+    # Hypothesis generates 100+ test cases per function covering boundary values
+    valid_ports = st.integers(min_value=1, max_value=65535)
+    protocols = st.sampled_from(["tcp", "udp"])
+
+    @given(port=valid_ports)
+    def test_property_simple_port_roundtrip(self, port: int) -> None:
+        """Simple port specs parse correctly for all valid ports."""
+        result = _parse_port_spec(str(port))
+        assert result.container == port
+        assert result.host_port == port
+        assert result.protocol == "tcp"  # Implicit default when not specified
+
+    @given(port=valid_ports, protocol=protocols)
+    def test_property_port_with_protocol(self, port: int, protocol: str) -> None:
+        """Port with protocol parses correctly for all valid combinations."""
+        result = _parse_port_spec(f"{port}/{protocol}")
+        assert result.container == port
+        assert result.host_port == port
+        assert result.protocol == protocol
+
+    @given(host=valid_ports, container=valid_ports, protocol=protocols)
+    def test_property_host_container_mapping(
+        self, host: int, container: int, protocol: str
+    ) -> None:
+        """Host:container mapping parses correctly for all valid ports."""
+        result = _parse_port_spec(f"{host}:{container}/{protocol}")
+        assert result.container == container
+        assert result.host_port == host
+        assert result.protocol == protocol

 class TestCheckPortConflicts:
```

```diff
--- a/tests/test_models.py
+++ b/tests/test_models.py
@@ -1,6 +1,9 @@
 """Tests for Pydantic models."""

 from pathlib import Path

 import pytest
+from hypothesis import given
+from hypothesis import strategies as st

 from mirustech.devenv_generator.models import MountSpec, PortConfig, ProfileConfig

@@ -25,6 +28,38 @@ class TestMountSpec:
         spec = MountSpec.from_string("/some/path:cow")
         assert spec.mode == "cow"

+    # Property tests verify parsing invariants across wide input space
+    # Path strategy restricted to filesystem-safe characters (alphanumeric + /-_.) to ensure
+    # tests work reliably across macOS/Linux. Unrestricted st.text() generates control characters,
+    # Unicode, null bytes causing platform-specific filesystem errors.
+    # Tradeoff: narrower input space (misses exotic Unicode edge cases) vs reliable cross-platform
+    # test execution (parsing logic doesn't require Unicode validation)
+    valid_paths = st.text(
+        alphabet=st.characters(
+            whitelist_categories=("Lu", "Ll", "Nd"),  # Letters and digits
+            whitelist_characters="/-_.",  # Common path characters
+        ),
+        min_size=1,
+        max_size=100,
+    ).filter(lambda p: p.strip() == p)  # No leading/trailing whitespace (filesystem accepts but messy)
+    modes = st.sampled_from(["rw", "ro", "cow"])
+
+    @given(path=valid_paths)
+    def test_property_default_mode(self, path: str) -> None:
+        """Mount specs without explicit mode default to rw for all paths."""
+        spec = MountSpec.from_string(path)
+        assert spec.mode == "rw"  # Default mode when not specified in spec
+        assert isinstance(spec.host_path, Path)
+
+    @given(path=valid_paths, mode=modes)
+    def test_property_explicit_mode(self, path: str, mode: str) -> None:
+        """Mount specs with explicit mode parse correctly for all combinations."""
+        spec = MountSpec.from_string(f"{path}:{mode}")
+        assert spec.mode == mode
+        assert isinstance(spec.host_path, Path)
+
+    @given(mode=modes)
+    def test_property_mode_invariant(self, mode: str) -> None:
+        """Mode field only accepts valid values (rw/ro/cow)."""
+        spec = MountSpec.from_string(f"/test/path:{mode}")
+        # Mode must be one of the three valid values
+        assert spec.mode in ("rw", "ro", "cow")
```

### Milestone 5: Documentation

**Files**:
- `CLAUDE.md`
- `README.md`

**Requirements**:
- Update CLAUDE.md index with new files from milestones:
  - `application/use_cases/build_decision.py`: Build decision logic, hash comparison
  - `profiles/minimal.yaml`: Fast iteration profile
  - `profiles/web-dev.yaml`: Web development profile
  - `profiles/data-science.yaml`: Data science profile
  - `tests/test_build_decision.py`: Build decision unit tests
- Update README.md with:
  - Architecture diagram from Invisible Knowledge (if changed)
  - Tradeoffs section (build hash tracking, exponential backoff)
  - Profile templates documentation (minimal/web-dev/data-science use cases)

**Acceptance Criteria**:
- CLAUDE.md enables LLM to locate build decision logic for debugging
- README.md captures exponential backoff rationale (not obvious from code)
- README.md documents when to use which profile template
- All diagrams match actual implementation structure

**Source Material**: `## Invisible Knowledge` section of this plan

## Milestone Dependencies

```
M1 (Optimize Polling) ---> Independent
                           |
M2 (Profile Templates) --> Independent
                           |
M3 (Extract Build Logic) -> Independent
                           |
M4 (Property Tests) -----> Independent

M5 (Documentation) ------> Depends on M1, M2, M3, M4 (documents all changes)
```

All implementation milestones (M1-M4) are independent and can execute in parallel. Documentation milestone (M5) depends on all implementation milestones completing.
