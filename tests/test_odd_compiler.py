"""Smoke tests for ODD → Python compilation."""

from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path

import pytest
from lxml import etree

from opm.resources import packaged_odd

ODD = packaged_odd('teipublisher')


def test_compile_teipublisher_odd_emits_valid_python(tmp_path: Path) -> None:
    from opm.odd_compiler import compile_odd

    src = compile_odd(str(ODD))
    assert 'def _dispatch' in src
    assert 'def transform' in src
    assert 'def new_context' in src
    assert 'config.xpath.test(node, ' in src
    assert 'pass_through' in src
    assert 'ODD_GENERATED_CSS' in src
    assert 'odd_css' in src
    # tagsDecl rendition → .simple_* (css.xql); model outputRendition → .tei-{ident}{n}[:scope]
    assert '.simple_bold' in src
    assert '.tei-corr2:before' in src
    assert '.tei-del1 {' in src

    out = tmp_path / 'gen.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)

    spec = importlib.util.spec_from_file_location('teipublisher_gen', str(out))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.transform)
    assert 'def main()' not in src


def test_compile_typst_mode_imports_typst_output_functions(tmp_path: Path) -> None:
    from opm.odd_compiler import compile_odd

    src = compile_odd(str(ODD), output_mode='typst')
    assert "OUTPUT_MODE = 'typst'" in src
    assert 'ODD_GENERATED_TYPST' in src
    assert 'ODD_GENERATED_CSS' not in src
    assert 'TYPST_RENDITION_FUNCTIONS' in src
    assert 'typst_functions=TYPST_RENDITION_FUNCTIONS,' in src

    out = tmp_path / 'typst_gen.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)
    assert r'\[' in src or '\\[' in src  # backslashes escaped for Python source

    from opm.runtime.markdown_output_functions import normalize_markdown_xml_text
    from opm.runtime.typst_output_functions import TypstOutputFunctions, escape_typst_text_node

    config = _load_generated(out).new_context(etree.fromstring('<TEI/>'))
    assert isinstance(config.pmf, TypstOutputFunctions)
    assert config.normalize_text is normalize_markdown_xml_text
    assert config.text_escape is escape_typst_text_node
    assert config.odd_css == ''


