"""Shared helpers for the jinks template tests (no opm imports beyond the engine)."""

from __future__ import annotations

from pathlib import Path

from lxml import etree, html

from opm.jinks_templates import Environment


def _canonical(el) -> tuple:
    def norm(s: str | None) -> str:
        return ' '.join((s or '').split())

    children = tuple(_canonical(c) for c in el if isinstance(c.tag, str))
    texts = [norm(el.text)] + [norm(c.tail) for c in el]
    return (el.tag, tuple(sorted(el.attrib.items())), tuple(t for t in texts if t), children)


def html_equal(actual: str, expected: str) -> bool:
    """Compare two HTML fragments ignoring whitespace, like chai-html."""
    def parse(s: str):
        return html.fragment_fromstring(s, create_parent='root')
    return _canonical(parse(actual)) == _canonical(parse(expected))


def blank_lines(s: str) -> str:
    """Empty every line that holds only spaces or tabs, as the jinks text tests do."""
    return '\n'.join('' if not line.strip(' \t') else line for line in s.split('\n'))


def write_files(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    return root


SYSTEM_NS = 'http://exist-db.org/xquery/system'
DEMO_NS = 'https://tei-publisher.com/jinks/xquery/demo'
TEI_NS = 'http://www.tei-c.org/ns/1.0'

_TEI = etree.fromstring(
    f'<TEI xmlns="{TEI_NS}"><teiHeader><fileDesc><titleStmt><title>TEI Publisher</title>'
    '</titleStmt></fileDesc></teiHeader><text><body><p>TEI Publisher is a web-based application '
    'for creating and publishing TEI documents.</p></body></text></TEI>'
).getroottree()


def demo_environment(root: Path | None = None, **kwargs) -> Environment:
    """An environment with stand-ins for the eXist and demo functions jinks' tests call."""
    namespaces = {'system': SYSTEM_NS, 'demo': DEMO_NS, **kwargs.pop('namespaces', {})}
    functions = {
        'system:get-product-name': lambda: 'eXist',
        'demo:sysinfo': lambda title: etree.fromstring(
            f'<ul><li>Application title: {title}</li></ul>'),
        'demo:tei': lambda: _TEI,
        **kwargs.pop('functions', {}),
    }
    return Environment(root, namespaces=namespaces, functions=functions, **kwargs)
