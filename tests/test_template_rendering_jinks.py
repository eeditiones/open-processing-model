"""jinks templates as opm page templates: engine choice, variables, tp: functions, chunking."""

from __future__ import annotations

from pathlib import Path

import jinja2

from opm import jinks_templates as jinks
from opm.chunking import chunk_document
from opm.config import ChunkingConfig
from opm.runtime.xpath_env import XPathEnvironment
from opm.template_frontmatter import template_context
from opm.template_rendering import (
    is_jinks_template,
    load_template,
    render_document_template,
    render_typst_document_template,
    template_environment,
)

from tests.test_chunking import _write_chunking_fixture_module, _write_chunking_fixture_xml

_DOC = '<html lang="en"><head><title>T</title></head><body><p>a &amp; b</p></body></html>'


def test_engine_is_chosen_by_suffix(tmp_path: Path) -> None:
    assert is_jinks_template(Path('page.html.tpl'))
    assert is_jinks_template(Path('book.typ.tpl'))
    assert not is_jinks_template(Path('page.html.j2'))
    # Any other name stays Jinja2, as it always was.
    assert not is_jinks_template(Path('page.html'))
    (tmp_path / 'a.html.j2').write_text('{{ x }}', encoding='utf-8')
    (tmp_path / 'a.html.tpl').write_text('[[ $x ]]', encoding='utf-8')
    assert isinstance(template_environment(tmp_path / 'a.html.j2'), jinja2.Environment)
    assert isinstance(template_environment(tmp_path / 'a.html.tpl'), jinks.Environment)


def test_document_template_variables(tmp_path: Path) -> None:
    page = tmp_path / 'page.html.tpl'
    page.write_text(
        '---toml\ntitle = "From frontmatter"\n---\n'
        '<html lang="[[ $lang ]]"><head>[[ $head_html ]]<style>[[ $odd_css ]]</style></head>'
        '<body><h1>[[ $title ]]</h1><nav>[[ $fragments?toc ]]</nav>[[ $content_html ]]'
        '<footer>[[ $context?site ]] [[ $parameters?p ]] [[ $context?layout?after?mobile ]]</footer>'
        '</body></html>',
        encoding='utf-8',
    )
    out = render_document_template(
        serialized_html=_DOC, template_path=page, odd_css='.a > .b {}',
        parameters={'p': 'P<'}, context={'site': 'Site & Co', 'title': 'ctx'},
        fragments={'toc': '<ul><li>1</li></ul>'},
    )
    assert out.startswith('\n<html lang="en"><head><title>T</title><style>.a > .b {}</style>')
    assert '<h1>From frontmatter</h1>' in out
    assert '<nav><ul><li>1</li></ul></nav><p>a &amp; b</p>' in out
    # Context values are escaped, and the packaged layout defaults are there.
    assert '<footer>Site &amp; Co P&lt; stack</footer>' in out


def test_template_context_for_jinks_adds_defaults(tmp_path: Path) -> None:
    (tmp_path / 'p.html.tpl').write_text('x', encoding='utf-8')
    env = template_environment(tmp_path / 'p.html.tpl')
    ctx = template_context(env, 'p.html.tpl', {'site': 's'})
    assert ctx['site'] == 's'
    assert 'layout' in ctx


def test_extends_packaged_search_path(tmp_path: Path) -> None:
    (tmp_path / 'base.html.tpl').write_text('<b>[% block content %][% endblock %]</b>', encoding='utf-8')
    (tmp_path / 'page.html.tpl').write_text(
        '---json\n{"templating": {"extends": "base.html.tpl"}}\n---\n[[ $content_html ]]',
        encoding='utf-8')
    out = render_document_template(serialized_html=_DOC, template_path=tmp_path / 'page.html.tpl',
                                   odd_css='', parameters={})
    assert out == '<b>\n<p>a &amp; b</p></b>'


def test_tp_extension_functions(tmp_path: Path) -> None:
    page = tmp_path / 'page.html.tpl'
    page.write_text('<p>[[ tp:greet("TEI") ]]</p>', encoding='utf-8')
    env = XPathEnvironment(extensions=('tests.extensions_sample',))
    out = render_document_template(serialized_html=_DOC, template_path=page, odd_css='',
                                   parameters={}, xpath_env=env)
    assert out == '<p>Hello TEI</p>'


def test_typst_template_is_text_mode(tmp_path: Path) -> None:
    book = tmp_path / 'book.typ.tpl'
    book.write_text('#set document(title: "[[ $metadata?title ]]")\n[[ $content_typst ]]',
                    encoding='utf-8')
    out = render_typst_document_template(content_typst='*a* & <b>', template_path=book,
                                         odd_typst='', parameters={},
                                         metadata={'title': 'A < B'})
    assert out == '#set document(title: "A < B")\n*a* & <b>'


