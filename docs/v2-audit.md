# CodeRecall V2 Audit

## 1. Existing Architecture
CodeRecall follows a clean, decoupled local-first architecture. 
- **CLI (`src/coderecall/cli`)**: Handles arguments, prompts, terminal presentation (Typer/Rich) and provides a JSON boundary for machine-readability.
- **Application (`src/coderecall/application`)**: Coordinates use cases (project, catalog, recall, importer).
- **Domain (`src/coderecall/domain`)**: Contains pure business logic, typed records (models), strict validation, analytics computations, and an injectable clock interface.
- **Revision (`src/coderecall/revision`)**: Owns the deterministic spaced-repetition scheduling algorithm.
- **Storage (`src/coderecall/storage`)**: Implements atomic local persistence (`state.json`), configuration (`config.toml`), file locks, journal-based recovery transactions, and backup routines.
- **Integrations (`src/coderecall/integrations`)**: External adapters for Git, GitHub, LeetCode (metadata), OpenAI, and plugins.
- **Execution (`src/coderecall/execution`)**: Optional restricted Linux Docker runner.

## 2. Existing Commands
The CLI features a robust hierarchy routing through Typer:
- **Global**: `--json`, `--quiet`, `--verbose`, `--no-color`, `--non-interactive`, `--dry-run`
- **Catalog**: `init`, `add`, `problems`, `problem`, `search`, `edit`, `import`, `note`, `mistake`, `archive`, `random`, `analyze`
- **Learning**: `today`, `revise`, `solve`, `interview`, `recall submit`, `recall hint`, `recall pause/resume`, `recall compare`, `recall cancel`, `recall capture`, `schedule`, `session`, `stats`, `topics`, `streak`, `summary`, `achievements`, `curve`
- **Goals**: `goal add`, `goal list`, `goal remove`
- **Management**: `status`, `doctor`, `config`, `git status|diff|commit|push`, `sync`, `github`, `backup`, `restore`, `export`, `ai`, `run`

## 3. Existing Models
Defined in `domain/models.py` as Python dataclasses:
- `State`, `Problem`, `Solution`, `Schedule`, `Review`, `Mistake`, `Activity`, `Session`, `Recall`, `Goal`, `Achievement`.
Fields represent a robust, versioned schema ensuring strict validation of problem metadata, solutions, analytics activity, and gamification state.

## 4. Existing Persistence Format
- Uses a single, atomic `state.json` (max 64 MiB limit) inside the ignored `.coderecall/` directory.
- `transaction.json` maintains a roll-forward transaction journal for safe generated-file/state updates.
- Uses OS-level file locking to prevent concurrent modifications.
- Strict codec checks enforce schema integrity, with built-in capability to transparently migrate older valid schemas.

## 5. Existing Scheduler
- Currently uses an FSRS-inspired scheduler (Free Spaced Repetition Scheduler v4).
- Maintains difficulty, stability, and retrievability per problem.
- Provides fallback to the original SM2-inspired simple interval scheduler.

## 6. Existing Git Functionality
- `LocalGitProvider` passes array arguments to the host Git executable.
- Never rewrites history, forces pushes, or stashes.
- Integrates commit logic strictly for owned `.coderecall/` assets.
- Checks outgoing commits for potential secrets.
- Supports fetch, branch synchronization, and Git/GitHub CLI integration.

## 7. Existing Runner
- Implemented as an optional, explicitly enabled Linux Docker sandbox (`python:3.12-alpine`).
- Enforces strict security: no network, no host mounts, read-only root, max memory constraints (128M), and CPU limits.
- Currently restricted to Python scripts.

## 8. Existing Analytics
- Extensive local analytics computed in `domain/analytics.py`.
- Features include: streaks, difficulty distribution, forgetting curves, time-of-day peak performance, learning velocity, and weakness detection.
- Topics are tracked with recall percentages.
- A fully local gamification system (goals and achievements) is present.

## 9. Reusable Components
- **CLI Outputs (`output.py`)**: Abstracted terminal output handling for emitting text or JSON dynamically.
- **Clock Protocol (`clock.py`)**: Fully deterministic, testable time injection.
- **Validation module (`validation.py`)**: Extensive file paths and language string validations.
- **Process execution (`process.py`)**: Safely spawns subprocesses with proper escaping and error boundaries.

