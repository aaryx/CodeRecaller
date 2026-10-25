"""CLI composition and stable error/JSON boundary."""

import json
import sys
from pathlib import Path

import click
import typer

from coderecall import __version__
from coderecall.cli.output import Options
from coderecall.domain.errors import CodeRecallError

app = typer.Typer(
    help="CodeRecall — Solve. Commit. Recall. Improve.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet"),
    verbose: bool = typer.Option(False, "--verbose"),
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_color: bool = typer.Option(False, "--no-color"),
    version: bool = typer.Option(False, "--version", is_eager=True),
) -> None:
    """Global options go before the command. Offline unless explicitly stated."""
    ctx.obj = Options(json_output, quiet, verbose, non_interactive, dry_run, no_color)
    if version:
        typer.echo(json.dumps({"version": __version__}) if json_output else __version__)
        raise typer.Exit()


def register() -> None:
    from coderecall.cli import catalog, dashboard, learning, management

    catalog.register(app)
    learning.register(app)
    management.register(app)
    dashboard.register(app)


register()


def main() -> None:
    args = sys.argv[1:]
    json_mode = "--json" in args
    try:
        if json_mode and "--help" in args:
            # Click normally renders text help before the root callback. Provide a JSON envelope.
            from click.testing import CliRunner
            from typer.main import get_command

            help_result = CliRunner().invoke(get_command(app), [a for a in args if a != "--json"])
            typer.echo(json.dumps({"help": help_result.output, "exit_code": help_result.exit_code}))
            raise SystemExit(help_result.exit_code)
        result = app(standalone_mode=False)
        if isinstance(result, int) and result:
            raise SystemExit(result)
    except (CodeRecallError, click.ClickException, OSError, UnicodeError) as exc:
        code = exc.exit_code if isinstance(exc, (CodeRecallError, click.ClickException)) else 1
        message = (
            str(exc)
            if isinstance(exc, (CodeRecallError, click.ClickException))
            else "Filesystem/encoding operation failed; local data preserved. Check permissions and paths"
        )
        if json_mode:
            typer.echo(
                json.dumps(
                    {"error": {"type": type(exc).__name__, "message": message, "exit_code": code}}
                )
            )
        else:
            from coderecall.cli.output import clean

            typer.echo(f"Error: {clean(message)}", err=True)
        if "--verbose" in args:
            # No traceback locals, provider bodies, paths with credentials, or source contents.
            typer.echo(
                json.dumps({"level": "error", "event": type(exc).__name__, "exit_code": code}),
                err=True,
            )
        raise SystemExit(code) from None
    except (click.Abort, KeyboardInterrupt):
        if json_mode:
            typer.echo(json.dumps({"error": {"message": "Cancelled", "exit_code": 130}}))
        else:
            typer.echo("Cancelled", err=True)
        raise SystemExit(130) from None


def project_root() -> Path:
    return Path.cwd()
