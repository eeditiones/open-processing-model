"""What an ODD declares, and what of it actually runs.

``-t json`` records every decision the processing model made on one document.
Coverage rolls those records up across a corpus and reads them against the ODD
itself, to answer the two questions an ODD author keeps asking:

* **What did I write that never runs?** Models that never fired, models that
  *cannot* fire because an earlier sibling has no ``@predicate``, and
  ``elementSpec``s for elements the corpus never contains.
* **What is in my documents that I never handled?** Elements no model matched at
  all (``unmatched`` records), and elements whose spec exists but whose every
  predicate was false — those produce no record whatsoever, which is exactly why
  they are hard to notice by hand.

Models inherited from an extended ODD are reported separately and never counted
as the author's problem: a local ``elementSpec`` replaces the inherited one
wholesale, so an inherited model is only changeable by redeclaring the element.
The locality split comes from :func:`opm.odd_compiler.parse_odd.spec_origin`,
surfaced in the compiled ``ODD_MODELS`` table as ``source``.

Coverage transforms whole documents; it ignores ``[chunking]``, since a chunk
selector may not cover the document and coverage is about the ODD, not the site.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from opm.odd_compiler.codegen import (
    _local,
    _model_children,
    _top_level_models,
    json_channel,
    model_key,
)
from opm.odd_compiler.parse_odd import (
    TEI_NS,
    has_models,
    iter_element_specs,
    load_odd,
    spec_origin,
)
from opm.runtime import source_positions

# ``alternate`` is the one behaviour that deliberately leaves part of the source
# unprocessed: it records the displayed reading and flattens the other one to
# text. Its subtree is therefore not scanned for silently dropped elements —
# "the ODD chose the other branch" is a decision, not an oversight.
_CONTENT_SELECTING = frozenset({'alternate'})


@dataclass
class Occurrence:
    """Where an element first turned up, and how often it did."""

    element: str
    count: int = 0
    xpath: str | None = None
    file: str | None = None
    line: int | None = None

    def to_dict(self) -> dict:
        return {
            'element': self.element,
            'count': self.count,
            'xpath': self.xpath,
            'file': self.file,
            'line': self.line,
        }

    @property
    def location(self) -> str:
        """``file:line`` when positions are available, else the XPath."""
        if self.file and self.line:
            return f'{self.file}:{self.line}'
        return self.xpath or ''


@dataclass
class ModelInfo:
    """One ``ODD_MODELS`` entry plus the verdict on it."""

    key: str
    element: str
    behaviour: str | None = None
    predicate: str | None = None
    desc: str | None = None
    output: str | None = None
    #: ODD this model was inherited from; ``None`` means it is local.
    source: str | None = None
    template: bool = False
    hits: int = 0
    #: Why this model can never fire, independent of any document.
    unreachable: str | None = None

    @property
    def local(self) -> bool:
        return self.source is None

    @property
    def emits_records(self) -> bool:
        """Whether firing this model would be visible in the JSON records.

        A model with neither ``@behaviour`` nor a ``pb:template`` compiles to a
        bare recursion into the children: it produces no record, so a zero hit
        count says nothing about whether it ran.
        """
        return bool(self.behaviour) or self.template

    def to_dict(self) -> dict:
        return {
            'key': self.key,
            'element': self.element,
            'behaviour': self.behaviour,
            'predicate': self.predicate,
            'desc': self.desc,
            'output': self.output,
            'source': self.source,
            'template': self.template,
            'hits': self.hits,
            'unreachable': self.unreachable,
        }


@dataclass
class CoverageReport:
    """The full diagnostic picture of one ODD against one corpus."""

    odd: Path
    channel: str
    documents: list[Path] = field(default_factory=list)
    models: dict[str, ModelInfo] = field(default_factory=dict)
    behaviours: Counter = field(default_factory=Counter)
    elements_seen: Counter = field(default_factory=Counter)
    records: int = 0
    suppressed: int = 0
    unmatched: dict[str, Occurrence] = field(default_factory=dict)
    dropped: dict[str, Occurrence] = field(default_factory=dict)
    #: Local specs whose element never appears in the corpus: ``{element, models}``.
    unused_specs: list[dict] = field(default_factory=list)
    #: Local specs that declare no model at all (attribute-only ODD changes).
    attribute_only_specs: list[str] = field(default_factory=list)
    #: ODD expressions opm can never evaluate, as the compiler recorded them in
    #: ``ODD_UNSUPPORTED`` (see :mod:`opm.odd_compiler.expression_check`).
    unsupported: list[dict] = field(default_factory=list)

    # ── slices the CLI and callers ask for ────────────────────────────────────

    def local_models(self) -> list[ModelInfo]:
        return [m for m in self.models.values() if m.local]

    def inherited_models(self) -> list[ModelInfo]:
        return [m for m in self.models.values() if not m.local]

    def unused_models(self) -> list[ModelInfo]:
        """Local models that could have fired on this corpus and did not.

        Restricted to models whose element the corpus actually contains: a model
        for an element that never appears says nothing about the model, and
        those elements are already listed as unexercised specs. Unreachable
        models are excluded too — they are reported on their own, with the
        reason, and listing them twice would only pad the actionable list.
        """
        return sorted(
            (
                m for m in self.models.values()
                if m.local and m.hits == 0 and m.emits_records
                and not m.unreachable and self.elements_seen.get(m.element)
            ),
            key=lambda m: (m.element, m.key),
        )

    def unreachable_models(self) -> list[ModelInfo]:
        return sorted(
            (m for m in self.models.values() if m.unreachable),
            key=lambda m: (m.element, m.key),
        )

    def silent_models(self) -> list[ModelInfo]:
        """Local models that emit nothing: no ``@behaviour``, no ``pb:template``."""
        return sorted(
            (m for m in self.models.values() if m.local and not m.emits_records),
            key=lambda m: (m.element, m.key),
        )

    def to_dict(self) -> dict:
        local = self.local_models()
        return {
            'odd': str(self.odd),
            'channel': self.channel,
            'documents': [str(p) for p in self.documents],
            'records': self.records,
            'suppressed': self.suppressed,
            'summary': {
                'local_models': len(local),
                'local_models_fired': sum(1 for m in local if m.hits),
                'inherited_models': len(self.models) - len(local),
                'inherited_models_fired': sum(
                    1 for m in self.inherited_models() if m.hits
                ),
                'elements_seen': len(self.elements_seen),
                'unmatched_elements': len(self.unmatched),
                'dropped_elements': len(self.dropped),
                'unreachable_models': len(self.unreachable_models()),
                'unsupported_expressions': len(self.unsupported),
            },
            'models': [m.to_dict() for m in self.models.values()],
            # A record with no behaviour is an unmatched element; ``null`` would
              # be a JSON key, and a confusing one.
              'behaviours': {
                  (behaviour or 'unmatched'): count
                  for behaviour, count in self.behaviours.most_common()
              },
            'elements_seen': dict(self.elements_seen.most_common()),
            'unmatched': [o.to_dict() for o in _by_count(self.unmatched)],
            'dropped': [o.to_dict() for o in _by_count(self.dropped)],
            'unused_specs': self.unused_specs,
            'attribute_only_specs': self.attribute_only_specs,
            'unsupported': self.unsupported,
        }


def _by_count(table: dict[str, Occurrence]) -> list[Occurrence]:
    return sorted(table.values(), key=lambda o: (-o.count, o.element))


# ── source paths ─────────────────────────────────────────────────────────────


def iter_element_paths(root):
    """Yield ``(element, xpath)`` for the whole tree, top-down.

    The paths are the ones ``-t json`` records
    (:func:`opm.runtime.json_output_functions._element_path`), which is what
    makes "this element produced no record" answerable by set difference. They
    are built once on the way down rather than reconstructed per element: the
    bottom-up version rescans the siblings at every step, which turns a big
    document into a quadratic walk.
    """
    if not isinstance(root.tag, str):
        return
    default_ns = etree.QName(root).namespace
    root_step = (
        _element_name(root) if etree.QName(root).namespace == default_ns else '*'
    )
    yield from _descend(root, f'/{root_step}', default_ns)


def _element_name(node) -> str:
    return etree.QName(node).localname


def _descend(node, path: str, default_ns):
    yield node, path
    counts: Counter = Counter()
    position = 0
    for child in node:
        if not isinstance(child.tag, str):
            continue  # comments and processing instructions
        position += 1
        if etree.QName(child).namespace == default_ns:
            counts[child.tag] += 1
            step = f'{_element_name(child)}[{counts[child.tag]}]'
        else:
            # No prefix is bound for a foreign namespace, so the record side
            # falls back to a positional step; match it exactly.
            step = f'*[{position}]'
        yield from _descend(child, f'{path}/{step}', default_ns)


# ── static analysis ──────────────────────────────────────────────────────────


def unreachable_models(parsed, output_mode: str = 'web') -> dict[str, str]:
    """Models that can never fire, mapped to the reason why.

    Mirrors the dispatch the code generator emits: conditional models become an
    ``if``/``elif`` chain in document order and the *first* model without a
    predicate becomes the ``else``. Two consequences, both silent in the ODD:
    when the very first model has no predicate the rest of the spec is dropped
    on the floor, and any further unconditional model after the first can never
    be the fallback.
    """
    findings: dict[str, str] = {}
    for spec in iter_element_specs(parsed):
        ident = spec.get('ident')
        if not ident or ident in ('*', 'text()'):
            continue
        _scan_level(
            _top_level_models(spec, output_mode), ident, spec, output_mode,
            findings, dead=None,
        )
    return findings


def _describe(el) -> str:
    loc = _local(el.tag)
    if loc == 'model':
        behaviour = el.get('behaviour')
        return f'the {behaviour} model' if behaviour else 'an earlier model'
    return f'the {loc}'


def _scan_level(entries, ident, spec, output_mode, findings, dead) -> None:
    """Scan one shadowing level: an elementSpec's models, or a modelGrp's."""
    for index, el in enumerate(entries):
        reason = dead
        if reason is None and index and not entries[0].get('predicate'):
            reason = (
                f'{_describe(entries[0])} above it has no @predicate and always wins'
            )
        if (
            reason is None
            and not el.get('predicate')
            and any(not e.get('predicate') for e in entries[:index])
        ):
            reason = 'an earlier model without @predicate is already the fallback'
        _scan_node(el, ident, spec, output_mode, findings, reason)


def _scan_node(el, ident, spec, output_mode, findings, dead) -> None:
    loc = _local(el.tag)
    if loc == 'model':
        if dead:
            findings[model_key(ident, spec, el)] = dead
    elif loc == 'modelGrp':
        _scan_level(
            _model_children(el, output_mode), ident, spec, output_mode, findings, dead,
        )
    elif loc == 'modelSequence':
        # Every child of a sequence contributes; none shadows its siblings.
        for child in _model_children(el, output_mode):
            _scan_node(child, ident, spec, output_mode, findings, dead)


# ── record walking ───────────────────────────────────────────────────────────


@dataclass
class _Seen:
    """What one document's records said about it."""

    recorded: set = field(default_factory=set)
    #: Paths whose subtree the ODD deliberately left unprocessed.
    pruned: set = field(default_factory=set)
    #: Paths of the first record of each element no model matched.
    unmatched: set = field(default_factory=set)


