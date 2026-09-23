"""Static ODD documentation site."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from lxml import etree
import pytest

from opm.cli import main
from opm.document_site import _CATALOG_IDS, build_document_site, prepare_document_tree
from opm.odd_schema import (
    chapters_have_prose,
    compile_schema,
    iter_guideline_chapters,
)
from opm.resources import packaged_odd
from opm.spec_index import iter_canonical_specs

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
MINI = FIXTURES / 'mini_schema.odd'
CUSTOM = FIXTURES / 'mini_custom.odd'
PM = FIXTURES / 'mini_pm.odd'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'


@pytest.fixture(autouse=True)
def _offline_tei(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> None:
    """Keep every test off the network and off the developer's cache.

    Two separate hazards. The urlopen stub catches a test that would download.
    Seeding the cache path catches the subtler one: a test that passes locally
    only because the real TEI artifact happens to be cached, then fails in CI
    where it is not. Pointing the cache at the mini schema also keeps
    TEI-targeting fixtures small — merging the real Guidelines would give them
    thousands of pages.
    """
    def _blocked(*_args, **_kwargs):
        raise AssertionError('tests must not download the TEI schema')

    monkeypatch.setattr('urllib.request.urlopen', _blocked)
    cached = tmp_path_factory.mktemp('tei-cache') / 'p5all.xml'
    shutil.copy(MINI, cached)
    monkeypatch.setattr('opm.odd_schema.p5all_cache_path', lambda: cached)


def test_build_document_site_from_mini_schema(tmp_path: Path) -> None:
    compiled = compile_schema(MINI)
    site = build_document_site(compiled, tmp_path / 'out', title='Mini')
    out = site.output_dir
    assert (out / 'index.html').is_file()
    assert (out / 'ref-p.html').is_file()
    assert (out / 'ref-hi.html').is_file()
    assert (out / 'ref-model.pLike.html').is_file()
    assert (out / 'ref-att.global.html').is_file()
    assert (out / 'REF-ELEMENTS.html').is_file()
    assert (out / 'idents.json').is_file()
    html = (out / 'ref-p.html').read_text(encoding='utf-8')
    assert 'Contained by' in html
    assert 'ref-div.html' in html
    assert 'May contain' in html
    assert 'ref-hi.html' in html
    assert 'ref-model.pLike.html' in html
    assert 'ref-att.global.html' in html
    assert 'marks paragraphs' in html
    # An attribute's datatype and closed value list, as the TEI Stylesheets give them.
    assert '1–∞ occurrences of' in html and 'separated by whitespace' in html
    assert '<dt>Legal values</dt>' in html
    assert '<code>italic</code></dt><dd>(cursive) ' in html
    assert '&lt;hi&gt;' in html or '>hi</a>' in html
    assert 'Processing model' in html
    assert 'paragraph' in html
    page = etree.HTML(html)
    for muted in page.xpath(
        '//div[contains(@class,"module-group")]//span[contains(@class,"muted")]'
        ' | //div[contains(@class,"spec-links")]//span[contains(@class,"muted")]'
    ):
        raise AssertionError(
            'class and grouped lists should not repeat a module label: '
            + etree.tostring(muted, encoding='unicode')
        )
    home = (out / 'index.html').read_text(encoding='utf-8')
    assert 'Elements' in home
    assert 'Mini' in home
    assert 'REF-ELEMENTS.html' in home
    assert 'doc-sidebar' in home
    # The reference list counts what each catalog holds.
    assert re.search(r'href="REF-ELEMENTS\.html">Elements</a> <span class="muted">3</span>', home)


def test_spec_only_chapters_are_written_without_their_specs(tmp_path: Path) -> None:
    """Every top-level div is a page, even one holding nothing but specs.

    p5subset wraps specs in ``div1`` skeletons. Read as a text, such a wrapper
    is a chapter with a heading and no prose: its specs are the reference
    run's pages, not part of the chapter.
    """
    src = tmp_path / 'skel.odd'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Skeleton</title></titleStmt>
                 <publicationStmt><p>t</p></publicationStmt>
                 <sourceDesc><p>t</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <div type="div1" xml:id="CO">
                 <head>Core</head>
                 <elementSpec ident="p" module="core">
                   <desc xml:lang="en">paragraph</desc>
                   <content><textNode/></content>
                 </elementSpec>
               </div>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    site = build_document_site(compile_schema(src), tmp_path / 'out')
    assert site.chapters == 1
    chapter = (site.output_dir / 'CO.html').read_text(encoding='utf-8')
    assert 'Core' in chapter
    assert 'paragraph' not in chapter[chapter.index('<main'):chapter.index('</main>')]
    assert (site.output_dir / 'ref-p.html').is_file()


def test_reference_pages_link_into_the_text(tmp_path: Path) -> None:
    """A spec's pointer into the prose lands on the chapter page that holds it.

    The text and the reference pages are two chunk runs; the reference run is
    handed the text's anchors, or ``#COPA`` would point into the spec page.
    """
    src = tmp_path / 'p5.xml'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Mini guidelines</title></titleStmt>
                 <publicationStmt><publisher>test</publisher></publicationStmt>
                 <sourceDesc><p>fixture</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <div type="div1" xml:id="CO"><head>Core</head><p>Intro.</p>
                 <div xml:id="COPA"><head>Paragraphs</head><p>About p.</p>
                   <elementSpec ident="p" module="core">
                     <desc xml:lang="en">paragraph</desc>
                     <content><textNode/></content>
                     <remarks xml:lang="en"><p>See <ptr target="#COPA"/>.</p></remarks>
                   </elementSpec>
                 </div>
               </div>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    site = build_document_site(compile_schema(src), tmp_path / 'out')
    ref = (site.output_dir / 'ref-p.html').read_text(encoding='utf-8')
    assert 'href="CO.html#COPA"' in ref
    assert 'href="#COPA"' not in ref


def test_duplicate_spec_copies_share_one_ref_page(tmp_path: Path) -> None:
    """p5subset repeats specs; each ident still gets one ``ref-*.html`` page."""
    src = tmp_path / 'dup.odd'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Dup</title></titleStmt>
                 <publicationStmt><p>t</p></publicationStmt>
                 <sourceDesc><p>t</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <schemaSpec ident="dup">
                 <elementSpec ident="p" module="core">
                   <desc xml:lang="en">from schema</desc>
                   <content><textNode/></content>
                 </elementSpec>
               </schemaSpec>
               <elementSpec ident="p" xml:id="ref-p" module="core">
                 <desc xml:lang="en">body copy</desc>
                 <content><textNode/></content>
               </elementSpec>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    compiled = compile_schema(src)
    tree = prepare_document_tree(compiled)
    # The default parser rejects duplicate xml:id (the tei_lite crash).
    etree.fromstring(etree.tostring(tree))
    xml_ids = [
        el.get('{http://www.w3.org/XML/1998/namespace}id')
        for el, _kind in iter_canonical_specs(tree)
        if el.get('ident') == 'p'
    ]
    assert xml_ids.count('ref-p') == 1
    site = build_document_site(compiled, tmp_path / 'out')
    assert (site.output_dir / 'ref-p.html').is_file()
    assert list(site.output_dir.glob('[0-9][0-9][0-9].html')) == []


def test_exemplum_keeps_mixed_content_around_element(tmp_path: Path) -> None:
    src = tmp_path / 'mixed.odd'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Mixed exemplum</title></titleStmt>
                 <publicationStmt><p>test</p></publicationStmt>
                 <sourceDesc><p>test</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <schemaSpec ident="mixed">
                 <elementSpec ident="add" module="core">
                   <desc xml:lang="en">addition</desc>
                   <content><textNode/></content>
                   <exemplum xml:lang="en">
                     <egXML xmlns="http://www.tei-c.org/ns/Examples">
                       before <add place="above">of these facts</add> after
                     </egXML>
                   </exemplum>
                 </elementSpec>
               </schemaSpec>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    compiled = compile_schema(src)
    site = build_document_site(compiled, tmp_path / 'out')
    html = (site.output_dir / 'ref-add.html').read_text(encoding='utf-8')
    assert 'before' in html
    assert 'after' in html
    assert 'of these facts' in html
    assert '&lt;add' in html


def test_customization_site_drops_deleted_element(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = compile_schema(CUSTOM)
    site = build_document_site(compiled, tmp_path / 'out')
    assert not (site.output_dir / 'ref-hi.html').exists()
    html = (site.output_dir / 'ref-p.html').read_text(encoding='utf-8')
    assert '@type' in html
    assert 'character data' in html.lower()


def test_processing_overlay_site_lists_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = compile_schema(PM)
    site = build_document_site(compiled, tmp_path / 'out')
    html = (site.output_dir / 'ref-p.html').read_text(encoding='utf-8')
    assert 'Processing model' in html
    assert 'block' in html
    assert '@rend' in html
    assert (site.output_dir / 'ref-quote.html').is_file()


def test_cli_document_mini_schema(tmp_path: Path) -> None:
    dest = tmp_path / 'site'
    assert main(['odd', 'document', str(MINI), '-o', str(dest), '--force']) == 0
    assert (dest / 'ref-p.html').is_file()
    assert (dest / 'document.css').is_file()
    assert (dest / 'tei-logo.svg').is_file()
    home = (dest / 'index.html').read_text(encoding='utf-8')
    assert 'tei-logo.svg' in home
    assert 'doc-brand__logo' in home
    # The tab icon, on every page rather than only the home page.
    icon = '<link rel="icon" href="tei-logo.svg" type="image/svg+xml">'
    assert icon in home
    assert icon in (dest / 'ref-p.html').read_text(encoding='utf-8')
    css = (dest / 'document.css').read_text(encoding='utf-8')
    assert '--doc-amber: #f7a823' in css
    assert "@import 'fonts.css'" in css
    assert 'scroll-padding-top: var(--doc-scroll-pad)' in css


def test_cli_document_default_output_uses_schema_ident(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(['odd', 'document', str(MINI), '--force']) == 0
    dest = tmp_path / 'odd' / 'mini'
    assert (dest / 'ref-p.html').is_file()
    assert (dest / 'document.css').is_file()


def test_cli_document_without_input_documents_tei(tmp_path: Path, monkeypatch) -> None:
    """No SOURCE, outside a documentation project: the TEI Guidelines."""
    import opm.odd_schema as odd_schema

    calls = []

    def fake_compile(source=None, *, use_guidelines=False, **kwargs):
        calls.append((source, use_guidelines))
        raise odd_schema.SchemaError('stop here')

    monkeypatch.setattr(odd_schema, 'compile_schema', fake_compile)
    monkeypatch.chdir(tmp_path)
    assert main(['odd', 'document']) == 1
    assert main(['odd', 'prepare']) == 1
    assert calls == [(None, True), (None, True)]


def test_guidelines_chapters_are_written(tmp_path: Path) -> None:
    src = tmp_path / 'p5.xml'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Mini guidelines</title></titleStmt>
                 <publicationStmt><publisher>test</publisher></publicationStmt>
                 <sourceDesc><p>fixture</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text>
               <front>
                 <titlePage>
                   <docTitle>
                     <titlePart type="main">Mini guidelines</titlePart>
                     <titlePart type="sub">A short fixture</titlePart>
                   </docTitle>
                   <docAuthor>Test Author</docAuthor>
                   <docDate>2026</docDate>
                 </titlePage>
               </front>
               <body>
                 <p>This document introduces the fixture schema.</p>
                 <div type="div1" xml:id="CO">
                   <head>Core</head>
                   <p>See <gi>p</gi> and section <ptr target="#NOTES"/>.</p>
                   <p>Example:
                     <egXML xmlns="http://www.tei-c.org/ns/Examples"><p>Hi</p></egXML>
                   </p>
                   <specList>
                     <specDesc key="p"/>
                     <specDesc key="hi"/>
                   </specList>
                   <div xml:id="CO-sub">
                     <head>Subsections</head>
                     <p>Nested.</p>
                   </div>
                 </div>
                 <div type="div1" xml:id="NOTES">
                   <head>Notes</head>
                   <p>More.</p>
                 </div>
                 <elementSpec ident="hi" module="core">
                   <gloss xml:lang="en">highlighted</gloss>
                   <desc xml:lang="en">marks a word or phrase as graphically distinct.</desc>
                   <content><textNode/></content>
                 </elementSpec>
                 <elementSpec ident="p" module="core">
                   <gloss xml:lang="en">paragraph</gloss>
                   <desc xml:lang="en">marks paragraphs in prose.</desc>
                   <listRef><ptr target="#COPA"/></listRef>
                   <content><textNode/></content>
                   <exemplum xml:lang="en">
                     <egXML xmlns="http://www.tei-c.org/ns/Examples"><p>one</p></egXML>
                   </exemplum>
                   <exemplum xml:lang="en">
                     <egXML xmlns="http://www.tei-c.org/ns/Examples"><p>two</p></egXML>
                   </exemplum>
                 </elementSpec>
               </body>
             </text>
           </TEI>''',
        encoding='utf-8',
    )
    compiled = compile_schema(src)
    site = build_document_site(compiled, tmp_path / 'out')
    assert site.chapters == 3
    assert (site.output_dir / 'Title.html').is_file()
    chapter = (site.output_dir / 'CO.html').read_text(encoding='utf-8')
    assert 'class="chapter-nav"' in chapter
    assert re.search(r'class="chapter-nav__prev"[^>]*href="Title\.html"', chapter)
    assert re.search(r'class="chapter-nav__next"[^>]*href="NOTES\.html"', chapter)
    title_page = (site.output_dir / 'Title.html').read_text(encoding='utf-8')
    assert re.search(r'class="chapter-nav__next"[^>]*href="CO\.html"', title_page)
    assert re.search(r'class="chapter-nav__prev"[^>]*href=""', title_page)
    notes = (site.output_dir / 'NOTES.html').read_text(encoding='utf-8')
    assert re.search(r'class="chapter-nav__prev"[^>]*href="CO\.html"', notes)
    # The A–Z catalogs close the text as its appendices, so the sequence runs
    # on into them and ends on the last one.
    assert re.search(r'class="chapter-nav__next"[^>]*href="REF-ELEMENTS\.html"', notes)
    last = (site.output_dir / 'REF-ATTS.html').read_text(encoding='utf-8')
    assert re.search(r'class="chapter-nav__next"[^>]*href=""', last)
    assert 'Core' in chapter
    assert 'ref-p.html' in chapter
    assert 'egXML' in chapter
    assert 'class="nt"' in chapter
    assert 'Hi' in chapter
    assert '<egxml' not in chapter.lower()
    assert 'Notes' in chapter  # ptr label from target heading
    assert 'NOTES.html' in chapter
    assert 'id="CO-sub"' in chapter
    assert 'specList' in chapter
    assert 'specList-elementSpec' in chapter
    assert '(paragraph)' in chapter
    assert 'marks paragraphs in prose.' in chapter
    assert '(highlighted)' in chapter
    assert 'marks a word or phrase as graphically distinct.' in chapter
    assert re.search(r'<a class="[^"]*\bgi\b[^"]*" href="ref-p\.html">p</a>', chapter)
    home = (site.output_dir / 'index.html').read_text(encoding='utf-8')
    assert 'CO.html#CO-sub' in home
    assert 'Subsections' in home
    assert 'This document introduces the fixture schema.' in home
    assert 'A short fixture' in home
    assert 'Test Author' in home
    assert 'Front Matter' in home
    assert 'Text Body' in home
    assert 'Title.html' in home
    ref = (site.output_dir / 'ref-p.html').read_text(encoding='utf-8')
    # Both exempla land in the one Examples section.
    assert ref.count('<h2>Examples</h2>') == 1
    examples = re.search(
        r'<section class="spec-section" id="ref-examples">.*?</section>', ref, re.DOTALL,
    )
    assert examples
    shown = re.sub(r'<[^>]+>', '', examples.group(0))
    assert 'one' in shown and 'two' in shown
    assert 'tei-c.org/release/doc/tei-p5-doc' in ref
    assert 'CO.html#COPA' in ref
    assert 'chapter-nav' not in ref
    assert site.unsupported == []


def test_chapter_nav_sits_after_the_chapter_and_in_the_rail(tmp_path: Path) -> None:
    """Both placements from the design: end-of-chapter cards, plus the rail pair.

    The rail copy is the per-chunk ``chapternav`` fragment, so it lands inside
    the on-this-page aside rather than in the chapter body, and body chapters
    carry their position as a number.
    """
    src = tmp_path / 'p5.xml'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Mini guidelines</title></titleStmt>
                 <publicationStmt><publisher>test</publisher></publicationStmt>
                 <sourceDesc><p>fixture</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text>
               <front>
                 <div type="div1" xml:id="AB"><head>About</head><p>Front prose.</p></div>
               </front>
               <body>
                 <div type="div1" xml:id="IN"><head>Infrastructure</head><p>One.</p></div>
                 <div type="div1" xml:id="HD"><head>The TEI Header</head><p>Two.</p></div>
                 <div type="div1" xml:id="CO"><head>Core</head><p>Three.</p></div>
                 <div type="div1" xml:id="DS"><head>Default Text Structure</head><p>Four.</p></div>
               </body>
             </text>
           </TEI>''',
        encoding='utf-8',
    )
    site = build_document_site(compile_schema(src), tmp_path / 'out')
    chapter = (site.output_dir / 'CO.html').read_text(encoding='utf-8')

    # Nothing above the chapter; the card pair closes it.
    body = chapter[chapter.index('<main'):chapter.index('</main>')]
    assert body.index('<article class="doc-chapter"') < body.index('class="chapter-nav"')
    assert 'chapter-nav' not in body[: body.index('<article')]
    # The cards sit outside the chapter, which is what keeps appended footnotes
    # inside it rather than in the card grid.
    assert body.index('</article>') < body.index('class="chapter-nav"')

    # The rail copy lives in the aside, not in the chapter body.
    aside = chapter[chapter.index('<aside class="doc-aside"'):]
    assert 'class="chapter-nav chapter-nav--rail"' in aside
    assert 'chapter-nav--rail' not in body

    # Chapters carry the same outline label as their heading: arabic in the
    # body, lowercase roman in the front matter.
    assert re.search(
        r'class="chapter-nav__num">2</span>The TEI Header', chapter
    )
    assert re.search(
        r'class="chapter-nav__num">4</span>Default Text Structure', chapter
    )
    first = (site.output_dir / 'IN.html').read_text(encoding='utf-8')
    assert re.search(r'class="chapter-nav__num">i\.</span>About', first)


def test_headings_carry_guidelines_outline_numbers(tmp_path: Path) -> None:
    """Numbering follows the published Guidelines: arabic body, roman front, lettered back.

    The index at each level counts sibling divs, so the title page and the
    pages the site injects itself (home, the A-Z catalogs) do not shift it.
    """
    src = tmp_path / 'p5.xml'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Mini guidelines</title></titleStmt>
                 <publicationStmt><publisher>test</publisher></publicationStmt>
                 <sourceDesc><p>fixture</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text>
               <front>
                 <titlePage><docTitle><titlePart>Mini</titlePart></docTitle></titlePage>
                 <div xml:id="TPV"><head>Releases</head><p>Front prose.</p></div>
                 <div xml:id="AB"><head>About</head><p>More front prose.</p>
                   <div xml:id="ABC"><head>Conventions</head><p>Deeper.</p></div>
                 </div>
               </front>
               <body>
                 <div xml:id="IN"><head>Infrastructure</head><p>One.</p>
                   <div xml:id="INA"><head>Modules</head><p>Two.</p>
                     <div xml:id="INAB"><head>Classes</head><p>Three.</p></div>
                   </div>
                 </div>
                 <div xml:id="HD"><head>The TEI Header</head><p>Four.</p></div>
               </body>
               <back>
                 <div xml:id="BIB"><head>Bibliography</head><p>Works cited.</p></div>
               </back>
             </text>
           </TEI>''',
        encoding='utf-8',
    )
    site = build_document_site(compile_schema(src), tmp_path / 'out')

    def heading(page: str, level: str) -> str:
        html = (site.output_dir / page).read_text(encoding='utf-8')
        match = re.search(rf'<{level}[^>]*>(.*?)</{level}>', html, re.S)
        assert match, f'no {level} in {page}'
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', match.group(1))).strip()

    # Body chapters are arabic and start at 1: the injected home page is not
    # a division of the text. A chapter's own label opens the page spelled out.
    assert heading('IN.html', 'h1') == 'Chapter 1 Infrastructure'
    assert heading('IN.html', 'h2') == '1.1 Modules'
    assert heading('IN.html', 'h3') == '1.1.1 Classes'
    assert heading('HD.html', 'h1') == 'Chapter 2 The TEI Header'
    # Front matter is roman with a trailing dot (spelled out on the page's own
    # heading), and the title page is skipped.
    assert heading('TPV.html', 'h1') == 'Front matter i Releases'
    assert heading('AB.html', 'h1') == 'Front matter ii About'
    assert heading('AB.html', 'h2') == 'ii.1. Conventions'
    # Back matter is lettered, after the five catalog appendices.
    assert heading('BIB.html', 'h1') == 'Appendix F Bibliography'
    assert heading('REF-ELEMENTS.html', 'h1') == 'Appendix A Elements'
    # The home page lists the same labels, and carries none itself.
    home = (site.output_dir / 'index.html').read_text(encoding='utf-8')
    assert re.search(r'heading-number">1 </span><a[^>]*href="IN.html"', home)
    assert re.search(r'heading-number">1\.1 </span><a[^>]*href="IN.html#INA"', home)
    assert heading('index.html', 'h1') == 'Mini guidelines'


def test_chapter_footnotes_and_modulespec(tmp_path: Path) -> None:
    """Footnotes close the chapter prose, above the nav; a moduleSpec is one chip.

    The runtime appends footnote ``dl``s to the chunk's last root element, so
    the chapter body has to be that element. A ``moduleSpec`` without a model
    spills its FPI idno and every translated ``desc`` into the running text.
    """
    src = tmp_path / 'p5.xml'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Mini guidelines</title></titleStmt>
                 <publicationStmt><publisher>test</publisher></publicationStmt>
                 <sourceDesc><p>fixture</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text>
               <body>
                 <div type="div1" xml:id="VE">
                   <head>Verse</head>
                   <p>Verse structures<note place="foot">A note on verse.</note> are
                     described here.</p>
                   <moduleSpec xml:id="DVE" ident="verse">
                     <idno type="FPI">Verse</idno>
                     <desc xml:lang="en" versionDate="2006-09-13">Verse structures</desc>
                     <desc xml:lang="fr" versionDate="2018-07-12">Poésie</desc>
                     <desc xml:lang="ja" versionDate="2018-07-12">韻文モジュール</desc>
                   </moduleSpec>
                 </div>
                 <div type="div1" xml:id="NEXT"><head>Next</head><p>More.</p></div>
               </body>
             </text>
           </TEI>''',
        encoding='utf-8',
    )
    site = build_document_site(compile_schema(src), tmp_path / 'out')
    page = (site.output_dir / 'VE.html').read_text(encoding='utf-8')

    # One footnote, inside the chapter, ahead of the previous/next cards.
    assert page.count('class="footnote"') == 1
    assert page.index('class="footnote"') < page.index('</article>')
    assert page.index('</article>') < page.index('class="chapter-nav"')

    # The moduleSpec is a single chip in the active language.
    assert '<strong>verse</strong>' in page
    assert 'Verse structures' in page
    assert 'Poésie' not in page
    assert '韻文モジュール' not in page
    assert 'tei-idno' not in page


def test_gloss_list_term_is_not_printed_twice(tmp_path: Path) -> None:
    """The list behaviour pairs label+item into dt/dd from the source siblings.

    Applying the labels as list children as well printed every term a second
    time, loose inside the ``dl`` and ahead of its own ``dt``.
    """
    src = tmp_path / 'p5.xml'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Mini guidelines</title></titleStmt>
                 <publicationStmt><publisher>test</publisher></publicationStmt>
                 <sourceDesc><p>fixture</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text>
               <body>
                 <div type="div1" xml:id="CL">
                   <head>Classifications</head>
                   <p>Elements fall into these groupings:</p>
                   <list type="gloss">
                     <label><term>divisions</term></label>
                     <item>major divisions of texts.</item>
                     <label><term>chunks</term></label>
                     <item>paragraph-level elements.</item>
                   </list>
                 </div>
               </body>
             </text>
           </TEI>''',
        encoding='utf-8',
    )
    site = build_document_site(compile_schema(src), tmp_path / 'out')
    page = (site.output_dir / 'CL.html').read_text(encoding='utf-8')

    assert page.count('>divisions<') == 1
    assert page.count('>chunks<') == 1
    assert page.count('<dt') == 2
    assert page.count('<dd') == 2


def test_front_and_back_matter_are_grouped_on_home(tmp_path: Path) -> None:
    """Guidelines front/back stay in those parts and appear under TOC headings.

    Dedication and the title-page verso use typed ``div``s (not ``div1``);
    the verso is a ``list`` with no ``p``. Schema-dump appendices whose
    ``xml:id`` matches a catalog stay as our catalog pages.
    """
    src = tmp_path / 'guidelines.xml'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Full guidelines fixture</title></titleStmt>
                 <publicationStmt><publisher>test</publisher></publicationStmt>
                 <sourceDesc><p>fixture</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text>
               <front>
                 <titlePage>
                   <docTitle><titlePart type="main">Guidelines</titlePart></docTitle>
                 </titlePage>
                 <div type="titlePageVerso" xml:id="TitlePageVerso">
                   <head>Releases of the TEI Guidelines</head>
                   <list><item>4.9.0</item></list>
                 </div>
                 <div type="Dedication" xml:id="dedication">
                   <head>Dedication</head>
                   <p>In memoriam.</p>
                 </div>
                 <div xml:id="FM1">
                   <head>Preface and Acknowledgments</head>
                   <p>Since Vassar.</p>
                 </div>
               </front>
               <body>
                 <div type="div1" xml:id="ST">
                   <head>The TEI Infrastructure</head>
                   <p>Modules.</p>
                 </div>
               </body>
               <back>
                 <div type="div1" xml:id="REF-ELEMENTS">
                   <head>Elements</head>
                   <p>Dump of every elementSpec.</p>
                   <elementSpec ident="p" module="core">
                     <desc xml:lang="en">paragraph</desc>
                     <content><textNode/></content>
                   </elementSpec>
                 </div>
                 <div xml:id="BIB">
                   <head>Bibliography</head>
                   <p>Works cited.</p>
                 </div>
               </back>
             </text>
           </TEI>''',
        encoding='utf-8',
    )
    compiled = compile_schema(src)
    tree = prepare_document_tree(compiled)
    front = {
        child.get('{http://www.w3.org/XML/1998/namespace}id')
        for child in tree.find('.//{http://www.tei-c.org/ns/1.0}front')
        if child.tag.endswith('div')
    }
    body_ids = {
        child.get('{http://www.w3.org/XML/1998/namespace}id')
        for child in tree.find('.//{http://www.tei-c.org/ns/1.0}body')
        if child.tag.endswith('div')
    }
    back_ids = {
        child.get('{http://www.w3.org/XML/1998/namespace}id')
        for child in tree.find('.//{http://www.tei-c.org/ns/1.0}back')
        if child.tag.endswith('div')
    }
    assert {'Title', 'TitlePageVerso', 'dedication', 'FM1'} <= front
    assert 'ST' in body_ids
    assert 'dedication' not in body_ids
    assert 'BIB' in back_ids
    # The Guidelines' own elementSpec dump is dropped; our catalog stub stands
    # in its place, in the back matter and ahead of the remaining appendices.
    assert 'REF-ELEMENTS' in back_ids
    assert 'REF-ELEMENTS' not in body_ids
    back = tree.find('.//{http://www.tei-c.org/ns/1.0}back')
    stub = back[0]
    assert stub.get('{http://www.w3.org/XML/1998/namespace}id') == 'REF-ELEMENTS'
    assert stub.get('subtype') == 'elements'
    assert not stub.findall('.//{http://www.tei-c.org/ns/1.0}elementSpec')

    site = build_document_site(compiled, tmp_path / 'out')
    home = (site.output_dir / 'index.html').read_text(encoding='utf-8')
    assert 'Front Matter' in home
    assert 'Text Body' in home
    assert 'Back Matter' in home
    assert 'Title.html' in home
    assert 'TitlePageVerso.html' in home
    assert 'dedication.html' in home
    assert 'FM1.html' in home
    assert 'ST.html' in home
    assert 'BIB.html' in home
    assert 'In memoriam' in (site.output_dir / 'dedication.html').read_text(
        encoding='utf-8',
    )
    assert '4.9.0' in (site.output_dir / 'TitlePageVerso.html').read_text(
        encoding='utf-8',
    )
    catalog = (site.output_dir / 'REF-ELEMENTS.html').read_text(encoding='utf-8')
    assert 'class="catalog"' in catalog
    assert 'Dump of every elementSpec' not in catalog
    # The catalogs are back-matter appendices, so they sit in the chapter
    # sequence: the last body chapter leads on to the first of them.
    assert re.search(r'class="chapter-nav__prev"[^>]*href="ST\.html"', catalog)
    st = (site.output_dir / 'ST.html').read_text(encoding='utf-8')
    assert re.search(r'class="chapter-nav__prev"[^>]*href="FM1\.html"', st)
    assert re.search(r'class="chapter-nav__next"[^>]*href="REF-ELEMENTS\.html"', st)
    # The home page is no chapter: no prev/next of its own.
    assert 'chapter-nav' not in home

    # Preparing the tree leaves the author's @type alone and adds no mark of
    # its own: which pages a div makes is read off where it sits.
    types = {div.get(XML_ID): div.get('type') for div in iter_guideline_chapters(tree)}
    assert types['dedication'] == 'Dedication'
    assert types['TitlePageVerso'] == 'titlePageVerso'
    assert types['ST'] == 'div1'
    assert not any(
        '{http://teipublisher.com/opm/1.0}' in key
        for el in tree.iter() if isinstance(el.tag, str) for key in el.attrib
    )
    home_div = tree.find('.//{http://www.tei-c.org/ns/1.0}div[@{http://www.w3.org/XML/1998/namespace}id="index"]')
    assert home_div is not None and home_div.getparent().tag.endswith('}text')


def test_unsupported_expressions_in_own_odd_are_reported(tmp_path: Path) -> None:
    """An expression opm cannot evaluate renders empty — it must not do so silently.

    Only the documentation ODD's own expressions count: it customizes
    teipublisher.odd, whose eXist calls are inherited and never reached.
    """
    odd = tmp_path / 'tampered.odd'
    packaged = Path(packaged_odd('tagdocs')).read_text(encoding='utf-8')
    odd.write_text(
        packaged.replace(
            "(@rend, local-name(id(concat('ref-', @key))), 'elementSpec')[1]",
            'current()',
        ),
        encoding='utf-8',
    )

    site = build_document_site(compile_schema(MINI), tmp_path / 'out', odd=odd)
    reasons = {(e['element'], e['where'], e['reason']) for e in site.unsupported}
    assert reasons == {('specDesc', 'param rend', 'unknown function current()')}


def test_eg_element_renders_as_source_block(tmp_path: Path) -> None:
    src = tmp_path / 'eg.odd'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Eg sample</title></titleStmt>
                 <publicationStmt><publisher>test</publisher></publicationStmt>
                 <sourceDesc><p>fixture</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <div type="div1" xml:id="EX">
                 <head>Example</head>
                 <p>Plain text sample:
                   <eg xml:space="preserve">
            CHAPTER 38
            READER, I married him.
                   </eg>
                 </p>
               </div>
               <schemaSpec ident="egsample">
                 <elementSpec ident="p" module="core">
                   <desc xml:lang="en">paragraph</desc>
                   <content><textNode/></content>
                 </elementSpec>
               </schemaSpec>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    site = build_document_site(compile_schema(src), tmp_path / 'out')
    html = (site.output_dir / 'EX.html').read_text(encoding='utf-8')
    assert '<pre' in html
    assert 'eg' in html
    assert 'CHAPTER 38' in html
    assert 'READER, I married him.' in html
    # Example body lives inside <code>, not as bare paragraph text only.
    assert '<code>' in html
    code_start = html.index('<code>')
    assert 'CHAPTER 38' in html[code_start:code_start + 200]


def test_tei_publishes_the_artifact_chapters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Documenting TEI itself, so the artifact's chapters are the site's."""
    artifact = tmp_path / 'p5all.xml'
    artifact.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
           <TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>TEI</title></titleStmt>
                 <publicationStmt><publisher>TEI</publisher></publicationStmt>
                 <sourceDesc><p>fixture</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <div type="div1" xml:id="CO">
                 <head>Core</head>
                 <p>Elements common to all documents.</p>
               </div>
               <elementSpec ident="p" module="core">
                 <desc xml:lang="en">marks paragraphs.</desc>
                 <content><textNode/></content>
               </elementSpec>
               <elementSpec ident="hi" module="core">
                 <desc xml:lang="en">highlighted</desc>
                 <content><textNode/></content>
               </elementSpec>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    monkeypatch.setattr('opm.odd_schema.ensure_p5all', lambda **_kwargs: artifact)

    tei = compile_schema(use_guidelines=True)
    assert chapters_have_prose(tei.tree)
    site = build_document_site(tei, tmp_path / 'tei-out')
    assert site.chapters == 1
    assert (site.output_dir / 'CO.html').is_file()


