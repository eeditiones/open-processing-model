"""Tests for ``opm index`` — rolling JSON-mode records up into index units."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opm.indexing import (
    FieldSpec, IndexOptions, UnitSpec, _fragment_plain_text, build_records, write_jsonl,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO_TEI_TEST_XML = ROOT / 'examples' / 'tei-test.xml'


def _para(text: str, xml_id: str | None = None, xpath: str = '/*/p') -> dict:
    """A paragraph record. Text lives in ``children``, as it does in real output."""
    record: dict = {
        'xpath': xpath,
        'element': 'p',
        'behaviour': 'paragraph',
        'model': 'tei-p1',
        'children': [text],
    }
    if xml_id:
        record['id'] = xml_id
    return record


def _section(xml_id: str, heading: str, *children: dict, xpath: str = '/*/div') -> dict:
    head = {
        'xpath': f'{xpath}/head',
        'element': 'head',
        'behaviour': 'heading',
        'model': 'tei-head1',
        'children': [heading],
    }
    return {
        'id': xml_id,
        'xpath': xpath,
        'element': 'div',
        'behaviour': 'section',
        'model': 'tei-div1',
        'children': [head, *children],
    }


def _build(document, **kwargs) -> list[dict]:
    kwargs.setdefault('doc_stem', 'doc')
    kwargs.setdefault('source', 'doc.xml')
    return build_records(document, **kwargs)


# ── shape ────────────────────────────────────────────────────────────────────

def test_metadata_values_are_scalars_or_string_lists() -> None:
    """Built-in labels are scalars; extracted fields are arrays of strings."""
    doc = [_section('s1', 'A heading', _para('Some prose that is long enough to keep.'))]
    records = _build(doc)

    assert records
    for record in records:
        for value in record['metadata'].values():
            if isinstance(value, list):
                assert value
                assert all(isinstance(item, str) for item in value)
            else:
                assert isinstance(value, (str, int, float, bool)), value


def test_breadcrumb_is_absent_unless_a_fragment_field_supplies_it() -> None:
    """The indexer does not invent a trail from headings."""
    inner = _section('s2', 'Inner', _para('Prose inside the nested section here.'),
                     xpath='/*/div/div')
    doc = [_section('s1', 'Outer', inner)]
    records = _build(doc)

    assert all('breadcrumb' not in r['metadata'] for r in records)


def test_page_metadata_is_copied_onto_every_record() -> None:
    inner = _section('s2', 'Inner', _para('Prose inside the nested section here.'),
                     xpath='/*/div/div')
    doc = [_section('s1', 'Outer', inner)]
    records = _build(doc, page_metadata={'breadcrumb': 'Outer > Inner'})

    crumbs = {r['metadata'].get('breadcrumb') for r in records}
    assert crumbs == {'Outer > Inner'}
    for record in records:
        assert isinstance(record['metadata']['breadcrumb'], str)


def test_unit_opens_at_each_section() -> None:
    doc = [
        _section('s1', 'First', _para('Prose belonging to the first section here.')),
        _section('s2', 'Second', _para('Prose belonging to the second section here.'),
                 xpath='/*/div[2]'),
    ]
    records = _build(doc)

    assert {r['metadata']['heading'] for r in records} == {'First', 'Second'}


def _heading(text: str, xpath: str = '/*/div/head') -> dict:
    return {
        'xpath': xpath,
        'element': 'head',
        'behaviour': 'heading',
        'model': 'tei-head1',
        'children': [text],
    }


def _units(*specs: UnitSpec, **tuning) -> IndexOptions:
    tuning.setdefault('min_chars', 1)
    return IndexOptions(units=specs, **tuning)


def test_declared_units_replace_titled_divisions() -> None:
    """``[[index.units]]`` is a replacement, so a wrapping section is not a passage."""
    doc = [_section(
        's1', 'Chapter',
        _para('The first paragraph, long enough to keep around.'),
        _para('The second paragraph, also long enough to keep.', xpath='/*/div/p[2]'),
    )]
    records = _build(doc, options=_units(
        UnitSpec(name='paragraph', behaviours=frozenset({'paragraph'})),
    ))

    assert [r['document'] for r in records] == [
        'The first paragraph, long enough to keep around.',
        'The second paragraph, also long enough to keep.',
    ]
    assert {r['metadata']['kind'] for r in records} == {'paragraph'}


def test_heading_unit_can_label_the_next_paragraph_without_emitting() -> None:
    doc = [{
        'xpath': '/*/div', 'element': 'div', 'behaviour': 'block', 'model': 'tei-div1',
        'children': [
            _heading('First steps'),
            _para('Click the visual editor to open it from here.'),
        ],
    }]
    records = _build(doc, options=_units(
        UnitSpec(name='heading', behaviours=frozenset({'heading'}), emit=False),
        UnitSpec(name='paragraph', behaviours=frozenset({'paragraph'})),
    ))

    assert len(records) == 1
    assert records[0]['metadata']['kind'] == 'paragraph'
    assert records[0]['metadata']['heading'] == 'First steps'
    assert 'breadcrumb' not in records[0]['metadata']
    assert 'First steps' not in records[0]['document']


def test_heading_unit_can_emit_its_own_record() -> None:
    doc = [{
        'xpath': '/*/div', 'element': 'div', 'behaviour': 'block', 'model': 'tei-div1',
        'children': [
            _heading('First steps'),
            _para('Click the visual editor to open it from here.'),
        ],
    }]
    records = _build(doc, options=_units(
        UnitSpec(name='heading', behaviours=frozenset({'heading'}), min_chars=1),
        UnitSpec(name='paragraph', behaviours=frozenset({'paragraph'})),
        min_chars=40,
    ))

    kinds = [r['metadata']['kind'] for r in records]
    assert kinds == ['heading', 'paragraph']
    assert records[0]['document'] == 'First steps'
    assert records[1]['metadata']['heading'] == 'First steps'


def test_fields_still_extract_from_declared_units() -> None:
    doc = [_section(
        's1', 'Heading',
        _para_with('Prose that carries a note', _note('The note text itself.'), '.'),
    )]
    records = _build(doc, options=IndexOptions(
        min_chars=1,
        units=(UnitSpec(name='paragraph', behaviours=frozenset({'paragraph'})),),
        fields=(FieldSpec(name='note', elements=frozenset({'note'}), metadata=False),),
    ))

    passage, note = records
    assert passage['metadata']['kind'] == 'paragraph'
    assert note['metadata']['kind'] == 'note'
    assert note['metadata']['parent'] == passage['id']
    assert 'note text itself' not in passage['document']


# ── ids ──────────────────────────────────────────────────────────────────────

def test_ids_are_stable_across_runs() -> None:
    doc = [_section('intro', 'Intro', _para('Prose long enough to survive min_chars.'))]
    assert [r['id'] for r in _build(doc)] == [r['id'] for r in _build(doc)]


def test_inserting_a_section_does_not_shift_later_ids() -> None:
    """A vector store upserts by id; a positional counter would orphan every row."""
    tail = _section('later', 'Later', _para('Prose in the section that comes later.'),
                    xpath='/*/div[2]')
    before = _build([_section('first', 'First', _para('Prose in the first section.')), tail])

    inserted = _section('inserted', 'Inserted', _para('Newly added prose in between.'),
                        xpath='/*/div[2]')
    after = _build([
        _section('first', 'First', _para('Prose in the first section.')),
        inserted,
        tail,
    ])

    later_before = [r['id'] for r in before if r['metadata'].get('heading') == 'Later']
    later_after = [r['id'] for r in after if r['metadata'].get('heading') == 'Later']
    assert later_before == later_after


def test_id_falls_back_to_an_xpath_hash_without_an_xml_id() -> None:
    doc = [{
        'xpath': '/*/div[3]',
        'element': 'div',
        'behaviour': 'section',
        'model': 'tei-div1',
        'children': [_para('Anonymous section prose, long enough to keep around.')],
    }]
    records = _build(doc)

    assert len(records) == 1
    assert records[0]['id'].startswith('doc#')
    assert 'xml_id' not in records[0]['metadata']


# ── splitting ────────────────────────────────────────────────────────────────

def test_oversized_unit_splits_into_parts() -> None:
    paras = [_para(f'Sentence number {i} padded out to a reasonable length. ' * 3)
             for i in range(12)]
    doc = [_section('big', 'Big', *paras)]
    records = _build(doc, options=IndexOptions(max_chars=400, min_chars=10, overlap=1))

    assert len(records) > 1
    assert {r['metadata']['n_parts'] for r in records} == {len(records)}
    assert [r['metadata']['part'] for r in records] == list(range(len(records)))
    assert all(r['metadata']['chars'] <= 600 for r in records)


def test_short_units_are_dropped() -> None:
    """A bare heading is retrieval noise, not a passage."""
    doc = [_section('stub', 'Stub', _para('Tiny.'))]
    records = _build(doc, options=IndexOptions(min_chars=200))
    assert records == []


# ── editorial judgment ───────────────────────────────────────────────────────

def test_suppressed_records_stay_out_of_the_index() -> None:
    """What the ODD omits is what the reader never sees — and must not be indexed."""
    omitted = {
        'xpath': '/*/div/del',
        'element': 'del',
        'behaviour': 'omit',
        'model': 'tei-del1',
        'suppressed': True,
        'children': [_para('STRUCK OUT TEXT that should never reach the index.')],
    }
    doc = [_section('s1', 'Heading', omitted,
                    _para('Kept prose that is long enough to survive.'))]
    records = _build(doc)

    corpus = ' '.join(r['document'] for r in records)
    assert 'STRUCK OUT' not in corpus
    assert 'Kept prose' in corpus


def test_own_text_is_not_counted_twice() -> None:
    """Each run of prose must enter the unit exactly once.

    ``children`` interleaves a record's own text runs with its child records,
    so walking a record's text *and* recursing would double every passage.
    """
    para = {
        'xpath': '/*/p',
        'element': 'p',
        'behaviour': 'paragraph',
        'model': 'tei-p1',
        'children': [
            'before ',
            {
                'xpath': '/*/p/hi', 'element': 'hi', 'behaviour': 'inline',
                'model': 'tei-hi1', 'children': ['middle'],
            },
            ' after',
        ],
    }
    doc = [_section('s1', 'Heading', para, _para('Filler prose to clear min_chars.'))]
    records = _build(doc)

    corpus = ' '.join(r['document'] for r in records)
    assert corpus.count('before') == 1
    assert corpus.count('middle') == 1


def test_heading_is_not_repeated_in_its_own_metadata() -> None:
    """Inline children inside a heading must not double it up."""
    head = {
        'xpath': '/*/div/head', 'element': 'head', 'behaviour': 'heading',
        'model': 'tei-head1',
        'children': [
            'Part one: ',
            {
                'xpath': '/*/div/head/hi', 'element': 'hi', 'behaviour': 'inline',
                'model': 'tei-hi1', 'children': ['the title'],
            },
        ],
    }
    doc = [{
        'id': 's1', 'xpath': '/*/div', 'element': 'div', 'behaviour': 'section',
        'model': 'tei-div1',
        'children': [head, _para('Body prose long enough to survive min_chars.')],
    }]
    records = _build(doc)

    assert records[0]['metadata']['heading'] == 'Part one: the title'


# ── hrefs ────────────────────────────────────────────────────────────────────

def test_href_resolves_against_the_chunk_anchor_map() -> None:
    doc = [_section('chapter-1', 'Chapter 1',
                    _para('Prose long enough to be worth indexing here.'))]
    records = _build(doc, anchors={'chapter-1': '001.html'})

    assert records[0]['metadata']['href'] == '001.html#chapter-1'


def test_href_is_absent_without_an_anchor_map() -> None:
    doc = [_section('chapter-1', 'Chapter 1',
                    _para('Prose long enough to be worth indexing here.'))]
    records = _build(doc)

    assert 'href' not in records[0]['metadata']
    assert records[0]['metadata']['xml_id'] == 'chapter-1'


# ── io ───────────────────────────────────────────────────────────────────────

def test_write_jsonl_emits_one_object_per_line(tmp_path: Path) -> None:
    doc = [_section('s1', 'Heading', _para('Prose long enough to be kept here.'))]
    path = tmp_path / 'records.jsonl'
    write_jsonl(_build(doc), path)

    lines = path.read_text(encoding='utf-8').splitlines()
    assert lines
    assert all(isinstance(json.loads(line), dict) for line in lines)


# ── end to end ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_index_document_on_the_demo_corpus(tmp_path: Path, monkeypatch) -> None:
    from opm.config import ProjectConfig
    from opm.indexing import index_document

    cache = tmp_path / 'cache'
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')
    monkeypatch.setattr('opm.resources.user_opm_cache_dir', lambda: cache)

    records = index_document(DEMO_TEI_TEST_XML, cfg=ProjectConfig())

    assert records
    assert len({r['id'] for r in records}) == len(records)
    corpus = ' '.join(r['document'] for r in records)
    # <choice><abbr>XML</abbr><expan>Extensible Markup Language</expan></choice>
    # resolves through `alternate` to the reading the page shows. An XPath
    # scrape of the same source would index "XMLExtensible Markup Language".
    assert 'Extensible Markup Language' in corpus
    assert 'XMLExtensible' not in corpus
    # teiHeader carries the `metadata` behaviour, so it is suppressed.
    assert 'Very Tremendous Texts' in corpus  # body content survives
    assert all('breadcrumb' not in r['metadata'] for r in records)


def test_index_copies_a_breadcrumb_fragment_onto_chunk_records(
    tmp_path: Path, monkeypatch,
) -> None:
    """The same fragment the page renders is copied onto every record from that chunk."""
    from opm.config import ChunkingConfig, FragmentConfig, ProjectConfig
    from opm.indexing import index_document
    from opm.resources import packaged_odd

    cache = tmp_path / 'cache'
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')
    monkeypatch.setattr('opm.resources.user_opm_cache_dir', lambda: cache)

    xml_path = tmp_path / 'guide.xml'
    xml_path.write_text(
        """<article xmlns="http://docbook.org/ns/docbook" version="5.0">
  <info><title>Guide</title></info>
  <section xml:id="install">
    <title>Install</title>
    <para>Intro prose long enough to keep as a passage.</para>
    <section xml:id="pip">
      <title>Using pip</title>
      <para>pip stuff long enough to keep as a passage.</para>
    </section>
  </section>
  <section xml:id="usage">
    <title>Usage</title>
    <para>use it, with enough characters to survive min_chars.</para>
  </section>
