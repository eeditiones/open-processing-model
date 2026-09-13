"""Tests for Typst output functions."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from lxml import etree

from opm.resources import packaged_odd
from opm.runtime.context import RenderContext
from opm.runtime.markdown_output_functions import normalize_markdown_xml_text
from opm.runtime.output_functions import TemplateOutput
from opm.runtime.pm_runtime import apply_children
from opm.runtime.xpath_env import XPathEnvironment
from opm.runtime.typst_output_functions import (
    TypstOutputFunctions,
    _apply_inline_styling,
    _wrap_typst_classes,
    apply_typst_finish_cleanup,
    strip_html_markup,
)


def _scaffold_template(name: str) -> Path:
    return Path(str(resources.files('opm').joinpath(f'resources/scaffold/templates/{name}')))


def test_finish_cleanup_does_not_stub_css_classes() -> None:
    """Custom classes use ``#opm-css``; finish cleanup must not invent ``#let`` stubs."""
    body = 'la#opm-css("inverted")[n]guish #tei_l1[line]'
    out = apply_typst_finish_cleanup(body)
    assert '#let inverted' not in out
    assert '#opm-css("inverted")[n]' in out


def test_wrap_typst_classes_innermost_first() -> None:
    inner = 'text'
    config = RenderContext(typst_functions=frozenset({'tei_pb', 'tei_pb2'}))
    wrapped = _wrap_typst_classes(config, ['tei-pb', 'tei-pb2'], inner)
    assert wrapped == '#tei_pb2[#tei_pb[text]]'


def test_wrap_typst_classes_css_class_only() -> None:
    config = RenderContext()
    wrapped = _wrap_typst_classes(
        config,
        ['tei-title', 'tei-title10', 'r', 'title'],
        'Section',
    )
    assert wrapped == '#opm-css("title")[Section]'


def test_wrap_typst_classes_output_rendition_and_css_class() -> None:
    config = RenderContext(typst_functions=frozenset({'tei_emphasis1'}))
    wrapped = _wrap_typst_classes(
        config,
        ['tei-emphasis', 'tei-emphasis1', 'r', 'customEmph'],
        'text',
    )
    assert wrapped == '#opm-css("customEmph")[#tei_emphasis1[text]]'


def test_wrap_typst_classes_skips_undefined_renditions() -> None:
    inner = 'hello'
    config = RenderContext(typst_functions=frozenset({'tei_del1'}))
    wrapped = _wrap_typst_classes(config, ['tei-hi', 'tei-hi1'], inner)
    assert wrapped == 'hello'


def test_wrap_typst_classes_wraps_css_class() -> None:
    config = RenderContext()
    wrapped = _wrap_typst_classes(config, ['tei-guilabel', 'tei-guilabel1', 'r', 'guilabel'], 'Save')
    assert wrapped == '#opm-css("guilabel")[Save]'


def test_wrap_typst_classes_wraps_multiple_css_classes() -> None:
    config = RenderContext()
    wrapped = _wrap_typst_classes(config, ['r', 'persName', 'context'], 'Name')
    assert wrapped == '#opm-css("context")[#opm-css("persName")[Name]]'


def test_break_line_emits_typst_markup() -> None:
    pmf = TypstOutputFunctions()
    config = RenderContext()

    class Node:
        def get(self, key):
            return None

    node = Node()
    assert pmf.break_(
        config, node, ['tei-lb', 'tei-lb2', 'r', 'lb'], node, type='line',
    ) == ['#linebreak();']


def test_apply_inline_styling_wraps_output_rendition() -> None:
    config = RenderContext(
        typst_functions=frozenset({'tei_emphasis1'}),
        odd_css='.tei-emphasis1 { font-weight: bold; font-style: italic; }',
    )

    class Node:
        def get(self, key):
            return None

    result = _apply_inline_styling(
        config, Node(), ['tei-emphasis', 'tei-emphasis1'], 'Demo Collection'
    )
    assert result == '#tei_emphasis1[Demo Collection]'
    assert 'emph[' not in result
    assert 'strong[' not in result