def test_missing_template_is_file_not_found(tmp_path: Path) -> None:
    page = tmp_path / 'page.html.tpl'
    page.write_text('---json\n{"templating": {"extends": "nope.html"}}\n---\n', encoding='utf-8')
    env = template_environment(page)
    try:
        load_template(env, page)
    except FileNotFoundError as e:
        assert 'nope.html' in str(e)
    else:  # pragma: no cover
        raise AssertionError('expected FileNotFoundError')


def test_chunk_pages_with_jinks_template(tmp_path: Path) -> None:
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    template = tmp_path / 'page.html.tpl'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)
    template.write_text(
        '<html><body>'
        '<p class="meta">[[ $chunk?id ]]|[[ $chunk?file ]]|[[ $document ]]|'
        '[[ array:size($documents) ]]</p>'
        '[% if $chunk?next %]<a href="[[ $chunk?next ]].html">next</a>[% endif %]'
        '<main>[[ $content_html ]]</main></body></html>',
        encoding='utf-8',
    )
    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=ChunkingConfig(xpath="//body/div[@type='chunk']", output_dir='out'),
        project_root=tmp_path,
        template_path=template,
    )
    pages = sorted((tmp_path / 'out').glob('*.html'))
    assert pages
    first = pages[0].read_text(encoding='utf-8')
    assert '|fixture.xml|1</p>' in first
    assert '<main><' in first and '&lt;' not in first.split('<main>')[1]


def test_context_wins_over_built_in_variables(tmp_path: Path) -> None:
    """As in the Jinja2 templates, ``[context] lang`` wins over the document's ``lang``."""
    page = tmp_path / 'page.html.tpl'
    page.write_text('[[ $lang ]]|[[ $context?lang ]]', encoding='utf-8')
    out = render_document_template(serialized_html=_DOC, template_path=page, odd_css='',
                                   parameters={}, context={'lang': 'de'})
    assert out == 'de|de'
    out = render_document_template(serialized_html=_DOC, template_path=page, odd_css='',
                                   parameters={})
    assert out == 'en|en'


def test_packaged_default_document_template(tmp_path: Path) -> None:
    """``default_document.html.tpl`` puts the document into ``opm/layout.html.tpl``."""
    from opm.template_rendering import default_template_path

    out = render_document_template(
        serialized_html=_DOC,
        template_path=default_template_path('default_document.html.tpl'),
        odd_css='.x {}', parameters={},
        context={'site_name': 'Site', 'menu': {'items': [{'label': 'About', 'url': 'about.html'}]},
                 'layout': {'before': {'width': '20rem'}}},
        fragments={'breadcrumbs': '<ol><li>A</li></ol>'},
    )
    assert out.lstrip().startswith('<!doctype html>\n<html lang="en">')
    assert '<!-- opm-default-template -->' in out
    assert '<style type="text/css">\n.x {}' in out
    assert '<span class="logo__title">Site</span>' in out
    assert '<li><a href="about.html">About</a></li>' in out
    assert '<div class="breadcrumb"><ol><li>A</li></ol></div>' in out
    assert 'style="--opm-layout-before-width: 20rem;"' in out
    assert 'class="opm-layout  opm-before--drawer opm-after--stack"' in out
    # Every region is written; opm-layout.css hides the empty ones.
    for region in ('class="hero"', 'class="before-top"', 'class="before"', 'class="after"',
                   'class="page-footer"'):
        assert region in out
    assert '<p>a &amp; b</p>' in out


def test_layout_template_fills_regions(tmp_path: Path) -> None:
    page = tmp_path / 'page.html.tpl'
    page.write_text(
        '---json\n{"templating": {"extends": "opm/layout.html.tpl"}, '
        '"features": {"menubar": false}, "layout": {"before": {"mobile": "stack"}}}\n---\n'
        '[% template before %]<nav class="toc"/>[% endtemplate %]'
        '[% template footer %]<p>foot</p>[% endtemplate %]'
        '[% template body_class %]mine[% endtemplate %]'
        '<section>[[ $content_html ]]</section>',
        encoding='utf-8')
    out = render_document_template(serialized_html=_DOC, template_path=page, odd_css='',
                                   parameters={})
    squashed = ''.join(out.split())
    assert '<asideclass="before"id="opm-before"><navclass="toc"/></aside>' in squashed
    assert '<footerclass="page-footer"><p>foot</p></footer>' in squashed
    assert '<mainclass="opm-main"id="opm-content"><section><p>a&amp;b</p></section></main>' in squashed
    assert 'class="menubar"' not in out
    assert 'id="opm-before-toggle"' not in out
    assert 'mine">' in out