def test_customization_does_not_inherit_tei_chapters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A customization documents itself, not all of TEI.

    The artifact always carries the Guidelines now, so this is the rule that
    keeps 39 TEI chapters out of a project's own site.
    """
    artifact = tmp_path / 'p5all.xml'
    artifact.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
           <TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>TEI</title></titleStmt>
                 <publicationStmt><publisher>TEI</publisher></publicationStmt>
                 <sourceDesc><p>fixture</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <div type="div1" xml:id="CO">
                 <head>Core</head>
                 <p>Elements common to all documents.</p>
               </div>
               <elementSpec ident="p" module="core">
                 <desc xml:lang="en">marks paragraphs.</desc>
                 <content><textNode/></content>
               </elementSpec>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    monkeypatch.setattr('opm.odd_schema.ensure_p5all', lambda **_kwargs: artifact)

    custom = tmp_path / 'custom.odd'
    custom.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
           <TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Custom</title></titleStmt>
                 <publicationStmt><p>t</p></publicationStmt>
                 <sourceDesc><p>t</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <schemaSpec ident="custom">
                 <elementSpec ident="p" mode="change">
                   <model behaviour="paragraph"/>
                 </elementSpec>
               </schemaSpec>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    compiled = compile_schema(custom)
    assert not chapters_have_prose(compiled.tree)
    site = build_document_site(compiled, tmp_path / 'custom-out')
    assert site.chapters == 0
    assert not (site.output_dir / 'CO.html').exists()
    # The schema itself still merged: the customization's model came through.
    assert (site.output_dir / 'ref-p.html').is_file()


_LIST_REF_ARTIFACT = '''<?xml version="1.0" encoding="UTF-8"?>
   <TEI xmlns="http://www.tei-c.org/ns/1.0">
     <teiHeader>
       <fileDesc>
         <titleStmt><title>TEI</title></titleStmt>
         <publicationStmt><publisher>TEI</publisher></publicationStmt>
         <sourceDesc><p>fixture</p></sourceDesc>
       </fileDesc>
     </teiHeader>
     <text><body>
       <div type="div1" xml:id="CO">
         <head>Core</head>
         <p>Elements common to all documents.</p>
         <div xml:id="COEDADD"><head>Additions</head><p>Prose.</p></div>
       </div>
       <elementSpec ident="p" module="core">
         <desc xml:lang="en">marks paragraphs.</desc>
         <content><textNode/></content>
         <listRef><ptr target="#COEDADD"/></listRef>
       </elementSpec>
     </body></text>
   </TEI>'''


def test_list_ref_links_to_the_local_chapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With the chapters published, a listRef stays inside the site."""
    artifact = tmp_path / 'p5all.xml'
    artifact.write_text(_LIST_REF_ARTIFACT, encoding='utf-8')
    monkeypatch.setattr('opm.odd_schema.ensure_p5all', lambda **_kwargs: artifact)

    site = build_document_site(compile_schema(use_guidelines=True), tmp_path / 'out')
    html = (site.output_dir / 'ref-p.html').read_text(encoding='utf-8')
    assert '<a class="spec__chip" href="CO.html#COEDADD">COEDADD</a>' in html
    assert 'tei-c.org/release' not in html
    assert 'id="COEDADD"' in (site.output_dir / 'CO.html').read_text(encoding='utf-8')