def test_apply_inline_styling_wraps_output_rendition_and_css_class() -> None:
    config = RenderContext(typst_functions=frozenset({'tei_emphasis1'}))

    class Node:
        def get(self, key):
            return None

    result = _apply_inline_styling(
        config,
        Node(),
        ['tei-emphasis', 'tei-emphasis1', 'r', 'customEmph'],
        'Demo Collection',
    )
    assert result == '#opm-css("customEmph")[#tei_emphasis1[Demo Collection]]'


def test_apply_inline_styling_rend_bold() -> None:
    class Node:
        def get(self, key):
            return 'bold' if key == 'rend' else None

    result = _apply_inline_styling(RenderContext(), Node(), [], 'hello')
    assert result == '*hello*'


def test_typst_heading_and_finish() -> None:
    pmf = TypstOutputFunctions()
    config = RenderContext()
    nodes = ['\n= Title\n\n', 'Body text']
    finished = pmf.finish(config, nodes)
    assert len(finished) == 1
    assert 'Title' in finished[0]
    assert 'Body text' in finished[0]


def test_typst_heading_wraps_css_class() -> None:
    pmf = TypstOutputFunctions()
    config = RenderContext(
        apply_children=lambda cfg, node, content, buf: buf.append('My Title'),
    )

    class Node:
        def getprevious(self):
            return None

    result = pmf.heading(
        config,
        Node(),
        ['tei-title', 'tei-title9', 'r', 'doc-title'],
        [],
        level=1,
    )
    text = ''.join(result)
    assert text == '\n= #opm-css("doc_title")[My Title]\n\n'


def test_typst_heading_wraps_output_rendition() -> None:
    pmf = TypstOutputFunctions()
    config = RenderContext(
        typst_functions=frozenset({'tei_title9'}),
        apply_children=lambda cfg, node, content, buf: buf.append('My Title'),
    )

    class Node:
        def getprevious(self):
            return None

    result = pmf.heading(
        config,
        Node(),
        ['tei-title', 'tei-title9', 'r', 'doc-title'],
        [],
        level=1,
    )
    text = ''.join(result)
    assert text == '\n= #opm-css("doc_title")[#tei_title9[My Title]]\n\n'


def test_strip_html_markup_removes_tags_and_unescapes() -> None:
    raw = 'before <span class="tei-add">added</span> &amp; after'
    assert strip_html_markup(raw) == 'before added & after'


def test_apply_typst_finish_cleanup_strips_pb_popover() -> None:
    raw = (
        'gap [#tei_gap[<pb-popover>\n'
        '<span class="gap" slot="default"></span>\n'
        '<template slot="alternate">classified: 3 lines</template>\n'
        '</pb-popover>]]'
    )
    cleaned = apply_typst_finish_cleanup(raw)
    assert '<' not in cleaned
    assert 'classified: 3 lines' in cleaned
    assert 'pb-popover' not in cleaned


def test_typst_code_preserves_line_breaks() -> None:
    pmf = TypstOutputFunctions()
    config = RenderContext(
        normalize_text=normalize_markdown_xml_text, dispatch=lambda *a, **k: [],
    )

    class Node:
        def get(self, key):
            return None

    result = pmf.code(
        config,
        Node(),
        [],
        ['line one\n', '  line two\n'],
        'xml',
    )
    assert len(result) == 1
    assert isinstance(result[0], TemplateOutput)
    assert 'line one\n  line two\n' in result[0]


def test_typst_code_preserves_xml_markup_literally() -> None:
    tei = 'http://www.tei-c.org/ns/1.0'
    listing = etree.Element(f'{{{tei}}}programlisting')
    tag = etree.SubElement(listing, f'{{{tei}}}tag')
    tag.text = 'elementSpec'

    pmf = TypstOutputFunctions()
    config = RenderContext(dispatch=lambda *a, **k: ['SHOULD_NOT_APPEAR'])

    result = pmf.code(config, listing, [], listing, 'xml')
    body = str(result[0])
    assert 'SHOULD_NOT_APPEAR' not in body
    assert '<tag>elementSpec</tag>' in body
    assert '#tei_' not in body


def test_typst_finish_preserves_xml_in_fenced_code() -> None:
    raw = '\n```xml\n<tag>elementSpec</tag>\n```\n'
    finished = apply_typst_finish_cleanup(raw)
    assert '<tag>elementSpec</tag>' in finished


