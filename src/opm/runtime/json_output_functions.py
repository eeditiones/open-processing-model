# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""JSON serialisation of the processing model's own decisions.

Unlike the HTML / Markdown / Typst backends this one does not render the
document — it records *what the ODD did to it*: which behaviour ran for each
element, which model won, where the element came from, and what it
contributed.  Two consumers want that:

* **ODD debugging.** ``model`` names the model that matched; the ``models``
  table in the output expands it to its predicate and ``<desc>``.
* **Search / RAG indexing.** ``opm index`` rolls these records up into
  embedding-sized units.  Indexing the processing model rather than the raw
  source means the ODD's editorial judgment carries into the index: ``omit``
  drops apparatus, ``alternate`` picks the displayed reading, templates expand
  abbreviations.

Every element that reaches a ``pmf`` method produces a record — inline
behaviours included, since a wrong inline model is the single most common ODD
bug and folding its text into the parent would hide it.  Suppressing
behaviours (``omit``, ``index``, ``metadata``) emit a childless record marked
``suppressed`` rather than vanishing, so "the ODD dropped this" and "it was
never in the source" stay distinguishable.  Elements no model matched arrive
via [`JsonOutputFunctions.unmatched`][opm.runtime.json_output_functions.JsonOutputFunctions.unmatched] with ``behaviour`` set to ``None``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lxml import etree

from opm.runtime import source_map, source_positions
from opm.runtime.output_functions import (
    PMResult,
    XLINK_HREF,
    XML_ID,
    ProcessingModelFunctions,
    child_nodes,
    normalize,
)

# ``cls`` is built by the code generator as ['tei-div', 'tei-div11', rend, …];
# the second entry is the model's stable key into the MODELS table.
_MODEL_KEY_RE = re.compile(r'^[A-Za-z_][\w.-]*\d+$')

_CLARK_RE = re.compile(r'^\{[^}]*\}')


def _local_name(node) -> str:
    tag = node.tag
    if not isinstance(tag, str):
        return '#comment'
    return _CLARK_RE.sub('', tag)


def _element_path(node) -> str | None:
    """An XPath to *node* built from element names rather than ``*`` wildcards.

    ``getroottree().getpath()`` has no prefix bound for a default namespace, so
    it can only emit ``/*/*[2]/*[4]`` — correct, unreadable, and useless for
    finding the element in an editor. Because opm resolves unprefixed names
    against the document's default namespace, ``/TEI/text[1]/body[1]/div[2]``
    is both legible and directly runnable against the same document.

    Elements outside that default namespace keep the positional form: there is
    no prefix to name them with, and an unprefixed step would not match them.
    """
    tree = node.getroottree()
    root = tree.getroot()
    if root is None or not isinstance(root.tag, str):
        return tree.getpath(node)
    default_ns = etree.QName(root).namespace

    steps: list[str] = []
    current = node
    while current is not None and isinstance(current.tag, str):
        parent = current.getparent()
        if parent is None:
            steps.append(
                _local_name(current)
                if etree.QName(current).namespace == default_ns
                else '*'
            )
            break
        if etree.QName(current).namespace == default_ns:
            same = [c for c in parent if c.tag == current.tag]
            steps.append(f'{_local_name(current)}[{same.index(current) + 1}]')
        else:
            kids = [c for c in parent if isinstance(c.tag, str)]
            steps.append(f'*[{kids.index(current) + 1}]')
        current = parent

    return '/' + '/'.join(reversed(steps))


def _model_key(cls) -> str | None:
    """Return the ``tei-div11``-style model key from a dispatch class list."""
    if not cls or len(cls) < 2:
        return None
    candidate = cls[1]
    if isinstance(candidate, str) and _MODEL_KEY_RE.match(candidate):
        return candidate
    return None


def _prune(children: list) -> list:
    """Drop text runs that normalisation emptied out.

    ``normalize_markdown_xml_text`` collapses pretty-print indentation to ``''``.
    Only exactly-empty strings go: a lone space between two elements
    (``</hi> <hi>``) is a real word separator and has to survive.
    """
    return [c for c in children if not (isinstance(c, str) and c == '')]


