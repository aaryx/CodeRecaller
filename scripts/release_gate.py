#!/usr/bin/env python3
"""Unified Automated Release Gate for CodeRecaller.

Runs the complete pre-release verification pipeline:
1. Git working tree cleanliness check
2. Version consistency across code, pyproject, and CHANGELOG
3. Ruff lint check
4. Ruff formatting check
5. Mypy strict type check
6. Pytest regression test suite
7. pip-audit dependency security scan
8. Hatchling build (sdist and wheel)
9. Clean-environment installation and CLI acceptance test
"""

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_step(
    name: str, cmd: list[str], cwd: Path = ROOT, capture: bool = True
) -> tuple[bool, str, float]:
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture,
            text=True,
            check=False,
            timeout=300,
        )
        duration = time.perf_counter() - start
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, output, duration
    except Exception as exc:
        duration = time.perf_counter() - start
        return False, str(exc), duration


def check_version_consistency() -> tuple[bool, str]:
    init_path = ROOT / "src" / "coderecall" / "__init__.py"
    if not init_path.exists():
        return False, f"Missing {init_path}"

    match = re.search(
        r'__version__\s*=\s*["\']([^"\']+)["\']', init_path.read_text(encoding="utf-8")
    )
    if not match:
        return False, "Could not extract __version__ from src/coderecall/__init__.py"

    version = match.group(1)

    changelog_path = ROOT / "CHANGELOG.md"
    if not changelog_path.exists():
        return False, "Missing CHANGELOG.md"

    changelog_content = changelog_path.read_text(encoding="utf-8")
    if f"[{version}]" not in changelog_content:
        return False, f"Version {version} not found in CHANGELOG.md (expected '## [{version}]')"

    pyproject_path = ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        return False, "Missing pyproject.toml"

    pyproject_content = pyproject_path.read_text(encoding="utf-8")
    if 'path = "src/coderecall/__init__.py"' not in pyproject_content:
        return (
            False,
            "pyproject.toml does not point to src/coderecall/__init__.py for dynamic version",
        )

    return True, f"Consistent across __init__.py, pyproject.toml, and CHANGELOG.md ({version})"


def main() -> int:
    parser = argparse.ArgumentParser(description="CodeRecaller Release Gate")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow uncommitted git changes")
    parser.add_argument(
        "--offline", action="store_true", help="Skip network-dependent checks (pip-audit)"
    )
    parser.add_argument(
        "--skip-install-test", action="store_true", help="Skip clean-venv install test"
    )
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest test suite")
    args = parser.parse_args()

    python = sys.executable
    print("=" * 70)
    print(" CODERECALLER AUTOMATED RELEASE GATE")
    print("=" * 70)

    steps: list[tuple[str, bool, str, float]] = []

    # 1. Git cleanliness
    if not args.allow_dirty:
        ok, out, dur = run_step("Git Cleanliness", ["git", "status", "--porcelain"])
        if ok and out.strip():
            steps.append(
                (
                    "Git Cleanliness",
                    False,
                    f"Working tree has uncommitted changes:\n{out.strip()}",
                    dur,
                )
            )
        elif not ok:
            steps.append(("Git Cleanliness", False, out.strip(), dur))
        else:
            steps.append(("Git Cleanliness", True, "Working tree is clean", dur))
    else:
        steps.append(("Git Cleanliness", True, "Skipped (--allow-dirty)", 0.0))

    # 2. Version consistency
    v_ok, v_msg = check_version_consistency()
    steps.append(("Version Consistency", v_ok, v_msg, 0.01))

    # 3. Ruff lint
    ok, out, dur = run_step("Ruff Lint", [python, "-m", "ruff", "check", "."])
    steps.append(("Ruff Lint", ok, "0 lint errors" if ok else out.strip()[:200], dur))

    # 4. Ruff format
    ok, out, dur = run_step("Ruff Format Check", [python, "-m", "ruff", "format", "--check", "."])
    steps.append(
        ("Ruff Format Check", ok, "All files properly formatted" if ok else out.strip()[:200], dur)
    )

    # 5. Mypy strict type check
    ok, out, dur = run_step("Mypy Type Check", [python, "-m", "mypy", "src"])
    steps.append(
        ("Mypy Type Check", ok, "Strict type check passed" if ok else out.strip()[:200], dur)
    )

    # 6. Pytest
    if not args.skip_tests:
        with tempfile.TemporaryDirectory(prefix="coderecall-basetemp-") as temp_base:
            ok, out, dur = run_step(
                "Pytest Test Suite",
                [python, "-m", "pytest", "-q", f"--basetemp={temp_base}"],
            )
            summary = out.strip().splitlines()[-1] if out.strip() else ""
            steps.append(("Pytest Test Suite", ok, summary if ok else out.strip()[-300:], dur))
    else:
        steps.append(("Pytest Test Suite", True, "Skipped (--skip-tests)", 0.0))

    # 7. pip-audit
    if not args.offline:
        ok, out, dur = run_step("Dependency Audit", [python, "-m", "pip_audit", "--skip-editable"])
        steps.append(
            ("Dependency Audit", ok, "Zero known vulnerabilities" if ok else out.strip()[:200], dur)
        )
    else:
        steps.append(("Dependency Audit", True, "Skipped (--offline)", 0.0))

    # 8. Build package
    ok, out, dur = run_step("Package Build", [python, "-m", "build", "--no-isolation"])
    steps.append(
        (
            "Package Build",
            ok,
            "Wheel and sdist built successfully" if ok else out.strip()[:200],
            dur,
        )
    )

    # 9. Clean-environment install
    if not args.skip_install_test:
        validate_script = ROOT / "scripts" / "validate_install.py"
        ok, out, dur = run_step("Clean Install Validation", [python, str(validate_script)])
        steps.append(
            (
                "Clean Install Validation",
                ok,
                "Fresh venv wheel install & CLI passed" if ok else out.strip()[:200],
                dur,
            )
        )
    else:
        steps.append(("Clean Install Validation", True, "Skipped (--skip-install-test)", 0.0))

    print()
    all_passed = True
    for name, success, detail, duration in steps:
        status_str = "[ PASS ]" if success else "[ FAIL ]"
        dur_str = f"({duration:.2f}s)" if duration > 0.05 else ""
        print(f" {status_str} {name:<26} {dur_str:<9} {detail}")
        if not success:
            all_passed = False

    print("=" * 70)
    if all_passed:
        print(" RESULT: ALL RELEASE GATES PASSED - READY FOR RELEASE TAGGING")
        print("=" * 70)
        return 0
    else:
        print(" RESULT: RELEASE GATE FAILED - REMEDIATION REQUIRED")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
