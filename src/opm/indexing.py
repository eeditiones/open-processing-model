# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Roll the JSON output mode's records up into embedding-sized index units.

``opm transform -t json`` records every decision the processing model made,
which is the right shape for debugging an ODD and the wrong shape for a search
index: one record per table cell is not something you embed, and a nested tree
has no stable identity to upsert against.

This module bridges the two. It walks the record tree, groups it at section
boundaries, and emits one JSONL line per retrievable unit with a flat
metadata map: scalars for labels, arrays of strings for extracted names
and the like.

Indexing the processing model rather than the source is the whole point: the
ODD has already decided what the reader sees. ``omit`` drops the apparatus,
``alternate`` picks the displayed reading, templates expand abbreviations. An
XPath scrape of the same TEI would index
``<choice><abbr>Mr</abbr><expan>Mister</expan></choice>`` as ``MrMister``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree

if TYPE_CHECKING:
    from opm.config import ProjectConfig

# Behaviours that open a new retrievable unit.
_UNIT_BOUNDARIES = frozenset({'section', 'body', 'document'})

# Behaviours whose own text is a heading rather than prose.
_HEADING_BEHAVIOURS = frozenset({'heading', 'title'})

# Behaviours that make a reasonable split point inside an oversized unit.
_SPLIT_BOUNDARIES = frozenset({'paragraph', 'block', 'list_item', 'cit', 'note'})

_TITLE_XPATH = {
    'tei': '(//teiHeader/fileDesc/titleStmt/title)[1]',
    'docbook': '(/article/info/title, /book/info/title)[1]',
    'jats': '(/article/front/article-meta/title-group/article-title)[1]',
}

_WS_RE = re.compile(r'\s+')


@dataclass(frozen=True)
class FieldSpec:
    """Material to pull out of a passage: a facet, a passage of its own, or page chrome.

    A note and a person name are the same operation — recognise a record, take
    its text — differing only in where the text goes. ``metadata=True`` copies
    it onto the passage as a list of distinct strings, for filtering;
    ``metadata=False`` emits it as its own retrievable record tagged ``kind``
    and linked to its parent, and whether a search engine indexes those is
    then a filter at load time rather than a decision baked into the file.

    ``inline`` is the one choice that cannot be deferred: it decides whether the
    text stays in the containing passage's embedded ``document`` string. It
    defaults to *metadata*, which is what each case usually wants — a name reads
    as part of the sentence, an extracted note does not — and can be set
    explicitly to keep a fragment in both places.

    ``fragment`` is a different source: the name of a ``[[chunking.fragments]]``
    entry. That HTML is transformed once per page (or once per document when
    the fragment is global), stripped to a scalar, and copied onto every
    record from that page. It cannot be mixed with a JSON selector, and it is
    always metadata — never a hit of its own.
    """

    name: str
    behaviours: frozenset[str] = frozenset()
    elements: frozenset[str] = frozenset()
    models: frozenset[str] = frozenset()
    fragment: str | None = None
    """``[[chunking.fragments]]`` name; when set, the other selectors stay empty."""
    metadata: bool = True
    inline: bool | None = None

    @property
    def keeps_text_inline(self) -> bool:
        return self.metadata if self.inline is None else self.inline

    def matches(self, record: dict) -> bool:
        if self.fragment:
            return False
        return _matches(record, self.behaviours, self.elements, self.models)


@dataclass(frozen=True)
class UnitSpec:
    """A JSON record that opens a retrievable passage.

    When ``[[index.units]]`` is present it *replaces* the default titled-division
    walk: only matching records become units, and unmatched structure is walked
    through so nested paragraphs (or whatever you selected) can still be found.

    ``name`` is stored as ``metadata.kind``. ``emit=False`` uses the match only
    as context — typically a heading that labels the following paragraph — and
    writes no JSONL line of its own. ``min_chars`` overrides the global floor
    for records this spec emits.
    """

    name: str
    behaviours: frozenset[str] = frozenset()
    elements: frozenset[str] = frozenset()
    models: frozenset[str] = frozenset()
    emit: bool = True
    min_chars: int | None = None

    def matches(self, record: dict) -> bool:
        return _matches(record, self.behaviours, self.elements, self.models)


