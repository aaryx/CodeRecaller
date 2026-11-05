#!/usr/bin/env python3
"""First-Time User Journey & Usability Audit for CodeRecaller.

Tests the full onboarding workflow in a clean isolated virtual environment
outside the repository, exactly following the README instructions:
1. coderecall --version & --help
2. coderecall init
3. coderecall add
4. coderecall problems, search, problem
5. coderecall revise
6. coderecall recall submit
7. coderecall today, stats, dashboard
8. coderecall backup & restore --check-only
9. coderecall restore into a separate workspace
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_process(
    cmd: list[str], cwd: Path, env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def main() -> int:
    print("=" * 70)
    print(" CODERECALLER FIRST-TIME USER JOURNEY AUDIT")
    print("=" * 70)

    # 1. Locate wheel
    wheels = list((ROOT / "dist").glob("coderecall-*-py3-none-any.whl"))
    if not wheels:
        print("[FAIL] No wheel found in dist/. Run python -m build first.")
        return 1
    wheel_path = sorted(wheels)[-1]
    print(f"[*] Target wheel: {wheel_path.name}")

    # 2. Setup isolated venv outside the repo
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="cr-user-journey-")
    temp_root = Path(temp_dir_obj.name)
    env_dir = temp_root / "venv"
    print(f"[*] Creating isolated virtual environment at {env_dir}...")
    venv.EnvBuilder(with_pip=True).create(env_dir)

    bindir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    python_exe = bindir / ("python.exe" if os.name == "nt" else "python")
    cli_exe = bindir / ("coderecall.exe" if os.name == "nt" else "coderecall")

    print("[*] Installing wheel into clean virtual environment...")
    install_ret, install_out, install_err = run_process(
        [str(python_exe), "-m", "pip", "install", str(wheel_path)],
        cwd=temp_root,
    )
    if install_ret != 0:
        print(f"[FAIL] Pip install failed (exit {install_ret}):\n{install_err}\n{install_out}")
        return 1
    print("[PASS] Wheel installed cleanly.")

    # Determine command invocation (use coderecall launcher if permitted, else python -m coderecall)
    cli_cmd = [str(python_exe), "-m", "coderecall"]
    try:
        test_ret, test_out, _ = run_process([str(cli_exe), "--version"], cwd=temp_root)
        if test_ret == 0:
            cli_cmd = [str(cli_exe)]
            print(f"[PASS] Console launcher '{cli_exe.name}' verified.")
    except OSError as exc:
        if getattr(exc, "winerror", None) == 4551:
            print(
                "[*] Console launcher execution restricted in temp by Windows App Control (4551); using python -m coderecall."
            )
        else:
            raise

    # Prepare disposable practice workspace
    practice_dir = temp_root / "my-practice"
    practice_dir.mkdir()

    observations: list[dict[str, object]] = []

    def record_step(
        step_name: str, cmd_args: list[str], expected_exit: int = 0, input_text: str = ""
    ):
        full_cmd = [*cli_cmd, *cmd_args]
        start_time = time.perf_counter()
        proc = subprocess.run(
            full_cmd,
            cwd=practice_dir,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=30,
        )
        duration = time.perf_counter() - start_time
        passed = proc.returncode == expected_exit
        status = "PASS" if passed else "FAIL"
        print(f" [{status}] {step_name:<36} exit={proc.returncode} ({duration:.2f}s)")
        obs = {
            "step": step_name,
            "cmd": " ".join(cmd_args),
            "exit_code": proc.returncode,
            "expected_exit": expected_exit,
            "passed": passed,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "duration": round(duration, 3),
        }
        observations.append(obs)
        if not passed:
            print(f"       ERROR STDOUT: {proc.stdout.strip()[:200]}")
            print(f"       ERROR STDERR: {proc.stderr.strip()[:200]}")
        return obs

    print("\n--- Phase 1: Exploration & Help ---")
    record_step("1.1 Check Version", ["--version"])
    record_step("1.2 Root Help", ["--help"])
    record_step("1.3 Doctor (Uninitialized)", ["doctor"], expected_exit=9)

    print("\n--- Phase 2: Workspace Initialization ---")
    # Initialize git repo first as recommended by quickstart
    run_process(["git", "init"], cwd=practice_dir)
    record_step("2.1 Initialize Workspace", ["init", "--yes"])
    record_step("2.2 Doctor (Initialized)", ["doctor"], expected_exit=0)

    print("\n--- Phase 3: Solution Capture ---")
    sol_file = practice_dir / "two_sum.py"
    sol_file.write_text(
        "def twoSum(nums, target):\n"
        "    seen = {}\n"
        "    for i, num in enumerate(nums):\n"
        "        diff = target - num\n"
        "        if diff in seen:\n"
        "            return [seen[diff], i]\n"
        "        seen[num] = i\n"
        "    return []\n",
        encoding="utf-8",
    )
    record_step(
        "3.1 Add First Solution",
        [
            "add",
            "--file",
            "two_sum.py",
            "--title",
            "Two Sum",
            "--external-id",
            "1",
            "--platform",
            "leetcode",
            "--topics",
            "array,hash-table",
            "--no-commit",
        ],
    )

    print("\n--- Phase 4: Discovery & Inspection ---")
    record_step("4.1 Problems List", ["problems"])
    record_step("4.2 Search by Title", ["search", "Two Sum"])
    record_step("4.3 Search by Topic", ["search", "hash-table"])
    record_step("4.4 Problem Details", ["problem", "1"])
    record_step("4.5 Status Overview", ["status"])

    # Semantic Assertion 1: Stored problem and solution match sample input
    prob_inspect_ret, prob_inspect_out, _ = run_process(
        [*cli_cmd, "--json", "problem", "1"], cwd=practice_dir
    )
    if prob_inspect_ret != 0:
        raise RuntimeError(f"Problem inspection failed: {prob_inspect_out}")
    p_info = json.loads(prob_inspect_out)
    prob_obj = p_info["problem"]
    if prob_obj["title"] != "Two Sum":
        raise RuntimeError(f"Expected 'Two Sum', got {prob_obj['title']}")
    if prob_obj["external_id"] != "1":
        raise RuntimeError(f"Expected external_id '1', got {prob_obj['external_id']}")
    if "array" not in prob_obj["topics"] or "hash-table" not in prob_obj["topics"]:
        raise RuntimeError(f"Topics mismatch: {prob_obj['topics']}")
    if len(prob_obj["solutions"]) < 1:
        raise RuntimeError("Expected at least 1 solution in catalog")
    canonical_sol_file = practice_dir / prob_obj["solutions"][0]["path"]
    if not canonical_sol_file.exists():
        raise RuntimeError(f"Stored solution path {canonical_sol_file} does not exist")
    if "seen[num] = i" not in canonical_sol_file.read_text(encoding="utf-8"):
        raise RuntimeError("Stored solution content mismatch")
    print(" [PASS] 4.6 Verified Stored Problem Metadata & Solution Match Sample Input")

    print("\n--- Phase 5: Active Recall Practice ---")
    # Non-interactive revise starts recall and outputs workspace
    revise_obs = record_step(
        "5.1 Start Active Recall", ["--non-interactive", "--json", "revise", "1"]
    )
    recall_id = ""
    workspace_rel = ""
    if revise_obs["passed"] and revise_obs["stdout"]:
        try:
            rev_data = json.loads(revise_obs["stdout"])
            recall_id = rev_data.get("recall_id", "")
            workspace_rel = rev_data.get("workspace", "")
            print(f"       recall_id: {recall_id}")
            print(f"       workspace: {workspace_rel}")
        except Exception as e:
            print(f"       Failed to parse revise JSON: {e}")

    if workspace_rel:
        ws_file = practice_dir / workspace_rel
        if ws_file.exists():
            print(f"       Workspace file exists (initial size: {ws_file.stat().st_size} bytes)")
            # Simulate candidate typing the solution in the workspace
            ws_file.write_text(
                "def twoSum(nums, target):\n"
                "    lookup = {}\n"
                "    for idx, val in enumerate(nums):\n"
                "        needed = target - val\n"
                "        if needed in lookup:\n"
                "            return [lookup[needed], idx]\n"
                "        lookup[val] = idx\n"
                "    return []\n",
                encoding="utf-8",
            )
            print("       Wrote candidate solution into workspace.")

    if recall_id:
        record_step(
            "5.2 Compare Attempt Pre-Submit (Protected)",
            ["recall", "compare", recall_id],
            expected_exit=7,
        )
        record_step(
            "5.3 Submit Recall Self-Assessment",
            [
                "recall",
                "submit",
                recall_id,
                "--result",
                "pass",
                "--confidence",
                "4",
                "--seconds",
                "85",
            ],
            expected_exit=0,
        )

        # Semantic Assertion 2 & 3: Verify learning-state transition and FSRS interval
        post_sub_ret, post_sub_out, _ = run_process(
            [*cli_cmd, "--json", "problem", "1"], cwd=practice_dir
        )
        if post_sub_ret != 0:
            raise RuntimeError(f"Post-submit inspection failed: {post_sub_out}")
        p_post = json.loads(post_sub_out)
        sched_post = p_post["schedule"]
        if sched_post["state"] != "REVIEW":
            raise RuntimeError(f"Expected state 'REVIEW', got {sched_post['state']}")
        if sched_post["successes"] < 1:
            raise RuntimeError(f"Expected successes >= 1, got {sched_post['successes']}")
        if sched_post["reps"] < 1:
            raise RuntimeError(f"Expected reps >= 1, got {sched_post['reps']}")
        if sched_post["stability"] <= 1.0:
            raise RuntimeError(f"Expected FSRS stability > 1.0, got {sched_post['stability']}")
        if sched_post["interval_days"] < 1:
            raise RuntimeError(f"Expected interval_days >= 1, got {sched_post['interval_days']}")
        if sched_post["next_review"] <= sched_post["last_review"]:
            raise RuntimeError("next_review should be scheduled after last_review")
        print(
            f" [PASS] 5.3a Verified FSRS Learning State Transition (Stability: {sched_post['stability']:.2f}, Interval: {sched_post['interval_days']}d)"
        )
        record_step(
            "5.4 Compare Attempt Post-Submit (Diff)",
            ["recall", "compare", recall_id],
            expected_exit=0,
        )
        record_step(
            "5.5 Promote Attempt to Canonical Solution",
            ["recall", "capture", recall_id, "--yes"],
            expected_exit=0,
        )

    print("\n--- Phase 6: Analytics & Review Queues ---")
    record_step("6.1 Today Queue", ["today"])
    record_step("6.2 Stats Summary", ["stats"])
    record_step("6.3 Dashboard Render", ["dashboard"])
    record_step("6.4 Topic Mastery", ["topics"])

    print("\n--- Phase 7: Backup & Verification ---")
    backup_obs = record_step("7.1 Create Backup", ["--json", "backup"])
    backup_file = ""
    if backup_obs["passed"] and backup_obs["stdout"]:
        try:
            b_data = json.loads(backup_obs["stdout"])
            backup_file = b_data.get("backup", "")
            print(f"       backup path: {backup_file}")
        except Exception as e:
            print(f"       Failed to parse backup JSON: {e}")

    if backup_file:
        record_step(
            "7.2 Verify Backup (--check-only)",
            ["restore", backup_file, "--check-only"],
        )

        print("\n--- Phase 8: Restore Into Separate Workspace ---")
        separate_practice = temp_root / "separate-practice"
        separate_practice.mkdir()
        run_process(["git", "init"], cwd=separate_practice)

        # Initialize separate workspace
        run_process([*cli_cmd, "init", "--yes"], cwd=separate_practice)

        # Restore into separate workspace
        restore_ret, restore_out, restore_err = run_process(
            [*cli_cmd, "restore", backup_file, "--yes"],
            cwd=separate_practice,
        )
        print(
            f" [{'PASS' if restore_ret == 0 else 'FAIL'}] 8.1 Restore Into Clean Workspace (exit {restore_ret})"
        )

        # Verify restored problems & learning state match backed-up state
        prob_ret, prob_out, _ = run_process(
            [*cli_cmd, "--json", "problem", "1"],
            cwd=separate_practice,
        )
        if prob_ret != 0:
            raise RuntimeError(f"Restored problem lookup failed: {prob_out}")
        restored_data = json.loads(prob_out)
        restored_prob = restored_data["problem"]
        restored_sched = restored_data["schedule"]

        if restored_prob["title"] != "Two Sum":
            raise RuntimeError("Restored problem title mismatch")
        if restored_prob["external_id"] != "1":
            raise RuntimeError("Restored external_id mismatch")
        if restored_sched["state"] != sched_post["state"]:
            raise RuntimeError("Restored schedule state mismatch")
        if restored_sched["successes"] != sched_post["successes"]:
            raise RuntimeError("Restored schedule successes mismatch")
        if abs(restored_sched["stability"] - sched_post["stability"]) >= 1e-4:
            raise RuntimeError("Restored stability mismatch")
        if restored_sched["next_review"] != sched_post["next_review"]:
            raise RuntimeError("Restored next_review mismatch")
        print(" [PASS] 8.2 Verified Restored Metadata & FSRS Learning State Match Backed-Up State")

    # Phase 9: Export
    print("\n--- Phase 9: Multi-Format Export ---")
    record_step("9.1 Export HTML", ["export", "--format", "html", "--output", "report.html"])
    record_step("9.2 Export JSON", ["export", "--format", "json", "--output", "archive.json"])
    record_step("9.3 Export CSV", ["export", "--format", "csv", "--output", "metrics.csv"])
    record_step("9.4 Export Markdown", ["export", "--format", "markdown", "--output", "report.md"])

    # Semantic Assertion 5: Verify exports contain expected sample records
    exp_json = practice_dir / "archive.json"
    exp_html = practice_dir / "report.html"
    exp_csv = practice_dir / "metrics.csv"
    exp_md = practice_dir / "report.md"

    if not exp_json.exists():
        raise RuntimeError("JSON export file missing")
    json_export_data = json.loads(exp_json.read_text(encoding="utf-8"))
    if not any("Two Sum" in str(item) for item in json_export_data.values()):
        raise RuntimeError("JSON export missing 'Two Sum' record")

    if not exp_html.exists():
        raise RuntimeError("HTML export file missing")
    html_content = exp_html.read_text(encoding="utf-8")
    if "<!DOCTYPE html>" not in html_content or "Two Sum" not in html_content:
        raise RuntimeError("HTML export missing doctype or record")

    if not exp_csv.exists():
        raise RuntimeError("CSV export file missing")
    csv_content = exp_csv.read_text(encoding="utf-8")
    if "Two Sum" not in csv_content and "array" not in csv_content:
        raise RuntimeError("CSV export missing record")

    if not exp_md.exists():
        raise RuntimeError("Markdown export file missing")
    md_content = exp_md.read_text(encoding="utf-8")
    if "Two Sum" not in md_content:
        raise RuntimeError("Markdown export missing 'Two Sum'")
    print(" [PASS] 9.5 Verified All 4 Export Formats Contain Expected Sample Records")

    all_passed = all(o["passed"] for o in observations)
    print("\n" + "=" * 70)
    print(f" JOURNEY AUDIT SUMMARY: {'ALL STEPS PASSED' if all_passed else 'SOME STEPS FAILED'}")
    print("=" * 70)

    # Save detailed audit log
    audit_log = ROOT / "docs" / "product" / "journey_audit_log.json"
    audit_log.write_text(json.dumps(observations, indent=2), encoding="utf-8")
    print(f"[*] Detailed audit log saved to {audit_log}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
