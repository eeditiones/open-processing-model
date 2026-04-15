"""Unified CLI: ``teipublisher compile`` and ``teipublisher transform``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Annotated, Optional

import typer
from click.exceptions import NoArgsIsHelpError, UsageError
from lxml import etree
from typer.main import get_command

from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python
from tei_publisher_py.pm_runtime import resolve_context_element, serialize as default_serialize

app = typer.Typer(
    name='teipublisher',
    help='TEI Publisher Python tools: compile ODD to Python, or run a transform on XML.',
    no_args_is_help=True,
    context_settings={'help_option_names': ['-h', '--help']},
)


def load_transform_module(script_path: Path):
    """Load a Python file that defines ``transform(root, options=None)``."""
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
    return mod


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
                '<odd-basename>-<mode>.py in the current working directory)'
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
            help='ODD processing-model output channel (@output on models; default: web).',
        ),
    ] = 'web',
) -> None:
    """Emit a Python transformation module from a TEI Publisher ODD."""
    src = compile_odd_to_python(str(odd), module_name=module_name, output_mode=mode)
    dest = output if output is not None else Path(f'{odd.stem}-{mode}.py')
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
        typer.Option('--output', '-o', help='Write HTML output to this file (default: stdout)'),
    ] = None,
    param: Annotated[
        list[str],
        typer.Option(
            '--param',
            '-p',
            metavar='KEY=VALUE',
            help='Runtime parameter for XPath $parameters (repeatable), e.g. -p mode=toc -p display=browse',
        ),
    ] = [],
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
) -> None:
    """Load a transformation script and print HTML for an XML document."""
    try:
        mod = load_transform_module(transform_script)
        serialize = getattr(mod, 'serialize', default_serialize)

        tree = etree.parse(str(input_xml))
        doc_root = tree.getroot()
        opts = _parameters_from_cli(param if param else None)
        if xpath:
            root = resolve_context_element(
                doc_root,
                xpath,
                opts if opts else None,
            )
        else:
            root = doc_root

        result = mod.transform(root, opts if opts else None)
        out = serialize(result)
        if output:
            with open(output, 'w', encoding='utf-8') as f:
                print(out, file=f)
        else:
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