def _matches(
    record: dict,
    behaviours: frozenset[str],
    elements: frozenset[str],
    models: frozenset[str],
) -> bool:
    return (
        record.get('behaviour') in behaviours
        or record.get('element') in elements
        or record.get('model') in models
    )


@dataclass
class IndexOptions:
    """Tuning for the rollup. Defaults suit prose in a general-purpose embedder."""

    max_chars: int = 1500
    min_chars: int = 40
    overlap: int = 1
    """Trailing split-boundary records carried into the next part, for context."""
    fields: tuple[FieldSpec, ...] = ()
    """``[[index.fields]]`` — a JSON-record facet, a child record, or a chunking fragment."""
    units: tuple[UnitSpec, ...] = ()
    """``[[index.units]]`` — records that open a passage; empty keeps titled divisions."""


@dataclass
class _Unit:
    """One retrievable passage, before it is split and serialised."""

    xml_id: str | None
    xpath: str | None
    heading: str | None
    entry_anchor: str | None = None
    """Last ``xml:id`` seen before this unit opened — the page it starts on."""
    parts: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    """``(text, xml_id, xpath)`` per contributing record, so a split keeps its anchor."""
    kind: str | None = None
    """Name of the [`FieldSpec`][opm.indexing.FieldSpec] or [`UnitSpec`][opm.indexing.UnitSpec] this unit came from."""
    parent: '_Unit | None' = None
    """The passage an extracted unit was taken out of."""
    fields: dict[str, list[str]] = field(default_factory=dict)
    """Extracted values destined for this unit's metadata, in document order."""
    min_chars: int | None = None
    """Per-unit floor; ``None`` uses [`IndexOptions.min_chars`][opm.indexing.IndexOptions.min_chars]."""

    @property
    def text(self) -> str:
        return _clean(' '.join(t for t, _, _ in self.parts))

    def anchor(self) -> tuple[str | None, str | None]:
        """The id and path this unit is named by.

        A container's own ``xml:id`` wins. Falling back to the *first
        contributing record* rather than the container matters when a boundary
        nests: two units would otherwise share the container's path and collide
        on the same generated id.
        """
        if self.xml_id:
            return self.xml_id, self.xpath
        for _, xml_id, xpath in self.parts:
            if xml_id:
                return xml_id, xpath
        first_path = self.parts[0][2] if self.parts else self.xpath
        return None, first_path or self.xpath


def _clean(text: str) -> str:
    return _WS_RE.sub(' ', text).strip()


def document_title(root: etree._Element) -> str | None:
    """Best-effort document title across the vocabularies opm ships ODDs for."""
    from opm.transform import xpath_select

    for expr in _TITLE_XPATH.values():
        try:
            result = xpath_select(root, expr)
        except Exception:  # noqa: BLE001 — a vocabulary mismatch is expected here
            continue
        if isinstance(result, list):
            result = result[0] if result else None
        if isinstance(result, etree._Element):
            text = _clean(''.join(result.itertext()))
            if text:
                return text
        elif result:
            text = _clean(str(result))
            if text:
                return text
    return None


# ── rollup ───────────────────────────────────────────────────────────────────