def test_typst_finish_preserves_at_and_underscores_in_fenced_code() -> None:
    raw = '\n```\n@mode foo_bar\n```\n'
    finished = apply_typst_finish_cleanup(raw)
    assert '@mode foo_bar' in finished


def test_typst_template_preserves_line_breaks() -> None:
    from opm.runtime.output_functions import TemplateOutput

    pmf = TypstOutputFunctions()
    tpl = '#note[\n[[title]]\n\n[[content]]\n]'
    result = pmf.template(
        RenderContext(),
        None,
        [],
        tpl,
        {'title': 'Title', 'content': 'Body'},
    )
    assert len(result) == 1
    assert isinstance(result[0], TemplateOutput)
    assert result[0] == '#note[\nTitle\n\nBody\n]'


def test_typst_template_flattens_html_to_text() -> None:
    pmf = TypstOutputFunctions()
    tpl = '<span class="above tei-add">[[content]]</span>'
    result = pmf.template(RenderContext(), None, [], tpl, {'content': 'Trump Tower'})
    assert result == ['Trump Tower']
    assert '<' not in result[0]


def test_metadata_stores_keyed_value() -> None:
    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    config = RenderContext(
        apply_children=lambda cfg, node, content, buf: buf.extend(content),
    )
    result = pmf.metadata(config, Node(), [], ['TEI Publisher Docs'], key='title')
    assert result == []
    assert config.state.metadata == {'title': ['TEI Publisher Docs']}
    # Collected values are run state; they never reach $parameters.
    assert 'metadata' not in config.parameters


def test_metadata_accumulates_multiple_values_as_list() -> None:
    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    config = RenderContext(
        apply_children=lambda cfg, node, content, buf: buf.extend(content),
    )
    pmf.metadata(config, Node(), [], ['Alice Smith'], key='authors')
    pmf.metadata(config, Node(), [], ['Bob Jones'], key='authors')
    assert config.state.metadata['authors'] == ['Alice Smith', 'Bob Jones']


def test_metadata_no_key_is_noop() -> None:
    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    config = RenderContext(apply_children=lambda *a, **k: None)
    result = pmf.metadata(config, Node(), [], [], key=None)
    assert result == []
    assert config.state.metadata == {}


def test_typst_note_emits_inline_footnote() -> None:
    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    config = RenderContext(
        apply_children=lambda cfg, node, content, buf: buf.extend(content),
    )
    result = pmf.note(config, Node(), [], ['note text'], None, None)
    assert result == ['#footnote[note text];']
    assert config.state.footnotes == []


def test_typst_note_keeps_the_source_marker() -> None:
    """A note's ``label`` (its ``@n``) is the marker, not Typst's running number."""

    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    config = RenderContext(
        apply_children=lambda cfg, node, content, buf: buf.extend(content),
    )
    assert pmf.note(config, Node(), [], ['struck out'], None, 'a') == [
        '#footnote(numbering: (..) => "a")[struck out];',
    ]
    # A label from an XPath param arrives as a one-item sequence.
    assert pmf.note(config, Node(), [], ['commentary'], None, ['12']) == [
        '#footnote(numbering: (..) => "12")[commentary];',
    ]


def test_typst_note_margin_emits_marginnote() -> None:
    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    config = RenderContext(
        apply_children=lambda cfg, node, content, buf: buf.extend(content),
    )
    result = pmf.note(config, Node(), [], ['42'], 'margin', None)
    assert result == ['#marginnote[42];']
    # ODD XPath often yields a singleton sequence for string params.
    result_seq = pmf.note(config, Node(), [], ['42'], ['margin'], None)
    assert result_seq == ['#marginnote[42];']
    # A label becomes the marker shown at the note and at its anchor.
    result_marked = pmf.note(config, Node(), [], ['struck out'], 'margin', ['a'])
    assert result_marked == ['#marginnote(marker: "a")[struck out];']


def test_apply_typst_finish_cleanup_preserves_marginnote() -> None:
    """Direct ``#marginnote`` aliases from the shell must survive finish cleanup."""
    raw = 'text|#marginnote[12] more'
    cleaned = apply_typst_finish_cleanup(raw)
    assert '#marginnote[12]' in cleaned
    assert '#let marginnote' not in cleaned