class JsonOutputFunctions(ProcessingModelFunctions):
    """Emit the processing model's decisions as JSON records."""

    #: Source positions of the run's document, filled in by `_positions`.
    _positions_cache: dict | None = None

    # ── record construction ───────────────────────────────────────────────────

    def _record(
        self,
        config,
        node,
        cls,
        behaviour: str | None,
        content,
        *,
        recurse: bool = True,
        **extra,
    ) -> PMResult:
        children: list = []
        if recurse:
            config.apply_children(config, node, content, children)
        return [
            self._build(
                node, cls, behaviour, _prune(children),
                positions=_positions(config), **extra,
            ),
        ]

    @staticmethod
    def _build(
        node, cls, behaviour: str | None, children: list,
        positions: dict | None = None, **extra,
    ) -> dict:
        rec: dict = {}
        xml_id = node.get(XML_ID) or node.get('id')
        if xml_id:
            rec['id'] = xml_id
        try:
            rec['xpath'] = _element_path(node)
        except (ValueError, AttributeError):
            # A detached subtree has no root tree to path against.
            rec['xpath'] = None
        where = source_positions.lookup(node, positions or {})
        if where is not None:
            rec['line'], rec['col'] = where
        rec['element'] = _local_name(node)
        rec['behaviour'] = behaviour
        rec['model'] = _model_key(cls)
        for key, value in extra.items():
            if value is not None:
                rec[key] = value
        if children:
            rec['children'] = children
        return rec

    def _suppressed(self, config, node, cls, behaviour: str) -> PMResult:
        """A behaviour that produces no output — recorded, but not recursed into."""
        _ = config
        rec = self._build(node, cls, behaviour, [], positions=_positions(config))
        rec['suppressed'] = True
        return [rec]

    # ── structural behaviours ─────────────────────────────────────────────────

    def block(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'block', content)

    def paragraph(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'paragraph', content)

    def heading(self, config, node, cls, content, level) -> PMResult:
        return self._record(config, node, cls, 'heading', content, level=level)

    def section(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'section', content)

    def body(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'body', content)

    def document(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'document', content)

    def list(self, config, node, cls, content, type=None) -> PMResult:
        return self._record(
            config, node, cls, 'list', content, type=type or node.get('type'),
        )

    def list_item(self, config, node, cls, content, n=None) -> PMResult:
        return self._record(
            config, node, cls, 'list_item', content, n=n or node.get('n'),
        )

    def table(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'table', content)

    def row(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'row', content)

    def cell(self, config, node, cls, content, type=None) -> PMResult:
        return self._record(config, node, cls, 'cell', content, type=type)

    def figure(self, config, node, cls, content, title=None) -> PMResult:
        return self._record(
            config, node, cls, 'figure', content, title=_flatten(title),
        )

    def graphic(
        self, config, node, cls, content, url,
        width=None, height=None, scale=None, title=None,
    ) -> PMResult:
        return self._record(
            config, node, cls, 'graphic', content,
            uri=_flatten(url), width=width, height=height,
            scale=scale, title=_flatten(title),
        )

    def note(self, config, node, cls, content, place=None, label=None) -> PMResult:
        # Notes stay inline in the tree rather than going through
        # ``config.state.footnotes``: that accumulator is typed for str / Element
        # and silently discards dicts when the footnotes are injected.
        return self._record(
            config, node, cls, 'note', content,
            place=place, label=_flatten(label),
        )

    def cit(self, config, node, cls, content, source=None) -> PMResult:
        return self._record(
            config, node, cls, 'cit', content, source=_flatten(source),
        )

    def break_(self, config, node, cls, content, type=None, label=None) -> PMResult:
        return self._record(
            config, node, cls, 'break', content,
            type=type, label=_flatten(label) or node.get('n'),
        )

    def code(self, config, node, cls, content, language=None) -> PMResult:
        return self._record(config, node, cls, 'code', content, language=language)

    # ── inline behaviours ─────────────────────────────────────────────────────
    #
    # These emit records too.  Folding them into the enclosing block (as a
    # purely index-shaped format would) hides exactly the bugs this output
    # exists to surface: the wrong `<hi>` model winning, an `<abbr>` matching
    # where `<expan>` was meant.

    def inline(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'inline', content)

    def code_inline(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'code_inline', content)

    def link(self, config, node, cls, content, uri, target, optional) -> PMResult:
        _ = optional
        resolved = _flatten(uri) or node.get(XLINK_HREF) or node.get('target')
        return self._record(
            config, node, cls, 'link', content,
            uri=resolved, target=_flatten(target),
        )

    def anchor(self, config, node, cls, content, id=None) -> PMResult:
        return self._record(
            config, node, cls, 'anchor', content,
            anchor_id=id or node.get(XML_ID),
        )

    def alternate(
        self, config, node, cls, content, default, alternate, optional=None,
    ) -> PMResult:
        _ = optional
        # The displayed reading is *default*; *alternate* is the hidden one.
        # Recording both is the point — this behaviour is where an ODD silently
        # picks one of two encodings.
        return self._record(
            config, node, cls, 'alternate', default,
            alternate_text=_flatten(alternate),
        )

    def glyph(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'glyph', content)

    def text(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'text', content)

    def title(self, config, node, cls, content) -> PMResult:
        return self._record(config, node, cls, 'title', content)

    def match(self, config, node, cls, content) -> PMResult:  # type: ignore[override]
        return self._record(config, node, cls, 'match', content)

    def webcomponent(
        self, config, node, cls, content, name, optional=None,
    ) -> PMResult:
        return self._record(
            config, node, cls, 'webcomponent', content,
            component=name,
            params={k: _flatten(v) for k, v in (optional or {}).items()} or None,
        )

    def template(
        self, config, node, cls, template_str: str, params: dict,
    ) -> PMResult:  # type: ignore[override]
        """Record a ``pb:template`` and keep the content it wraps.

        The generator hands templates their parameters already processed, so
        ``params['content']`` is a list of finished records. Dropping it would
        lose every element a template-heavy ODD wraps — for DocBook that is
        most of the document.
        """
        _ = config
        children: list = []
        scalars: dict = {}
        for key, value in (params or {}).items():
            if isinstance(value, list):
                children.extend(
                    item for item in value
                    if isinstance(item, dict) or isinstance(item, str)
                )
            elif isinstance(value, dict):
                children.append(value)
            else:
                flat = _flatten(value)
                if flat is not None:
                    scalars[key] = flat
        rec = self._build(
            node, cls, 'template', _prune(children), positions=_positions(config),
        )
        # Templates are indented XML blocks; collapse them so records stay legible.
        rec['template'] = ' '.join(template_str.split())
        if scalars:
            rec['params'] = scalars
        return [rec]

    # ── recursion ─────────────────────────────────────────────────────────────

    def pass_through(self, config, node, cls, content) -> PMResult:
        """Recurse, but still record that a ``pass_through`` model won.

        Emitting nothing here would hide a real decision: when the model you
        expected did not fire because a ``pass_through`` one matched first,
        the element simply would not appear. The same argument that puts inline
        and suppressed behaviours in the tree applies to this one.
        """
        result: list = []
        for item in normalize(content):
            if isinstance(item, (str, dict)):
                result.append(item)
            elif isinstance(item, etree._Element):
                sub = (
                    config.apply(config, child_nodes(node))
                    if item is node
                    else config.apply(config, [item])
                )
                result.extend(sub)
        return [
            self._build(
                node, cls, 'pass_through', _prune(result),
                positions=_positions(config),
            ),
        ]

    # ── suppressing behaviours ────────────────────────────────────────────────

    def omit(self, config, node, cls, content) -> PMResult:
        _ = content
        return self._suppressed(config, node, cls, 'omit')

    def index(self, config, node, cls, content, type=None) -> PMResult:
        _ = content
        result = self._suppressed(config, node, cls, 'index')
        if type:
            result[0]['type'] = type
        return result

    def metadata(self, config, node, cls, content) -> PMResult:
        _ = content
        return self._suppressed(config, node, cls, 'metadata')

    # ── elements no model matched ─────────────────────────────────────────────

    def unmatched(self, config, node) -> PMResult:
        """Record an element the ODD has no model for, then recurse into it.

        The generated dispatch routes its ``case _:`` arm here for JSON output.
        Without this the element would never reach a ``pmf`` method and its
        text would surface in some ancestor with no provenance at all — which
        is the one thing you most want to find when an ODD looks incomplete.
        """
        children: list = []
        config.apply_children(config, node, node, children)
        return [self._build(node, [], None, _prune(children), positions=_positions(config))]

    # ── assembly ──────────────────────────────────────────────────────────────

    def finish(self, config, nodes: list) -> list:
        roots = [
            n for n in nodes
            if isinstance(n, dict) or (isinstance(n, str) and n.strip())
        ]
        payload = {
            'document': roots,
            'models': _relevant_models(config.models, config.root),
        }
        return [json.dumps(payload, ensure_ascii=False, indent=2)]


