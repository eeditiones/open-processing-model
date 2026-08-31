"""Unified CLI: ``opm init``, ``opm transform``, ``opm chunk``, ``opm index``, and ``opm serve``.

ODDs are compiled on demand into the user cache (``platformdirs``); there is no
separate ``compile`` command.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import webbrowser
from dataclasses import replace
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

from lxml import etree

from opm.config import (
    ChunkingConfig,
    FragmentConfig,
    ProjectConfig,
    load_project_config,
    resolve_base_css,
)
from opm.odd_cache import ResolvedTransform, resolve_transform_module
from opm.resources import packaged_default_css, packaged_default_docx
from opm.scaffold import (
    EXAMPLE_NAMES,
    EXAMPLES,
    InitOptions,
    ScaffoldError,
    VOCABULARIES,
    scaffold,
)
from opm.runtime.pm_runtime import resolve_context_element
from opm.transform import (
    load_transform_module,
    load_xpath_collections,
    load_xpath_documents,
    run_transform,
)
from opm.runtime.pm_runtime import xpath_runtime_context
from opm.chunking import build_index, chunk_document

app = typer.Typer(
    name='opm',
    help=(
        'Open Processing Model: transform XML via ODD processing models '
        '(ODDs compile on demand into the user cache).'
    ),
    no_args_is_help=True,
    context_settings={'help_option_names': ['-h', '--help']},
)


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
    title: Annotated[
        Optional[str],
        typer.Option('--title', help='Edition title used in README (default: directory name).'),
    ] = None,
) -> None:
    """Create a local project: an empty one, or a copy of a bundled example."""
    if list_examples:
        _print_examples()
        return

    if vocabulary is not None and example is not None:
        _die('--vocabulary and --example both choose a starting point; pass one.')

    if vocabulary is None and example is None:
        vocabulary, example = _choose_start()

    if example is not None:
        for flag, given in (
            ('--copy-base-odd', copy_base_odd),
            ('--title', title is not None),
        ):
            if given:
                _note(f'{flag} does not apply to --example; ignoring it.')

    vocab = (vocabulary or 'tei').strip().lower()
    if example is None and copy_base_odd and vocab != 'tei':
        _note(f'--copy-base-odd is TEI-only; {vocab} already copies its own ODD.')
    try:
        result = scaffold(
            InitOptions(
                directory=directory,
                force=force,
                title=title,
                vocabulary=vocab,
                example=example,
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


def _preview_kind_from_module(mod) -> str:
    """Return ``'html'``, ``'markdown'``, ``'docx'``, ``'epub'``, or ``'text'`` based on output channels."""
    raw = mod.transform_output_channels()
    if not raw:
        return 'text'
    primary = raw[0] if isinstance(raw, (list, tuple)) else raw
    if primary == 'markdown':
        return 'markdown'
    if primary in ('web', 'print'):
        return 'html'
    if primary == 'docx':
        return 'docx'
    if primary == 'epub':
        return 'epub'
    if primary == 'typst':
        return 'typst'
    if primary == 'json' or primary.startswith('json-'):
        return 'json'
    return 'text'


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


def _apply_json_channel(transform_type: str | None, channel: str | None) -> str | None:
    """Fold ``--channel`` into the compile mode, giving ``json-<channel>``.

    JSON output records what some other channel decided, so which channel it
    inspects is part of the compile: the models that participate, and therefore
    the cached module, differ per channel.
    """
    from opm.odd_compiler.codegen import RENDER_MODES, is_json_mode

    if channel is None:
        return transform_type
    if not is_json_mode(transform_type or ''):
        _die('--channel applies to -t json only.')
    picked = channel.strip().lower()
    if picked not in RENDER_MODES:
        _die(
            f'--channel must be one of {", ".join(RENDER_MODES)}, got {channel!r}.',
        )
    return f'json-{picked}'


def _resolve_cli_transform(
    *,
    cfg: ProjectConfig,
    odd: Path | None,
    transform_type: str | None,
    base_css: str | None = None,
) -> ResolvedTransform:
    """Resolve ``--odd`` / config odd / packaged default for transform."""
    mode = (transform_type or 'web').strip().lower() or 'web'

    if odd is not None:
        return resolve_transform_module(odd=odd, output_mode=mode, base_css=base_css)

    cfg_odd = cfg.odd_for_type(mode)
    if cfg_odd is not None:
        return resolve_transform_module(odd=cfg_odd, output_mode=mode, base_css=base_css)

    return resolve_transform_module(output_mode=mode, base_css=base_css)


def _materialize_chunking_modules(
    config: ChunkingConfig,
    base_css: str | None = None,
) -> tuple[ChunkingConfig, list[ResolvedTransform]]:
    """Compile ``odd`` entries on *config* into runtime ``module`` paths."""
    reported: list[ResolvedTransform] = []

    main = resolve_transform_module(
        odd=config.odd,
        output_mode='web',
        use_packaged_default=config.odd is None,
        base_css=base_css,
    )
    reported.append(main)

    new_fragments: list[FragmentConfig] | None = None
    if config.fragments:
        new_fragments = []
        for frag in config.fragments:
            if frag.odd is None:
                new_fragments.append(replace(frag, module=None))
                continue
            resolved = resolve_transform_module(
                odd=frag.odd,
                output_mode=frag.mode,
                use_packaged_default=False,
                base_css=base_css,
            )
            reported.append(resolved)
            new_fragments.append(replace(frag, module=resolved.module_path))

    return (
        replace(config, module=main.module_path, odd=config.odd, fragments=new_fragments),
        reported,
    )


def _chunk_input_files(input_path: Path) -> list[Path]:
    """Return XML files to process for ``opm chunk``."""
    if input_path.is_dir():
        return sorted(path for path in input_path.iterdir() if path.is_file() and path.suffix.lower() == '.xml')
    return [input_path]


def _append_doc_path(base_doc_path: str | None, xml_path: Path) -> str:
    """Append the XML filename to a configured pb-view document path."""
    if not base_doc_path:
        return xml_path.name
    return f'{base_doc_path.rstrip("/")}/{xml_path.name}'


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


def _append_output_dir(base_output_dir: str, xml_path: Path) -> str:
    """Append the XML filename to the chunk output directory."""
    return f'{base_output_dir.rstrip("/")}/{xml_path.name}'


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
                'Transform type / ODD output channel (web, docx, typst, markdown, …). '
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
                'for (web, print, epub, markdown, docx, typst). Default: web.'
            ),
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            '--output',
            '-o',
            help='Write transform output to this file (default: stdout unless --preview)',
        ),
    ] = None,
    preview: Annotated[
        bool,
        typer.Option(
            '--preview',
            '-v',
            help=(
                'Preview output: channel web/print → browser, markdown → Rich (paged in a TTY so '
                'bold/italic survive), docx/epub → the platform default application; other '
                'channels (e.g. typst) → plain text in the terminal.'
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
            help='Optional external CSS file injected into <head> for full-document HTML output.',
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
                'Falls back to transform.web.webcomponents.enabled in the project config.'
            ),
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
    """Transform an XML document via an ODD with processing instructions and return the result (HTML, markdown, …)."""
    try:
        cfg = load_project_config(config)
        for p in cfg.pythonpath:
            entry = str(p.resolve())
            if entry not in sys.path:
                sys.path.insert(0, entry)

        if input_xml is None:
            _die('input XML file is required.')

        # --css / [document] css replaces the packaged base rules, which are
        # compiled into the ODD stylesheet — so it has to be known before the
        # ODD is compiled, and it is part of the cache key.
        # NB: cwd is the root only for the bare styles/default-styles.css
        # fallback; a configured path is already absolute by this point.
        effective_css = css if css is not None else cfg.document_css
        effective_type = _apply_json_channel(transform_type, channel)
        resolved = _resolve_cli_transform(
            cfg=cfg,
            odd=odd,
            transform_type=effective_type,
            base_css=resolve_base_css(effective_css, Path.cwd()),
        )
        _report_resolved_module(resolved)
        effective_script = resolved.module_path

        effective_webcomponents = webcomponents if webcomponents is not None else (cfg.webcomponents_enabled or False)
        mod = load_transform_module(effective_script)
        channels = mod.transform_output_channels()
        primary = channels[0] if channels else ''
        if isinstance(channels, (list, tuple)) and channels:
            primary = channels[0]
        elif not isinstance(channels, (list, tuple)):
            primary = channels

        # Print / EPUB have no interactive UI — never load web components.
        if primary in ('print', 'epub'):
            effective_webcomponents = False

        if primary == 'typst':
            effective_template = template if template is not None else cfg.typst_template
            effective_docx_template = None
        elif primary == 'docx':
            effective_template = None
            effective_docx_template = template if template is not None else cfg.document_docx_template
            if effective_docx_template is None:
                effective_docx_template = packaged_default_docx()
        elif primary == 'print':
            # Do not fall back to the web/document shell (nav, web components).
            effective_template = template if template is not None else cfg.print_template
            effective_docx_template = None
        elif primary == 'epub':
            effective_template = None
            effective_docx_template = None
        else:
            effective_template = template if template is not None else cfg.document_template
            effective_docx_template = None
        effective_extensions: tuple[str, ...] = (
            tuple(xpath_extensions) if xpath_extensions else cfg.xpath_extensions
        )

        # Config parameters seed $parameters; CLI -p overrides them.
        parameters = dict(cfg.parameters)
        parameters.update(_parameters_from_cli(param if param else None))
        # Add input_path to parameters for image processing in DOCX output
        parameters['input_path'] = str(input_xml)
        xpath_base_uri = input_xml.resolve().as_uri()
        xpath_documents = load_xpath_documents(cfg.xpath_documents)
        xpath_collections, xpath_documents = load_xpath_collections(
            cfg.xpath_collections, xpath_documents,
        )
        parameters.update(
            xpath_runtime_context(
                base_uri=xpath_base_uri,
                documents=xpath_documents,
                collections=xpath_collections,
                variables=dict(cfg.xpath_variables),
                namespaces=dict(cfg.xpath_namespaces),
            ),
        )

        tree = etree.parse(str(input_xml))
        doc_root = tree.getroot()
        root = (
            resolve_context_element(
                doc_root,
                xpath,
                parameters or None,
                xpath_extensions=effective_extensions,
            )
            if xpath
            else doc_root
        )

        template_context = cfg.context_for(
            primary, webcomponents=effective_webcomponents,
        )

        out = run_transform(
            mod,
            root,
            parameters=parameters,
            xpath_extensions=effective_extensions,
            webcomponents=effective_webcomponents,
            template_path=effective_template,
            template_context=template_context,
            docx_template=effective_docx_template,
            typst_template_path=effective_template if primary == 'typst' else None,
            xpath_base_uri=xpath_base_uri,
            xpath_documents=xpath_documents,
            epub_chunking=cfg.epub_chunking,
            epub_css=cfg.epub_css,
            epub_skip_title=cfg.epub_skip_title,
        )

        if isinstance(out, bytes):
            if output:
                output.write_bytes(out)
            elif preview:
                kind = _preview_kind_from_module(mod)
                label = 'EPUB' if kind == 'epub' else 'DOCX'
                ext = '.epub' if kind == 'epub' else '.docx'
                if not _preview_file_with_default_app(out, ext, label):
                    typer.echo(
                        f'{label} output cannot be previewed in the terminal and no '
                        f'application is registered for {ext} files. '
                        f'Use --output to write a {ext} file.',
                    )
            else:
                sys.stdout.buffer.write(out)
        else:
            if output:
                output.write_text(out, encoding='utf-8')
            elif preview:
                kind = _preview_kind_from_module(mod)
                if kind == 'html':
                    _preview_html_in_browser(out)
                elif kind == 'markdown':
                    _preview_markdown_terminal(out)
                elif kind == 'json':
                    _preview_json_terminal(out)
                elif kind == 'typst':
                    _preview_plain_terminal(out)
                else:
                    _preview_plain_terminal(out)
            else:
                print(out)
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
                'Falls back to transform.web.webcomponents.enabled in the project config.'
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
        cfg = load_project_config(config)
        for p in cfg.pythonpath:
            entry = str(p.resolve())
            if entry not in sys.path:
                sys.path.insert(0, entry)

        if input_xml is None:
            _die('input XML file is required.')

        if not cfg.chunking:
            _die('no [chunking] section found in config.')
        
        # Override config with CLI options
        chunking_config = cfg.chunking
        if output_dir:
            chunking_config.output_dir = str(output_dir)
        if template:
            chunking_config.template = template
        if depth is not None:
            chunking_config = replace(chunking_config, depth=depth)
        if odd is not None:
            chunking_config = replace(chunking_config, module=None, odd=odd)

        chunking_config, resolved_list = _materialize_chunking_modules(
            chunking_config, base_css=resolve_base_css(cfg.document_css, Path.cwd())
        )
        for resolved in resolved_list:
            _report_resolved_module(resolved)

        if output_format not in ('html', 'json', 'pb-view'):
            _die(
                '--format must be "html", "json" or "pb-view", '
                f'got {output_format!r}'
            )

        input_files = _chunk_input_files(input_xml)
        if input_xml.is_dir():
            if not input_files:
                _die(f'no XML files found in directory {input_xml}.')

        out_dir = Path.cwd() / chunking_config.output_dir
        _prepare_chunk_output_dir(out_dir, force=force)
        
        # Config templates are already resolved relative to the config file;
        # a --template CLI path is relative to the current working directory.
        effective_template = chunking_config.template
        
        effective_webcomponents = (
            True if output_format in ('json', 'pb-view')
            else (webcomponents if webcomponents is not None else (cfg.webcomponents_enabled or False))
        )
        effective_extensions: tuple[str, ...] | None = (
            tuple(xpath_extensions) if xpath_extensions else None
        )

        # Chunk the document(s)
        effective_chunk_script = chunking_config.module
        if input_xml.is_dir():
            typer.echo(
                f'Chunking {len(input_files)} XML files from {input_xml} '
                f'using {effective_chunk_script or "module from config"}...'
            )
        else:
            typer.echo(f'Chunking {input_xml} using {effective_chunk_script or "module from config"}...')
        # ``on_progress`` counts chunks *within one document*, so a directory run
        # gets a second task counting files — one bar per unit, rather than
        # trading chunk-level detail for a file count.
        per_file = len(input_files) > 1
        with _chunk_progress() as progress:
            file_task = (
                progress.add_task('Files', total=len(input_files)) if per_file else None
            )
            # Total arrives with the first callback: only the chunker knows how
            # many chunks a document splits into. Until then the bar pulses.
            chunk_task = progress.add_task('Processing chunks', total=None)

            def _on_progress(current: int, total: int) -> None:
                progress.update(chunk_task, completed=current, total=total)

            base_doc_path = doc_path or chunking_config.doc_path

            for xml_file in input_files:
                if per_file:
                    # `update` cannot clear a total, so the next document's first
                    # callback replaces it; zero the count so the bar restarts.
                    progress.update(
                        chunk_task, completed=0, description=f'Chunking {xml_file.name}'
                    )
                if input_xml.is_dir() and output_format != 'pb-view':
                    effective_chunking_config = replace(
                        chunking_config,
                        output_dir=_append_output_dir(chunking_config.output_dir, xml_file),
                        link_doc=xml_file.name,
                    )
                else:
                    # Single-file output into …/<name>.xml/ should still expand {doc}.
                    out = Path(chunking_config.output_dir)
                    effective_chunking_config = (
                        replace(chunking_config, link_doc=xml_file.name)
                        if out.name == xml_file.name
                        else chunking_config
                    )
                effective_doc_path = (
                    _append_doc_path(base_doc_path, xml_file)
                    if input_xml.is_dir() and output_format == 'pb-view'
                    else base_doc_path
                )

                chunk_document(
                    module_path=chunking_config.module,
                    xml_path=xml_file,
                    config=effective_chunking_config,
                    project_root=Path.cwd(),
                    template_path=effective_template,
                    on_progress=_on_progress,
                    project_config=cfg,
                    webcomponents=effective_webcomponents,
                    xpath_extensions=effective_extensions,
                    output_format=output_format,
                    doc_path=effective_doc_path,
                )
                if file_task is not None:
                    progress.advance(file_task)

        # A directory run leaves one subdirectory per document, which the dev
        # server would otherwise show as a bare listing. Writing index.html is
        # enough: http.server prefers it over list_directory().
        index_file: Path | None = None
        if input_xml.is_dir() and output_format == 'html':
            index_file = build_index(
                out_dir,
                template_path=chunking_config.index_template,
                title=chunking_config.index_title or input_xml.name,
                module_path=chunking_config.module,
                project_config=cfg,
                project_root=Path.cwd(),
                chunking_config=chunking_config,
            )

        typer.echo(f'Chunks written to {out_dir}/')
        if output_format == 'pb-view':
            if input_xml.is_dir():
                data_subdir = f'{(doc_path or chunking_config.doc_path or "").rstrip("/")}/<document>.xml/'
                if data_subdir.startswith('/'):
                    data_subdir = data_subdir[1:]
            else:
                effective_doc_path = doc_path or chunking_config.doc_path
                data_subdir = f'{effective_doc_path}/' if effective_doc_path else ''
            typer.echo(f'  - {data_subdir}index.json: pb-view lookup table')
            typer.echo(f'  - {data_subdir}<xml:id>.json: part files')
            resolved_module = chunking_config.module
            odd_name = getattr(load_transform_module(resolved_module), 'ODD_NAME', '') if resolved_module else ''
            typer.echo(f'  - css/{odd_name}.css: ODD stylesheet')
        else:
            ext = 'json' if output_format == 'json' else 'html'
            if input_xml.is_dir():
                typer.echo('  - <document>.xml/manifest.json: metadata for page navigation and linking')
                typer.echo(f'  - <document>.xml/*.{ext}: chunk files')
                if index_file is not None:
                    typer.echo('  - index.html: collection index served at the site root')
            else:
                typer.echo('  - manifest.json: metadata for page navigation and linking')
                typer.echo(f'  - *.{ext}: chunk files')

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

    A directory run writes ``index.html`` at the site root, but a single
    document does not: its pages are ``001.html`` and up, so the first one
    stands in for an index rather than sending the reader to a file listing.
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
    """
    import errno
    import functools
    import http.server

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
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


@app.command('index')
def index_cmd(
    input_xml: Annotated[
        Optional[Path],
        typer.Argument(
            help='XML file to index, or a directory of XML files.',
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

    from opm.indexing import IndexOptions, index_document, write_jsonl

    try:
        cfg = load_project_config(config)
        for p in cfg.pythonpath:
            entry = str(p.resolve())
            if entry not in sys.path:
                sys.path.insert(0, entry)

        if input_xml is None:
            _die('input XML file is required.')

        input_files = _chunk_input_files(input_xml)
        if input_xml.is_dir() and not input_files:
            _die(f'no XML files found in directory {input_xml}.')

        options = IndexOptions(
            max_chars=max_chars if max_chars is not None else cfg.index_max_chars,
            min_chars=min_chars if min_chars is not None else cfg.index_min_chars,
            overlap=overlap if overlap is not None else cfg.index_overlap,
        )
        records: list[dict] = []
        for path in input_files:
            records.extend(
                index_document(
                    path, cfg=cfg, odd=odd, project_root=Path.cwd(), options=options,
                ),
            )

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
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        _die(str(e), cause=e)


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
