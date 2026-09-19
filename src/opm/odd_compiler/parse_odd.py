# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Parse ODD for schemaSpec namespace and elementSpec model trees."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from lxml import etree

from opm.xml_parser import make_parser

TEI_NS = 'http://www.tei-c.org/ns/1.0'

# Real-world ODDs (e.g. tei_simplePrint.odd) carry duplicate xml:id values.
# collect_ids=False prevents lxml from rejecting them; xml:id is not used by
# the compiler — specs are located by @ident, not by xml:id lookup.
_PARSER = make_parser()


@dataclass(frozen=True)
class OddLicence:
    """The rights statement an ODD declares in its own ``teiHeader``.

    A compiled module incorporates the processing models of every ODD in the
    inheritance chain, and the stock ones are CC BY — which asks for attribution
    wherever the material goes. Carrying the statement into the generated code is
    how that attribution survives a compile step nobody watches.
    """

    odd: str  # file name, not path: the generated module is not about this machine
    title: str | None = None
    publisher: str | None = None
    licence: str | None = None
    target: str | None = None
    #: The prose of ``availability`` — copyright holders, and the provenance of
    #: anything the ODD was built on. Reproduced rather than summarised: naming
    #: who is owed credit is the whole point of carrying the statement along.
    notes: tuple[str, ...] = ()


@dataclass
class ParsedOdd:
    tree: etree._ElementTree
    schema_ns: str
    odd_path: str
    element_specs: list
    odd_chain: list[str]
    nsmap: dict[str, str]  # prefix -> namespace URI from ODD root
    #: Rights statements along ``odd_chain``, parents first. ODDs that declare
    #: none are left out, so this is empty when nothing claims anything.
    licences: list[OddLicence] = field(default_factory=list)


def spec_origin(spec_el) -> Path | None:
    """The ODD file an ``elementSpec`` was parsed from.

    `_collect_element_specs` merges inherited specs *by reference*, so a
    spec taken from a parent ODD still belongs to that file's tree and
    ``docinfo.URL`` names it. That is what separates "I wrote this" from "I
    inherited this" — the only question that tells an ODD author whether editing
    the local file can change a decision at all.

    Returns ``None`` when the origin cannot be determined (a spec built in
    memory has no document URL).
    """
    tree = spec_el.getroottree()
    url = tree.docinfo.URL if tree is not None else None
    if not url:
        return None
    if url.startswith('file://'):
        url = unquote(urlparse(url).path)
    origin = Path(url)
    try:
        return origin.resolve()
    except OSError:
        return origin


def _schema_spec(root) -> etree._Element:
    spec = root.find(f'.//{{{TEI_NS}}}schemaSpec')
    if spec is None:
        raise ValueError('No tei:schemaSpec in ODD')
    return spec


def resolve_schema_source(token: str, odd_path: Path) -> Path:
    """Resolve one ``schemaSpec/@source`` token to an ODD file.

    Relative tokens are tried next to *odd_path* first, then as a packaged
    stock ODD (``teipublisher.odd``, ``docbook.odd``, …).
    """
    p = Path(token)
    if p.is_absolute():
        return p
    sibling = (odd_path.parent / p).resolve()
    if sibling.is_file():
        return sibling
    try:
        from opm.resources import packaged_odd

        return packaged_odd(p.name).resolve()
    except FileNotFoundError:
        return sibling


def _resolve_source_paths(schema_spec, odd_path: Path) -> list[Path]:
    raw = (schema_spec.get('source') or '').strip()
    if not raw:
        return []
    return [resolve_schema_source(token, odd_path) for token in raw.split()]


def _collect_element_specs(odd_path: Path, seen: set[Path]) -> list:
    odd_path = odd_path.resolve()
    if odd_path in seen:
        raise ValueError(f'Circular ODD inheritance via schemaSpec@source: {odd_path}')
    seen.add(odd_path)

    tree = etree.parse(str(odd_path), _PARSER)
    root = tree.getroot()
    schema_spec = _schema_spec(root)

    # Parent ODDs first, then local ODD; same ident always overwrites earlier.
    merged: dict[str, etree._Element] = {}
    for source_path in _resolve_source_paths(schema_spec, odd_path):
        for spec in _collect_element_specs(source_path, seen):
            ident = spec.get('ident')
            if ident:
                merged[ident] = spec

    for spec in root.iter(f'{{{TEI_NS}}}elementSpec'):
        ident = spec.get('ident')
        if ident:
            merged[ident] = spec

    seen.remove(odd_path)
    return list(merged.values())


