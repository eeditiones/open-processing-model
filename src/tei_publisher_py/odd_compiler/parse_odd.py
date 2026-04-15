"""Parse ODD for schemaSpec namespace and elementSpec model trees."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

TEI_NS = 'http://www.tei-c.org/ns/1.0'


@dataclass
class ParsedOdd:
    tree: etree._ElementTree
    schema_ns: str
    odd_path: str


def load_odd(path: str | Path) -> ParsedOdd:
    p = Path(path).resolve()
    tree = etree.parse(str(p))
    root = tree.getroot()
    spec = root.find(f'.//{{{TEI_NS}}}schemaSpec')
    if spec is None:
        raise ValueError('No tei:schemaSpec in ODD')
    ns = spec.get('ns') or TEI_NS
    return ParsedOdd(tree=tree, schema_ns=ns, odd_path=str(p))


def iter_element_specs(parsed: ParsedOdd):
    """Yield tei:elementSpec elements in document order."""
    root = parsed.tree.getroot()
    for el in root.iter(f'{{{TEI_NS}}}elementSpec'):
        yield el


def has_models(spec_el) -> bool:
    return next(spec_el.iter(f'{{{TEI_NS}}}model'), None) is not None