def test_list_ref_falls_back_to_the_published_guidelines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A customization publishes no chapters, so the chip leaves the site.

    The label is a plain string: rendering the ``ref`` itself would nest an
    ``<a>`` inside the chip's anchor, which browsers split into two links.
    """
    artifact = tmp_path / 'p5all.xml'
    artifact.write_text(_LIST_REF_ARTIFACT, encoding='utf-8')
    monkeypatch.setattr('opm.odd_schema.ensure_p5all', lambda **_kwargs: artifact)

    custom = tmp_path / 'custom.odd'
    custom.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
           <TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Custom</title></titleStmt>
                 <publicationStmt><p>t</p></publicationStmt>
                 <sourceDesc><p>t</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <schemaSpec ident="custom">
                 <elementSpec ident="p" mode="change">
                   <model behaviour="paragraph"/>
                 </elementSpec>
               </schemaSpec>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    site = build_document_site(compile_schema(custom), tmp_path / 'out')
    html = (site.output_dir / 'ref-p.html').read_text(encoding='utf-8')
    assert (
        '<a class="spec__chip" '
        'href="https://www.tei-c.org/release/doc/tei-p5-doc/en/html/CO.html#COEDADD" '
        'rel="external">COEDADD</a>'
    ) in html


def test_document_site_ships_self_hosted_fonts(tmp_path: Path) -> None:
    compiled = compile_schema(MINI)
    site = build_document_site(compiled, tmp_path / 'out')
    out = site.output_dir
    assert (out / 'fonts.css').is_file()
    assert (out / 'theme.js').is_file()
    faces = sorted(p.name for p in (out / 'fonts').glob('*.woff2'))
    assert faces, 'no webfonts copied'
    fonts_css = (out / 'fonts.css').read_text(encoding='utf-8')
    for face in faces:
        assert f"url('fonts/{face}')" in fonts_css
    # Every @font-face src resolves to a file that was actually copied.
    for ref in re.findall(r"url\('fonts/([^']+)'\)", fonts_css):
        assert (out / 'fonts' / ref).is_file(), ref
    page = (out / 'ref-p.html').read_text(encoding='utf-8')
    assert 'theme.js' in page
    assert 'data-doc-theme' in page
    assert 'doc-theme__moon' in page
    assert 'doc-theme__sun' in page
    assert '>Dark</button>' not in page


def test_reference_page_toc_targets_exist(tmp_path: Path) -> None:
    """Spec sections that the on-this-page rail (filled in the browser) lists are present."""
    compiled = compile_schema(MINI)
    site = build_document_site(compiled, tmp_path / 'out')
    html = (site.output_dir / 'ref-p.html').read_text(encoding='utf-8')
    assert 'class="doc-aside"' in html
    assert 'id="ref-attributes"' in html
    assert 'id="ref-classes"' in html
    assert 'id="ref-models"' in html
    # The entries the rail nests under those two: the attributes the spec
    # defines itself, and each class / content relation.
    assert '<dt id="att-rend">' in html
    for anchor in ('ref-memberOf', 'ref-mayContain', 'ref-containedBy'):
        assert f'<dt id="{anchor}">' in html
    klass = (site.output_dir / 'ref-model.phrase.html').read_text(encoding='utf-8')
    assert '<dt id="ref-usedBy">' in klass
    assert '<dt id="ref-members">' in klass


def test_header_carries_edition_and_licence(tmp_path: Path) -> None:
    src = tmp_path / 'edition.odd'
    src.write_text(
        '''<TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Edition test</title></titleStmt>
                 <editionStmt>
                   <edition>P5 <ref target="#x">Version</ref> 4.12.0. Last updated on
                     <date when="2026-07-28">28th July 2026</date>, revision abc</edition>
                 </editionStmt>
                 <publicationStmt>
                   <availability><licence>Distributed under CC BY 4.0.</licence></availability>
                 </publicationStmt>
                 <sourceDesc><p>test</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <schemaSpec ident="edition">
                 <moduleSpec ident="core"><desc>Core elements.</desc></moduleSpec>
                 <elementSpec ident="p" module="core">
                   <desc xml:lang="en">paragraph</desc>
                   <content><textNode/></content>
                 </elementSpec>
               </schemaSpec>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    compiled = compile_schema(src)
    site = build_document_site(compiled, tmp_path / 'out')
    html = (site.output_dir / 'ref-p.html').read_text(encoding='utf-8')
    assert 'P5 Version 4.12.0 · 28th July 2026' in html
    assert 'Distributed under CC BY 4.0.' in html


def test_sidebar_marks_the_current_page(tmp_path: Path) -> None:
    compiled = compile_schema(MINI)
    site = build_document_site(compiled, tmp_path / 'out')
    catalog = (site.output_dir / 'REF-ELEMENTS.html').read_text(encoding='utf-8')
    assert 'href="REF-ELEMENTS.html" aria-current="page"' in catalog
    # A page that is not in the sidebar marks nothing.
    assert 'aria-current' not in (site.output_dir / 'ref-p.html').read_text(encoding='utf-8')


def _unnumbered_chapters_odd(tmp_path: Path, *, extra_first: str = '') -> Path:
    """Fixture whose chapters carry headings but no ``xml:id``."""
    src = tmp_path / f'chapters{len(extra_first)}.odd'
    src.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
           <TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Handbook</title></titleStmt>
                 <publicationStmt><p>t</p></publicationStmt>
                 <sourceDesc><p>t</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <schemaSpec ident="handbook">
                 <elementSpec ident="p" module="core">
                   <desc xml:lang="en">paragraph</desc>
                   <content><textNode/></content>
                 </elementSpec>
               </schemaSpec>
               {extra_first}
               <div><head>Encoding Names</head><p>One.</p>
                 <div><head>Sub Section</head><p>Nested.</p></div>
               </div>
               <div><head>Épreuves &amp; Proofs</head><p>Two.</p></div>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    return src


def test_chapter_ids_come_from_headings(tmp_path: Path) -> None:
    compiled = compile_schema(_unnumbered_chapters_odd(tmp_path))
    tree = prepare_document_tree(compiled)
    ids = [
        div.get(XML_ID) for div in iter_guideline_chapters(tree)
        if div.get(XML_ID) not in _CATALOG_IDS
    ]
    assert ids == ['encoding-names', 'epreuves-proofs']
    nested = next(
        div for div in iter_guideline_chapters(tree)
        if div.get(XML_ID) == 'encoding-names'
    )
    assert [d.get(XML_ID) for d in nested if d.tag.endswith('div')] == [
        'encoding-names-sub-section',
    ]


def test_chapter_ids_survive_an_inserted_chapter(tmp_path: Path) -> None:
    """Inserting a chapter must not renumber the URLs of the ones after it."""
    def ids_for(src: Path) -> dict[str, str]:
        tree = prepare_document_tree(compile_schema(src))
        return {
            _chapter_head(div): div.get(XML_ID)
            for div in iter_guideline_chapters(tree)
            if div.get(XML_ID) not in _CATALOG_IDS
        }

    before = ids_for(_unnumbered_chapters_odd(tmp_path))
    after = ids_for(
        _unnumbered_chapters_odd(
            tmp_path, extra_first='<div><head>Brand New</head><p>Zero.</p></div>',
        ),
    )
    assert before['Encoding Names'] == after['Encoding Names']
    assert before['Épreuves & Proofs'] == after['Épreuves & Proofs']
    assert after['Brand New'] == 'brand-new'


def test_chapter_ids_do_not_collide(tmp_path: Path) -> None:
    src = tmp_path / 'dupes.odd'
    src.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
           <TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Dupes</title></titleStmt>
                 <publicationStmt><p>t</p></publicationStmt>
                 <sourceDesc><p>t</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <schemaSpec ident="dupes">
                 <elementSpec ident="p" module="core">
                   <desc xml:lang="en">paragraph</desc>
                   <content><textNode/></content>
                 </elementSpec>
               </schemaSpec>
               <div><head>Elements</head><p>One.</p></div>
               <div><head>Elements</head><p>Two.</p></div>
               <div><head>12 Numbers</head><p>Three.</p></div>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    tree = prepare_document_tree(compile_schema(src))
    ids = [
        div.get(XML_ID) for div in iter_guideline_chapters(tree)
        if div.get(XML_ID) not in _CATALOG_IDS
    ]
    assert ids == ['elements', 'elements-2', 'chapter-12-numbers']
    assert len(ids) == len(set(ids))
    # REF-ELEMENTS is injected after this runs, so it must still be free.
    assert 'REF-ELEMENTS' not in ids


def _chapter_head(div: etree._Element) -> str:
    """The heading text, without the outline number prepare puts in front."""
    for child in div:
        if child.tag.endswith('head'):
            text = [child.text or ''] + [
                ('' if el.get('type') == 'headingNumber' else ''.join(el.itertext())) + (el.tail or '')
                for el in child
            ]
            return ' '.join(''.join(text).split())
    return ''


def test_non_spec_element_yields_its_ref_id_to_the_spec(tmp_path: Path) -> None:
    """A figure already holding ``ref-faith`` must not collide with the spec.

    The TEI Guidelines really do this, and two elements sharing an ``xml:id``
    means two chunks claiming ``ref-faith.html``.
    """
    src = tmp_path / 'clash.odd'
    src.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
           <TEI xmlns="http://www.tei-c.org/ns/1.0">
             <teiHeader>
               <fileDesc>
                 <titleStmt><title>Clash</title></titleStmt>
                 <publicationStmt><p>t</p></publicationStmt>
                 <sourceDesc><p>t</p></sourceDesc>
               </fileDesc>
             </teiHeader>
             <text><body>
               <div xml:id="NM">
                 <head>Names</head>
                 <p>See <ptr target="#ref-faith"/> below.</p>
                 <figure xml:id="ref-faith"><head>A figure</head></figure>
               </div>
               <schemaSpec ident="clash">
                 <elementSpec ident="faith" module="namesdates">
                   <desc xml:lang="en">a faith</desc>
                   <content><textNode/></content>
                 </elementSpec>
               </schemaSpec>
             </body></text>
           </TEI>''',
        encoding='utf-8',
    )
    tree = prepare_document_tree(compile_schema(src))
    by_id: dict[str, list[str]] = {}
    for el in tree.iter():
        if el.get(XML_ID):
            by_id.setdefault(el.get(XML_ID), []).append(
                etree.QName(el).localname,
            )
    assert by_id['ref-faith'] == ['elementSpec']
    assert by_id['ref-faith-figure'] == ['figure']
    assert not [i for i, tags in by_id.items() if len(tags) > 1], 'duplicate xml:id'
    # The pointer follows the element it was aimed at.
    targets = [
        el.get('target') for el in tree.iter()
        if el.get('target', '').startswith('#ref-faith')
    ]
    assert targets == ['#ref-faith-figure']


def test_a_plain_chunk_run_needs_no_spec_index(tmp_path: Path, monkeypatch) -> None:
    """The prepared tree holds everything the pages show, so rendering it
    never builds a SpecIndex."""
    from dataclasses import replace

    from opm.chunking import chunk_document
    from opm.config import load_project_config
    from opm.document_site import _TAGDOCS_XPATH_EXTENSIONS
    from opm.resources import packaged_document_dir
    from opm.spec_index import SpecIndex

    xml = tmp_path / 'schema.xml'
    xml.write_bytes(etree.tostring(prepare_document_tree(compile_schema(MINI))))
    built = []
    original = SpecIndex.from_tree.__func__

    def counting(cls, root, **kwargs):
        built.append(root)
        return original(cls, root, **kwargs)

    monkeypatch.setattr(SpecIndex, 'from_tree', classmethod(counting))

    cfg = load_project_config(packaged_document_dir() / 'opm.toml')
    reference = next(run for run in cfg.chunking_runs if run.name == 'reference')
    out = tmp_path / 'out'
    chunk_document(
        module_path=None,
        xml_path=xml,
        config=replace(reference, output_dir='.'),
        project_root=out,
        template_path=reference.template,
        project_config=cfg,
        xpath_extensions=_TAGDOCS_XPATH_EXTENSIONS,
    )

    pages = list(out.glob('ref-*.html'))
    assert len(pages) > 1
    assert built == []
    assert 'ref-hi.html' in (out / 'ref-p.html').read_text(encoding='utf-8')


# ── documentation projects (opm init --example odd) ───────────────────────


def test_the_odd_example_matches_the_packaged_site() -> None:
    """examples/odd carries copies of what `opm odd document` builds with outside
    a project; the two must not drift apart."""
    from opm.config import load_project_config
    from opm.resources import example_dir, packaged_document_dir

    example = example_dir('odd')
    packaged = packaged_document_dir()
    odd_dir = Path(packaged_odd('tagdocs')).parent
    pairs = [
        (example / 'odd' / 'tagdocs.odd', odd_dir / 'tagdocs.odd'),
        (example / 'odd' / 'tagdocs.css', odd_dir / 'tagdocs.css'),
        *(
            (example / 'templates' / name, packaged / name)
            for name in ('page.html.j2', 'nav.xml', 'document.css', 'search.js',
                         'theme.js', 'tagdocs.typ.j2')
        ),
    ]
    for own, original in pairs:
        assert own.read_bytes() == original.read_bytes(), f'{own} differs from {original}'

    project = load_project_config(example / 'opm.toml')
    reference = load_project_config(packaged / 'opm.toml')
    assert project.xpath_extensions == reference.xpath_extensions

    def shape(runs):
        return [
            (run.name, run.xpath, run.file_pattern, run.template.name if run.template else None,
             [(f.name, f.xpath, f.scope) for f in run.fragments or ()])
            for run in runs
        ]

    assert shape(project.chunking_runs) == shape(reference.chunking_runs)


def test_documentation_project_starts_with_the_packaged_runs(tmp_path: Path) -> None:
    """The scaffold copies the runs `opm odd document` uses, re-rooted — no drift."""
    from opm.config import load_project_config
    from opm.resources import packaged_document_dir
    from opm.scaffold import InitOptions, scaffold

    result = scaffold(InitOptions(directory=tmp_path / 'site-project', example='odd'))
    root = result.directory
    for rel in (
        'opm.toml', 'odd/tagdocs.odd', 'odd/tagdocs.css',
        'templates/page.html.j2', 'templates/nav.xml', 'templates/document.css',
        'templates/tagdocs.typ.j2',
    ):
        assert (root / rel).is_file(), rel

    project = load_project_config(root / 'opm.toml')
    packaged = load_project_config(packaged_document_dir() / 'opm.toml')
    assert project.document is not None and project.document.source is None
    assert project.xpath_extensions == packaged.xpath_extensions
    assert not (root / 'extensions').exists()

    def shape(runs):
        return [
            (run.name, run.xpath, run.file_pattern, run.template.name if run.template else None,
             [(f.name, f.xpath) for f in run.fragments or ()])
            for run in runs
        ]

    assert shape(project.chunking_runs) == shape(packaged.chunking_runs)
    assert {run.output_dir for run in project.chunking_runs} == {'site'}
    assert project.chunking_runs[0].template == root / 'templates' / 'page.html.j2'
    assert project.typst_template == root / 'templates' / 'tagdocs.typ.j2'


def test_odd_document_builds_with_the_project_it_runs_in(
    tmp_path: Path, monkeypatch,
) -> None:
    """Inside a documentation project the project's ODD and assets win."""
    import sys

    from opm.scaffold import InitOptions, scaffold

    root = scaffold(InitOptions(directory=tmp_path / 'proj', example='odd')).directory
    config = (root / 'opm.toml').read_text(encoding='utf-8')
    config = config.replace('# source = "my-customization.odd"', f'source = "{MINI.as_posix()}"')
    (root / 'opm.toml').write_text(config, encoding='utf-8')
    # Changed ODD models, a changed asset.
    odd = root / 'odd' / 'tagdocs.odd'
    odd.write_text(
        odd.read_text(encoding='utf-8')
        .replace("'opt': 'Optional'", "'opt': 'PROJECT-Optional'")
        .replace(
            '<param name="catalog" value="list[@type=\'attCatalog\']"/>',
            '<param name="catalog" value="(\'Project attributes\', list[@type=\'attCatalog\'])"/>',
        ),
        encoding='utf-8',
    )
    (root / 'templates' / 'document.css').write_text('/* project css */\n', encoding='utf-8')

    # `extensions` is also the package name of ordinary scaffolded projects.
    for name in [m for m in sys.modules if m == 'extensions' or m.startswith('extensions.')]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.chdir(root)

    assert main(['odd', 'document', '--force']) == 0

    site = root / 'site'
    assert 'PROJECT-Optional' in (site / 'ref-p.html').read_text(encoding='utf-8')
    assert 'Project attributes' in (site / 'REF-ATTS.html').read_text(encoding='utf-8')
    assert (site / 'document.css').read_text(encoding='utf-8') == '/* project css */\n'
    # Not in the project, so the packaged ones: fonts and logo.
    assert (site / 'tei-logo.svg').is_file()
    assert any((site / 'fonts').glob('*.woff2'))