</article>
""",
        encoding='utf-8',
    )
    fields = (FieldSpec(name='breadcrumb', fragment='breadcrumbs'),)
    cfg = ProjectConfig(
        chunking=ChunkingConfig(
            selector='opm.navigation.dbk_section_chunks',
            depth=2,
            output_dir='chunks',
            fragments=[
                FragmentConfig(
                    name='breadcrumbs',
                    scope='per-chunk',
                    xpath='.',
                    parameters={'mode': 'breadcrumb'},
                ),
            ],
        ),
        xpath_extensions=('opm.runtime.common_xpath_functions',),
        index_fields=fields,
    )
    records = index_document(
        xml_path,
        cfg=cfg,
        odd=packaged_odd('docbook'),
        project_root=tmp_path,
        options=IndexOptions(min_chars=1, fields=fields),
    )

    crumbs = {r['metadata'].get('breadcrumb') for r in records}
    assert all(isinstance(c, str) for c in crumbs)
    assert any(c is not None and 'Guide' in c and 'Install' in c for c in crumbs)
    assert any(c is not None and 'Using pip' in c for c in crumbs)
    pip = next(r for r in records if r['metadata'].get('heading') == 'Using pip')
    assert pip['metadata']['breadcrumb'] == 'Guide > Install > Using pip'


# ── chunk integration ────────────────────────────────────────────────────────

def test_chunk_file_gives_every_record_a_link() -> None:
    """A chunk selector may rebuild the region as a detached tree.

    Its synthesised ids never existed in the source, so an href that depends on
    matching ``xml:id`` resolves for nothing. Knowing the chunk file is enough
    on its own.
    """
    doc = [_section('s1', 'Heading', _para('Prose long enough to be kept here.'))]
    records = _build(doc, chunk_file='003.html')

    assert records[0]['metadata']['href'] == '003.html#s1'
    assert records[0]['metadata']['chunk'] == '003.html'


def test_chunk_file_links_even_without_an_xml_id() -> None:
    doc = [{
        'xpath': '/*/div', 'element': 'div', 'behaviour': 'section',
        'model': 'tei-div1',
        'children': [_para('Anonymous prose that still deserves a link back.')],
    }]
    records = _build(doc, chunk_file='007.html')

    assert records[0]['metadata']['href'] == '007.html'


def test_same_path_in_two_chunks_gets_distinct_ids() -> None:
    """Chunks are transformed separately, so their internal paths repeat."""
    doc = [{
        'xpath': '/*/div', 'element': 'div', 'behaviour': 'section',
        'model': 'tei-div1',
        'children': [_para('Identical structure, different chunk entirely.')],
    }]
    first = _build(doc, chunk_file='001.html')
    second = _build(doc, chunk_file='002.html')

    assert first[0]['id'] != second[0]['id']


def test_xml_id_keeps_one_id_across_rechunking() -> None:
    """An anchored passage must not change identity when chunk layout shifts."""
    doc = [_section('stable', 'Heading', _para('Prose long enough to be kept here.'))]
    assert _build(doc, chunk_file='001.html')[0]['id'] == \
        _build(doc, chunk_file='009.html')[0]['id']


def test_page_metadata_is_the_same_on_later_chunks() -> None:
    """A fragment field is evaluated per page, not reconstructed from headings."""
    doc = [_section('s2', 'Chapter Two', _para('Prose long enough to be kept here.'))]
    records = _build(doc, page_metadata={'breadcrumb': 'The Whole Book > Chapter Two'})

    assert records[0]['metadata']['breadcrumb'] == 'The Whole Book > Chapter Two'


# ── unit boundaries ──────────────────────────────────────────────────────────

def test_a_titled_block_opens_a_unit() -> None:
    """ODDs differ on whether a chapter gets `section` or plain `block`.

    Keying only on the behaviour name collapsed a whole play into one unit.
    """
    inner = {
        'id': 'scene1', 'xpath': '/*/div/div', 'element': 'div',
        'behaviour': 'block', 'model': 'tei-div2',
        'children': [
            {'xpath': '/*/div/div/head', 'element': 'head', 'behaviour': 'heading',
             'model': 'tei-head1', 'children': ['Scene One']},
            _para('Prose belonging to the first scene of the act.'),
        ],
    }
    doc = [_section('act1', 'Act One', inner)]
    records = _build(doc)

    assert any(r['metadata'].get('heading') == 'Scene One' for r in records)
    assert all('breadcrumb' not in r['metadata'] for r in records)


def test_nested_boundaries_do_not_collide_on_one_id() -> None:
    """An enclosing unit must be emitted once, not once per nested boundary."""
    def scene(n: int) -> dict:
        return {
            'xpath': f'/*/div/div[{n}]', 'element': 'div', 'behaviour': 'block',
            'model': 'tei-div2',
            'children': [
                {'xpath': f'/*/div/div[{n}]/head', 'element': 'head',
                 'behaviour': 'heading', 'model': 'tei-head1',
                 'children': [f'Scene {n}']},
                _para(f'Prose belonging to scene number {n} of this act.'),
            ],
        }
    doc = [_section('act1', 'Act One', scene(1), scene(2), scene(3))]
    records = _build(doc)

    assert len(records) == len({r['id'] for r in records})


# ── templates ────────────────────────────────────────────────────────────────

def test_template_content_reaches_the_index() -> None:
    """``pb:template`` params arrive already processed.

    Dropping them loses everything a template-heavy ODD wraps — for DocBook
    that was the entire document body.
    """
    templated = {
        'xpath': '/*/div', 'element': 'section', 'behaviour': 'template',
        'model': 'tei-section1',
        'template': '<pb-observable data="[[root]]">[[content]]</pb-observable>',
        'children': [_para('Prose that the template wraps and must not lose.')],
    }
    doc = [_section('s1', 'Heading', templated)]
    records = _build(doc)

    assert 'template wraps and must not lose' in ' '.join(r['document'] for r in records)


# ── fields ───────────────────────────────────────────────────────────────────

def _note(text: str, xml_id: str | None = None, xpath: str = '/*/p/note') -> dict:
    record: dict = {
        'xpath': xpath,
        'element': 'note',
        'behaviour': 'note',
        'model': 'tei-note1',
        'children': [text],
    }
    if xml_id:
        record['id'] = xml_id
    return record


def _fields(*specs: FieldSpec, **tuning) -> IndexOptions:
    return IndexOptions(fields=specs, min_chars=1, **tuning)


def _para_with(*children, xpath: str = '/*/p') -> dict:
    return {
        'xpath': xpath, 'element': 'p', 'behaviour': 'paragraph', 'model': 'tei-p1',
        'children': list(children),
    }


def test_metadata_field_copies_values_onto_the_passage() -> None:
    """A facet: the name stays in the prose and is repeated as a list."""
    name = {
        'xpath': '/*/p/persName', 'element': 'persName', 'behaviour': 'inline',
        'model': 'tei-persName1', 'children': ['Aldo Manuzio'],
    }
    other = dict(name, xpath='/*/p/persName[2]', children=['Serafino'])
    doc = [_section('s1', 'A heading', _para_with('Printed by ', name, ' and ', other, '.'))]

    records = _build(doc, options=_fields(
        FieldSpec(name='persons', elements=frozenset({'persName'})),
    ))

    assert records[0]['metadata']['persons'] == ['Aldo Manuzio', 'Serafino']
    assert 'Aldo Manuzio' in records[0]['document']


def test_metadata_field_reports_each_value_once() -> None:
    name = {
        'xpath': '/*/p/persName', 'element': 'persName', 'behaviour': 'inline',
        'model': 'tei-persName1', 'children': ['Serafino'],
    }
    doc = [_section('s1', 'A heading', _para_with('A ', name, ' and again ', dict(name), '.'))]

    records = _build(doc, options=_fields(
        FieldSpec(name='persons', elements=frozenset({'persName'})),
    ))

    assert records[0]['metadata']['persons'] == ['Serafino']


def test_extracted_field_becomes_its_own_record() -> None:
    """``metadata=False``: a note is retrievable on its own, and tagged."""
    doc = [_section(
        's1', 'A heading',
        _para_with('Prose that carries a note', _note('The note text itself.'), '.'),
    )]

    records = _build(doc, options=_fields(
        FieldSpec(name='note', elements=frozenset({'note'}), metadata=False),
    ))

    passage, note = records
    assert note['metadata']['kind'] == 'note'
    assert note['document'] == 'The note text itself.'
    # Whether to embed notes is then a filter on `kind`, not a choice baked in.
    assert note['metadata']['parent'] == passage['id']
    # `inline` defaults off the flag, so the note leaves the passage it annotates.
    assert 'note text itself' not in passage['document']


def test_extracted_field_can_stay_in_its_passage_too() -> None:
    doc = [_section(
        's1', 'A heading',
        _para_with('Prose that carries a note', _note('The note text itself.'), '.'),
    )]

    records = _build(doc, options=_fields(
        FieldSpec(
            name='note', elements=frozenset({'note'}), metadata=False, inline=True,
        ),
    ))

    assert len(records) == 2
    assert 'note text itself' in records[0]['document']
    assert records[1]['metadata']['kind'] == 'note'


def test_extracted_field_keeps_its_own_id_and_xpath() -> None:
    doc = [_section(
        's1', 'A heading',
        _para_with('Prose. ', _note('A note with an id of its own.', xml_id='n1'), ''),
    )]

    records = _build(doc, options=_fields(
        FieldSpec(name='note', behaviours=frozenset({'note'}), metadata=False),
    ))
    note = records[-1]

    assert note['id'] == 'doc#n1'
    assert note['metadata']['xml_id'] == 'n1'
    assert note['metadata']['xpath'] == '/*/p/note'


def test_fields_select_by_behaviour_element_or_model() -> None:
    """All three handles a JSON record carries pick the same note."""
    doc = [_section('s1', 'A heading', _para_with('Prose. ', _note('Note text.')))]

    for spec in (
        FieldSpec(name='n', behaviours=frozenset({'note'}), metadata=False),
        FieldSpec(name='n', elements=frozenset({'note'}), metadata=False),
        FieldSpec(name='n', models=frozenset({'tei-note1'}), metadata=False),
    ):
        records = _build(doc, options=_fields(spec))
        assert [r['metadata'].get('kind') for r in records] == [None, 'n']


def test_suppressed_content_never_reaches_a_field() -> None:
    """What the ODD dropped stays dropped, facet or not."""
    hidden = dict(_note('Apparatus the reader never sees.'), suppressed=True)
    doc = [_section('s1', 'A heading', _para_with('Prose. ', hidden))]

    records = _build(doc, options=_fields(
        FieldSpec(name='note', elements=frozenset({'note'}), metadata=False),
    ))

    assert len(records) == 1
    assert 'Apparatus' not in records[0]['document']


def test_field_specs_default_inline_to_the_metadata_flag() -> None:
    assert FieldSpec(name='persons', metadata=True).keeps_text_inline
    assert not FieldSpec(name='note', metadata=False).keeps_text_inline
    assert FieldSpec(name='note', metadata=False, inline=True).keeps_text_inline


def test_fragment_plain_text_joins_list_items() -> None:
    html = (
        '<nav aria-label="breadcrumb"><ul>'
        '<li>Guide</li><li><a href="001.html">Install</a></li>'
        '<li>Using pip</li></ul></nav>'
    )
    assert _fragment_plain_text(html) == 'Guide > Install > Using pip'


def test_fragment_plain_text_collapses_non_list_markup() -> None:
    assert _fragment_plain_text('<span>  A   letter </span>') == 'A letter'
    assert _fragment_plain_text('already plain') == 'already plain'

# ── config ───────────────────────────────────────────────────────────────────

def _config(tmp_path: Path, body: str):
    from opm.config import load_project_config

    path = tmp_path / 'opm.toml'
    path.write_text(body, encoding='utf-8')
    return load_project_config(path)


def test_index_fields_are_read_from_the_config(tmp_path: Path) -> None:
    cfg = _config(tmp_path, """
