# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unified CLI: ``opm init``, ``opm transform``, ``opm chunk``, ``opm index``,
``opm odd`` (``document``, ``coverage``), and ``opm serve``.

ODDs are compiled on demand into the user cache (``platformdirs``); there is no
separate ``compile`` command.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Annotated, Any, NoReturn, Optional, TYPE_CHECKING

import typer
from typer.main import get_command

if TYPE_CHECKING:  # rich is imported lazily: it costs ~30ms of startup
    from rich.progress import Progress
    from rich.style import Style

try:
    from typer._click.exceptions import NoArgsIsHelpError, UsageError
except ImportError:  # typer < 0.27 still depends on the click package
    from click.exceptions import NoArgsIsHelpError, UsageError


from opm.config import load_project_config
from opm.odd_cache import ResolvedTransform
from opm.output_modes import CONFIG_SECTIONS, RENDER_MODES, OutputMode, module_mode, output_mode
from opm.typst_compile import compile_pdf, typst_available, typst_executable
from opm.resources import opm_version
from opm.scaffold import (
    EXAMPLE_NAMES,
    EXAMPLES,
    InitOptions,
    ScaffoldError,
    VOCABULARIES,
    scaffold,
)
from opm.project import CHUNK_FORMATS, Project, chunk_input_files
from opm.transform import load_transform_module
from opm.runtime.xpath_diagnostics import XPathErrorLog, collect_xpath_errors

app = typer.Typer(
    name='opm',
    help=(
        'Open Processing Model: transform XML via ODD processing models '
        '(ODDs compile on demand into the user cache).'
    ),
    no_args_is_help=True,
    context_settings={'help_option_names': ['-h', '--help']},
)

odd_app = typer.Typer(
    name='odd',
    help='Inspect or document an ODD: corpus coverage, static schema reference sites.',
    no_args_is_help=True,
    context_settings={'help_option_names': ['-h', '--help']},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f'opm {opm_version()}')
        raise typer.Exit()


def _print_logo() -> None:
    """Print the OPM logo on stderr, so it never mixes with output on stdout.

    Only in an interactive terminal: piped or redirected runs stay as they were.
    """
    if not sys.stderr.isatty():
        return
    # Imported lazily, like rich: only the logo needs them.
    from rich.console import Console
    from rich.text import Text
    from rich_pyfiglet import RichFiglet

    console = Console(stderr=True)
    # The orange of the OPM logo (docs/assets/logo.svg).
    console.print(RichFiglet('OPM', font='slant', colors=['#F5A623']))
    console.print(Text(f'Open Processing Model {opm_version()}\n', style='dim'))


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            '--version',
            '-V',
            help='Show the installed version and exit.',
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option('--quiet', '-q', help='Do not print the OPM logo.'),
    ] = False,
) -> None:
    # No docstring: Typer would use it as the group help, replacing ``app.help``.
    if not quiet:
        _print_logo()


@app.command('init')
def init_cmd(
    directory: Annotated[
        Path,
        typer.Argument(help='Project directory (default: current directory).'),
    ] = Path('.'),
    force: Annotated[
        bool,
        typer.Option('--force', help='Overwrite existing generated files.'),
    ] = False,
    vocabulary: Annotated[
        Optional[str],
        typer.Option(
            '--vocabulary',
            help=(
                f'Empty project for this vocabulary: {", ".join(VOCABULARIES)} '
                '(default: tei).'
            ),
        ),
    ] = None,
    example: Annotated[
        Optional[str],
        typer.Option(
            '--example',
            '-e',
            help=(
                'Start from a bundled example project instead of an empty one: '
                f'{", ".join(EXAMPLE_NAMES)}.'
            ),
        ),
    ] = None,
    list_examples: Annotated[
        bool,
        typer.Option(
            '--list-examples',
            help='List the bundled example projects and exit.',
        ),
    ] = False,
    copy_base_odd: Annotated[
        bool,
        typer.Option(
            '--copy-base-odd',
            help='TEI only: also copy packaged teipublisher.odd and tp.css into odd/.',
        ),
    ] = False,
    templates: Annotated[
        bool,
        typer.Option(
            '--templates',
            help=(
                'Also copy the alternative HTML shells (chapbook, journal, '
                'handbook, tufte, bootstrap) beside the one wired up.'
            ),
        ),
    ] = False,
) -> None:
    """Create a local project: an empty one, or a copy of a bundled example."""
    if list_examples:
        _print_examples()
        return

    if vocabulary is not None and example is not None:
        _die('--vocabulary and --example both choose a starting point; pass one.')

    if vocabulary is None and example is None:
        vocabulary, example = _choose_start()
        # A bare `opm init` settles the shells in the same breath as the
        # starting point; --templates has already answered the question.
        if not templates:
            templates = _ask_extra_templates()

    if example is not None and copy_base_odd:
        _note('--copy-base-odd does not apply to --example; ignoring it.')

    vocab = (vocabulary or 'tei').strip().lower()
    if example is None and copy_base_odd and vocab != 'tei':
        _note(f'--copy-base-odd is TEI-only; {vocab} already copies its own ODD.')
    try:
        result = scaffold(
            InitOptions(
                directory=directory,
                force=force,
                vocabulary=vocab,
                example=example,
                templates=templates,
                copy_base_odd=copy_base_odd and vocab == 'tei' and example is None,
            )
        )
    except ScaffoldError as e:
        _die(str(e), cause=e)

    _print_path_tree(
        result.directory,
        result.written,
        f'Created project in {result.directory}',
    )
    if result.skipped:
        _print_path_tree(
            result.directory,
            result.skipped,
            'Skipped existing files (pass --force to overwrite; '
            'AGENTS.md / CLAUDE.md are never overwritten):',
            stderr=True,
        )

    sample = result.sample_path
    typer.echo('')
    typer.echo('Next:')
    typer.echo(f'  opm transform {sample} --preview')
    if result.example is None:
        typer.echo(f'  opm chunk {sample} --force --preview')
    else:
        # Chunk targets differ per example (serafin chunks a whole directory),
        # and each README walks through what its project demonstrates.
        typer.echo('  see README.md for what this project shows')


#: How the vocabularies are spelled in the picker.
_VOCABULARY_LABELS = {'tei': 'TEI', 'docbook': 'DocBook', 'jats': 'JATS'}


def _print_examples() -> None:
    """List the bundled example projects."""
    from rich.console import Console
    from rich.table import Table

    table = Table(title='Bundled example projects', title_justify='left', box=None)
    table.add_column('name', style='bold')
    table.add_column('project')
    table.add_column('shows')
    for example in EXAMPLES:
        table.add_row(example.name, example.title, example.summary)
    console = Console()
    console.print(table)
    console.print('\nStart from one with: opm init <dir> --example <name>')


#: Rows offered by the ``opm init`` picker: (label, summary, (vocabulary, example)).
def _start_rows() -> list[tuple[str, str, tuple[str | None, str | None]]]:
    rows: list[tuple[str, str, tuple[str | None, str | None]]] = [
        (
            f'Empty project — {_VOCABULARY_LABELS.get(vocab, vocab)}',
            'stub ODD, templates, sample document',
            (vocab, None),
        )
        for vocab in VOCABULARIES
    ]
    rows += [
        (example.title, example.summary, (None, example.name))
        for example in EXAMPLES
    ]
    return rows


