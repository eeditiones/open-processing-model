"""Static ODD documentation site."""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree
import pytest

from opm.cli import main
from opm.document_site import build_document_site, prepare_document_tree
from opm.odd_schema import (
    chapters_have_prose,
    compile_schema,
    iter_guideline_chapters,
)
from opm.resources import packaged_odd
from opm.spec_index import OPM_PAGE, PAGE_CHAPTER, iter_canonical_specs

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
MINI = FIXTURES / 'mini_schema.odd'
CUSTOM = FIXTURES / 'mini_custom.odd'
PM = FIXTURES / 'mini_pm.odd'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'


@pytest.fixture(autouse=True)
def _no_p5subset_download(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args, **_kwargs):
        raise AssertionError('tests must not download p5subset')

    monkeypatch.setattr('urllib.request.urlopen', _blocked)


def _stub_p5subset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the mini schema as the TEI base so customization tests stay small.

    ``mini_custom.odd`` / ``mini_pm.odd`` are TEI-targeting overlays, so
    ``compile_schema`` would otherwise merge cached ``p5subset.xml`` and the
    site would grow to thousands of pages.
    """
    monkeypatch.setattr('opm.odd_schema.ensure_p5all', lambda **_k: MINI)


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


def test_spec_only_chapters_are_not_written(tmp_path: Path) -> None:
    """p5subset wraps specs in ``div1`` skeletons; those are not site chapters."""
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
    assert site.chapters == 0
    assert not (site.output_dir / 'CO.html').exists()
    assert (site.output_dir / 'ref-p.html').is_file()


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
    _stub_p5subset(monkeypatch)
    compiled = compile_schema(CUSTOM)
    site = build_document_site(compiled, tmp_path / 'out')
    assert not (site.output_dir / 'ref-hi.html').exists()
    html = (site.output_dir / 'ref-p.html').read_text(encoding='utf-8')
    assert '@type' in html
    assert 'character data' in html.lower()


def test_processing_overlay_site_lists_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_p5subset(monkeypatch)
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


def test_cli_document_requires_input() -> None:
    assert main(['odd', 'document']) == 1


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
    assert re.search(r'class="chapter-nav__next"[^>]*href=""', notes)
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

    # Body chapters are numbered by position; front/back chapters are not.
    assert re.search(
        r'class="chapter-nav__num">2</span>The TEI Header', chapter
    )
    assert re.search(
        r'class="chapter-nav__num">4</span>Default Text Structure', chapter
    )
    first = (site.output_dir / 'IN.html').read_text(encoding='utf-8')
    assert re.search(r'class="chapter-nav__num"></span>About', first)


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
    assert 'REF-ELEMENTS' not in back_ids

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
    assert 'chapter-nav' not in catalog
    st = (site.output_dir / 'ST.html').read_text(encoding='utf-8')
    assert re.search(r'class="chapter-nav__prev"[^>]*href="FM1\.html"', st)
    assert re.search(r'class="chapter-nav__next"[^>]*href="BIB\.html"', st)

    # Marking a chapter as publishable must not overwrite the author's @type:
    # the ODD and the stylesheet still need to tell a dedication from a chapter.
    marked = {
        div.get(XML_ID): (div.get('type'), div.get(OPM_PAGE))
        for div in iter_guideline_chapters(tree)
    }
    assert marked['dedication'] == ('Dedication', PAGE_CHAPTER)
    assert marked['TitlePageVerso'] == ('titlePageVerso', PAGE_CHAPTER)
    assert marked['ST'] == ('div1', PAGE_CHAPTER)


def test_unsupported_expressions_in_own_odd_are_reported(tmp_path: Path) -> None:
    """An expression opm cannot evaluate renders empty — it must not do so silently.

    Only the documentation ODD's own expressions count: it customizes
    teipublisher.odd, whose eXist calls are inherited and never reached.
    """
    odd = tmp_path / 'tampered.odd'
    packaged = Path(packaged_odd('tagdocs')).read_text(encoding='utf-8')
    odd.write_text(
        packaged.replace('tp:spec_desc(@key, .)', 'current()'),
        encoding='utf-8',
    )

    site = build_document_site(compile_schema(MINI), tmp_path / 'out', odd=odd)
    reasons = {(e['element'], e['where'], e['reason']) for e in site.unsupported}
    assert reasons == {('specDesc', 'param desc', 'unknown function current()')}


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
    """``--tei`` documents TEI, so the artifact's chapters are the site's."""
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

    tei = compile_schema(use_tei=True)
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
        if div.get(OPM_PAGE) == PAGE_CHAPTER
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
            if div.get(OPM_PAGE) == PAGE_CHAPTER
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
        if div.get(OPM_PAGE) == PAGE_CHAPTER
    ]
    assert ids == ['elements', 'elements-2', 'chapter-12-numbers']
    assert len(ids) == len(set(ids))
    # REF-ELEMENTS is injected after this runs, so it must still be free.
    assert 'REF-ELEMENTS' not in ids


def _chapter_head(div: etree._Element) -> str:
    for child in div:
        if child.tag.endswith('head'):
            return ' '.join(child.itertext()).strip()
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