class _Walker:
    """Carries the open unit and the running anchor across one document's walk.

    The open unit lives here rather than being passed down and returned, so a
    nested boundary closes the enclosing unit exactly once. Recursing with the
    parent unit as an argument re-emitted it after every nested boundary and
    collided their ids.
    """

    def __init__(
        self,
        fields: tuple[FieldSpec, ...] = (),
        unit_specs: tuple[UnitSpec, ...] = (),
    ) -> None:
        self.fields = tuple(f for f in fields if not f.fragment)
        self.unit_specs = unit_specs
        self.units: list[_Unit] = []
        self.extracted: list[_Unit] = []
        """Units lifted out by a ``metadata=False`` field, parents first at emit time."""
        self.current: _Unit | None = None
        self.last_anchor: str | None = None
        """Most recent ``xml:id`` seen in document order.

        Page-based editions hang their ids on empty ``<pb/>`` milestones, which
        contribute no text and so never anchor a unit of their own. Remembering
        the last one lets a passage link to the page it starts on.
        """
        self.running_heading: str | None = None
        """Heading last seen from a unit spec — labels following paragraphs."""

    def finish(self) -> list[_Unit]:
        if self.current is not None and self.current.parts:
            self.units.append(self.current)
        return self.units

    def collect(self, record: dict) -> None:
        # Suppressed content is what the ODD decided the reader does not see;
        # it is exactly what must not reach the index.
        if record.get('suppressed'):
            return

        if record.get('id'):
            self.last_anchor = record['id']

        specs = [f for f in self.fields if f.matches(record)]
        if specs:
            keep_inline = False
            for spec in specs:
                self.extract(record, spec)
                keep_inline = keep_inline or spec.keeps_text_inline
            if not keep_inline:
                # The text belongs to the facet or the extracted record only;
                # walking on would embed it in the containing passage as well.
                return

        spec = next((u for u in self.unit_specs if u.matches(record)), None)
        if spec is not None:
            self.open_specified(record, spec)
            return

        if self.unit_specs:
            # Custom units replace the default walk: unmatched records are
            # structure to look through, not a catch-all passage.
            self.descend(record)
            return

        heading = _first_heading(record)
        # A named behaviour is not enough on its own: ODDs differ on whether an
        # act or a chapter gets `section` or plain `block`, but a division that
        # carries a heading is a retrievable unit in either.
        if record.get('behaviour') in _UNIT_BOUNDARIES or heading is not None:
            self.open(record, heading)
            return

        if self.current is None:
            self.current = _Unit(
                xml_id=record.get('id'),
                xpath=record.get('xpath'),
                heading=None,
                entry_anchor=self.last_anchor,
            )
        self.descend(record)

    def extract(self, record: dict, spec: FieldSpec) -> None:
        """Take a record's text out as a facet value or as a unit of its own."""
        text = _record_text(record)
        if not text:
            return
        if spec.metadata:
            if self.current is not None:
                values = self.current.fields.setdefault(spec.name, [])
                if text not in values:  # a name repeated in one passage is one facet
                    values.append(text)
            return
        unit = _Unit(
            xml_id=record.get('id'),
            xpath=record.get('xpath'),
            heading=None,
            entry_anchor=self.last_anchor,
            kind=spec.name,
            parent=self.current,
        )
        unit.parts.append((text, record.get('id'), record.get('xpath')))
        self.extracted.append(unit)

    def open_specified(self, record: dict, spec: UnitSpec) -> None:
        """Open (or remember) a unit declared in ``[[index.units]]``."""
        own_heading = (
            _record_text(record)
            if record.get('behaviour') in _HEADING_BEHAVIOURS
            else _first_heading(record)
        )
        self._remember_heading(own_heading)
        if not spec.emit:
            if self.current is not None and self.current.parts:
                self.units.append(self.current)
            self.current = None
            return
        self.open(
            record,
            own_heading or self.running_heading,
            kind=spec.name,
            min_chars=spec.min_chars,
        )
        # A specified unit is exactly this record's subtree, so close it before
        # a sibling (a block that is not itself a unit) can leak into it.
        if self.current is not None:
            if self.current.parts:
                self.units.append(self.current)
            self.current = None

    def _remember_heading(self, heading: str | None) -> None:
        if heading:
            self.running_heading = heading

    def open(
        self,
        record: dict,
        heading: str | None,
        *,
        kind: str | None = None,
        min_chars: int | None = None,
    ) -> None:
        if self.current is not None and self.current.parts:
            self.units.append(self.current)
        self.current = _Unit(
            xml_id=record.get('id'),
            xpath=record.get('xpath'),
            heading=heading,
            entry_anchor=self.last_anchor,
            kind=kind,
            min_chars=min_chars,
        )
        self.descend(record)

    def descend(self, record: dict) -> None:
        # `children` interleaves this record's own text runs with its child
        # records in source order, and is the only place text lives. A record
        # with no children produced no text, so it contributes nothing.
        for child in record.get('children', ()):
            if isinstance(child, dict):
                self.collect(child)
            elif isinstance(child, str):
                self.add(child, record)

    def add(self, text: str, record: dict) -> None:
        text = _clean(text)
        if text and self.current is not None:
            self.current.parts.append(
                (text, record.get('id'), record.get('xpath')),
            )


