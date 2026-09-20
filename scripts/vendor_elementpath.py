# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Refresh ``src/opm/_vendor/elementpath`` from a checkout of the opm fork.

opm needs XQuery 3.1 — ODDs are shared with TEI Publisher, whose eXist runtime
evaluates XQuery, and the stock XPath 3.1 parser cannot run the element
constructors, ``let`` chains and ``try``/``catch`` those ODDs contain. The fork
at https://github.com/wolfgangmm/elementpath adds an ``xquery31`` package, but
it also patches elementpath's core (``tdop.Parser.seek``, ``XPathToken.as_name``,
the ``position`` argument of the tree builders), so the addition cannot be
shipped on its own against a release from PyPI.

Distributing the fork is what forces a copy into the tree rather than a
requirement: opm is published on PyPI, and PyPI rejects direct-URL/VCS
dependencies, so ``elementpath @ git+https://…`` can never reach anyone who
installs the wheel.

The copy is renamed to ``opm._vendor.elementpath``, as pip does with its own
vendored packages. A subpackage that kept the name would not work: elementpath
imports itself absolutely (``from elementpath.helpers import …``, 300-odd
times), and those would bind to whatever top-level ``elementpath`` the
environment happens to have — xmlschema pulls one in, for instance.

Nothing under ``src/opm/_vendor/`` is edited by hand. Fixes go to the fork, then
this script runs again.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

#: Where the vendored copy lives, relative to the repository root.
TARGET = Path('src/opm/_vendor/elementpath')

#: Directories never copied out of the fork.
_SKIP_DIRS = frozenset({'__pycache__', '.git', '.mypy_cache', '.ruff_cache'})

# The two shapes elementpath uses to import itself. Both are anchored at the
# start of a line but tolerate indentation: a handful sit inside `if
# TYPE_CHECKING:` blocks. Relative imports (`from .helpers import …`) already
# resolve within the copy and are left alone.
_FROM_IMPORT = re.compile(r'^(?P<indent>[ \t]*)from elementpath(?P<rest>\.|\s+import)', re.M)
_IMPORT_AS = re.compile(
    r'^(?P<indent>[ \t]*)import elementpath(?P<sub>\.[\w.]+)?(?P<as>\s+as\s)', re.M
)

#: Anything still importing the top-level package after the rewrite is a bug.
_LEFTOVER = re.compile(r'^[ \t]*(?:from|import) elementpath\b', re.M)


def rewrite(source: str) -> str:
    """Point *source*'s absolute self-imports at the vendored package."""
    source = _FROM_IMPORT.sub(r'\g<indent>from opm._vendor.elementpath\g<rest>', source)
    return _IMPORT_AS.sub(r'\g<indent>import opm._vendor.elementpath\g<sub>\g<as>', source)


def _git(fork: Path, *args: str) -> str:
    result = subprocess.run(
        ['git', '-C', str(fork), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else 'unknown'


def _copy_package(fork: Path, target: Path) -> list[Path]:
    """Replace *target* with the fork's ``elementpath`` package. Returns the files."""
    if target.exists():
        shutil.rmtree(target)

    written: list[Path] = []
    source_root = fork / 'elementpath'
    for path in sorted(source_root.rglob('*')):
        if _SKIP_DIRS & set(path.parts) or not path.is_file():
            continue
        if path.suffix == '.pyc':
            continue
        destination = target / path.relative_to(source_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == '.py':
            destination.write_text(rewrite(path.read_text()))
        else:
            shutil.copy2(path, destination)
        written.append(destination)
    return written


def _write_provenance(fork: Path, root: Path, version: str) -> None:
    """Record what was copied, so the copy can be traced back to a commit."""
    commit = _git(fork, 'rev-parse', 'HEAD')
    subject = _git(fork, 'log', '-1', '--format=%s')
    (root / 'src/opm/_vendor/README.md').write_text(
        f"""# Vendored dependencies

## elementpath

A fork of [elementpath](https://github.com/sissaschool/elementpath) adding an XQuery 3.1
parser, vendored because opm needs XQuery and the fork is not published anywhere PyPI
would let opm depend on it. MIT, as upstream; see `elementpath/LICENSE`.

| | |
|---|---|
| Upstream | <https://github.com/wolfgangmm/elementpath> |
| Commit | `{commit}` |
| Subject | {subject} |
| Base version | {version} |

Imports are rewritten from `elementpath.*` to `opm._vendor.elementpath.*`, so this copy
never collides with a stock elementpath in the same environment.

**Do not edit anything here.** Fix the fork, then run:

```sh
python scripts/vendor_elementpath.py <path-to-fork>
```
"""
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'fork',
        nargs='?',
        type=Path,
        default=Path('../elementpath'),
        help='checkout of the elementpath fork (default: ../elementpath)',
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    fork = args.fork.resolve()
    if not (fork / 'elementpath' / '__init__.py').is_file():
        print(f'Not an elementpath checkout: {fork}', file=sys.stderr)
        return 1

    target = root / TARGET
    written = _copy_package(fork, target)

    licence = fork / 'LICENSE'
    if licence.is_file():
        shutil.copy2(licence, target / 'LICENSE')
        written.append(target / 'LICENSE')

    leftovers = [
        path.relative_to(root)
        for path in written
        if path.suffix == '.py' and _LEFTOVER.search(path.read_text())
    ]
    if leftovers:
        print('Imports of the top-level package survived the rewrite:', file=sys.stderr)
        for path in leftovers:
            print(f'  {path}', file=sys.stderr)
        return 1

    version = re.search(
        r"^__version__ = '([^']+)'", (target / '__init__.py').read_text(), re.M
    )
    _write_provenance(fork, root, version.group(1) if version else 'unknown')

    print(f'Vendored {len(written)} files from {fork} → {TARGET}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