def test_prepare_then_chunk_gives_a_static_site_builder_both_runs(
    tmp_path: Path, monkeypatch,
) -> None:
    """`opm odd prepare` + `opm chunk --format json` in a documentation project."""
    import json
    import sys

    from opm.scaffold import InitOptions, scaffold

    root = scaffold(InitOptions(directory=tmp_path / 'proj', example='odd')).directory
    config = (root / 'opm.toml').read_text(encoding='utf-8')
    (root / 'opm.toml').write_text(
        config.replace('# source = "my-customization.odd"', f'source = "{MINI.as_posix()}"'), encoding='utf-8',
    )
    for name in [m for m in sys.modules if m == 'extensions' or m.startswith('extensions.')]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.chdir(root)

    assert main(['odd', 'prepare', '-o', 'schema.xml']) == 0
    assert main(['chunk', 'schema.xml', '--format', 'json', '--force']) == 0

    out = root / 'site' / 'schema.xml'
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    assert {chunk['run'] for chunk in manifest['chunks']} == {'guidelines', 'home', 'reference'}
    assert (out / 'index.json').is_file()
    ref = json.loads((out / 'ref-p.json').read_text(encoding='utf-8'))
    assert 'paragraph' in ref['content']
    # A second prepare refuses to overwrite without --force.
    assert main(['odd', 'prepare', '-o', 'schema.xml']) != 0