## 10. Missing Functionality (per V2 Spec)
- **Advanced TUI / Dashboard**: A polished `coderecall dashboard` with a unified view of streaks, due items, and performance.
- **Multi-language Sandbox**: The runner is currently Python-only. Support for Java, C++, JS/Node, Go, and Rust needs to be abstracted into a protocol (e.g., `LanguageRunner`).
- **Test Case Engine**: Structured visible/hidden test cases and test execution assertions.
- **Advanced Git Intelligence**: Missing deep historical commands (`git analyze`, `git history`, `git evolution`).
- **Professional CLI Polish**: Need to consolidate some commands into a polished interface.

## 11. Architectural Risks
- **JSON Size Limits**: The 64 MiB limit and linear O(n) read/write will degrade performance if the user catalog grows massively.
- **Domain logic bleed**: While currently clean, as the TUI becomes richer, there's a risk of entangling UI presentation with domain models.
- **Sandbox Extensibility**: Moving from 1 language to 6 requires a generic `LanguageRunner` interface, risking Docker configuration drift or security regressions.

## 12. Compatibility Risks
- State JSON migration needs to remain robust. Introducing new test cases or language structures requires careful schema extension without breaking old files.
- Modifying Git synchronization logic to support deeper analysis risks breaking existing tracked states.

## 13. Security Risks
- **Sandbox Expansion**: Adding compiled languages (C++, Rust) or dynamic languages (JS) requires verifying compiler limits, timeout handling, and file system isolation constraints in Docker.
- **Git Analytics**: Parsing arbitrary git diffs and commit messages could introduce injection vulnerabilities if not strictly sanitized in the TUI/CLI output.

## 14. Proposed Extension Points
- **LanguageRunner Protocol**: Abstract the `DockerRunner` to load specific `LanguageDefinition` configs (compilation steps, entrypoints, timeouts).
- **GitAnalyzer**: Create a domain service for deep Git history inspection, isolated from the execution wrapper.
- **Test Case Model**: Extend the `Problem` model to track test case metadata and extend the `ExecutionResult` to report structured test success/failures.
- **Rich Dashboard Component**: Add a dedicated dashboard presenter in `cli` utilizing Rich layout features, completely separated from core application logic.

## V2 Implementation Plan

### Phase 1: Professional CLI & Dashboard (TUI)
- **Files to Modify**: `src/coderecall/cli/__init__.py`, `src/coderecall/cli/learning.py`, `src/coderecall/cli/output.py`
- **Files to Create**: `src/coderecall/cli/dashboard.py`
- **Task**: Create `coderecall dashboard` with Rich layout. Ensure fallback and `--json` support. Refine command UX.

### Phase 2: Test Case Engine & Execution Result Model
- **Files to Modify**: `src/coderecall/domain/models.py`, `src/coderecall/storage/codec.py`, `src/coderecall/execution/runner.py`
- **Data Model Changes**: Add `TestMetadata` and `ExecutionResult` types to domain records.
- **Task**: Define `ExecutionResult` and structured test models. Extend JSON codec with backward compatibility.

### Phase 3: Multi-language Secure Sandbox
- **Files to Modify**: `src/coderecall/execution/docker.py`
- **Files to Create**: `src/coderecall/execution/languages.py`
- **Task**: Implement `LanguageDefinition` protocol. Add Docker profiles for Java, C++, JS, Go, Rust. Hardcode security boundaries (no net, read-only, limited RAM). Add sandbox integration tests.

### Phase 4: Advanced Git Intelligence
- **Files to Modify**: `src/coderecall/integrations/git.py`
- **Files to Create**: `src/coderecall/application/git_analytics.py`, `src/coderecall/cli/git.py`
- **Task**: Implement `git history`, `git analyze`, and `git evolution`. Safely parse `git log` and `git diff` outputs.

### Phase 5: Final Polish & Testing
- **Task**: Write security and property-based tests for the sandbox and Git history parsers. Update documentation (`docs/sandbox.md`, `docs/git-intelligence.md`, `docs/v2-architecture.md`). Verify 100% CLI/local-first integrity.

## Migration Strategy
- `codec.py` handles reading existing `state.json`. All new fields will be provided with explicit default values and migrated on-the-fly during parsing without failing on older versions.
- If data structure re-arrangement is necessary, we increment the `schema_version` and provide explicit upgrade logic that translates V1 `Problem` fields to V2 shapes.
- Unknown fields will be strictly logged/handled rather than silently discarded.

## Test Strategy
- **Security Testing**: Verify Git argument escaping against malicious branch names/messages. Verify sandbox constraints (no network, limited RAM).
- **Property-based Testing**: Ensure serialization/deserialization of existing state holds true under all conditions.
- **Integration Testing**: Spin up isolated Docker containers to test Python, Java, C++, JS, Go, Rust code execution correctness.
- **Unit Testing**: 100% logic coverage on Analytics, Weakness Detection, and Git parsing.
