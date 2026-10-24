import csv
import hashlib
import html
import io
import json
import os
import random
import shlex
import shutil
import sys
from collections import Counter
from dataclasses import asdict
from datetime import timedelta
from functools import cached_property
from pathlib import Path
from uuid import uuid4

from coderecall.application.catalog import Catalog, identify, owned_paths
from coderecall.application.recall import RecallService
from coderecall.domain.analytics import (
    check_achievements,
    due,
    forgetting_curve,
    goal_progress,
    recommendations,
    statistics,
    streak,
)
from coderecall.domain.clock import Clock, SystemClock
from coderecall.domain.errors import CodeRecallError, ValidationError
from coderecall.domain.models import Activity, Goal, Mistake, Problem, State
from coderecall.domain.validation import fuzzy_match
from coderecall.integrations.git import LocalGitProvider, SyncPlan
from coderecall.integrations.process import run
from coderecall.revision.scheduler import FSRSScheduler, SimpleIntervalScheduler
from coderecall.storage.config import Config
from coderecall.storage.local import LocalStore, discover
from coderecall.storage.paths import safe_path


class Project:
    def __init__(self, root: Path | None = None, clock: Clock | None = None):
        self.root = discover(root or Path.cwd())
        self.clock = clock or SystemClock()
        self.store = LocalStore(self.root)
        self.config = Config(self.root)
        self.catalog = Catalog(self.store, self.clock, self.config)
        self.git = LocalGitProvider(self.root)

    @cached_property
    def recall(self) -> RecallService:
        scheduler_name = self.config.get("revision.scheduler")
        if scheduler_name == "simple":
            return RecallService(self.store, self.clock, SimpleIntervalScheduler())
        if scheduler_name == "fsrs":
            retention = int(self.config.get("revision.target_retention")) / 100.0
            return RecallService(self.store, self.clock, FSRSScheduler(retention))
        from coderecall.integrations.plugins import load_scheduler

        return RecallService(self.store, self.clock, load_scheduler(str(scheduler_name)))

    def list_problems(
        self,
        query: str = "",
        difficulty: str = "",
        topic: str = "",
        language: str = "",
        pattern: str = "",
        due_only: bool = False,
        overdue: bool = False,
        failed: bool = False,
        unreviewed: bool = False,
        unsolved: bool = False,
        archived: bool = False,
    ) -> list[Problem]:
        state = self.store.read()
        due_ids = {p.id for p in due(state, self.clock.now(), overdue)}
        reviews = {r.problem_id for r in state.reviews}
        latest = {r.problem_id: r for r in state.reviews}
        result: list[tuple[float, Problem]] = []
        for p in state.problems.values():
            if p.archived != archived:
                continue

            # Fuzzy search matching
            if query:
                haystack = " ".join(
                    [
                        p.id,
                        p.external_id,
                        p.title,
                        p.slug,
                        p.difficulty,
                        *p.topics,
                        *p.patterns,
                        *p.tags,
                        *p.notes,
                        *(s.language for s in p.solutions),
                        *(s.approach for s in p.solutions),
                    ]
                )
                # Try exact match first, then fuzzy
                if query.casefold() in haystack.casefold():
                    score = 1.0
                else:
                    score = fuzzy_match(query, haystack, threshold=0.3)
                    if score == 0.0:
                        continue
            else:
                score = 1.0

            if difficulty and difficulty != p.difficulty or topic and topic not in p.topics:
                continue
            if (
                language
                and language not in {s.language for s in p.solutions}
                or pattern
                and pattern not in p.patterns
            ):
                continue
            if (due_only or overdue) and p.id not in due_ids or unreviewed and p.id in reviews:
                continue
            if failed and (p.id not in latest or latest[p.id].success) or unsolved and p.solutions:
                continue
            result.append((score, p))
        return [p for _, p in sorted(result, key=lambda x: (-x[0], x[1].title.casefold(), x[1].id))]

    def stats(self, week: bool = False) -> dict[str, object]:
        now = self.clock.now()
        return statistics(
            self.store.read(),
            now,
            str(self.config.get("streak.activities")),
            now - timedelta(days=7) if week else None,
        )

    def today(self) -> dict[str, object]:
        state, now = self.store.read(), self.clock.now()
        queue = due(state, now)
        weak = recommendations(state, now)
        new = int(self.config.get("revision.daily_new"))

        # Check for new achievements
        new_achievements = (
            check_achievements(state, now)
            if self.config.get("analytics.achievements_enabled")
            else []
        )

        result: dict[str, object] = {
            "reviews": [
                {"id": p.id, "title": p.title, "due": state.schedules[p.id].next_review}
                for p in queue
            ],
            "weak_topics": weak,
            "suggested_new": new,
            "estimated_minutes": len(queue) * 15 + new * 25 + (15 if weak else 0),
            "estimate_basis": "15 minutes/review, 25/new, 15 weak-topic practice; recommendation only",
            "goals": goal_progress(state, now),
        }

        if new_achievements:
            result["new_achievements"] = [asdict(a) for a in new_achievements]
            # Persist newly unlocked achievements
            with self.store.transaction() as s:
                s.achievements.extend(new_achievements)

        return result

    def status(self) -> dict[str, object]:
        state, now = self.store.read(), self.clock.now()
        try:
            git: object = self.git.status()
        except CodeRecallError as exc:
            git = str(exc)
        return {
            "repository": str(self.root),
            "git": git,
            "problems": len(state.problems),
            "solutions": sum(len(p.solutions) for p in state.problems.values()),
            "due": len(due(state, now)),
            "overdue": len(due(state, now, True)),
            "streak": streak(state, now, str(self.config.get("streak.activities"))),
            "sync_status": state.sync_status,
            "local_state": "healthy",
            "scheduler": str(self.config.get("revision.scheduler")),
            "achievements_unlocked": len(state.achievements),
            "active_goals": len([g for g in state.goals if g.active]),
        }

    def commit_plan(self) -> list[str]:
        return self.git.changed_owned(self.commit_paths())

    def commit_paths(self) -> list[str]:
        return self._commit_paths(self.store.read())

    def _commit_paths(self, state: State) -> list[str]:
        paths = owned_paths(state)
        ignore = safe_path(self.root, ".gitignore")
        # Only the exact generated ignore file is ours; never stage pre-existing user rules.
        if ignore.is_file() and ignore.read_bytes() == b".coderecall/\n":
            paths.append(".gitignore")
        return paths

    def commit(self, message: str) -> str:
        with self.store.lock():
            state = self.store.load_unlocked()
            paths = self._commit_paths(state)
            result = self.git.commit(paths, message)
            if not result.startswith("No "):
                for p in state.problems.values():
                    for solution in p.solutions:
                        source = safe_path(self.root, solution.path)
                        if source.exists():
                            digest = hashlib.sha256(source.read_bytes()).hexdigest()
                            if not solution.git_ref or solution.digest != digest:
                                solution.git_ref = result
                                solution.digest = digest
                                solution.modified_at = self.clock.now().isoformat()
                state.sync_status = "PUSH_PENDING"
                state.activities.append(
                    Activity("git_commit", "", self.clock.now().isoformat(), detail=result)
                )
                self.store.save_unlocked(state)
            return result

    def sync(
        self,
        fetch: bool,
        execute: bool,
        approved: SyncPlan | None = None,
        import_solutions: bool = False,
    ) -> dict[str, object]:
        plan = approved or self.git.plan(fetch=fetch)
        result: dict[str, object] = {
            "plan": asdict(plan),
            "network": fetch or execute,
            "executed": False,
        }
        if execute:
            try:
                result["result"] = self.git.execute_plan(
                    plan, bool(self.config.get("git.scan_secrets"))
                )
            except CodeRecallError:
                with self.store.transaction() as state:
                    state.sync_status = "PUSH_PENDING" if plan.ahead else "ERROR"
                raise
            with self.store.transaction() as state:
                state.sync_status = "CLEAN"
            result["executed"] = True
            if import_solutions:
                from coderecall.application.importer import apply_import, scan

                try:
                    result["import"] = apply_import(self.catalog, scan(self.root))
                except (CodeRecallError, OSError) as exc:
                    result["import_warning"] = str(exc)
                    result["git_synced"] = True
        return result

    def random_problem(
        self, seed: int | None = None, weak: bool = False, **filters: str | bool
    ) -> Problem:
        problems = self.list_problems(**filters)  # type: ignore[arg-type]
        if weak:
            topics = {r["topic"] for r in recommendations(self.store.read(), self.clock.now())}
            problems = [p for p in problems if topics.intersection(p.topics)]
        if not problems:
            raise ValidationError("No problems match these filters")
        return random.Random(seed).choice(problems)  # noqa: S311 -- reproducible practice selection

    def edit(self, query: str) -> str:
        problem = identify(self.store.read(), query)
        if not problem.solutions:
            raise ValidationError("No solution to edit")
        return self.open_editor(safe_path(self.root, problem.solutions[-1].path))

    def open_editor(self, path: Path) -> str:
        editor = (
            str(self.config.get("repository.editor"))
            or os.environ.get("VISUAL")
            or os.environ.get("EDITOR")
        )
        if not editor:
            raise ValidationError("Set EDITOR or repository.editor first (e.g. code --wait)")
        try:
            arguments = shlex.split(editor, posix=os.name != "nt")
        except ValueError as exc:
            raise ValidationError("Invalid editor quoting") from exc
        arguments = [a.strip('"') for a in arguments]
        arguments = [a for a in arguments if a]
        if not arguments:
            raise ValidationError("Editor command is empty")
        result = run(arguments[0], [*arguments[1:], str(path)], self.root, 86400, interactive=True)
        if result.returncode:
            raise ValidationError("Editor exited unsuccessfully")
        return str(path)

    def export(self, format: str) -> str:
        state = self.store.read()
        review_counts = Counter(r.problem_id for r in state.reviews)
        if format == "json":
            return json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n"
        if format == "csv":
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "id",
                    "title",
                    "platform",
                    "difficulty",
                    "topics",
                    "notes",
                    "next_review",
                    "reviews",
                    "fsrs_difficulty",
                    "fsrs_stability",
                ]
            )
            for p in state.problems.values():
                schedule = state.schedules[p.id]
                values = [
                    p.id,
                    p.title,
                    p.platform,
                    p.difficulty,
                    ";".join(p.topics),
                    "\n".join(p.notes),
                    schedule.next_review,
                    str(review_counts[p.id]),
                    str(round(schedule.difficulty, 2)),
                    str(round(schedule.stability, 2)),
                ]
                writer.writerow(
                    [
                        "'" + v if v.startswith(("=", "+", "-", "@", "\t", "\r")) else v
                        for v in values
                    ]
                )
            return stream.getvalue()
        if format == "markdown":
            return (
                "# CodeRecall learning export (private)\n\n"
                + "\n\n".join(
                    f"## {p.title}\n\nID: {p.id}\n\nNext review: {state.schedules[p.id].next_review}\n\n"
                    + "\n".join(p.notes)
                    for p in state.problems.values()
                )
                + "\n"
            )
        if format == "html":
            return self._export_html(state)
        raise ValidationError("Export format must be json, csv, markdown or html")

    def _export_html(self, state: State) -> str:
        """Generate a beautiful HTML report with embedded analytics."""
        now = self.clock.now()
        stats = statistics(state, now, str(self.config.get("streak.activities")))
        streak_data = stats.get("streak", {})
        topic_data = stats.get("topics", [])
        raw_recall = stats.get("recall_percent")
        recall_percent = float(raw_recall) if isinstance(raw_recall, (int, float)) else None
        raw_overdue = stats.get("overdue", 0)
        overdue_count = int(raw_overdue) if isinstance(raw_overdue, int) else 0

        recall_class = (
            "success"
            if (recall_percent or 0.0) >= 70
            else "warning"
            if (recall_percent or 0.0) >= 50
            else "danger"
        )
        overdue_class = "danger" if overdue_count > 0 else "success"

        problems_by_difficulty: Counter[str] = Counter()
        for p in state.problems.values():
            if not p.archived:
                problems_by_difficulty[p.difficulty] += 1

        achievements_html = ""
        if state.achievements:
            items = "".join(
                f'<div class="achievement unlocked">{html.escape(a.name)} — {html.escape(a.description)}</div>'
                for a in state.achievements
            )
            achievements_html = (
                f"<h2 style='margin-bottom:1rem;color:var(--primary)'>🏆 Achievements</h2>"
                f'<div class="achievements">{items}</div>'
            )

        topic_rows = []
        for row in topic_data if isinstance(topic_data, list) else []:
            topic_name = html.escape(str(row.get("topic", "")))
            solved = row.get("solved", 0)
            reviews = row.get("reviews", 0)
            failed = row.get("failed", 0)
            raw_rp = row.get("recall_percent")
            recall_str = f"{raw_rp}%" if raw_rp is not None else "N/A"
            rp_val = float(raw_rp) if isinstance(raw_rp, (int, float)) else 0.0
            bg_color = (
                "var(--success)"
                if rp_val >= 70
                else "var(--warning)"
                if rp_val >= 50
                else "var(--danger)"
            )
            bar_html = f'<div class="bar"><div class="bar-fill" style="width:{rp_val}%;background:{bg_color}"></div></div>'
            topic_rows.append(
                f"<tr><td>{topic_name}</td><td>{solved}</td><td>{reviews}</td><td>{failed}</td><td>{recall_str}</td><td>{bar_html}</td></tr>"
            )
        topic_table_html = "".join(topic_rows)

        problem_rows = []
        for p in sorted(state.problems.values(), key=lambda x: x.title.casefold()):
            if p.archived:
                continue
            topics_str = html.escape(", ".join(p.topics[:3]))
            sched = state.schedules.get(p.id)
            next_rev = html.escape(sched.next_review[:10]) if sched else ""
            problem_rows.append(
                f"<tr><td>{html.escape(p.title)}</td>"
                f"<td>{html.escape(p.platform)}</td>"
                f'<td><span class="badge badge-{html.escape(p.difficulty)}">{html.escape(p.difficulty)}</span></td>'
                f"<td>{topics_str}</td>"
                f"<td>{len(p.solutions)}</td>"
                f"<td>{next_rev}</td></tr>"
            )
        problem_table_html = "".join(problem_rows)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CodeRecall — Learning Report</title>
