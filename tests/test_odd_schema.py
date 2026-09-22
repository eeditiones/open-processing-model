"""odd2odd-lite compilation of ODD customizations."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from lxml import etree

from opm.odd_schema import (
    P5ALL_URL,
    SchemaError,
    compile_schema,
    normalize_tei_version,
    p5all_cache_path,
    targets_tei,
)
from opm.resources import packaged_odd
from opm.odd_expand import _att_tree, _may_contain
from opm.spec_index import Spec, SpecIndex, localname

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
MINI = FIXTURES / 'mini_schema.odd'
CUSTOM = FIXTURES / 'mini_custom.odd'
PM = FIXTURES / 'mini_pm.odd'
TEI_NS = 'http://www.tei-c.org/ns/1.0'


def _models(spec: Spec) -> list[etree._Element]:
    """The processing models declared on *spec*, as the ODD holds them."""
    return [m for m in spec.node if localname(m) in {'model', 'modelGrp', 'modelSequence'}]


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


def _write_processing_odd(
    path: Path,
    *,
    ident: str,
    ns: str | None = None,
    version: str | None = None,
    source: str | None = None,
) -> Path:
    ns_attr = '' if ns is None else f' ns="{ns}"'
    source_attr = '' if source is None else f' source="{source}"'
    version_attr = '' if version is None else f' version="{version}"'
    path.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="{TEI_NS}"{version_attr}>
  <teiHeader>
    <fileDesc>
      <titleStmt><title>{ident}</title></titleStmt>
      <publicationStmt><p>test</p></publicationStmt>
      <sourceDesc><p>test</p></sourceDesc>
    </fileDesc>
  </teiHeader>
  <text><body>
    <schemaSpec ident="{ident}"{ns_attr}{source_attr}>
      <elementSpec ident="p" mode="change">
        <model behaviour="paragraph"/>
      </elementSpec>
    </schemaSpec>
  </body></text>
</TEI>
''',
        encoding='utf-8',
    )
    return path


def _stub_p5all(monkeypatch: pytest.MonkeyPatch, *, returns: Path = MINI):
    calls: list[dict[str, object]] = []

    def fake(*, fetch: bool = True, url: str | None = None, **_kwargs):
        calls.append({'fetch': fetch, 'url': url})
        return returns

    monkeypatch.setattr('opm.odd_schema.ensure_p5all', fake)
    return calls


def test_self_contained_schema_is_indexed_as_is() -> None:
    compiled = compile_schema(MINI)
    index = SpecIndex.from_tree(compiled.tree)
    assert index.element('p').ident == 'p'
    assert compiled.title == 'Mini schema'
    assert compiled.ident == 'mini'
    assert [m.get('behaviour') for m in _models(index.element('p'))] == ['paragraph']


def test_customization_deletes_element_and_attribute() -> None:
    compiled = compile_schema(CUSTOM)
    index = SpecIndex.from_tree(compiled.tree)
    assert compiled.ident == 'miniCustom'
    assert index.get('hi') is None
    p = index.element('p')
    child_idents = {c.ident for c in _may_contain(index, p)}
    assert 'hi' not in child_idents
    att_names = {a.ident for a in p.local_atts}
    assert 'type' in att_names
    inherited = {
        item.get('ident')
        for item in _att_tree(index, p).iterfind(f".//{{{TEI_NS}}}list[@type='atts']/{{{TEI_NS}}}item")
    }
    assert 'n' not in inherited
    assert 'xml:id' in inherited


def test_processing_models_merge_along_source_chain() -> None:
    compiled = compile_schema(PM)
    index = SpecIndex.from_tree(compiled.tree)
    assert compiled.ident == 'miniPm'
    p = index.element('p')
    assert [m.get('behaviour') for m in _models(p)] == ['block', 'paragraph']
    assert _models(p)[0].get('predicate') == '@rend'
    assert _models(p)[0].get('cssClass') == 'rend'
    assert 'hi' in {c.ident for c in _may_contain(index, p)}
    assert index.get('quote') is not None
    assert _models(index.element('quote'))[0].get('behaviour') == 'inline'


def test_processing_odd_without_schema_source_documents_its_specs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    odd = Path(__file__).resolve().parents[1] / 'src/opm/resources/odd/teipublisher.odd'
    if not odd.is_file():
        odd = packaged_odd('teipublisher')
    root = etree.parse(str(odd)).getroot()
    assert targets_tei(root)
    calls = _stub_p5all(monkeypatch)
    compiled = compile_schema(odd)
    assert calls and calls[0]['url'] is None
    assert compiled.fetched_source == MINI
    index = SpecIndex.from_tree(compiled.tree)
    p = index.element('p')
    assert any(m.get('behaviour') == 'paragraph' for m in _models(p))
    assert any(m.get('output') == 'print' for m in _models(p))
    assert 'hi' in {c.ident for c in _may_contain(index, p)}


def test_directory_of_specs(tmp_path: Path) -> None:
    src = (tmp_path / 'Specs')
    src.mkdir()
    (src / 'p.xml').write_text(
        '''<elementSpec xmlns="http://www.tei-c.org/ns/1.0" ident="p" module="core">
             <desc xml:lang="en">paragraph</desc>
             <content><textNode/></content>
           </elementSpec>''',
        encoding='utf-8',
    )
    compiled = compile_schema(src)
    index = SpecIndex.from_tree(compiled.tree)
    assert index.element('p').module == 'core'


def test_p5all_cache_is_a_single_file() -> None:
    assert p5all_cache_path().name == 'p5all.xml'
    assert P5ALL_URL.endswith('/p5all.xml.gz')
    assert normalize_tei_version('4.8.0') == '4.8.0'
    assert normalize_tei_version(None) == 'current'


def test_self_contained_schema_does_not_fetch_p5subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A compiled schema document is indexed as-is; no TEI base is layered under it."""
    calls = _stub_p5all(monkeypatch)
    compile_schema(MINI)
    assert calls == []


