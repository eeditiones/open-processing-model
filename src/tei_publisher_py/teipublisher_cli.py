"""Unified CLI: ``teipublisher compile`` and ``teipublisher transform``."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from lxml import etree

from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python
from tei_publisher_py.pm_runtime import resolve_context_element, serialize as default_serialize


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


def _cmd_compile(args: argparse.Namespace) -> int:
    src = compile_odd_to_python(args.odd, module_name=args.module_name)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(src)
    else:
        sys.stdout.write(src)
    return 0


def _cmd_transform(args: argparse.Namespace) -> int:
    mod = load_transform_module(args.transform_script)
    serialize = getattr(mod, 'serialize', default_serialize)

    tree = etree.parse(str(args.input))
    doc_root = tree.getroot()
    opts = _parameters_from_cli(args.param)
    if args.xpath:
        root = resolve_context_element(
            doc_root,
            args.xpath,
            opts if opts else None,
        )
    else:
        root = doc_root

    result = mod.transform(root, opts if opts else None)
    out = serialize(result)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            print(out, file=f)
    else:
        print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='teipublisher',
        description='TEI Publisher Python tools: compile ODD to Python, or run a transform on XML.',
    )
    sub = p.add_subparsers(dest='command', required=True)

    c = sub.add_parser(
        'compile',
        help='Emit a Python transformation module from a TEI Publisher ODD.',
    )
    c.add_argument('odd', help='Path to the .odd file')
    c.add_argument(
        '-o', '--output',
        help='Write output to this file (default: stdout)',
    )
    c.add_argument(
        '--module-name',
        default='generated_odd',
        help='Logical module name (recorded in the generated docstring only)',
    )
    c.set_defaults(func=_cmd_compile)

    t = sub.add_parser(
        'transform',
        help='Load a transformation script and print HTML for an XML document.',
    )
    t.add_argument(
        'transform_script',
        type=Path,
        help='Path to the .py file (must define transform())',
    )
    t.add_argument('input', type=Path, help='Input XML file')
    t.add_argument(
        '-o', '--output',
        type=Path,
        help='Write HTML output to this file (default: stdout)',
    )
    t.add_argument(
        '-p', '--param',
        action='append',
        default=[],
        metavar='KEY=VALUE',
        help='Runtime parameter for XPath $parameters (repeatable), e.g. -p mode=toc -p display=browse',
    )
    t.add_argument(
        '-x', '--xpath',
        metavar='EXPR',
        help=(
            'XPath 3.1 expression evaluated with the document root as the context item; '
            'the single selected element becomes the transform root. Unprefixed names use '
            'the same default element namespace as the document root. $parameters is bound '
            'from --param.'
        ),
    )
    t.set_defaults(func=_cmd_transform)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        if args.command == 'transform':
            print(f'teipublisher: error: {e}', file=sys.stderr)
            return 1
        raise


if __name__ == '__main__':
    raise SystemExit(main())