def _fit(text: str, room: int) -> str:
    """Shorten *text* to *room* columns, ending in an ellipsis when cut."""
    if len(text) <= room:
        return text
    return text[: max(1, room - 1)].rstrip() + '…'


def _select_from_menu(
    rows: list[tuple[str, str, tuple[str | None, str | None]]],
) -> tuple[str | None, str | None] | None:
    """Arrow-key menu. Returns ``None`` when this terminal cannot host one."""
    try:
        import questionary
        from questionary import Choice, Style
    except ImportError:
        # Editable installs whose dependencies were resolved before questionary
        # was added still have to reach the numbered prompt, not a traceback.
        return None

    # Labels padded to a common width so the dim summaries line up. A menu row
    # cannot wrap — prompt_toolkit clips it at the edge — so the summary is
    # truncated to what is left, and dropped when that is not worth reading.
    width = max(len(label) for label, _, _ in rows)
    room = shutil.get_terminal_size((80, 24)).columns - width - 6
    choices = [
        Choice(
            title=(
                [('class:label', label.ljust(width)), ('class:summary', f'  {_fit(summary, room)}')]
                if room >= 20
                else [('class:label', label)]
            ),
            value=value,
        )
        for label, summary, value in rows
    ]
    try:
        return questionary.select(
            'Start from:',
            choices=choices,
            qmark='',
            pointer='▸',
            instruction='(↑/↓, Enter)',
            style=Style([
                ('question', 'bold'),
                ('pointer', 'fg:cyan bold'),
                ('highlighted', 'fg:cyan bold'),
                ('selected', 'fg:cyan'),
                ('answer', 'fg:green bold'),
                ('label', ''),
                ('summary', 'fg:#8a8a8a'),
            ]),
        ).unsafe_ask()
    except KeyboardInterrupt:
        _die('cancelled.')
    except Exception:
        # prompt_toolkit needs a full-screen capable terminal; a dumb TERM or an
        # emulated console raises rather than degrading. Fall back to numbers.
        return None


def _choose_start() -> tuple[str | None, str | None]:
    """Ask what to start from, returning ``(vocabulary, example)``.

    Only prompts on a terminal: a piped or scripted ``opm init`` keeps its old
    behaviour and gets an empty TEI project.
    """
    if not sys.stdin.isatty():
        return None, None

    rows = _start_rows()
    picked = _select_from_menu(rows)
    if picked is not None:
        return picked

    from rich.console import Console
    from rich.prompt import Prompt
    from rich.table import Table

    table = Table(box=None, padding=(0, 2, 0, 0), show_header=False)
    table.add_column('', style='bold')
    table.add_column('')
    table.add_column('', style='dim')
    for number, (label, summary, _) in enumerate(rows, 1):
        table.add_row(str(number), label, summary)

    console = Console()
    console.print('Start from:')
    console.print(table)
    try:
        answer = Prompt.ask(
            'Choice',
            choices=[str(i) for i in range(1, len(rows) + 1)],
            default='1',
            show_choices=False,
            console=console,
        )
    except EOFError:
        _die('cancelled.')
    return rows[int(answer) - 1][2]


def _ask_extra_templates() -> bool:
    """Ask whether to copy the alternative HTML shells beside the wired one.

    Only prompts on a terminal: a piped or scripted ``opm init`` keeps the lean
    default of the one shell the project actually uses, and says so through
    ``--templates`` when it wants the rest.
    """
    if not sys.stdin.isatty():
        return False

    question = 'Also copy the alternative HTML shells to swap in later?'
    try:
        import questionary
    except ImportError:
        # Editable installs whose dependencies were resolved before questionary
        # was added still have to reach the plain prompt, not a traceback.
        pass
    else:
        try:
            return bool(
                questionary.confirm(question, default=False, qmark='').unsafe_ask()
            )
        except KeyboardInterrupt:
            _die('cancelled.')
        except Exception:
            # prompt_toolkit needs a full-screen capable terminal; a dumb TERM
            # or an emulated console raises rather than degrading.
            pass

    from rich.prompt import Confirm

    try:
        return bool(Confirm.ask(question, default=False))
    except (EOFError, KeyboardInterrupt):
        _die('cancelled.')


def _stderr_message(prefix: str, style: str, message: str) -> None:
    """Write ``opm: <prefix>: <message>`` to stderr, prefix styled.

    The message is assembled as a ``Text``, never parsed as rich markup: it
    routinely carries paths and quoted values, and ``[…]`` in one of those would
    be read as a style tag and swallowed. ``soft_wrap`` keeps rich from folding
    a line at 80 columns when stderr is redirected, so a script reading the
    output still sees whole messages.
    """
    from rich.console import Console
    from rich.text import Text

    Console(stderr=True).print(
        Text.assemble((f'opm: {prefix}:', style), ' ', message),
        soft_wrap=True,
        highlight=False,
    )


def _link_style(target: str) -> Style:
    """Style for a path or URL the terminal can open (OSC-8 hyperlink).

    Terminals that do not support hyperlinks simply show the styled text, so
    the label always has to stay readable on its own.
    """
    from rich.style import Style

    return Style(color='green', bold=True, link=target)


def _print_path_tree(
    root: Path, paths: list[Path], label: str, *, stderr: bool = False
) -> None:
    """Print *label*, then *paths* as a tree of *root*, nested by directory.

    The heading is printed separately because a ``Tree`` crops its own label to
    the console width — an absolute path would lose its tail. Leaves are
    ``Text``, not markup: a file name is data, and one containing ``[…]`` would
    otherwise be read as a style tag.
    """
    from rich.console import Console
    from rich.text import Text
    from rich.tree import Tree

    tree = Tree(Text(f'{root.name}/', style='bold'))
    branches: dict[Path, Tree] = {Path('.'): tree}
    for path in sorted(paths):
        try:
            rel = path.relative_to(root)
        except ValueError:
            # Written outside the project directory: show the path whole.
            tree.add(Text(str(path)))
            continue
        parent = Path('.')
        for part in rel.parts[:-1]:
            key = parent / part
            if key not in branches:
                branches[key] = branches[parent].add(Text(f'{part}/', style='bold'))
            parent = key
        branches[parent].add(Text(rel.name))
    console = Console(stderr=stderr)
    console.print(Text(label), soft_wrap=True)
    console.print(tree)


def _die(message: str, *, cause: BaseException | None = None) -> NoReturn:
    """Report a fatal error and exit non-zero."""
    _stderr_message('error', 'bold red', message)
    raise SystemExit(1) from cause


def _note(message: str) -> None:
    """Report something the user should know about, without failing."""
    _stderr_message('note', 'bold yellow', message)


def _load_project(path: Path | None) -> Project:
    """Load the project in ``opm.toml``, rooted at the working directory.

    The chunk output directory and ``styles/default-styles.css`` are found
    from where opm runs, not from where the config file is.
    """
    return Project.load(path, root=Path.cwd())