def _collect_odd_chain(odd_path: Path, seen: set[Path]) -> list[Path]:
    """Return inherited ODD files in load order: parent(s) first, then *odd_path*."""
    odd_path = odd_path.resolve()
    if odd_path in seen:
        raise ValueError(f'Circular ODD inheritance via schemaSpec@source: {odd_path}')
    seen.add(odd_path)

    tree = etree.parse(str(odd_path), _PARSER)
    root = tree.getroot()
    schema_spec = _schema_spec(root)

    chain: list[Path] = []
    for source_path in _resolve_source_paths(schema_spec, odd_path):
        chain.extend(_collect_odd_chain(source_path, seen))
    chain.append(odd_path)

    seen.remove(odd_path)
    return chain


def _normalized_text(el) -> str | None:
    """All text under *el* as one whitespace-collapsed line, or ``None`` if empty."""
    if el is None:
        return None
    return ' '.join(''.join(el.itertext()).split()) or None


def _odd_title(root) -> str | None:
    title = root.find(
        f'{{{TEI_NS}}}teiHeader/{{{TEI_NS}}}fileDesc/{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}title'
    )
    if title is None:
        return None
    # A title usually wraps a <desc>; its own direct text is the name on its own.
    return ' '.join((title.text or '').split()) or _normalized_text(title)


def read_licence(odd_path: str | Path) -> OddLicence | None:
    """The rights statement *odd_path* declares, or ``None`` if it declares none.

    Read from ``teiHeader/fileDesc/publicationStmt`` by an explicit path rather
    than a descendant search: an ODD's body may quote a whole TEI header inside
    an example, and that header is documentation, not a claim about this file.
    """
    try:
        root = etree.parse(str(odd_path), _PARSER).getroot()
    except (OSError, etree.XMLSyntaxError):
        return None
    pub = root.find(f'{{{TEI_NS}}}teiHeader/{{{TEI_NS}}}fileDesc/{{{TEI_NS}}}publicationStmt')
    if pub is None:
        return None
    availability = pub.find(f'{{{TEI_NS}}}availability')
    licence_el = None if availability is None else availability.find(f'{{{TEI_NS}}}licence')
    publisher = _normalized_text(pub.find(f'{{{TEI_NS}}}publisher'))
    licence = _normalized_text(licence_el)
    notes = (
        ()
        if availability is None
        else tuple(
            note
            for note in (
                _normalized_text(p) for p in availability.findall(f'{{{TEI_NS}}}p')
            )
            if note
        )
    )
    if not (licence or publisher):
        return None
    return OddLicence(
        odd=Path(odd_path).name,
        title=_odd_title(root),
        publisher=publisher,
        licence=licence,
        target=licence_el.get('target') if licence_el is not None else None,
        notes=notes,
    )


def _collect_licences(odd_chain: list[Path]) -> list[OddLicence]:
    licences: list[OddLicence] = []
    for odd_path in odd_chain:
        licence = read_licence(odd_path)
        if licence is not None and licence not in licences:
            licences.append(licence)
    return licences


def load_odd(path: str | Path) -> ParsedOdd:
    p = Path(path).resolve()
    # collect_ids=False avoids rejecting real-world ODDs that carry duplicate
    # xml:id values (e.g. tei_simplePrint.odd). xml:id indexing is not needed
    # by the compiler — specs are located by ident, not by xml:id lookup.
    tree = etree.parse(str(p), _PARSER)
    root = tree.getroot()
    spec = _schema_spec(root)
    # Respect explicit empty ns="" (no namespace) vs missing ns (default to TEI_NS)
    ns_attr = spec.get('ns')
    ns = TEI_NS if ns_attr is None else ns_attr
    odd_chain = _collect_odd_chain(p, set())
    element_specs = _collect_element_specs(p, set())
    # Collect namespace mappings from ODD root element (for XPath expressions)
    nsmap = {k: v for k, v in root.nsmap.items() if k is not None}  # exclude default namespace
    return ParsedOdd(
        tree=tree,
        schema_ns=ns,
        odd_path=str(p),
        element_specs=element_specs,
        odd_chain=[str(x) for x in odd_chain],
        nsmap=nsmap,
        licences=_collect_licences(odd_chain),
    )


def iter_element_specs(parsed: ParsedOdd):
    """Yield tei:elementSpec elements in document order."""
    yield from parsed.element_specs


def has_models(spec_el) -> bool:
    return next(spec_el.iter(f'{{{TEI_NS}}}model'), None) is not None