def _load_generated(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compile_markdown_mode_renders_with_markdown_output_functions(tmp_path: Path) -> None:
    from opm.odd_compiler import compile_odd
    from opm.runtime.markdown_output_functions import (
        MarkdownOutputFunctions,
        normalize_markdown_xml_text,
    )

    src = compile_odd(str(ODD), output_mode='markdown')
    assert "OUTPUT_MODE = 'markdown'" in src
    out = tmp_path / 'md_gen.py'
    out.write_text(src, encoding='utf-8')

    config = _load_generated(out).new_context(etree.fromstring('<TEI/>'))
    assert isinstance(config.pmf, MarkdownOutputFunctions)
    assert config.normalize_text is normalize_markdown_xml_text
    assert config.output == 'markdown'


def test_compile_web_mode_emits_output_mode() -> None:
    from opm.odd_compiler import compile_odd

    src = compile_odd(str(ODD), output_mode='web')
    assert "OUTPUT_MODE = 'web'" in src
    assert 'odd_css=ODD_GENERATED_CSS,' in src


def test_compile_unknown_mode_is_an_error() -> None:
    from opm.odd_compiler import compile_odd

    with pytest.raises(ValueError, match="Unknown output mode 'latex'"):
        compile_odd(str(ODD), output_mode='latex')


def test_opm_output_prefix_matches_web_mode_in_document_order(tmp_path: Path) -> None:
    """``output=\"opm-web\"`` is web-only for this compiler; first matching model wins."""
    from opm.odd_compiler import compile_odd

    odd = tmp_path / 'opm_web.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="p" mode="change">'
        '<model output="opm-web" behaviour="block"/>'
        '<model output="web" behaviour="paragraph"/>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    src = compile_odd(str(odd), output_mode='web')
    assert "return pmf.block(config, node, ['tei-p', 'tei-p1', r], node)" in src
    assert 'pmf.paragraph' not in src


def test_opm_output_prefix_ignored_for_other_compile_modes(tmp_path: Path) -> None:
    from opm.odd_compiler import compile_odd

    odd = tmp_path / 'opm_markdown_only.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="p" mode="change">'
        '<model output="opm-web" behaviour="block"/>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    src = compile_odd(str(odd), output_mode='markdown')
    assert "case 'p':" not in src


def test_compile_code_behaviour_emits_language_kwarg_for_markdown(tmp_path: Path) -> None:
    from opm.odd_compiler import compile_odd

    odd = tmp_path / 'code_behaviour.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="code" mode="change">'
        '<model output="markdown" behaviour="code">'
        '<param name="language" value="\'python\'"/>'
        '</model>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    src = compile_odd(str(odd), output_mode='markdown')
    assert "pmf.code(config, node, ['tei-code', 'tei-code1', r], node, language='python')" in src


def test_generated_transform_calls_pmf_finish() -> None:
    from opm.odd_compiler import compile_odd

    src = compile_odd(str(ODD))
    assert 'config.pmf.finish(config, result)' in src


def test_load_odd_tolerates_duplicate_xml_id(tmp_path: Path) -> None:
    """Real-world ODDs (e.g. tei_simplePrint.odd) carry duplicate xml:id values;
    the loader must not reject them, since xml:id is not used for spec lookup."""
    from opm.odd_compiler.parse_odd import load_odd

    odd = tmp_path / 'dup_id.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<note xml:id="n7">a</note><note xml:id="n7">b</note>'
        '<schemaSpec xmlns="http://www.tei-c.org/ns/1.0" ident="x" '
        'ns="http://www.tei-c.org/ns/1.0"/>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    parsed = load_odd(str(odd))
    assert parsed.schema_ns == 'http://www.tei-c.org/ns/1.0'


def test_emit_skips_xml_comments_inside_elementSpec(tmp_path: Path) -> None:
    """XML comments are legitimate children of elementSpec / modelGrp and must
    not reach _local(tag) — their .tag is a cyfunction, not a string."""
    from opm.odd_compiler import compile_odd

    odd = tmp_path / 'with_comment.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="p" mode="change">'
        '<!-- comment between specs is legal -->'
        '<model behaviour="paragraph"/>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    src = compile_odd(str(odd))
    assert "case 'p':" in src


def test_hyphen_in_element_ident_emits_valid_template_helper_name(tmp_path: Path) -> None:
    """elementSpec @ident may contain hyphens (e.g. ref-cell); helper defs must be valid Python."""
    from opm.odd_compiler import compile_odd

    odd = tmp_path / 'hyphen_ident.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:pb="http://teipublisher.com/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="ref-cell" mode="change">'
        '<model behaviour="paragraph">'
        '<pb:template xmlns="" xml:space="preserve"><span>[[content]]</span></pb:template>'
        '</model>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    src = compile_odd(str(odd))
    assert 'def _odd_template_ref_cell_1(' in src
    assert "'tei-ref-cell'" in src
    assert "'tei-ref-cell1'" in src

    out = tmp_path / 'gen.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)


def test_template_output_is_not_reprocessed_in_a_no_namespace_odd(tmp_path: Path) -> None:
    """A pb:template combined with a behaviour keeps the markup it builds.

    ``_dispatch`` returns foreign-namespace nodes untouched, which is what
    normally protects template output. An ODD with ``ns=""`` (JATS) has no such
    guard, so the behaviour must be handed a template-marked config instead.
    """
    from opm.odd_compiler import compile_odd

    odd = tmp_path / 'no_ns.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:pb="http://teipublisher.com/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="">'
        '<elementSpec ident="list" mode="add">'
        '<model behaviour="list"><param name="content" value="ref"/></model>'
        '</elementSpec>'
        '<elementSpec ident="ref" mode="add">'
        '<model behaviour="pass-through">'
        '<param name="id" value="@id"/>'
        '<pb:template xmlns="" xml:space="preserve"><li id="[[id]]">[[content]]</li></pb:template>'
        '</model>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    src = compile_odd(str(odd))
    assert 'pmf.pass_through(template_config(config)' in src

    out = tmp_path / 'gen.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)
    spec = importlib.util.spec_from_file_location('no_ns_gen', str(out))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    root = etree.fromstring(b'<list><ref id="r1">one</ref></list>')
    html = ''.join(
        part if isinstance(part, str)
        else etree.tostring(part, encoding='unicode', method='html')
        for part in mod.transform(root)
    )
    assert '<li id="r1">one</li>' in html


def test_emit_template_params_use_apply_template_param_value(tmp_path: Path) -> None:
    """Literal ``.`` and XPath params must not inject raw context TEI into templates."""
    from opm.odd_compiler import compile_odd

    odd = tmp_path / 'tpl_param_ctx.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:pb="http://teipublisher.com/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="seg" mode="change">'
        '<model behaviour="inline">'
        '<param name="inner" value="."/>'
        '<param name="label" value="string(.)"/>'
        '<pb:template xmlns="" xml:space="preserve">'
        '<span>[[label]]:[[inner]]</span></pb:template>'
        '</model>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    src = compile_odd(str(odd))
    assert 'apply_template_param_value,' in src
    assert 'apply_template_param_value(config, node, node)' in src
    assert 'apply_template_param_value(config, node, config.xpath.select(node,' in src


def test_compile_odd_without_web_specs_emits_valid_python(tmp_path: Path) -> None:
    """An ODD whose element specs target only non-web outputs (e.g. print)
    must still yield a syntactically valid Python module — the previous
    emitter produced a bare ``match`` with no ``case`` lines, which is a
    SyntaxError."""
    from opm.odd_compiler import compile_odd

    odd = tmp_path / 'print_only.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="p" mode="change">'
        '<model output="print" behaviour="paragraph"/>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    src = compile_odd(str(odd))
    out = tmp_path / 'gen.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)
    # No cases for web output → match statement is omitted entirely.
    assert 'match _tag(node):' not in src
    assert 'return apply(config, child_nodes(node))' in src


def test_teipublisher_web_injects_generated_css_in_head(tmp_path: Path) -> None:
    """Compiled module passes ODD CSS into ``odd_css``; HTML ``head`` gets a single style block."""
    from opm.odd_compiler import compile_odd
    from opm.runtime.pm_runtime import serialize

    path = tmp_path / 'teipublisher_web.py'
    path.write_text(compile_odd(str(ODD)), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('teipublisher_web', str(path))
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    xml = b"""<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:lang="en">
<teiHeader><fileDesc><titleStmt><title>T</title></titleStmt></fileDesc></teiHeader>
<text><body><p>x</p></body></text></TEI>"""
    root = etree.fromstring(xml)
    out = serialize(m.transform(root))
    assert '<style' in out
    assert 'Model rendition styles' in m.ODD_GENERATED_CSS
    assert '.tei-del1' in out
    assert out.count('/* Generated stylesheet. Do not edit. */') == 1


def test_compile_inherited_odd_loads_parent_then_overwrites_child(tmp_path: Path) -> None:
    """Child ODD inherits elementSpec from source ODD and overwrites duplicate idents."""
    from opm.odd_compiler import compile_odd

    (tmp_path / 'child.css').write_text('.tei-speaker { font-style: italic; }\n', encoding='utf-8')
    child = tmp_path / 'custom.odd'
    child.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>child</title></titleStmt>
      <publicationStmt><p>test</p></publicationStmt>
      <sourceDesc><p>test</p></sourceDesc>
    </fileDesc>
    <encodingDesc>
      <tagsDecl>
        <rendition source="child.css"/>
      </tagsDecl>
    </encodingDesc>
  </teiHeader>
  <text><body>
    <schemaSpec ident="custom" start="TEI teiCorpus" source="teipublisher.odd">
      <elementSpec ident="lb" mode="change">
        <model behaviour="omit"/>
      </elementSpec>
      <elementSpec ident="titleStmt" mode="change">
        <model predicate="$parameters?mode=('breadcrumb', 'title')" behaviour="inline">
          <desc>for breadcrumbs, pick title/@type='statement'</desc>
          <param name="content" value="title[@type='statement']"/>
        </model>
      </elementSpec>
    </schemaSpec>
  </body></text>
</TEI>
''',
        encoding='utf-8',
    )
    src = compile_odd(str(child))

    # Inherited from packaged teipublisher.odd (not declared in the child).
    assert "case 'ab':" in src

    # Overwritten by the child for ident='lb' (mode is ignored).
    assert "case 'lb':" in src
    assert "return pmf.omit(config, node, ['tei-lb', 'tei-lb1', r], node)" in src
    # Inherited + local tagsDecl rendition sources are included in generated CSS.
    assert 'external styles loaded from child.css' in src
    assert '.simple_bold { font-weight: bold; }' in src
    # <desc> from models is preserved as generated Python comments.
    assert "# for breadcrumbs, pick title/@type='statement'" in src


def test_compile_child_odd_inherits_packaged_teipublisher(tmp_path: Path) -> None:
    """schemaSpec/@source falls back to packaged stock ODDs when no sibling exists."""
    from opm.odd_compiler import compile_odd

    child = tmp_path / 'custom.odd'
    child.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc>
    <titleStmt><title>child</title></titleStmt>
    <publicationStmt><p>test</p></publicationStmt>
    <sourceDesc><p>test</p></sourceDesc>
  </fileDesc></teiHeader>
  <text><body>
    <schemaSpec ident="custom" start="TEI teiCorpus" source="teipublisher.odd">
    </schemaSpec>
  </body></text>
</TEI>
''',
        encoding='utf-8',
    )
    src = compile_odd(str(child))
    assert "case 'p':" in src
    assert 'external styles loaded from tp.css' in src


_JATS_NESTED = (
    '<article>'
    '<front><article-meta><title-group><article-title>A</article-title></title-group>'
    '</article-meta></front>'
    '<body>'
    '<sec id="s1"><title>One</title><p>x</p>'
    '<sec id="s1a"><title>One A</title><p>y</p></sec>'
    '</sec>'
    '<sec id="s2"><title>Two</title><p>z</p></sec>'
    '</body>'
    '</article>'
)


def _jats_toc(tmp_path: Path, **params: str) -> str:
    """Render packaged ``jats.odd`` in ``mode=toc``, the fragment ``opm chunk`` builds."""
    from opm.odd_compiler import compile_odd
    from opm.transform import load_transform_module, run_transform

    mod_path = tmp_path / 'jats_web.py'
    mod_path.write_text(
        compile_odd(str(packaged_odd('jats')), output_mode='web'), encoding='utf-8'
    )
    root = etree.fromstring(_JATS_NESTED.encode())
    return str(
        run_transform(
            load_transform_module(mod_path),
            root,
            parameters={'mode': 'toc', **params},
            apply_template=False,
        )
    )


def test_jats_toc_nests_sections_and_links_by_id(tmp_path: Path) -> None:
    """JATS sections carry ``@id``, not ``@xml:id``; the TOC has to link on that."""
    out = _jats_toc(tmp_path)
    # Root list holds the two top-level sections, not front matter.
    assert out.count('<li') == 3
    assert 'article-title' not in out
    # Leaf entry.
    assert 'xml-id="s2"' in out and 'node-id="s2"' in out
    assert '>Two<' in out
    # Parent section keeps its child in a nested list.
    assert '<details open="open">' in out
    assert 'xml-id="s1a"' in out


def test_jats_toc_collapse_parameter_closes_the_details(tmp_path: Path) -> None:
    out = _jats_toc(tmp_path, collapse='true')
    assert '<details>' in out
    assert '<details open="open">' not in out


def test_docbook_toc_prefers_opm_web_over_tei_publisher_lib_models(tmp_path: Path) -> None:
    """docbook.odd carries both TOC forms; the ``opm-web`` ones must win in web mode.

    The plain ``mode='toc'`` models exist for the eXist-side webcomponents TOC and sit
    after the ``opm-web`` ones. Document order decides, so reordering them upstream would
    silently swap opm's static TOC for the live one.
    """
    from opm.odd_compiler import compile_odd
    from opm.transform import load_transform_module, run_transform

    dbk = 'http://docbook.org/ns/docbook'
    root = etree.fromstring(
        f'<article xmlns="{dbk}" version="5.0"><info><title>Guide</title></info>'
        f'<section xml:id="a"><title>A</title>'
        f'<section xml:id="a1"><title>A one</title><para>x</para></section>'
        f'</section>'
        f'<section xml:id="b"><title>B</title><para>y</para></section>'
        f'</article>'.encode()
    )
    mod_path = tmp_path / 'dbk_web.py'
    mod_path.write_text(
        compile_odd(str(packaged_odd('docbook')), output_mode='web'), encoding='utf-8'
    )
    out = str(
        run_transform(
            load_transform_module(mod_path),
            root,
            parameters={'mode': 'toc'},
            apply_template=False,
        )
    )
    # opm-web form: <details> wrapper and a pb-link carrying node-id.
    assert '<details open="open">' in out
    assert 'node-id="a"' in out
    assert 'node-id="b"' in out
    # The tei-publisher-lib leaf model would emit a bare <li> with no pb-link.
    assert '<li><span' not in out


def _odd_with_availability(path: Path, *, title: str, availability: str, source: str = '') -> Path:
    """A minimal compilable ODD carrying a rights statement of its own."""
    src_attr = f' source="{source}"' if source else ''
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        f'<teiHeader><fileDesc><titleStmt><title>{title}<desc>ignored</desc></title></titleStmt>'
        f'<publicationStmt>{availability}</publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        f'<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0"{src_attr}>'
        '<elementSpec ident="p" mode="change"><model behaviour="paragraph"/></elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    return path


def test_generated_module_reproduces_odd_rights_statement() -> None:
    """CC BY asks for attribution; a compiled module has to carry it to give it."""
    from opm.odd_compiler import compile_odd

    src = compile_odd(str(ODD))
    docstring = src.split('"""')[1]
    assert 'teipublisher.odd — TEI Publisher ODD' in docstring
    assert 'e-editiones' in docstring
    assert 'Creative Commons Attribution 4.0 International License' in docstring
    assert 'https://creativecommons.org/licenses/by/4.0/' in docstring
    # The prose of <availability> names who is owed credit — copyright holders and
    # the provenance of what the models were built on. Both have to survive.
    assert 'Copyright 2017–2026 e-editiones and individual contributors.' in docstring
    assert 'TEI Consortium' in docstring


def test_rights_statement_covers_inherited_odds_parents_first(tmp_path: Path) -> None:
    """The ODD you compile may say CC0 while the models it inherits say otherwise."""
    from opm.odd_compiler import compile_odd

    child = _odd_with_availability(
        tmp_path / 'child.odd',
        title='Project ODD',
        availability=(
            '<publisher>Some Project</publisher>'
            '<availability><licence '
            'target="https://creativecommons.org/publicdomain/zero/1.0/">'
            'CC0 1.0 Universal</licence></availability>'
        ),
        source=str(ODD),
    )
    docstring = compile_odd(str(child)).split('"""')[1]
    assert docstring.index('teipublisher.odd') < docstring.index('child.odd — Project ODD')
    # The inherited models keep asking for their credit, whatever the local ODD says.
    assert 'Creative Commons Attribution 4.0 International License' in docstring
    assert 'Some Project' in docstring
    assert 'CC0 1.0 Universal' in docstring


def test_no_rights_statement_when_the_odd_declares_none(tmp_path: Path) -> None:
    """Silence is not a licence to invent one."""
    from opm.odd_compiler import compile_odd

    odd = _odd_with_availability(
        tmp_path / 'bare.odd', title='Bare', availability='<p>p</p>'
    )
    assert 'Rights in the processing models' not in compile_odd(str(odd))


def test_rights_statement_cannot_break_out_of_the_docstring(tmp_path: Path) -> None:
    """ODD text is arbitrary; a stray quote run must not end the module docstring."""
    from opm.odd_compiler import compile_odd

    odd = _odd_with_availability(
        tmp_path / 'quoted.odd',
        title='Quoted """ ODD',
        availability=(
            '<publisher>Ends with a backslash \\</publisher>'
            '<availability><licence target="https://example.org/l">'
            'The """so-called""" licence</licence></availability>'
        ),
    )
    src = compile_odd(str(odd))
    out = tmp_path / 'quoted_gen.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)
    assert "The '''so-called''' licence" in src.split('"""')[1]


def test_source_odd_path_with_windows_backslashes_is_docstring_safe(
    tmp_path: Path,
) -> None:
    """``C:\\Users\\…`` in the docstring must not become a ``\\U`` unicode escape."""
    from dataclasses import replace

    from opm.odd_compiler.codegen.python_generator import PythonGenerator
    from opm.odd_compiler.parse_odd import load_odd

    odd = _odd_with_availability(
        tmp_path / 'winpath.odd',
        title='Windows path',
        availability='',
    )
    parsed = replace(
        load_odd(str(odd)),
        odd_path=r'C:\Users\alice\opm\odd\custom.odd',
    )
    src = PythonGenerator().generate_module(parsed, 'm', output_mode='web')
    out = tmp_path / 'winpath_gen.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)
    docstring = src.split('"""')[1]
    assert 'Source ODD: C:/Users/alice/opm/odd/custom.odd' in docstring
    assert '\\Users' not in docstring


def test_read_licence_ignores_a_teiheader_quoted_inside_the_odd_body(tmp_path: Path) -> None:
    """An example header in the body documents TEI; it claims nothing about this file."""
    from opm.odd_compiler.parse_odd import read_licence

    odd = tmp_path / 'example_header.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>Real</title></titleStmt>'
        '<publicationStmt><publisher>Real Publisher</publisher>'
        '<availability><licence target="https://example.org/real">Real licence</licence>'
        '</availability></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<p><egXML xmlns="http://www.tei-c.org/ns/Examples">'
        '<teiHeader><fileDesc><titleStmt><title>Quoted</title></titleStmt>'
        '<publicationStmt><publisher>Quoted Publisher</publisher></publicationStmt>'
        '</fileDesc></teiHeader></egXML></p>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="p" mode="change"><model behaviour="paragraph"/></elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    licence = read_licence(odd)
    assert licence is not None
    assert licence.publisher == 'Real Publisher'
    assert licence.title == 'Real'
    assert licence.licence == 'Real licence'
    assert licence.target == 'https://example.org/real'