def _preview_output(out: str | bytes, mode: OutputMode) -> None:
    """Show *out* the way ``--preview`` does for *mode* (see ``OutputMode.preview``)."""
    if mode.preview == 'app':
        label = mode.name.upper()
        data = out if isinstance(out, bytes) else out.encode('utf-8')
        if not _preview_file_with_default_app(data, mode.extension, label):
            typer.echo(
                f'{label} output cannot be previewed in the terminal and no '
                f'application is registered for {mode.extension} files. '
                f'Use --output to write a {mode.extension} file.',
            )
        return
    text = out.decode('utf-8') if isinstance(out, bytes) else out
    if mode.preview == 'browser':
        _preview_html_in_browser(text)
    elif mode.preview == 'markdown':
        _preview_markdown_terminal(text)
    elif mode.preview == 'json':
        _preview_json_terminal(text)
    else:
        _preview_plain_terminal(text)


def _pdf_request(mode: OutputMode, output: Path | None, preview: bool) -> tuple[bool, bool]:
    """``(pdf, view)``: whether to compile the output to PDF, and whether to open it.

    Typst output becomes a PDF when ``--output`` names a ``.pdf`` file, or for
    ``--preview`` when the typst command is installed; the compiler then opens
    it. Otherwise it stays Typst source. ``--output`` wins over ``--preview``,
    as for every other type.
    """
    if mode.compiler is None:
        return False, False
    if output is not None:
        return output.suffix.lower() == '.pdf', False
    if not preview:
        return False, False
    if typst_available():
        return True, True
    _note('the typst command is not on PATH; showing the Typst source instead of the PDF.')
    return False, False


def _preview_html_in_browser(html: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode='w',
        encoding='utf-8',
        suffix='.html',
        delete=False,
        prefix='opm-preview-',
    ) as f:
        f.write(html)
        path = Path(f.name)
    webbrowser.open(path.as_uri())


def _preview_file_with_default_app(data: bytes, suffix: str, label: str) -> bool:
    """Write *data* to a temp file and open it in the platform's default app.

    Used for formats that cannot be rendered in a terminal or browser (docx,
    epub).  Returns ``False`` when no handler could be launched, so the caller
    can fall back to telling the user to pass ``--output``.
    """
    import click  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(
        suffix=suffix,
        delete=False,
        prefix='opm-preview-',
    ) as f:
        f.write(data)
        path = Path(f.name)
    try:
        if click.launch(str(path)) != 0:
            return False
    except OSError:
        return False
    from rich.console import Console
    from rich.text import Text

    Console(stderr=True).print(
        Text.assemble(f'Opened {label} preview: ', (str(path), _link_style(path.as_uri()))),
        soft_wrap=True,
        highlight=False,
    )
    return True


def _preview_markdown_terminal(md: str) -> None:
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    # Rich's pager keeps ANSI styles (bold/italic) when handing off to the system pager
    # (e.g. less). Piping plain output to `less` drops a TTY and strips styling unless
    # FORCE_COLOR is set; using pager(styles=True) avoids that for interactive preview.
    if sys.stdout.isatty():
        with console.pager(styles=True):
            console.print(Markdown(md))
    else:
        console.print(Markdown(md))


def _preview_plain_terminal(text: str) -> None:
    """Print source output (Typst, unrecognised channels) to the terminal.

    Rich reads ``[...]`` as style tags and Typst content blocks are square
    brackets, so markup has to be off — with it on, ``[transform.typst]`` in a
    comment came out as an empty gap. Highlighting guesses at Python-ish tokens
    in what is not Python, and ``soft_wrap`` leaves long lines to the terminal
    rather than hard-wrapping source at the console width.
    """
    from rich.console import Console

    Console().print(text, markup=False, highlight=False, soft_wrap=True)


def _preview_json_terminal(text: str) -> None:
    """Print JSON output with syntax highlighting."""
    from rich.console import Console
    from rich.json import JSON

    console = Console()
    try:
        console.print(JSON(text))
    except ValueError:
        # Malformed JSON is worth seeing verbatim rather than swallowing.
        _preview_plain_terminal(text)


def _parameters_from_cli(param_list: list[str] | None) -> dict[str, str]:
    """Parse ``KEY=VALUE`` strings into a parameters dict (XPath ``$parameters``)."""
    if not param_list:
        return {}
    out: dict[str, str] = {}
    for raw in param_list:
        if '=' not in raw:
            raise ValueError(f'--param must be KEY=VALUE, got {raw!r}')
        key, _, value = raw.partition('=')
        key = key.strip()
        if not key:
            raise ValueError(f'--param must be KEY=VALUE, got {raw!r}')
        out[key] = value
    return out


def _report_resolved_module(resolved: ResolvedTransform) -> None:
    """Print the cache path when the module was produced from an ODD."""
    if resolved.source_odd is None:
        return
    from rich.console import Console
    from rich.text import Text

    module = (str(resolved.module_path), _link_style(resolved.module_path.as_uri()))
    line = (
        Text.assemble(f'Compiled {resolved.source_odd} → ', module)
        if resolved.freshly_compiled
        else Text.assemble('Cached module: ', module)
    )
    Console(stderr=True).print(line, soft_wrap=True, highlight=False)
    if resolved.freshly_compiled and resolved.unsupported:
        count = len(resolved.unsupported)
        plural = count != 1
        _note(
            f'{count} ODD expression{"s" if plural else ""} use{"" if plural else "s"} '
            'features opm does not support (probably for TEI Publisher compatibility) and '
            f'{"are" if plural else "is"} skipped; opm odd coverage lists them.'
        )


#: Run-time failures listed in full; the rest are only counted.
_XPATH_FAILURES_SHOWN = 10

_STRICT_HELP = (
    'Exit with an error when an XPath expression fails at run time, instead of '
    'treating it as false or empty. Expressions opm cannot run at all (eXist '
    'functions, XQuery syntax) are reported when the ODD is compiled and do not count.'
)


def _report_xpath_errors(log: XPathErrorLog, *, strict: bool = False) -> None:
    """Report the run's XPath errors on stderr; with *strict*, fail on them.

    Hints name configuration the project is missing and never fail a run.
    Failures are listed once per expression, the most frequent first: each one
    counted as false (a predicate) or empty (a param), so the output is complete
    but lacks whatever those expressions would have contributed.
    """
    for hint in log.hints.values():
        _note(hint)
    failures = log.ordered_failures()
    if not failures:
        return
    from rich.console import Console
    from rich.text import Text

    count = len(failures)
    plural = count != 1
    _stderr_message(
        'warning', 'bold yellow',
        f'{count} XPath expression{"s" if plural else ""} failed at run time and '
        f'{"were" if plural else "was"} treated as false or empty:',
    )
    console = Console(stderr=True)
    for failure in failures[:_XPATH_FAILURES_SHOWN]:
        where = [f'{failure.count}×']
        if failure.element:
            first = f'first at <{failure.element}>'
            if failure.document:
                first += f' {_relative_path(Path(failure.document))}'
                if failure.line:
                    first += f':{failure.line}'
            where.append(first)
        error = f'{failure.code}: {failure.message}' if failure.code else failure.message
        for text in (
            Text.assemble('  ', (' '.join(failure.expression.split()), 'bold')),
            Text(f'    {error}'),
            Text(f'    {", ".join(where)}', style='dim'),
        ):
            console.print(text, soft_wrap=True, highlight=False)
    if count > _XPATH_FAILURES_SHOWN:
        console.print(
            Text(f'  … and {count - _XPATH_FAILURES_SHOWN} more', style='dim'),
            soft_wrap=True, highlight=False,
        )
    if strict:
        _die(f'--strict: {count} XPath expression{"s" if plural else ""} failed at run time.')


