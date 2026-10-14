# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the ``note`` behaviour of the HTML and Markdown output functions.

A critical edition carries two note series at once: a text-critical apparatus
labelled from TEI ``@n`` and a commentary numbered by the running counter.
These cover how the two are kept apart, and what happens to a stand-off note
whose lookup finds nothing.
"""

from __future__ import annotations

from lxml import etree

from opm.runtime.context import RenderContext
from opm.runtime.html_output_functions import HtmlOutputFunctions
from opm.runtime.markdown_output_functions import MarkdownOutputFunctions
from opm.runtime.output_functions import XML_ID
from opm.runtime.pm_runtime import apply_children

TEI_NS = 'http://www.tei-c.org/ns/1.0'


def _config(pmf) -> RenderContext:
    return RenderContext(
        pmf=pmf,
        apply_children=apply_children,
        apply=lambda _c, nodes: list(nodes) if isinstance(nodes, list) else [nodes],
    )


def _note(label: str | None = None, **attrs) -> etree._Element:
    node = etree.Element(f'{{{TEI_NS}}}note', attrs)
    if label is not None:
        node.set('n', label)
    node.text = 'Body'
    return node


def test_note_records_what_an_ordering_hook_needs() -> None:
    """The collected footnote carries the label, number, anchor and source node."""
    pmf = HtmlOutputFunctions()
    config = _config(pmf)
    node = _note('a', type='textcritical')

    config.pmf.note(config, node, ['tei-note'], node, place='foot', label=node.get('n'))

    footnote = config.state.footnotes[0]
    assert footnote.label == 'a'
    assert footnote.marker == 'a'
    assert footnote.place == 'foot'
    assert footnote.anchor.startswith('fn_')
    # The source element, so a hook can branch on anything the ODD did not pass.
    assert footnote.node.get('type') == 'textcritical'
    assert footnote.body.get('class') == 'footnote'


def test_note_marks_a_labelled_note_with_data_n() -> None:
    """CSS can tell the apparatus from the commentary without parsing the marker."""
    pmf = HtmlOutputFunctions()
    config = _config(pmf)

    labelled = _note('a')
    ref = pmf.note(config, labelled, ['tei-note'], labelled, label=labelled.get('n'))[0]
    numbered = _note()
    plain = pmf.note(config, numbered, ['tei-note'], numbered, label=None)[0]

    assert ref.get('data-n') == 'a'
    assert config.state.footnotes[0].body.get('data-n') == 'a'
    assert plain.get('data-n') is None
    assert config.state.footnotes[1].body.get('data-n') is None


def test_the_two_note_series_number_independently() -> None:
    """A note with its own ``@n`` does not consume a value from the counter.

    Otherwise both series share one sequence and the commentary skips every
    number the apparatus took — 1, 3, 4, 7, … instead of 1, 2, 3, 4.
    """
    pmf = HtmlOutputFunctions()
    config = _config(pmf)

    markers = []
    for label in ['a', None, 'b', None, None]:
        node = _note(label)
        pmf.note(config, node, ['tei-note'], node, label=node.get('n'))
        markers.append(config.state.footnotes[-1].marker)

    assert markers == ['a', '1', 'b', '2', '3']


def test_note_label_from_an_empty_xpath_result_is_no_label() -> None:
    """An ODD param that selected nothing is an empty sequence, not ``None``."""
    pmf = HtmlOutputFunctions()
    config = _config(pmf)
    node = _note()

    pmf.note(config, node, ['tei-note'], node, place=[], label=[])

    footnote = config.state.footnotes[0]
    assert footnote.label is None
    assert footnote.place is None
    # Not the literal string '[]', which is what str() of the empty result gives.
    assert footnote.marker == '1'


def test_unresolved_standoff_note_emits_nothing() -> None:
    """A stand-off lookup that finds nothing is not a footnote.

    ``teipublisher.odd`` renders ``<anchor type="note"/>`` as a note whose
    content and label are looked up in a ``listAnnotation``. An edition that
    keeps its notes inline has no such section, so both params come back empty
    — there is no note to emit, and an empty numbered entry would be wrong.
    """
    pmf = HtmlOutputFunctions()
    config = _config(pmf)
    anchor = etree.Element(f'{{{TEI_NS}}}anchor', {'type': 'note'})

    assert pmf.note(config, anchor, ['tei-anchor'], [], place=[], label=[]) == []
    assert config.state.footnotes == []
    assert config.state.note_counter == 0, 'no number was consumed either'


def _lemma_range_doc(label: str = 'b') -> tuple[etree._Element, etree._Element]:
    """Build ``<anchor type="note"/>…<note target="…">`` and return both ends."""
    tei = f'{{{TEI_NS}}}'
    root = etree.Element(f'{tei}p')
    anchor = etree.SubElement(root, f'{tei}anchor', {'type': 'note'})
    anchor.set(XML_ID, 'fn-b')
    anchor.tail = 'lemma text'
    note = etree.SubElement(root, f'{tei}note', {
        'n': label,
        'target': 'fn-b',
        'type': 'textcritical',
    })
    note.set(XML_ID, 'nb')
    note.text = 'Apparatus'
    return anchor, note


def test_lemma_range_start_emits_opening_marker() -> None:
    """``place="start"`` writes ``a-`` and links to the end note's footnote."""
    pmf = HtmlOutputFunctions()
    config = _config(pmf)
    anchor, _note = _lemma_range_doc('b')

    result = pmf.note(config, anchor, ['tei-anchor'], [], place='start', label='b')

    assert len(result) == 1
    span = result[0]
    assert span.get('data-range') == 'start'
    assert span.find('a').text == 'b-'
    assert span.find('a').get('href') == '#fn_nb'
    assert config.state.footnotes == []


