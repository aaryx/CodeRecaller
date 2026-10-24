from dataclasses import replace
from datetime import timedelta

import pytest

from coderecall.application.catalog import Capture
from coderecall.application.project import doctor
from coderecall.domain.errors import ValidationError
from coderecall.domain.models import Activity, Problem, Review, Schedule
from coderecall.integrations.problems import ProblemMetadata
from coderecall.storage.config import Config


def test_list_problems_filtering(project, capture):
    # Add problem 1: Easy array problem
    p1, _ = project.catalog.add(capture)

    # Add problem 2: Hard graph problem
    c2 = Capture(
        metadata=ProblemMetadata(
            title="Course Schedule",
            platform="leetcode",
            external_id="207",
            slug="course-schedule",
            url="https://leetcode.com/problems/course-schedule/",
            difficulty="hard",
            topics=["graph", "topological-sort"],
        ),
        language="python",
        code="def canFinish(): pass\n",
        approach="DFS cycle detection",
        time_complexity="O(V+E)",
        space_complexity="O(V)",
        patterns=["dfs"],
        tags=["blind75"],
        note="Key is cycle detection",
    )
    p2, _ = project.catalog.add(c2)

    # Filtering by difficulty
    assert len(project.list_problems(difficulty="easy")) == 1
    assert project.list_problems(difficulty="easy")[0].id == p1.id
    assert len(project.list_problems(difficulty="hard")) == 1
    assert project.list_problems(difficulty="hard")[0].id == p2.id
    assert len(project.list_problems(difficulty="medium")) == 0

    # Filtering by topic
    assert len(project.list_problems(topic="graph")) == 1
    assert project.list_problems(topic="graph")[0].id == p2.id
    assert len(project.list_problems(topic="array")) == 1
    assert project.list_problems(topic="array")[0].id == p1.id

    # Filtering by language
    assert len(project.list_problems(language="python")) == 2
    assert len(project.list_problems(language="rust")) == 0

    # Filtering by pattern
    assert len(project.list_problems(pattern="dfs")) == 1
    assert len(project.list_problems(pattern="bfs")) == 0

    # Query search: exact and fuzzy
    assert len(project.list_problems(query="Course Schedule")) == 1
    assert len(project.list_problems(query="cycle detection")) == 1
    assert len(project.list_problems(query="blind75")) == 1
    assert len(project.list_problems(query="nonexistent_xyz_query")) == 0

    # Unreviewed filter
    assert len(project.list_problems(unreviewed=True)) == 2
    with project.store.transaction() as state:
        state.reviews.append(
            Review(
                "rev_1",
                p1.id,
                project.clock.now().isoformat(),
                project.clock.now().isoformat(),
                0,
                True,
                60,
                1,
                0,
                4,
                "",
                "hash",
                "O(n)",
            )
        )
    assert len(project.list_problems(unreviewed=True)) == 1
    assert project.list_problems(unreviewed=True)[0].id == p2.id

    # Failed filter
    assert len(project.list_problems(failed=True)) == 0
    with project.store.transaction() as state:
        state.reviews.append(
            Review(
                "rev_2",
                p2.id,
                project.clock.now().isoformat(),
                project.clock.now().isoformat(),
                0,
                False,
                120,
                1,
                1,
                1,
                "",
                "",
                "",
            )
        )
    assert len(project.list_problems(failed=True)) == 1
    assert project.list_problems(failed=True)[0].id == p2.id

    # Due only filter
    with project.store.transaction() as state:
        state.schedules[p1.id].next_review = (project.clock.now() - timedelta(days=1)).isoformat()
        state.schedules[p2.id].next_review = (project.clock.now() + timedelta(days=10)).isoformat()
    assert len(project.list_problems(due_only=True)) == 1
    assert project.list_problems(due_only=True)[0].id == p1.id


def test_scheduler_instantiation(project):
    # Default is fsrs
    assert project.recall.scheduler.__class__.__name__ == "FSRSScheduler"

    # Switch to simple
    project.config.set(project.root, "revision.scheduler", "simple")
    project.config = Config(project.root)
    # Invalidate cached property
    del project.__dict__["recall"]
    assert project.recall.scheduler.__class__.__name__ == "SimpleIntervalScheduler"


