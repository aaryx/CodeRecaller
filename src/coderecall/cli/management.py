import json
from dataclasses import asdict
from pathlib import Path

import typer

from coderecall import __version__
from coderecall.application.catalog import owned_paths
from coderecall.application.project import Project
from coderecall.application.project import doctor as inspect_project
from coderecall.cli.output import confirm, emit, options
from coderecall.domain.errors import ValidationError
from coderecall.execution.runner import UnavailableRunner
from coderecall.integrations.git import LocalGitProvider
from coderecall.integrations.github import GitHubProvider
from coderecall.storage.backup import backup as make_backup
from coderecall.storage.backup import restore as restore_backup
from coderecall.storage.backup import validate_archive
from coderecall.storage.config import Config
from coderecall.storage.local import LocalStore, discover
from coderecall.storage.paths import create_or_match


def init(ctx: typer.Context, git_init: bool = False, yes: bool = False) -> None:
    """Create private local state and ignore it in Git; never overwrite initialization."""
    root = Path.cwd()
    git = LocalGitProvider(root)
    if options(ctx).dry_run:
        emit(
            ctx,
            {
                "would_create": [
                    ".coderecall/config.toml",
                    ".coderecall/manifest.json",
                    ".coderecall/state.json",
                ],
                "would_update": ".gitignore",
            },
        )
        return
    from coderecall.domain.errors import ProviderError

    try:
        available = git.available()
    except ProviderError:
        available = False
    if available and Path(git.command("rev-parse", "--show-toplevel")).resolve() != root.resolve():
        raise ValidationError(
            "Initialize CodeRecall at the Git repository root, not a subdirectory"
        )
    if not available:
        if git_init or (
            not options(ctx).non_interactive
            and not options(ctx).json
            and confirm(ctx, "Initialize Git here?", yes)
        ):
            git.command("init")
    LocalStore(root).initialize()
    emit(
        ctx,
        {
            "initialized": str(root),
            "state": ".coderecall/",
            "privacy": "Entire local learning state ignored by Git",
            "ready": True,
        },
    )


def status(ctx: typer.Context) -> None:
    emit(ctx, Project().status())


def doctor(
    ctx: typer.Context,
    migrate: bool = False,
    yes: bool = False,
    languages: bool = typer.Option(
        False, "--languages", help="Check installed language registry sandboxes"
    ),
) -> None:
    """Inspect local health without network calls; optionally migrate known old schemas."""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    if languages:
        import shutil

        from coderecall.integrations.process import run

        console.print("[bold]Enabled Languages:[/bold]")
        has_docker = shutil.which("docker") is not None

        # In a real environment, we'd query versions dynamically or have a richer manifest.
        # Here we just check docker images.
        targets = {
            "python": ("Python 3.14", "coderecall/python:latest"),
            "java": ("Java 21", "coderecall/java:latest"),
            "cpp": ("C++ 20", "coderecall/cpp:latest"),
            "rust": ("Rust 1.76", "coderecall/rust:latest"),
        }
        for _key, (display, image) in targets.items():
            if not has_docker:
                console.print(f"○ {display:<11} (Docker unavailable)")
                continue

            res = run("docker", ["images", "-q", image], Path.cwd(), timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                console.print(f"[green]✓[/green] {display:<11} ({image})")
            else:
                console.print(f"○ {display:<11} (Not pulled)")
        return

    if migrate and confirm(ctx, "Back up and migrate local state?", yes):
        emit(ctx, {"migration": LocalStore(discover(Path.cwd())).migrate()})
        return

    result = inspect_project(Path.cwd())
    if options(ctx).json:
        emit(ctx, result)
        if result["errors"]:
            raise typer.Exit(9)
        return

    console.print(f"Errors    {result['errors']}")
    console.print(f"Warnings  {result['warnings']}\n")
    console.print("[bold]Checks[/bold]")

    table = Table(box=None)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    checks = result.get("checks", [])
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict):
                status = check.get("status", "")
                if status == "ok":
                    status = "[green]ok[/green]"
                elif status == "warning":
                    status = "[yellow]warning[/yellow]"
                elif status == "error":
                    status = "[red]error[/red]"
                elif status == "info":
                    status = "[blue]info[/blue]"

                table.add_row(str(check.get("check")), status, str(check.get("detail")))
    console.print(table)

    if result["errors"]:
        raise typer.Exit(9)


def version(ctx: typer.Context) -> None:
    emit(ctx, {"version": __version__})


def backup(ctx: typer.Context) -> None:
    """Make an idempotent local private-state backup; source code remains in Git."""
    store = LocalStore(discover(Path.cwd()))
    if options(ctx).dry_run:
        emit(ctx, {"would_backup": ".coderecall/backups/"})
    else:
        emit(ctx, {"backup": str(make_backup(store)), "private": True, "includes_code": False})


