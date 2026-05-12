"""Parse ODD for schemaSpec namespace and elementSpec model trees."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

TEI_NS = 'http://www.tei-c.org/ns/1.0'

# Real-world ODDs (e.g. tei_simplePrint.odd) carry duplicate xml:id values.
# collect_ids=False prevents lxml from rejecting them; xml:id is not used by
# the compiler — specs are located by @ident, not by xml:id lookup.
_PARSER = etree.XMLParser(collect_ids=False)


@dataclass
class ParsedOdd:
    tree: etree._ElementTree
    schema_ns: str
    odd_path: str
    element_specs: list
    odd_chain: list[str]
    nsmap: dict[str, str]  # prefix -> namespace URI from ODD root


def _schema_spec(root) -> etree._Element:
    spec = root.find(f'.//{{{TEI_NS}}}schemaSpec')
    if spec is None:
        raise ValueError('No tei:schemaSpec in ODD')
    return spec


def _resolve_source_paths(schema_spec, odd_path: Path) -> list[Path]:
    raw = (schema_spec.get('source') or '').strip()
    if not raw:
        return []
    out: list[Path] = []
    for token in raw.split():
        p = Path(token)
        if not p.is_absolute():
            p = (odd_path.parent / p).resolve()
        out.append(p)
    return out


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
    )


def iter_element_specs(parsed: ParsedOdd):
    """Yield tei:elementSpec elements in document order."""
    yield from parsed.element_specs


def has_models(spec_el) -> bool:
    return next(spec_el.iter(f'{{{TEI_NS}}}model'), None) is not None