[[index.fields]]
name = "note"
elements = ["note"]
metadata = false

[[index.fields]]
name = "persons"
elements = "persName"
""")

    note, persons = cfg.index_fields
    assert note.elements == frozenset({'note'})
    assert not note.metadata
    assert not note.keeps_text_inline
    # A single string is accepted where a list would do.
    assert persons.elements == frozenset({'persName'})
    assert persons.metadata


def test_a_field_must_select_something(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='selects nothing'):
        _config(tmp_path, '[[index.fields]]\nname = "note"\n')


def test_a_fragment_field_is_read_from_the_config(tmp_path: Path) -> None:
    cfg = _config(tmp_path, """
[chunking]
selector = "opm.navigation.dbk_section_chunks"

[[chunking.fragments]]
name = "breadcrumbs"
scope = "per-chunk"
xpath = "."
parameters = { mode = "breadcrumb" }

[[index.fields]]
name = "breadcrumb"
fragment = "breadcrumbs"
""")

    spec, = cfg.index_fields
    assert spec.name == 'breadcrumb'
    assert spec.fragment == 'breadcrumbs'
    assert spec.metadata
    assert not spec.behaviours
    assert not spec.elements
    assert not spec.models


def test_a_fragment_field_cannot_mix_selectors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='cannot mix'):
        _config(tmp_path, """