def _apply_json_channel(transform_type: str | None, channel: str | None) -> str | None:
    """Fold ``--channel`` into the compile mode, giving ``json-<channel>``.

    JSON output records what some other channel decided, so which channel it
    inspects is part of the compile: the models that participate, and therefore
    the cached module, differ per channel.
    """
    if channel is None:
        return transform_type
    if not output_mode(transform_type).records:
        _die('--channel applies to -t json only.')
    picked = channel.strip().lower()
    if picked not in RENDER_MODES:
        _die(
            f'--channel must be one of {", ".join(RENDER_MODES)}, got {channel!r}.',
        )
    return f'json-{picked}'


def _corpus_files(input_path: Path | None) -> list[Path]:
    """XML files for a corpus-wide command (``opm index``, ``opm odd coverage``).

    Three things ``opm chunk`` does not do, because chunking publishes a given
    set of pages while these commands read a body of material:

    * ``./data`` is the default when no path is given — the layout ``opm init``
      scaffolds and every bundled example uses.
    * Directories are searched recursively: corpora are routinely filed in
      subdirectories (``data/article/…``), and silently reading none of them
      would understate an index or a coverage report.
    * An empty or missing corpus is an error, not an empty result.
    """
    source = input_path if input_path is not None else Path('data')
    if input_path is None and not source.is_dir():
        _die('input XML file or directory is required (no ./data directory to fall back on).')
    if not source.exists():
        _die(f'no such file or directory: {source}')
    if not source.is_dir():
        return [source]
    files = sorted(path for path in source.rglob('*.xml') if path.is_file())
    if not files:
        _die(f'no XML files found in directory {source}.')
    return files


def _chunk_progress() -> Progress:
    """Progress display for ``opm chunk``: description, bar, count, ETA.

    Disabled whenever stdout is not a terminal. The bar is decoration, never
    output — a piped or redirected run must see only what the command echoes,
    and rich would otherwise print one final frame when the display stops.
    """
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        TextColumn,
        TimeRemainingColumn,
    )

    console = Console()
    return Progress(
        TextColumn('{task.description}'),
        BarColumn(complete_style='cyan', finished_style='cyan'),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        disable=not console.is_terminal,
    )


def _document_output_dir(compiled, output_dir: Path | None) -> Path:
    """``-o``, else ``odd/<schemaSpec @ident>`` under the current directory."""
    if output_dir is not None:
        return output_dir.resolve()
    ident = Path(getattr(compiled, 'ident', '') or 'schema').name
    if ident in {'', '.', '..'}:
        ident = 'schema'
    return (Path('odd') / ident).resolve()


def _prepare_chunk_output_dir(out_dir: Path, *, force: bool) -> None:
    """Remove *out_dir* if it already exists.

    With ``--force``, the directory (or file) is deleted immediately. Otherwise
    an interactive terminal is prompted; non-interactive runs error so scripts
    must pass ``--force``.
    """
    if not out_dir.exists():
        return
    if not force:
        prompt = f'Output directory {out_dir} already exists. Remove it and continue?'
        if sys.stdin.isatty():
            if not typer.confirm(prompt, default=False):
                raise SystemExit(1)
        else:
            _die(
                f'output directory {out_dir} already exists. '
                'Use --force to replace it.'
            )
    if out_dir.is_dir():
        shutil.rmtree(out_dir)
    else:
        out_dir.unlink()


@app.command('transform')
def transform_cmd(
    input_xml: Annotated[Optional[Path], typer.Argument(help='Input XML file')] = None,
    odd: Annotated[
        Optional[Path],
        typer.Option(
            '--odd',
            '-d',
            help=(
                'ODD file to compile on demand into the user cache. '
                'Overrides transform.<type>.odd in config.'
            ),
        ),
    ] = None,
    transform_type: Annotated[
        Optional[str],
        typer.Option(
            '--type',
            '-t',
            metavar='TYPE',
            help=(
                f'Transform type / ODD output channel ({", ".join(CONFIG_SECTIONS)}). '
                'Selects transform.<type>.odd from config when --odd '
                'is omitted; also sets the compile mode for --odd.'
            ),
        ),
    ] = None,
    channel: Annotated[
        Optional[str],
        typer.Option(
            '--channel',
            metavar='CHANNEL',
            help=(
                'With -t json only: which ODD output channel to record decisions '
                f'for ({", ".join(RENDER_MODES)}). Default: web.'
            ),
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            '--output',
            '-o',
            help=(
                'Write transform output to this file (default: stdout unless --preview). '
                'With -t typst, a .pdf file name compiles the output with the typst command.'
            ),
        ),
    ] = None,
    preview: Annotated[
        bool,
        typer.Option(
            '--preview',
            '-v',
            help=(
                'Preview output: channel web/print → browser, markdown → Rich (paged in a TTY so '
                'bold/italic survive), docx/epub → the platform default application, typst → '
                'the compiled PDF, opened by typst (typst compile --open) when the typst command '
                'is installed; other channels → plain text in the terminal.'
            ),
        ),
    ] = False,
    param: Annotated[
        list[str],
        typer.Option(
            '--param',
            '-p',
            metavar='KEY=VALUE',
            help='Runtime parameter for XPath $parameters (repeatable), e.g. -p mode=toc -p display=browse',
        ),
    ] = [],
    css: Annotated[
        Optional[Path],
        typer.Option(
            '--css',
            help=(
                'CSS file replacing the packaged base rules compiled into the ODD stylesheet. '
                'Falls back to transform.css in the project config.'
            ),
        ),
    ] = None,
    template: Annotated[
        Optional[Path],
        typer.Option(
            '--template',
            help='Template path: Jinja2 for HTML/print/Typst output, or .docx for DOCX output.',
        ),
    ] = None,
    xpath: Annotated[
        Optional[str],
        typer.Option(
            '--xpath',
            '-x',
            metavar='EXPR',
            help=(
                'XPath 3.1 expression evaluated with the document root as the context item; '
                'the single selected element becomes the transform root. Unprefixed names use '
                'the same default element namespace as the document root. $parameters is bound '
                'from --param.'
            ),
        ),
    ] = None,
    xpath_extensions: Annotated[
        Optional[list[str]],
        typer.Option(
            '--xpath-extensions',
            help=(
                'Dotted import path(s) of Python module(s) whose public callables become XPath '
                'functions in the tp: namespace (repeat option to add modules; e.g. '
                '--xpath-extensions extensions.common --xpath-extensions extensions.dates). '
                'Importing these modules runs top-level code: only use trusted code.'
            ),
        ),
    ] = None,
    webcomponents: Annotated[
        Optional[bool],
        typer.Option(
            '--webcomponents/--no-webcomponents',
            help=(
                'Enable/disable tei-publisher web components mode: alternate behaviours emit '
                '<pb-alternate> and the document template loads tei-publisher-components. '
                'Falls back to transform.web.webcomponents in the project config.'
            ),
        ),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option('--strict', help=_STRICT_HELP),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option(
            '--config',
            '-c',
            help='Path to a TOML configuration file (default: opm.toml in the current directory).',
        ),
    ] = None,
) -> None:
    """Transform an XML document via an ODD with processing instructions and return the result (HTML, markdown, …)."""
    try:
        project = _load_project(config)

        if input_xml is None:
            _die('input XML file is required.')

        # --css / [transform] css replaces the packaged base rules, which are
        # compiled into the ODD stylesheet — so it has to be known before the
        # ODD is compiled, and it is part of the cache key.
        if css is not None:
            project = project.with_config(document_css=css)
        effective_type = _apply_json_channel(transform_type, channel)
        _report_resolved_module(project.compile(effective_type, odd))

        mode = module_mode(project.module(effective_type, odd))
        pdf, view = _pdf_request(mode, output, preview)
        if pdf:
            # Fail before transforming rather than after.
            typst_executable()
        with collect_xpath_errors() as xpath_log:
            out = project.transform(
                input_xml,
                mode=effective_type,
                odd=odd,
                xpath=xpath,
                # -p overrides [transform.parameters].
                parameters=_parameters_from_cli(param or None),
                # No --xpath-extensions means the configured ones.
                xpath_extensions=xpath_extensions or None,
                webcomponents=webcomponents,
                template=template,
            )
        if pdf:
            # Image paths in the output are the XML's own, relative to its directory.
            out = compile_pdf(str(out), root=input_xml.resolve().parent, open_viewer=view)

        if output:
            if isinstance(out, bytes):
                output.write_bytes(out)
            else:
                output.write_text(out, encoding='utf-8')
        elif view:
            # Typst has already opened the PDF; nothing goes to stdout.
            pass
        elif preview:
            _preview_output(out, mode)
        elif isinstance(out, bytes):
            sys.stdout.buffer.write(out)
        else:
            print(out)
        _report_xpath_errors(xpath_log, strict=strict)
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        _die(str(e), cause=e)


