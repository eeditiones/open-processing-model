# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build and check the TEI artifact that ``opm odd document`` downloads.

The artifact is ``P5/Source/guidelines-{lang}.xml`` with XInclude resolved: the
same specs as ``p5subset.xml`` plus the Guidelines chapter prose, so one fetch
replaces both. Note that ``P5/p5.xml`` is *not* the input — TEI gitignores it
as a build product of their Makefile, so it does not exist in a checkout.

The figures the prose shows (``graphic/@url``, all under ``Images/``) are not
in the XML, so ``--images-out`` packs them into a second artifact,
``images.tar.gz``, with their paths as the prose writes them.

Run by ``.github/workflows/tei-data.yml``; usable by hand to reproduce a
release locally.
"""

from __future__ import annotations

import argparse
import gzip
import re
import sys
import tarfile
from datetime import date as Date
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urljoin, urlparse

from lxml import etree

TEI_NS = 'http://www.tei-c.org/ns/1.0'
XML_BASE = '{http://www.w3.org/XML/1998/namespace}base'

#: Below these the input is not a full Guidelines tree and something upstream
#: changed. Generous on purpose: this catches a truncated or wrong file, not
#: ordinary drift between TEI releases.
_MIN_COUNTS = {'elementSpec': 400, 'classSpec': 150, 'macroSpec': 4, 'dataSpec': 20}


def describe_version(root: etree._Element) -> str:
    """How to label this tree, for logs and release notes.

    ``TEI/@version`` is the *schema* version (``5.0`` while 4.12.0 is the
    current P5 release), so it is not a release label. The P5 number lives in
    ``editionStmt/edition`` — but in a raw Source checkout that element is an
    unfilled template, populated only by TEI's own build. So report whichever
    is actually there and never dress the schema version up as a release: the
    workflow takes the release number from the git tag instead.
    """
    schema = (root.get('version') or '?').strip()
    for edition in root.iter(_q('edition')):
        text = re.sub(r"\s+", " ", " ".join(edition.itertext())).strip()
        match = re.search(r"\b(\d+\.\d+(?:\.\d+)?)\b", text)
        if match:
            return f"P5 {match.group(1)} (schema {schema})"
    return f"schema {schema}, P5 release unstated in source"

def _q(tag: str) -> str:
    return f'{{{TEI_NS}}}{tag}'


def _ordinal(day: int) -> str:
    """``28`` → ``28th``, the day format TEI's own build writes."""
    if 11 <= day % 100 <= 13:
        return f'{day}th'
    suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    return f'{day}{suffix}'


def _in_example(el: etree._Element) -> bool:
    """True inside ``egXML``/``eg``: specs quoted in prose are not the schema's."""
    parent = el.getparent()
    while parent is not None:
        if isinstance(parent.tag, str) and etree.QName(parent).localname in {'egXML', 'eg'}:
            return True
        parent = parent.getparent()
    return False


def figure_urls(root: etree._Element) -> list[str]:
    """The relative ``graphic/@url`` values the prose shows, in document order.

    Graphics quoted in examples are markup being explained, not figures, and
    an absolute URL or one climbing out of the tree is nothing to ship.
    """
    seen: dict[str, None] = {}
    for graphic in root.iter(_q('graphic')):
        url = (graphic.get('url') or '').strip()
        if url and not _in_example(graphic) and _is_local(url):
            seen.setdefault(url, None)
    return list(seen)


def _is_local(url: str) -> bool:
    if urlparse(url).scheme or url.startswith('/'):
        return False
    return '..' not in PurePosixPath(url).parts


def _figure_files(root: etree._Element) -> dict[str, Path]:
    """Each figure's URL and the file it names, resolved against its xml:base.

    Call before ``xml:base`` is stripped: XInclude records there which source
    file a chapter came from, and its figures are relative to that file.
    """
    urls = set(figure_urls(root))
    found: dict[str, Path] = {}
    for graphic in root.iter(_q('graphic')):
        url = (graphic.get('url') or '').strip()
        if url in urls and url not in found and not _in_example(graphic):
            base = graphic.base or ''
            found[url] = Path(unquote(urlparse(urljoin(base, url)).path))
    return found


