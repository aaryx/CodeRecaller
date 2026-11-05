# Contributing to CodeRecaller

Thank you for your interest in contributing to CodeRecaller!

CodeRecaller is an open-source, local-first Python tool designed to help developers master coding patterns through active recall, spaced repetition (FSRS), and Git-native solution tracking.

We welcome bug fixes, documentation improvements, test coverage enhancements, and feature proposals that respect our **local-first, privacy-by-default, and zero-telemetry** principles.

---

## 1. Code of Conduct

All contributors and participants are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md). Please treat everyone with respect and empathy.

---

## 2. Development Setup

### Prerequisites
- **Python**: 3.11, 3.12, 3.13, or 3.14
- **Git**: 2.30+
- **Docker**: (Optional) Only needed if developing or testing container sandbox features.

### Step-by-Step Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/CodeRecaller.git
   cd CodeRecaller
   ```

2. **Create and activate a virtual environment:**
   - **Linux / macOS:**
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
   - **Windows (PowerShell):**
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - **Windows (Command Prompt):**
     ```cmd
     python -m venv .venv
     .\.venv\Scripts\activate.bat
     ```

3. **Install development dependencies in editable mode:**
   ```bash
   pip install --upgrade pip
   pip install -e ".[dev]"
   ```

4. **Verify the installation:**
   ```bash
   coderecall version
   ```

---

## 3. Running Quality Checks & Tests

CodeRecaller enforces strict linting, formatting, type checking, and test coverage. All checks must pass before pull requests can be merged.

### Automated Test Suite
```bash
pytest
```
*Note: Tests use temporary isolated projects and git repositories. No GitHub credentials or network access are required for the test suite. On Windows accounts without Developer Mode enabled, a symlink test may be safely skipped.*

### Linting and Code Style
We use [Ruff](https://astral.sh/ruff) for fast linting and formatting:
```bash
# Check code style and rules
ruff check .

# Check code formatting
ruff format --check .

# Automatically apply safe fixes and formatting
ruff check --fix .
ruff format .
```

### Static Type Checking
We enforce strict typing with [Mypy](https://mypy.readthedocs.io/):
```bash
mypy src
```

### Clean Packaging & Installation Validation
Verify that wheel and sdist builds succeed reproducibly and install into a clean temporary environment:
```bash
# Build wheel and sdist without isolation
python -m build --no-isolation

# Run isolated clean-environment acceptance test
python scripts/validate_install.py
```

### Dependency Vulnerability Audit
```bash
pip-audit --skip-editable
```

---

## 4. Architecture & Design Principles

Before modifying code, please review [architecture.md](architecture.md) and [SECURITY.md](SECURITY.md).

CodeRecaller follows a strict layered architecture:
- `src/coderecall/domain/`: Pure domain models, mathematical schedulers (FSRS), validation constraints, clock, and error types. Zero external dependencies.
- `src/coderecall/storage/`: Atomic file replacement, write-ahead transaction journaling (`transaction.json`), OS file locking (`msvcrt`/`fcntl`), and codecs.
- `src/coderecall/execution/`: Sandboxed Docker container runner and execution protocols.
- `src/coderecall/integrations/`: Git operations, secret scanner, process runners, and optional adapters.
- `src/coderecall/application/`: Service orchestrators, catalog management, recall sessions, and backup managers.
- `src/coderecall/cli/`: Typer command definitions, argument parsing, and Rich terminal presentation.

### Invariant Rules
1. **Dependencies flow inward:** Domain models must never import from storage, integrations, application, or CLI layers.
2. **Local-first privacy:** Never introduce outbound network calls, analytics, background telemetry, or cloud dependencies into standard workflows.
3. **Selective Git staging:** Git commits must stage **only** problem-owned files. Unrelated user files in the workspace must never be touched.
4. **Secret scanning:** Commits must pass secret regex scanning before staging occurs.
5. **State durability:** Multi-file state modifications must use the two-phase transaction journal (`transaction.json`) with roll-forward recovery.
6. **Cross-platform compatibility:** Always use `safe_path()` for filesystem paths; reject Windows drive letters (`C:`), UNC paths, and directory traversal (`..`).

---

## 5. Commit & Pull Request Guidelines

### Commit Message Conventions
We follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat(scope): add new feature`
- `fix(scope): fix bug or regression`
- `docs(scope): update documentation`
- `test(scope): add or improve tests`
- `refactor(scope): internal refactoring with no behavior change`
- `perf(scope): performance optimization`
- `chore(scope): maintenance, build, or tooling updates`

### Pull Request Process
1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Write clean, focused code with regression tests covering new behavior or bug fixes.
3. Run the full verification suite (`ruff`, `mypy`, `pytest`).
4. Update relevant documentation in `docs/` and `README.md` if public commands or options change.
5. Push to your fork and submit a Pull Request against `main`.
6. Ensure the GitHub Actions CI matrix passes completely across all operating systems.

---

## 6. Security Vulnerability Disclosures

If you discover a security vulnerability, please do **NOT** open a public issue. Follow our responsible disclosure guidelines in [SECURITY.md](SECURITY.md) and report it via [GitHub Private Vulnerability Reporting](https://github.com/aaryx/CodeRecaller/security/advisories/new).