@app.command()
def chunk(
    input_xml: Annotated[
        Optional[Path],
        typer.Argument(
            help='XML file to transform and chunk, or a directory of XML files.',
        ),
    ] = None,
    odd: Annotated[
        Optional[Path],
        typer.Option(
            '--odd',
            '-d',
            help='ODD file to compile on demand for chunking (overrides chunking.odd in config).',
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            '--output-dir',
            '-o',
            help='Directory to write chunked files (overrides chunking.output_dir in config).',
        ),
    ] = None,
    template: Annotated[
        Optional[Path],
        typer.Option(
            '--template',
            '-t',
            exists=True,
            dir_okay=False,
            help='Jinja2 template for chunk pages (overrides chunking.template in config).',
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            '--force',
            '-f',
            help='Remove the existing output directory without prompting.',
        ),
    ] = False,
    depth: Annotated[
        Optional[int],
        typer.Option(
            '--depth',
            help='Maximum division/section depth for chunk splitting (overrides chunking.depth in config).',
        ),
    ] = None,
    webcomponents: Annotated[
        Optional[bool],
        typer.Option(
            '--webcomponents/--no-webcomponents',
            help=(
                'Enable/disable tei-publisher web components mode. '
                'Falls back to transform.web.webcomponents in the project config.'
            ),
        ),
    ] = None,
    xpath_extensions: Annotated[
        Optional[list[str]],
        typer.Option(
            '--xpath-extensions',
            help=(
                'Dotted import path(s) of Python module(s) whose public callables become XPath '
                'functions in the tp: namespace (repeatable). '
                'Falls back to transform.xpath_extensions in opm.toml.'
            ),
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option(
            '--format',
            help=(
                'Output format for chunk files: "html" (default, rendered via Jinja2 template), '
                '"json" (one JSON file per chunk containing content, head, odd_css, and '
                'fragments — suitable for static site generators such as Eleventy), or '
                '"pb-view" (index.json lookup table plus one part file per chunk, consumable '
                'by the dynamic pb-view web component in static mode).'
            ),
        ),
    ] = 'html',
    doc_path: Annotated[
        Optional[str],
        typer.Option(
            '--doc-path',
            help=(
                'For --format pb-view: document path subdirectory. Data is written to '
                '<output-dir>/<doc-path>/ and must match the pb-document @path; CSS stays '
                'shared at <output-dir>/css/. Falls back to chunking.doc_path in config.'
            ),
        ),
    ] = None,
    preview: Annotated[
        bool,
        typer.Option(
            '--preview',
            '-v',
            help=(
                'After chunking, start a local HTTP server rooted at the output '
                'directory and open the first page in a browser (HTML output only).'
            ),
        ),
    ] = False,
    port: Annotated[
        int,
        typer.Option(
            '--port',
            '-p',
            help='Port for --preview (default: 8080).',
        ),
    ] = 8080,
    strict: Annotated[
        bool,
        typer.Option('--strict', help=_STRICT_HELP),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option(
            '--config',
            '-c',
            help='Path to a TOML configuration file (default: opm.toml in the current directory).',
        ),
    ] = None,
) -> None:
    """Chunk a large XML document into smaller HTML pages or JSON data files."""
    try:
        project = _load_project(config)

        if input_xml is None:
            _die('input XML file or directory is required.')

        chunking = project.config.chunking
        if not chunking:
            _die('no [chunking] section found in config.')
        
        if output_format not in CHUNK_FORMATS:
            _die(
                '--format must be "html", "json" or "pb-view", '
                f'got {output_format!r}'
            )

        modules = project.chunk_modules(odd)
        for resolved in modules:
            _report_resolved_module(resolved)

        input_files = chunk_input_files(input_xml)
        if input_xml.is_dir():
            if not input_files:
                _die(f'no XML files found in directory {input_xml}.')

        # Asked here rather than left to Project.chunk, so the prompt comes
        # before the progress display starts.
        out_dir = project.chunk_output_dir(output_dir)
        _prepare_chunk_output_dir(out_dir, force=force)

        module_path = modules[0].module_path
        if input_xml.is_dir():
            typer.echo(
                f'Chunking {len(input_files)} XML files from {input_xml} '
                f'using {module_path}...'
            )
        else:
            typer.echo(f'Chunking {input_xml} using {module_path}...')
        # ``on_progress`` counts chunks *within one document*, so a directory run
        # gets a second task counting files — one bar per unit, rather than
        # trading chunk-level detail for a file count.
        per_file = len(input_files) > 1
        with _chunk_progress() as progress, collect_xpath_errors() as xpath_log:
            file_task = (
                progress.add_task('Files', total=len(input_files)) if per_file else None
            )
            # Total arrives with the first callback: only the chunker knows how
            # many chunks a document splits into. Until then the bar pulses.
            chunk_task = progress.add_task('Processing chunks', total=None)

            def _on_document(position: int, xml_file: Path) -> None:
                if file_task is None:
                    return
                progress.update(file_task, completed=position)
                # `update` cannot clear a total, so the next document's first
                # callback replaces it; zero the count so the bar restarts.
                progress.update(
                    chunk_task, completed=0, description=f'Chunking {xml_file.name}'
                )

            def _on_progress(current: int, total: int) -> None:
                progress.update(chunk_task, completed=current, total=total)

            run = project.chunk(
                input_xml,
                format=output_format,
                output_dir=output_dir,
                # Unlike the configured one, a --template path is relative to
                # the working directory.
                template=template,
                depth=depth,
                odd=odd,
                doc_path=doc_path,
                webcomponents=webcomponents,
                xpath_extensions=xpath_extensions,
                overwrite=True,
                on_document=_on_document,
                on_progress=_on_progress,
            )
            if file_task is not None:
                progress.update(file_task, completed=len(input_files))

        typer.echo(f'Chunks written to {out_dir}/')
        chunk_doc_path = doc_path or chunking.doc_path
        if output_format == 'pb-view':
            if input_xml.is_dir():
                data_subdir = f'{(chunk_doc_path or "").rstrip("/")}/<document>.xml/'
                if data_subdir.startswith('/'):
                    data_subdir = data_subdir[1:]
            else:
                data_subdir = f'{chunk_doc_path}/' if chunk_doc_path else ''
            typer.echo(f'  - {data_subdir}index.json: pb-view lookup table')
            typer.echo(f'  - {data_subdir}<xml:id>.json: part files')
            odd_name = getattr(load_transform_module(module_path), 'ODD_NAME', '')
            typer.echo(f'  - css/{odd_name}.css: ODD stylesheet')
        else:
            ext = 'json' if output_format == 'json' else 'html'
            typer.echo('  - <document>.xml/manifest.json: metadata for page navigation and linking')
            typer.echo(f'  - <document>.xml/*.{ext}: chunk files')
            if run.index_file is not None:
                typer.echo('  - index.html: collection index served at the site root')

        _report_xpath_errors(xpath_log, strict=strict)

        if preview:
            # Only HTML has a page to land on; json/pb-view output is served for
            # another tool to fetch, so the browser would show a file listing.
            _serve_directory(out_dir, port, open_browser=output_format == 'html')

    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        _die(str(e), cause=e)


_SERVE_PORT_TRIES = 20


def _bind_http_server(handler: Any, port: int, tries: int = _SERVE_PORT_TRIES):
    """Bind an HTTP server, skipping ports that are already in use.

    Returns ``(httpd, bound_port)``. Raises the last ``OSError`` if every
    candidate from *port* through *port + tries - 1* fails.
    """
    import errno
    import http.server

    last_error: OSError | None = None
    for candidate in range(port, port + max(1, tries)):
        try:
            httpd = http.server.HTTPServer(('', candidate), handler)
            bound = httpd.socket.getsockname()[1]
            return httpd, bound
        except OSError as e:
            last_error = e
            if e.errno != errno.EADDRINUSE:
                raise
    assert last_error is not None
    raise last_error


def _preview_landing_url(root: Path, port: int) -> str:
    """URL to open for a served chunk directory.

    An HTML run writes ``index.html`` at the site root, so that is the landing
    page. The numbered-page fallback covers a directory holding pages written
    some other way, so the browser never opens on a bare file listing.
    """
    base = f'http://localhost:{port}/'
    if (root / 'index.html').is_file():
        return base
    pages = sorted(path.name for path in root.glob('[0-9]*.html'))
    return base + pages[0] if pages else base


def _serve_directory(root: Path, port: int, *, open_browser: bool = False) -> None:
    """Serve *root* over HTTP until interrupted (same behaviour as ``opm serve``).

    With *open_browser*, the landing page is opened once the socket is bound —
    the request waits in the listen backlog until ``serve_forever`` picks it up.

    ``serve_forever`` runs on a daemon thread so Ctrl-C can interrupt the main
    thread on Windows, where Winsock waits do not deliver ``KeyboardInterrupt``.
    """
    import errno
    import functools
    import http.server
    import threading

    root = root.resolve()
    if not root.is_dir():
        _die(f'directory {root} does not exist.')

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(root),
    )
    try:
        httpd, bound_port = _bind_http_server(handler, port)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            _die(
                f'port {port} is already in use. Try a different port with -p.',
                cause=e,
            )
        _die(str(e), cause=e)

    if bound_port != port:
        typer.echo(
            f'Port {port} is in use; serving on {bound_port} instead.',
            err=True,
        )
    with httpd:
        from rich.console import Console
        from rich.text import Text

        url = f'http://localhost:{bound_port}/'
        Console().print(
            Text.assemble(
                f'Serving {root} at ',
                (url, _link_style(url)),
                ' — press Ctrl-C to stop.',
            ),
            soft_wrap=True,
            highlight=False,
        )
        if open_browser:
            webbrowser.open(_preview_landing_url(root, bound_port))
        thread = threading.Thread(
            target=httpd.serve_forever,
            name='opm-serve',
            daemon=True,
        )
        thread.start()
        stop = threading.Event()
        try:
            while thread.is_alive():
                stop.wait(0.5)
        except KeyboardInterrupt:
            httpd.shutdown()
            thread.join(timeout=5)


