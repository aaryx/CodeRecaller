import json
import os
import subprocess
import sys

from typer.testing import CliRunner

from coderecall.cli import app


def cli(root, *args, expected=0):
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "CodeRecall Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "CodeRecall Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "coderecall", "--json", "--non-interactive", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_complete_cli_acceptance(tmp_path):
    assert cli(tmp_path, "init", "--git-init")["ready"]
    source = tmp_path / "draft.py"
    source.write_text("def solve():\n    return 42\n", encoding="utf-8")
    result = cli(
        tmp_path,
        "add",
        "--title",
        "Synthetic Sum",
        "--file",
        str(source),
        "--external-id",
        "1",
        "--topics",
        "array",
        "--no-commit",
    )
    pid = result["problem_id"]
    assert (tmp_path / result["solutions"][0]).is_file()
    assert cli(tmp_path, "status")["problems"] == 1
    assert "changes" in cli(tmp_path, "git", "status")
    commit = cli(tmp_path, "git", "commit", "--yes")
    assert len(commit["commit"]) == 40
    assert cli(tmp_path, "stats")["problems_solved"] == 1
    assert cli(tmp_path, "today")["reviews"] == []
    recall = cli(tmp_path, "revise", pid)
    assert "return 42" not in json.dumps(recall)
    (tmp_path / recall["workspace"]).write_text("def solve():\n    return 42\n", encoding="utf-8")
    review = cli(
        tmp_path,
        "recall",
        "submit",
        recall["recall_id"],
        "--result",
        "pass",
        "--confidence",
        "5",
        "--seconds",
        "391",
    )
    assert review["schedule"]["interval_days"] >= 2
    assert cli(tmp_path, "topics")[0]["recall_percent"] == 100
    saved = cli(tmp_path, "backup")["backup"]
    cli(tmp_path, "note", pid, "--text", "temporary")
    assert cli(tmp_path, "restore", saved, "--yes")["restored"]
    assert cli(tmp_path, "export")["reviews"][0]["seconds"] == 391
    assert cli(tmp_path, "search", "Synthetic")[0]["id"] == pid
    assert cli(tmp_path, "random", "--seed", "42")["id"] == pid
    assert cli(tmp_path, "ai")["enabled"] is False
    assert cli(tmp_path, "run", str(source), expected=8)["state"] == "UNAVAILABLE"
    assert cli(tmp_path, "doctor")["errors"] == 0


def test_json_errors_and_dry_run(tmp_path):
    assert cli(tmp_path, "status", expected=3)["error"]["exit_code"] == 3
    assert cli(tmp_path, "bad-command", expected=2)["error"]["exit_code"] == 2
    cli(tmp_path, "--dry-run", "init")
    assert not (tmp_path / ".coderecall").exists()
    cli(tmp_path, "init")
    assert cli(tmp_path, "init", expected=3)["error"]
    before = (tmp_path / ".coderecall/state.json").read_bytes()
    source = tmp_path / "solution.py"
    source.write_text("print(1)", encoding="utf-8")
    cli(tmp_path, "--dry-run", "add", "--title", "Test", "--file", str(source))
    assert before == (tmp_path / ".coderecall/state.json").read_bytes()


def test_help_and_version():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0 and "revise" in result.output
    assert runner.invoke(app, ["--version"]).exit_code == 0


def test_json_help_doctor_failure_and_stdin(tmp_path):
    assert "help" in cli(tmp_path, "--help")
    assert cli(tmp_path, "doctor", expected=9)["errors"] > 0
    cli(tmp_path, "init")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "coderecall",
            "--json",
            "--non-interactive",
            "add",
            "--stdin",
            "--language",
            "python",
            "--title",
            "Piped",
            "--no-commit",
        ],
        cwd=tmp_path,
        input="print(42)\n",
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["created"]


def test_recall_submission_and_public_capture_cli(tmp_path):
    cli(tmp_path, "init")
    source = tmp_path / "original.py"
    source.write_text("print('original')", encoding="utf-8")
    pid = cli(tmp_path, "add", "--title", "Practice", "--file", str(source), "--no-commit")[
        "problem_id"
    ]
    attempt = cli(tmp_path, "revise", pid)
    rid = attempt["recall_id"]
    assert cli(
        tmp_path, "recall", "submit", rid, "--result", "pass", "--confidence", "4", expected=7
    )["error"]
    (tmp_path / attempt["workspace"]).write_text("print('new attempt')", encoding="utf-8")
    result = cli(tmp_path, "recall", "submit", rid, "--result", "pass", "--confidence", "4")
    assert result["review"]["assessment"] == "self-reported-code"
    assert cli(tmp_path, "recall", "capture", rid, "--yes")["captured"]
    assert cli(tmp_path, "status")["solutions"] == 2
    human = subprocess.run(
        [sys.executable, "-m", "coderecall", "--no-color", "stats"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert human.returncode == 0 and "Problems Solved" in human.stdout
    assert '"problems_solved"' not in human.stdout


def test_dashboard_rendering_encoding_and_fallback(tmp_path):
    cli(tmp_path, "init")
    # Test --json output contract
    data = cli(tmp_path, "dashboard")
    assert "streak" in data
    assert "due_today" in data
    assert "retention_percent" in data
    assert "weak_topic" in data

    # Test fallback rendering under simulated legacy Windows CP1252 terminal
    env_cp1252 = os.environ.copy()
    env_cp1252["PYTHONIOENCODING"] = "cp1252"
    result_cp1252 = subprocess.run(
        [sys.executable, "-m", "coderecall", "--no-color", "dashboard"],
        cwd=tmp_path,
        env=env_cp1252,
        capture_output=True,
        text=True,
        encoding="cp1252",
        timeout=30,
    )
    assert result_cp1252.returncode == 0, result_cp1252.stderr
    assert "CODE RECALL" in result_cp1252.stdout
    assert "Streak" in result_cp1252.stdout

    # Test normal UTF-8 terminal rendering
    env_utf8 = os.environ.copy()
    env_utf8["PYTHONIOENCODING"] = "utf-8"
    result_utf8 = subprocess.run(
        [sys.executable, "-m", "coderecall", "--no-color", "dashboard"],
        cwd=tmp_path,
        env=env_utf8,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result_utf8.returncode == 0, result_utf8.stderr
    assert "CODE RECALL" in result_utf8.stdout
