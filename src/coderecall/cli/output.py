import json
import re
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.table import Table

CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean(value: object) -> str:
    return CONTROL.sub(lambda m: f"\\x{ord(m.group()):02x}", str(value))


@dataclass
class Options:
    json: bool = False
    quiet: bool = False
    verbose: bool = False
    non_interactive: bool = False
    dry_run: bool = False
    no_color: bool = False


def options(ctx: typer.Context) -> Options:
    return ctx.find_root().obj if isinstance(ctx.find_root().obj, Options) else Options()


def emit(ctx: typer.Context, value: object) -> None:
    opts = options(ctx)
    if opts.json:
        typer.echo(json.dumps(value, ensure_ascii=False, allow_nan=False))
        return
    if opts.quiet:
        return
    console = Console(no_color=opts.no_color, markup=False, highlight=False)
    render(console, value)


def display(value: object) -> str:
    if value is None:
        return "Not measured"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(clean(v) for v in value) or "None"
    return clean(value)


def render(console: Console, value: object) -> None:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        table = Table(show_lines=False)
        keys = list(value[0])
        for key in keys:
            table.add_column(clean(key).replace("_", " ").title())
        for row in value:
            table.add_row(*(display(row.get(key, "")) for key in keys))
        console.print(table)
    elif isinstance(value, str):
        console.print(clean(value))
    elif isinstance(value, dict):
        details = Table.grid(padding=(0, 2))
        details.add_column(style="bold")
        details.add_column()
        sections: list[tuple[str, object]] = []
        for key, item in value.items():
            label = clean(key).replace("_", " ").title()
            if (
                isinstance(item, dict)
                or isinstance(item, list)
                and item
                and isinstance(item[0], dict)
            ):
                sections.append((label, item))
            else:
                details.add_row(label, display(item))
        console.print(details)
        for label, item in sections:
            console.print("\n" + label, style="bold")
            render(console, item)
    else:
        console.print(display(value))


def confirm(ctx: typer.Context, text: str, yes: bool = False) -> bool:
    opts = options(ctx)
    if opts.dry_run:
        return False
    if yes:
        return True
    if opts.non_interactive or opts.json:
        from coderecall.domain.errors import ValidationError

        raise ValidationError("Confirmation required: pass --yes or use --dry-run")
    return typer.confirm(clean(text), default=False, err=True)
