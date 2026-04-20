"""Unified CLI: ``teipublisher compile`` and ``teipublisher transform``."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Annotated, Optional

import typer
from click.exceptions import NoArgsIsHelpError, UsageError
from lxml import etree
from typer.main import get_command

from tei_publisher_py.config import DEFAULT_CDN_TEMPLATE, DEFAULT_VERSION, load_project_config
from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python
from tei_publisher_py.pm_runtime import resolve_context_element, serialize as default_serialize
from tei_publisher_py.template_rendering import (
    render_document_template,
    resolve_template_path,
)

app = typer.Typer(
    name='teipublisher',
    help='TEI Publisher Python tools: compile ODD to Python, or run a transform on XML.',
    no_args_is_help=True,
    context_settings={'help_option_names': ['-h', '--help']},
)


def load_transform_module(script_path: Path):
    """Load a Python file that defines ``transform()`` and ``transform_output_channels()``."""
    path = script_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Not a file: {path}')
    name = f'tei_transform_{path.stem}'
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load module from {path}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, 'transform'):
        raise AttributeError(
            f'{path} has no transform() — expected a TEI Publisher transform module',
        )
    if not hasattr(mod, 'transform_output_channels'):
        raise AttributeError(
            f'{path} has no transform_output_channels() — expected a module emitted by teipublisher compile',
        )
    return mod


def _preview_kind_from_module(mod) -> str:
    """Return ``'html'``, ``'markdown'``, or ``'text'`` (plain terminal) from ``transform_output_channels()``."""
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
    """Return CSS text from ``--css`` or default ``styles/default-styles.css`` if present."""
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
                'Write generated Python to this file (default: '
                'modules/<odd-basename>-<mode>.py below the current working directory)'
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
) -> None:
    """Emit a Python transformation module from a TEI Publisher ODD."""
    src = compile_odd_to_python(str(odd), module_name=module_name, output_mode=mode)
    if output is not None:
        dest = output
    else:
        dest = Path('modules') / f'{odd.stem}-{mode}.py'
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
        Optional[str],
        typer.Option(
            '--xpath-extensions',
            help=(
                'Dotted import path of a Python module whose public callables become XPath '
                'functions in the tp: namespace (e.g. extensions.common). Importing the module '
                'runs its top-level code: only use trusted code.'
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

        mod = load_transform_module(transform_script)
        serialize = getattr(mod, 'serialize', default_serialize)

        tree = etree.parse(str(input_xml))
        doc_root = tree.getroot()
        opts = _parameters_from_cli(param if param else None)
        user_css = _resolve_user_css(effective_css)
        if xpath:
            root = resolve_context_element(
                doc_root,
                xpath,
                opts if opts else None,
                xpath_extensions=xpath_extensions,
            )
        else:
            root = doc_root

        transform_opts = dict(opts)
        if xpath_extensions:
            transform_opts['xpath_extensions'] = xpath_extensions
        if effective_webcomponents:
            transform_opts['webcomponents'] = True
        result = mod.transform(root, transform_opts if transform_opts else None)
        is_document_result = any(
            isinstance(item, etree._Element) and etree.QName(item).localname == 'html'
            for item in result
        )
        out = serialize(result)
        kind = _preview_kind_from_module(mod)
        if kind == 'html' and is_document_result:
            tpl = resolve_template_path(effective_template)
            webcomponents_url = None
            if effective_webcomponents:
                webcomponents_url = cfg.webcomponents_cdn or DEFAULT_CDN_TEMPLATE.replace('{version}', DEFAULT_VERSION)
            out = render_document_template(
                serialized_html=out,
                template_path=tpl,
                odd_css=getattr(mod, 'ODD_GENERATED_CSS', ''),
                user_css=user_css,
                parameters=opts,
                webcomponents_url=webcomponents_url,
            )
        if output:
            output.write_text(out, encoding='utf-8')
        if preview:
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