def _iter_units(document: list, options: IndexOptions) -> tuple[list[_Unit], list[_Unit]]:
    """Walk one document's record roots into ``(units, extracted units)``.

    One walker spans every root so an open unit and the running anchor survive
    the boundary between them.
    """
    walker = _Walker(options.fields, options.units)
    for root in document:
        if isinstance(root, dict):
            walker.collect(root)
    return walker.finish(), walker.extracted


def _first_heading(record: dict) -> str | None:
    for child in record.get('children', []):
        if isinstance(child, dict) and child.get('behaviour') in _HEADING_BEHAVIOURS:
            text = _record_text(child)
            if text:
                return text
    return None


def _record_text(record: dict) -> str:
    """Full text of a record's subtree — used for headings, which are short."""
    parts: list[str] = []
    for child in record.get('children', ()):
        if isinstance(child, str):
            parts.append(child)
        elif isinstance(child, dict) and not child.get('suppressed'):
            parts.append(_record_text(child))
    return _clean(' '.join(parts))


def _split(
    unit: _Unit, options: IndexOptions,
) -> list[tuple[str, str | None, str | None]]:
    """Split an oversized unit at record boundaries, with overlap."""
    anchor_id, anchor_path = unit.anchor()
    if len(unit.text) <= options.max_chars:
        return [(unit.text, anchor_id, anchor_path)]

    def close(buffer: list) -> tuple[str, str | None, str | None]:
        text = _clean(' '.join(p for p, _, _ in buffer))
        for _, xml_id, xpath in buffer:
            if xml_id:
                return text, xml_id, xpath
        return text, anchor_id, buffer[0][2] if buffer else anchor_path

    chunks: list[tuple[str, str | None, str | None]] = []
    buffer: list[tuple[str, str | None, str | None]] = []
    size = 0
    for piece in unit.parts:
        if buffer and size + len(piece[0]) + 1 > options.max_chars:
            chunks.append(close(buffer))
            buffer = buffer[-options.overlap:] if options.overlap else []
            size = sum(len(p) + 1 for p, _, _ in buffer)
        buffer.append(piece)
        size += len(piece[0]) + 1
    if buffer:
        chunks.append(close(buffer))
    return chunks


# ── record assembly ──────────────────────────────────────────────────────────

def _record_id(
    doc_stem: str,
    xml_id: str | None,
    xpath: str | None,
    scope: str | None = None,
) -> str:
    """A stable id, so re-indexing upserts in place instead of orphaning rows.

    An ``xml:id`` survives edits elsewhere in the document, so it is preferred
    and deliberately not scoped to a chunk — the same passage keeps its id even
    if re-chunking moves it to another page. Falling back to a hash of the
    XPath is weaker (it moves when a sibling is inserted) but is at least
    deterministic for an unchanged document, which a positional counter is not;
    *scope* keeps two chunks with the same internal path apart.
    """
    if xml_id:
        return f'{doc_stem}#{xml_id}'
    digest = hashlib.sha1(f'{scope or ""}|{xpath or ""}'.encode()).hexdigest()[:12]
    return f'{doc_stem}#{digest}'