@app.command('index')
def index_cmd(
    input_xml: Annotated[
        Optional[Path],
        typer.Argument(
            help=(
                'XML file to index, or a directory of XML files (searched '
                'recursively). Defaults to ./data when it exists.'
            ),
        ),
    ] = None,
    odd: Annotated[
        Optional[Path],
        typer.Option(
            '--odd',
            '-d',
            help='ODD file to compile on demand (overrides transform.json.odd in config).',
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            '--output',
            '-o',
            help='JSONL file to write (default: stdout).',
        ),
    ] = None,
    max_chars: Annotated[
        Optional[int],
        typer.Option(
            '--max-chars',
            help=(
                'Split a section longer than this at record boundaries. '
                'Falls back to index.max_chars in opm.toml (default: 1500).'
            ),
        ),
    ] = None,
    min_chars: Annotated[
        Optional[int],
        typer.Option(
            '--min-chars',
            help=(
                'Drop units shorter than this — bare headings are retrieval noise. '
                'Falls back to index.min_chars in opm.toml (default: 40).'
            ),
        ),
    ] = None,
    overlap: Annotated[
        Optional[int],
        typer.Option(
            '--overlap',
            help=(
                'Records of context carried into the next part when a unit splits. '
                'Falls back to index.overlap in opm.toml (default: 1).'
            ),
        ),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option('--strict', help=_STRICT_HELP),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option(
            '--config',
            '-c',
            help='Path to a TOML configuration file (default: opm.toml in the current directory).',
        ),
    ] = None,
) -> None:
    """Emit embedding-ready JSONL records for a search index or vector store.

    Records come from the processing model, not the raw source, so the ODD's
    editorial decisions carry into the index: omitted apparatus stays out, and
    ``alternate`` contributes the reading the page displays.
    """
    import json

    from opm.indexing import IndexOptions, write_jsonl

    try:
        project = _load_project(config)
        cfg = project.config

        input_files = _corpus_files(input_xml)

        options = IndexOptions(
            max_chars=max_chars if max_chars is not None else cfg.index_max_chars,
            min_chars=min_chars if min_chars is not None else cfg.index_min_chars,
            overlap=overlap if overlap is not None else cfg.index_overlap,
            fields=cfg.index_fields,
            units=cfg.index_units,
        )
        with collect_xpath_errors() as xpath_log:
            records = project.index(input_files, odd=odd, options=options)

        if output:
            from rich.console import Console

            write_jsonl(records, output)
            # Progress goes to stderr so `opm index ... | jq` stays clean.
            Console(stderr=True).print(
                f'Wrote {len(records)} records from {len(input_files)} '
                f'document(s) to {output}',
            )
        else:
            for record in records:
                print(json.dumps(record, ensure_ascii=False))
        _report_xpath_errors(xpath_log, strict=strict)
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        _die(str(e), cause=e)


