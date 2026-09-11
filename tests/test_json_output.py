"""Tests for the ``json`` output mode — the processing model's decisions as data."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from lxml import etree

from opm.resources import packaged_odd
from opm.runtime.json_output_functions import JsonOutputFunctions
from opm.runtime.context import RenderContext
from opm.runtime.pm_runtime import apply, apply_children

ROOT = Path(__file__).resolve().parents[1]
ODD = packaged_odd('teipublisher')
DEMO_TEI_TEST_XML = ROOT / 'examples' / 'tei-test.xml'
TEI = 'http://www.tei-c.org/ns/1.0'


def _config(**extra) -> RenderContext:
    return RenderContext(**{'dispatch': lambda cfg, node, params: [], **extra})


def _el(tag: str, text: str | None = None, **attrs) -> etree._Element:
    el = etree.Element(f'{{{TEI}}}{tag}')
    if text:
        el.text = text
    for k, v in attrs.items():
        el.set(k, v)
    # getpath() needs a tree; a bare element has none.
    etree.ElementTree(el)
    return el


def _walk(record):
    if isinstance(record, dict):
        yield record
        for child in record.get('children', []):
            yield from _walk(child)


# ── unit: record construction ────────────────────────────────────────────────

def test_block_produces_a_record() -> None:
    pmf = JsonOutputFunctions()
    node = _el('div', 'hello')
    result = pmf.block(_config(), node, ['tei-div', 'tei-div3', None], node)

    assert len(result) == 1
    rec = result[0]
    assert rec['behaviour'] == 'block'
    assert rec['element'] == 'div'
    assert rec['model'] == 'tei-div3'
    assert rec['children'] == ['hello']


def test_inline_produces_its_own_record() -> None:
    """Inline behaviours must not fold silently into the parent.

    A wrong inline model is the commonest ODD bug; folding its text into the
    enclosing block would leave no trace of which model actually won.
    """
    pmf = JsonOutputFunctions()
    node = _el('hi', 'emphasised')
    result = pmf.inline(_config(), node, ['tei-hi', 'tei-hi7', 'italic'], node)

    assert len(result) == 1
    assert result[0]['behaviour'] == 'inline'
    assert result[0]['model'] == 'tei-hi7'
    assert result[0]['children'] == ['emphasised']


def test_prose_is_stored_on_exactly_one_record() -> None:
    """A container must not repeat its children's prose.

    Text lives in ``children`` as ordered runs, so each passage appears once,
    on the record that produced it. Storing a rolled-up copy on every ancestor
    would mean an embedding store held the same sentences at three
    granularities — and for mixed content the roll-up is a gapped string that
    reads as corrupt.
    """
    parent = _el('div')
    first = etree.SubElement(parent, f'{{{TEI}}}p')
    first.text = 'First paragraph.'
    second = etree.SubElement(parent, f'{{{TEI}}}p')
    second.text = 'Second paragraph.'
    etree.ElementTree(parent)

    pmf = JsonOutputFunctions()
    config = _config()
    config.dispatch = lambda cfg, node, params: pmf.paragraph(
        cfg, node, ['tei-p', 'tei-p1', None], node,
    )
    result = pmf.section(config, parent, ['tei-div', 'tei-div1', None], parent)

    rec = result[0]
    assert [c['children'] for c in rec['children']] == [
        ['First paragraph.'], ['Second paragraph.'],
    ]
    # The container itself stores no copy of that prose.
    assert 'text' not in rec


def test_omit_records_suppression_instead_of_vanishing() -> None:
    """``omit`` must leave a trace.

    Returning ``[]`` makes "the ODD dropped this" and "it was never in the
    source" indistinguishable — the commonest ODD debugging question.
    """
    pmf = JsonOutputFunctions()
    node = _el('del', 'struck out')
    result = pmf.omit(_config(), node, ['tei-del', 'tei-del2', None], node)

    assert len(result) == 1
    assert result[0]['suppressed'] is True
    assert result[0]['behaviour'] == 'omit'
    assert result[0]['element'] == 'del'
    assert 'children' not in result[0]


def test_heading_carries_level_and_link_carries_uri() -> None:
    pmf = JsonOutputFunctions()
    head = _el('head', 'A title')
    heading = pmf.heading(_config(), head, ['tei-head', 'tei-head1', None], head, 2)
    assert heading[0]['level'] == 2
    assert heading[0]['children'] == ['A title']

    ref = _el('ref', 'see here', target='#target')
    link = pmf.link(
        _config(), ref, ['tei-ref', 'tei-ref1', None], ref, '#target', None, None,
    )
    assert link[0]['uri'] == '#target'


def test_mixed_content_keeps_source_order() -> None:
    para = _el('p')
    para.text = 'before '
    hi = etree.SubElement(para, f'{{{TEI}}}hi')
    hi.text = 'middle'
    hi.tail = ' after'
    etree.ElementTree(para)

    pmf = JsonOutputFunctions()
    config = _config()
    config.dispatch = lambda cfg, node, params: pmf.inline(
        cfg, node, ['tei-hi', 'tei-hi1', None], node,
    )
    rec = pmf.paragraph(config, para, ['tei-p', 'tei-p1', None], para)[0]

    kinds = [
        c['behaviour'] if isinstance(c, dict) else c for c in rec['children']
    ]
    assert kinds == ['before ', 'inline', ' after']
    # The link's own words stay on the link's record. A rolled-up parent string
    # would read 'before  after' — a sentence with a hole where the inline was.
    assert 'text' not in rec


def test_prune_drops_emptied_runs_but_keeps_a_word_separator() -> None:
    """Normalisation empties pretty-print padding; a lone space is real.

    Dropping ``' '`` too would run ``</hi> <hi>`` together into one word.
    """
    from opm.runtime.json_output_functions import _prune

    assert _prune(['a', '', ' ', 'b']) == ['a', ' ', 'b']


# ── runtime: records survive the tree walk ───────────────────────────────────

def test_dict_records_survive_append_to() -> None:
    """``append_to`` handles only str/Element by default and drops dicts silently."""
    from opm.runtime.pm_runtime import append_to

    buf: list = []
    append_to(buf, {'behaviour': 'block'})
    assert buf == [{'behaviour': 'block'}]


# ── end to end ───────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def json_module(tmp_path_factory):
    from opm.odd_compiler import compile_odd

    path = tmp_path_factory.mktemp('json') / 'teipublisher_json.py'
    path.write_text(compile_odd(str(ODD), output_mode='json'), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('teipublisher_json_fixture', str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def demo_output(json_module):
    root = etree.parse(str(DEMO_TEI_TEST_XML)).getroot()
    return json.loads(json_module.transform(root)[0])


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_output_is_parseable_json_with_a_models_table(demo_output) -> None:
    assert demo_output['document']
    assert demo_output['models']


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_web_output_models_participate_under_json(demo_output) -> None:
    """The ``json`` alias pulls in ``@output="web"`` models; without it dispatch is empty."""
    records = [r for root in demo_output['document'] for r in _walk(root)]
    assert any(r['behaviour'] == 'paragraph' for r in records)
    assert any(r['behaviour'] == 'section' for r in records)


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_records_nest_at_least_three_deep(demo_output) -> None:
    def depth(record) -> int:
        kids = [c for c in record.get('children', []) if isinstance(c, dict)]
        return 1 + max((depth(c) for c in kids), default=0)

    assert max(depth(r) for r in demo_output['document']) >= 3


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_model_keys_resolve_against_the_models_table(demo_output) -> None:
    records = [r for root in demo_output['document'] for r in _walk(root)]
    used = {r['model'] for r in records if r['model']}
    assert used
    assert used <= set(demo_output['models'])


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_unmatched_elements_are_visible(demo_output) -> None:
    """Elements with no model reach ``pmf.unmatched`` rather than disappearing."""
    records = [r for root in demo_output['document'] for r in _walk(root)]
    unmatched = [r for r in records if r['behaviour'] is None]
    assert unmatched
    assert all(r['model'] is None for r in unmatched)
    # They still recurse: at least one carries content below it.
    assert any(r.get('children') for r in unmatched)


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_suppressed_content_is_recorded_not_dropped(demo_output) -> None:
    records = [r for root in demo_output['document'] for r in _walk(root)]
    suppressed = [r for r in records if r.get('suppressed')]
    assert suppressed
    # teiHeader is bound to the `metadata` behaviour in teipublisher.odd.
    assert any(r['element'] == 'teiHeader' for r in suppressed)


def test_other_output_modes_keep_their_inline_dispatch_fallthrough() -> None:
    """The ``case _:`` change must be json-only; every other mode is untouched."""
    from opm.odd_compiler.codegen.python_generator import PythonGenerator
    from opm.odd_compiler.parse_odd import load_odd

    parsed = load_odd(str(ODD))
    generator = PythonGenerator()
    for mode in ('web', 'markdown', 'print', 'epub', 'typst'):
        src = generator.generate_module(parsed, 'm', output_mode=mode)
        assert 'pmf.unmatched' not in src, mode
        assert 'ODD_MODELS' not in src, mode

    src = generator.generate_module(parsed, 'm', output_mode='json')
    assert 'return pmf.unmatched(config, node)' in src
    assert 'ODD_MODELS = {' in src


# ── output channels ──────────────────────────────────────────────────────────

def test_json_channel_aliases_cover_every_render_mode() -> None:
    from opm.odd_compiler.codegen import (
        OUTPUT_MODE_ALIASES,
        RENDER_MODES,
        is_json_mode,
        json_channel,
    )

    for mode in RENDER_MODES:
        accepted = OUTPUT_MODE_ALIASES[f'json-{mode}']
        assert accepted[0] == 'json'
        assert mode in accepted
        assert is_json_mode(f'json-{mode}')
        assert json_channel(f'json-{mode}') == mode

    # print and epub carry their own web fallback into the JSON view.
    assert OUTPUT_MODE_ALIASES['json-print'] == ('json', 'print', 'web')
    assert OUTPUT_MODE_ALIASES['json-epub'] == ('json', 'epub', 'web')
    # typst and markdown do not fall back to web, so neither do their JSON modes.
    assert OUTPUT_MODE_ALIASES['json-typst'] == ('json', 'typst')
    assert not is_json_mode('typst')
    assert json_channel('json') == 'web'


def test_channel_selects_that_channels_models() -> None:
    """``-t json`` alone shows the reading view; a typst ODD needs its own channel."""
    from opm.odd_compiler.codegen.python_generator import PythonGenerator
    from opm.odd_compiler.parse_odd import load_odd

    parsed = load_odd(str(ODD))
    generator = PythonGenerator()

    def tagged(mode: str) -> set[str]:
        src = generator.generate_module(parsed, 'm', output_mode=mode)
        namespace: dict = {}
        start = src.index('ODD_MODELS = {')
        exec(src[start:src.index('\n\n', start)], namespace)  # noqa: S102
        return {
            key for key, entry in namespace['ODD_MODELS'].items()
            if entry.get('output') == 'typst'
        }

    assert not tagged('json')
    assert tagged('json-typst')


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_typst_channel_records_a_different_decision(json_module) -> None:
    """teiHeader is `metadata` for web but `pass_through` for typst.

    The web view therefore stops at the header while the typst view descends
    into it — the kind of channel-specific behaviour `-t json` alone hides.
    """
    from opm.odd_compiler import compile_odd

    namespace: dict = {}
    exec(compile_odd(str(ODD), output_mode='json-typst'), namespace)  # noqa: S102

    root = etree.parse(str(DEMO_TEI_TEST_XML)).getroot()
    typst = json.loads(namespace['transform'](root)[0])
    web = json.loads(json_module.transform(root)[0])

    def find(payload, element):
        for root_record in payload['document']:
            for record in _walk(root_record):
                if record['element'] == element:
                    return record
        return None

    assert find(web, 'teiHeader')['behaviour'] == 'metadata'
    assert find(web, 'teiHeader').get('suppressed') is True
    assert find(typst, 'teiHeader')['behaviour'] == 'pass_through'
    # Descending into the header reaches elements the web view never records.
    assert find(web, 'author') is None
    assert find(typst, 'author') is not None


# ── behaviour + pb:template ──────────────────────────────────────────────────

def test_template_combo_records_carry_their_model() -> None:
    """A model with both ``@behaviour`` and ``pb:template`` emits two records.

    That is faithful — the runtime really calls ``pmf.template`` and passes its
    result as the behaviour's content — but both come from one model, so both
    must name it. The combo helper used to be handed an empty class list, which
    left the inner record with ``model: null`` and no way back to the ODD.
    """
    from opm.odd_compiler.codegen.python_generator import PythonGenerator
    from opm.odd_compiler.parse_odd import load_odd

    src = PythonGenerator().generate_module(
        load_odd(str(ODD)), 'm', output_mode='json',
    )
    combo_helpers = [
        line for line in src.splitlines()
        if line.startswith('def _odd_template_')
    ]
    assert combo_helpers
    # Every helper takes `r`; _classes_expr references it, so a helper without
    # it raises NameError the moment its model matches.
    assert all(line.rstrip().endswith('r):') for line in combo_helpers), combo_helpers
    assert 'pmf.template(\n        config,\n        node,\n        [],' not in src


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_template_record_shares_the_model_of_its_behaviour(demo_output) -> None:
    records = [r for root in demo_output['document'] for r in _walk(root)]
    templates = [r for r in records if r['behaviour'] == 'template']

    assert templates
    assert all(r['model'] for r in templates), 'template records lost their model'
    assert all(r['model'] in demo_output['models'] for r in templates)

    # The pair sits at one xpath: the behaviour wraps the template's output.
    for outer in records:
        inner = [
            c for c in outer.get('children', [])
            if isinstance(c, dict)
            and c['behaviour'] == 'template'
            and c['xpath'] == outer['xpath']
        ]
        for record in inner:
            assert record['model'] == outer['model']


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_records_carry_no_rolled_up_text_field(demo_output) -> None:
    """Text lives in ``children`` and nowhere else.

    A rolled-up ``text`` was 100% redundant with the string members of
    ``children``, and for mixed content it produced a sentence with a hole
    where the inline element had been:

        "Numerous projects realized with  prove that it is:"
    """
    records = [r for root in demo_output['document'] for r in _walk(root)]
    assert records
    assert not [r for r in records if 'text' in r]


# ── the models table ─────────────────────────────────────────────────────────

def test_models_table_holds_what_records_cannot() -> None:
    """`predicate`, `desc` and `output` appear nowhere in the record tree.

    A record names the model that won but not what that model *was*, which is
    the question being asked when a transform surprises you.
    """
    from opm.runtime.json_output_functions import _relevant_models

    models = {
        'tei-hi1': {
            'element': 'hi', 'behaviour': 'inline',
            'predicate': "@rend='italic'", 'desc': 'Italic display',
        },
        'tei-hi2': {'element': 'hi', 'behaviour': 'omit'},
        'tei-castList1': {'element': 'castList', 'behaviour': 'block'},
    }
    root = etree.fromstring(
        f'<TEI xmlns="{TEI}"><text><hi>x</hi></text></TEI>'.encode(),
    )
    pruned = _relevant_models(models, root)

    # Both `hi` models stay: the one that lost is what answers "why not mine?".
    assert set(pruned) == {'tei-hi1', 'tei-hi2'}
    assert pruned['tei-hi1']['predicate'] == "@rend='italic'"
    # castList is not in this document, so its models can explain nothing here.
    assert 'tei-castList1' not in pruned


def test_relevant_models_degrades_without_a_root() -> None:
    from opm.runtime.json_output_functions import _relevant_models

    models = {'tei-hi1': {'element': 'hi', 'behaviour': 'inline'}}
    assert _relevant_models(models, None) == models
    assert _relevant_models(None, None) == {}


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_models_table_is_pruned_but_still_covers_every_record(demo_output) -> None:
    records = [r for root in demo_output['document'] for r in _walk(root)]
    fired = {r['model'] for r in records if r['model']}
    table = demo_output['models']

    assert fired <= set(table)
    # Pruned: the packaged ODD declares far more models than this document uses.
    assert len(table) < 239
    # Models that lost are kept — that is the table's whole point.
    assert len(table) > len(fired)


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_models_table_keeps_suppressed_subtrees(demo_output) -> None:
    """teiHeader is omitted for web, so nothing inside it produces a record.

    Pruning against the emitted records rather than the source would drop the
    models you need exactly when you ask why nothing came out.
    """
    elements = {entry['element'] for entry in demo_output['models'].values()}
    assert 'titleStmt' in elements or 'title' in elements


# ── xpath ────────────────────────────────────────────────────────────────────

def _paths_round_trip(root) -> list[str]:
    """Return paths that fail to select exactly the element they came from."""
    from opm.runtime.json_output_functions import _element_path
    from opm.transform import xpath_select

    broken = []
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        path = _element_path(element)
        got = xpath_select(root, path)
        if not (isinstance(got, list) and len(got) == 1 and got[0] is element):
            broken.append(path)
    return broken


def test_xpath_uses_element_names_not_wildcards() -> None:
    """``getpath()`` cannot name elements in an unprefixed default namespace.

    It emits ``/*/*[2]/*[4]`` — correct but unreadable, and no use for finding
    the element in an editor.
    """
    from opm.runtime.json_output_functions import _element_path

    root = etree.fromstring(
        f'<TEI xmlns="{TEI}"><text><body><p>a</p><p>b</p></body></text></TEI>'.encode(),
    )
    second = root.findall(f'.//{{{TEI}}}p')[1]

    assert root.getroottree().getpath(second) == '/*/*/*/*[2]'
    assert _element_path(second) == '/TEI/text[1]/body[1]/p[2]'


def test_element_paths_select_the_element_they_came_from() -> None:
    """A readable path that resolves to the wrong node is worse than a wildcard."""
    root = etree.fromstring(
        f'''<TEI xmlns="{TEI}"><text><body>
             <div><head>One</head><p>a</p><p>b</p></div>
             <div><head>Two</head><p>c</p></div>
           </body></text></TEI>'''.encode(),
    )
    assert _paths_round_trip(root) == []


def test_foreign_namespaces_keep_positional_steps() -> None:
    """An unprefixed step cannot match an element outside the default namespace."""
    from opm.runtime.json_output_functions import _element_path

    root = etree.fromstring(
        f'''<TEI xmlns="{TEI}"><text><body><formula>
             <math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>
           </formula></body></text></TEI>'''.encode(),
    )
    mi = root.iter('{http://www.w3.org/1998/Math/MathML}mi').__next__()

    assert _element_path(mi) == '/TEI/text[1]/body[1]/formula[1]/*[1]/*[1]'
    assert _paths_round_trip(root) == []


def test_element_path_survives_a_document_with_no_namespace() -> None:
    root = etree.fromstring(b'<article><body><p>a</p><p>b</p></body></article>')

    from opm.runtime.json_output_functions import _element_path
    assert _element_path(root.findall('.//p')[1]) == '/article/body[1]/p[2]'
    assert _paths_round_trip(root) == []


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_demo_record_paths_are_named_and_resolvable(demo_output) -> None:
    records = [r for root in demo_output['document'] for r in _walk(root)]
    paths = [r['xpath'] for r in records if r['xpath']]

    assert paths
    assert not [p for p in paths if p.startswith('/*')], 'wildcard root path'
    root = etree.parse(str(DEMO_TEI_TEST_XML)).getroot()
    assert _paths_round_trip(root) == []


def test_models_table_marks_inherited_models(tmp_path) -> None:
    """``source`` says the model came from an extended ODD, not this one.

    An author reading the table needs to know whether editing the local ODD can
    change a decision at all — a model inherited from ``teipublisher.odd`` has
    to be overridden there or redeclared here.
    """
    from opm.odd_compiler.codegen.python_generator import PythonGenerator
    from opm.odd_compiler.parse_odd import load_odd

    odd = tmp_path / 'child.odd'
    odd.write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        '<schemaSpec ident="child" start="TEI" source="teipublisher.odd">'
        '<elementSpec ident="hi" mode="change">'
        '<model behaviour="inline"><desc>local override</desc></model>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )

    src = PythonGenerator().generate_module(load_odd(str(odd)), 'm', output_mode='json')
    namespace: dict = {}
    start = src.index('ODD_MODELS = {')
    exec(src[start:src.index('\n\n', start)], namespace)  # noqa: S102
    models = namespace['ODD_MODELS']

    # `hi` is redeclared locally, so it is the local ODD's to change.
    hi = {key: entry for key, entry in models.items() if entry['element'] == 'hi'}
    assert hi
    assert all('source' not in entry for entry in hi.values())

    # Everything else comes in from the ODD being extended.
    inherited = {entry.get('source') for entry in models.values() if entry['element'] != 'hi'}
    assert inherited == {'teipublisher.odd'}
