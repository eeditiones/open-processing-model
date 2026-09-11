# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Roll the JSON output mode's records up into embedding-sized index units.

``opm transform -t json`` records every decision the processing model made,
which is the right shape for debugging an ODD and the wrong shape for a search
index: one record per table cell is not something you embed, and a nested tree
has no stable identity to upsert against.

This module bridges the two. It walks the record tree, groups it at section
boundaries, and emits one JSONL line per retrievable unit with flat scalar
metadata — the shape ChromaDB accepts and Elasticsearch is happy with.

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
from typing import Any

from lxml import etree

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
    """Material to pull out of a passage: a facet, or a passage of its own.

    A note and a person name are the same operation — recognise a record, take
    its text — differing only in where the text goes. ``metadata=True`` joins it
    onto the passage that contains it, for filtering; ``metadata=False`` emits it
    as its own retrievable record tagged ``kind`` and linked to its parent, and
    whether a search engine indexes those is then a filter at load time rather
    than a decision baked into the file.

    ``inline`` is the one choice that cannot be deferred: it decides whether the
    text stays in the containing passage's embedded ``document`` string. It
    defaults to *metadata*, which is what each case usually wants — a name reads
    as part of the sentence, an extracted note does not — and can be set
    explicitly to keep a fragment in both places.
    """

    name: str
    behaviours: frozenset[str] = frozenset()
    elements: frozenset[str] = frozenset()
    models: frozenset[str] = frozenset()
    metadata: bool = True
    inline: bool | None = None
    separator: str = '; '
    """Joins several values of a metadata field: Chroma takes scalars, not lists."""

    @property
    def keeps_text_inline(self) -> bool:
        return self.metadata if self.inline is None else self.inline

    def matches(self, record: dict) -> bool:
        return (
            record.get('behaviour') in self.behaviours
            or record.get('element') in self.elements
            or record.get('model') in self.models
        )


@dataclass
class IndexOptions:
    """Tuning for the rollup. Defaults suit prose in a general-purpose embedder."""

    max_chars: int = 1500
    min_chars: int = 40
    overlap: int = 1
    """Trailing split-boundary records carried into the next part, for context."""
    fields: tuple[FieldSpec, ...] = ()
    """``[[index.fields]]`` — material extracted as a facet or as its own record."""


@dataclass
class _Unit:
    """One retrievable passage, before it is split and serialised."""

    xml_id: str | None
    xpath: str | None
    heading: str | None
    breadcrumb: list[str]
    entry_anchor: str | None = None
    """Last ``xml:id`` seen before this unit opened — the page it starts on."""
    parts: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    """``(text, xml_id, xpath)`` per contributing record, so a split keeps its anchor."""
    kind: str | None = None
    """Name of the :class:`FieldSpec` this unit was extracted by, if any."""
    parent: '_Unit | None' = None
    """The passage an extracted unit was taken out of."""
    fields: dict[str, list[str]] = field(default_factory=dict)
    """Extracted values destined for this unit's metadata, in document order."""

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

    def __init__(self, fields: tuple[FieldSpec, ...] = ()) -> None:
        self.fields = fields
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

    def finish(self) -> list[_Unit]:
        if self.current is not None and self.current.parts:
            self.units.append(self.current)
        return self.units

    def collect(self, record: dict, breadcrumb: list[str]) -> None:
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
                self.extract(record, spec, breadcrumb)
                keep_inline = keep_inline or spec.keeps_text_inline
            if not keep_inline:
                # The text belongs to the facet or the extracted record only;
                # walking on would embed it in the containing passage as well.
                return

        heading = _first_heading(record)
        # A named behaviour is not enough on its own: ODDs differ on whether an
        # act or a chapter gets `section` or plain `block`, but a division that
        # carries a heading is a retrievable unit in either.
        if record.get('behaviour') in _UNIT_BOUNDARIES or heading is not None:
            self.open(record, breadcrumb, heading)
            return

        if self.current is None:
            self.current = _Unit(
                xml_id=record.get('id'),
                xpath=record.get('xpath'),
                heading=None,
                breadcrumb=list(breadcrumb),
                entry_anchor=self.last_anchor,
            )
        self.descend(record, breadcrumb)

    def extract(self, record: dict, spec: FieldSpec, breadcrumb: list[str]) -> None:
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
            breadcrumb=list(breadcrumb),
            entry_anchor=self.last_anchor,
            kind=spec.name,
            parent=self.current,
        )
        unit.parts.append((text, record.get('id'), record.get('xpath')))
        self.extracted.append(unit)

    def open(self, record: dict, breadcrumb: list[str], heading: str | None) -> None:
        if self.current is not None and self.current.parts:
            self.units.append(self.current)
        inner = breadcrumb + [heading] if heading else list(breadcrumb)
        self.current = _Unit(
            xml_id=record.get('id'),
            xpath=record.get('xpath'),
            heading=heading,
            breadcrumb=inner,
            entry_anchor=self.last_anchor,
        )
        self.descend(record, inner)

    def descend(self, record: dict, breadcrumb: list[str]) -> None:
        # `children` interleaves this record's own text runs with its child
        # records in source order, and is the only place text lives. A record
        # with no children produced no text, so it contributes nothing.
        for child in record.get('children', ()):
            if isinstance(child, dict):
                self.collect(child, breadcrumb)
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
    walker = _Walker(options.fields)
    for root in document:
        if isinstance(root, dict):
            walker.collect(root, [])
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
    base_breadcrumb: list[str] | None = None,
    options: IndexOptions | None = None,
) -> list[dict]:
    """Turn one document's (or one chunk's) JSON-mode records into index records."""
    options = options or IndexOptions()
    anchors = anchors or {}

    units, extracted = _iter_units(document, options)
    separators = {spec.name: spec.separator for spec in options.fields}

    records: list[dict] = []
    seen: dict[str, int] = {}
    ids: dict[int, str] = {}
    # Extracted units come last so the passage they were taken from already has
    # an id to point at.
    for unit in units + extracted:
        pieces = _split(unit, options)
        kept = [p for p in pieces if len(p[0]) >= options.min_chars]
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
            crumbs = _crumbs(base_breadcrumb, unit.breadcrumb)
            if crumbs:
                # Chroma metadata takes scalars only — never a list.
                metadata['breadcrumb'] = ' > '.join(crumbs)
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
                metadata[name] = separators.get(name, '; ').join(values)
            records.append({
                'id': record_id,
                'document': text,
                'metadata': metadata,
            })
    return records