<style>
:root {{
    --bg: #0f172a; --surface: #1e293b; --card: #334155;
    --primary: #3b82f6; --success: #22c55e; --warning: #f59e0b;
    --danger: #ef4444; --text: #f1f5f9; --muted: #94a3b8;
    --border: #475569; --glow: rgba(59, 130, 246, 0.2);
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--text); padding: 2rem;
    line-height: 1.6;
}}
.container {{ max-width: 1200px; margin: 0 auto; }}
h1 {{
    font-size: 2.5rem; text-align: center; margin-bottom: 2rem;
    background: linear-gradient(135deg, var(--primary), #8b5cf6);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    font-weight: 800;
}}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }}
.card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 1.5rem;
    box-shadow: 0 4px 24px rgba(0,0,0,0.3);
    transition: transform 0.2s, box-shadow 0.2s;
}}
.card:hover {{ transform: translateY(-4px); box-shadow: 0 8px 32px var(--glow); }}
.card h3 {{ color: var(--primary); margin-bottom: 0.75rem; font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.1em; }}
.stat {{ font-size: 2.5rem; font-weight: 800; }}
.stat.success {{ color: var(--success); }}
.stat.warning {{ color: var(--warning); }}
.stat.danger {{ color: var(--danger); }}
.subtitle {{ color: var(--muted); font-size: 0.875rem; margin-top: 0.25rem; }}
table {{
    width: 100%; border-collapse: collapse; background: var(--surface);
    border-radius: 12px; overflow: hidden; margin-bottom: 2rem;
}}
th {{ background: var(--card); padding: 0.75rem 1rem; text-align: left; color: var(--primary); font-weight: 600; }}
td {{ padding: 0.75rem 1rem; border-top: 1px solid var(--border); }}
tr:hover td {{ background: var(--card); }}
.badge {{
    display: inline-block; padding: 0.25rem 0.75rem; border-radius: 999px;
    font-size: 0.75rem; font-weight: 600;
}}
.badge-easy {{ background: rgba(34,197,94,0.15); color: var(--success); }}
.badge-medium {{ background: rgba(245,158,11,0.15); color: var(--warning); }}
.badge-hard {{ background: rgba(239,68,68,0.15); color: var(--danger); }}
.badge-unknown {{ background: rgba(148,163,184,0.15); color: var(--muted); }}
.bar {{
    height: 8px; border-radius: 4px; background: var(--card); overflow: hidden; margin-top: 0.5rem;
}}
.bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.5s; }}
.achievements {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 2rem; }}
.achievement {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 0.75rem 1rem; font-size: 0.875rem;
}}
.achievement.unlocked {{ border-color: var(--success); background: rgba(34,197,94,0.05); }}
footer {{ text-align: center; color: var(--muted); padding: 2rem 0; font-size: 0.75rem; }}
</style>
</head>
<body>
<div class="container">
<h1>🧠 CodeRecall Learning Report</h1>
<p style="text-align:center;color:var(--muted);margin-bottom:2rem">
Generated {html.escape(now.strftime("%B %d, %Y at %H:%M UTC"))} • Scheduler: {
            html.escape(str(self.config.get("revision.scheduler")))
        }