def test_escape_typst_at_signs_escapes_attribute_mentions() -> None:
    from opm.runtime.typst_output_functions import escape_typst_at_signs

    assert escape_typst_at_signs('the @mode attribute') == 'the \\@mode attribute'
    assert escape_typst_at_signs('the @ident attribute') == 'the \\@ident attribute'


def test_escape_typst_text_node_escapes_special_chars() -> None:
    from opm.runtime.typst_output_functions import escape_typst_text_node

    assert escape_typst_text_node('the @mode attribute') == 'the \\@mode attribute'
    assert escape_typst_text_node('pay #attention') == 'pay \\#attention'
    assert escape_typst_text_node('cost $5') == 'cost \\$5'
    assert escape_typst_text_node('foo * bar') == 'foo \\* bar'
    assert escape_typst_text_node('foo_bar') == 'foo\\_bar'


def test_apply_typst_finish_cleanup_does_not_escape_chars_in_prose() -> None:
    """Character escaping is done at text-node level; cleanup must not add it."""
    raw = 'Pay attention to the @mode attribute on elementSpec.'
    cleaned = apply_typst_finish_cleanup(raw)
    assert '@mode' in cleaned
    assert '\\@' not in cleaned


def test_apply_typst_finish_cleanup_inline_footnote_preserved() -> None:
    """Inline #footnote[body] survives finish cleanup intact."""
    raw = 'text#footnote[He mentions this.] more text'
    cleaned = apply_typst_finish_cleanup(raw)
    assert '#footnote[He mentions this.]' in cleaned


def test_css_length_to_typst_converts_px() -> None:
    from opm.runtime.typst_output_functions import css_length_to_typst

    assert css_length_to_typst('512px') == '384pt'
    assert css_length_to_typst('10pt') == '10pt'


def test_escape_typst_underscores_preserves_emphasis() -> None:
    from opm.runtime.typst_output_functions import escape_typst_underscores

    assert escape_typst_underscores('_italic_') == '_italic_'
    assert escape_typst_underscores("'_blank'") == "'\\_blank'"


def test_escape_typst_underscores_with_tei_identifiers_on_line() -> None:
    from opm.runtime.typst_output_functions import escape_typst_underscores

    line = (
        '#tei_emphasis1[NB:]Abbreviation … underscore (_).'
    )
    fixed = escape_typst_underscores(line)
    assert '#tei_emphasis1[' in fixed
    assert 'underscore (\\_).' in fixed
    assert 'tei\\_emphasis' not in fixed


def test_escape_typst_asterisks_escapes_lone_asterisk() -> None:
    from opm.runtime.typst_output_functions import escape_typst_asterisks

    assert escape_typst_asterisks('foo * bar') == 'foo \\* bar'
    assert escape_typst_asterisks('param: *') == 'param: \\*'


def test_escape_typst_asterisks_preserves_bold_pairs() -> None:
    from opm.runtime.typst_output_functions import escape_typst_asterisks

    assert escape_typst_asterisks('*bold*') == '*bold*'
    assert escape_typst_asterisks('*bold*: *') == '*bold*: \\*'


def test_css_typst_wrap_uses_brackets() -> None:
    from opm.runtime.typst_output_functions import _css_typst_wrap

    config = RenderContext(odd_css='.simple_bold { font-weight: bold; }')
    assert _css_typst_wrap(config, ['simple_bold'], 'NB:') == 'strong[NB:]'


def test_typst_figure_skips_figure_css_class_wrap() -> None:
    pmf = TypstOutputFunctions()
    config = RenderContext(
        apply_children=lambda cfg, node, content, buf: buf.extend(
            pmf.graphic(cfg, node, [], [], 'demo.png', '512px', None, None, None)
        ),
    )
    result = pmf.figure(
        config,
        None,
        ['tei-figure', 'tei-figure2', 'r', 'figure'],
        [],
        title='Browsing Demo collection',
    )
    text = ''.join(result)
    assert '#figure[\n  #figure(' not in text
    assert 'image("demo.png", width: 384pt)' in text
    assert 'caption:' in text


def test_typst_figure_uses_code_mode_for_nested_image() -> None:
    pmf = TypstOutputFunctions()
    config = RenderContext(
        apply_children=lambda cfg, node, content, buf: buf.extend(
            pmf.graphic(cfg, node, [], [], 'fig.png', '512px', None, None, None)
        ),
    )
    result = pmf.figure(config, None, [], [], title=None)
    text = ''.join(result)
    assert 'image("fig.png", width: 384pt)' in text
    assert '#image(' not in text