def test_tei_customization_fetches_p5subset_even_with_local_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``@source`` parents (teipublisher, a mini schema) are overlays, not the TEI base."""
    calls = _stub_p5all(monkeypatch)
    compile_schema(PM)
    compile_schema(CUSTOM)
    assert len(calls) == 2
    assert all(c['url'] is None for c in calls)


def test_customization_adding_its_own_elements_fetches_p5subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """New elementSpecs do not make a TEI customization self-contained.

    An ODD may add elements of its own and still take everything else from
    TEI, so a ``content`` model in the input is no signal to skip the merge.
    """
    calls = _stub_p5all(monkeypatch)
    odd = tmp_path / 'adds.odd'
    odd.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
        <TEI xmlns="http://www.tei-c.org/ns/1.0">
          <teiHeader><fileDesc>
            <titleStmt><title>Adds an element</title></titleStmt>
            <publicationStmt><p>test</p></publicationStmt>
            <sourceDesc><p>test</p></sourceDesc>
          </fileDesc></teiHeader>
          <text><body>
            <schemaSpec ident="adds" source="p5subset.xml">
              <elementSpec ident="myThing" mode="add">
                <desc xml:lang="en">an element this ODD invents</desc>
                <content><textNode/></content>
              </elementSpec>
            </schemaSpec>
          </body></text>
        </TEI>''',
        encoding='utf-8',
    )
    compile_schema(odd)
    assert len(calls) == 1


def test_non_tei_vocabularies_are_standalone(monkeypatch: pytest.MonkeyPatch) -> None:
    """JATS (``ns=""``) and DocBook ODDs are schemas in their own right."""
    calls = _stub_p5all(monkeypatch)
    for name in ('jats.odd', 'docbook.odd'):
        compile_schema(Path('src/opm/resources/odd') / name)
    assert calls == []


def test_local_content_model_narrows_the_dependency_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subsetting follows the ODD's own content models, not the stock ones.

    An edition that rewrites `text` to hold a pair of parallel texts no longer
    references front, back or group. Closing over the source's content model
    instead would pull all three into the schema behind the ODD's back, and the
    include list would not mean what it says.
    """
    source = tmp_path / 'source.odd'
    source.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="{TEI_NS}">
  <teiHeader><fileDesc>
    <titleStmt><title>Source</title></titleStmt>
    <publicationStmt><p>test</p></publicationStmt>
    <sourceDesc><p>test</p></sourceDesc>
  </fileDesc></teiHeader>
  <text><body>
    <schemaSpec ident="src">
      <moduleSpec ident="textstructure"><desc>Text structure.</desc></moduleSpec>
      <elementSpec ident="text" module="textstructure">
        <desc>a text</desc>
        <content>
          <elementRef key="front"/><elementRef key="body"/><elementRef key="back"/>
        </content>
      </elementSpec>
      <elementSpec ident="body" module="textstructure">
        <desc>a body</desc><content><textNode/></content>
      </elementSpec>
      <elementSpec ident="front" module="textstructure">
        <desc>front matter</desc><content><textNode/></content>
      </elementSpec>
      <elementSpec ident="back" module="textstructure">
        <desc>back matter</desc><content><textNode/></content>
      </elementSpec>
    </schemaSpec>
  </body></text>
