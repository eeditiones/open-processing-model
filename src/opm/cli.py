"""Unified CLI: ``opm transform``, ``opm chunk``, and ``opm serve``.

ODDs are compiled on demand into the user cache (``platformdirs``); there is no
separate ``compile`` command.
"""

from __future__ import annotations

import sys
import tempfile
import webbrowser
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Optional

import typer
from typer.main import get_command

try:
    from typer._click.exceptions import NoArgsIsHelpError, UsageError
except ImportError:  # typer < 0.27 still depends on the click package
    from click.exceptions import NoArgsIsHelpError, UsageError

from lxml import etree

from opm.config import (
    DEFAULT_CDN_TEMPLATE,
    DEFAULT_VERSION,
    ChunkingConfig,
    FragmentConfig,
    ProjectConfig,
    load_project_config,
)
from opm.odd_cache import ResolvedTransform, resolve_transform_module
from opm.resources import packaged_default_css
from opm.runtime.pm_runtime import resolve_context_element
from opm.transform import load_transform_module, load_xpath_documents, run_transform
from opm.runtime.pm_runtime import xpath_runtime_context
from opm.chunking import chunk_document

app = typer.Typer(
    name='opm',
    help=(
        'Open Processing Model: transform XML via ODD processing models '
        '(ODDs compile on demand into the user cache).'
    ),
    no_args_is_help=True,
    context_settings={'help_option_names': ['-h', '--help']},
)


def _preview_kind_from_module(mod) -> str:
    """Return ``'html'``, ``'markdown'``, ``'docx'``, or ``'text'`` based on output channels."""
    raw = mod.transform_output_channels()
    if not raw:
        return 'text'
    primary = raw[0] if isinstance(raw, (list, tuple)) else raw
    if primary == 'markdown':
        return 'markdown'
    if primary == 'web':
        return 'html'
    if primary == 'docx':
        return 'docx'
    if primary == 'typst':
        return 'typst'
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
    from rich.console import Console

    Console().print(text)


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


def _resolve_user_css(css_path: Path | None) -> str | None:
    """Return CSS text from ``--css``, CWD ``styles/default-styles.css``, or the package."""
    if css_path is not None:
        return css_path.read_text(encoding='utf-8')
    path = Path('styles/default-styles.css')
    if path.is_file():
        return path.read_text(encoding='utf-8')
    packaged = packaged_default_css()
    if packaged is not None and packaged.is_file():
        return packaged.read_text(encoding='utf-8')
    return None


def _report_resolved_module(resolved: ResolvedTransform) -> None:
    """Print the cache path when the module was produced from an ODD."""
    if resolved.source_odd is None:
        return
    styled = typer.style(str(resolved.module_path), fg=typer.colors.GREEN, bold=True)
    if resolved.freshly_compiled:
        typer.echo(f'Compiled {resolved.source_odd} → {styled}', err=True)
    else:
        typer.echo(f'Cached module: {styled}', err=True)


def _resolve_cli_transform(
    *,
    cfg: ProjectConfig,
    odd: Path | None,
    transform_type: str | None,
) -> ResolvedTransform:
    """Resolve ``--odd`` / config odd / packaged default for transform."""
    mode = (transform_type or 'web').strip().lower() or 'web'

    if odd is not None:
        return resolve_transform_module(odd=odd, output_mode=mode)

    cfg_odd = cfg.odd_for_type(mode)
    if cfg_odd is not None:
        return resolve_transform_module(odd=cfg_odd, output_mode=mode)

    return resolve_transform_module(output_mode=mode)


