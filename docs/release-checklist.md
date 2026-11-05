# CodeRecaller Release Checklist

This checklist must be executed and verified before tagging and publishing any release of CodeRecaller.

---

## 1. Automated Release Gate

Run the automated verification script:

```bash
python scripts/release_gate.py
```

Verify that all gates pass:
- [ ] **Git Working Tree**: Clean working tree with no uncommitted or untracked changes (`git status --porcelain` is empty).
- [ ] **Version Consistency**: Version matches across:
  - `src/coderecall/__init__.py` (`__version__ = "X.Y.Z"`)
  - `pyproject.toml` (dynamic version points to `src/coderecall/__init__.py`)
  - `CHANGELOG.md` (section `## [X.Y.Z] - YYYY-MM-DD` exists)
- [ ] **Code Quality & Linting**: `ruff check .` passes with 0 errors.
- [ ] **Code Formatting**: `ruff format --check .` passes (all files formatted).
- [ ] **Static Type Safety**: `mypy src` passes in strict mode.
- [ ] **Regression Test Suite**: `pytest` passes all test cases (0 failures).
- [ ] **Dependency Security**: `pip-audit --skip-editable` reports 0 known vulnerabilities.
- [ ] **Package Build**: `python -m build --no-isolation` successfully builds wheel (`.whl`) and source distribution (`.tar.gz`).
- [ ] **Clean Installation Validation**: `python scripts/validate_install.py` installs the built wheel in an isolated temporary virtual environment and executes the CLI lifecycle.

---

## 2. Platform & CI Verification

- [ ] **GitHub Actions Matrix**: Latest commit on `main` has a passing CI run (`https://github.com/aaryx/CodeRecaller/actions`).
  - Ubuntu (Python 3.11, 3.12, 3.13)
  - macOS (Python 3.11, 3.12, 3.13)
  - Windows (Python 3.11, 3.12, 3.13)
  - Live Docker container sandbox test on Ubuntu runner passed (`coderecall run`).
  - Dependency audit job (`pip-audit`) passed.

---

## 3. Documentation & Release Notes

- [ ] `README.md` reflects current CLI commands, options, and supported Python versions.
- [ ] `CHANGELOG.md` accurately documents `Added`, `Changed`, `Fixed`, and `Security` items.
- [ ] `docs/product/first-time-user-review.md` and `docs/product/roadmap.md` are up to date.
- [ ] No temporary files or test credentials exist in the distribution packages.

---

## 4. Tagging & Publication

Follow the complete step-by-step instructions in [RELEASING.md](../RELEASING.md):

```bash
# 1. Create annotated tag
git tag -a v0.3.0 -m "Release v0.3.0"

# 2. Push tag
git push origin v0.3.0

# 3. Publish GitHub Release with attached dist artifacts and SHA256 checksums
```

> [!CAUTION]
> Do not publish packages to PyPI or create public releases without explicit authorization and verified release credentials.