def write_images(figures: dict[str, Path], out: Path) -> int:
    """Pack *figures* into the tar.gz at *out*, each under its URL; count them.

    A figure missing upstream is reported, not fatal: the page shows a broken
    image either way, and holding back the whole release for it helps no one.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    packed = 0
    with tarfile.open(out, 'w:gz') as tar:
        for url, path in sorted(figures.items()):
            if not path.is_file():
                print(f'figure not found upstream: {url} ({path})', file=sys.stderr)
                continue
            tar.add(path, arcname=str(PurePosixPath(url)), recursive=False)
            packed += 1
    print(f'{out} ({out.stat().st_size:,} bytes) {packed} figure(s)')
    return packed


def _spec_totals(root: etree._Element) -> dict[str, str]:
    """The counts TEI's prose quotes of itself ("There are N model classes…").

    Same definitions TEI's own build uses, which is why they come out at its
    published numbers: every spec but those quoted inside an example, and
    attributes counted by distinct name rather than by declaration.
    """
    classes = [c for c in root.iter(_q('classSpec')) if not _in_example(c)]
    attributes = {
        a.get('ident') for a in root.iter(_q('attDef'))
        if a.get('ident') and not _in_example(a)
    }
    return {
        'totalElements': str(
            sum(1 for e in root.iter(_q('elementSpec')) if not _in_example(e))
        ),
        'totalModelClasses': str(sum(1 for c in classes if c.get('type') == 'model')),
        'totalAttributeClasses': str(sum(1 for c in classes if c.get('type') == 'atts')),
        'totalAttributes': str(len(attributes)),
        'totalDataSpec': str(
            sum(1 for d in root.iter(_q('dataSpec')) if not _in_example(d))
        ),
    }


def expand_insert_pis(
    root: etree._Element,
    *,
    version: str = '',
    revision: str = '',
    when: Date | None = None,
) -> tuple[int, list[str]]:
    """Fill TEI's build-time ``<?insert …?>`` placeholders; report what is left.

    The Guidelines source carries its release number, date, revision and its
    own self-counts as processing instructions, which TEI's Makefile fills and
    a plain XInclude resolve does not: left alone they render as nothing, so
    the edition line reads "P5 ." and the copyright year is blank. A
    placeholder with no value stays a placeholder — a later build can still
    fill it, and an empty one would only hide that it was never supplied.
    """
    values = _spec_totals(root)
    if version:
        # TEI writes the word too: "P5 Version 4.12.0. Last updated on …".
        values['version'] = f'Version {version}'
    if revision:
        values['revision'] = revision
    if when is not None:
        values['date'] = f'{_ordinal(when.day)} {when.strftime("%B")} {when.year}'
        values['year'] = str(when.year)

    filled = 0
    unfilled: set[str] = set()
    for pi in list(root.iter(etree.ProcessingInstruction)):
        if pi.target != 'insert':
            continue
        key = (pi.text or '').strip()
        text = values.get(key)
        if not text:
            unfilled.add(key)
            continue
        parent = pi.getparent()
        if parent is None:
            continue
        tail = pi.tail or ''
        previous = pi.getprevious()
        if previous is None:
            parent.text = (parent.text or '') + text + tail
        else:
            previous.tail = (previous.tail or '') + text + tail
        parent.remove(pi)
        filled += 1
    return filled, sorted(unfilled)


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


def build(
    source: Path,
    out: Path,
    *,
    version: str = '',
    revision: str = '',
    when: Date | None = None,
    images_out: Path | None = None,
) -> int:
    parser = etree.XMLParser(
        remove_blank_text=False, resolve_entities=False, huge_tree=True,
        collect_ids=False,
    )
    doc = etree.parse(str(source), parser)
    doc.xinclude()
    root = doc.getroot()
    figures = _figure_files(root)
    # xml:base is XInclude bookkeeping, meaningless once assembled, and it is
    # on every spec — dropping it saves size and noise.
    for el in root.iter():
        if isinstance(el.tag, str) and XML_BASE in el.attrib:
            del el.attrib[XML_BASE]
    filled, unfilled = expand_insert_pis(
        root, version=version, revision=revision, when=when,
    )
    print(f'filled {filled} <?insert?> placeholder(s)')
    if unfilled:
        # tab-content-models is a table TEI generates; the rest mean the
        # release metadata was not passed in.
        print(f'left unfilled: {", ".join(unfilled)}', file=sys.stderr)
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
        f'TEI {describe_version(root)} '
        + ', '.join(f'{tag}={n}' for tag, n in sorted(counts.items()))
    )
    if images_out is not None:
        write_images(figures, images_out)
    return 0


def _check_images(root: etree._Element, images: Path) -> list[str]:
    """Reasons the figure archive *images* does not go with *root*."""
    try:
        with tarfile.open(images, 'r:gz') as tar:
            names = {
                member.name for member in tar.getmembers() if member.isfile()
            }
    except (tarfile.TarError, OSError, EOFError) as exc:
        return [f'{images} could not be read: {exc}']
    problems = [
        f'{name} in {images} escapes the archive'
        for name in sorted(names) if not _is_local(name)
    ]
    urls = figure_urls(root)
    missing = [url for url in urls if url not in names]
    if urls and len(missing) == len(urls):
        problems.append(f'{images} holds none of the {len(urls)} figures')
    elif missing:
        # The build already said so; one missing upstream is not a reason to
        # hold back the release.
        print(
            f'{len(missing)} figure(s) missing from {images}: {missing}',
            file=sys.stderr,
        )
    return problems


def verify(path: Path, images: Path | None = None) -> int:
    root = _load(path)
    problems = _check(root)
    if images is not None:
        problems += _check_images(root, images)
    if problems:
        print(f'{path} is not a usable artifact:', file=sys.stderr)
        for problem in problems:
            print(f'  - {problem}', file=sys.stderr)
        return 1
    print(f'{path} verified: TEI {describe_version(root)}, {_counts(root)}')
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        '--source', type=Path,
        help='P5/Source/guidelines-en.xml to XInclude-resolve',
    )
    ap.add_argument('--out', type=Path, help='where to write p5all.xml')
    ap.add_argument(
        '--version', default='',
        help='TEI release being built, e.g. 4.12.0 (fills <?insert version?>).',
    )
    ap.add_argument(
        '--revision', default='',
        help='Short commit of the TEI checkout (fills <?insert revision?>).',
    )
    ap.add_argument(
        '--date', default='',
        help='Release date as YYYY-MM-DD (fills <?insert date?> / <?insert year?>).',
    )
    ap.add_argument(
        '--images-out', type=Path,
        help='also pack the figures the prose shows into this .tar.gz',
    )
    ap.add_argument('--verify', type=Path, help='check a built .xml or .xml.gz')
    ap.add_argument(
        '--images', type=Path,
        help='with --verify: check this figure archive holds every figure',
    )
    ap.add_argument(
        '--print-version', type=Path,
        help='describe the TEI version of a built artifact',
    )
    args = ap.parse_args(argv)

    if args.print_version:
        print(describe_version(_load(args.print_version)))
        return 0
    if args.verify:
        return verify(args.verify, args.images)
    if not args.source or not args.out:
        ap.error('--source and --out are required to build')
    when = None
    if args.date:
        try:
            when = Date.fromisoformat(args.date)
        except ValueError:
            ap.error(f'--date must be YYYY-MM-DD, not {args.date!r}')
    return build(
        args.source, args.out,
        version=args.version, revision=args.revision, when=when,
        images_out=args.images_out,
    )


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ArtifactError as exc:
        print(f'error: {exc}', file=sys.stderr)
        raise SystemExit(1) from None
