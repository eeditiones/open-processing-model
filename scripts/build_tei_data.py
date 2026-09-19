# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build and check the TEI artifact that ``opm odd document`` downloads.

The artifact is ``TEI/P5/p5.xml`` with XInclude resolved: the same specs as
``p5subset.xml`` plus the Guidelines chapter prose, so one fetch replaces both.
Run by ``.github/workflows/tei-data.yml``; usable by hand to reproduce a
release locally.
"""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path

from lxml import etree

TEI_NS = 'http://www.tei-c.org/ns/1.0'
XML_BASE = '{http://www.w3.org/XML/1998/namespace}base'

#: Below these the input is not a full Guidelines tree and something upstream
#: changed. Generous on purpose: this catches a truncated or wrong file, not
#: ordinary drift between TEI releases.
_MIN_COUNTS = {'elementSpec': 400, 'classSpec': 150, 'macroSpec': 4, 'dataSpec': 20}


def _q(tag: str) -> str:
    return f'{{{TEI_NS}}}{tag}'


def _counts(root: etree._Element) -> dict[str, int]:
    return {tag: len(root.findall(f'.//{_q(tag)}')) for tag in _MIN_COUNTS}


def _check(root: etree._Element) -> list[str]:
    """Reasons *root* is not a usable artifact."""
    problems = []
    counts = _counts(root)
    for tag, minimum in _MIN_COUNTS.items():
        if counts[tag] < minimum:
            problems.append(f'only {counts[tag]} {tag} (expected at least {minimum})')
    specs = root.findall(f'.//{_q("elementSpec")}')
    without_module = [e.get('ident') for e in specs if not e.get('module')]
    if without_module:
        problems.append(
            f'{len(without_module)} elementSpec without @module, e.g. '
            f'{without_module[:3]}'
        )
    without_content = [e.get('ident') for e in specs if e.find(_q('content')) is None]
    if without_content:
        problems.append(
            f'{len(without_content)} elementSpec without <content>, e.g. '
            f'{without_content[:3]}'
        )
    if root.find(f'.//{_q("xi:include")}') is not None:
        problems.append('unresolved XInclude')
    chapters = [
        div for part in root.iter(_q('front'), _q('body'), _q('back'))
        for div in part if etree.QName(div).localname == 'div'
    ]
    if len(chapters) < 20:
        problems.append(f'only {len(chapters)} chapters (expected the Guidelines prose)')
    return problems


class ArtifactError(Exception):
    """The file is not a usable TEI artifact."""


def _load(path: Path) -> etree._Element:
    parser = etree.XMLParser(
        remove_blank_text=False, resolve_entities=False, huge_tree=True,
        collect_ids=False,
    )
    try:
        if path.suffix == '.gz':
            with gzip.open(path, 'rb') as fh:
                return etree.parse(fh, parser).getroot()
        return etree.parse(str(path), parser).getroot()
    except (etree.XMLSyntaxError, OSError, EOFError) as exc:
        # A truncated download is the likely cause, so say that plainly
        # rather than printing a parser traceback.
        raise ArtifactError(f'{path} could not be parsed: {exc}') from exc


def build(source: Path, out: Path) -> int:
    parser = etree.XMLParser(
        remove_blank_text=False, resolve_entities=False, huge_tree=True,
        collect_ids=False,
    )
    doc = etree.parse(str(source), parser)
    doc.xinclude()
    root = doc.getroot()
    # xml:base is XInclude bookkeeping, meaningless once assembled, and it is
    # on every spec — dropping it saves size and noise.
    for el in root.iter():
        if isinstance(el.tag, str) and XML_BASE in el.attrib:
            del el.attrib[XML_BASE]
    problems = _check(root)
    if problems:
        print(f'{source} did not produce a usable artifact:', file=sys.stderr)
        for problem in problems:
            print(f'  - {problem}', file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.write(str(out), xml_declaration=True, encoding='UTF-8', pretty_print=False)
    counts = _counts(root)
    print(
        f'{out} ({out.stat().st_size:,} bytes) '
        f'TEI {root.get("version") or "?"} '
        + ', '.join(f'{tag}={n}' for tag, n in sorted(counts.items()))
    )
    return 0


def verify(path: Path) -> int:
    root = _load(path)
    problems = _check(root)
    if problems:
        print(f'{path} is not a usable artifact:', file=sys.stderr)
        for problem in problems:
            print(f'  - {problem}', file=sys.stderr)
        return 1
    print(f'{path} verified: TEI {root.get("version") or "?"}, {_counts(root)}')
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, help='TEI/P5/p5.xml to assemble')
    ap.add_argument('--out', type=Path, help='where to write p5all.xml')
    ap.add_argument('--verify', type=Path, help='check a built .xml or .xml.gz')
    ap.add_argument(
        '--print-version', type=Path, help='print TEI/@version of a built artifact',
    )
    args = ap.parse_args(argv)

    if args.print_version:
        print((_load(args.print_version).get('version') or 'unknown').strip())
        return 0
    if args.verify:
        return verify(args.verify)
    if not args.source or not args.out:
        ap.error('--source and --out are required to build')
    return build(args.source, args.out)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ArtifactError as exc:
        print(f'error: {exc}', file=sys.stderr)
        raise SystemExit(1) from None
