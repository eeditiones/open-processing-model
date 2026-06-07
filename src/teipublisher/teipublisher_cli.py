"""Unified CLI: ``teipublisher compile`` and ``teipublisher transform``."""

from __future__ import annotations

import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Annotated, Optional

import typer
from click.exceptions import NoArgsIsHelpError, UsageError
from typer.main import get_command

from lxml import etree

from teipublisher.config import DEFAULT_CDN_TEMPLATE, DEFAULT_VERSION, load_project_config
from teipublisher.odd_compiler import compile_odd, PythonGenerator
from teipublisher.runtime.pm_runtime import resolve_context_element
from teipublisher.transform import load_transform_module, run_transform
from teipublisher.chunking import chunk_document

app = typer.Typer(
    name='teipublisher',
    help='TEI Publisher Python tools: compile ODD to Python, or run a transform on XML.',
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
        prefix='teipublisher-preview-',
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
    """Return CSS text from ``--css`` or ``styles/default-styles.css`` if that file exists."""
    path = css_path if css_path is not None else Path('styles/default-styles.css')
    if css_path is None and not path.is_file():
        return None
    return path.read_text(encoding='utf-8')


@app.command('compile')
def compile_cmd(
    odd: Annotated[Path, typer.Argument(help='Path to the .odd file')],
    output: Annotated[
        Optional[Path],
        typer.Option(
            '--output',
            '-o',
            help=(
                'Write generated code to this file (default: '
                'modules/<odd-basename>-<mode>.<ext> below the current working directory)'
            ),
        ),
    ] = None,
    module_name: Annotated[
        str,
        typer.Option(help='Logical module name (recorded in the generated docstring only)'),
    ] = 'generated_odd',
    mode: Annotated[
        str,
        typer.Option(
            '--mode',
            '-m',
            help='ODD processing-model output channel: web (HTML), markdown, typst, docx, … (@output on models; default: web).',
        ),
    ] = 'web',
    target: Annotated[
        str,
        typer.Option(
            '--target',
            '-t',
            help='Target language for code generation (currently only python).',
        ),
    ] = 'python',
) -> None:
    """Emit a transformation module from a TEI Publisher ODD."""
    src = compile_odd(str(odd), target=target, module_name=module_name, output_mode=mode)
    if output is not None:
        dest = output
    else:
        ext = PythonGenerator().file_extension if target == 'python' else f'.{target}'
        dest = Path('modules') / f'{odd.stem}-{mode}{ext}'
        dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src, encoding='utf-8')
    typer.echo(f'Compiled {odd} → {typer.style(str(dest), fg=typer.colors.GREEN, bold=True)}')


@app.command('transform')
def transform_cmd(
    input_xml: Annotated[Optional[Path], typer.Argument(help='Input XML file')] = None,
    transform_script: Annotated[
        Optional[Path],
        typer.Option('--module', '-m', help='Path to the .py file (must define transform()). Falls back to transform.module in config.'),
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
                'Falls back to the webcomponents.enabled setting in default.toml.'
            ),
        ),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option(
            '--config',
            '-c',
            help='Path to a TOML configuration file (default: default.toml in the current directory).',
        ),
    ] = None,
) -> None:
    """Load a transformation script and print the result (HTML, markdown, …) for an XML document."""
    try:
        cfg = load_project_config(config)
        for p in cfg.pythonpath:
            entry = str(p.resolve())
            if entry not in sys.path:
                sys.path.insert(0, entry)

        effective_script = transform_script or cfg.transform_module
        if effective_script is None:
            typer.echo(
                'teipublisher: error: transform script is required. '
                'Pass it as an argument or set transform.module in your config.',
                err=True,
            )
            raise SystemExit(1)
        if input_xml is None:
            typer.echo('teipublisher: error: input XML file is required.', err=True)
            raise SystemExit(1)

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

        parameters = _parameters_from_cli(param if param else None)
        # Add input_path to parameters for image processing in DOCX output
        if parameters is None:
            parameters = {}
        parameters['input_path'] = str(input_xml)
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
        typer.echo(f'teipublisher: error: {e}', err=True)
        raise SystemExit(1) from e