</TEI>
''',
        encoding='utf-8',
    )
    odd = tmp_path / 'edition.odd'
    odd.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="{TEI_NS}">
  <teiHeader><fileDesc>
    <titleStmt><title>Edition</title></titleStmt>
    <publicationStmt><p>test</p></publicationStmt>
    <sourceDesc><p>test</p></sourceDesc>
  </fileDesc></teiHeader>
  <text><body>
    <schemaSpec ident="edition" start="text">
      <moduleRef key="textstructure" include="text body"/>
      <elementSpec ident="text" mode="change">
        <content><elementRef key="body"/></content>
      </elementSpec>
    </schemaSpec>
  </body></text>
</TEI>
''',
        encoding='utf-8',
    )
    _stub_p5all(monkeypatch, returns=source)
    index = SpecIndex.from_tree(compile_schema(odd).tree)
    assert index.get('text') is not None
    assert index.get('body') is not None
    assert index.get('front') is None
    assert index.get('back') is None


def _odd(title: str, schema: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="{TEI_NS}">
  <teiHeader><fileDesc>
    <titleStmt><title>{title}</title></titleStmt>
    <publicationStmt><p>test</p></publicationStmt>
    <sourceDesc><p>test</p></sourceDesc>
  </fileDesc></teiHeader>
  <text><body>
    {schema}
  </body></text>
</TEI>
'''


_CLASS_SOURCE = '''<schemaSpec ident="src">
  <moduleSpec ident="core"><desc>Core.</desc></moduleSpec>
  <moduleSpec ident="linking"><desc>Linking.</desc></moduleSpec>
  <elementSpec ident="body" module="core">
    <desc>a body</desc>
    <content><classRef key="model.pLike"/><classRef key="model.egLike"/><elementRef key="join"/></content>
  </elementSpec>
  <elementSpec ident="eg" module="core">
    <desc>an example</desc><classes><memberOf key="model.egLike"/></classes>
    <content><textNode/></content>
  </elementSpec>
  <elementSpec ident="join" module="linking">
    <desc>a join</desc><classes><memberOf key="att.pointing"/></classes>
    <content><textNode/></content>
  </elementSpec>
  <classSpec ident="att.pointing" type="atts" module="linking"><desc>pointing</desc></classSpec>
  <classSpec ident="model.egLike" type="model" module="core"><desc>examples</desc></classSpec>
  <elementSpec ident="p" module="core">
    <desc>a paragraph</desc>
    <classes>
      <memberOf key="att.global"/><memberOf key="att.cmc"/><memberOf key="att.placement"/>
      <memberOf key="model.pLike"/><memberOf key="model.linePart"/>
    </classes>
    <content><textNode/></content>
    <attList>
      <attDef ident="place" mode="change" usage="req">
        <valList type="closed" mode="replace">
          <valItem ident="margin"><desc>in the margin</desc></valItem>
        </valList>
      </attDef>
    </attList>
  </elementSpec>
  <elementSpec ident="line" module="core">
    <desc>a line</desc><content><classRef key="model.linePart"/></content>
  </elementSpec>
  <classSpec ident="att.global" type="atts" module="core"><desc>global</desc></classSpec>
  <classSpec ident="att.cmc" type="atts" module="core"><desc>cmc</desc></classSpec>
  <classSpec ident="att.placement" type="atts" module="core">
    <desc>placement</desc>
    <attList>
      <attDef ident="place" usage="opt">
        <desc>where it is placed</desc>
        <datatype maxOccurs="unbounded"><dataRef key="teidata.enumerated"/></datatype>
      </attDef>
    </attList>
  </classSpec>
  <classSpec ident="model.pLike" type="model" module="core"><desc>paragraphs</desc></classSpec>
  <classSpec ident="model.linePart" type="model" module="core"><desc>line parts</desc></classSpec>
</schemaSpec>'''


def test_customization_prunes_classes_as_odd2odd_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A class the ODD deletes stays deleted though an element still names it; a
    class only a left-out element used goes, as does a model class no element
    is left in, as in the TEI Stylesheets' odd2odd; and no ``memberOf`` points
    at any of them. An element a content model names but no ``moduleRef``
    includes stays out, and an empty ``@include`` takes no elements."""
    source = tmp_path / 'source.odd'
    source.write_text(_odd('Source', _CLASS_SOURCE), encoding='utf-8')
    odd = tmp_path / 'custom.odd'
    odd.write_text(_odd('Custom', '''<schemaSpec ident="custom" start="body">
      <moduleRef key="core" include="body p"/>
      <moduleRef key="linking" include=""/>
      <classSpec ident="att.cmc" type="atts" module="core" mode="delete"/>
    </schemaSpec>'''), encoding='utf-8')
    _stub_p5all(monkeypatch, returns=source)
    tree = compile_schema(odd).tree
    index = SpecIndex.from_tree(tree)
    for gone in ('line', 'eg', 'join', 'att.cmc', 'model.linePart', 'model.egLike', 'att.pointing'):
        assert index.get(gone) is None, gone
    for kept in ('att.global', 'att.placement', 'model.pLike'):
        assert index.get(kept) is not None, kept
    assert index.get('p').member_of_keys == ['att.global', 'att.placement', 'model.pLike']


def test_changed_attribute_is_completed_from_its_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``attDef mode="change"`` that restates only the values keeps the
    description and datatype of the class attribute it changes."""
    from opm.document_site import prepare_document_tree

    source = tmp_path / 'source.odd'
    source.write_text(_odd('Source', _CLASS_SOURCE), encoding='utf-8')
    odd = tmp_path / 'custom.odd'
    odd.write_text(_odd('Custom', '''<schemaSpec ident="custom" start="body">
      <moduleRef key="core" include="body p"/>
    </schemaSpec>'''), encoding='utf-8')
    _stub_p5all(monkeypatch, returns=source)
    tree = prepare_document_tree(compile_schema(odd))
    ns = {'t': TEI_NS}
    (place,) = tree.xpath("//t:elementSpec[@xml:id='ref-p']//t:attDef[@ident='place']", namespaces=ns)
    assert place.get('usage') == 'req'
    assert place.get('source') == '#ref-att.placement'
    assert place.xpath('string(t:desc)', namespaces=ns) == 'where it is placed'
    assert place.xpath('t:datatype/@maxOccurs', namespaces=ns) == ['unbounded']
    assert place.xpath('t:valList/t:valItem/@ident', namespaces=ns) == ['margin']


def test_roma_style_module_refs_fetch_p5subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``@module`` on overlays must not suppress the TEI base (DTABf-style ODDs)."""
    calls = _stub_p5all(monkeypatch)
    odd = tmp_path / 'roma.odd'
    odd.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="{TEI_NS}">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>Roma-style</title></titleStmt>
      <publicationStmt><p>test</p></publicationStmt>
      <sourceDesc><p>test</p></sourceDesc>
    </fileDesc>
  </teiHeader>
  <text><body>
    <schemaSpec ident="roma" start="TEI">
      <moduleRef key="core" include="p hi"/>
      <elementSpec ident="p" module="core" mode="change">
        <model behaviour="paragraph"/>
      </elementSpec>
    </schemaSpec>
  </body></text>
</TEI>
''',
        encoding='utf-8',
    )
    compiled = compile_schema(odd)
    assert calls and calls[0]['url'] is None
    assert compiled.fetched_source == MINI
    index = SpecIndex.from_tree(compiled.tree)
    assert index.get('p') is not None
    assert index.get('hi') is not None