def test_typst_link() -> None:
    pmf = TypstOutputFunctions()
    config = RenderContext(
        apply_children=lambda cfg, node, content, out: out.append('label'),
    )
    result = pmf.link(config, None, [], [], 'http://example.com', None, None)
    assert ''.join(result) == '#link("http://example.com")[label]'


def test_wrap_typst_classes_skips_rend_function_tokens() -> None:
    """``color(red)`` from @rend must not become an invalid ``#color(red)[...]`` call."""
    config = RenderContext()
    wrapped = _wrap_typst_classes(config, ['tei-hi', 'tei-hi1', 'color(red)'], 'text')
    assert 'color(red)' not in wrapped
    assert wrapped == 'text'


def test_apply_inline_styling_rend_color() -> None:
    from opm.runtime.typst_output_functions import _apply_inline_styling

    class Node:
        def get(self, key):
            return 'color(red)' if key == 'rend' else None

    config = RenderContext()
    result = _apply_inline_styling(config, Node(), ['tei-hi', 'tei-hi1', 'color(red)'], 'red text')
    assert 'color(red)' not in result
    assert '#text(fill: red)[red text]' in result


def test_apply_inline_styling_rend_unknown_function_is_ignored() -> None:
    from opm.runtime.typst_output_functions import _apply_inline_styling

    class Node:
        def get(self, key):
            return 'unknown(value)' if key == 'rend' else None

    config = RenderContext()
    result = _apply_inline_styling(config, Node(), ['tei-hi', 'tei-hi1', 'unknown(value)'], 'text')
    assert 'unknown(value)' not in result
    assert result == 'text'


def test_lb_pass_through_template_for_typst(tmp_path) -> None:
    """Typst ``<lb/>`` models may use ``pass-through`` + ``pb:template``, not ``#opm-css("lb")[]``."""
    from opm.odd_compiler import compile_odd
    from opm.transform import load_transform_module, run_transform

    tei = 'http://www.tei-c.org/ns/1.0'
    root = etree.fromstring(
        f'<TEI xmlns="{tei}"><text><body>'
        f'<p>son<lb break="no"/>dern</p>'
        f'<head>Title<lb/>(subtitle)</head>'
        f'</body></text></TEI>'.encode()
    )
    odd = tmp_path / 'lb_typst.odd'
    odd.write_text(
        '''<?xml version="1.0"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:pb="http://teipublisher.com/1.0">
  <teiHeader><fileDesc>
    <titleStmt><title>t</title></titleStmt>
    <publicationStmt><p>p</p></publicationStmt>
    <sourceDesc><p>s</p></sourceDesc>
  </fileDesc></teiHeader>
  <text><body>
    <schemaSpec ident="lb_typst" ns="http://www.tei-c.org/ns/1.0">
      <elementSpec ident="lb" mode="change">
        <model output="typst" predicate="@break='no'" behaviour="pass-through">
          <pb:template xml:space="preserve">-#linebreak();</pb:template>
        </model>
        <model output="typst" predicate="parent::p or parent::head" behaviour="break">
          <param name="type" value="'line'"/>
        </model>
      </elementSpec>
    </schemaSpec>
  </body></text>
</TEI>
''',
        encoding='utf-8',
    )
    mod_path = tmp_path / 'lb_typst.py'
    mod_path.write_text(compile_odd(str(odd), output_mode='typst'), encoding='utf-8')
    mod = load_transform_module(mod_path)
    body = run_transform(mod, root, apply_template=False)
    assert '#opm-css("lb")' not in body
    assert 'son-#linebreak();dern' in body
    assert 'Title#linebreak();(subtitle)' in body
    # Bare -\\ before ] would escape Typst's closing bracket (e.g. #footnote).
    assert '-\\' not in body
    assert '\\]' not in body