@app.command()
def chunk(
    input_xml: Annotated[
        Optional[Path],
        typer.Argument(
            help='XML file to transform and chunk.',
        ),
    ] = None,
    transform_script: Annotated[
        Optional[Path],
        typer.Option(
            '--module', '-m',
            help='Path to a Python transform script. Falls back to chunking.module in config.',
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
                'Falls back to the webcomponents.enabled setting in default.toml.'
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
                'Falls back to transform.xpath_extensions in default.toml.'
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
            help='Path to a TOML configuration file (default: default.toml in the current directory).',
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
            typer.echo('teipublisher: error: input XML file is required.', err=True)
            raise SystemExit(1)

        if not cfg.chunking:
            typer.echo(
                'teipublisher: error: no [chunking] section found in config.',
                err=True
            )
            raise SystemExit(1)
        
        # Override config with CLI options
        chunking_config = cfg.chunking
        if output_dir:
            chunking_config.output_dir = str(output_dir)
        if template:
            chunking_config.template = template
        
        # Check if output directory exists
        out_dir = Path.cwd() / chunking_config.output_dir
        if out_dir.exists() and not force:
            typer.echo(
                f'teipublisher: error: output directory {out_dir} already exists. '
                'Use --force to overwrite.',
                err=True
            )
            raise SystemExit(1)
        
        # Resolve template path
        effective_template = None
        if chunking_config.template:
            if chunking_config.template.is_absolute():
                effective_template = chunking_config.template
            else:
                effective_template = Path.cwd() / chunking_config.template
        
        effective_webcomponents = (
            True if output_format in ('json', 'pb-view')
            else (webcomponents if webcomponents is not None else (cfg.webcomponents_enabled or False))
        )
        effective_extensions: tuple[str, ...] | None = (
            tuple(xpath_extensions) if xpath_extensions else None
        )

        # Chunk the document
        effective_chunk_script = transform_script or (cfg.chunking.module if cfg.chunking else None)
        typer.echo(f'Chunking {input_xml} using {effective_chunk_script or "module from config"}...')
        with typer.progressbar(length=0, label='Processing chunks') as progress:
            def _on_progress(current: int, total: int) -> None:
                if progress.length == 0:
                    progress.length = total  # type: ignore[assignment]
                progress.update(1)

            if output_format not in ('html', 'json', 'pb-view'):
                typer.echo(
                    'teipublisher: error: --format must be "html", "json" or "pb-view", '
                    f'got {output_format!r}',
                    err=True,
                )
                raise SystemExit(1)

            effective_doc_path = doc_path or chunking_config.doc_path

            chunk_document(
                module_path=transform_script or None,
                xml_path=input_xml,
                config=chunking_config,
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
            data_subdir = f'{effective_doc_path}/' if effective_doc_path else ''
            typer.echo(f'  - {data_subdir}index.json: pb-view lookup table')
            typer.echo(f'  - {data_subdir}<xml:id>.json: part files')
            resolved_module = transform_script or chunking_config.module
            odd_name = getattr(load_transform_module(resolved_module), 'ODD_NAME', '') if resolved_module else ''
            typer.echo(f'  - css/{odd_name}.css: ODD stylesheet')
        else:
            ext = 'json' if output_format == 'json' else 'html'
            typer.echo('  - manifest.json: metadata for static site builders')
            typer.echo(f'  - *.{ext}: chunk files')
        
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        typer.echo(f'teipublisher: error: {e}', err=True)
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
            help='Path to a TOML configuration file (default: default.toml in the current directory).',
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
        typer.echo(f'teipublisher: error: directory {root} does not exist.', err=True)
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
        cmd.main(args=argv, prog_name='teipublisher', standalone_mode=False)
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