def restore(ctx: typer.Context, archive: Path, yes: bool = False) -> None:
    """Validate backup and preserve current state before restoring learning data."""
    validate_archive(archive)
    if options(ctx).dry_run:
        emit(ctx, {"valid": True, "would_restore": str(archive), "configuration": "preserved"})
    elif confirm(
        ctx, "Replace local learning state with this backup? A recovery copy will be retained", yes
    ):
        recovery = restore_backup(LocalStore(discover(Path.cwd())), archive)
        emit(ctx, {"restored": True, "recovery_backup": recovery, "configuration": "preserved"})


def export(ctx: typer.Context, format: str = "json", output: Path | None = None) -> None:
    """Export private learning data. JSON is full fidelity; CSV/Markdown are summaries."""
    content = Project().export(format)
    if options(ctx).dry_run:
        emit(ctx, {"would_export": str(output) if output else "stdout", "format": format})
        return
    if output:
        # Export is explicitly user-directed, but never follows symlinks or overwrites files.
        if output.is_symlink() or any(
            p.is_symlink() or getattr(p, "is_junction", lambda: False)()
            for p in output.absolute().parents
        ):
            raise ValidationError("Export target cannot be a symlink")
        create_or_match(output, content.encode())
        emit(ctx, {"exported": str(output), "private": True})
    elif options(ctx).json:
        emit(
            ctx, json.loads(content) if format == "json" else {"format": format, "content": content}
        )
    else:
        typer.echo(content, nl=False)


def config(ctx: typer.Context, action: str = "show", key: str = "", value: str = "") -> None:
    """Show/get/set project TOML configuration. No credentials accepted."""
    root = discover(Path.cwd())
    configuration = Config(root)
    if action == "show":
        emit(ctx, configuration.values)
    elif action == "get":
        emit(ctx, {key: configuration.get(key)})
    elif action == "set":
        if not options(ctx).dry_run:
            with LocalStore(root).lock():
                Config.set(root, key, value)
        emit(ctx, {"key": key, "saved": not options(ctx).dry_run})
    else:
        raise ValidationError("Config action must be show, get or set")


def git_status(ctx: typer.Context) -> None:
    emit(ctx, Project().git.status())


def git_diff(ctx: typer.Context) -> None:
    p = Project()
    emit(ctx, {"diff": p.git.diff(owned_paths(p.store.read()))})


def git_commit(
    ctx: typer.Context, message: str = "practice: record solution updates", yes: bool = False
) -> None:
    """Preview and commit only owned files; refuse unrelated staged changes."""
    project = Project()
    paths = project.commit_plan()
    if options(ctx).dry_run:
        emit(ctx, {"would_commit": paths, "message": message})
    else:
        if not options(ctx).json:
            emit(ctx, {"will_commit": paths})
        if confirm(ctx, "Commit these owned files?", yes):
            emit(ctx, {"commit": project.commit(message), "paths": paths})


def git_push(ctx: typer.Context, yes: bool = False) -> None:
    """Explicit network push with outgoing-history secret scan."""
    p = Project()
    plan = p.git.plan()
    if options(ctx).dry_run:
        emit(ctx, {"plan": asdict(plan), "network": False})
    elif confirm(ctx, "Scan outgoing history and push to the configured remote?", yes):
        emit(ctx, p.sync(fetch=True, execute=True))


def sync(
    ctx: typer.Context, yes: bool = False, fetch: bool = True, import_solutions: bool = False
) -> None:
    """Fetch explicitly, calculate a safe plan, then fast-forward or push with consent."""
    from rich.console import Console

    from coderecall.domain.errors import SyncConflictError

    p = Project()
    console = Console()

    try:
        approved = p.git.plan(fetch=fetch)
    except SyncConflictError as exc:
        if options(ctx).json:
            raise
        console.print(f"[bold red]Abort:[/bold red] {str(exc)}")
        raise typer.Exit(1) from exc

    plan = {"plan": asdict(approved), "import_solutions": import_solutions, "network": fetch}

    if options(ctx).json:
        emit(ctx, plan)
        if not options(ctx).dry_run and confirm(ctx, "Apply the synchronization plan?", yes):
            emit(
                ctx,
                p.sync(
                    fetch=False, execute=True, approved=approved, import_solutions=import_solutions
                ),
            )
        return

    # Render plan beautifully
    console.print("[bold]Sync Plan:[/bold]")
    if approved.state == "CLEAN":
        console.print("Repository is up to date.")
    else:
        if approved.behind:
            console.print(f"Pull [cyan]{approved.behind}[/cyan] commit(s)")
        if approved.ahead:
            console.print(f"Push [cyan]{approved.ahead}[/cyan] commit(s)")
        if approved.state == "CONFLICT":
            console.print("[red]Conflict detected. Reconcile manually.[/red]")

    if options(ctx).dry_run:
        return

    if confirm(ctx, "Apply the synchronization plan?", yes):
        result = p.sync(
            fetch=False, execute=True, approved=approved, import_solutions=import_solutions
        )
        plan_dict = result.get("plan", {})
        state_str = "UNKNOWN"
        if isinstance(plan_dict, dict):
            state_str = str(plan_dict.get("state", "UNKNOWN"))
        console.print(f"[green]Successfully synced ({state_str})[/green]")


