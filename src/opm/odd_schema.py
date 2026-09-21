# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Load an ODD and compile it by following ``schemaSpec/@source``.

An ODD may declare content models, processing models, or both. Compilation
walks the inheritance chain (parent ODDs first), then overlays local specs with
``mode`` of ``add`` / ``change`` / ``delete`` / ``replace`` — including
``model`` / ``modelGrp`` / ``modelSequence``.

TEI-targeting ODDs (``schemaSpec/@ns`` absent or the TEI namespace) are merged
onto cached ``p5subset.xml`` so ``moduleRef`` and content models resolve.
``TEI/@version`` selects a Vault release; otherwise the latest release is
fetched. It is not shipped in the wheel. JATS / DocBook ODDs (``@ns`` empty or
another vocabulary) are not merged onto TEI.

Specs and chapter prose are compiled separately and joined at the end: the
specs come from the ``moduleRef`` / ``@mode`` merge, the prose from the input
itself or, when the input *is* the schema being documented, from the downloaded
TEI ``Source/`` Guidelines. The result is one tree carrying both.
"""

from __future__ import annotations

import gzip
import hashlib
import re
import shutil
import urllib.request
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from opm.odd_compiler.parse_odd import resolve_schema_source
from opm.resources import opm_version, user_opm_cache_dir
from opm.spec_index import (
    TEI_NS,
    _PARSER,
    _inside_egxml,
    iter_canonical_specs,
    localname,
    qn,
)

#: One pre-assembled artifact — the TEI Guidelines with every spec inlined and
#: XInclude resolved — replacing both ``p5subset.xml`` and the ``Source/`` tree.
#: Hosted on a rolling release tag so TEI data refreshes without a opm release.
_RELEASE_BASE = (
    'https://github.com/eeditiones/open-processing-model/releases/download/tei-data'
)
P5ALL_URL = f'{_RELEASE_BASE}/p5all.xml.gz'
P5ALL_CHECKSUMS_URL = f'{_RELEASE_BASE}/SHA256SUMS'
P5ALL_ASSET = 'p5all.xml.gz'
_TEI_VERSION_RE = re.compile(r'^\d+\.\d+(?:\.\d+)?$')

# schemaSpec/@source tokens that mean TEI p5subset, not another ODD file.
_TEI_SOURCE_TOKENS = {
    'p5subset.xml',
    'p5subset',
    'tei_all',
    'tei_all.odd',
    'tei',
}

_MODEL_TAGS = {'model', 'modelGrp', 'modelSequence'}
_SPEC_TAGS = {'elementSpec', 'classSpec', 'macroSpec', 'dataSpec', 'moduleSpec'}


class SchemaError(ValueError):
    """The input is not an ODD / compiled spec document we can document."""


@dataclass
class CompiledSchema:
    """A schema ready to index: merged specs, plus chapter prose when there is any."""

    tree: etree._Element
    source_path: Path | None = None
    title: str = ''
    ident: str = ''
    warnings: list[str] = field(default_factory=list)
    fetched_source: Path | None = None

    def __post_init__(self) -> None:
        if not self.ident:
            self.ident = schema_ident(self.tree, self.source_path)


def p5all_cache_path() -> Path:
    """Where the decompressed TEI artifact lives once fetched."""
    return user_opm_cache_dir() / 'tei' / 'p5all.xml'


def ensure_p5all(
    *,
    fetch: bool = True,
    url: str | None = None,
    checksums_url: str | None = None,
) -> Path:
    """Return a local ``p5all.xml``, downloading it into the user cache if needed.

    One file, one request. It carries the same specs as ``p5subset.xml`` plus
    the Guidelines prose, so there is nothing else to fetch and no version to
    resolve — the artifact tracks TEI's latest release.
    """
    dest = p5all_cache_path()
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    if not fetch:
        raise SchemaError(
            f'The TEI schema is not cached at {dest} and downloading is off. '
            f'Put a p5all.xml there to work offline.'
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    archive = dest.with_suffix('.xml.gz.part')
    try:
        _download_file(url or P5ALL_URL, archive)
        _verify_checksum(
            archive, P5ALL_ASSET, checksums_url or P5ALL_CHECKSUMS_URL,
        )
        _gunzip(archive, dest)
    finally:
        archive.unlink(missing_ok=True)
    return dest


def _verify_checksum(path: Path, name: str, checksums_url: str) -> None:
    """Check *path* against the published ``SHA256SUMS`` entry for *name*.

    A missing or unreachable checksum file is not fatal — the download still
    has TLS and gzip's own CRC behind it — but a checksum that is present and
    does not match means corrupted or substituted bytes, so that is an error.
    """
    try:
        listing = _http_get_text(checksums_url)
    except SchemaError:
        return
    expected = ''
    for line in listing.splitlines():
        digest, _, filename = line.partition(' ')
        if filename.strip().lstrip('*') == name:
            expected = digest.strip()
            break
    if not expected:
        return
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SchemaError(
            f'Checksum mismatch for {name}: expected {expected}, got {actual}. '
            'The download was corrupted or tampered with.'
        )


def _gunzip(archive: Path, dest: Path) -> None:
    """Decompress *archive* to *dest*, atomically."""
    tmp = dest.with_suffix('.xml.part')
    try:
        with gzip.open(archive, 'rb') as src, tmp.open('wb') as out:
            shutil.copyfileobj(src, out)
    except (OSError, EOFError) as exc:
        tmp.unlink(missing_ok=True)
        raise SchemaError(f'Could not decompress {archive}: {exc}') from exc
    tmp.replace(dest)


def normalize_tei_version(raw: str | None) -> str:
    """``4.8.0`` / ``4.8`` stay as Vault ids; anything else means latest."""
    if not raw:
        return 'current'
    value = raw.strip()
    if _TEI_VERSION_RE.match(value):
        return value
    return 'current'


#: The compressed TEI artifact is ~2 MB. This is a sanity bound, not a quota:
#: it stops a misbehaving server or proxy from filling the disk.
_MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024


def _download_file(
    url: str, dest: Path, *, timeout: int = 60, max_bytes: int = _MAX_DOWNLOAD_BYTES,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + '.part')
    request = urllib.request.Request(
        url,
        headers={'User-Agent': f'opm/{opm_version()} (ODD documentation)'},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp, tmp.open('wb') as out:
            written = 0
            while chunk := resp.read(64 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise SchemaError(
                        f'{url} sent more than {max_bytes} bytes; refusing to '
                        'keep reading.'
                    )
                out.write(chunk)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise SchemaError(f'Could not download {url}: {exc}') from exc
    except SchemaError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)


def _http_get_text(url: str, *, timeout: int = 60) -> str:
    request = urllib.request.Request(
        url,
        headers={'User-Agent': f'opm/{opm_version()} (ODD documentation)'},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except OSError as exc:
        raise SchemaError(f'Could not download {url}: {exc}') from exc


def load_xml(path: Path) -> etree._Element:
    """Parse *path*, or a directory of spec files, into one TEI tree."""
    path = path.resolve()
    if path.is_dir():
        return _load_spec_directory(path)
    if not path.is_file():
        raise SchemaError(f'No such file or directory: {path}')
    return etree.parse(str(path), _PARSER).getroot()


def targets_tei(root: etree._Element) -> bool:
    """True when ``schemaSpec/@ns`` is absent or the TEI namespace.

    JATS (``ns=""``) and DocBook (another namespace) are not TEI customizations.
    """
    schema = _main_schema_spec(root)
    if schema is None:
        return localname(root) == 'TEI' or root.nsmap.get(None) == TEI_NS
    ns = schema.get('ns')
    if ns is None:
        return True
    return ns == TEI_NS


def has_guidelines_chapters(root: etree._Element) -> bool:
    """True when *root* is a Guidelines-like document with chapter ``div``s."""
    return bool(list(iter_guideline_chapters(root)))


def iter_guideline_chapters(root: etree._Element):
    """Yield top-level front/body/back ``div``s used as Guidelines chapters.

    Dedication / title-page verso and other typed front ``div``s are included,
    and so are the A–Z catalog stubs ``opm odd document`` puts in back matter:
    they are its appendices. The home page it adds sits directly under
    ``text``, outside all three parts, so it is never one.
    """
    text = root.find(f'.//{qn("text")}')
    if text is None:
        # Default namespace documents still match via local-name walks below.
        text = next((el for el in root.iter() if localname(el) == 'text'), None)
    if text is None:
        return
    for part_name in ('front', 'body', 'back'):
        for part in text:
            if localname(part) != part_name:
                continue
            for child in part:
                if localname(child) != 'div':
                    continue
                yield child


def compile_schema(
    path: Path | str | None = None,
    *,
    use_guidelines: bool = False,
    fetch: bool = True,
    p5all_url: str | None = None,
) -> CompiledSchema:
    """Load *path* and merge it along ``schemaSpec/@source``.

    * Parent ODDs are applied first, then the local file — the same order
      [`parse_odd`][opm.odd_compiler.parse_odd] uses for processing models.
    * A TEI-targeting ODD (``schemaSpec/@ns`` absent or the TEI namespace) is
      merged onto the cached TEI artifact so ``moduleRef`` and content models
      resolve. It tracks TEI's latest release; an ODD pinning an older
      ``TEI/@version`` is compiled against the latest with a warning. JATS /
      DocBook set a different ``@ns`` and are left alone.
    * ``use_guidelines`` documents TEI alone.
    * A compiled document (Guidelines ``p5.xml``, ``p5subset.xml``, a directory
      of Specs) with no further inheritance is returned as-is.
    * Chapter prose from the input is always kept. When the input *is* the
      schema being documented (``use_guidelines``, a Guidelines ``p5.xml``, a Specs
      directory) its chapters are published too. A customization merged onto
      TEI documents itself, so TEI's chapters stay out of its site.
    """
    warnings: list[str] = []
    fetched: Path | None = None

    input_path: Path | None = Path(path).resolve() if path else None
    if input_path is None and not use_guidelines:
        raise SchemaError(
            'Pass an ODD / compiled spec document, or --guidelines to document the TEI schema.'
        )

    root: etree._Element | None = None
    if input_path is not None:
        root = load_xml(input_path)

    if (
        root is not None
        and _is_standalone_spec_document(
            root, input_path, use_guidelines=use_guidelines,
        )
    ):
        tree = _apply_prose(
            root,
            _prose_document(
                root, None, documenting_base=True,
            ),
        )
        return CompiledSchema(
            tree=tree,
            source_path=input_path,
            title=_title_of(root, input_path),
            warnings=warnings,
        )

    chain: list[Path] = []
    if input_path is not None and input_path.is_file():
        chain = _inheritance_chain(input_path)

    source_root: etree._Element | None = None
    source_path: Path | None = None
    need_tei = use_guidelines or (
        root is not None
        and (_schema_source_is_tei(root) or targets_tei(root))
    )
    if need_tei:
        fetched = ensure_p5all(fetch=fetch, url=p5all_url)
        source_root = load_xml(fetched)
        source_path = fetched
        warnings.append(f'Using the TEI schema from {fetched}')
        warnings.extend(
            _version_pin_notes(_requested_tei_version(root, chain), source_root)
        )

    skip = source_path.resolve() if source_path is not None else None
    if source_root is not None:
        tree = source_root
        overlays = [p for p in chain if skip is None or p.resolve() != skip]
        if not overlays and input_path is not None and input_path.is_file():
            if skip is None or input_path.resolve() != skip:
                overlays = [input_path]
    elif chain:
        tree = load_xml(chain[0])
        overlays = chain[1:]
    elif root is not None:
        schema = _main_schema_spec(root)
        if schema is not None and schema.find(qn('moduleRef')) is not None:
            raise SchemaError(
                f'{input_path} uses moduleRef but no schema source was found. '
                'A TEI customization is merged onto the TEI schema automatically; '
                'this ODD neither targets TEI nor declares its own modules with '
                'moduleSpec.'
            )
        tree = _apply_prose(
            root,
            _prose_document(
                root, None, documenting_base=True,
            ),
        )
        return CompiledSchema(
            tree=tree,
            source_path=input_path,
            title=_title_of(root, input_path),
            warnings=warnings,
        )
    else:
        raise SchemaError(
            'Pass an ODD / compiled spec document, or --guidelines to document the TEI schema.'
        )

    for overlay_path in overlays:
        overlay = root if overlay_path == input_path else load_xml(overlay_path)
        tree = _odd2odd(tree, overlay)

    title_root = root if root is not None else tree
    title = _title_of(title_root, input_path) or _title_of(tree, source_path)
    tree = _apply_prose(
        tree,
        _prose_document(
            root,
            source_root,
            # With no customization applied, the source document is itself what
            # we are documenting, so its chapters are the site's chapters.
            documenting_base=root is None,
        ),
    )
    return CompiledSchema(
        tree=tree,
        source_path=input_path or source_path,
        title=title,
        warnings=warnings,
        fetched_source=fetched,
        ident=schema_ident(title_root, input_path) if title_root is not None else '',
    )


def _prose_document(
    root: etree._Element | None,
    schema_base: etree._Element | None,
    *,
    documenting_base: bool,
) -> etree._Element | None:
    """Document whose chapter prose the compiled tree should carry, if any.

    The input wins when it already has chapter prose — a Guidelines ``p5.xml``,
    or a project ODD with chapters of its own. Otherwise the schema source
    supplies it, but only when there is no customization: the TEI artifact
    always carries the Guidelines, and a customization documents itself rather
    than republishing all of TEI alongside its own schema.
    """
    if root is not None and chapters_have_prose(root):
        return root
    if documenting_base and schema_base is not None and chapters_have_prose(schema_base):
        return schema_base
    return None


def chapters_have_prose(root: etree._Element) -> bool:
    """True when guideline chapters contain prose outside specification elements.

    ``p5subset.xml`` keeps the division/heading skeleton (and inlined specs)
    but strips ordinary chapter paragraphs — those chapters must not be treated
    as a full Guidelines document.
    """
    return any(chapter_has_prose(div) for div in iter_guideline_chapters(root))


_PROSE_TAGS = {'p', 'list', 'table', 'lg', 'titlePage'}


def chapter_has_prose(div: etree._Element) -> bool:
    """True when *div* has ordinary prose, not only inlined specs.

    Front matter such as the title-page verso is often a ``list`` with no
    ``p``; those still belong on the site.
    """
    for el in div.iter():
        if not isinstance(el.tag, str) or localname(el) not in _PROSE_TAGS:
            continue
        if _inside_spec_documentation(el):
            continue
        return True
    return False


def _inside_spec_documentation(el: etree._Element) -> bool:
    """True when *el* sits under a Spec / attDef / remarks / exemplum / desc."""
    node: etree._Element | None = el
    while node is not None:
        name = localname(node)
        if name.endswith('Spec') or name in {
            'attDef', 'valList', 'constraintSpec', 'content', 'classes',
            'exemplum', 'remarks', 'desc', 'gloss', 'altIdent', 'equiv',
        }:
            return True
        parent = node.getparent()
        node = parent if isinstance(parent, etree._Element) else None
    return False


def schema_ident(root: etree._Element, path: Path | None = None) -> str:
    """``schemaSpec/@ident``, else the source file stem, else ``schema``."""
    schema = _main_schema_spec(root)
    if schema is not None:
        ident = (schema.get('ident') or '').strip()
        if ident:
            return ident
    if path is not None:
        stem = path.stem.strip()
        if stem and stem not in {'.', '..'}:
            return stem
    return 'schema'


def _main_schema_spec(root: etree._Element) -> etree._Element | None:
    """The customization ``schemaSpec``, skipping examples inside ``egXML``."""
    for el in root.iter(qn('schemaSpec')):
        if not _inside_egxml(el):
            return el
    return None


def _schema_tokens(root: etree._Element) -> list[str]:
    schema = _main_schema_spec(root)
    if schema is None:
        return []
    return (schema.get('source') or '').split()


def _schema_source_is_tei(root: etree._Element) -> bool:
    for token in _schema_tokens(root):
        name = Path(token.split('?')[0]).name.lower()
        if name in _TEI_SOURCE_TOKENS or (
            token.startswith('http') and 'tei' in token.lower()
        ):
            return True
    return False


def _tei_root_version(root: etree._Element | None) -> str | None:
    if root is None:
        return None
    el = root if localname(root) == 'TEI' else next(
        (e for e in root.iter() if localname(e) == 'TEI'), None,
    )
    if el is None:
        return None
    value = (el.get('version') or '').strip()
    return value or None


def _requested_tei_version(root: etree._Element | None, chain: list[Path]) -> str:
    """``TEI/@version`` on the input, then ancestors; else ``current``."""
    raw = _tei_root_version(root)
    if not raw:
        for path in reversed(chain[:-1] if chain else []):
            try:
                raw = _tei_root_version(load_xml(path))
            except SchemaError:
                continue
            if raw:
                break
    return normalize_tei_version(raw)


def _version_pin_notes(
    requested: str, base: etree._Element | None,
) -> list[str]:
    """Warn when an ODD pins a TEI release the single artifact cannot serve.

    ``TEI/@version`` used to select a Vault snapshot. There is one artifact
    now, tracking TEI's latest release, so a pin is reported rather than
    silently honoured — a customization written against an older TEI may
    reference specs that release no longer has.
    """
    if requested == 'current' or base is None:
        return []
    actual = (base.get('version') or '').strip()
    if not actual or actual == requested:
        return []
    return [
        f'This ODD asks for TEI {requested}, but opm documents against one '
        f'pinned TEI release ({actual}) and will compile against that.'
    ]


def _is_standalone_spec_document(
    root: etree._Element,
    path: Path | None,
    *,
    use_guidelines: bool,
) -> bool:
    """True when *root* is already the document to index (no merge).

    An ODD that targets TEI is always a customization, however many specs of
    its own it adds, so it merges onto p5subset. Everything else already is
    the schema: a Specs directory, a compiled spec document (``p5subset`` /
    Guidelines ``p5.xml``, which carry no ``schemaSpec``), a hand-authored
    schema that *declares* its modules with ``moduleSpec`` instead of
    referencing TEI's with ``moduleRef``, and JATS / DocBook ODDs, which
    declare a non-TEI ``@ns``.
    """
    if use_guidelines:
        return False
    if path is not None and path.is_dir():
        return True
    schema = _main_schema_spec(root)
    if schema is None:
        return True
    if schema.find(qn('moduleSpec')) is not None:
        return True
    return not targets_tei(root)


def _inheritance_chain(odd_path: Path, *, seen: set[Path] | None = None) -> list[Path]:
    """Parent ODDs first, then *odd_path*. Skips TEI tokens and missing files."""
    odd_path = odd_path.resolve()
    seen = seen if seen is not None else set()
    if odd_path in seen:
        raise SchemaError(
            f'Circular ODD inheritance via schemaSpec@source: {odd_path}'
        )
    if not odd_path.is_file():
        return []
    seen.add(odd_path)
    try:
        root = load_xml(odd_path)
    except SchemaError:
        seen.remove(odd_path)
        return []
    chain: list[Path] = []
    for token in _schema_tokens(root):
        raw = token.split('?')[0]
        name = Path(raw).name.lower()
        if name in _TEI_SOURCE_TOKENS or token.startswith('http'):
            continue
        try:
            resolved = resolve_schema_source(token, odd_path)
        except FileNotFoundError:
            continue
        if resolved.is_file() and resolved.resolve() != odd_path:
            chain.extend(_inheritance_chain(resolved, seen=seen))
    chain.append(odd_path)
    seen.remove(odd_path)
    return chain


def _title_of(root: etree._Element, path: Path | None) -> str:
    header = root.find(
        f'.//{qn("teiHeader")}/{qn("fileDesc")}/{qn("titleStmt")}/{qn("title")}'
    )
    if header is not None:
        text = ''.join(header.itertext()).strip()
        if text:
            return text.split('\n')[0].strip()
    schema = _main_schema_spec(root)
    if schema is not None and schema.get('ident'):
        return schema.get('ident') or ''
    return path.stem if path else ''


def _load_spec_directory(path: Path) -> etree._Element:
    tei = etree.Element(qn('TEI'), nsmap={None: TEI_NS})
    text = etree.SubElement(tei, qn('text'))
    body = etree.SubElement(text, qn('body'))
    schema = etree.SubElement(body, qn('schemaSpec'), ident=path.name)
    files = sorted(path.rglob('*.xml')) + sorted(path.rglob('*.odd'))
    for file in files:
        try:
            root = etree.parse(str(file), _PARSER).getroot()
        except etree.XMLSyntaxError:
            continue
        for spec, _kind in iter_canonical_specs(root):
            schema.append(_copy(spec))
    if not list(schema):
        raise SchemaError(f'No specification elements found under {path}')
    return tei


def _copy(el: etree._Element) -> etree._Element:
    return etree.fromstring(etree.tostring(el, with_tail=False))


def _specs_by_ident(root: etree._Element) -> dict[str, etree._Element]:
    out: dict[str, etree._Element] = {}
    for el, _kind in iter_canonical_specs(root):
        ident = el.get('ident')
        if not ident:
            continue
        previous = out.get(ident)
        if previous is None or (el.get('module') and not previous.get('module')):
            out[ident] = el
    return out


def _odd2odd(source: etree._Element, customization: etree._Element) -> etree._Element:
    """Subset *source* by ``moduleRef`` and apply local spec ``@mode``.

    The result is a bare ``TEI/text/body/schemaSpec`` holding the merged specs.
    Chapter prose is a separate concern — see [`_apply_prose`][opm.odd_schema._apply_prose].
    """
    selected = _specs_by_ident(source)
    schema = _main_schema_spec(customization)
    if schema is not None:
        all_specs = dict(selected)
        # Filter, then let the customization have its say, and only then close
        # over what is left. The closure has to see the content models the ODD
        # actually declares: a customization that rewrites `text` to hold a
        # pair of texts no longer references front/back/group, and subsetting
        # from the stock model would pull all three back in behind its back.
        selected = _apply_module_refs(selected, schema, close=False)
        selected = _apply_local_specs(selected, schema)
        if any(localname(el) == 'moduleRef' for el in schema):
            all_specs.update(selected)
            selected = _dependency_closure(all_specs, selected)
    return _wrap_specs(
        selected, ident=(schema.get('ident') if schema is not None else None)
    )


def _apply_prose(
    tree: etree._Element,
    prose_doc: etree._Element | None,
) -> etree._Element:
    """Move *tree*'s specs into *prose_doc*, so the result carries both.

    Which specs a schema has and which chapters document them come from
    different places: the specs from the ``moduleRef`` / ``@mode`` merge, the
    prose from the input itself or from the downloaded Guidelines. This is
    where the two meet, and it is the only place chapters enter the compiled
    tree. Returns *tree* unchanged when there is no prose to carry.
    """
    if prose_doc is None:
        return tree
    return _merge_specs_into_document(
        prose_doc,
        _specs_by_ident(tree),
        ident=schema_ident(tree) or None,
    )


def _merge_specs_into_document(
    source: etree._Element,
    selected: dict[str, etree._Element],
    *,
    ident: str | None,
) -> etree._Element:
    """Rewrite *source*'s specs to *selected*, keeping prose and spec positions.

    The Guidelines and ``p5subset.xml`` scatter their specs through the body
    chapters that document them rather than collecting them in a
    ``schemaSpec``. Specs the customization dropped are removed where they
    stand, specs it kept or changed are replaced in place, and specs it added
    land in a ``schemaSpec`` appended to ``text/body``. An ident the document
    repeats keeps only its first occurrence, so the result has no duplicate
    specs to disambiguate later.
    """
    doc = deepcopy(source)
    remaining = dict(selected)
    for el, _kind in list(iter_canonical_specs(doc)):
        spec_ident = el.get('ident')
        parent = el.getparent()
        if not spec_ident or parent is None:
            continue
        replacement = remaining.pop(spec_ident, None)
        if replacement is None:
            parent.remove(el)
            continue
        merged = _copy(replacement)
        merged.tail = el.tail
        parent.replace(el, merged)
    if remaining:
        body = _ensure_body_element(doc)
        schema = etree.SubElement(body, qn('schemaSpec'), ident=ident or 'compiled')
        for spec in sorted(remaining.values(), key=lambda el: el.get('ident') or ''):
            schema.append(_copy(spec))
    return doc


def _ensure_body_element(doc: etree._Element) -> etree._Element:
    """``text/body`` of *doc*, created when the document has neither."""
    text = next((el for el in doc.iter() if localname(el) == 'text'), None)
    if text is None:
        text = etree.SubElement(doc, qn('text'))
    body = next((el for el in text if localname(el) == 'body'), None)
    if body is None:
        body = etree.SubElement(text, qn('body'))
    return body


def _module_ref_filters(ref: etree._Element) -> tuple[set[str], set[str]]:
    """Return ``(include, except)`` ident sets for one ``moduleRef``."""
    include = set((ref.get('include') or '').split())
    excepted = set((ref.get('except') or '').split())
    for child in ref:
        names = {c.get('ident') for c in child.iter() if c.get('ident')}
        names.discard(None)
        if localname(child) == 'include':
            include.update(n for n in names if n)
        elif localname(child) == 'except':
            excepted.update(n for n in names if n)
    return include, excepted


def _apply_module_refs(
    specs: dict[str, etree._Element],
    schema: etree._Element,
    *,
    close: bool = True,
) -> dict[str, etree._Element]:
    refs = [el for el in schema if localname(el) == 'moduleRef']
    if not refs:
        return specs
    keep: dict[str, etree._Element] = {}
    for ref in refs:
        module = ref.get('key')
        include, excepted = _module_ref_filters(ref)
        for ident, el in specs.items():
            if module and el.get('module') != module:
                continue
            if include and ident not in include:
                continue
            if ident in excepted:
                continue
            keep[ident] = el
    return _dependency_closure(specs, keep) if close else keep


def _dependency_closure(
    all_specs: dict[str, etree._Element],
    keep: dict[str, etree._Element],
) -> dict[str, etree._Element]:
    changed = True
    while changed:
        changed = False
        needed: set[str] = set()
        for el in keep.values():
            needed.update(_referenced_idents(el))
            classes = el.find(qn('classes'))
            if classes is not None:
                for member in classes:
                    if localname(member) == 'memberOf' and member.get('key'):
                        needed.add(member.get('key') or '')
        for ident in needed:
            if ident and ident in all_specs and ident not in keep:
                keep[ident] = all_specs[ident]
                changed = True
    return keep


def _referenced_idents(el: etree._Element) -> set[str]:
    keys: set[str] = set()
    content = el.find(qn('content'))
    if content is None:
        return keys
    for child in content.iter():
        tag = localname(child)
        if tag in {'elementRef', 'classRef', 'macroRef'} and child.get('key'):
            keys.add(child.get('key') or '')
        elif tag == 'dataRef' and (child.get('key') or child.get('name')):
            keys.add(child.get('key') or child.get('name') or '')
    return keys


def _apply_local_specs(
    specs: dict[str, etree._Element],
    schema: etree._Element,
) -> dict[str, etree._Element]:
    out = dict(specs)
    for el in schema.iter():
        if localname(el) not in _SPEC_TAGS:
            continue
        if el.getparent() is not None and localname(el.getparent()) in {
            'except',
            'include',
        }:
            continue
        if _inside_egxml(el):
            continue
        ident = el.get('ident')
        if not ident:
            continue
        mode = (el.get('mode') or 'replace').lower()
        if mode == 'delete':
            out.pop(ident, None)
        elif ident in out and mode in {'add', 'change'}:
            # add on an existing ident is treated as change: keep schema
            # content from the parent and overlay models / atts / desc.
            out[ident] = _merge_change(_copy(out[ident]), el)
        elif mode == 'add':
            out[ident] = _copy(el)
        else:  # replace, or change with no source spec
            out[ident] = _copy(el)
    return out


def _merge_change(base: etree._Element, overlay: etree._Element) -> etree._Element:
    """Merge a ``mode=change`` spec onto *base* (already a copy)."""
    if overlay.get('module'):
        base.set('module', overlay.get('module') or '')
    for child in overlay:
        tag = localname(child)
        if tag == 'classes':
            _merge_classes(base, child)
        elif tag == 'attList':
            _merge_att_list(base, child)
        elif tag == 'content':
            _replace_child(base, 'content', child)
        elif tag in {'desc', 'gloss', 'remarks'}:
            _replace_lang_child(base, tag, child)
        elif tag in {'exemplum', 'constraintSpec', 'listRef'}:
            base.append(_copy(child))
        elif tag in _MODEL_TAGS:
            continue
        else:
            _replace_child(base, tag, child)
    _merge_models(base, overlay)
    return base


def _merge_models(base: etree._Element, overlay: etree._Element) -> None:
    """Replace processing models when the overlay declares any."""
    incoming = [c for c in overlay if localname(c) in _MODEL_TAGS]
    if not incoming:
        return
    for child in list(base):
        if localname(child) in _MODEL_TAGS:
            base.remove(child)
    for model in incoming:
        base.append(_copy(model))


def _merge_classes(base: etree._Element, overlay: etree._Element) -> None:
    classes = base.find(qn('classes'))
    if classes is None:
        base.append(_copy(overlay))
        return
    existing = {
        m.get('key'): m for m in classes if localname(m) == 'memberOf' and m.get('key')
    }
    for member in overlay:
        if localname(member) != 'memberOf' or not member.get('key'):
            continue
        key = member.get('key') or ''
        mode = (member.get('mode') or 'add').lower()
        if mode == 'delete':
            old = existing.pop(key, None)
            if old is not None:
                classes.remove(old)
        else:
            if key in existing:
                classes.remove(existing[key])
            copied = _copy(member)
            classes.append(copied)
            existing[key] = copied


def _merge_att_list(base: etree._Element, overlay: etree._Element) -> None:
    att_list = base.find(qn('attList'))
    if att_list is None:
        base.append(_copy(overlay))
        return
    existing = {
        a.get('ident'): a for a in att_list.iter(qn('attDef')) if a.get('ident')
    }
    for att in overlay.iter(qn('attDef')):
        ident = att.get('ident')
        if not ident:
            continue
        mode = (att.get('mode') or 'replace').lower()
        old = existing.get(ident)
        if mode == 'delete':
            if old is not None:
                parent = old.getparent()
                if parent is not None:
                    parent.remove(old)
                existing.pop(ident, None)
            # Keep a mode=delete marker so inherited attributes can be suppressed.
            att_list.append(_copy(att))
            continue
        elif mode == 'change' and old is not None:
            _merge_change(old, att)
        else:
            copied = _copy(att)
            if old is not None:
                parent = old.getparent()
                if parent is not None:
                    parent.replace(old, copied)
            else:
                att_list.append(copied)
            existing[ident] = copied


def _replace_child(base: etree._Element, tag: str, overlay: etree._Element) -> None:
    old = base.find(qn(tag))
    copied = _copy(overlay)
    if old is None:
        base.append(copied)
    else:
        base.replace(old, copied)


def _replace_lang_child(
    base: etree._Element, tag: str, overlay: etree._Element
) -> None:
    lang = overlay.get('{http://www.w3.org/XML/1998/namespace}lang')
    for old in list(base):
        if localname(old) != tag:
            continue
        if lang and old.get('{http://www.w3.org/XML/1998/namespace}lang') not in {
            None,
            lang,
        }:
            continue
        base.remove(old)
        break
    base.append(_copy(overlay))


def _wrap_specs(
    specs: dict[str, etree._Element], *, ident: str | None
) -> etree._Element:
    tei = etree.Element(qn('TEI'), nsmap={None: TEI_NS})
    text = etree.SubElement(tei, qn('text'))
    body = etree.SubElement(text, qn('body'))
    schema = etree.SubElement(body, qn('schemaSpec'), ident=ident or 'compiled')
    for spec in sorted(specs.values(), key=lambda el: el.get('ident') or ''):
        schema.append(_copy(spec) if spec.getroottree() is not None else spec)
    return tei