def _materialize_chunking_modules(config: ChunkingConfig) -> tuple[ChunkingConfig, list[ResolvedTransform]]:
    """Compile ``odd`` entries on *config* into runtime ``module`` paths."""
    reported: list[ResolvedTransform] = []

    main = resolve_transform_module(
        odd=config.odd,
        output_mode='web',
        use_packaged_default=config.odd is None,
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


def _append_output_dir(base_output_dir: str, xml_path: Path) -> str:
    """Append the XML filename to the chunk output directory."""
    return f'{base_output_dir.rstrip("/")}/{xml_path.name}'


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
                'Preview output: channel web → browser, markdown → Rich (paged in a TTY so '
                'bold/italic survive); other channels (e.g. print) → plain text in the terminal.'
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
            help='Template path: Jinja2 for HTML/Typst output, or .docx for DOCX output.',
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
            typer.echo('opm: error: input XML file is required.', err=True)
            raise SystemExit(1)

        resolved = _resolve_cli_transform(
            cfg=cfg,
            odd=odd,
            transform_type=transform_type,
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

        if primary == 'typst':
            effective_template = template if template is not None else cfg.typst_template
            effective_docx_template = None
        elif primary == 'docx':
            effective_template = None
            effective_docx_template = template if template is not None else cfg.document_docx_template
        else:
            effective_template = template if template is not None else cfg.document_template
            effective_docx_template = None
        effective_css = css if css is not None else cfg.document_css
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
        parameters.update(
            xpath_runtime_context(base_uri=xpath_base_uri, documents=xpath_documents),
        )
        user_css = _resolve_user_css(effective_css)

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

        webcomponents_url: str | None = None
        if effective_webcomponents:
            webcomponents_url = cfg.webcomponents_cdn or DEFAULT_CDN_TEMPLATE.replace('{version}', DEFAULT_VERSION)

        out = run_transform(
            mod,
            root,
            parameters=parameters,
            xpath_extensions=effective_extensions,
            webcomponents=effective_webcomponents,
            template_path=effective_template,
            user_css=user_css,
            webcomponents_url=webcomponents_url,
            docx_template=effective_docx_template,
            typst_template_path=effective_template if primary == 'typst' else None,
            xpath_base_uri=xpath_base_uri,
            xpath_documents=xpath_documents,
        )

        if isinstance(out, bytes):
            if output:
                output.write_bytes(out)
            elif preview:
                typer.echo('DOCX output cannot be previewed in the terminal. Use --output to write a .docx file.')
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
                elif kind == 'typst':
                    _preview_plain_terminal(out)
                else:
                    _preview_plain_terminal(out)
            else:
                print(out)
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        typer.echo(f'opm: error: {e}', err=True)
        raise SystemExit(1) from e


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
            help='Overwrite existing output directory.',
        ),
    ] = False,
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
            typer.echo('opm: error: input XML file is required.', err=True)
            raise SystemExit(1)

        if not cfg.chunking:
            typer.echo(
                'opm: error: no [chunking] section found in config.',
                err=True
            )
            raise SystemExit(1)
        
        # Override config with CLI options
        chunking_config = cfg.chunking
        if output_dir:
            chunking_config.output_dir = str(output_dir)
        if template:
            chunking_config.template = template
        if odd is not None:
            chunking_config = replace(chunking_config, module=None, odd=odd)

        chunking_config, resolved_list = _materialize_chunking_modules(chunking_config)
        for resolved in resolved_list:
            _report_resolved_module(resolved)

        if output_format not in ('html', 'json', 'pb-view'):
            typer.echo(
                'opm: error: --format must be "html", "json" or "pb-view", '
                f'got {output_format!r}',
                err=True,
            )
            raise SystemExit(1)

        input_files = _chunk_input_files(input_xml)
        if input_xml.is_dir():
            if not input_files:
                typer.echo(
                    f'opm: error: no XML files found in directory {input_xml}.',
                    err=True,
                )
                raise SystemExit(1)

        # Check if output directory exists
        out_dir = Path.cwd() / chunking_config.output_dir
        if out_dir.exists() and not force:
            typer.echo(
                f'opm: error: output directory {out_dir} already exists. '
                'Use --force to overwrite.',
                err=True
            )
            raise SystemExit(1)
        
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
        with typer.progressbar(length=0, label='Processing chunks') as progress:
            def _on_progress(current: int, total: int) -> None:
                if progress.length == 0:
                    progress.length = total  # type: ignore[assignment]
                progress.update(1)

            base_doc_path = doc_path or chunking_config.doc_path

            for xml_file in input_files:
                effective_chunking_config = (
                    replace(
                        chunking_config,
                        output_dir=_append_output_dir(chunking_config.output_dir, xml_file),
                    )
                    if input_xml.is_dir() and output_format != 'pb-view'
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
                typer.echo('  - <document>.xml/manifest.json: metadata for static site builders')
                typer.echo(f'  - <document>.xml/*.{ext}: chunk files')
            else:
                typer.echo('  - manifest.json: metadata for static site builders')
                typer.echo(f'  - *.{ext}: chunk files')
        
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        typer.echo(f'opm: error: {e}', err=True)
        raise SystemExit(1) from e


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
    import http.server
    import functools

    cfg = load_project_config(config)
    if directory is not None:
        root = directory.resolve()
    elif cfg.chunking:
        root = (Path.cwd() / cfg.chunking.output_dir).resolve()
    else:
        root = (Path.cwd() / 'chunks').resolve()

    if not root.is_dir():
        typer.echo(f'opm: error: directory {root} does not exist.', err=True)
        raise SystemExit(1)

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(root),
    )
    with http.server.HTTPServer(('', port), handler) as httpd:
        typer.echo(f'Serving {root} at http://localhost:{port}/ — press Ctrl-C to stop.')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


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