def _crumbs(base: list[str] | None, inner: list[str]) -> list[str]:
    """Join the caller's breadcrumb root to the unit's own, without repeats.

    Each chunk is transformed on its own, so only the first one contains the
    document-level heading; the rest need the title supplied from outside.
    """
    out: list[str] = []
    for crumb in list(base or []) + list(inner):
        if crumb and (not out or out[-1] != crumb):
            out.append(crumb)
    return out


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

def _chunk_processor(root, module_path: Path, cfg, project_root: Path):
    """Build the chunker for *root*, or ``None`` when the project has no chunking.

    ``ChunkProcessor`` derives chunk filenames from position and neither
    ``select_chunks`` nor ``build_anchor_index`` transforms anything, so the
    filenames and anchors match what ``opm chunk`` publishes even though the
    module loaded here is the JSON one.
    """
    if cfg.chunking is None or not (cfg.chunking.xpath or cfg.chunking.selector):
        return None
    from opm.chunking import ChunkProcessor

    processor = ChunkProcessor(
        module_path,
        root,
        cfg.chunking,
        project_root,
        project_config=cfg,
        xpath_extensions=cfg.xpath_extensions or None,
    )
    processor.select_chunks()
    return processor


def index_document(
    xml_path: Path,
    *,
    cfg,
    odd: Path | None = None,
    project_root: Path | None = None,
    options: IndexOptions | None = None,
) -> list[dict]:
    """Transform *xml_path* in ``json`` mode and roll the records up for indexing.

    Where the project chunks its output, each chunk is transformed on its own
    and tagged with the file it will be published as. That is what makes a
    retrieval hit citable: a chunk-based href needs no ``xml:id`` at all, which
    matters because chunk selectors may rebuild the region as a detached tree
    whose ids never existed in the source document.
    """
    from opm.odd_cache import resolve_transform_module
    from opm.runtime.xpath_env import XPathEnvironment
    from opm.transform import (
        load_transform_module,
        load_xpath_collections,
        load_xpath_documents,
    )

    project_root = project_root or Path.cwd()
    # The config already carries the rollup tuning and the field declarations;
    # a caller that passes cfg but no options means "use what the project says".
    options = options or IndexOptions(
        max_chars=cfg.index_max_chars,
        min_chars=cfg.index_min_chars,
        overlap=cfg.index_overlap,
        fields=cfg.index_fields,
    )
    resolved_odd = odd if odd is not None else cfg.odd_for_type('json')
    resolved = resolve_transform_module(
        odd=resolved_odd,
        output_mode='json',
        use_packaged_default=resolved_odd is None,
    )
    module = load_transform_module(resolved.module_path)

    root = etree.parse(str(xml_path)).getroot()
    title = document_title(root)
    parameters = dict(cfg.parameters)

    # Register lookups (e.g. collection($global:register-root)) need the same
    # XPath runtime context as `opm transform`; without collections, ODD models
    # fall back to the TEI surface form instead of the register main name.
    xpath_documents = load_xpath_documents(cfg.xpath_documents)
    xpath_collections, xpath_documents = load_xpath_collections(
        cfg.xpath_collections, xpath_documents,
    )
    xpath_env = XPathEnvironment(
        base_uri=xml_path.resolve().as_uri(),
        documents=xpath_documents,
        collections=xpath_collections,
        variables=dict(cfg.xpath_variables),
        namespaces=dict(cfg.xpath_namespaces),
        extensions=cfg.xpath_extensions,
    )
    transform_opts: dict[str, Any] = dict(parameters)

    def transform(node) -> list:
        payload = module.transform(node, dict(transform_opts) or None, xpath_env=xpath_env)[0]
        return json.loads(payload).get('document', [])

    processor = _chunk_processor(root, resolved.module_path, cfg, project_root)
    if processor is None or not processor.chunks:
        return build_records(
            transform(root),
            doc_stem=xml_path.stem,
            source=str(xml_path),
            title=title,
            options=options,
        )

    anchors = processor.build_anchor_index()
    records: list[dict] = []
    for position, chunk in enumerate(processor.chunks):
        metadata = processor.generate_chunk_metadata(chunk, position)
        records.extend(
            build_records(
                transform(chunk),
                doc_stem=xml_path.stem,
                source=str(xml_path),
                title=title,
                anchors=anchors,
                chunk_file=metadata.file,
                base_breadcrumb=[title] if title else None,
                options=options,
            ),
        )
    return records


def write_jsonl(records: list[dict], path: Path) -> None:
    with path.open('w', encoding='utf-8') as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write('\n')