def test_lemma_range_end_uses_paired_markers() -> None:
    """A note with ``@target`` on an anchor shows ``-a`` in text and ``a-a`` below."""
    pmf = HtmlOutputFunctions()
    config = _config(pmf)
    _anchor, note = _lemma_range_doc('b')

    ref = pmf.note(config, note, ['tei-note'], note, label=note.get('n'))[0]

    assert ref.find('a').text == '-b'
    assert ref.get('data-range') == 'end'
    footnote = config.state.footnotes[0]
    assert footnote.label == 'b'
    assert footnote.marker == 'b'
    assert footnote.body.find('dt').text == 'b-b'


def test_markdown_note_records_the_label_for_a_hook() -> None:
    """Markdown shows no marker of its own, but a hook still sorts on the label."""
    pmf = MarkdownOutputFunctions()
    config = _config(pmf)
    node = _note('a')

    assert pmf.note(config, node, [], node, label=node.get('n')) == ['[^1]']

    footnote = config.state.footnotes[0]
    assert footnote.label == 'a'
    assert footnote.body.strip() == '[^1]: Body'
    assert footnote.number == 0, 'a labelled note draws no running number'


def test_markdown_unresolved_standoff_note_emits_nothing() -> None:
    pmf = MarkdownOutputFunctions()
    config = _config(pmf)
    anchor = etree.Element(f'{{{TEI_NS}}}anchor', {'type': 'note'})

    assert pmf.note(config, anchor, [], [], place=[], label=[]) == []
    assert config.state.footnotes == []


def test_unresolved_standoff_note_consumes_no_id() -> None:
    """A suppressed note leaves the synthetic-id counter alone as well."""
    pmf = HtmlOutputFunctions()
    config = _config(pmf)
    anchor = etree.Element(f'{{{TEI_NS}}}anchor', {'type': 'note'})

    pmf.note(config, anchor, ['tei-anchor'], [], place=[], label=[])
    assert config.state.id_counter == 0

    # The next real note still gets fn_1, not fn_2.
    node = _note()
    ref = pmf.note(config, node, ['tei-note'], node, label=None)[0]
    assert ref.find('a').get('href') == '#fn_1'