def _coverage_table(
    console,
    title: str,
    columns: list[str],
    rows: list[list[str]],
    note: str = '',
    limit: int | None = 20,
) -> None:
    """One section of the coverage report; skipped when it has no findings.

    Long sections are cut off rather than paged: a stock ODD against one
    document can leave a hundred models unused, and a wall of them buries the
    sections below it. ``--all`` and ``--json`` both give the full list.
    """
    if not rows:
        return
    from rich.table import Table

    shown = rows if limit is None else rows[:limit]
    heading = f'[bold]{title}[/bold]'
    console.print(f'{heading}  [dim]{note}[/dim]' if note else heading, highlight=False)

    table = Table(box=None, padding=(0, 2, 0, 0), pad_edge=False)
    for index, column in enumerate(columns):
        # Identifier columns get a floor so the long free-text ones (a
        # predicate, a description) cannot squeeze them down to an ellipsis.
        # The first column is what a reader looks up, so it is never cut.
        content = max((len(row[index]) for row in shown), default=0)
        floor = max(len(column), content)
        table.add_column(
            column,
            style='bold' if index == 0 else None,
            min_width=floor if index == 0 else min(floor, 18),
            no_wrap=True,
            overflow='ellipsis',
        )
    for row in shown:
        table.add_row(*row)
    console.print(table)
    if len(shown) < len(rows):
        console.print(
            f'[dim]… and {len(rows) - len(shown)} more '
            '(--all to list them, --json for everything)[/dim]',
            highlight=False,
        )
    console.print()


def _relative_path(path: Path) -> str:
    """Shorten a path against the working directory when it is below it."""
    try:
        return str(Path(path).resolve().relative_to(Path.cwd()))
    except (OSError, ValueError):
        return str(path)


def _truncate(text: str | None, width: int = 60) -> str:
    if not text:
        return ''
    flat = ' '.join(text.split())
    return flat if len(flat) <= width else f'{flat[: width - 1]}…'


def _render_coverage(report, *, limit: int | None = 20) -> None:
    """Print the coverage report as a set of tables (see ``opm odd coverage``)."""
    from rich.console import Console

    from opm.coverage import _by_count

    console = Console()
    local = report.local_models()
    inherited = report.inherited_models()
    fired_local = sum(1 for m in local if m.hits)
    fired_inherited = sum(1 for m in inherited if m.hits)
    unused = report.unused_models()
    docs = len(report.documents)

    console.print(
        f'[bold]ODD coverage[/bold] — {_relative_path(report.odd)} '
        f'[dim](channel: {report.channel})[/dim]',
        highlight=False, soft_wrap=True,
    )
    console.print(
        f'{docs} document{"s" if docs != 1 else ""}, '
        f'{report.records} records, {report.suppressed} suppressed',
        highlight=False, soft_wrap=True,
    )
    console.print()

    percent = f'{fired_local * 100 // len(local)}%' if local else '—'
    summary = [
        ['Local models', str(len(local)), f'fired {fired_local} ({percent})',
         f'unused {len(unused)}'],
        ['Inherited models', str(len(inherited)), f'fired {fired_inherited}', ''],
        ['Elements in documents', str(len(report.elements_seen)),
         f'no model {len(report.unmatched)}', f'dropped {len(report.dropped)}'],
    ]
    _coverage_table(console, 'Summary', ['', 'total', '', ''], summary, limit=None)

    _coverage_table(
        console, 'Unused local models',
        ['model', 'element', 'behaviour', 'predicate'],
        [
            [m.key, m.element, m.behaviour or '(template)',
             _truncate(m.predicate, 60)]
            for m in unused
        ],
        note='element is in the corpus, this model never won',
        limit=limit,
    )
    _coverage_table(
        console, 'Unreachable models',
        ['model', 'element', 'why'],
        [[m.key, m.element, _truncate(m.unreachable, 70)]
         for m in report.unreachable_models()],
        note='can never fire, whatever the document',
        limit=limit,
    )
    _coverage_table(
        console, 'Expressions opm cannot run',
        # The expression itself is in --json; the reason and the ODD line are
        # what a reader scanning the table acts on.
        ['location', 'where', 'why'],
        [
            [
                f"{entry.get('odd') or ''}:{entry['line']}"
                if entry.get('line') else (entry.get('odd') or ''),
                _truncate(f"{entry.get('element') or ''} {entry.get('where') or ''}", 40),
                _truncate(entry.get('reason'), 60),
            ]
            for entry in report.unsupported
        ],
        note='skipped: a predicate counts as false, a param falls back',
        limit=limit,
    )
    _coverage_table(
        console, 'Models that emit nothing',
        ['model', 'element'],
        [[m.key, m.element] for m in report.silent_models()],
        note='no @behaviour and no pb:template',
        limit=limit,
    )
    _coverage_table(
        console, 'Elements with no model',
        ['element', 'count', 'first seen'],
        [[o.element, str(o.count), o.location] for o in _by_count(report.unmatched)],
        note='nothing in the ODD matched them',
        limit=limit,
    )
    _coverage_table(
        console, 'Elements dropped',
        ['element', 'count', 'first seen'],
        [[o.element, str(o.count), o.location] for o in _by_count(report.dropped)],
        note='a spec exists, but every predicate was false',
        limit=limit,
    )
    _coverage_table(
        console, 'Element specs never exercised',
        ['element', 'models'],
        [[entry['element'], str(entry['models'])] for entry in report.unused_specs],
        note='declared here, absent from the corpus',
        limit=limit,
    )
    if report.attribute_only_specs:
        console.print(
            '[dim]Attribute-only specs (no models): '
            f'{", ".join(report.attribute_only_specs)}[/dim]',
            highlight=False,
        )



