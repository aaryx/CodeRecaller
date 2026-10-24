import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

import typer

from coderecall.application.catalog import Capture, identify, validate_capture
from coderecall.application.importer import apply_import, scan
from coderecall.application.project import Project
from coderecall.cli.output import confirm, emit, options
from coderecall.domain.errors import CodeRecallError, ValidationError
from coderecall.domain.models import Problem
from coderecall.domain.validation import LANGUAGES, slugify, validate_url
from coderecall.integrations.problems import LeetCodeProvider, ProblemMetadata


def split(value: str) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in value.split(",") if v.strip()))


def rows(problems: list[Problem]) -> list[dict[str, object]]:
    return [
        {"id": p.id, "title": p.title, "difficulty": p.difficulty, "topics": p.topics}
        for p in problems
    ]


def add(
    ctx: typer.Context,
    title: str = "",
    url: str = "",
    file: Path | None = None,
    language: str = "",
    platform: str = "custom",
    external_id: str = "",
    difficulty: str = "unknown",
    topics: str = "",
    patterns: str = "",
    tags: str = "",
    labels: str = "",
    approach: str = "",
    time_complexity: str = "unknown",
    space_complexity: str = "unknown",
    note: str = "",
    seconds: int = 0,
    attempts: int = 1,
    fetch: bool = False,
    stdin: bool = False,
    no_commit: bool = False,
) -> None:
    """Capture a solution offline. --fetch explicitly requests LeetCode metadata."""
    project = Project()
    opts = options(ctx)
    guided = (
        not title
        and not url
        and file is None
        and not stdin
        and not opts.json
        and not opts.non_interactive
    )
    if url:
        validate_url(url)
        if urlsplit(url).hostname in {"leetcode.com", "www.leetcode.com"}:
            platform = "leetcode"
            validate_url(url, leetcode=True)
            if not title:
                title = urlsplit(url).path.split("/")[2].replace("-", " ").title()
    meta = ProblemMetadata(title, platform, external_id, "", url, difficulty, split(topics))
    warning = ""
    if fetch:
        try:
            meta = LeetCodeProvider().fetch(url)
        except CodeRecallError as exc:
            warning = str(exc)
    if not meta.title:
        if opts.json or opts.non_interactive:
            raise ValidationError("Supply --title or --url")
        meta.title = typer.prompt("Problem title", err=True)
    if stdin:
        code = sys.stdin.read(2 * 1024 * 1024 + 1)
    else:
        if file is None:
            if opts.json or opts.non_interactive:
                raise ValidationError("Supply --file or --stdin")
            file = Path(typer.prompt("Solution file", err=True))
        if not file.is_file() or file.is_symlink() or file.stat().st_size > 2 * 1024 * 1024:
            raise ValidationError("Solution file must be a regular file at most 2 MiB")
        code = file.read_text(encoding="utf-8")
        language = language or next(
            (name for name, pair in LANGUAGES.items() if pair[0] == file.suffix.lower()), ""
        )
    if not language:
        if opts.json or opts.non_interactive:
            raise ValidationError("Supply --language")
        language = typer.prompt("Language", default="python", err=True)
    if guided:
        meta.external_id = typer.prompt(
            "External problem ID (optional)", default=external_id, err=True
        )
        meta.platform = typer.prompt("Platform", default=platform, err=True)
        meta.difficulty = typer.prompt(
            "Difficulty: unknown/easy/medium/hard", default=difficulty, err=True
        )
        meta.topics = split(typer.prompt("Topics (comma-separated)", default=topics, err=True))
        patterns = typer.prompt("Patterns (comma-separated)", default=patterns, err=True)
        approach = typer.prompt("Public approach description", default=approach, err=True)
        time_complexity = typer.prompt("Time complexity", default=time_complexity, err=True)
        space_complexity = typer.prompt("Space complexity", default=space_complexity, err=True)
        note = typer.prompt("Private note", default=note, err=True)
        seconds = typer.prompt(
            "Solve time in seconds (0 = unmeasured)", default=seconds, type=int, err=True
        )
        attempts = typer.prompt("Attempts", default=attempts, type=int, err=True)
    capture = Capture(
        meta,
        language,
        code,
        approach,
        time_complexity,
        space_complexity,
        note,
        split(patterns),
        split(tags),
        split(labels),
        seconds,
        attempts,
    )
    validate_capture(capture)
    if opts.dry_run:
        emit(
            ctx,
            {
                "dry_run": True,
                "title": meta.title,
                "language": language,
                "slug": slugify(meta.title),
            },
        )
        return
    problem, created = project.catalog.add(capture)
    result: dict[str, object] = {
        "problem_id": problem.id,
        "created": created,
        "solutions": [s.path for s in problem.solutions],
    }
    if warning:
        result["metadata_warning"] = warning
    strategy = project.config.get("git.strategy")
    if (
        created
        and not no_commit
        and project.config.get("git.auto_commit")
        and strategy in {"every-solution", "solution-and-review"}
    ):
        try:
            if project.git.available():
                paths = project.commit_plan()
                if not opts.json and not opts.quiet:
                    typer.echo("Committing owned files:\n" + "\n".join(paths), err=True)
                result["commit_preview"] = paths
                result["commit"] = project.commit(f"solve: {problem.title}")
                if project.config.get("git.auto_push"):
                    result["sync"] = project.sync(fetch=True, execute=True)
        except CodeRecallError as exc:
            result["git_warning"] = str(exc)
            result["local_saved"] = True
    emit(ctx, result)