def _positions(config) -> dict:
    """Source positions for this document, built once per transform.

    Cached on the run's output functions because it costs a second parse of
    the file. Absent without an ``input_path`` — a caller handing in a tree it
    built itself has no source text to point at.
    """
    owner = config.pmf
    cached = getattr(owner, '_positions_cache', None)
    if cached is not None:
        return cached
    path = config.input_path
    root = config.root
    positions: dict = {}
    if path and root is not None:
        # A chunk selector may hand us a rebuilt tree; positions live in the
        # document it was copied from.
        # `or` would truth-test the element: a childless one is falsy, so a
        # valid origin would be silently swapped back for the chunk copy.
        origin = source_map.source_of(root)
        if origin is None:
            origin = root
        positions = source_positions.build(Path(str(path)), origin)
    if owner is not None:
        owner._positions_cache = positions
    return positions


def _relevant_models(models: dict | None, root) -> dict:
    """Drop models for elements this document does not contain.

    The table exists to answer "which model won" and, more usefully, "why did
    mine not win" — so every model competing for an element that is *present*
    has to stay, whether or not it fired. Models for elements the document
    never uses can answer neither question about this document, and on a large
    ODD they are most of the table.

    Pruning is keyed on the source tree rather than on the emitted records:
    an element inside a suppressed subtree produces no record, but its models
    are exactly what you are looking at when you ask why nothing came out.
    """
    if not models:
        return {}
    if root is None:
        return models
    present = {
        _local_name(el) for el in root.iter() if isinstance(el.tag, str)
    }
    return {
        key: entry for key, entry in models.items()
        if entry.get('element') in present
    }


def _flatten(value) -> str | int | float | bool | None:
    """Reduce an XPath result to a JSON scalar for a record field.

    Numbers and booleans keep their type; everything else becomes text.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, etree._Element):
        return (''.join(value.itertext())).strip() or None
    if isinstance(value, (list, tuple)):
        parts = [_flatten(v) for v in value]
        joined = ' '.join(str(p) for p in parts if p)
        return joined.strip() or None
    return str(value)
