from dataclasses import asdict

import typer

from coderecall.application.project import Project
from coderecall.cli.output import emit, options
from coderecall.domain.analytics import streak as streak_data
from coderecall.domain.analytics import topic_stats
from coderecall.domain.errors import ValidationError
from coderecall.storage.paths import safe_path


def today(ctx: typer.Context) -> None:
    """Show due reviews and explain deterministic recommendations."""
    emit(ctx, Project().today())


def stats(
    ctx: typer.Context,
    today: bool = typer.Option(False, "--today", help="Show stats for today only"),
    week: bool = typer.Option(False, "--week", help="Show stats for the last 7 days"),
    month: bool = typer.Option(False, "--month", help="Show stats for the last 30 days"),
    year: bool = typer.Option(False, "--year", help="Show stats for the last 365 days"),
    all_time: bool = typer.Option(False, "--all-time", help="Show all-time stats (default)"),
) -> None:
    """Show measured local practice statistics."""
    from datetime import timedelta

    from rich.console import Console
    from rich.table import Table

    from coderecall.domain.analytics import statistics

    project = Project()
    now = project.clock.now()

    since = None
    if today:
        since = now - timedelta(days=1)
    elif week:
        since = now - timedelta(days=7)
    elif month:
        since = now - timedelta(days=30)
    elif year:
        since = now - timedelta(days=365)

    # if all_time or no flag provided, since remains None

    state = project.store.read()
    result = statistics(state, now, str(project.config.get("streak.activities")), since)

    if options(ctx).json:
        emit(ctx, result)
        return

    console = Console()
    console.print("[bold]Learning Analytics[/bold]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row("Problems Solved", str(result.get("problems_solved", 0)))
    table.add_row("Reviews Completed", str(result.get("reviews_completed", 0)))

    recall = result.get("recall_percent")
    table.add_row("Recall Accuracy", f"{recall}%" if recall is not None else "N/A")

    streak = result.get("streak", {})
    if isinstance(streak, dict):
        table.add_row("Current Streak", f"{streak.get('current', 0)} days")
        table.add_row("Longest Streak", f"{streak.get('longest', 0)} days")

    avg_solve = result.get("average_solve_seconds")
    table.add_row("Avg Solve Time", f"{avg_solve}s" if avg_solve is not None else "N/A")

    avg_rev = result.get("average_review_seconds")
    table.add_row("Avg Review Time", f"{avg_rev}s" if avg_rev is not None else "N/A")

    table.add_row("Hints Used", str(result.get("hints_used", 0)))
    table.add_row("Total Attempts", str(result.get("attempts", 0)))
    table.add_row("Overdue Reviews", str(result.get("overdue", 0)))

    console.print(table)


def topics(ctx: typer.Context) -> None:
    """Topic recall = successful reviews / completed reviews; no invented mastery score."""
    from rich.console import Console

    stats = topic_stats(Project().store.read())

    if options(ctx).json:
        emit(ctx, stats)
        return

    # Sort by recall rate descending, handle None
    def sort_key(s: dict[str, object]) -> float:
        val = s.get("recall_percent")
        return float(str(val)) if val is not None else -1.0

    sorted_stats = sorted(stats, key=sort_key, reverse=True)

    console = Console()
    console.print("[bold]Topics (by recall rate)[/bold]\n")

    for i, stat in enumerate(sorted_stats, 1):
        topic_name = stat["topic"]
        recall = stat["recall_percent"]
        reviews = stat["reviews"]
        recall_str = f"{recall}%" if recall is not None else "N/A"
        console.print(f"{i}. {str(topic_name):<16} {recall_str:<4} ({reviews} reviews)")


def streak(ctx: typer.Context) -> None:
    """Show genuine activity dates and UTC streaks."""
    project = Project()
    emit(
        ctx,
        streak_data(
            project.store.read(), project.clock.now(), str(project.config.get("streak.activities"))
        ),
    )


def weak(ctx: typer.Context) -> None:
    """Analyze learning history to identify weak areas and recurring mistakes."""
    from rich.console import Console
    from rich.panel import Panel

    from coderecall.domain.analytics import weakness_detection

    project = Project()
    state = project.store.read()
    now = project.clock.now()
    weaknesses = weakness_detection(state, now)

    if options(ctx).json:
        emit(ctx, weaknesses)
        return

    console = Console()
    if not weaknesses:
        console.print(
            Panel(
                "[green]No specific weaknesses detected! Keep practicing.[/green]",
                title="Weakness Report",
            )
        )
        return

    topics = [w for w in weaknesses if w["type"] == "topic"]
    mistakes = [w for w in weaknesses if w["type"] == "mistake_pattern"]
    hard = [w for w in weaknesses if w["type"] == "hard_problem"]

    if topics:
        console.print("[bold red]Weak Areas[/bold red]")
        for t in topics:
            console.print(f"{str(t['name']):<25} {t['recall_rate']}%")
        console.print()

    if mistakes:
        console.print("[bold yellow]Recurring Mistakes[/bold yellow]")
        for m in mistakes:
            console.print(
                f"{str(m['name']):<25} {m['occurrences']}%"
            )  # Displayed as % to match prompt example roughly or just occurrences
        console.print()

    recommendations = []
    if topics:
        recommendations.append(f"Review {topics[0]['name']} fundamentals")
        recommendations.append(f"solve 3 easy {topics[0]['name']} problems")
    if mistakes:
        recommendations.append(f"review {mistakes[0]['name']}")
    if hard:
        recommendations.append("attempt one medium problem")

    if recommendations:
        console.print("[bold blue]Recommended action:[/bold blue]")
        console.print(" -> ".join(recommendations))


def summary(ctx: typer.Context, week: bool = True) -> None:
    """Summarize the last seven days (--no-week includes all history)."""
    emit(ctx, Project().stats(week))


def active_flow(ctx: typer.Context, id: str, mode: str, minutes: int) -> None:
    project = Project()
    if options(ctx).dry_run:
        emit(ctx, {"would_start": id or "first due problem", "mode": mode})
        return
    result = project.recall.start(id, mode, minutes)
    emit(ctx, result)
    if options(ctx).non_interactive or options(ctx).json:
        return
    rid = str(result["recall_id"])
    mode = str(result["mode"])
    while True:
        action = typer.prompt(
            "[e] Edit blank workspace [h] Hint [s] Submit [p] Pause [c] Continue [r] Reveal [q] Quit",
            err=True,
        ).lower()
        if action == "q":
            project.recall.pause(rid)
            emit(ctx, "Paused. Resume with coderecall recall resume " + rid)
            return
        if action == "e":
            project.open_editor(safe_path(project.root, str(result["workspace"])))
        elif action in {"h", "r"}:
            if mode == "interview":
                emit(ctx, "Hints/reveal are disabled in interview mode")
            else:
                emit(ctx, project.recall.hint(rid, action == "r"))
        elif action in {"p", "c"}:
            emit(ctx, project.recall.pause(rid, action == "c"))
        elif action == "s":
            success = typer.confirm("Solved successfully? (self-assessment)", err=True)
            confidence = typer.prompt("Confidence (1–5)", type=int, err=True)
            attempts = typer.prompt("Attempts", default=1, type=int, err=True)
            approach = (
                typer.prompt("Explain your approach", err=True) if mode == "interview" else ""
            )
            complexity = typer.prompt("Explain complexity", err=True) if mode == "interview" else ""
            verbal = False
            if (
                success
                and not safe_path(project.root, str(result["workspace"]))
                .read_text(encoding="utf-8")
                .strip()
            ):
                verbal = typer.confirm(
                    "No code saved. Record an explanation-only assessment?", default=False, err=True
                )
                if not verbal:
                    emit(ctx, "Save your attempt before submitting a pass.")
                    continue
                approach = approach or typer.prompt("Explain your approach", err=True)
            emit(
                ctx,
                project.recall.submit(
                    rid,
                    success,
                    confidence,
                    attempts,
                    approach=approach,
                    complexity=complexity,
                    verbal=verbal,
                ),
            )
            return


def revise(ctx: typer.Context, id: str = typer.Argument("")) -> None:
    """Start active recall; old source stays hidden until explicit reveal."""
    active_flow(ctx, id, "recall", 30)


def solve(ctx: typer.Context, id: str) -> None:
    """Start a blank timed practice attempt for a stored problem."""
    active_flow(ctx, id, "solve", 30)


def interview(
    ctx: typer.Context, id: str = typer.Argument(""), minutes: int = 30, seed: int | None = None
) -> None:
    """Timed interview practice with hints disabled and explanation required."""
    if not id:
        id = Project().random_problem(seed).id
    active_flow(ctx, id, "interview", minutes)


def submit(
    ctx: typer.Context,
    recall_id: str,
    result: str = typer.Option(..., "--result"),
    confidence: int = typer.Option(..., "--confidence"),
    attempts: int = 1,
    seconds: int | None = None,
    note: str = "",
    mistake: str = "",
    approach: str = "",
    complexity: str = "",
    verbal: bool = False,
) -> None:
    """Record self-assessed pass/fail. Repeating the same recall ID is idempotent."""
    if result not in {"pass", "fail"}:
        raise ValidationError("Result must be pass or fail")
    if options(ctx).dry_run:
        emit(ctx, {"would_submit": recall_id, "result": result})
        return
    emit(
        ctx,
        Project().recall.submit(
            recall_id,
            result == "pass",
            confidence,
            attempts,
            seconds,
            note,
            mistake,
            approach,
            complexity,
            verbal,
        ),
    )


def hint(ctx: typer.Context, recall_id: str, reveal: bool = False) -> None:
    """Advance one hint level; --reveal explicitly shows the previous solution."""
    if options(ctx).dry_run:
        emit(ctx, {"would_hint": recall_id})
    else:
        emit(ctx, Project().recall.hint(recall_id, reveal))


def pause(ctx: typer.Context, recall_id: str) -> None:
    if options(ctx).dry_run:
        emit(ctx, {"would_pause": recall_id})
    else:
        emit(ctx, Project().recall.pause(recall_id))


def resume(ctx: typer.Context, recall_id: str) -> None:
    if options(ctx).dry_run:
        emit(ctx, {"would_resume": recall_id})
    else:
        emit(ctx, Project().recall.pause(recall_id, True))


def compare(ctx: typer.Context, recall_id: str) -> None:
    emit(ctx, Project().recall.compare(recall_id))


def cancel(ctx: typer.Context, recall_id: str) -> None:
    emit(
        ctx,
        {"would_cancel": recall_id} if options(ctx).dry_run else Project().recall.cancel(recall_id),
    )


def capture(ctx: typer.Context, recall_id: str, yes: bool = False) -> None:
    """Explicitly promote a successful private attempt to public solution files."""
    from coderecall.cli.output import confirm

    if options(ctx).dry_run:
        emit(ctx, {"would_capture_review": recall_id, "public_code": True})
    elif confirm(
        ctx, "Save this attempt as public solution code and apply the configured Git policy?", yes
    ):
        emit(ctx, Project().capture_review(recall_id))


def schedule(ctx: typer.Context, action: str, id: str, days: int = 1) -> None:
    """Explicit schedule actions: skip, suspend, resume, reschedule, reset."""
    if options(ctx).dry_run:
        emit(ctx, {"would_schedule": id, "action": action, "days": days})
    else:
        emit(ctx, asdict(Project().recall.schedule_action(id, action, days)))


def mistake(
    ctx: typer.Context, id: str, text: str, category: str = "edge-case", severity: str = "medium"
) -> None:
    """Record a private, categorized mistake for recurring-mistake analytics."""
    project = Project()
    if not options(ctx).dry_run:
        project.add_mistake(id, text, category, severity)
    emit(ctx, {"recorded": not options(ctx).dry_run, "private": True})


def session_action(ctx: typer.Context, action: str, note: str = "") -> None:
    """Start/stop/status. Idle empty sessions do not count toward streaks."""
    if options(ctx).dry_run and action != "status":
        emit(ctx, {"would_session": action})
    else:
        project = Project()
        result = project.recall.session(action, note)
        if action == "stop" and project.daily_commit_due():
            from coderecall.domain.errors import CodeRecallError

            try:
                paths = project.commit_plan()
                if not options(ctx).json and not options(ctx).quiet:
                    emit(ctx, {"will_commit": paths})
                result["commit_preview"] = paths
                result["commit"] = project.commit("practice: daily solution updates")
            except CodeRecallError as exc:
                result["git_warning"] = str(exc)
        emit(ctx, result)


def goal_add(
    ctx: typer.Context,
    kind: str = typer.Argument(..., help="daily, weekly, or monthly"),
    target_type: str = typer.Argument(..., help="reviews, solves, minutes, or streak"),
    target_value: int = typer.Argument(..., help="Target number"),
) -> None:
    """Set a learning goal (daily/weekly/monthly reviews/solves/minutes/streak)."""
    if options(ctx).dry_run:
        emit(ctx, {"would_create_goal": kind, "target": f"{target_value} {target_type}"})
    else:
        goal = Project().add_goal(kind, target_type, target_value)
        emit(ctx, asdict(goal))


def goal_list(ctx: typer.Context) -> None:
    """Show current goal progress."""
    emit(ctx, Project().goals())


def goal_remove(ctx: typer.Context, goal_id: str) -> None:
    """Deactivate a goal."""
    if options(ctx).dry_run:
        emit(ctx, {"would_remove_goal": goal_id})
    else:
        Project().remove_goal(goal_id)
        emit(ctx, {"removed": goal_id})


def achievements(ctx: typer.Context) -> None:
    """Show unlocked achievements and badges."""
    state = Project().store.read()
    emit(ctx, [asdict(a) for a in state.achievements])


def curve(ctx: typer.Context, id: str) -> None:
    """Show forgetting curve data for a specific problem."""
    emit(ctx, Project().forgetting_curve(id))


def register(app: typer.Typer) -> None:
    for function in [
        today,
        stats,
        topics,
        streak,
        summary,
        revise,
        solve,
        interview,
        schedule,
        mistake,
        achievements,
        curve,
        weak,
    ]:
        app.command()(function)  # type: ignore[type-var]
    group = typer.Typer(help="Manage a resumable recall attempt.")
    for function in [submit, hint, pause, resume, compare, cancel, capture]:
        group.command()(function)  # type: ignore[type-var]
    app.add_typer(group, name="recall")
    app.command("session")(session_action)

    # Goals sub-group
    goals = typer.Typer(help="Set and track learning goals.")
    goals.command("add")(goal_add)
    goals.command("list")(goal_list)
    goals.command("remove")(goal_remove)
    app.add_typer(goals, name="goal")
    app.command("review")(revise)
    app.command("analytics")(stats)