[[index.fields]]
name = "breadcrumb"
fragment = "breadcrumbs"
elements = ["title"]
""")


def test_a_fragment_field_must_name_an_existing_fragment(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='no such entry'):
        _config(tmp_path, """
[chunking]
selector = "opm.navigation.dbk_section_chunks"

[[index.fields]]
name = "breadcrumb"
fragment = "breadcrumbs"
""")


def test_a_fragment_field_cannot_be_a_child_record(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='metadata cannot be false'):
        _config(tmp_path, """
[[chunking.fragments]]
name = "breadcrumbs"
xpath = "."

[[index.fields]]
name = "breadcrumb"
fragment = "breadcrumbs"
metadata = false
""")


def test_a_field_must_be_named(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='missing "name"'):
        _config(tmp_path, '[[index.fields]]\nelements = ["note"]\n')


def test_index_units_are_read_from_the_config(tmp_path: Path) -> None:
    cfg = _config(tmp_path, """
[[index.units]]
name = "heading"
behaviours = ["heading"]
emit = false

[[index.units]]
name = "paragraph"
behaviours = "paragraph"
min_chars = 1
""")

    heading, paragraph = cfg.index_units
    assert heading.behaviours == frozenset({'heading'})
    assert not heading.emit
    assert heading.min_chars is None
    assert paragraph.behaviours == frozenset({'paragraph'})
    assert paragraph.emit
    assert paragraph.min_chars == 1


def test_a_unit_must_select_something(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='selects nothing'):
        _config(tmp_path, '[[index.units]]\nname = "paragraph"\n')


def test_a_unit_must_be_named(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='missing "name"'):
        _config(tmp_path, '[[index.units]]\nbehaviours = ["paragraph"]\n')

# ── CLI ──────────────────────────────────────────────────────────────────────

def _tiny_corpus(tmp_path: Path, monkeypatch) -> Path:
    """A project with an ODD and one document filed in a subdirectory."""
    odd = tmp_path / 'tiny.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        '<schemaSpec ident="tiny" ns="">'
        '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
        '<elementSpec ident="div"><model behaviour="section"/></elementSpec>'
        '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>'
        '</schemaSpec></body></text></TEI>',
        encoding='utf-8',
    )
    nested = tmp_path / 'data' / 'article'
    nested.mkdir(parents=True)
    (nested / 'one.xml').write_text(
        '<doc><div><p>Indexable prose, filed a directory deeper.</p></div></doc>',
        encoding='utf-8',
    )
    cache = tmp_path / 'cache'
    # platformdirs on macOS ignores XDG_CACHE_HOME; redirect the dir instead.
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')
    monkeypatch.setattr('opm.resources.user_opm_cache_dir', lambda: cache)
    monkeypatch.chdir(tmp_path)
    return odd


def test_cli_defaults_to_the_data_directory_and_recurses(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """``opm index`` with no path indexes ./data, subdirectories included."""
    from opm.cli import main

    odd = _tiny_corpus(tmp_path, monkeypatch)

    assert main(['index', '-d', str(odd)]) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records
    assert records[0]['metadata']['source'] == str(Path('data') / 'article' / 'one.xml')
    assert 'filed a directory deeper' in records[0]['document']


def test_cli_reports_a_missing_corpus(tmp_path: Path, monkeypatch, capsys) -> None:
    from opm.cli import main

    monkeypatch.chdir(tmp_path)

    assert main(['index']) == 1
    assert 'input XML file or directory is required' in capsys.readouterr().err