def _scan_records(nodes, report: CoverageReport, seen: _Seen) -> None:
    for record in nodes:
        if not isinstance(record, dict):
            continue  # text runs
        report.records += 1
        report.behaviours[record.get('behaviour')] += 1
        path = record.get('xpath')
        if path:
            seen.recorded.add(path)
        key = record.get('model')
        info = report.models.get(key) if key else None
        if info is not None:
            info.hits += 1
        if record.get('suppressed'):
            report.suppressed += 1
            if path:
                seen.pruned.add(path)
        elif record.get('behaviour') in _CONTENT_SELECTING and path:
            seen.pruned.add(path)
        if record.get('behaviour') is None:
            element = record.get('element') or '?'
            occurrence = report.unmatched.setdefault(element, Occurrence(element))
            occurrence.count += 1
            if occurrence.xpath is None:
                occurrence.xpath = path
                if path:
                    seen.unmatched.add(path)
        _scan_records(record.get('children', []), report, seen)


def _scan_source(root, path: Path, seen: _Seen, report: CoverageReport) -> None:
    """Compare the source tree against what the records account for.

    Only the *outermost* element of a subtree that produced nothing is reported.
    An element that falls through its predicates still recurses into its
    children, so a single unhandled ``<contrib-group>`` otherwise drags every
    name, affiliation and email under it into the list, and the one finding that
    matters is buried under its own consequences.
    """
    positions = source_positions.build(path, root)
    blind: str | None = None  # path of the pruned or dropped ancestor we are in
    for element, xpath in iter_element_paths(root):
        name = _element_name(element)
        report.elements_seen[name] += 1
        if blind is not None and not xpath.startswith(f'{blind}/'):
            blind = None
        if xpath in seen.pruned:
            blind = blind or xpath
            continue
        if xpath in seen.recorded:
            if xpath in seen.unmatched:
                _locate(report.unmatched.get(name), path, element, positions)
            continue
        if blind is not None:
            continue
        blind = xpath
        occurrence = report.dropped.setdefault(name, Occurrence(name))
        occurrence.count += 1
        if occurrence.xpath is None:
            occurrence.xpath = xpath
            _locate(occurrence, path, element, positions)