def test_monograph_example_uses_jinks_templates(tmp_path: Path) -> None:
    """The monograph example renders its chunk pages through ``monograph.html.tpl``."""
    from opm.cli import main

    example = Path(__file__).resolve().parents[1] / 'examples' / 'monograph'
    out = tmp_path / 'chunks'
    assert main(['chunk', str(example / 'data' / '47009.xml'), '-o', str(out), '--force',
                 '--config', str(example / 'opm.toml')]) == 0
    page = (out / '47009.xml' / '002.html').read_text(encoding='utf-8')
    assert '<title>Der Römerbrief 1922</title>' in page
    assert '<span class="logo__title">Der Römerbrief 1922</span>' in page
    assert page.count('aria-current="page"') == 1
    assert 'class="chap-folio-nav__rail chap-folio-nav__rail--prev"' in page
    assert '<body class="chapbook chapbook--with-toc">' in page


def test_packaged_defaults_are_jinks_templates() -> None:
    from opm.template_rendering import (
        DEFAULT_INDEX_TEMPLATE_NAME, DEFAULT_PRINT_TEMPLATE_NAME, DEFAULT_TEMPLATE_NAME,
        DEFAULT_TYPST_TEMPLATE_NAME, default_template_path,
    )
    for name in (DEFAULT_TEMPLATE_NAME, DEFAULT_PRINT_TEMPLATE_NAME,
                 DEFAULT_TYPST_TEMPLATE_NAME, DEFAULT_INDEX_TEMPLATE_NAME):
        assert name.endswith('.tpl'), name
        assert default_template_path(name).is_file()


def test_default_index_writes_entry_fragments_as_markup(tmp_path: Path) -> None:
    """Index entries are dataclasses; their fragments reach the template as HTML."""
    from opm.chunking import IndexEntry
    from opm.template_rendering import (
        DEFAULT_INDEX_TEMPLATE_NAME, default_template_path, render_index_template,
    )

    entries = [
        IndexEntry(name='a.xml', stem='a', label='A', href='a.xml/001.html', chunks=1,
                   fragments={'browse': '<h2 class="b">A &amp; B</h2>'}),
        IndexEntry(name='b.xml', stem='b', label='B <x>', href='b.xml/001.html', chunks=3,
                   fragments={}),
    ]
    out = render_index_template(
        entries=entries, template_path=default_template_path(DEFAULT_INDEX_TEMPLATE_NAME),
        title='Letters', context={'site_name': ''},
    )
    assert '<!-- opm-default-index-template -->' in out
    assert '<title>Letters</title>' in out
    assert '<h2 class="b">A &amp; B</h2>' in out
    assert '<h2><a href="b.xml/001.html">B &lt;x&gt;</a></h2>' in out
    assert '1 section\n' in out and '3 sections' in out


def test_default_typst_template_takes_the_metadata_title(tmp_path: Path) -> None:
    from opm.template_rendering import DEFAULT_TYPST_TEMPLATE_NAME, default_template_path

    out = render_typst_document_template(
        content_typst='Body', template_path=default_template_path(DEFAULT_TYPST_TEMPLATE_NAME),
        odd_typst='#let x = 1', parameters={'title': 'Param'}, metadata={'title': ['Meta']},
    )
    assert 'title: "Meta",' in out
    assert '#let x = 1' in out and out.rstrip().endswith('Body')
    assert '#let opm-css(name, body)' in out


def test_base_template_wraps_body_in_pb_page(tmp_path: Path) -> None:
    page = tmp_path / 'page.html.tpl'
    page.write_text(
        '---toml\n[pb_page]\nendpoint = "."\napi-version = "1.0.0"\n\n'
        '[templating]\nextends = "opm/base.html.tpl"\n---\n', encoding='utf-8')
    out = render_document_template(serialized_html=_DOC, template_path=page, odd_css='',
                                   parameters={})
    squashed = ' '.join(out.split())
    assert '<pb-page endpoint="." api-version="1.0.0"> <article class="content">' in squashed
    assert '</article> </pb-page>' in squashed
    plain = tmp_path / 'plain.html.tpl'
    plain.write_text('---json\n{"templating": {"extends": "opm/base.html.tpl"}}\n---\n',
                     encoding='utf-8')
    assert '<pb-page' not in render_document_template(
        serialized_html=_DOC, template_path=plain, odd_css='', parameters={})


def test_scaffolded_shells_exist_in_both_syntaxes() -> None:
    from opm.resources import packaged_document_dir  # noqa: F401  (package import check)
    from opm.scaffold import _EXTRA_SHELLS, _resource_root

    templates = _resource_root().joinpath('scaffold', 'templates')
    for name in _EXTRA_SHELLS:
        assert templates.joinpath(f'{name}.html.tpl').is_file(), name
        assert templates.joinpath(f'{name}.html.j2').is_file(), name
    for name in ('book', 'docbook'):
        assert templates.joinpath(f'{name}.typ.tpl').is_file(), name
        assert templates.joinpath(f'{name}.typ.j2').is_file(), name