def test_teipublisher_typst_fills_book_template_metadata(tmp_path) -> None:
    """TEI header title/authors are keyed metadata consumed by ``book.typ.j2``."""
    from opm.odd_compiler import compile_odd
    from opm.transform import load_transform_module, run_transform

    tei = 'http://www.tei-c.org/ns/1.0'
    root = etree.fromstring(
        f'<TEI xmlns="{tei}">'
        f'<teiHeader><fileDesc><titleStmt>'
        f'<title>The Greatest Markup</title>'
        f'<author>Alice Smith</author>'
        f'<author>Bob Jones</author>'
        f'</titleStmt>'
        f'<publicationStmt><p>n</p></publicationStmt>'
        f'<sourceDesc><p>s</p></sourceDesc>'
        f'</fileDesc></teiHeader>'
        f'<text><body><p>Hello</p></body></text>'
        f'</TEI>'.encode()
    )
    odd_path = packaged_odd('teipublisher')
    mod_path = tmp_path / 'tei_typst.py'
    mod_path.write_text(compile_odd(str(odd_path), output_mode='typst'), encoding='utf-8')
    mod = load_transform_module(mod_path)
    out = run_transform(
        mod,
        root,
        typst_template_path=_scaffold_template('book.typ.j2'),
    )
    assert 'title: [The Greatest Markup]' in out
    assert '"Alice Smith"' in out
    assert '"Bob Jones"' in out
    assert 'Your Title' not in out


def test_docbook_typst_note_is_inflow_callout_not_marginnote(tmp_path) -> None:
    """DocBook ``<note>`` uses ``cssClass="note"`` (orange bar), not ``#note`` / marginalia."""
    from opm.odd_compiler import compile_odd
    from opm.transform import load_transform_module, run_transform

    dbk = 'http://docbook.org/ns/docbook'
    root = etree.fromstring(
        f'<article xmlns="{dbk}" version="5.0">'
        f'<info><title>Guide</title></info>'
        f'<section xml:id="tour"><title>Tour</title>'
        f'<para>Before.</para>'
        f'<note><para>If you installed without docker, you will only see two applications.</para></note>'
        f'<para>After.</para>'
        f'</section>'
        f'</article>'.encode()
    )
    odd_path = packaged_odd('docbook')
    mod_path = tmp_path / 'docbook_typst.py'
    mod_path.write_text(compile_odd(str(odd_path), output_mode='typst'), encoding='utf-8')
    mod = load_transform_module(mod_path)
    out = run_transform(mod, root, typst_template_path=_scaffold_template('docbook.typ.j2'))
    assert '#opm-css("note")' in out
    assert 'stroke: (left: 4pt + rgb("#d07f00"))' in out
    assert 'If you installed without docker' in out
    # The ODD must not emit marginalia's ``#note[…]`` for DocBook notes.
    assert '#note[' not in out
    assert '#marginnote[' not in out


def test_ordered_list_item_numbering_ignores_other_siblings() -> None:
    """Items count only their own kind.

    A JATS ``ref-list`` puts a ``title`` before the first ``ref``; counting every
    preceding sibling started the reference list at 2.
    """
    root = etree.fromstring(
        '<ref-list><title>References</title>'
        '<ref>First</ref><ref>Second</ref><ref>Third</ref></ref-list>'
    )
    pmf = TypstOutputFunctions()
    config = RenderContext(
        list_type='ordered',
        apply_children=lambda cfg, node, content, buf: buf.append(node.text),
    )
    markers = [
        ''.join(str(p) for p in pmf.list_item(config, ref, [], None))
        for ref in root.findall('ref')
    ]
    assert [m.strip() for m in markers] == ['1. First', '2. Second', '3. Third']