def test_jats_and_docbook_do_not_fetch_p5subset(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_p5all(monkeypatch)
    jats = packaged_odd('jats')
    docbook = packaged_odd('docbook')
    assert not targets_tei(etree.parse(str(jats)).getroot())
    assert not targets_tei(etree.parse(str(docbook)).getroot())
    compile_schema(jats)
    compile_schema(docbook)
    assert calls == []


def test_empty_and_foreign_ns_do_not_fetch_p5subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_p5all(monkeypatch)
    compile_schema(_write_processing_odd(tmp_path / 'jats.odd', ident='jats', ns=''))
    compile_schema(
        _write_processing_odd(
            tmp_path / 'docbook.odd',
            ident='docbook',
            ns='http://docbook.org/ns/docbook',
        )
    )
    assert calls == []


def _versioned_artifact(tmp_path: Path, version: str = '5.0') -> Path:
    """MINI, stamped with a TEI release number, standing in for the artifact."""
    dest = tmp_path / 'p5all.xml'
    dest.write_text(
        MINI.read_text(encoding='utf-8').replace(
            '<TEI xmlns="http://www.tei-c.org/ns/1.0">',
            f'<TEI xmlns="http://www.tei-c.org/ns/1.0" version="{version}">',
            1,
        ),
        encoding='utf-8',
    )
    return dest


def test_tei_version_pin_is_reported_not_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One artifact cannot serve a Vault snapshot, so say so rather than lie."""
    _stub_p5all(monkeypatch, returns=_versioned_artifact(tmp_path))
    odd = _write_processing_odd(
        tmp_path / 'pm.odd', ident='pm', version='4.8.0',
    )
    compiled = compile_schema(odd)
    assert any(
        '4.8.0' in w and '5.0' in w for w in compiled.warnings
    ), compiled.warnings
    index = SpecIndex.from_tree(compiled.tree)
    p = index.element('p')
    assert [m.get('behaviour') for m in _models(p)] == ['paragraph']
    assert 'hi' in {c.ident for c in _may_contain(index, p)}


def test_unpinned_odd_fetches_the_artifact_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_p5all(monkeypatch)
    odd = _write_processing_odd(tmp_path / 'pm.odd', ident='pm')
    compiled = compile_schema(odd)
    assert calls == [{'fetch': True, 'url': None}]
    assert not [w for w in compiled.warnings if 'asks for TEI' in w]


def test_ancestor_tei_version_pin_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pin inherited through schemaSpec/@source is reported too."""
    _stub_p5all(monkeypatch, returns=_versioned_artifact(tmp_path))
    _write_processing_odd(
        tmp_path / 'parent.odd', ident='parent', version='4.8.0',
    )
    child = _write_processing_odd(
        tmp_path / 'child.odd', ident='child', source='parent.odd',
    )
    compiled = compile_schema(child)
    assert any('4.8.0' in w for w in compiled.warnings), compiled.warnings


def test_explicit_tei_namespace_still_fetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_p5all(monkeypatch)
    odd = _write_processing_odd(
        tmp_path / 'pm.odd', ident='pm', ns=TEI_NS,
    )
    compile_schema(odd)
    assert calls and calls[0]['url'] is None


def test_offline_without_cache_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(*, fetch: bool = True, url: str | None = None, **_kwargs):
        if not fetch:
            raise SchemaError('not cached')
        raise AssertionError('offline must not download')

    monkeypatch.setattr('opm.odd_schema.ensure_p5all', fake)
    odd = _write_processing_odd(tmp_path / 'pm.odd', ident='pm')
    with pytest.raises(SchemaError, match='not cached'):
        compile_schema(odd, fetch=False)


def _serve(monkeypatch: pytest.MonkeyPatch, payload: dict[str, bytes]) -> list[str]:
    """Stub the network so each URL returns the bytes mapped to it."""
    requested: list[str] = []

    class _Resp(io.BytesIO):
        """A real stream: ``read(n)`` must eventually return b'', or
        ``copyfileobj`` writes forever."""

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            self.close()
            return False

    def fake_urlopen(request, **_kwargs):
        url = request.full_url if hasattr(request, 'full_url') else str(request)
        requested.append(url)
        for suffix, data in payload.items():
            if url.endswith(suffix):
                return _Resp(data)
        raise OSError(f'404 {url}')

    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    return requested


def _artifact_bytes() -> tuple[bytes, str]:
    import gzip
    import hashlib

    raw = MINI.read_bytes()
    packed = gzip.compress(raw)
    return packed, hashlib.sha256(packed).hexdigest()


def test_ensure_p5all_downloads_verifies_and_decompresses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opm.odd_schema import ensure_p5all

    packed, digest = _artifact_bytes()
    cache = tmp_path / 'tei' / 'p5all.xml'
    monkeypatch.setattr('opm.odd_schema.p5all_cache_path', lambda: cache)
    urls = _serve(monkeypatch, {
        'p5all.xml.gz': packed,
        'SHA256SUMS': f'{digest}  p5all.xml.gz\n'.encode(),
    })

    path = ensure_p5all()
    assert path == cache
    assert path.read_bytes() == MINI.read_bytes()
    assert any(u.endswith('p5all.xml.gz') for u in urls)
    # Cached: a second call must not hit the network again.
    urls.clear()
    assert ensure_p5all() == cache
    assert urls == []
    # No .part files left behind.
    assert sorted(q.name for q in cache.parent.iterdir()) == ['p5all.xml']


def test_ensure_p5all_rejects_a_bad_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupted or substituted bytes must fail loudly, not parse halfway."""
    from opm.odd_schema import ensure_p5all

    packed, _digest = _artifact_bytes()
    cache = tmp_path / 'tei' / 'p5all.xml'
    monkeypatch.setattr('opm.odd_schema.p5all_cache_path', lambda: cache)
    _serve(monkeypatch, {
        'p5all.xml.gz': packed,
        'SHA256SUMS': b'0' * 64 + b'  p5all.xml.gz\n',
    })

    with pytest.raises(SchemaError, match='Checksum mismatch'):
        ensure_p5all()
    assert not cache.exists()
    assert not list(cache.parent.iterdir())


def test_ensure_p5all_tolerates_a_missing_checksum_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TLS and gzip's CRC still apply, so an absent SHA256SUMS is not fatal."""
    from opm.odd_schema import ensure_p5all

    packed, _digest = _artifact_bytes()
    cache = tmp_path / 'tei' / 'p5all.xml'
    monkeypatch.setattr('opm.odd_schema.p5all_cache_path', lambda: cache)
    _serve(monkeypatch, {'p5all.xml.gz': packed})

    assert ensure_p5all().read_bytes() == MINI.read_bytes()


def test_ensure_p5all_offline_without_cache_explains_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opm.odd_schema import ensure_p5all

    monkeypatch.setattr(
        'opm.odd_schema.p5all_cache_path', lambda: tmp_path / 'tei' / 'p5all.xml',
    )
    with pytest.raises(SchemaError, match='not cached'):
        ensure_p5all(fetch=False)


def test_download_refuses_an_endless_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server that never stops sending must not fill the disk."""
    from opm.odd_schema import _download_file

    class _Endless:
        def read(self, size=-1):
            return b'x' * (size if size and size > 0 else 1024)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr('urllib.request.urlopen', lambda *_a, **_k: _Endless())
    dest = tmp_path / 'big.bin'
    with pytest.raises(SchemaError, match='refusing to keep reading'):
        _download_file('https://example.invalid/big', dest, max_bytes=1024 * 1024)
    assert not dest.exists()
    assert not list(tmp_path.iterdir())
