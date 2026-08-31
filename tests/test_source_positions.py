"""Tests for line/column positions into the original XML text."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from opm.resources import packaged_odd
from opm.runtime import source_map, source_positions

ROOT = Path(__file__).resolve().parents[1]
ODD = packaged_odd('teipublisher')
DEMO_TEI_TEST_XML = ROOT / 'examples' / 'tei-test.xml'
TEI = 'http://www.tei-c.org/ns/1.0'

SAMPLE = f'''<TEI xmlns="{TEI}">
  <text><body>
    <p>hello <hi rend="i">there</hi></p>
    <p
       n="2">second</p>
  </body></text>
</TEI>'''.encode()


def _starts_at(raw: bytes, line: int, col: int) -> str:
    return raw.decode('utf-8').splitlines()[line - 1][col - 1:]


def test_positions_point_at_the_opening_angle_bracket() -> None:
    root = etree.fromstring(SAMPLE)
    positions = source_positions.build(SAMPLE, root)

    for element in root.iter():
        where = source_positions.lookup(element, positions)
        assert where is not None, element.tag
        local = etree.QName(element).localname
        assert _starts_at(SAMPLE, *where).startswith(f'<{local}')


def test_positions_beat_lxml_sourceline_on_a_wrapped_start_tag() -> None:
    """``sourceline`` reports where a start tag *ends*, not where it begins.

    An element whose attributes wrap lands on the wrong line — 24 of 260
    elements in ``examples/serafin``.
    """
    root = etree.fromstring(SAMPLE)
    wrapped = root.findall(f'.//{{{TEI}}}p')[1]
    positions = source_positions.build(SAMPLE, root)

    line, col = source_positions.lookup(wrapped, positions)
    assert _starts_at(SAMPLE, line, col).startswith('<p')
    assert wrapped.sourceline == line + 1  # lxml points one line too far down


def test_column_separates_elements_sharing_a_line() -> None:
    """Dense TEI puts many elements on one line, so a line alone is ambiguous."""
    root = etree.fromstring(SAMPLE)
    positions = source_positions.build(SAMPLE, root)

    para = root.findall(f'.//{{{TEI}}}p')[0]
    hi = root.find(f'.//{{{TEI}}}hi')
    assert source_positions.lookup(para, positions)[0] == \
        source_positions.lookup(hi, positions)[0]
    assert source_positions.lookup(para, positions)[1] != \
        source_positions.lookup(hi, positions)[1]


def test_map_is_discarded_when_the_source_does_not_match_the_tree() -> None:
    """A position pointing at the wrong element is worse than no position."""
    root = etree.fromstring(SAMPLE)
    other = b'<TEI xmlns="%s"><text/></TEI>' % TEI.encode()

    assert source_positions.build(other, root) == {}
    assert source_positions.build(b'not xml at all', root) == {}
    assert source_positions.build(Path('/no/such/file.xml'), root) == {}


def test_lookup_without_a_map_returns_none() -> None:
    root = etree.fromstring(SAMPLE)
    assert source_positions.lookup(root, {}) is None


def test_lookup_follows_a_chunk_copy_back_to_its_original() -> None:
    """Chunk selectors rebuild a region as a detached tree.

    Its elements are new objects, so they are absent from a map built over the
    source document and have to be resolved through the copy → source registry.
    """
    import copy

    root = etree.fromstring(SAMPLE)
    positions = source_positions.build(SAMPLE, root)
    original = root.find(f'.//{{{TEI}}}hi')

    detached = copy.deepcopy(original)
    source_map.clear()
    try:
        assert source_positions.lookup(detached, positions) is None
        source_map.record(detached, original)
        assert source_positions.lookup(detached, positions) == \
            source_positions.lookup(original, positions)
    finally:
        source_map.clear()


def test_a_childless_origin_is_not_discarded() -> None:
    """``source_of(x) or x`` truth-tests the element, and a childless one is falsy.

    lxml warns about this; the fallback has to be an explicit ``is None``.
    """
    root = etree.fromstring(SAMPLE)
    positions = source_positions.build(SAMPLE, root)
    leaf = root.find(f'.//{{{TEI}}}hi')
    # No children is what makes an lxml element falsy today, and this one is a
    # perfectly good element. (Asserting `not leaf` here would itself warn.)
    assert len(leaf) == 0

    detached = etree.fromstring(b'<hi/>')
    source_map.clear()
    try:
        source_map.record(detached, leaf)
        assert source_positions.lookup(detached, positions) is not None
    finally:
        source_map.clear()


# ── end to end ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_every_record_position_lands_on_its_own_start_tag() -> None:
    from opm.odd_compiler import compile_odd

    namespace: dict = {}
    exec(compile_odd(str(ODD), output_mode='json'), namespace)  # noqa: S102
    root = etree.parse(str(DEMO_TEI_TEST_XML)).getroot()
    payload = json.loads(
        namespace['transform'](root, {'input_path': str(DEMO_TEI_TEST_XML)})[0],
    )

    raw = DEMO_TEI_TEST_XML.read_bytes()

    def walk(record):
        if isinstance(record, dict):
            yield record
            for child in record.get('children', []):
                yield from walk(child)

    records = [r for rt in payload['document'] for r in walk(rt)]
    positioned = [r for r in records if 'line' in r]
    assert positioned
    assert len(positioned) == len(records)
    for record in positioned:
        text = _starts_at(raw, record['line'], record['col'])
        assert text.startswith(f'<{record["element"]}'), record


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_records_omit_position_without_a_source_file() -> None:
    """A caller transforming a tree it built itself has no text to point at."""
    from opm.odd_compiler import compile_odd

    namespace: dict = {}
    exec(compile_odd(str(ODD), output_mode='json'), namespace)  # noqa: S102
    root = etree.parse(str(DEMO_TEI_TEST_XML)).getroot()
    payload = json.loads(namespace['transform'](root)[0])

    def walk(record):
        if isinstance(record, dict):
            yield record
            for child in record.get('children', []):
                yield from walk(child)

    records = [r for rt in payload['document'] for r in walk(rt)]
    assert records
    assert not [r for r in records if 'line' in r]