_JATS_ARTICLE = (
    '<article xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article">'
    '<front>'
    '<journal-meta><journal-title-group><journal-title>Journal of Art Historiography'
    '</journal-title></journal-title-group><issn>2042-4752</issn></journal-meta>'
    '<article-meta>'
    '<article-id pub-id-type="publisher-id">ARTHIST</article-id>'
    '<article-id pub-id-type="doi">https://doi.org/10.48352/uobxjah.00004200</article-id>'
    '<title-group><article-title>Digital Editions</article-title></title-group>'
    '<contrib-group><contrib contrib-type="person">'
    '<contrib-id contrib-id-type="orcid">https://orcid.org/0000-0002-4419-7912</contrib-id>'
    '<name><surname>Bastianello</surname><given-names>Elisa</given-names></name>'
    '<email>bastianello@biblhertz.it</email>'
    '<xref ref-type="aff" rid="aff1"/></contrib></contrib-group>'
    '<aff id="aff1"><institution content-type="orgname">Digital Publishing</institution>'
    '<addr-line/><city>Rome</city><country>IT</country></aff>'
    '<pub-date publication-format="electronic" iso-8601-date="2022-12"><year>2022</year></pub-date>'
    '<volume>27</volume><elocation-id>EB01</elocation-id>'
    '<permissions><copyright-statement>(c) 2022</copyright-statement>'
    '<license xlink:href="https://creativecommons.org/licenses/by-nc/4.0/">'
    '<license-p>CC BY-NC 4.0</license-p></license></permissions>'
    '<abstract><title>Abstract</title><p>On digital editions.</p></abstract>'
    '</article-meta></front>'
    '<body><sec id="s1"><title>Content</title><p>Body text.</p></sec></body>'
    '</article>'
)


def _jats_typst_metadata(tmp_path) -> dict[str, str]:
    """Render packaged ``jats.odd`` through a template that dumps each metadata key."""
    from opm.odd_compiler import compile_odd
    from opm.transform import load_transform_module, run_transform

    keys = ('title', 'authors', 'author_records', 'journal', 'volume', 'elocation', 'date', 'doi', 'license')
    template = tmp_path / 'dump.typ.j2'
    template.write_text(
        '\n'.join("%s=={{ (metadata.get('%s') or [''])[0] }}" % (k, k) for k in keys),
        encoding='utf-8',
    )
    mod_path = tmp_path / 'jats_typst.py'
    mod_path.write_text(
        compile_odd(str(packaged_odd('jats')), output_mode='typst'), encoding='utf-8'
    )
    out = run_transform(
        load_transform_module(mod_path),
        etree.fromstring(_JATS_ARTICLE.encode()),
        xpath_env=XPathEnvironment(extensions=['opm.runtime.common_xpath_functions']),
        typst_template_path=template,
    )
    return dict(line.split('==', 1) for line in str(out).splitlines() if '==' in line)


def test_jats_typst_metadata_carries_the_citation_apparatus(tmp_path) -> None:
    """The Typst title block needs more than title/authors/abstract for a journal article."""
    meta = _jats_typst_metadata(tmp_path)
    assert meta['journal'] == 'Journal of Art Historiography'
    assert meta['volume'] == '27'
    assert meta['elocation'] == 'EB01'
    assert meta['date'] == 'December 2022'
    # The bare DOI, so a shell can build both the link and the display text.
    assert meta['doi'] == '10.48352/uobxjah.00004200'
    assert meta['license'] == 'https://creativecommons.org/licenses/by-nc/4.0/'


def test_jats_typst_authors_key_stays_a_plain_name(tmp_path) -> None:
    """``book.typ.j2`` prints ``authors`` verbatim, so the record goes in its own key."""
    meta = _jats_typst_metadata(tmp_path)
    assert meta['authors'] == 'Elisa Bastianello'
    assert '|' not in meta['authors']
    name, email, affiliation, orcid = meta['author_records'].split('|')
    assert name == 'Elisa Bastianello'
    assert email == 'bastianello\\@biblhertz.it'
    # Reached through xref/@rid, with the empty addr-line dropped.
    assert affiliation == 'Digital Publishing, Rome, IT'
    # Bare ORCID: arkheion builds the orcid.org URL itself.
    assert orcid == '0000-0002-4419-7912'


def test_jats_web_publication_date_is_formatted(tmp_path) -> None:
    """Upstream's XSLT ``format-date()`` does not exist here; ``tp:format_date`` replaces it."""
    from opm.odd_compiler import compile_odd
    from opm.transform import load_transform_module, run_transform

    mod_path = tmp_path / 'jats_web.py'
    mod_path.write_text(
        compile_odd(str(packaged_odd('jats')), output_mode='web'), encoding='utf-8'
    )
    out = str(
        run_transform(
            load_transform_module(mod_path),
            etree.fromstring(_JATS_ARTICLE.encode()),
            xpath_env=XPathEnvironment(extensions=['opm.runtime.common_xpath_functions']),
            apply_template=False,
        )
    )
    assert 'December 2022' in out