def test_a_documentation_project_turns_the_prepared_tree_into_typst(
    tmp_path: Path, monkeypatch,
) -> None:
    """`opm odd prepare` + `opm transform -t typst`: the PDF is one pass over the same tree."""
    from opm.scaffold import InitOptions, scaffold
    from opm.typst_compile import compile_pdf

    root = scaffold(InitOptions(directory=tmp_path / 'proj', example='odd')).directory
    config = (root / 'opm.toml').read_text(encoding='utf-8')
    (root / 'opm.toml').write_text(
        config.replace('# source = "my-customization.odd"', f'source = "{MINI.as_posix()}"'),
        encoding='utf-8',
    )
    monkeypatch.chdir(root)
    assert main(['odd', 'prepare', '-o', 'schema.xml']) == 0
    assert main(['transform', 'schema.xml', '-t', 'typst', '-o', 'docs.typ']) == 0

    # The document body follows the shell's last rule, the running footer.
    body = (root / 'docs.typ').read_text(encoding='utf-8').split('#set page(footer:', 1)[1]
    # The reference part: every spec once, in the catalog's A–Z order.
    positions = [body.index(f'#label("ref-{ident}")') for ident in ('div', 'hi', 'p')]
    assert positions == sorted(positions)
    assert all(body.count(f'#label("ref-{ident}")') == 1 for ident in ('div', 'hi', 'p'))
    # Spec entries are headings, but stay out of the table of contents.
    assert '#heading(level: 2, outlined: false)[#sym.lt;p#sym.gt;]' in body
    # Pointers become in-document links, not web URLs; no HTML leaks through.
    # An element reference carries the angle brackets the web adds in CSS.
    assert '#opm-xref("ref-hi")[\\<hi>]' in body
    assert 'Legal values:' in body and '- italic \\(cursive): set in italics' in body
    assert '.html' not in body
    # Unescaped HTML; an element reference prints as escaped Typst text (\<div>).
    assert not re.search(r'(?<!\\)<(section|article|a|li|div)\b', body)
    if shutil.which('typst'):
        assert compile_pdf((root / 'docs.typ').read_text(encoding='utf-8'), root=root).startswith(b'%PDF')

    # -p part=reference: the appendices alone, the cover still titled.
    assert main([
        'transform', 'schema.xml', '-t', 'typst', '-p', 'part=reference', '-o', 'reference.typ',
    ]) == 0
    reference = (root / 'reference.typ').read_text(encoding='utf-8')
    assert '#label("ref-p")' in reference and '#label("REF-ELEMENTS")' in reference