def problems(
    ctx: typer.Context,
    difficulty: str = "",
    topic: str = "",
    language: str = "",
    pattern: str = "",
    due: bool = False,
    failed: bool = False,
    unreviewed: bool = False,
    overdue: bool = False,
    archived: bool = False,
) -> None:
    """List and filter the local catalog."""
    result = Project().list_problems(
        difficulty=difficulty,
        topic=topic,
        language=language,
        pattern=pattern,
        due_only=due,
        failed=failed,
        unreviewed=unreviewed,
        overdue=overdue,
        archived=archived,
    )
    emit(ctx, rows(list(result)))


def problem(ctx: typer.Context, id: str) -> None:
    """Show a problem's metadata and private notes; never print source code."""
    project = Project()
    state = project.store.read()
    item = identify(state, id)
    emit(ctx, {"problem": asdict(item), "schedule": asdict(state.schedules[item.id])})


def search(ctx: typer.Context, query: str) -> None:
    """Search local titles, IDs, topics, patterns, languages, tags and notes."""
    emit(ctx, rows(list(Project().list_problems(query=query))))


def import_repository(
    ctx: typer.Context,
    path: Path,
    yes: bool = False,
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Preview and import existing code as data; never execute repository content."""
    project = Project()
    plan = scan(path)
    if dry_run or options(ctx).dry_run:
        emit(ctx, plan.summary())
        return
    if not options(ctx).json:
        emit(ctx, plan.summary())
    if confirm(ctx, "Import these files into the configured layout?", yes):
        emit(ctx, apply_import(project.catalog, plan))


def edit(ctx: typer.Context, id: str) -> None:
    """Open the latest stored solution in EDITOR (this reveals the solution)."""
    if options(ctx).dry_run:
        emit(ctx, {"would_edit": id})
    elif options(ctx).json or options(ctx).non_interactive:
        raise ValidationError("Editor requires interactive mode")
    else:
        emit(ctx, Project().edit(id))


def note(ctx: typer.Context, id: str, text: str = "", hint_level: int = 0) -> None:
    """Append a private note or set a private hint level (1–4)."""
    project = Project()
    if not text:
        emit(ctx, {"notes": identify(project.store.read(), id).notes})
        return
    if options(ctx).dry_run:
        emit(ctx, {"would_annotate": id})
        return
    if hint_level:
        project.add_hint(id, hint_level, text)
    else:
        project.catalog.annotate(id, text)
    emit(ctx, {"saved": True, "private": True})


def archive(ctx: typer.Context, id: str, undo: bool = False) -> None:
    """Archive without deleting; --undo returns a problem to the catalog."""
    if not options(ctx).dry_run:
        Project().catalog.archive(id, not undo)
    emit(ctx, {"id": id, "archived": not undo, "dry_run": options(ctx).dry_run})


def random_problem(
    ctx: typer.Context,
    difficulty: str = "",
    topic: str = "",
    pattern: str = "",
    language: str = "",
    weak: bool = False,
    unsolved: bool = False,
    seed: int | None = None,
) -> None:
    """Select a practice problem; --seed is reproducible for a stable catalog."""
    p = Project().random_problem(
        seed,
        weak,
        difficulty=difficulty,
        topic=topic,
        pattern=pattern,
        language=language,
        unsolved=unsolved,
    )
    emit(ctx, {"id": p.id, "title": p.title, "difficulty": p.difficulty, "topics": p.topics})


def analyze(
    ctx: typer.Context,
    file: Path,
    time_complexity: str = "unknown",
    space_complexity: str = "unknown",
) -> None:
    """Report user-provided complexity without executing or guessing about code."""
    if not file.is_file():
        raise ValidationError("Solution file not found")
    language = next((k for k, v in LANGUAGES.items() if v[0] == file.suffix.lower()), "unknown")
    emit(
        ctx,
        {
            "language": language,
            "time": time_complexity,
            "space": space_complexity,
            "source": "user-provided",
            "correctness_verified": False,
        },
    )


def register(app: typer.Typer) -> None:
    for function in [add, problems, problem, search, edit, note, archive, analyze]:
        app.command()(function)  # type: ignore[type-var]
    app.command("import")(import_repository)
    app.command("random")(random_problem)
    app.command("list")(problems)
    app.command("show")(problem)