def build_records(
    document: list,
    *,
    doc_stem: str,
    source: str,
    title: str | None = None,
    anchors: dict[str, str] | None = None,
    chunk_file: str | None = None,
    page_metadata: dict[str, str] | None = None,
    options: IndexOptions | None = None,
) -> list[dict]:
    """Turn one document's (or one chunk's) JSON-mode records into index records.

    *page_metadata* is copied onto every record — values already stripped to
    scalars, typically from ``fragment`` fields evaluated once for the page.
    """
    options = options or IndexOptions()
    anchors = anchors or {}

    units, extracted = _iter_units(document, options)

    records: list[dict] = []
    seen: dict[str, int] = {}
    ids: dict[int, str] = {}
    # Extracted units come last so the passage they were taken from already has
    # an id to point at.
    for unit in units + extracted:
        pieces = _split(unit, options)
        floor = options.min_chars if unit.min_chars is None else unit.min_chars
        kept = [p for p in pieces if len(p[0]) >= floor]
        if not kept:
            continue
        for position, (text, anchor, anchor_path) in enumerate(kept):
            base = _record_id(doc_stem, anchor, anchor_path, scope=chunk_file)
            record_id = base if len(kept) == 1 else f'{base}-{position}'
            # Two units can still land on one id when neither carries an
            # xml:id and a selector produced records off the same path. A
            # vector store overwrites on a repeated id, so disambiguate rather
            # than silently lose a passage.
            if record_id in seen:
                seen[record_id] += 1
                record_id = f'{record_id}~{seen[record_id]}'
            else:
                seen[record_id] = 0
            ids.setdefault(id(unit), record_id)
            metadata: dict[str, Any] = {
                'source': source,
                'doc': doc_stem,
                'xpath': anchor_path or unit.xpath or '',
                'part': position,
                'n_parts': len(kept),
                'chars': len(text),
                'hash': hashlib.sha1(text.encode('utf-8')).hexdigest()[:16],
            }
            if title:
                metadata['title'] = title
            if unit.heading:
                metadata['heading'] = unit.heading
            if anchor:
                metadata['xml_id'] = anchor
            if chunk_file:
                metadata['chunk'] = chunk_file
            href = _href(anchor, unit.entry_anchor, anchors, chunk_file)
            if href:
                metadata['href'] = href
            if unit.kind:
                metadata['kind'] = unit.kind
                parent_id = ids.get(id(unit.parent)) if unit.parent else None
                if parent_id:
                    metadata['parent'] = parent_id
            for name, values in unit.fields.items():
                metadata[name] = list(values)
            if page_metadata:
                metadata.update(page_metadata)
            records.append({
                'id': record_id,
                'document': text,
                'metadata': metadata,
            })
    return records


def _href(
    anchor: str | None,
    entry_anchor: str | None,
    anchors: dict[str, str],
    chunk_file: str | None,
) -> str | None:
    """Build a link back to the published page for this passage.

    Knowing which chunk a record came from is enough on its own, so a corpus
    whose divisions carry no ``xml:id`` still gets citable links. The anchor
    map only refines that to a fragment when the id survives into the chunk.
    """
    for candidate in (anchor, entry_anchor):
        if candidate and candidate in anchors:
            return f'{anchors[candidate]}#{candidate}'
    if chunk_file:
        return f'{chunk_file}#{anchor}' if anchor else chunk_file
    return None


# ── driver ───────────────────────────────────────────────────────────────────

def _chunk_processor(
    root,
    module_path: Path,
    cfg,
    project_root: Path,
    *,
    chunking=None,
    xpath_env=None,
    webcomponents: bool = False,
    anchors=None,
):
    """Build the chunker for *root*, or ``None`` when the project has no chunking.

    ``ChunkProcessor`` derives chunk filenames from position and neither
    ``select_chunks`` nor ``build_anchor_index`` transforms the body, so the
    filenames and anchors match what ``opm chunk`` publishes. When fragment
    fields are evaluated, *module_path* is the web module those fragments use.
    """
    chunking = cfg.chunking if chunking is None else chunking
    if chunking is None or not (chunking.xpath or chunking.selector):
        return None
    from opm.chunking import ChunkProcessor

    processor = ChunkProcessor(
        module_path,
        root,
        chunking,
        project_root,
        project_config=cfg,
        webcomponents=webcomponents,
        xpath_env=xpath_env,
        anchors=anchors,
    )
    processor.select_chunks()
    return processor


