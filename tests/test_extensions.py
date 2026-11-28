"""Project extension modules: prefixed XPath functions and custom behaviours."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from lxml import etree

from opm.config import load_project_config
from opm.odd_compiler.behaviour_map import BEHAVIOUR_METHOD
from opm.odd_compiler.expression_check import static_problem
from opm.project import Project
from opm.runtime.extensions import ExtensionModule, clear_cache, method_name
from opm.runtime.xpath_env import XPathEnvironment, clear_compiled_xpath_cache

TEI = 'http://www.tei-c.org/ns/1.0'

EXT_SOURCE = '''
from opm.runtime.extensions import behaviour
from opm.runtime.xpath_extensions import expect_string


def shout(value):
    return expect_string(value).upper()


def output_entity(value):
    return f'entity:{expect_string(value)}'


@behaviour
def footnote(pmf, config, node, cls, content, place=None, label=None):
    out = pmf.builtin.note(config, node, cls, content, place, label)
    for el in out:
        if hasattr(el, 'set'):
            el.set('data-fn-group', node.get('type') or 'none')
    return out


@behaviour("next-part")
def next_part(pmf, config, node, cls, content, direction=None):
    return [f'[{direction}]']
'''

OVERRIDE_SOURCE = '''
from opm.runtime.extensions import behaviour


@behaviour
def inline(pmf, config, node, cls, content):
    out = pmf.builtin.inline(config, node, cls, content)
    for el in out:
        el.set('data-custom', 'yes')
    return out
'''

ODD = '''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:pb="http://teipublisher.com/1.0">
  <teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>
    <publicationStmt><p/></publicationStmt><sourceDesc><p/></sourceDesc></fileDesc></teiHeader>
  <text><body>
    <schemaSpec ident="t" start="TEI" source="teipublisher.odd">
      <elementSpec ident="note" mode="change">
        <model behaviour="footnote">
          <param name="place" value="'footnote'"/>
        </model>
      </elementSpec>
      <elementSpec ident="ref" mode="change">
        <model predicate="@type='next'" behaviour="next-part">
          <param name="direction" value="'forward'"/>
        </model>
        <model predicate="@type='missing'" behaviour="no-such-behaviour"/>
        <model behaviour="inline">
          <param name="content" value="ext-html:output-entity(@target)"/>
        </model>
      </elementSpec>
      <elementSpec ident="name" mode="change">
        <model behaviour="inline">
          <param name="content" value="ext-html:shout(.)"/>
        </model>
      </elementSpec>
    </schemaSpec>
  </body></text>
</TEI>
'''

DOC = f'''<TEI xmlns="{TEI}"><teiHeader/><text><body>
<p>A <name>barth</name> text<note type="digital">fn body</note>
<ref type="next">x</ref> <ref target="k1">y</ref> <ref type="missing">kept</ref></p>
</body></text></TEI>'''


@pytest.fixture(autouse=True)
def _clean_caches():
    yield
    clear_cache()
    clear_compiled_xpath_cache()
    for name in [m for m in sys.modules if m.startswith('kbext_')]:
        del sys.modules[name]


def _project(tmp_path: Path, extensions_toml: str, *, module: str = 'kbext_html',
             source: str = EXT_SOURCE) -> Project:
    (tmp_path / f'{module}.py').write_text(textwrap.dedent(source), encoding='utf-8')
    (tmp_path / 't.odd').write_text(ODD, encoding='utf-8')
    (tmp_path / 'doc.xml').write_text(DOC, encoding='utf-8')
    (tmp_path / 'opm.toml').write_text(
        '[project]\npythonpath = ["."]\n\n[transform]\nodd = "t.odd"\n\n' + extensions_toml,
        encoding='utf-8',
    )
    config = load_project_config(tmp_path / 'opm.toml')
    return Project(config, root=tmp_path)


def test_method_name_reproduces_the_builtin_table() -> None:
    for odd_name, method in BEHAVIOUR_METHOD.items():
        assert method_name(odd_name) == method


def test_config_parses_extension_tables(tmp_path: Path) -> None:
    (tmp_path / 'opm.toml').write_text(textwrap.dedent('''
        [transform]
        xpath_extensions = ["a.b"]

        [[transform.extensions]]
        module = "ext.html"
        prefix = "ext-html"
        output = ["web"]
    '''), encoding='utf-8')
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert cfg.extensions == (
        ExtensionModule('a.b'),
        ExtensionModule('ext.html', 'ext-html', None, ('web',)),
    )


@pytest.mark.parametrize('table, message', [
    ('prefix = "x"', 'needs module'),
    ('module = "m"\nprefix = "a:b"', 'not a valid prefix'),
    ('module = "m"\noutput = ["nope"]', 'unknown output'),
    ('module = "m"\nbogus = 1', 'unknown key'),
])
def test_config_rejects_bad_extension_tables(tmp_path: Path, table: str, message: str) -> None:
    (tmp_path / 'opm.toml').write_text(f'[[transform.extensions]]\n{table}\n', encoding='utf-8')
    with pytest.raises(ValueError, match=message):
        load_project_config(tmp_path / 'opm.toml')


def test_prefixed_function_with_dashed_name(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / 'kbext_fn.py').write_text(EXT_SOURCE, encoding='utf-8')
    monkeypatch.syspath_prepend(str(tmp_path))
    env = XPathEnvironment(extensions=[ExtensionModule('kbext_fn', 'ext-html')])
    root = etree.fromstring(f'<p xmlns="{TEI}">k</p>')
    assert env.select(root, 'ext-html:output-entity(.)') == 'entity:k'
    assert env.select(root, 'ext-html:output_entity(.)') == 'entity:k'
    # Behaviours are not XPath functions.
    assert static_problem('ext-html:footnote(.)', {}) is None  # unknown to the compiler, kept
    # select() logs the failed evaluation and yields no result.
    assert env.select(root, 'ext-html:footnote(.)') in ([], None, '')


def test_ext_prefix_calls_are_not_compiled_out() -> None:
    assert static_problem('ext-html:output-entity(.)', {}) is None
    assert static_problem('util:document-name(.)', {}) == 'eXist function util:document-name()'
    assert static_problem('fn:no-such(.)', {}) is not None


def test_custom_behaviours_and_functions_in_web(tmp_path: Path) -> None:
    project = _project(tmp_path, textwrap.dedent('''
        [[transform.extensions]]
        module = "kbext_html"
        prefix = "ext-html"
    '''))
    html = project.transform(tmp_path / 'doc.xml', mode='web')
    assert 'data-fn-group="digital"' in html
    assert 'fn body' in html
    assert '[forward]' in html
    assert 'entity:k1' in html
    assert 'BARTH' in html
    # An unknown behaviour still renders its content.
    assert 'kept' in html


def test_output_restricts_behaviours(tmp_path: Path) -> None:
    project = _project(tmp_path, textwrap.dedent('''
        [[transform.extensions]]
        module = "kbext_html"
        prefix = "ext-html"
        output = ["print"]
    '''))
    html = project.transform(tmp_path / 'doc.xml', mode='web')
    assert 'data-fn-group' not in html
    assert '[forward]' not in html
    # XPath functions stay available in every output.
    assert 'BARTH' in html


def test_markdown_uses_custom_behaviour(tmp_path: Path) -> None:
    project = _project(tmp_path, textwrap.dedent('''
        [[transform.extensions]]
        module = "kbext_html"
        prefix = "ext-html"
    '''))
    md = project.transform(tmp_path / 'doc.xml', mode='markdown')
    assert '[forward]' in md
    assert 'BARTH' in md


def test_override_builtin_behaviour(tmp_path: Path) -> None:
    project = _project(tmp_path, textwrap.dedent('''
        [[transform.extensions]]
        module = "kbext_override"
        prefix = "kb"
    '''), module='kbext_override', source=OVERRIDE_SOURCE)
    html = project.transform(tmp_path / 'doc.xml', mode='web')
    assert 'data-custom="yes"' in html


def test_without_extension_unknown_behaviour_renders_children(tmp_path: Path) -> None:
    project = _project(tmp_path, '')
    html = project.transform(tmp_path / 'doc.xml', mode='web')
    assert 'fn body' in html
    assert 'data-fn-group' not in html



@pytest.mark.parametrize('xpath, expected', [('//div', 'div'), (None, 'TEI')])
def test_transform_xpath_binds_the_selection_as_root(xpath, expected) -> None:
    """``opm transform --xpath`` binds the selection as ``$parameters?root``."""
    import types
    from unittest.mock import patch

    from opm.transform import transform_node

    doc = etree.fromstring(f'<TEI xmlns="{TEI}"><text><body><div/></body></text></TEI>')
    seen = {}

    def fake_run(mod, element, **kwargs):
        seen['root'] = kwargs['xpath_env'].select(element, '$parameters?root/local-name()')
        return ''

    with patch('opm.transform.run_transform', fake_run):
        transform_node(types.ModuleType('m'), doc, xpath=xpath, xpath_env=XPathEnvironment())
    assert seen['root'] == expected
