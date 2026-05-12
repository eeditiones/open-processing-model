"""Integration test: compile ``odd/teipublisher.odd`` and transform demo XML."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
ODD = ROOT / 'odd' / 'teipublisher.odd'
DEMO_TEI_TEST_XML = ROOT / 'demo' / 'tei-test.xml'


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(),
    reason='Fixture demo/tei-test.xml not found',
)
def test_teipublisher_odd_teitest_xml_choice_abbr_expan_alternate_html(tmp_path: Path) -> None:
    """Compile ``odd/teipublisher.odd``, transform ``demo/tei-test.xml``, check ``choice``/``alternate`` HTML.

    Catches regressions where XPath results stayed as elementpath wrappers so ``apply_children``
    skipped content (empty ``alternate`` containers).
    """
    from teipublisher.odd_compiler import compile_odd
    from teipublisher.runtime.pm_runtime import serialize

    path = tmp_path / 'teipublisher_web.py'
    path.write_text(compile_odd(str(ODD)), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('teipublisher_web_fixture', str(path))
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    root = etree.parse(str(DEMO_TEI_TEST_XML)).getroot()
    html = serialize(m.transform(root))

    # <choice><abbr>XML</abbr><expan>Extensible Markup Language</expan></choice> in Trump’s speech.
    # ODD: default=expan[1], alternate=abbr[1] (see ``elementSpec ident="choice"`` in teipublisher.odd).
    compact = re.sub(r'\s+', ' ', html)
    assert re.search(
        r'<span class="tei-choice tei-choice2 alternate">'
        r'<span>Extensible Markup Language</span>'
        r'<span class="altcontent">XML</span></span>',
        compact,
    ), 'expected expan in the first container and abbr in .altcontent'


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(),
    reason='Fixture demo/tei-test.xml not found',
)
def test_teipublisher_odd_teitest_xml_register_mode_people_list_names(tmp_path: Path) -> None:
    """``mode=register`` list items must show a name when ``persName`` has no @type (see teiHeader listPerson)."""
    from teipublisher.odd_compiler import compile_odd
    from teipublisher.runtime.pm_runtime import serialize

    path = tmp_path / 'teipublisher_web.py'
    path.write_text(compile_odd(str(ODD)), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('teipublisher_web_register', str(path))
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    root = etree.parse(str(DEMO_TEI_TEST_XML)).getroot()
    html = serialize(m.transform(root, {'mode': 'register'}))
    compact = re.sub(r'\s+', ' ', html)
    assert '<h3>People</h3>' in compact
    assert 'Donald' in compact and 'Vladimir' in compact


@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(),
    reason='Fixture demo/tei-test.xml not found',
)
def test_teipublisher_odd_teitest_xml_glossary_list_renders_as_definition_list(tmp_path: Path) -> None:
    """Glossary ``list`` with ``label`` children must render as ``<dl>`` with ``<dt>/<dd>`` pairs."""
    from teipublisher.odd_compiler import compile_odd
    from teipublisher.runtime.pm_runtime import serialize

    path = tmp_path / 'teipublisher_web.py'
    path.write_text(compile_odd(str(ODD)), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('teipublisher_web_glossary', str(path))
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    root = etree.parse(str(DEMO_TEI_TEST_XML)).getroot()
    html = serialize(m.transform(root))
    compact = re.sub(r'\s+', ' ', html)

    # Glossary section should render as <dl> with <dt>/<dd> pairs
    assert '<dl class="tei-list tei-list1">' in compact, 'glossary list should render as <dl>'
    assert '<dt class="tei-item tei-item1">TEI Processing Model</dt>' in compact, 'label should render as <dt>'
    assert '<dd class="tei-item tei-item1">A mechanism defined within an' in compact, 'item should render as <dd>'
    assert '<dt class="tei-item tei-item1">ODD</dt>' in compact, 'second label should render as <dt>'
    assert '<dt class="tei-item tei-item1">Behaviour</dt>' in compact, 'third label should render as <dt>'