def _web_chunking(cfg: ProjectConfig, odd: Path | None, base_css: str | None, chunking=None):
    """Compile the web (and per-fragment) modules ``opm chunk`` would use for a run.

    *chunking* is the run, the first one when omitted.
    """
    from dataclasses import replace

    from opm.odd_cache import resolve_transform_module

    chunking = cfg.chunking if chunking is None else chunking
    web_odd = odd if odd is not None else (
        chunking.odd if chunking is not None and chunking.odd is not None
        else cfg.odd_for_type('web')
    )
    web = resolve_transform_module(
        odd=web_odd,
        output_mode='web',
        use_packaged_default=web_odd is None,
        base_css=base_css,
    )
    if chunking is None or not chunking.fragments:
        return web.module_path, chunking
    compiled = []
    for fragment in chunking.fragments:
        if fragment.odd is not None:
            resolved = resolve_transform_module(
                odd=fragment.odd,
                output_mode=fragment.mode,
                use_packaged_default=False,
                base_css=base_css,
            )
            compiled.append(replace(fragment, module=resolved.module_path))
        else:
            compiled.append(fragment)
    return web.module_path, replace(
        chunking, module=web.module_path, fragments=compiled,
    )


def _fragment_plain_text(html: str) -> str:
    """Strip a chunking fragment to a scalar: list items joined with `` > ``."""
    from lxml import html as lxml_html

    text = (html or '').strip()
    if not text:
        return ''
    if '<' not in text:
        return _clean(text)
    try:
        tree = lxml_html.fromstring(text)
    except Exception:  # noqa: BLE001 — fall back to tag-stripped text
        return _clean(text)
    items = [tree] if getattr(tree, 'tag', None) == 'li' else tree.xpath('.//li')
    if items:
        parts = [_clean(''.join(item.itertext())) for item in items]
        return ' > '.join(part for part in parts if part)
    return _clean(''.join(tree.itertext()))


def _page_metadata(
    processor, fields: tuple[FieldSpec, ...], chunk, position: int, cache: dict,
    *, strict: bool = True,
) -> dict[str, str]:
    """Evaluate ``fragment`` fields once for this page.

    Not *strict* — a ``[[chunking]]`` array — a field whose fragment only
    another run declares is left out of this run's pages; loading the config
    already checked that some run declares it.
    """
    specs = [spec for spec in fields if spec.fragment]
    if not specs:
        return {}
    if processor is None:
        raise ValueError(
            'index.fields names a chunking fragment, but the project has no '
            '[chunking] section',
        )
    available = {frag.name: frag for frag in (processor.config.fragments or [])}
    values: dict[str, str] = {}
    for spec in specs:
        fragment = available.get(spec.fragment)
        if fragment is None and not strict:
            continue
        if fragment is None:
            raise ValueError(
                f'index.fields["{spec.name}"] names fragment {spec.fragment!r}, '
                'but [chunking.fragments] has no such entry',
            )
        html = processor.process_fragment(fragment, chunk, cache, position)
        text = _fragment_plain_text(html)
        if text:
            values[spec.name] = text
    return values