def test_status_and_today(project, capture):
    p, _ = project.catalog.add(capture)
    status = project.status()
    assert status["problems"] == 1
    assert status["solutions"] == 1
    assert status["local_state"] == "healthy"
    assert status["achievements_unlocked"] == 0

    today = project.today()
    assert "reviews" in today
    assert "estimated_minutes" in today
    assert "goals" in today
    assert today["suggested_new"] == 2


def test_random_problem_and_validation(project, capture):
    p, _ = project.catalog.add(capture)
    chosen = project.random_problem(seed=42)
    assert chosen.id == p.id

    with pytest.raises(ValidationError, match="No problems match these filters"):
        project.random_problem(difficulty="nonexistent")


def test_export_formats(project, capture):
    p, _ = project.catalog.add(capture)
    # Add formula injection test problem
    inj_cap = Capture(
        metadata=ProblemMetadata(
            title="=SUM(A1:A10)",
            platform="custom",
            external_id="inj1",
            slug="sum-test",
            url="",
            difficulty="easy",
            topics=["test"],
        ),
        language="python",
        code="x = 1\n",
        approach="Direct",
        time_complexity="O(1)",
        space_complexity="O(1)",
        note="+cmd|' /C calc'!A0",
    )
    project.catalog.add(inj_cap)

    # JSON export
    json_out = project.export("json")
    assert '"problems":' in json_out
    assert p.id in json_out

    # CSV export with formula injection sanitization
    csv_out = project.export("csv")
    assert "id,title,platform" in csv_out
    # Formula prefixes should be escaped with leading single quote
    assert "'=SUM(A1:A10)" in csv_out
    assert "'+cmd|' /C calc'!A0" in csv_out

    # Markdown export
    md_out = project.export("markdown")
    assert "# CodeRecall learning export" in md_out
    assert p.title in md_out

    # HTML export
    html_out = project.export("html")
    assert "<!DOCTYPE html>" in html_out
    assert "CodeRecall — Learning Report" in html_out
    assert p.title in html_out

    # Invalid export format
    with pytest.raises(ValidationError, match="Export format must be"):
        project.export("xml")


def test_goals_lifecycle(project):
    # Validation errors on goal creation
    with pytest.raises(ValidationError, match="Goal kind must be"):
        project.add_goal("hourly", "reviews", 5)
    with pytest.raises(ValidationError, match="Goal target must be positive"):
        project.add_goal("daily", "reviews", 0)
    with pytest.raises(ValidationError, match="Goal target must be reviews"):
        project.add_goal("daily", "invalid_type", 5)

    goal = project.add_goal("daily", "reviews", 5)
    assert goal.id.startswith("goal_")
    assert goal.target_value == 5
    assert goal.active

    goals = project.goals()
    assert len(goals) == 1
    assert goals[0]["target_value"] == 5

    # Remove goal
    project.remove_goal(goal.id)
    assert len([g for g in project.goals() if g["active"]]) == 0

    with pytest.raises(ValidationError, match="Goal not found"):
        project.remove_goal("nonexistent_id")


def test_batch_archive_and_reschedule(project, capture):
    p1, _ = project.catalog.add(capture)
    c2 = replace(capture, metadata=ProblemMetadata("Problem 2", "custom", "p2"))
    p2, _ = project.catalog.add(c2)

    # Batch archive
    res = project.batch_archive([p1.id, p2.id, "invalid_id"])
    assert len(res["processed"]) == 2
    assert len(res["errors"]) == 1
    assert project.store.read().problems[p1.id].archived is True
    assert project.store.read().problems[p2.id].archived is True

    # Undo batch archive
    res = project.batch_archive([p1.id], undo=True)
    assert len(res["processed"]) == 1
    assert project.store.read().problems[p1.id].archived is False

    # Batch reschedule validation
    with pytest.raises(ValidationError, match="Days must be 1–365"):
        project.batch_reschedule([p1.id], days=0)
    with pytest.raises(ValidationError, match="Days must be 1–365"):
        project.batch_reschedule([p1.id], days=400)

    # Batch reschedule valid
    res = project.batch_reschedule([p1.id, "missing_id"], days=14)
    assert len(res["processed"]) == 1
    assert len(res["errors"]) == 1
    sched = project.store.read().schedules[p1.id]
    assert sched.next_review == (project.clock.now() + timedelta(days=14)).isoformat()


