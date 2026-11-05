## Summary & User Benefit

<!-- Briefly describe the change and why it is valuable to developers. -->

## Changes Made

<!-- Bullet points summarizing code, documentation, or test modifications. -->

## Verification & Test Results

<!-- List commands executed locally and attach test output summary. -->
- [ ] `pytest` passed (all tests green)
- [ ] `ruff check .` passed (0 errors)
- [ ] `ruff format --check .` passed (clean formatting)
- [ ] `mypy src` passed (strict type safety)
- [ ] Built wheel and verified clean install (`python scripts/validate_install.py`)

## Privacy, Security & Compatibility Checklist

- [ ] **Zero Telemetry**: No outbound network requests or background tracking added.
- [ ] **Selective Staging**: Git operations affect only problem-owned files.
- [ ] **Path Safety**: Filesystem operations use `safe_path()` without directory traversal.
- [ ] **State Integrity**: Schema changes include migration handling and tests.
- [ ] **Documentation**: `README.md`, `docs/`, or CLI `--help` updated where applicable.