def index_document(
    xml_path: Path,
    *,
    cfg: ProjectConfig,
    odd: Path | None = None,
    project_root: Path | None = None,
    options: IndexOptions | None = None,
    base_css: str | None = None,
) -> list[dict]:
    """Transform *xml_path* in ``json`` mode and roll the records up for indexing.

    [`opm.project.Project.index`][opm.project.Project.index] runs this over a corpus. *odd* replaces
    ``[transform.json] odd``, *options* the ``[index]`` settings, and
    *base_css* is passed on to the compiler.

    Where the project chunks its output, each chunk is transformed on its own
    and tagged with the file it will be published as. That is what makes a
    retrieval hit citable: a chunk-based href needs no ``xml:id`` at all, which
    matters because chunk selectors may rebuild the region as a detached tree
    whose ids never existed in the source document.
    """
    from opm.odd_cache import resolve_transform_module
    from opm.transform import (
        load_transform_module,
        project_xpath_env,
    )

    project_root = project_root or Path.cwd()
    # The config already carries the rollup tuning and the field declarations;
    # a caller that passes cfg but no options means "use what the project says".
    options = options or IndexOptions(
        max_chars=cfg.index_max_chars,
        min_chars=cfg.index_min_chars,
        overlap=cfg.index_overlap,
        fields=cfg.index_fields,
        units=cfg.index_units,
    )
    resolved_odd = odd if odd is not None else cfg.odd_for_type('json')
    resolved = resolve_transform_module(
        odd=resolved_odd,
        output_mode='json',
        use_packaged_default=resolved_odd is None,
        base_css=base_css,
    )
    module = load_transform_module(resolved.module_path)

    root = etree.parse(str(xml_path)).getroot()
    title = document_title(root)
    parameters = dict(cfg.parameters)

    # Register lookups (e.g. collection($global:register-root)) need the same
    # XPath runtime context as `opm transform`; without collections, ODD models
    # fall back to the TEI surface form instead of the register main name.
    xpath_env = project_xpath_env(cfg, xml_path)
    transform_opts: dict[str, Any] = dict(parameters)

    def transform(node) -> list:
        payload = module.transform(node, dict(transform_opts) or None, xpath_env=xpath_env)[0]
        return json.loads(payload).get('document', [])

    fragment_fields = any(spec.fragment for spec in options.fields)
    webcomponents = bool(cfg.webcomponents_enabled) if fragment_fields else False
    runs = cfg.chunking_runs or ((cfg.chunking,) if cfg.chunking is not None else ())
    # One chunker per run, as `opm chunk` runs them: each is handed the anchors
    # of the runs before it, so links between their pages resolve.
    processors = []
    anchors: dict[str, str] = {}
    for run in runs or (None,):
        processor_module, chunking = resolved.module_path, run
        if fragment_fields:
            processor_module, chunking = _web_chunking(cfg, odd, base_css, run)
        processor = _chunk_processor(
            root,
            processor_module,
            cfg,
            project_root,
            chunking=chunking,
            xpath_env=xpath_env,
            webcomponents=webcomponents,
            anchors=anchors,
        )
        if processor is None:
            continue
        anchors = processor.build_anchor_index()
        processors.append(processor)
    strict = len(runs) < 2
    cache: dict = {}

    def records_for(
        node, *, processor, chunk_file: str | None, anchors: dict | None, position: int, context,
    ) -> list[dict]:
        return build_records(
            transform(node),
            doc_stem=xml_path.stem,
            source=str(xml_path),
            title=title,
            anchors=anchors,
            chunk_file=chunk_file,
            page_metadata=_page_metadata(
                processor, options.fields, context, position, cache, strict=strict,
            ) if fragment_fields else None,
            options=options,
        )

    if not any(processor.chunks for processor in processors):
        return records_for(
            root, processor=processors[0] if processors else None,
            chunk_file=None, anchors=None, position=0, context=root,
        )

    records: list[dict] = []
    for processor in processors:
        # Rebuilt after every run exists, so each run sees the final map.
        run_anchors = processor.build_anchor_index()
        for position, chunk in enumerate(processor.chunks):
            metadata = processor.generate_chunk_metadata(chunk, position)
            records.extend(
                records_for(
                    chunk,
                    processor=processor,
                    chunk_file=metadata.file,
                    anchors=run_anchors,
                    position=position,
                    context=chunk,
                ),
            )
    return records


def write_jsonl(records: list[dict], path: Path) -> None:
    """Write *records* to *path*, one JSON object per line (UTF-8)."""
    with path.open('w', encoding='utf-8') as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write('\n')
