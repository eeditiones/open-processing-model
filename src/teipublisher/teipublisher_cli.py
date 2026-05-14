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
    """Return ``'html'``, ``'markdown'``, or ``'text'`` based on ``transform_output_channels()``."""
    raw = mod.transform_output_channels()
    if not raw:
        return 'text'
    primary = raw[0] if isinstance(raw, (list, tuple)) else raw
    if primary == 'markdown':
        return 'markdown'
    if primary == 'web':
        return 'html'
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
            help='ODD processing-model output channel: web (HTML), markdown, print, … (@output on models; default: web).',
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


@app.command('transform')
def transform_cmd(
    transform_script: Annotated[
        Path,
        typer.Argument(help='Path to the .py file (must define transform())'),
    ],
    input_xml: Annotated[Path, typer.Argument(help='Input XML file')],
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
            help='Optional Jinja2 template path for full-document HTML output.',
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
                'Falls back to the webcomponents.enabled setting in teipublisher.toml.'
            ),
        ),
    ] = None,
) -> None:
    """Load a transformation script and print the result (HTML, markdown, …) for an XML document."""
    try:
        cfg = load_project_config()
        effective_webcomponents = webcomponents if webcomponents is not None else (cfg.webcomponents_enabled or False)
        effective_template = template if template is not None else cfg.document_template
        effective_css = css if css is not None else cfg.document_css
        effective_extensions: tuple[str, ...] = (
            tuple(xpath_extensions) if xpath_extensions else cfg.xpath_extensions
        )

        mod = load_transform_module(transform_script)
        parameters = _parameters_from_cli(param if param else None)
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
        )

        if output:
            output.write_text(out, encoding='utf-8')
        if preview:
            kind = _preview_kind_from_module(mod)
            if kind == 'html':
                _preview_html_in_browser(out)
            elif kind == 'markdown':
                _preview_markdown_terminal(out)
            else:
                _preview_plain_terminal(out)
        elif not output:
            print(out)
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        typer.echo(f'teipublisher: error: {e}', err=True)
        raise SystemExit(1) from e


@app.command()
def chunk(
    transform_script: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            help='Path to a Python transform script generated by ``teipublisher compile``.',
        ),
    ],
    input_xml: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            help='XML file to transform and chunk.',
        ),
    ],
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
                'Falls back to the webcomponents.enabled setting in teipublisher.toml.'
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
                'Falls back to transform.xpath_extensions in teipublisher.toml.'
            ),
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option(
            '--format',
            help=(
                'Output format for chunk files: "html" (default, rendered via Jinja2 template) '
                'or "json" (one JSON file per chunk containing content, head, odd_css, and '
                'fragments — suitable for static site generators such as Eleventy).'
            ),
        ),
    ] = 'html',
) -> None:
    """Chunk a large XML document into smaller HTML pages or JSON data files."""
    try:
        cfg = load_project_config()
        
        # Check if chunking is enabled in config
        if not cfg.chunking or not cfg.chunking.enabled:
            typer.echo(
                'teipublisher: error: chunking not enabled in teipublisher.toml. '
                'Add [chunking] enabled = true to your configuration.',
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
            True if output_format == 'json'
            else (webcomponents if webcomponents is not None else (cfg.webcomponents_enabled or False))
        )
        effective_extensions: tuple[str, ...] | None = (
            tuple(xpath_extensions) if xpath_extensions else None
        )

        # Chunk the document
        typer.echo(f'Chunking {input_xml} using {transform_script}...')
        with typer.progressbar(length=0, label='Processing chunks') as progress:
            def _on_progress(current: int, total: int) -> None:
                if progress.length == 0:
                    progress.length = total  # type: ignore[assignment]
                progress.update(1)

            if output_format not in ('html', 'json'):
                typer.echo(
                    f'teipublisher: error: --format must be "html" or "json", got {output_format!r}',
                    err=True,
                )
                raise SystemExit(1)

            chunk_document(
                module_path=transform_script,
                xml_path=input_xml,
                config=chunking_config,
                project_root=Path.cwd(),
                template_path=effective_template,
                on_progress=_on_progress,
                project_config=cfg,
                webcomponents=effective_webcomponents,
                xpath_extensions=effective_extensions,
                output_format=output_format,
            )
        
        ext = 'json' if output_format == 'json' else 'html'
        typer.echo(f'Chunks written to {out_dir}/')
        typer.echo(f'  - manifest.json: metadata for static site builders')
        typer.echo(f'  - *.{ext}: chunk files')
        
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        typer.echo(f'teipublisher: error: {e}', err=True)
        raise SystemExit(1) from e


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