@odd_app.command('document')
def document_cmd(
    source: Annotated[
        Optional[Path],
        typer.Argument(
            help=(
                'ODD, compiled spec document (p5subset.xml / Guidelines p5.xml), '
                'or a directory of Specs. Omit with --tei to document the TEI schema.'
            ),
        ),
    ] = None,
    tei: Annotated[
        bool,
        typer.Option(
            '--tei',
            help=(
                'Document TEI alone (no SOURCE). Downloads the TEI schema '
                '(specs plus Guidelines prose, ~2 MB) into the user cache on '
                'first use; it is not shipped in the wheel. TEI-targeting ODDs '
                'merge onto it by default.'
            ),
        ),
    ] = False,
    schema_source: Annotated[
        Optional[Path],
        typer.Option(
            '--source',
            help='Local schema source (p5subset.xml or a compiled ODD) used as the merge base.',
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            '--output-dir',
            '-o',
            help='Output directory (default: odd/<schemaSpec ident>).',
        ),
    ] = None,
    lang: Annotated[
        str,
        typer.Option('--lang', help='xml:lang to prefer on gloss/desc/remarks (default: en).'),
    ] = 'en',
    title: Annotated[
        Optional[str],
        typer.Option('--title', help='Site title (default: taken from the ODD header).'),
    ] = None,
    odd: Annotated[
        Optional[Path],
        typer.Option(
            '--odd',
            '-d',
            help='Processing ODD used to render nested TEI (default: packaged tagdocs.odd).',
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option('--force', help='Replace the output directory if it already exists.'),
    ] = False,
    offline: Annotated[
        bool,
        typer.Option(
            '--offline',
            help='Do not download the TEI schema; fail if it is not already cached.',
        ),
    ] = False,
    preview: Annotated[
        bool,
        typer.Option(
            '--preview',
            '-v',
            help='After building, serve the site and open it in a browser.',
        ),
    ] = False,
    port: Annotated[
        int,
        typer.Option('--port', '-p', help='Port for --preview (default: 8080).'),
    ] = 8080,
) -> None:
    """Generate a static HTML documentation site from an ODD.

    Follows ``schemaSpec/@source`` (processing-model chains included). A
    TEI-targeting ODD (``schemaSpec/@ns`` absent or the TEI namespace) is merged
    onto the cached TEI schema. --tei documents TEI alone; --source supplies a
    local schema instead. Writes
    reference pages plus A–Z catalogs. Processing models are listed on each
    elementSpec.

    Chapter prose from the input is always kept, and when the input is itself
    the schema being documented (--tei, a Guidelines p5.xml, a Specs directory)
    its chapters are published too. A customization documents itself, so TEI's
    chapters stay out of its site. An ODD pinning an older TEI/@version is
    compiled against the shipped snapshot, with a warning.
    PDF, Markdown and print channels are planned.
    """
    from opm.document_site import build_document_site
    from opm.odd_schema import SchemaError, compile_schema

    if source is None and not tei and schema_source is None:
        _die('pass an ODD / spec document, or --tei to document the TEI schema.')

    try:
        compiled = compile_schema(
            source,
            source=schema_source,
            use_tei=tei,
            fetch=not offline,
        )
    except SchemaError as exc:
        _die(str(exc), cause=exc)

    for warning in compiled.warnings:
        _note(warning)

    out_dir = _document_output_dir(compiled, output_dir)
    _prepare_chunk_output_dir(out_dir, force=force)

    typer.echo(f'Documenting {compiled.title or compiled.source_path or "schema"} → {out_dir}')

    with _chunk_progress() as progress, collect_xpath_errors() as xpath_log:
        task = progress.add_task('Writing pages', total=None)

        def _on_progress(current: int, total: int, label: str) -> None:
            progress.update(
                task,
                completed=current,
                total=total,
                description=f'Writing {label}',
            )

        site = build_document_site(
            compiled,
            out_dir,
            lang=lang,
            title=title,
            odd=odd,
            on_progress=_on_progress,
        )

    typer.echo(
        f'Wrote {site.pages} pages ({len(site.index.elements())} elements'
        + (f', {site.chapters} chapters' if site.chapters else '')
        + f') to {out_dir}'
    )
    if site.unsupported:
        count = len(site.unsupported)
        plural = count != 1
        _note(
            f'{count} expression{"s" if plural else ""} in the documentation ODD '
            f'{"are" if plural else "is"} not supported and rendered empty: '
            + '; '.join(
                f'{e.get("element") or "?"} {e.get("where") or ""} — {e.get("reason")}'
                for e in site.unsupported[:_XPATH_FAILURES_SHOWN]
            )
        )
    _report_xpath_errors(xpath_log)
    if preview:
        _serve_directory(out_dir, port, open_browser=True)


@odd_app.command('coverage')
def coverage_cmd(
    input_xml: Annotated[
        Optional[Path],
        typer.Argument(
            help=(
                'XML file or directory of XML files to measure the ODD against. '
                'Defaults to ./data when it exists.'
            ),
        ),
    ] = None,
    odd: Annotated[
        Optional[Path],
        typer.Option(
            '--odd',
            '-d',
            help='ODD file to compile on demand (overrides transform.json.odd in config).',
        ),
    ] = None,
    channel: Annotated[
        Optional[str],
        typer.Option(
            '--channel',
            metavar='CHANNEL',
            help=(
                'ODD output channel to report on '
                '(web, print, epub, markdown, docx, typst). Default: web.'
            ),
        ),
    ] = None,
    param: Annotated[
        Optional[list[str]],
        typer.Option(
            '--param',
            '-p',
            help='Transform parameter KEY=VALUE (repeatable), as for opm transform.',
        ),
    ] = None,
    show_all: Annotated[
        bool,
        typer.Option(
            '--all',
            '-a',
            help='List every finding instead of the first 20 per section.',
        ),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option(
            '--json',
            help='Print the whole report as JSON instead of tables.',
        ),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option('--config', '-c', help='Path to opm.toml.'),
    ] = None,
) -> None:
    """Diagnose an ODD against a corpus: what never runs, and what is never handled.

    Reports the models and elementSpecs you wrote that no document exercised,
    models that can never fire at all, elements no model matched, and elements
    whose spec exists but whose predicates were all false. Models inherited from
    an extended ODD are counted separately — a local elementSpec replaces the
    inherited one wholesale, so they are not yours to change.

    Coverage transforms whole documents; chunking config is ignored.
    """
    import json

    try:
        project = _load_project(config)

        mode = _apply_json_channel('json', channel) or 'json'
        input_files = _corpus_files(input_xml)

        _report_resolved_module(project.compile(mode, odd))

        # A predicate that raises counts as false, which can make a model look
        # unused; the errors are listed after the report so that shows.
        with collect_xpath_errors() as xpath_log:
            report = project.coverage(
                input_files, mode=mode, odd=odd, parameters=_parameters_from_cli(param),
            )

        if as_json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            _render_coverage(report, limit=None if show_all else 20)
        _report_xpath_errors(xpath_log)
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        _die(str(e), cause=e)


# ``opm coverage`` shipped in 0.9.0; keep it as a hidden alias of ``odd coverage``.
app.command('coverage', hidden=True, deprecated=True)(coverage_cmd)
app.add_typer(odd_app, name='odd')


@app.command('serve')
def serve_cmd(
    port: Annotated[
        int,
        typer.Option('--port', '-p', help='Port to listen on (default: 8080).'),
    ] = 8080,
    directory: Annotated[
        Optional[Path],
        typer.Option(
            '--directory',
            '-d',
            help='Directory to serve (default: chunking.output_dir from config, or "chunks").',
        ),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option(
            '--config',
            '-c',
            help='Path to a TOML configuration file (default: opm.toml in the current directory).',
        ),
    ] = None,
) -> None:
    """Start a local HTTP server rooted at the chunks output directory."""
    cfg = load_project_config(config)
    if directory is not None:
        root = directory.resolve()
    elif cfg.chunking:
        root = (Path.cwd() / cfg.chunking.output_dir).resolve()
    else:
        root = (Path.cwd() / 'chunks').resolve()

    _serve_directory(root, port)


def main(argv: list[str] | None = None) -> int:
    """Programmatic entry (``argv`` is like ``sys.argv[1:]`` when invoking the installed script)."""
    cmd = get_command(app)
    try:
        cmd.main(args=argv, prog_name='opm', standalone_mode=False)
    except NoArgsIsHelpError:
        # With ``standalone_mode=False``, Click does not turn this into exit 0 (Typer ``no_args_is_help``).
        return 0
    except UsageError as e:
        # Missing required args, bad option values, etc. (``standalone_mode=False`` skips Click's handler).
        e.show()
        return e.exit_code
    except SystemExit as e:
        code = e.code
        if isinstance(code, int):
            return code
        return 1 if code else 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