def test_a_documentation_project_turns_the_prepared_tree_into_markdown(
    tmp_path: Path, monkeypatch,
) -> None:
    """`opm transform -t markdown` shares the typst models tagged `plain`."""
    from opm.scaffold import InitOptions, scaffold

    root = scaffold(InitOptions(directory=tmp_path / 'proj', example='odd')).directory
    config = (root / 'opm.toml').read_text(encoding='utf-8')
    (root / 'opm.toml').write_text(
        config.replace('# source = "my-customization.odd"', f'source = "{MINI.as_posix()}"'),
        encoding='utf-8',
    )
    monkeypatch.chdir(root)
    assert main(['odd', 'prepare', '-o', 'schema.xml']) == 0
    assert main(['transform', 'schema.xml', '-t', 'markdown', '-o', 'docs.md']) == 0

    body = (root / 'docs.md').read_text(encoding='utf-8')
    assert body.lstrip().startswith('# Mini schema')
    # The reference part: every spec once, in the catalog's A–Z order.
    positions = [body.index(f"<a id='ref-{ident}'></a>") for ident in ('div', 'hi', 'p')]
    assert positions == sorted(positions)
    assert all(body.count(f"<a id='ref-{ident}'></a>") == 1 for ident in ('div', 'hi', 'p'))
    assert '## `<p>`' in body
    # Pointers become in-document links, not web URLs; no HTML leaks through.
    # An element reference carries the angle brackets the web adds in CSS.
    assert '[`<hi>`](#ref-hi)' in body
    assert '.html' not in body
    assert not re.search(r'<(section|article|li|div|dl|span)\s+class=', body)
    assert 'Legal values:' in body and '- italic (cursive): set in italics' in body

    assert main([
        'transform', 'schema.xml', '-t', 'markdown', '-p', 'part=reference', '-o', 'reference.md',
    ]) == 0
    reference = (root / 'reference.md').read_text(encoding='utf-8')
    assert "<a id='ref-p'></a>" in reference and "<a id='REF-ELEMENTS'></a>" in reference
