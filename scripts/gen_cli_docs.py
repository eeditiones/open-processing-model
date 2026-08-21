"""Generate ``docs/cli.md`` from the Typer app (replaces mkdocs-typer2)."""

from __future__ import annotations

from pathlib import Path

from typer.main import get_command

from opm.cli import app

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'cli.md'


def _click():
    try:
        import click
        return click
    except ImportError:
        from typer import _click as click
        return click


def _ctx(command, prog: str, parent=None):
    click = _click()
    return click.Context(command, info_name=prog, parent=parent)


def _usage(command, ctx) -> str:
    formatter = ctx.make_formatter()
    command.format_usage(ctx, formatter)
    return formatter.getvalue().strip().removeprefix('Usage:').strip()


def _escape(text: str) -> str:
    return text.replace('|', '\\|')


def _is_argument(param) -> bool:
    opts = list(param.opts) + list(getattr(param, 'secondary_opts', []) or [])
    return bool(opts) and not any(opt.startswith('-') for opt in opts)


def _arguments(command, ctx) -> str:
    rows: list[str] = []
    for param in command.get_params(ctx):
        if not _is_argument(param):
            continue
        name = param.human_readable_name if hasattr(param, 'human_readable_name') else param.name
        help_text = (param.help or '').replace('\n', ' ').strip()
        rows.append(f'| `{_escape(str(name))}` | {_escape(help_text)} |')
    if not rows:
        return ''
    return (
        '**Arguments:**\n\n'
        '| Argument | Description |\n'
        '| --- | --- |\n'
        + '\n'.join(rows)
        + '\n'
    )


def _option_label(param, ctx) -> str:
    opts = list(param.opts) + list(getattr(param, 'secondary_opts', []) or [])
    if getattr(param, 'is_flag', False):
        return ', '.join(opts)
    metavar = ''
    make_metavar = getattr(param, 'make_metavar', None)
    if make_metavar is not None:
        try:
            metavar = make_metavar(ctx)
        except TypeError:
            metavar = make_metavar()
    if metavar and metavar not in opts and not str(metavar).startswith('['):
        return f'{", ".join(opts)} {metavar}'
    return ', '.join(opts)


def _options_table(command, ctx) -> str:
    rows: list[str] = []
    seen: set[str] = set()
    for param in command.get_params(ctx):
        if _is_argument(param):
            continue
        opts = list(param.opts) + list(getattr(param, 'secondary_opts', []) or [])
        if not opts:
            continue
        key = ', '.join(opts)
        if key in seen:
            continue
        seen.add(key)
        help_text = (param.help or '').replace('\n', ' ').strip()
        rows.append(f'| `{_escape(_option_label(param, ctx))}` | {_escape(help_text)} |')
    if not rows:
        return ''
    return (
        '**Options:**\n\n'
        '| Option | Description |\n'
        '| --- | --- |\n'
        + '\n'.join(rows)
        + '\n'
    )


def _render_command(command, prog: str, *, heading: int, parent=None) -> str:
    ctx = _ctx(command, prog.split()[-1], parent=parent)
    parts = [
        f'{"#" * heading} `{prog}`',
        '',
    ]
    doc = (command.help or '').strip()
    if doc:
        parts.extend([doc, ''])
    parts.extend([
        '**Usage:**',
        '',
        '```text',
        _usage(command, ctx),
        '```',
        '',
    ])
    args = _arguments(command, ctx)
    if args:
        parts.extend([args, ''])
    opts = _options_table(command, ctx)
    if opts:
        parts.extend([opts, ''])

    sub_names = list(command.list_commands(ctx)) if hasattr(command, 'list_commands') else []
    if sub_names:
        parts.append('**Commands:**')
        parts.append('')
        for name in sub_names:
            sub = command.get_command(ctx, name)
            summary = (getattr(sub, 'get_short_help_str', lambda: sub.help or '')() or '').strip()
            parts.append(f'- [`{name}`](#{prog.replace(" ", "-")}-{name}): {summary}')
        parts.append('')
        for name in sub_names:
            sub = command.get_command(ctx, name)
            if sub is None:
                continue
            parts.append(_render_command(sub, f'{prog} {name}', heading=heading + 1, parent=ctx))
    return '\n'.join(parts).rstrip() + '\n'


def main() -> None:
    command = get_command(app)
    body = _render_command(command, 'opm', heading=2)
    OUT.write_text(
        '# CLI Reference\n'
        '\n'
        'The `opm` command is a [Typer](https://typer.tiangolo.com/) application. '
        'This page is generated from `opm.cli` by `scripts/gen_cli_docs.py`. '
        'Run `uv run opm --help` (or `opm <command> --help`) for the same '
        'information in your terminal.\n'
        '\n'
        f'{body}',
        encoding='utf-8',
    )
    print(f'Wrote {OUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