def test_hints_and_mistakes(project, capture):
    p, _ = project.catalog.add(capture)

    # Hint validation
    with pytest.raises(ValidationError, match="Provide a hint at level 1–4"):
        project.add_hint(p.id, 0, "test")
    with pytest.raises(ValidationError, match="Provide a hint at level 1–4"):
        project.add_hint(p.id, 5, "test")
    with pytest.raises(ValidationError, match="Provide a hint at level 1–4"):
        project.add_hint(p.id, 2, "   ")

    # Add hints
    project.add_hint(p.id, 2, "Hint 2 text")
    problem = project.store.read().problems[p.id]
    assert len(problem.hints) == 2
    assert problem.hints[0] == "No user hint recorded for this level"
    assert problem.hints[1] == "Hint 2 text"

    # Mistake validation
    with pytest.raises(ValidationError, match="Provide text and severity"):
        project.add_mistake(p.id, "", "logic", "medium")
    with pytest.raises(ValidationError, match="Provide text and severity"):
        project.add_mistake(p.id, "Off by one", "logic", "critical")

    # Add mistake
    project.add_mistake(p.id, "Forgot base case", "edge_case", "high")
    mistakes = project.store.read().mistakes
    assert len(mistakes) == 1
    assert mistakes[0].problem_id == p.id
    assert mistakes[0].category == "edge_case"
    assert mistakes[0].severity == "high"


def test_doctor_diagnostics(project, capture):
    p, _ = project.catalog.add(capture)
    diag = doctor(project.root)
    assert diag["errors"] == 0
    checks = {c["check"]: c for c in diag["checks"]}
    assert "Python" in checks
    assert checks["state/config/schema"]["status"] == "ok"
    assert checks["owned files"]["status"] == "ok"
    assert checks["backups"]["status"] in ("ok", "warning")
    assert checks["pending transactions"]["status"] == "ok"


def test_open_editor_errors(project, capture, monkeypatch):
    p, _ = project.catalog.add(capture)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    Config.set(project.root, "repository.editor", "")
    project.config = Config(project.root)

    # No editor set
    with pytest.raises(ValidationError, match="Set EDITOR or repository.editor first"):
        project.edit(p.id)

    # Empty editor
    Config.set(project.root, "repository.editor", '""')
    project.config = Config(project.root)
    with pytest.raises(ValidationError, match="Editor command is empty"):
        project.edit(p.id)


def test_commit_paths_gitignore_detection(project, capture):
    p, _ = project.catalog.add(capture)
    paths = project.commit_paths()
    # By default, generated .gitignore with exact content is tracked
    assert ".gitignore" in paths

    # When .gitignore has user customizations, never stage it
    (project.root / ".gitignore").write_bytes(b".coderecall/\n*.pyc\n")
    paths = project.commit_paths()
    assert ".gitignore" not in paths


def test_random_problem_weak(project, capture):
    p, _ = project.catalog.add(capture)
    # Fail a review on this topic so it becomes recommended weak
    with project.store.transaction() as state:
        state.reviews.append(
            Review(
                "rev_fail",
                p.id,
                project.clock.now().isoformat(),
                project.clock.now().isoformat(),
                0,
                False,
                60,
                1,
                1,
                1,
            )
        )
    weak_p = project.random_problem(weak=True)
    assert weak_p.id == p.id


def test_edit_no_solutions(project):
    # Create problem without solutions
    with project.store.transaction() as state:
        p = Problem(
            id="cr_nosol",
            external_id="nosol",
            title="No Solution Problem",
            slug="no-sol",
            url="",
            platform="custom",
            difficulty="medium",
            topics=["math"],
            patterns=[],
            tags=[],
            created_at=project.clock.now().isoformat(),
            solutions=[],
        )
        state.problems[p.id] = p
        state.schedules[p.id] = Schedule(p.id, project.clock.now().isoformat())

    with pytest.raises(ValidationError, match="No solution to edit"):
        project.edit("cr_nosol")


