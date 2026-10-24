import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from coderecall.cli import app

runner = CliRunner()


def test_cli_config_commands(project, monkeypatch):
    monkeypatch.chdir(project.root)
    # config show (default action)
    res_list = runner.invoke(app, ["--json", "config"])
    assert res_list.exit_code == 0
    data = json.loads(res_list.output)
    assert "revision" in data and "scheduler" in data["revision"]

    # config set
    res_set = runner.invoke(
        app, ["--json", "config", "--action", "set", "--key", "execution.timeout", "--value", "10"]
    )
    assert res_set.exit_code == 0

    # config get
    res_get = runner.invoke(
        app, ["--json", "config", "--action", "get", "--key", "execution.timeout"]
    )
    assert res_get.exit_code == 0
    assert json.loads(res_get.output)["execution.timeout"] == 10


def test_cli_backup_verify_and_restore_check_only(project, capture, monkeypatch):
    monkeypatch.chdir(project.root)
    project.catalog.add(capture)

    # Make backup
    res_bak = runner.invoke(app, ["--json", "backup"])
    assert res_bak.exit_code == 0
    backup_path = json.loads(res_bak.output)["backup"]
    assert Path(backup_path).is_file()

    # Test backup --verify
    res_verify = runner.invoke(app, ["--json", "backup", "--verify", backup_path])
    assert res_verify.exit_code == 0
    verify_data = json.loads(res_verify.output)
    assert verify_data["valid"] is True
    assert verify_data["problems_count"] == 1
    assert verify_data["schema_version"] == 1

    # Test restore --check-only
    res_chk = runner.invoke(app, ["--json", "restore", backup_path, "--check-only"])
    assert res_chk.exit_code == 0
    chk_data = json.loads(res_chk.output)
    assert chk_data["valid"] is True
    assert chk_data["problems_count"] == 1


def test_cli_catalog_list_and_filters(project, capture, monkeypatch):
    monkeypatch.chdir(project.root)
    p, _ = project.catalog.add(capture)

    # list all
    res_list = runner.invoke(app, ["--json", "list"])
    assert res_list.exit_code == 0
    problems = json.loads(res_list.output)
    assert len(problems) == 1
    assert problems[0]["id"] == p.id

    # list with matching topic filter
    res_topic = runner.invoke(app, ["--json", "list", "--topic", "array"])
    assert res_topic.exit_code == 0
    assert len(json.loads(res_topic.output)) == 1

    # list with non-matching topic filter
    res_miss = runner.invoke(app, ["--json", "list", "--topic", "graph"])
    assert res_miss.exit_code == 0
    assert len(json.loads(res_miss.output)) == 0

    # show command
    res_show = runner.invoke(app, ["--json", "show", p.id])
    assert res_show.exit_code == 0
    shown = json.loads(res_show.output)
    assert shown["problem"]["title"] == "Two Sum"

    # archive and unarchive
    res_arc = runner.invoke(app, ["--json", "archive", p.id])
    assert res_arc.exit_code == 0
    assert res_arc.output.strip() != ""

    res_unarc = runner.invoke(app, ["--json", "archive", p.id, "--undo"])
    assert res_unarc.exit_code == 0


def test_cli_stats_time_windows(project, capture, monkeypatch):
    monkeypatch.chdir(project.root)
    project.catalog.add(capture)

    for flag in ["--today", "--week", "--month", "--year", "--all-time"]:
        res = runner.invoke(app, ["--json", "stats", flag])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert "problems_solved" in data


def test_cli_sessions_lifecycle(project, monkeypatch):
    monkeypatch.chdir(project.root)

    # session start
    res_start = runner.invoke(app, ["--json", "session", "start", "--note", "Practice test"])
    assert res_start.exit_code == 0
    start_data = json.loads(res_start.output)
    assert "id" in start_data and start_data["ended_at"] == ""

    # session status
    res_status = runner.invoke(app, ["--json", "session", "status"])
    assert res_status.exit_code == 0
    status_data = json.loads(res_status.output)
    assert "id" in status_data

    # session stop
    res_stop = runner.invoke(app, ["--json", "session", "stop"])
    assert res_stop.exit_code == 0
    stop_data = json.loads(res_stop.output)
    assert stop_data["ended_at"] != ""


def test_cli_goals_and_achievements(project, monkeypatch):
    monkeypatch.chdir(project.root)

    # Add goal
    res_add_goal = runner.invoke(app, ["--json", "goal", "add", "daily", "reviews", "5"])
    assert res_add_goal.exit_code == 0

    # List goals
    res_goals = runner.invoke(app, ["--json", "goal", "list"])
    assert res_goals.exit_code == 0
    goals = json.loads(res_goals.output)
    assert len(goals) >= 1

    # Achievements command
    res_ach = runner.invoke(app, ["--json", "achievements"])
    assert res_ach.exit_code == 0
    ach_data = json.loads(res_ach.output)
    assert isinstance(ach_data, list)


