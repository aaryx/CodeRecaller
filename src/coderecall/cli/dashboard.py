import json

import typer
from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from coderecall.application.project import Project
from coderecall.cli.output import options
from coderecall.domain.analytics import streak as streak_data
from coderecall.domain.analytics import topic_stats


def _can_encode(text: str, console: Console) -> bool:
    encoding = console.encoding or getattr(console.file, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _progress_bar(percentage: int, width: int = 15, unicode_ok: bool = True) -> str:
    filled = int((percentage / 100) * width)
    empty = width - filled
    if unicode_ok:
        return "█" * filled + "░" * empty
    return "#" * filled + "-" * empty


def render_dashboard(ctx: typer.Context) -> None:
    project = Project()
    state = project.store.read()
    now = project.clock.now()

    # Gather data
    opts = options(ctx)
    today_data = project.today()
    streak_info = streak_data(state, now, str(project.config.get("streak.activities")))

    current_streak = streak_info.get("current", 0) if isinstance(streak_info, dict) else 0
    due_today = len(today_data.get("reviews", []))  # type: ignore
    weak_topics_list = today_data.get("weak_topics", [])

    weak_topic_name = "None"
    if isinstance(weak_topics_list, list) and weak_topics_list:
        weak_topic_name = weak_topics_list[0].get("topic", "None")

    # Calculate global retention
    t_stats = topic_stats(state)
    total_reviews = sum(int(t.get("reviews", 0)) for t in t_stats)  # type: ignore
    total_failed = sum(int(t.get("failed", 0)) for t in t_stats)  # type: ignore
    total_successes = total_reviews - total_failed
    global_retention = (total_successes / total_reviews * 100) if total_reviews > 0 else 0.0

    if opts.json:
        typer.echo(
            json.dumps(
                {
                    "streak": current_streak,
                    "due_today": due_today,
                    "retention_percent": round(global_retention, 1),
                    "weak_topic": weak_topic_name,
                    "topics": t_stats,
                }
            )
        )
        return

    console = Console(no_color=opts.no_color)
    unicode_ok = _can_encode("🔥█╭", console)

    # 1. Header Section
    header = Text("CODE RECALL\nPersonal Coding Intelligence", justify="left", style="bold")

    # 2. Stats Section
    stats_table = Table.grid(padding=(0, 2))
    stats_table.add_column(style="bold")
    stats_table.add_column()

    streak_label = "🔥 Streak" if unicode_ok else "Streak"
    due_label = "📚 Due Today" if unicode_ok else "Due Today"
    retention_label = "🧠 Retention" if unicode_ok else "Retention"
    weak_label = "⚠ Weak Topic" if unicode_ok else "Weak Topic"

    stats_table.add_row(streak_label, f"{current_streak} days")
    stats_table.add_row(due_label, str(due_today))
    stats_table.add_row(retention_label, f"{global_retention:.1f}%")
    stats_table.add_row(weak_label, str(weak_topic_name))

    # 3. Today Section
    today_table = Table(box=None, show_header=False, expand=True)
    today_table.add_column(justify="left")
    today_table.add_column(justify="left")
    today_table.add_column(justify="left")
    today_table.add_column(justify="right")

    reviews = list(today_data.get("reviews", []))  # type: ignore
    if not reviews:
        empty_msg = "No reviews due today! 🎉" if unicode_ok else "No reviews due today!"
        today_table.add_row(empty_msg, "", "", "")
    else:
        for idx, r in enumerate(reviews[:5]):
            p = state.problems.get(r["id"])
            if not p:
                continue
            due_str = "Overdue" if r["due"] < now.isoformat() else "Due"
            today_table.add_row(f"{idx + 1:02d}", p.title, p.difficulty.title(), due_str)
        if len(reviews) > 5:
            today_table.add_row("...", f"+{len(reviews) - 5} more", "", "")

    # 4. Performance Section
    perf_table = Table(box=None, show_header=False, expand=True)
    perf_table.add_column(justify="left")
    perf_table.add_column(justify="left")
    perf_table.add_column(justify="right")

    for t in sorted(t_stats, key=lambda x: str(x["topic"])):
        recall = t.get("recall_percent")
        if recall is None:
            continue
        bar = _progress_bar(int(recall), unicode_ok=unicode_ok)  # type: ignore
        perf_table.add_row(str(t["topic"]).title(), bar, f"{recall}%")

    if not t_stats:
        perf_table.add_row("No topic performance data yet.", "", "")

    # Layout Assembly
    group = Group(
        header,
        Text(""),
        stats_table,
        Text(""),
        Text("TODAY", style="bold dim"),
        Text(""),
        today_table,
        Text(""),
        Text("PERFORMANCE", style="bold dim"),
        Text(""),
        perf_table,
    )

    panel_box = box.ROUNDED if unicode_ok else box.ASCII
    panel = Panel(
        group,
        expand=False,
        box=panel_box,
        width=50,
    )
    console.print(Align.left(panel))


def register(app: typer.Typer) -> None:
    app.command(name="dashboard", help="Show the interactive learning dashboard.")(render_dashboard)
