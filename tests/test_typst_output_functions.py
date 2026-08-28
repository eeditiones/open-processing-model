"""Tests for Typst output functions."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from lxml import etree

from opm.resources import packaged_odd
from opm.runtime.markdown_output_functions import normalize_markdown_xml_text
from opm.runtime.output_functions import TemplateOutput
from opm.runtime.pm_runtime import apply_children
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
    config = {'typst_functions': frozenset({'tei_pb', 'tei_pb2'})}
    wrapped = _wrap_typst_classes(config, ['tei-pb', 'tei-pb2'], inner)
    assert wrapped == '#tei_pb2[#tei_pb[text]]'


def test_wrap_typst_classes_css_class_only() -> None:
    config: dict = {'typst_functions': frozenset()}
    wrapped = _wrap_typst_classes(
        config,
        ['tei-title', 'tei-title10', 'r', 'title'],
        'Section',
    )
    assert wrapped == '#opm-css("title")[Section]'


def test_wrap_typst_classes_output_rendition_and_css_class() -> None:
    config = {'typst_functions': frozenset({'tei_emphasis1'})}
    wrapped = _wrap_typst_classes(
        config,
        ['tei-emphasis', 'tei-emphasis1', 'r', 'customEmph'],
        'text',
    )
    assert wrapped == '#opm-css("customEmph")[#tei_emphasis1[text]]'


def test_wrap_typst_classes_skips_undefined_renditions() -> None:
    inner = 'hello'
    config = {'typst_functions': frozenset({'tei_del1'})}
    wrapped = _wrap_typst_classes(config, ['tei-hi', 'tei-hi1'], inner)
    assert wrapped == 'hello'


def test_wrap_typst_classes_wraps_css_class() -> None:
    config: dict = {'typst_functions': frozenset()}
    wrapped = _wrap_typst_classes(config, ['tei-guilabel', 'tei-guilabel1', 'r', 'guilabel'], 'Save')
    assert wrapped == '#opm-css("guilabel")[Save]'


def test_wrap_typst_classes_wraps_multiple_css_classes() -> None:
    config: dict = {'typst_functions': frozenset()}
    wrapped = _wrap_typst_classes(config, ['r', 'persName', 'context'], 'Name')
    assert wrapped == '#opm-css("context")[#opm-css("persName")[Name]]'


def test_break_line_emits_typst_markup() -> None:
    pmf = TypstOutputFunctions()
    config: dict = {'typst_functions': frozenset()}

    class Node:
        def get(self, key):
            return None

    node = Node()
    assert pmf.break_(
        config, node, ['tei-lb', 'tei-lb2', 'r', 'lb'], node, type='line',
    ) == ['#linebreak();']


def test_apply_inline_styling_wraps_output_rendition() -> None:
    config = {
        'typst_functions': frozenset({'tei_emphasis1'}),
        'odd_css': '.tei-emphasis1 { font-weight: bold; font-style: italic; }',
    }

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
    config = {'typst_functions': frozenset({'tei_emphasis1'})}

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

    result = _apply_inline_styling({}, Node(), [], 'hello')
    assert result == '*hello*'


def test_typst_heading_and_finish() -> None:
    pmf = TypstOutputFunctions()
    config: dict = {}
    nodes = ['\n= Title\n\n', 'Body text']
    finished = pmf.finish(config, nodes)
    assert len(finished) == 1
    assert 'Title' in finished[0]
    assert 'Body text' in finished[0]


def test_typst_heading_wraps_css_class() -> None:
    pmf = TypstOutputFunctions()
    config = {
        'typst_functions': frozenset(),
        'apply_children': lambda cfg, node, content, buf: buf.append('My Title'),
    }

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
    config = {
        'typst_functions': frozenset({'tei_title9'}),
        'apply_children': lambda cfg, node, content, buf: buf.append('My Title'),
    }

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
    config = {
        'normalize_text': normalize_markdown_xml_text,
        'apply_children': apply_children,
        'dispatch': lambda *a, **k: [],
    }

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
    config: dict = {'dispatch': lambda *a, **k: ['SHOULD_NOT_APPEAR']}

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
        {},
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
    result = pmf.template({}, None, [], tpl, {'content': 'Trump Tower'})
    assert result == ['Trump Tower']
    assert '<' not in result[0]


def test_metadata_stores_keyed_value() -> None:
    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    params: dict = {}
    config: dict = {
        'parameters': params,
        'apply_children': lambda cfg, node, content, buf: buf.extend(content),
    }
    result = pmf.metadata(config, Node(), [], ['TEI Publisher Docs'], key='title')
    assert result == []
    assert params['metadata'] == {'title': ['TEI Publisher Docs']}


def test_metadata_accumulates_multiple_values_as_list() -> None:
    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    params: dict = {}
    config: dict = {
        'parameters': params,
        'apply_children': lambda cfg, node, content, buf: buf.extend(content),
    }
    pmf.metadata(config, Node(), [], ['Alice Smith'], key='authors')
    pmf.metadata(config, Node(), [], ['Bob Jones'], key='authors')
    assert params['metadata']['authors'] == ['Alice Smith', 'Bob Jones']


def test_metadata_no_key_is_noop() -> None:
    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    config: dict = {'parameters': {}, 'apply_children': lambda *a, **k: None}
    result = pmf.metadata(config, Node(), [], [], key=None)
    assert result == []
    assert 'metadata' not in config['parameters']


def test_typst_note_emits_inline_footnote() -> None:
    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    config: dict = {
        'apply_children': lambda cfg, node, content, buf: buf.extend(content),
    }
    result = pmf.note(config, Node(), [], ['note text'], None, None)
    assert result == ['#footnote[note text];']
    assert 'footnotes' not in config


def test_typst_note_margin_emits_marginnote() -> None:
    class Node:
        def get(self, key):
            return None

    pmf = TypstOutputFunctions()
    config: dict = {
        'apply_children': lambda cfg, node, content, buf: buf.extend(content),
    }
    result = pmf.note(config, Node(), [], ['42'], 'margin', None)
    assert result == ['#marginnote[42];']
    # ODD XPath often yields a singleton sequence for string params.
    result_seq = pmf.note(config, Node(), [], ['42'], ['margin'], None)
    assert result_seq == ['#marginnote[42];']


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

    config = {'odd_css': '.simple_bold { font-weight: bold; }'}
    assert _css_typst_wrap(config, ['simple_bold'], 'NB:') == 'strong[NB:]'


def test_typst_figure_skips_figure_css_class_wrap() -> None:
    pmf = TypstOutputFunctions()
    config = {
        'typst_functions': frozenset(),
        'apply_children': lambda cfg, node, content, buf: buf.extend(
            pmf.graphic(cfg, node, [], [], 'demo.png', '512px', None, None, None)
        ),
    }
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
    config = {
        'apply_children': lambda cfg, node, content, buf: buf.extend(
            pmf.graphic(cfg, node, [], [], 'fig.png', '512px', None, None, None)
        ),
    }
    result = pmf.figure(config, None, [], [], title=None)
    text = ''.join(result)
    assert 'image("fig.png", width: 384pt)' in text
    assert '#image(' not in text


def test_typst_link() -> None:
    pmf = TypstOutputFunctions()
    config = {
        'apply_children': lambda cfg, node, content, out: out.append('label'),
    }
    result = pmf.link(config, None, [], [], 'http://example.com', None, None)
    assert ''.join(result) == '#link("http://example.com")[label]'


def test_wrap_typst_classes_skips_rend_function_tokens() -> None:
    """``color(red)`` from @rend must not become an invalid ``#color(red)[...]`` call."""
    config: dict = {'typst_functions': frozenset()}
    wrapped = _wrap_typst_classes(config, ['tei-hi', 'tei-hi1', 'color(red)'], 'text')
    assert 'color(red)' not in wrapped
    assert wrapped == 'text'


def test_apply_inline_styling_rend_color() -> None:
    from opm.runtime.typst_output_functions import _apply_inline_styling

    class Node:
        def get(self, key):
            return 'color(red)' if key == 'rend' else None

    config: dict = {'typst_functions': frozenset()}
    result = _apply_inline_styling(config, Node(), ['tei-hi', 'tei-hi1', 'color(red)'], 'red text')
    assert 'color(red)' not in result
    assert '#text(fill: red)[red text]' in result


def test_apply_inline_styling_rend_unknown_function_is_ignored() -> None:
    from opm.runtime.typst_output_functions import _apply_inline_styling

    class Node:
        def get(self, key):
            return 'unknown(value)' if key == 'rend' else None

    config: dict = {'typst_functions': frozenset()}
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
