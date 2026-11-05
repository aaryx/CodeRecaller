# CodeRecaller Release Guide & Checklist

This document outlines the reproducible release process for CodeRecaller maintainers.

---

## 1. Pre-Release Quality Gate

Before tagging any candidate release, ensure the codebase satisfies all automated quality gates:

```bash
# 1. Run the unified automated release gate
python scripts/release_gate.py
```

The release gate verifies:
- [x] Working tree is clean and up to date with `main`.
- [x] Version consistency between `src/coderecall/__init__.py`, `pyproject.toml`, and `CHANGELOG.md`.
- [x] Ruff lint checks pass (`ruff check .` = 0 errors).
- [x] Ruff formatting is clean (`ruff format --check .`).
- [x] Mypy strict type checking passes (`mypy src`).
- [x] Pytest regression test suite passes completely.
- [x] Dependency vulnerability audit passes (`pip-audit --skip-editable`).
- [x] Wheel and source distribution build successfully without isolation.
- [x] Clean-environment installation and CLI acceptance test passes (`scripts/validate_install.py`).
- [x] GitHub Actions CI matrix on `main` is 100% green.

---

## 2. Version Bumping & Changelog

1. Ensure the target version follows [Semantic Versioning](https://semver.org/):
   - `MAJOR` for breaking state schema or incompatible CLI contract changes.
   - `MINOR` for backwards-compatible features (e.g. new export formats, new schedulers).
   - `PATCH` for backwards-compatible bug fixes and security hardening.

2. Verify version string in `src/coderecall/__init__.py`:
   ```python
   __version__ = "0.3.0"
   ```

3. Update `CHANGELOG.md`:
   - Promote `## [Unreleased]` changes to `## [X.Y.Z] - YYYY-MM-DD`.
   - Ensure sections follow Keep a Changelog (`Added`, `Changed`, `Fixed`, `Security`).

4. Commit the release preparation:
   ```bash
   git add src/coderecall/__init__.py CHANGELOG.md
   git commit -m "chore(release): prepare v0.3.0 release"
   git push origin main
   ```

---

## 3. Git Tagging

Once the commit is on `main` and GitHub Actions CI has passed:

```bash
# Create an annotated signed tag (or standard annotated tag)
git tag -a v0.3.0 -m "Release v0.3.0: FSRS v4, terminal resilience, secret scanner, and multi-format export"

# Push tag to GitHub remote
git push origin v0.3.0
```

---

## 4. Build Artifacts

Build fresh, reproducible distribution packages from the tagged release commit:

```bash
# Remove prior build artifacts
rm -rf dist/ build/ *.egg-info

# Build sdist and wheel
python -m build --no-isolation

# Generate SHA-256 checksums
# Linux/macOS:
sha256sum dist/* > dist/SHA256SUMS.txt
# Windows PowerShell:
# Get-FileHash dist/* -Algorithm SHA256 | ForEach-Object { "$($_.Hash.ToLower())  $($_.Path | Split-Path -Leaf)" } | Out-File dist/SHA256SUMS.txt -Encoding utf8
```

---

## 5. GitHub Release Creation

1. Open [CodeRecaller Releases](https://github.com/aaryx/CodeRecaller/releases/new).
2. Select tag `v0.3.0`.
3. Set Release Title: `CodeRecaller v0.3.0: Spaced Repetition, Active Recall & Git Solution Tracking`.
4. Paste release notes from `CHANGELOG.md`.
5. Attach the distribution artifacts:
   - `coderecall-0.3.0-py3-none-any.whl`
   - `coderecall-0.3.0.tar.gz`
   - `SHA256SUMS.txt`
6. Publish the release.

---

## 6. PyPI Publication (Authorized Maintainers Only)

Publishing to PyPI must use trusted publishing (OIDC) or Twine with API tokens. Never hardcode credentials.

```bash
# Validate distribution metadata
twine check dist/*

# Upload to PyPI
twine upload dist/*
```

---

## 7. Post-Release Verification

Verify that the published release can be installed cleanly by end users:

```bash
# Test pipx installation
pipx install coderecall --force

# Verify CLI version and diagnostics
coderecall --version
coderecall doctor

# Uninstall test
pipx uninstall coderecall
```