def test_html_export_achievements_and_archived(project, capture):
    p, _ = project.catalog.add(capture)
    # Unlock achievement and archive problem
    from coderecall.domain.models import Achievement

    with project.store.transaction() as state:
        state.achievements.append(
            Achievement(
                "first_solve",
                "🎯 First Blood",
                "Solve your first problem",
                project.clock.now().isoformat(),
            )
        )
        # Add archived problem
        arch = Problem(
            id="cr_arch_1",
            external_id="arch",
            title="Archived Problem",
            slug="arch-problem",
            url="",
            platform="custom",
            difficulty="easy",
            topics=["misc"],
            patterns=[],
            tags=[],
            created_at=project.clock.now().isoformat(),
            archived=True,
        )
        state.problems[arch.id] = arch
        state.schedules[arch.id] = Schedule(arch.id, project.clock.now().isoformat())

    html_out = project.export("html")
    assert "🏆 Achievements" in html_out
    assert "🎯 First Blood" in html_out
    assert "Two Sum" in html_out
    assert "Archived Problem" not in html_out


def test_daily_commit_due(project, capture):
    p, _ = project.catalog.add(capture)
    assert not project.daily_commit_due()

    # Enable auto_commit and strategy daily
    project.config.set(project.root, "git.auto_commit", "true")
    project.config.set(project.root, "git.strategy", "daily")
    project.config = Config(project.root)

    # Add solution activity today
    with project.store.transaction() as state:
        state.activities.append(Activity("solution", p.id, project.clock.now().isoformat()))

    assert project.daily_commit_due()

    # Record git_commit activity today
    with project.store.transaction() as state:
        state.activities.append(Activity("git_commit", p.id, project.clock.now().isoformat()))

    assert not project.daily_commit_due()


def test_forgetting_curve(project, capture):
    p, _ = project.catalog.add(capture)
    curve = project.forgetting_curve(p.id)
    assert isinstance(curve, list)
    assert len(curve) > 0
    assert "days_since_review" in curve[0]
    assert "estimated_retention" in curve[0]


def test_doctor_diagnostics_extended(project, capture):
    p, _ = project.catalog.add(capture)
    # Create backups dir with a backup
    backups_dir = project.store.path("backups")
    backups_dir.mkdir(parents=True, exist_ok=True)
    (backups_dir / "backup-20260101.zip").write_bytes(b"PK000fake")

    diag = doctor(project.root)
    checks = {c["check"]: c for c in diag["checks"]}
    assert checks["backups"]["status"] == "ok"
    assert "1 available" in checks["backups"]["detail"]
    assert checks["pending transactions"]["status"] == "ok"

    # Now test when root has an invalid state
    corrupt_root = project.root / "corrupt_proj"
    corrupt_root.mkdir()
    (corrupt_root / ".coderecall").mkdir()
    (corrupt_root / ".coderecall" / "state.json").write_text("invalid json{{{", encoding="utf-8")
    diag_err = doctor(corrupt_root)
    assert diag_err["errors"] > 0
    err_checks = {c["check"]: c for c in diag_err["checks"]}
    assert "project" in err_checks
    assert err_checks["project"]["status"] == "error"


def test_capture_review_lifecycle(project, capture):
    p, _ = project.catalog.add(capture)

    # Missing recall raises ValidationError
    with pytest.raises(ValidationError, match="Submit the recall before capturing its code"):
        project.capture_review("nonexistent_rid")

    # Start recall
    recall = project.recall.start(p.id, minutes=15)
    rid = str(recall["recall_id"])

    # Record failed review
    with project.store.transaction() as state:
        state.reviews.append(
            Review(
                rid,
                p.id,
                project.clock.now().isoformat(),
                project.clock.now().isoformat(),
                0,
                False,
                120,
                1,
                0,
                1,
            )
        )

    with pytest.raises(ValidationError, match="A failed attempt stays private"):
        project.capture_review(rid)

    # Now make it a successful review with submitted.txt
    workspace_dir = project.root / ".coderecall" / "workspaces" / rid
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "submitted.txt").write_text("def solve(): return True\n", encoding="utf-8")

    with project.store.transaction() as state:
        state.reviews[-1].success = True

    result = project.capture_review(rid)
    assert result["problem_id"] == p.id
    assert result["local_saved"] is True