</p>

<div class="grid">
<div class="card">
    <h3>Problems Solved</h3>
    <div class="stat success">{html.escape(str(stats.get("problems_solved", 0)))}</div>
    <div class="subtitle">{html.escape(str(stats.get("solutions_added", 0)))} total solutions</div>
</div>
<div class="card">
    <h3>Reviews Completed</h3>
    <div class="stat">{html.escape(str(stats.get("reviews_completed", 0)))}</div>
    <div class="subtitle">{html.escape(str(stats.get("hints_used", 0)))} hints used</div>
</div>
<div class="card">
    <h3>Recall Rate</h3>
    <div class="stat {recall_class}">{html.escape(str(stats.get("recall_percent", "N/A")))}{
            "%" if stats.get("recall_percent") is not None else ""
        }</div>
    <div class="subtitle">Target: 90%</div>
</div>
<div class="card">
    <h3>Current Streak</h3>
    <div class="stat warning">🔥 {
            html.escape(str(streak_data.get("current", 0) if isinstance(streak_data, dict) else 0))
        }</div>
    <div class="subtitle">Longest: {
            html.escape(str(streak_data.get("longest", 0) if isinstance(streak_data, dict) else 0))
        } days</div>
</div>
<div class="card">
    <h3>Overdue</h3>
    <div class="stat {overdue_class}">{html.escape(str(overdue_count))}</div>
    <div class="subtitle">problems need review</div>