def test_cli_schedule_actions(project, capture, monkeypatch):
    monkeypatch.chdir(project.root)
    p, _ = project.catalog.add(capture)

    # suspend
    res_susp = runner.invoke(app, ["--json", "schedule", "suspend", p.id])
    assert res_susp.exit_code == 0

    # resume
    res_res = runner.invoke(app, ["--json", "schedule", "resume", p.id])
    assert res_res.exit_code == 0

    # reschedule
    res_sched = runner.invoke(app, ["--json", "schedule", "reschedule", p.id, "--days", "14"])
    assert res_sched.exit_code == 0

    # reset
    res_reset = runner.invoke(app, ["--json", "schedule", "reset", p.id])
    assert res_reset.exit_code == 0


def test_cli_export_formats(project, capture, monkeypatch):
    monkeypatch.chdir(project.root)
    project.catalog.add(capture)

    # JSON export
    res_json = runner.invoke(app, ["--json", "export", "--format", "json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.output)
    assert "problems" in data

    # Markdown export
    res_md = runner.invoke(app, ["--json", "export", "--format", "markdown"])
    assert res_md.exit_code == 0
    assert "# CodeRecall" in res_md.output

    # CSV export
    res_csv = runner.invoke(app, ["--json", "export", "--format", "csv"])
    assert res_csv.exit_code == 0
    assert "title,platform" in res_csv.output


def test_cli_doctor_languages(project, monkeypatch):
    monkeypatch.chdir(project.root)
    res = runner.invoke(app, ["--no-color", "doctor", "--languages"])
    assert res.exit_code == 0
    assert "Enabled Languages:" in res.output


def test_cli_dashboard_text_and_json(project, capture, monkeypatch):
    monkeypatch.chdir(project.root)
    project.catalog.add(capture)

    # Dashboard in json mode
    res_json = runner.invoke(app, ["--json", "dashboard"])
    assert res_json.exit_code == 0
    d_data = json.loads(res_json.output)
    assert "retention_percent" in d_data
    assert "streak" in d_data

    # Dashboard in rich text mode
    res_text = runner.invoke(app, ["--no-color", "dashboard"])
    assert res_text.exit_code == 0
    assert "CODE RECALL" in res_text.output
    assert "Streak" in res_text.output


def test_cli_add_and_archive(project, tmp_path, monkeypatch):
    monkeypatch.chdir(project.root)
    sol_file = tmp_path / "solution.py"
    sol_file.write_text("def solve(): return 42\n", encoding="utf-8")

    # Add via CLI
    res_add = runner.invoke(
        app,
        [
            "--json",
            "add",
            "--title",
            "CLI Added Problem",
            "--file",
            str(sol_file),
            "--language",
            "python",
            "--difficulty",
            "medium",
            "--topics",
            "math,logic",
            "--no-commit",
        ],
    )
    assert res_add.exit_code == 0
    added_info = json.loads(res_add.output)
    pid = added_info["problem_id"]

    # Archive via CLI
    res_arc = runner.invoke(app, ["--json", "archive", pid])
    assert res_arc.exit_code == 0


def test_cli_recall_flow(project, capture, monkeypatch):
    monkeypatch.chdir(project.root)
    p, _ = project.catalog.add(capture)

    # Start recall via revise in json mode
    res_start = runner.invoke(app, ["--json", "revise", p.id])
    assert res_start.exit_code == 0
    r_data = json.loads(res_start.output)
    rid = str(r_data["recall_id"])

    # Request hint via recall hint
    res_hint = runner.invoke(app, ["--json", "recall", "hint", rid])
    assert res_hint.exit_code == 0

    # Pause and resume
    res_pause = runner.invoke(app, ["--json", "recall", "pause", rid])
    assert res_pause.exit_code == 0
    res_resume = runner.invoke(app, ["--json", "recall", "resume", rid])
    assert res_resume.exit_code == 0

    # Write solution to workspace
    (project.root / r_data["workspace"]).write_text("def solve(): pass\n", encoding="utf-8")

    # Submit review
    res_rev = runner.invoke(
        app,
        [
            "--json",
            "recall",
            "submit",
            rid,
            "--result",
            "pass",
            "--confidence",
            "4",
            "--seconds",
            "120",
        ],
    )
    assert res_rev.exit_code == 0
    rev_data = json.loads(res_rev.output)
    assert rev_data["review"]["success"] is True


def test_cli_today_and_status(project, capture, monkeypatch):
    monkeypatch.chdir(project.root)
    project.catalog.add(capture)

    # today command
    res_today = runner.invoke(app, ["--json", "today"])
    assert res_today.exit_code == 0
    assert "reviews" in json.loads(res_today.output)

    res_today_txt = runner.invoke(app, ["--no-color", "today"])
    assert res_today_txt.exit_code == 0

    # status command
    res_status = runner.invoke(app, ["--json", "status"])
    assert res_status.exit_code == 0
    assert json.loads(res_status.output)["local_state"] == "healthy"

    res_status_txt = runner.invoke(app, ["--no-color", "status"])
    assert res_status_txt.exit_code == 0


def test_output_render_and_display():
    from rich.console import Console

    from coderecall.cli.output import clean, display, render

    # Clean control codes
    assert clean("Hello\x00World\x1b") == "Hello\\x00World\\x1b"

    # Display helper
    assert display(None) == "Not measured"
    assert display(True) == "Yes"
    assert display(False) == "No"
    assert display(["a", "b"]) == "a, b"
    assert display([]) == "None"
    assert display("regular") == "regular"

    # Render branches to memory console
    con = Console(record=True, no_color=True)
    # 1. String
    render(con, "Simple text")
    # 2. List of dicts (Table)
    render(con, [{"name": "item1", "val": 10}, {"name": "item2", "val": 20}])
    # 3. Dict with nested sections
    render(con, {"simple_key": "simple_val", "nested_sec": [{"col": "v1"}]})
    # 4. Primitive
    render(con, 12345)

    captured = con.export_text()
    assert "Simple text" in captured
    assert "item1" in captured
    assert "Simple Key" in captured


def test_cli_catalog_extended_commands(project, capture, tmp_path, monkeypatch):
    monkeypatch.chdir(project.root)
    p, _ = project.catalog.add(capture)

    # Search command
    res_search = runner.invoke(app, ["--json", "search", "two sum"])
    assert res_search.exit_code == 0
    assert len(json.loads(res_search.output)) >= 1

    # Note command
    res_note = runner.invoke(app, ["--json", "note", p.id, "--text", "Remember hash map lookup"])
    assert res_note.exit_code == 0

    # Random command
    res_rand = runner.invoke(app, ["--json", "random"])
    assert res_rand.exit_code == 0
    assert json.loads(res_rand.output)["id"] == p.id

    # Analyze command
    sol_file = project.root / p.solutions[0].path
    res_ana = runner.invoke(app, ["--json", "analyze", str(sol_file), "--time-complexity", "O(n)"])
    assert res_ana.exit_code == 0
    ana_data = json.loads(res_ana.output)
    assert ana_data["time"] == "O(n)"
    assert ana_data["language"] == "python"

    # Import preview using --dry-run
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "0001-two-sum.py").write_text("def solve(): pass\n", encoding="utf-8")
    res_imp = runner.invoke(app, ["--json", "import", str(incoming), "--dry-run"])
    assert res_imp.exit_code == 0
    imp_data = json.loads(res_imp.output)
    assert imp_data["recognized"] == 1


def test_cli_learning_extended_commands(project, capture, monkeypatch):
    monkeypatch.chdir(project.root)
    p, _ = project.catalog.add(capture)

    # Mistake command
    res_mistake = runner.invoke(
        app,
        [
            "--json",
            "mistake",
            p.id,
            "Missed zero case",
            "--category",
            "edge_case",
            "--severity",
            "high",
        ],
    )
    assert res_mistake.exit_code == 0

    # Topics command
    res_topics = runner.invoke(app, ["--json", "topics"])
    assert res_topics.exit_code == 0

    # Streak command
    res_streak = runner.invoke(app, ["--json", "streak"])
    assert res_streak.exit_code == 0

    # Summary command
    res_sum = runner.invoke(app, ["--json", "summary"])
    assert res_sum.exit_code == 0

    # Curve command
    res_curve = runner.invoke(app, ["--json", "curve", p.id])
    assert res_curve.exit_code == 0

    # Weak command
    res_weak = runner.invoke(app, ["--json", "weak"])
    assert res_weak.exit_code == 0


def test_cli_management_extended_commands(project, tmp_path, monkeypatch):
    monkeypatch.chdir(project.root)

    # Doctor command
    res_doc = runner.invoke(app, ["--json", "doctor"])
    assert res_doc.exit_code == 0
    doc_data = json.loads(res_doc.output)
    assert "checks" in doc_data

    # Init command in new subfolder
    new_dir = tmp_path / "new_repo"
    new_dir.mkdir()
    monkeypatch.chdir(new_dir)
    res_init = runner.invoke(app, ["--json", "init"])
    assert res_init.exit_code == 0
    assert (new_dir / ".coderecall" / "state.json").is_file()


def test_output_confirm_and_quiet(project, capture, monkeypatch):
    import click

    from coderecall.cli.output import Options, confirm, emit
    from coderecall.domain.errors import ValidationError

    ctx = click.Context(click.Command("test"))

    # Dry run confirmation
    ctx.obj = Options(dry_run=True)
    assert confirm(ctx, "Are you sure?") is False

    # Explicit yes
    ctx.obj = Options()
    assert confirm(ctx, "Are you sure?", yes=True) is True

    # Non-interactive without yes raises
    ctx.obj = Options(non_interactive=True)
    with pytest.raises(ValidationError, match="Confirmation required"):
        confirm(ctx, "Are you sure?")

    # Quiet emit suppresses output
    ctx.obj = Options(quiet=True)
    emit(ctx, "should not raise or print")