def _locate(occurrence, path: Path, element, positions) -> None:
    if occurrence is None or occurrence.line is not None:
        return
    where = source_positions.lookup(element, positions)
    if where is not None:
        occurrence.file = str(path)
        occurrence.line = where[0]


# ── entry point ──────────────────────────────────────────────────────────────


def analyze(
    paths,
    *,
    cfg=None,
    odd: Path | None = None,
    output_mode: str = 'json',
    parameters: dict | None = None,
) -> CoverageReport:
    """Run *paths* through the ODD in JSON mode and report on the outcome.

    *output_mode* is a JSON mode (``json``, ``json-typst``, …); the channel it
    inspects decides which ``@output``-tagged models participate, so a coverage
    run is always about one channel.
    """
    from opm.odd_cache import resolve_transform_module
    from opm.runtime.pm_runtime import xpath_runtime_context
    from opm.transform import (
        load_transform_module,
        load_xpath_collections,
        load_xpath_documents,
    )

    documents = [Path(p) for p in paths]
    resolved_odd = odd if odd is not None else (cfg.odd_for_type('json') if cfg else None)
    resolved = resolve_transform_module(
        odd=resolved_odd,
        output_mode=output_mode,
        use_packaged_default=resolved_odd is None,
    )
    module = load_transform_module(resolved.module_path)
    odd_path = Path(resolved.source_odd) if resolved.source_odd else Path('(module)')
    channel = json_channel(output_mode)

    report = CoverageReport(
        odd=odd_path,
        channel=channel,
        documents=documents,
        models={
            key: ModelInfo(
                key=key,
                element=entry.get('element', '?'),
                behaviour=entry.get('behaviour'),
                predicate=entry.get('predicate'),
                desc=entry.get('desc'),
                output=entry.get('output'),
                source=entry.get('source'),
                template=bool(entry.get('template')),
            )
            for key, entry in getattr(module, 'ODD_MODELS', {}).items()
        },
        unsupported=list(getattr(module, 'ODD_UNSUPPORTED', [])),
    )

    parsed = load_odd(odd_path) if resolved.source_odd else None
    if parsed is not None:
        for key, reason in unreachable_models(parsed, channel).items():
            info = report.models.get(key)
            if info is not None:
                info.unreachable = reason

    merged = dict(cfg.parameters) if cfg is not None else {}
    merged.update(parameters or {})

    # A predicate is free to call doc(), collection() or a tp: extension
    # function; without the same runtime context the transform gets, those
    # predicates would fail here and their models be reported as never fired.
    extensions = tuple(cfg.xpath_extensions) if cfg is not None else ()
    xpath_documents = load_xpath_documents(cfg.xpath_documents) if cfg else {}
    xpath_collections: dict = {}
    if cfg is not None:
        xpath_collections, xpath_documents = load_xpath_collections(
            cfg.xpath_collections, xpath_documents,
        )

    for document in documents:
        root = etree.parse(str(document)).getroot()
        options = dict(merged)
        options.update(
            xpath_runtime_context(
                base_uri=document.resolve().as_uri(),
                documents=xpath_documents,
                collections=xpath_collections,
                variables=dict(cfg.xpath_variables) if cfg else {},
                namespaces=dict(cfg.xpath_namespaces) if cfg else {},
            ),
        )
        if extensions:
            options['xpath_extensions'] = list(extensions)
        payload = json.loads(module.transform(root, options)[0])
        seen = _Seen()
        _scan_records(payload.get('document', []), report, seen)
        _scan_source(root, document, seen, report)

    if parsed is not None:
        _report_specs(parsed, report)
    return report


def _report_specs(parsed, report: CoverageReport) -> None:
    """Local element specs the corpus never exercised."""
    primary = Path(parsed.odd_path).resolve()
    for spec in iter_element_specs(parsed):
        ident = spec.get('ident')
        if not ident or ident in ('*', 'text()'):
            continue
        if spec_origin(spec) != primary:
            continue  # inherited: not this ODD's to fix
        if not has_models(spec):
            report.attribute_only_specs.append(ident)
        elif not report.elements_seen.get(ident):
            report.unused_specs.append({
                'element': ident,
                'models': len(spec.findall(f'.//{{{TEI_NS}}}model')),
            })
    report.attribute_only_specs.sort()
    report.unused_specs.sort(key=lambda entry: entry['element'])