def github(ctx: typer.Context, action: str = "status", yes: bool = False) -> None:
    """Explicit network authentication via gh; shared gh credentials, never project tokens."""
    provider = GitHubProvider(Path.cwd())
    if options(ctx).dry_run:
        emit(ctx, {"would_github": action})
    elif action == "status":
        emit(ctx, provider.status())
    elif action in {"connect", "disconnect"}:
        if options(ctx).json or options(ctx).non_interactive:
            raise ValidationError(
                "GitHub login/logout requires an interactive terminal; use gh directly for automation"
            )
        if confirm(ctx, "Change shared GitHub CLI authentication?", yes):
            emit(ctx, provider.connect() if action == "connect" else provider.disconnect())
    else:
        raise ValidationError("GitHub action must be connect, disconnect or status")


def ai(
    ctx: typer.Context, action: str = "status", file: Path | None = None, consent: bool = False
) -> None:
    """Optional trusted AI plugin. Every source disclosure requires --consent."""
    p = Project()
    enabled = bool(p.config.get("ai.enabled"))
    plugin = str(p.config.get("ai.plugin"))
    if action == "status":
        emit(ctx, {"enabled": enabled, "provider": plugin or None, "network": False})
        return
    if not enabled or not plugin:
        raise ValidationError("AI disabled/unconfigured; explicitly install and enable a provider")
    if not consent:
        raise ValidationError("External code disclosure requires --consent on this request")
    if (
        file is None
        or not file.is_file()
        or file.is_symlink()
        or file.stat().st_size > 2 * 1024 * 1024
    ):
        raise ValidationError("Provide a regular source --file at most 2 MiB")
    if options(ctx).dry_run:
        emit(ctx, {"would_send": str(file), "provider": plugin, "task": action})
        return
    from coderecall.integrations.plugins import request_ai

    emit(
        ctx,
        request_ai(plugin, file.read_text(encoding="utf-8"), action, str(p.config.get("ai.model"))),
    )


def run_solution(ctx: typer.Context, file: Path, yes: bool = False) -> None:
    """Run an explicitly selected solution script in a restricted Linux Docker container."""
    from rich.console import Console
    from rich.panel import Panel

    p = Project()
    console = Console()

    if options(ctx).dry_run:
        emit(
            ctx,
            {
                "would_run": str(file),
                "sandbox": "docker",
                "enabled": p.config.get("execution.enabled"),
            },
        )
        return

    if not p.config.get("execution.enabled"):
        if options(ctx).json:
            emit(ctx, asdict(UnavailableRunner().run(file)))
        else:
            console.print("[red]Sandbox is disabled in configuration.[/red]")
        raise typer.Exit(8)

    if not options(ctx).json and not options(ctx).non_interactive:
        if not confirm(
            ctx, f"Execute [bold]{file.name}[/bold] in the configured local Docker sandbox?", yes
        ):
            return

    from coderecall.execution.docker import DockerRunner

    result = DockerRunner(
        p.root, str(p.config.get("execution.image")), int(p.config.get("execution.timeout"))
    ).run(file)

    if options(ctx).json:
        emit(ctx, asdict(result))
    else:
        if result.state == "PASS":
            color = "green"
            icon = "✓"
        elif result.state == "FAIL":
            color = "red"
            icon = "✗"
        else:
            color = "yellow"
            icon = "⚠"

        console.print(
            Panel(
                f"[{color}]{icon} {result.detail}[/{color}]",
                title=f"Execution Result: {result.state}",
                border_style=color,
            )
        )

    if result.state != "PASS":
        raise typer.Exit(8)


def register(app: typer.Typer) -> None:
    for function in [init, status, doctor, version, backup, restore, export, sync, github, ai]:
        app.command()(function)  # type: ignore[type-var]
    app.command("config")(config)
    app.command("run")(run_solution)
    group = typer.Typer(help="Safe local Git operations and explicit remote push.")
    group.command("status")(git_status)
    group.command("diff")(git_diff)
    group.command("commit")(git_commit)
    group.command("push")(git_push)
    app.add_typer(group, name="git")