</div>
<div class="card">
    <h3>Difficulty Spread</h3>
    <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:0.5rem">
        <span class="badge badge-easy">Easy: {problems_by_difficulty.get("easy", 0)}</span>
        <span class="badge badge-medium">Medium: {problems_by_difficulty.get("medium", 0)}</span>
        <span class="badge badge-hard">Hard: {problems_by_difficulty.get("hard", 0)}</span>
    </div>
</div>
</div>

{achievements_html}

<h2 style="margin-bottom:1rem;color:var(--primary)">📊 Topics</h2>
<table>
<tr><th>Topic</th><th>Solved</th><th>Reviews</th><th>Failed</th><th>Recall</th><th>Progress</th></tr>
{topic_table_html}
</table>

<h2 style="margin-bottom:1rem;color:var(--primary)">📋 Problem Catalog</h2>
<table>
<tr><th>Title</th><th>Platform</th><th>Difficulty</th><th>Topics</th><th>Solutions</th><th>Next Review</th></tr>
{problem_table_html}
</table>

<footer>
    CodeRecall v{
            html.escape(__import__("coderecall").__version__)
        } • Private learning data • Do not share publicly
</footer>
</div>
</body>
</html>"""

    def capture_review(self, rid: str) -> dict[str, object]:
        from coderecall.application.catalog import Capture
        from coderecall.integrations.problems import ProblemMetadata

        state = self.store.read()
        recall = state.recalls.get(rid)
        review = next((r for r in state.reviews if r.id == rid), None)
        if recall is None or review is None:
            raise ValidationError("Submit the recall before capturing its code")
        if not review.success:
            raise ValidationError(
                "A failed attempt stays private; capture a corrected solution with add"
            )
        problem = state.problems[recall.problem_id]
        submitted = safe_path(self.root, f".coderecall/workspaces/{rid}/submitted.txt")
        code = (
            submitted.read_text(encoding="utf-8")
            if submitted.exists()
            else self.recall.attempt_code(recall)
        )
        language = next(
            (
                s.language
                for s in problem.solutions
                if s.path.endswith(Path(recall.workspace).suffix)
            ),
            "python",
        )
        capture = Capture(
            ProblemMetadata(
                problem.title,
                problem.platform,
                problem.external_id,
                problem.slug,
                problem.url,
                problem.difficulty,
                problem.topics,
            ),
            language,
            code,
            review.approach or "Recall solution",
            review.complexity or "unknown",
            patterns=problem.patterns,
            tags=problem.tags,
        )
        saved, created = self.catalog.add(capture)
        result: dict[str, object] = {
            "problem_id": saved.id,
            "captured": created,
            "local_saved": True,
        }
        if (
            self.config.get("git.auto_commit")
            and self.config.get("git.strategy") == "solution-and-review"
        ):
            try:
                result["commit_preview"] = self.commit_plan()
                result["commit"] = self.commit(f"recall: {problem.title}")
                if self.config.get("git.auto_push"):
                    result["sync"] = self.sync(fetch=True, execute=True)
            except CodeRecallError as exc:
                result["git_warning"] = str(exc)
        return result

    def add_hint(self, query: str, level: int, text: str) -> None:
        if not 1 <= level <= 4 or not text.strip():
            raise ValidationError("Provide a hint at level 1–4")
        with self.store.transaction() as state:
            problem = identify(state, query)
            while len(problem.hints) < level:
                problem.hints.append("No user hint recorded for this level")
            problem.hints[level - 1] = text

    def add_mistake(self, query: str, text: str, category: str, severity: str) -> None:
        if severity not in {"low", "medium", "high"} or not text.strip():
            raise ValidationError("Provide text and severity low, medium or high")
        with self.store.transaction() as state:
            problem = identify(state, query)
            state.mistakes.append(
                Mistake(problem.id, text, category, severity, self.clock.now().isoformat())
            )

    def daily_commit_due(self) -> bool:
        from coderecall.domain.clock import instant

        activities = self.store.read().activities
        today = self.clock.now().date()
        return (
            bool(self.config.get("git.auto_commit"))
            and self.config.get("git.strategy") == "daily"
            and any(a.kind == "solution" and instant(a.at).date() == today for a in activities)
            and not any(
                a.kind == "git_commit" and instant(a.at).date() == today for a in activities
            )
        )

    # ─── Goals ──────────────────────────────────────────────────────

    def add_goal(self, kind: str, target_type: str, target_value: int) -> Goal:
        """Create a new learning goal."""
        if kind not in {"daily", "weekly", "monthly"}:
            raise ValidationError("Goal kind must be daily, weekly, or monthly")
        if target_type not in {"reviews", "solves", "minutes", "streak"}:
            raise ValidationError("Goal target must be reviews, solves, minutes, or streak")
        if target_value < 1:
            raise ValidationError("Goal target must be positive")

        goal = Goal(
            id="goal_" + uuid4().hex[:12],
            kind=kind,
            target_type=target_type,
            target_value=target_value,
            created_at=self.clock.now().isoformat(),
        )
        with self.store.transaction() as state:
            state.goals.append(goal)
        return goal

    def remove_goal(self, goal_id: str) -> None:
        """Deactivate a goal."""
        with self.store.transaction() as state:
            for goal in state.goals:
                if goal.id == goal_id:
                    goal.active = False
                    return
            raise ValidationError("Goal not found")

    def goals(self) -> list[dict[str, object]]:
        """Return current goal progress."""
        state = self.store.read()
        return goal_progress(state, self.clock.now())

    # ─── Forgetting Curves ──────────────────────────────────────────

    def forgetting_curve(self, query: str) -> list[dict[str, object]]:
        """Get forgetting curve data for a specific problem."""
        state = self.store.read()
        problem = identify(state, query)
        return forgetting_curve(state, problem.id)

    # ─── Batch Operations ───────────────────────────────────────────

    def batch_archive(self, queries: list[str], undo: bool = False) -> dict[str, object]:
        """Archive or unarchive multiple problems at once."""
        results: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        with self.store.transaction() as state:
            for query in queries:
                try:
                    problem = identify(state, query)
                    if problem.archived != (not undo):
                        problem.archived = not undo
                        state.activities.append(
                            Activity(
                                "archive" if not undo else "unarchive",
                                problem.id,
                                self.clock.now().isoformat(),
                            )
                        )
                    results.append({"id": problem.id, "title": problem.title, "archived": not undo})
                except CodeRecallError as exc:
                    errors.append({"query": query, "error": str(exc)})
        return {"processed": results, "errors": errors}

    def batch_reschedule(self, queries: list[str], days: int) -> dict[str, object]:
        """Reschedule multiple problems at once."""
        if not 1 <= days <= 365:
            raise ValidationError("Days must be 1–365")
        results: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        with self.store.transaction() as state:
            for query in queries:
                try:
                    problem = identify(state, query)
                    schedule = state.schedules[problem.id]
                    schedule.next_review = (self.clock.now() + timedelta(days=days)).isoformat()
                    results.append(
                        {
                            "id": problem.id,
                            "title": problem.title,
                            "next_review": schedule.next_review,
                        }
                    )
                except CodeRecallError as exc:
                    errors.append({"query": query, "error": str(exc)})
        return {"processed": results, "errors": errors}


def doctor(root: Path) -> dict[str, object]:
    checks: list[dict[str, str]] = []
    checks.append({"check": "Python", "status": "ok", "detail": sys.version.split()[0]})
    for command in ["git", "gh", "docker"]:
        checks.append(
            {
                "check": command,
                "status": "ok" if shutil.which(command) else "warning",
                "detail": "available" if shutil.which(command) else "not installed (optional)",
            }
        )
    try:
        project = Project(root)
        state = project.store.read()
        checks.append({"check": "state/config/schema", "status": "ok", "detail": "validated"})
        missing = [p for p in owned_paths(state) if not safe_path(project.root, p).is_file()]
        checks.append(
            {
                "check": "owned files",
                "status": "error" if missing else "ok",
                "detail": f"{len(missing)} missing",
            }
        )
        missing_workspaces = sum(
            not safe_path(project.root, r.workspace).is_file()
            for r in state.recalls.values()
            if not r.completed
        )
        checks.append(
            {
                "check": "active recall workspaces",
                "status": "warning" if missing_workspaces else "ok",
                "detail": f"{missing_workspaces} missing",
            }
        )
        checks.append(
            {
                "check": "permissions",
                "status": "ok" if os.access(project.store.directory, os.W_OK) else "error",
                "detail": "state directory write access",
            }
        )
        checks.append(
            {
                "check": "repository",
                "status": "ok" if project.git.available() else "warning",
                "detail": "Git repository detection",
            }
        )
        checks.append(
            {
                "check": "GitHub credentials",
                "status": "info",
                "detail": "not probed offline; github status explicitly checks authentication",
            }
        )
        checks.append(
            {
                "check": "AI",
                "status": "info",
                "detail": "enabled" if project.config.get("ai.enabled") else "disabled",
            }
        )
        checks.append(
            {
                "check": "sandbox",
                "status": "info",
                "detail": "enabled" if project.config.get("execution.enabled") else "disabled",
            }
        )
        checks.append(
            {
                "check": "scheduler",
                "status": "ok",
                "detail": str(project.config.get("revision.scheduler")),
            }
        )
        editor = str(project.config.get("repository.editor")) or os.environ.get("EDITOR", "")
        checks.append(
            {
                "check": "editor",
                "status": "ok" if editor else "warning",
                "detail": "configured" if editor else "set EDITOR",
            }
        )
        checks.append(
            {
                "check": "achievements",
                "status": "ok",
                "detail": f"{len(state.achievements)} unlocked",
            }
        )
        backups_dir = project.store.path("backups")
        if backups_dir.is_dir():
            backups = list(backups_dir.glob("backup-*.zip"))
            checks.append(
                {
                    "check": "backups",
                    "status": "ok" if backups else "warning",
                    "detail": f"{len(backups)} available"
                    if backups
                    else "no backups made yet (run coderecall backup)",
                }
            )
        else:
            checks.append(
                {
                    "check": "backups",
                    "status": "warning",
                    "detail": "no backups directory (run coderecall backup)",
                }
            )
        journal = project.store.path("transaction.json")
        checks.append(
            {
                "check": "pending transactions",
                "status": "warning" if journal.exists() else "ok",
                "detail": "unrecovered transaction pending" if journal.exists() else "none",
            }
        )
    except (CodeRecallError, OSError) as exc:
        checks.append({"check": "project", "status": "error", "detail": str(exc)})
    return {
        "checks": checks,
        "errors": sum(c["status"] == "error" for c in checks),
        "warnings": sum(c["status"] == "warning" for c in checks),
    }
