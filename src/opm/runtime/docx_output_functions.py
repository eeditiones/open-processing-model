# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DOCX serialisation for the TEI processing model (docx-functions.xql equivalent).

Uses python-docx for OPC packaging and raw lxml OOXML elements for content.
Content is accumulated as a flat list (like Markdown mode), then assembled
into a .docx binary in finish().
"""

from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import quoteattr

from lxml import etree

from opm.runtime.markdown_output_functions import _get_css_map
from opm.runtime.output_functions import (
    PMResult,
    ProcessingModelFunctions,
    apply_pb_template,
    normalize,
    child_nodes,
)

# ── OOXML constants ────────────────────────────────────────────────────────────

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'

# Internal sentinel namespace for placeholder elements resolved in finish()
_DOCX_NS = 'http://www.tei-c.org/ns/docx'
FOOTNOTE_SENTINEL_TAG = f'{{{_DOCX_NS}}}footnote-sentinel'
HYPERLINK_SENTINEL_TAG = f'{{{_DOCX_NS}}}hyperlink-sentinel'
IMAGE_SENTINEL_TAG = f'{{{_DOCX_NS}}}image-sentinel'

FOOTNOTES_RT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes'
FOOTNOTES_CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml'
HYPERLINK_RT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'
IMAGE_RT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def docx_apply_children(config, source_node, content, parent_el) -> None:
    """apply_children variant for DOCX: keeps lxml elements as elements in list parents.

    The standard pm_runtime.apply_children serializes elements to HTML strings when
    the parent accumulator is a list (Markdown mode).  DOCX needs actual lxml OOXML
    elements in the list so they can be assembled into a document later.
    """
    from opm.runtime.pm_runtime import apply as _pm_apply, append_to  # noqa: PLC0415

    norm = config.normalize_text
    for item in normalize(content):
        if isinstance(item, str):
            s = norm(item) if norm else item
            if isinstance(parent_el, list):
                parent_el.append(s)
            else:
                append_to(parent_el, s)
        elif isinstance(item, etree._Element):
            dispatch = config.dispatch
            sub = (
                _pm_apply(config, child_nodes(source_node), dispatch)
                if item is source_node
                else _pm_apply(config, [item], dispatch)
            )
            if isinstance(parent_el, list):
                parent_el.extend(sub)
            else:
                for r in sub:
                    append_to(parent_el, r)


# ── Low-level OOXML helpers ────────────────────────────────────────────────────

def _w(tag: str) -> etree._Element:
    return etree.Element(f'{{{W}}}{tag}')


def _ooxml_text(items: list) -> str:
    """Flatten applied output to plain text by reading its ``w:t`` runs."""
    parts: list[str] = []
    for item in items:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, etree._Element) and not callable(item.tag):
            parts.extend(t.text or '' for t in item.iter(f'{{{W}}}t'))
    return ''.join(parts)


def _wsub(parent: etree._Element, tag: str) -> etree._Element:
    return etree.SubElement(parent, f'{{{W}}}{tag}')


def _wset(el: etree._Element, attr: str, val: str) -> None:
    el.set(f'{{{W}}}{attr}', val)


# ── CSS parsing (shared with Markdown approach) ────────────────────────────────

# The class map is markdown_output_functions._get_css_map: one parser for every
# text backend, cached per stylesheet.


def _css_props(config: dict, cls: list) -> dict:
    """Return merged CSS property dict for the given class list."""
    css_map = _get_css_map(config)
    combined: dict = {}
    for item in cls:
        if item:
            for name in str(item).split():
                if name in css_map:
                    combined.update(css_map[name])
    return combined


# ── Main class ─────────────────────────────────────────────────────────────────

class DocxOutputFunctions(ProcessingModelFunctions):
    """DOCX output for TEI processing model.

    Style resolution rules (matching tei-publisher-lib):
    - For each ODD cssClass that does not start with ``tei-``, look up the name
      (case-insensitive) in the template's paragraph / character / table style
      index.  First match wins; unknown classes are silently skipped.
    - Paragraph fallback: "Normal".  Character fallback: no style (CSS properties
      like bold/italic still apply).  Table fallback: "TableGrid".
    """

    def __init__(self) -> None:
        self._styles_loaded = False
        self._para_styles: dict[str, str] = {}
        self._char_styles: dict[str, str] = {}
        self._table_styles: dict[str, str] = {}
        self._bullet_numid: int = 1
        self._ordered_numid: int = 5
        self._bullet_abstract_id: int = 8   # python-docx default abstract for bullet
        self._ordered_abstract_id: int = 7  # python-docx default abstract for ordered
        self._needs_numbering: bool = False
        self._current_template: str | None = None  # Store template path globally
        # Per-run package state; a run creates its own instance.
        self._footnotes: dict[int, list] = {}
        self._num_instances: list[tuple[int, str]] = []
        self._image_counter = 0
        self._image_rid_map: dict[str, str] = {}

    # ── Style index ────────────────────────────────────────────────────────────

    def _ensure_styles(self, config: dict) -> None:
        if self._styles_loaded:
            return
        from docx import Document  # noqa: PLC0415
        template = config.docx_template
        if template:
            self._current_template = template
        doc = Document(template) if template else Document()
        self._load_style_index(doc)

    def _load_style_index(self, doc) -> None:
        from docx.enum.style import WD_STYLE_TYPE  # noqa: PLC0415
        self._para_styles = {}
        self._char_styles = {}
        self._table_styles = {}
        for style in doc.styles:
            if style.style_id is None:
                continue
            sid = style.style_id
            name_key = style.name.lower()
            if style.type == WD_STYLE_TYPE.PARAGRAPH:
                self._para_styles[name_key] = sid
            elif style.type == WD_STYLE_TYPE.CHARACTER:
                self._char_styles[name_key] = sid
            elif style.type == WD_STYLE_TYPE.TABLE:
                self._table_styles[name_key] = sid
            else:
                continue
        try:
            np = doc.part.numbering_part
            b_num, o_num, b_abs, o_abs = self._find_list_numids(np._element)
            self._bullet_numid, self._ordered_numid = b_num, o_num
            self._bullet_abstract_id, self._ordered_abstract_id = b_abs, o_abs
            self._needs_numbering = False
        except (KeyError, NotImplementedError, AttributeError):
            self._needs_numbering = True
            # Resolve abstract IDs from the python-docx bundled default
            self._init_default_numbering_ids()
        # Always register Hyperlink so link() can reference it even when the
        # template omits it — the style itself is injected into styles.xml in finish().
        if 'hyperlink' not in self._char_styles:
            self._char_styles['hyperlink'] = 'Hyperlink'
        self._styles_loaded = True

    def _init_default_numbering_ids(self) -> None:
        """Load abstract numIds from the python-docx bundled default.docx."""
        import docx as _docx_pkg  # noqa: PLC0415
        import os  # noqa: PLC0415
        from docx import Document as _Doc  # noqa: PLC0415
        _path = os.path.join(os.path.dirname(_docx_pkg.__file__), 'templates', 'default.docx')
        _np = _Doc(_path).part.numbering_part
        b_num, o_num, b_abs, o_abs = self._find_list_numids(_np._element)
        self._bullet_numid, self._ordered_numid = b_num, o_num
        self._bullet_abstract_id, self._ordered_abstract_id = b_abs, o_abs

    def _find_list_numids(self, numbering_el) -> tuple[int, int, int, int]:
        """Scan numbering.xml for the first bullet and ordered numId+abstractNumId."""
        WP = f'{{{W}}}'
        abstract_formats: dict[str, str] = {}
        for abs_num in numbering_el.findall(f'{WP}abstractNum'):
            aid = abs_num.get(f'{WP}abstractNumId')
            lvl = abs_num.find(f'{WP}lvl[@{WP}ilvl="0"]')
            if lvl is None:
                lvl = abs_num.find(f'{WP}lvl')
            if lvl is not None:
                fmt_el = lvl.find(f'{WP}numFmt')
                if fmt_el is not None:
                    abstract_formats[aid] = fmt_el.get(f'{WP}val', '')
        bullet_numid: int | None = None
        bullet_abs: int | None = None
        ordered_numid: int | None = None
        ordered_abs: int | None = None
        for num in numbering_el.findall(f'{WP}num'):
            numid = int(num.get(f'{WP}numId', '0'))
            ref = num.find(f'{WP}abstractNumId')
            if ref is not None:
                aid_val = ref.get(f'{WP}val', '')
                fmt = abstract_formats.get(aid_val, '')
                if fmt == 'bullet' and bullet_numid is None:
                    bullet_numid, bullet_abs = numid, int(aid_val)
                elif fmt == 'decimal' and ordered_numid is None:
                    ordered_numid, ordered_abs = numid, int(aid_val)
        return bullet_numid or 1, ordered_numid or 5, bullet_abs or 8, ordered_abs or 7

    def _resolve_para_style(self, cls: list) -> str:
        for item in cls:
            if not item:
                continue
            for name in str(item).split():
                if name.startswith('tei-'):
                    continue
                found = self._para_styles.get(name.lower())
                if found:
                    return found
        return 'Normal'

    def _resolve_char_style(self, cls: list) -> str | None:
        for item in cls:
            if not item:
                continue
            for name in str(item).split():
                if name.startswith('tei-'):
                    continue
                found = self._char_styles.get(name.lower())
                if found:
                    return found
        return None

    def _resolve_table_style(self, cls: list) -> str:
        for item in cls:
            if not item:
                continue
            for name in str(item).split():
                if name.startswith('tei-'):
                    continue
                found = self._table_styles.get(name.lower())
                if found:
                    return found
        return self._table_styles.get('table grid', 'TableGrid')

    # ── OOXML element factories ────────────────────────────────────────────────

    def _make_para(self, style_id: str = 'Normal') -> etree._Element:
        p = _w('p')
        pPr = _wsub(p, 'pPr')
        pStyle = _wsub(pPr, 'pStyle')
        _wset(pStyle, 'val', style_id)
        return p

    def _get_para_style(self, p: etree._Element) -> str | None:
        """Return the w:pStyle val of a <w:p>, or None if absent."""
        pPr = p.find(f'{{{W}}}pPr')
        if pPr is None:
            return None
        pStyle = pPr.find(f'{{{W}}}pStyle')
        if pStyle is None:
            return None
        return pStyle.get(f'{{{W}}}val')

    def _set_para_style(self, p: etree._Element, style_id: str) -> None:
        """Set the w:pStyle val of a <w:p>, creating pPr/pStyle if needed."""
        pPr = p.find(f'{{{W}}}pPr')
        if pPr is None:
            pPr = _w('pPr')
            p.insert(0, pPr)
        pStyle = pPr.find(f'{{{W}}}pStyle')
        if pStyle is None:
            pStyle = _w('pStyle')
            pPr.insert(0, pStyle)
        _wset(pStyle, 'val', style_id)

    def _make_run(
        self,
        text: str,
        *,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        char_style: str | None = None,
    ) -> etree._Element:
        r = _w('r')
        if bold or italic or underline or char_style:
            rPr = _wsub(r, 'rPr')
            if char_style:
                rStyle = _wsub(rPr, 'rStyle')
                _wset(rStyle, 'val', char_style)
            if bold:
                _wsub(rPr, 'b')
            if italic:
                _wsub(rPr, 'i')
            if underline:
                u_el = _wsub(rPr, 'u')
                _wset(u_el, 'val', 'single')
        t = _wsub(r, 't')
        t.text = text
        if text and (text[0] == ' ' or text[-1] == ' '):
            t.set(XML_SPACE, 'preserve')
        return r

    # ── Content accumulation helpers ───────────────────────────────────────────

    def _is_structural(self, el) -> bool:
        if not isinstance(el, etree._Element):
            return False
        if callable(el.tag):  # lxml Comment, PI, CDATA — tag is a Cython callable
            return False
        return etree.QName(el).localname in ('p', 'tbl', 'sdt')

    def _collect(self, config: dict, node, content) -> list:
        items: list = []
        config.apply_children(config, node, content, items)
        return self._filter_ooxml(items)

    _ALLOWED_NS = {W, 'http://www.tei-c.org/ns/docx'}

    def _filter_ooxml(self, items: list) -> list:
        """Remove any lxml elements that are not in a recognised OOXML namespace.

        HTML elements (span, pb-popover, template, …) leak in when the pm runtime
        parses webcomponent / alternate HTML template strings.  They must not reach
        the DOCX body or any w:p content.
        """
        result = []
        for item in items:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, etree._Element) and not callable(item.tag):
                ns = etree.QName(item.tag).namespace
                if ns in self._ALLOWED_NS:
                    result.append(item)
        return result

    def _items_to_runs(
        self,
        items: list,
        *,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        char_style: str | None = None,
    ) -> list:
        result = []
        for item in items:
            if isinstance(item, str):
                if item:
                    result.append(self._make_run(
                        item, bold=bold, italic=italic,
                        underline=underline, char_style=char_style,
                    ))
            elif isinstance(item, etree._Element) and not callable(item.tag):
                if etree.QName(item.tag).namespace in self._ALLOWED_NS:
                    result.append(item)
        return result

    def _wrap_in_para(self, items: list, style_id: str = 'Normal') -> etree._Element | None:
        """Build a ``<w:p>`` from a flat list of strings and inline elements.

        Whitespace-only strings are skipped; a paragraph is returned only when
        it contains at least one non-empty run or inline element.
        """
        p = self._make_para(style_id)
        has_content = False
        for item in items:
            if isinstance(item, str):
                if item.strip():
                    p.append(self._make_run(item))
                    has_content = True
            elif isinstance(item, etree._Element) and not callable(item.tag):
                if etree.QName(item.tag).namespace in self._ALLOWED_NS:
                    p.append(item)
                    has_content = True
        return p if has_content else None

    def _blockify(self, items: list, para_style: str = 'Normal') -> list:
        """Separate structural blocks from inline content; wrap inlines in ``<w:p>``."""
        result: list = []
        pending: list = []

        def flush() -> None:
            if not pending:
                return
            p = self._wrap_in_para(pending, para_style)
            if p is not None:
                result.append(p)
            pending.clear()

        for item in items:
            if not isinstance(item, (str, etree._Element)):
                continue  # skip unexpected items (e.g. XPath atomics)
            if isinstance(item, etree._Element) and self._is_structural(item):
                flush()
                result.append(item)
            else:
                pending.append(item)
        flush()
        return result

    def _add_pstyle_free_abstracts(self, numbering_el) -> tuple[int, int]:
        """Inject fresh multilevel abstract definitions for bullet and ordered lists.

        Rather than copying the template's single-level abstracts (which only define
        ilvl=0 and therefore break nested lists), we build complete 9-level definitions
        from scratch — matching the XQuery fallback-abstract-num-ordered/bullet approach.
        Each new abstract gets a unique abstractNumId and w:nsid.

        Returns ``(bullet_abstract_id, ordered_abstract_id)``.
        """
        WP = f'{{{W}}}'
        existing_ids = {
            int(a.get(f'{WP}abstractNumId', '-1'))
            for a in numbering_el.findall(f'{WP}abstractNum')
        }
        existing_nsids = set()
        for a in numbering_el.findall(f'{WP}abstractNum'):
            nsid_el = a.find(f'{WP}nsid')
            if nsid_el is not None:
                existing_nsids.add(nsid_el.get(f'{WP}val', '').upper())

        next_id = max(existing_ids, default=0) + 1
        next_nsid = max((int(v, 16) for v in existing_nsids if v), default=0x00000000) + 1

        bullet_id = next_id
        ordered_id = next_id + 1

        def _make_abstract(abs_id: int, nsid_val: int, fmt: str) -> etree._Element:
            abs_el = etree.Element(f'{WP}abstractNum')
            abs_el.set(f'{WP}abstractNumId', str(abs_id))
            nsid_el = etree.SubElement(abs_el, f'{WP}nsid')
            nsid_el.set(f'{WP}val', f'{nsid_val:08X}')
            ml_el = etree.SubElement(abs_el, f'{WP}multiLevelType')
            ml_el.set(f'{WP}val', 'multilevel')
            for ilvl in range(9):
                indent = 360 * (ilvl + 1)
                lvl_el = etree.SubElement(abs_el, f'{WP}lvl')
                lvl_el.set(f'{WP}ilvl', str(ilvl))
                start_el = etree.SubElement(lvl_el, f'{WP}start')
                start_el.set(f'{WP}val', '1')
                fmt_el = etree.SubElement(lvl_el, f'{WP}numFmt')
                fmt_el.set(f'{WP}val', fmt)
                txt_el = etree.SubElement(lvl_el, f'{WP}lvlText')
                txt_el.set(f'{WP}val', '' if fmt == 'bullet' else f'%{ilvl + 1}.')
                jc_el = etree.SubElement(lvl_el, f'{WP}lvlJc')
                jc_el.set(f'{WP}val', 'left')
                pPr_el = etree.SubElement(lvl_el, f'{WP}pPr')
                tabs_el = etree.SubElement(pPr_el, f'{WP}tabs')
                tab_el = etree.SubElement(tabs_el, f'{WP}tab')
                tab_el.set(f'{WP}val', 'num')
                tab_el.set(f'{WP}pos', str(indent))
                ind_el = etree.SubElement(pPr_el, f'{WP}ind')
                ind_el.set(f'{WP}left', str(indent))
                ind_el.set(f'{WP}hanging', '360')
                if fmt == 'bullet':
                    rPr_el = etree.SubElement(lvl_el, f'{WP}rPr')
                    fonts_el = etree.SubElement(rPr_el, f'{WP}rFonts')
                    fonts_el.set(f'{WP}ascii', 'Symbol')
                    fonts_el.set(f'{WP}hAnsi', 'Symbol')
                    fonts_el.set(f'{WP}hint', 'default')
            return abs_el

        bullet_abs = _make_abstract(bullet_id, next_nsid, 'bullet')
        ordered_abs = _make_abstract(ordered_id, next_nsid + 1, 'decimal')

        first_num = numbering_el.find(f'{WP}num')
        if first_num is not None:
            first_num.addprevious(ordered_abs)
            first_num.addprevious(bullet_abs)
        else:
            numbering_el.append(bullet_abs)
            numbering_el.append(ordered_abs)

        return bullet_id, ordered_id

    def _should_preserve_whitespace(self, cls: list) -> bool:
        """Return True if the class list indicates preformatted/code content."""
        for item in cls:
            if not item:
                continue
            for name in str(item).split():
                if name in ('Code', 'Preformatted', 'CodeChar', 'tei-code', 'tei-tag'):
                    return True
        return False

    def _split_newlines(self, items: list) -> list:
        """Replace \\n in string items with <w:r><w:br/></w:r> elements."""
        result: list = []
        for item in items:
            if isinstance(item, str):
                lines = item.split('\n')
                for i, line in enumerate(lines):
                    if i > 0:
                        br_r = _w('r')
                        _wsub(br_r, 'br')
                        result.append(br_r)
                    if line:
                        result.append(line)
            else:
                result.append(item)
        return result

    # ── Behaviour methods ──────────────────────────────────────────────────────

    def block(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        style = self._resolve_para_style(cls)
        preserve = self._should_preserve_whitespace(cls)
        items = self._collect(
            config.derive(normalize_text=None) if preserve else config, node, content,
        )
        if preserve:
            items = self._split_newlines(items)
        result = self._blockify(items, style)
        # Propagate the block style to child paragraphs that carry only the document
        # default — covers <note>/<para> → Alert, <programlisting> → Code, etc.
        # Paragraphs with any explicit style (headings, list items, …) are left alone.
        _PROPAGATE_FROM = {None, 'Normal', 'Standard'}
        if style not in _PROPAGATE_FROM:
            for el in result:
                if (
                    isinstance(el, etree._Element)
                    and not callable(el.tag)
                    and etree.QName(el).localname == 'p'
                    and self._get_para_style(el) in _PROPAGATE_FROM
                ):
                    self._set_para_style(el, style)
        return result

    def inline(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        items = self._collect(config, node, content)
        char_style = self._resolve_char_style(cls)
        css = _css_props(config, cls)
        return self._items_to_runs(
            items,
            bold='bold' in css.get('font-weight', ''),
            italic='italic' in css.get('font-style', ''),
            underline='underline' in css.get('text-decoration', ''),
            char_style=char_style,
        )

    def paragraph(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        items = self._collect(config, node, content)
        style_id = self._resolve_para_style(cls)
        p = self._make_para(style_id)
        has_content = False
        for item in items:
            if isinstance(item, str):
                if item.strip():
                    p.append(self._make_run(item))
                    has_content = True
            elif isinstance(item, etree._Element):
                local = etree.QName(item).localname
                if local == 'p':
                    # Flatten nested w:p — extract its inline children into our para
                    for child in list(item):
                        p.append(child)
                        has_content = True
                elif local != 'tbl':
                    p.append(item)
                    has_content = True
        return [p] if has_content else []

    def heading(self, config, node, cls, content, level=None) -> PMResult:
        self._ensure_styles(config)
        items = self._collect(config, node, content)
        lvl = max(1, min(9, int(level) if level and str(level).isdigit() else 1))
        style_id = self._para_styles.get(f'heading {lvl}', f'Heading{lvl}')
        p = self._wrap_in_para(items, style_id)
        return [p] if p is not None else []

    def section(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

    def body(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

    def document(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

    def pass_through(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

    def list(self, config, node, cls, content, type=None) -> PMResult:
        self._ensure_styles(config)
        # Fall back to reading @type from the source node when the ODD doesn't pass it
        if not type and node is not None:
            type = node.get('type') or None
        prev_type = config.list_type
        prev_depth = config.list_depth
        effective_type = type or 'unordered'
        # Allocate a fresh numId when:
        # - this is a top-level list (prev_depth < 0), OR
        # - this is a nested list of a DIFFERENT type than the parent
        #   (e.g. ordered inside bullet needs its own decimal counter).
        # Same-type nested lists reuse the parent numId so the ilvl drives indentation.
        is_ordered = effective_type == 'ordered'
        parent_type = prev_type or 'unordered'
        type_changed = effective_type != parent_type
        list_id = config.list_id
        if prev_depth < 0 or type_changed:
            list_id = 100 + len(self._num_instances)
            self._num_instances.append((list_id, 'ordered' if is_ordered else 'bullet'))
        # The items see this list's settings; the list's siblings keep their own.
        sub = config.derive(list_type=effective_type, list_depth=prev_depth + 1, list_id=list_id)
        return self._collect(sub, node, content)

    def list_item(self, config, node, cls, content, n=None) -> PMResult:
        self._ensure_styles(config)
        items = self._collect(config, node, content)
        list_type = config.list_type or 'unordered'
        depth = max(config.list_depth, 0)
        numid = config.list_id or (
            self._ordered_numid if list_type == 'ordered' else self._bullet_numid
        )
        # Use ListParagraph base style (locale-independent; German: Listenabsatz)
        list_para = (
            self._para_styles.get('list paragraph')
            or self._para_styles.get('listenabsatz')
            or 'Normal'
        )
        result = self._blockify(items, list_para)
        # Inject w:numPr into paragraphs that don't already have one.
        # Paragraphs from nested list_item() calls already carry correct numPr
        # (deeper ilvl / inner numId) — overwriting them would collapse all
        # levels to the outer depth.
        for el in result:
            if isinstance(el, etree._Element) and not callable(el.tag) and etree.QName(el).localname == 'p':
                pPr = el.find(f'{{{W}}}pPr')
                if pPr is None:
                    pPr = _w('pPr')
                    el.insert(0, pPr)
                if pPr.find(f'{{{W}}}numPr') is not None:
                    continue  # already set by a nested list — preserve it
                numPr = _w('numPr')
                ilvl_el = _wsub(numPr, 'ilvl')
                _wset(ilvl_el, 'val', str(depth))
                numId_el = _wsub(numPr, 'numId')
                _wset(numId_el, 'val', str(numid))
                pStyle_el = pPr.find(f'{{{W}}}pStyle')
                if pStyle_el is not None:
                    pStyle_el.addnext(numPr)
                else:
                    pPr.insert(0, numPr)
        return result

    def link(self, config, node, cls, content, uri=None, target=None, optional=None) -> PMResult:
        self._ensure_styles(config)
        items = self._collect(config, node, content)
        if not uri:
            return items
        char_style = self._char_styles.get('hyperlink')
        if uri.startswith('#'):
            hyperlink = _w('hyperlink')
            _wset(hyperlink, 'anchor', uri.lstrip('#'))
            for item in items:
                if isinstance(item, str) and item:
                    hyperlink.append(self._make_run(item, char_style=char_style))
                elif isinstance(item, etree._Element):
                    hyperlink.append(item)
            return [hyperlink]
        # External link: sentinel resolved to a w:hyperlink with OPC relationship in finish()
        sentinel = etree.Element(HYPERLINK_SENTINEL_TAG)
        sentinel.set('href', uri)
        for item in items:
            if isinstance(item, str) and item:
                sentinel.append(self._make_run(item, char_style=char_style))
            elif isinstance(item, etree._Element):
                sentinel.append(item)
        return [sentinel]

    def table(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        items = self._collect(config, node, content)
        tbl = _w('tbl')
        tblPr = _wsub(tbl, 'tblPr')
        tblStyle = _wsub(tblPr, 'tblStyle')
        _wset(tblStyle, 'val', self._resolve_table_style(cls))
        tblW = _wsub(tblPr, 'tblW')
        _wset(tblW, 'w', '0')
        _wset(tblW, 'type', 'auto')
        for item in items:
            if isinstance(item, etree._Element) and etree.QName(item).localname == 'tr':
                tbl.append(item)
        return [tbl]

    def row(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        items = self._collect(config, node, content)
        tr = _w('tr')
        for item in items:
            if isinstance(item, etree._Element) and etree.QName(item).localname == 'tc':
                tr.append(item)
        return [tr]

    def cell(self, config, node, cls, content, type=None) -> PMResult:
        self._ensure_styles(config)
        items = self._collect(config, node, content)
        tc = _w('tc')
        for block in self._blockify(items):
            tc.append(block)
        if not any(etree.QName(c).localname == 'p' for c in tc):
            tc.append(self._make_para())
        return [tc]

    def figure(self, config, node, cls, content, title=None) -> PMResult:
        self._ensure_styles(config)
        items = self._collect(config, node, content)
        title_items = self._collect(config, node, title) if title is not None else []
        has_caption = any(
            (isinstance(i, str) and i.strip()) or
            (isinstance(i, etree._Element) and not callable(i.tag))
            for i in title_items
        )

        figure_style_id = self._para_styles.get('figure', 'Figure')
        figure_items = self._blockify(items, figure_style_id)

        if not has_caption:
            return figure_items

        # Mirror XQuery pmf:p-add-keep-next: add keepNext to each figure paragraph
        for item in figure_items:
            if isinstance(item, etree._Element) and item.tag == f'{{{W}}}p':
                ppr = item.find(f'{{{W}}}pPr')
                if ppr is None:
                    ppr = _w('pPr')
                    item.insert(0, ppr)
                if ppr.find(f'{{{W}}}keepNext') is None:
                    ppr.insert(0, _w('keepNext'))

        caption_style_id = self._para_styles.get('caption', 'Caption')
        caption_para = etree.Element(f'{{{W}}}p')
        caption_ppr = etree.SubElement(caption_para, f'{{{W}}}pPr')
        etree.SubElement(caption_ppr, f'{{{W}}}pStyle').set(f'{{{W}}}val', caption_style_id)

        # Delegate content processing to the transform pipeline (mirrors pmf:apply-runs)
        for item in title_items:
            if isinstance(item, str):
                if item:
                    caption_para.append(self._make_run(item))
            elif isinstance(item, etree._Element) and not callable(item.tag):
                caption_para.append(item)

        return figure_items + [caption_para]

    def graphic(self, config, node, cls, content, url=None,
                width=None, height=None, scale=None, title=None) -> PMResult:
        self._ensure_styles(config)
        # Handle TEI graphic elements - check for corresp attribute first
        image_url = url
        if node is not None and image_url is None:
            image_url = node.get('corresp')
        
        if not image_url:
            return [self._make_run('[Image: missing URL]')]
        
        # Create sentinel for later processing
        sentinel = etree.Element(IMAGE_SENTINEL_TAG)
        sentinel.set('url', image_url)
        if width:
            sentinel.set('width', str(width))
        if height:
            sentinel.set('height', str(height))
        if scale:
            sentinel.set('scale', str(scale))
        if title:
            sentinel.set('title', title)
        
        return [sentinel]

    def note(self, config, node, cls, content, place=None, label=None) -> PMResult:
        self._ensure_styles(config)
        fn_id = len(self._footnotes) + 1
        self._footnotes[fn_id] = self._collect(config, node, content)
        sentinel = etree.Element(FOOTNOTE_SENTINEL_TAG)
        sentinel.set('id', str(fn_id))
        return [sentinel]

    def cit(self, config, node, cls, content, source=None) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

    def webcomponent(self, config, node, cls, content, name=None, optional=None) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, node)

    def omit(self, config, node, cls, content) -> PMResult:
        return []

    def index(self, config, node, cls, content, type=None) -> PMResult:
        return []

    def break_(self, config, node, cls, content, type=None, label=None) -> PMResult:
        r = _w('r')
        br = _wsub(r, 'br')
        if type == 'page':
            _wset(br, 'type', 'page')
        return [r]

    def anchor(self, config, node, cls, content, id=None) -> PMResult:
        if not id:
            return []
        bookmark_id = abs(hash(id)) % 100000
        start = _w('bookmarkStart')
        _wset(start, 'id', str(bookmark_id))
        _wset(start, 'name', id)
        end = _w('bookmarkEnd')
        _wset(end, 'id', str(bookmark_id))
        return [start, end]

    def alternate(self, config, node, cls, content, default=None, alternate=None, optional=None) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

    def glyph(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

    def text(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

    def metadata(self, config, node, cls, content, key=None) -> PMResult:
        """Collect a header value under *key* instead of emitting body content.

        Mirrors `TypstOutputFunctions.metadata`: the ODD names the field,
        the collected text lands in ``config.state.metadata`` and is
        mapped onto the ``.docx`` core properties by [`finish`][opm.runtime.docx_output_functions.DocxOutputFunctions.finish].
        """
        if key:
            self._ensure_styles(config)
            text = _ooxml_text(self._collect(config, node, content)).strip()
            config.state.metadata.setdefault(str(key), []).append(text)
        return []

    def title(self, config, node, cls, content) -> PMResult:
        return []

    def match(self, config, node, cls, content) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

    def template(self, config, node, cls, template_str: str, params: dict) -> PMResult:
        self._ensure_styles(config)
        items = apply_pb_template(template_str, params, config)
        return self._blockify(items)

    # ── finish() ───────────────────────────────────────────────────────────────

    def _inject_missing_builtin_styles(self, doc) -> None:
        """Inject built-in styles (Hyperlink, FootnoteText, FootnoteReference) absent from the template.

        Mirrors the XQuery pmf:ensure-builtin-styles logic so templates that
        don't ship these styles still produce correctly formatted output.
        """
        WP = f'{{{W}}}'
        styles_el = doc.part.styles._element
        existing_ids = (
            {el.get(f'{WP}styleId') for el in styles_el.findall(f'{WP}style')}
            | {el.find(f'{WP}name').get(f'{WP}val', '')
               for el in styles_el.findall(f'{WP}style')
               if el.find(f'{WP}name') is not None}
        )

        if not {'Caption', 'caption'} & existing_ids:
            caption_style = etree.SubElement(styles_el, f'{WP}style')
            caption_style.set(f'{WP}type', 'paragraph')
            caption_style.set(f'{WP}styleId', 'Caption')
            caption_style.set(f'{WP}customStyle', '1')
            name_el = etree.SubElement(caption_style, f'{WP}name')
            name_el.set(f'{WP}val', 'caption')
            based_on = etree.SubElement(caption_style, f'{WP}basedOn')
            based_on.set(f'{WP}val', 'Normal')
            next_el = etree.SubElement(caption_style, f'{WP}next')
            next_el.set(f'{WP}val', 'Normal')
            ui_pri = etree.SubElement(caption_style, f'{WP}uiPriority')
            ui_pri.set(f'{WP}val', '35')
            etree.SubElement(caption_style, f'{WP}qFormat')
            rpr = etree.SubElement(caption_style, f'{WP}rPr')
            etree.SubElement(rpr, f'{WP}i')
            etree.SubElement(rpr, f'{WP}iCs')

        default_para = 'Normal'
        for style_el in styles_el.findall(f'{WP}style'):
            if (style_el.get(f'{WP}type') == 'paragraph'
                    and style_el.get(f'{WP}default') == '1'):
                sid = style_el.get(f'{WP}styleId')
                if sid:
                    default_para = sid
                break

        default_char = 'DefaultParagraphFont'
        for style_el in styles_el.findall(f'{WP}style'):
            if (style_el.get(f'{WP}type') == 'character'
                    and style_el.get(f'{WP}default') == '1'):
                sid = style_el.get(f'{WP}styleId')
                if sid:
                    default_char = sid
                    break

        if 'Hyperlink' not in existing_ids and 'hyperlink' not in existing_ids:
            hl = etree.SubElement(styles_el, f'{WP}style')
            hl.set(f'{WP}type', 'character')
            hl.set(f'{WP}styleId', 'Hyperlink')
            name_el = etree.SubElement(hl, f'{WP}name')
            name_el.set(f'{WP}val', 'Hyperlink')
            based_on = etree.SubElement(hl, f'{WP}basedOn')
            based_on.set(f'{WP}val', default_char)
            ui_pri = etree.SubElement(hl, f'{WP}uiPriority')
            ui_pri.set(f'{WP}val', '99')
            etree.SubElement(hl, f'{WP}unhideWhenUsed')
            rPr = etree.SubElement(hl, f'{WP}rPr')
            color = etree.SubElement(rPr, f'{WP}color')
            color.set(f'{WP}val', '0563C1')
            color.set(f'{WP}themeColor', 'hyperlink')
            u_el = etree.SubElement(rPr, f'{WP}u')
            u_el.set(f'{WP}val', 'single')

        if 'FootnoteText' not in existing_ids and 'footnote text' not in existing_ids:
            ft = etree.SubElement(styles_el, f'{WP}style')
            ft.set(f'{WP}type', 'paragraph')
            ft.set(f'{WP}styleId', 'footnote text')
            name_el = etree.SubElement(ft, f'{WP}name')
            name_el.set(f'{WP}val', 'footnote text')
            based_on = etree.SubElement(ft, f'{WP}basedOn')
            based_on.set(f'{WP}val', default_para)
            ui_pri = etree.SubElement(ft, f'{WP}uiPriority')
            ui_pri.set(f'{WP}val', '99')
            etree.SubElement(ft, f'{WP}semiHidden')
            etree.SubElement(ft, f'{WP}unhideWhenUsed')
            pPr = etree.SubElement(ft, f'{WP}pPr')
            sp = etree.SubElement(pPr, f'{WP}spacing')
            sp.set(f'{WP}after', '0')
            sp.set(f'{WP}line', '240')
            sp.set(f'{WP}lineRule', 'auto')
            rPr = etree.SubElement(ft, f'{WP}rPr')
            sz = etree.SubElement(rPr, f'{WP}sz')
            sz.set(f'{WP}val', '20')
            szCs = etree.SubElement(rPr, f'{WP}szCs')
            szCs.set(f'{WP}val', '20')

        if 'FootnoteReference' not in existing_ids and 'footnote reference' not in existing_ids:
            fr = etree.SubElement(styles_el, f'{WP}style')
            fr.set(f'{WP}type', 'character')
            fr.set(f'{WP}styleId', 'footnote reference')
            name_el = etree.SubElement(fr, f'{WP}name')
            name_el.set(f'{WP}val', 'footnote reference')
            based_on = etree.SubElement(fr, f'{WP}basedOn')
            based_on.set(f'{WP}val', default_char)
            ui_pri = etree.SubElement(fr, f'{WP}uiPriority')
            ui_pri.set(f'{WP}val', '99')
            etree.SubElement(fr, f'{WP}semiHidden')
            etree.SubElement(fr, f'{WP}unhideWhenUsed')
            rPr = etree.SubElement(fr, f'{WP}rPr')
            etree.SubElement(rPr, f'{WP}vertAlign').set(f'{WP}val', 'superscript')

        if 'footnote text' not in self._para_styles:
            self._para_styles['footnote text'] = 'footnote text'
        if 'footnote reference' not in self._char_styles:
            self._char_styles['footnote reference'] = 'footnote reference'
        
        # Inject Figure style if missing — mirrors XQuery pmf:ensure-builtin-styles
        if 'figure' not in self._para_styles:
            self._para_styles['figure'] = 'Figure'
            figure_style = etree.SubElement(styles_el, f'{WP}style')
            _wset(figure_style, 'type', 'paragraph')
            _wset(figure_style, 'styleId', 'Figure')
            name = etree.SubElement(figure_style, f'{WP}name')
            _wset(name, 'val', 'Figure')
            basedOn = etree.SubElement(figure_style, f'{WP}basedOn')
            _wset(basedOn, 'val', default_para)
            next_el = etree.SubElement(figure_style, f'{WP}next')
            _wset(next_el, 'val', 'Caption')
            ui_pri = etree.SubElement(figure_style, f'{WP}uiPriority')
            _wset(ui_pri, 'val', '99')
            pPr = etree.SubElement(figure_style, f'{WP}pPr')
            etree.SubElement(pPr, f'{WP}jc').set(f'{WP}val', 'center')
            spacing = etree.SubElement(pPr, f'{WP}spacing')
            _wset(spacing, 'before', '120')
            _wset(spacing, 'after', '0')

    def _drop_custom_xml_rels(self, doc) -> None:
        """Remove customXml relationships from the document part.

        Template/bibliography customXml is a frequent source of Word 'unreadable content'
        when merged with generated body content. TEI → DOCX does not need it.
        Mirrors the XQuery pmf:make-document-rels which omits customXml deliberately.
        """
        CUSTOM_XML_RT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml'
        rels = doc.part.rels
        to_drop = [rId for rId, rel in list(rels.items()) if rel.reltype == CUSTOM_XML_RT]
        for rId in to_drop:
            rels.pop(rId)

    # ODD metadata key → python-docx core property name.  Core properties are
    # plain strings, so multi-valued keys are joined.
    _CORE_PROPERTY_KEYS = {
        'title': 'title',
        'author': 'author',
        'authors': 'author',
        'subject': 'subject',
        'keywords': 'keywords',
        'category': 'category',
        'comments': 'comments',
        # An abstract has no core property of its own; Word's Comments field is
        # the conventional home for a description. Without this the key would be
        # collected and then silently dropped.
        'abstract': 'comments',
    }

    # OOXML caps core property strings at 255 characters and python-docx raises
    # rather than truncating.  An abstract routinely runs longer, so clamp here:
    # losing the tail of a description beats failing the whole transform.
    _CORE_PROPERTY_MAX = 255

    def _apply_core_properties(self, config: dict, doc) -> None:
        """Map values collected by [`metadata`][opm.runtime.docx_output_functions.DocxOutputFunctions.metadata] onto the document properties."""
        collected = config.state.metadata
        for key, values in collected.items():
            prop = self._CORE_PROPERTY_KEYS.get(str(key).lower())
            if prop is None:
                continue
            text = ', '.join(v for v in values if v)
            if len(text) > self._CORE_PROPERTY_MAX:
                text = text[: self._CORE_PROPERTY_MAX - 1].rstrip() + '\u2026'
            if text:
                setattr(doc.core_properties, prop, text)

    def finish(self, config: dict, nodes: list) -> list:
        """Assemble body elements into a ``.docx`` and return ``[bytes]``."""
        from docx import Document  # noqa: PLC0415
        from docx.opc.part import Part  # noqa: PLC0415
        from docx.opc.packuri import PackURI  # noqa: PLC0415

        template_path = config.docx_template
        doc = Document(template_path) if template_path else Document()
        if not self._styles_loaded:
            self._load_style_index(doc)
        self._inject_missing_builtin_styles(doc)
        self._apply_core_properties(config, doc)

        if self._needs_numbering:
            import docx as _docx_pkg  # noqa: PLC0415
            import os  # noqa: PLC0415
            _default_path = os.path.join(os.path.dirname(_docx_pkg.__file__), 'templates', 'default.docx')
            _default_doc = Document(_default_path)
            _np = _default_doc.part.numbering_part
            from docx.opc.constants import RELATIONSHIP_TYPE as _RT  # noqa: PLC0415
            if doc.part.package:
                _new_np = type(_np)(_np.partname, _np.content_type, _np._element, doc.part.package)
                doc.part.relate_to(_new_np, _RT.NUMBERING)

        # Add per-list w:num instances so each list gets its own counter
        instances = self._num_instances
        if instances:
            numbering_el = doc.part.numbering_part._element
            # Create pStyle-free abstract copies so Word doesn't share a global
            # counter across instances (abstracts with w:pStyle bindings do that).
            bullet_abs_id, ordered_abs_id = self._add_pstyle_free_abstracts(numbering_el)
            kind_to_abs = {'bullet': bullet_abs_id, 'ordered': ordered_abs_id}
            for new_numid, kind in instances:
                num_el = _w('num')
                _wset(num_el, 'numId', str(new_numid))
                abs_ref = _wsub(num_el, 'abstractNumId')
                _wset(abs_ref, 'val', str(kind_to_abs[kind]))
                # Force counter restart at 1 — without this explicit override
                # Word may continue counting from a previous list.
                lvl_override = _wsub(num_el, 'lvlOverride')
                _wset(lvl_override, 'ilvl', '0')
                start_override = _wsub(lvl_override, 'startOverride')
                _wset(start_override, 'val', '1')
                numbering_el.append(num_el)

        body = doc.element.body
        sectPr = body.find(f'{{{W}}}sectPr')
        for child in list(body):
            if etree.QName(child).localname != 'sectPr':
                body.remove(child)

        body_elements = [
            item for item in nodes
            if isinstance(item, etree._Element)
            and not callable(item.tag)
            and etree.QName(item.tag).namespace in self._ALLOWED_NS
        ]
        doc_nsmap = doc.element.nsmap
        self._replace_footnote_sentinels(body_elements, doc_nsmap)
        self._replace_hyperlink_sentinels(body_elements, doc, doc_nsmap)
        self._replace_image_sentinels(body_elements, doc, doc_nsmap, config)

        for el in body_elements:
            if sectPr is not None:
                sectPr.addprevious(el)
            else:
                body.append(el)

        footnotes_data = self._footnotes
        if footnotes_data:
            # Drop any existing footnotes part from the template to avoid duplicates.
            existing_fn_rids = [
                rId for rId, rel in list(doc.part.rels.items())
                if rel.reltype == FOOTNOTES_RT
            ]
            for rId in existing_fn_rids:
                doc.part.rels.pop(rId)
            footnote_rels = self._resolve_footnote_sentinels(
                footnotes_data, doc, doc_nsmap, config
            )
            xml_bytes = self._build_footnotes_xml(footnotes_data)
            footnotes_part = Part(
                PackURI('/word/footnotes.xml'),
                FOOTNOTES_CT,
                xml_bytes,
                doc.part.package,
            )
            doc.part.relate_to(footnotes_part, FOOTNOTES_RT)

        self._drop_custom_xml_rels(doc)

        buf = BytesIO()
        doc.save(buf)

        buf = self._normalize_document_xml(buf)

        if footnotes_data:
            buf = self._inject_footnotes_rels(buf, footnote_rels)

        return [buf.getvalue()]

    # Parts we rewrite to hoist namespace declarations to the root element.
    # Word's strict XML parser rejects inline xmlns: redeclarations on child
    # elements even though they are technically valid XML.
    _NORMALIZE_PARTS = {
        'word/document.xml',
        'word/styles.xml',
        'word/numbering.xml',
        'word/footnotes.xml',
    }
    
    # Supported image formats and their MIME types
    _IMAGE_MIME_TYPES = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.tiff': 'image/tiff',
        '.tif': 'image/tiff',
        '.svg': 'image/svg+xml',
    }

    def _normalize_document_xml(self, buf: BytesIO) -> BytesIO:
        """Rewrite modified XML parts so all namespace declarations sit on the root.

        Our generated elements are created as standalone lxml trees and then
        appended to python-docx's document body / styles element.  When
        python-docx serialises the package each injected child carries its own
        redundant xmlns: declarations.  Word's strict XML parser rejects this
        with XMLParseError {"Element":""}.  A round-trip through lxml's
        serialiser consolidates all namespace declarations on the root element.
        """
        import zipfile as _zipfile  # noqa: PLC0415
        buf.seek(0)
        src = _zipfile.ZipFile(buf, 'r')
        out = BytesIO()
        with _zipfile.ZipFile(out, 'w', _zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename in self._NORMALIZE_PARTS:
                    root = etree.fromstring(data)
                    MC = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
                    mc_ign = f'{{{MC}}}Ignorable'
                    if mc_ign in root.attrib:
                        del root.attrib[mc_ign]
                    
                    # For styles.xml, merge: use template as base and add any styles
                    # injected at runtime (Hyperlink, FootnoteText, Figure, …) that
                    # the template does not already define.
                    if item.filename == 'word/styles.xml' and self._current_template:
                        try:
                            with _zipfile.ZipFile(self._current_template, 'r') as template_zip:
                                template_styles_xml = template_zip.read('word/styles.xml')
                                template_styles = etree.fromstring(template_styles_xml)

                                # IDs already present in the template — don't duplicate them
                                template_ids = {
                                    el.get(f'{{{W}}}styleId')
                                    for el in template_styles.findall(f'{{{W}}}style')
                                }

                                # Start with template styles, then append injected extras
                                merged_styles = template_styles
                                for style_el in list(root.findall(f'{{{W}}}style')):
                                    style_id = style_el.get(f'{{{W}}}styleId')
                                    if style_id and style_id not in template_ids:
                                        import copy  # noqa: PLC0415
                                        merged_styles.append(copy.deepcopy(style_el))

                                data = etree.tostring(
                                    merged_styles,
                                    xml_declaration=True,
                                    encoding='UTF-8',
                                    standalone=True,
                                )
                        except Exception:
                            # If template merging fails, use original styles
                            data = etree.tostring(
                                root,
                                xml_declaration=True,
                                encoding='UTF-8',
                                standalone=True,
                            )
                    else:
                        data = etree.tostring(
                            root,
                            xml_declaration=True,
                            encoding='UTF-8',
                            standalone=True,
                        )
                dst.writestr(item, data)
        src.close()
        out.seek(0)
        return out

    def _create_footnote_image_part(self, config: dict, sentinel: etree._Element, doc):
        """Create the OOXML image part for a sentinel and return its ``word/``-relative name.

        The part is also related from ``document.xml`` so python-docx serializes it
        into the package; the footnote's own relationship is written separately by
        `_inject_footnotes_rels`.
        """
        import os  # noqa: PLC0415

        image_url = sentinel.get('url')
        input_path = config.input_path
        if not image_url or not input_path:
            return None
        image_path = os.path.join(os.path.dirname(os.path.abspath(input_path)), image_url)
        if not os.path.exists(image_path):
            return None

        _, ext = os.path.splitext(image_path.lower())
        mime_type = self._IMAGE_MIME_TYPES.get(ext)
        if not mime_type:
            ext, mime_type = '.png', 'image/png'
        try:
            with open(image_path, 'rb') as fh:
                image_data = fh.read()
        except OSError:
            return None

        self._image_counter += 1
        filename = f'media/image{10 + self._image_counter}{ext}'
        try:
            from docx.opc.packuri import PackURI  # noqa: PLC0415
            from docx.opc.part import Part  # noqa: PLC0415

            image_part = Part(PackURI(f'/word/{filename}'), mime_type, image_data, doc.part.package)
            doc.part.relate_to(image_part, IMAGE_RT)
        except Exception:
            return None
        return filename

    def _resolve_footnote_sentinels(
        self, footnotes_data: dict, doc, nsmap: dict, config: dict
    ) -> list[tuple[str, str, bool]]:
        """Resolve hyperlink and image sentinels inside footnote content.

        Body sentinels are handled by `_replace_hyperlink_sentinels` /
        `_replace_image_sentinels`, which register targets on ``document.xml``'s
        relationship part.  A ``w:hyperlink`` or ``w:drawing`` inside ``footnotes.xml``
        must instead reference ``word/_rels/footnotes.xml.rels``, so ids are allocated
        here and returned for `_inject_footnotes_rels` to write out.  Left in
        place, a sentinel is an element outside the OOXML namespaces and Word offers
        to repair the file.

        Returns ``(rId, target, is_external)`` triples.
        """
        rels: list[tuple[str, str, bool]] = []
        by_href: dict[str, str] = {}

        def next_rid() -> str:
            return f'rId{len(rels) + 1}'

        def to_hyperlink(sentinel: etree._Element) -> etree._Element:
            href = sentinel.get('href', '')
            r_id = by_href.get(href)
            if r_id is None:
                r_id = by_href[href] = next_rid()
                rels.append((r_id, href, True))
            hl = etree.Element(f'{{{W}}}hyperlink', nsmap=nsmap)
            hl.set(f'{{{R_NS}}}id', r_id)
            for child in list(sentinel):
                hl.append(child)
            return hl

        def to_image(sentinel: etree._Element) -> etree._Element:
            target = self._create_footnote_image_part(config, sentinel, doc)
            if target:
                r_id = next_rid()
                rels.append((r_id, target, False))
                drawing = self._create_image_drawing_element(
                    r_id, sentinel.get('width'), sentinel.get('height'), sentinel.get('scale')
                )
                if drawing is not None:
                    return drawing
            # Same degradation as the body path: a visible placeholder, never a
            # sentinel that would corrupt the package.
            return self._make_run(f'[Image: {sentinel.get("url", "")}]')

        def convert(el: etree._Element) -> etree._Element | None:
            if el.tag == HYPERLINK_SENTINEL_TAG:
                return to_hyperlink(el)
            if el.tag == IMAGE_SENTINEL_TAG:
                return to_image(el)
            return None

        def walk(el: etree._Element) -> None:
            for child in list(el):
                replacement = convert(child)
                if replacement is not None:
                    el.replace(child, replacement)
                    walk(replacement)
                else:
                    walk(child)

        for fn_id, items in footnotes_data.items():
            resolved = []
            for item in items:
                if isinstance(item, etree._Element):
                    replacement = convert(item)
                    if replacement is not None:
                        walk(replacement)
                        resolved.append(replacement)
                        continue
                    walk(item)
                resolved.append(item)
            footnotes_data[fn_id] = resolved
        return rels

    def _inject_footnotes_rels(self, buf: BytesIO, rels: list[tuple[str, str, bool]]) -> BytesIO:
        """Write word/_rels/footnotes.xml.rels, carrying any footnote hyperlinks.

        python-docx does not auto-generate a .rels file for raw Part instances.
        The XQuery always emits this file; Word may reject a package that has
        word/footnotes.xml with no corresponding .rels entry.
        """
        import zipfile as _zipfile  # noqa: PLC0415
        RELS_NAME = 'word/_rels/footnotes.xml.rels'
        entries = ''.join(
            f'<Relationship Id="{r_id}" Type="{HYPERLINK_RT if external else IMAGE_RT}" '
            f'Target={quoteattr(target)}'
            + (' TargetMode="External"' if external else '')
            + '/>'
            for r_id, target, external in rels
        )
        rels_xml = (
            "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\r\n"
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{entries}</Relationships>'
        ).encode('utf-8')
        buf.seek(0)
        src = _zipfile.ZipFile(buf, 'r')
        out = BytesIO()
        with _zipfile.ZipFile(out, 'w', _zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                if item.filename == RELS_NAME:
                    continue
                dst.writestr(item, src.read(item.filename))
            dst.writestr(RELS_NAME, rels_xml)
        src.close()
        out.seek(0)
        return out

    def _replace_footnote_sentinels(self, elements: list, nsmap: dict) -> None:
        for el in elements:
            self._replace_sentinels_in(el, nsmap)

    def _replace_sentinels_in(self, el: etree._Element, nsmap: dict) -> None:
        to_replace = [(i, child) for i, child in enumerate(el) if child.tag == FOOTNOTE_SENTINEL_TAG]
        offset = 0
        for orig_idx, sentinel in to_replace:
            fn_id = int(sentinel.get('id') or '0')
            ref_run = etree.Element(f'{{{W}}}r', nsmap=nsmap)
            rPr = etree.SubElement(ref_run, f'{{{W}}}rPr')
            rStyle = etree.SubElement(rPr, f'{{{W}}}rStyle')
            _wset(rStyle, 'val', 'footnote reference')
            fn_ref = etree.SubElement(ref_run, f'{{{W}}}footnoteReference')
            _wset(fn_ref, 'id', str(fn_id))
            el.remove(sentinel)  # type: ignore
            el.insert(orig_idx + offset, ref_run)
            offset += 1 - 1  # remove + insert → net 0
        for child in el:
            self._replace_sentinels_in(child, nsmap)

    def _replace_hyperlink_sentinels(self, body_elements: list, doc, nsmap: dict) -> None:
        for el in body_elements:
            self._replace_hyperlinks_in(el, doc, nsmap)

    def _replace_hyperlinks_in(self, el: etree._Element, doc, nsmap: dict) -> None:
        to_replace = [
            (i, child) for i, child in enumerate(el)
            if child.tag == HYPERLINK_SENTINEL_TAG
        ]
        offset = 0
        for orig_idx, sentinel in to_replace:
            href = sentinel.get('href', '')
            r_id = doc.part.relate_to(href, HYPERLINK_RT, is_external=True)
            hl = etree.Element(f'{{{W}}}hyperlink', nsmap=nsmap)
            hl.set(f'{{{R_NS}}}id', r_id)
            for child in list(sentinel):
                hl.append(child)
            el.remove(sentinel)  # type: ignore
            el.insert(orig_idx + offset, hl)
        for child in el:
            self._replace_hyperlinks_in(child, doc, nsmap)

    def _build_footnotes_xml(self, footnotes_data: dict) -> bytes:
        nsmap = {'w': W, 'r': R_NS}
        root = etree.Element(f'{{{W}}}footnotes', nsmap=nsmap)

        for fn_type, fn_id_str, sep_tag in [
            ('separator', '-1', 'separator'),
            ('continuationSeparator', '0', 'continuationSeparator'),
        ]:
            fn_el = _wsub(root, 'footnote')
            _wset(fn_el, 'type', fn_type)
            _wset(fn_el, 'id', fn_id_str)
            p = _wsub(fn_el, 'p')
            pPr = _wsub(p, 'pPr')
            sp = _wsub(pPr, 'spacing')
            _wset(sp, 'after', '0')
            _wset(sp, 'line', '240')
            _wset(sp, 'lineRule', 'auto')
            r = _wsub(p, 'r')
            _wsub(r, sep_tag)

        for fn_id, fn_items in sorted(footnotes_data.items()):
            fn_el = _wsub(root, 'footnote')
            _wset(fn_el, 'id', str(fn_id))

            para = _wsub(fn_el, 'p')
            pPr = _wsub(para, 'pPr')
            pStyle = _wsub(pPr, 'pStyle')
            _wset(pStyle, 'val', self._para_styles.get('footnote text', 'footnote text'))

            marker_r = _wsub(para, 'r')
            marker_rPr = _wsub(marker_r, 'rPr')
            marker_rStyle = _wsub(marker_rPr, 'rStyle')
            _wset(marker_rStyle, 'val',
                  self._char_styles.get('footnote reference', 'footnote reference'))
            _wsub(marker_r, 'footnoteRef')

            space_r = _wsub(para, 'r')
            space_t = _wsub(space_r, 't')
            space_t.text = ' '  # non-breaking space after marker

            for item in fn_items:
                if isinstance(item, str):
                    if item.strip():
                        r = _wsub(para, 'r')
                        t = _wsub(r, 't')
                        t.text = item
                        if item[0] == ' ' or item[-1] == ' ':
                            t.set(XML_SPACE, 'preserve')
                elif isinstance(item, etree._Element):
                    local = etree.QName(item).localname
                    if local == 'p':
                        fn_el.append(item)
                    else:
                        para.append(item)

        result = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
        return result if isinstance(result, bytes) else result.encode('utf-8')

    def _replace_image_sentinels(self, body_elements: list, doc, nsmap: dict, config: dict) -> None:
        """Replace image sentinels with actual OOXML drawing elements using XQuery-compatible approach."""
        # Image numbering continues self._image_counter, which is per run.
        
        # Collect all image sentinels first
        image_sentinels = []
        
        for el in body_elements:
            self._collect_image_sentinels(el, image_sentinels)
        
        # Build image package like XQuery pmf:build-image-package
        if image_sentinels:
            self._build_image_package(config, image_sentinels, doc)
        
        # Replace sentinels with drawing elements
        for el in body_elements:
            self._replace_image_sentinels_in_element(el, config)
    
    def _collect_image_sentinels(self, el: etree._Element, sentinels: list) -> None:
        """Collect all image sentinels in the document."""
        if el.tag == IMAGE_SENTINEL_TAG:
            sentinels.append(el)
        
        for child in el:
            self._collect_image_sentinels(child, sentinels)
    
    def _build_image_package(self, config: dict, sentinels: list, doc) -> None:
        """Build image package like XQuery pmf:build-image-package."""
        import os  # noqa: PLC0415
        
        # The rId → actual relationship mapping lands in self._image_rid_map.
        
        for i, sentinel in enumerate(sentinels):
            self._image_counter += 1
            r_id_num = 10 + self._image_counter  # Start from rId10 like XQuery
            r_id = f'rId{r_id_num}'
            
            # Store the rId on the sentinel for later use
            sentinel.set('rId', r_id)
            
            # Get image URL
            image_url = sentinel.get('url')
            if not image_url:
                continue
            
            # Resolve image path
            input_path = config.input_path
            if not input_path:
                continue
            
            input_dir = os.path.dirname(os.path.abspath(input_path))
            image_path = os.path.join(input_dir, image_url)
            
            if not os.path.exists(image_path):
                continue
            
            # Determine MIME type and extension
            _, ext = os.path.splitext(image_path.lower())
            mime_type = self._IMAGE_MIME_TYPES.get(ext)
            if not mime_type:
                ext = '.png'
                mime_type = 'image/png'
            
            # Read image data
            try:
                with open(image_path, 'rb') as f:
                    image_data = f.read()
            except Exception:
                continue
            
            # Create image part
            image_filename = f'media/image{r_id_num}{ext}'
            
            try:
                from docx.opc.packuri import PackURI  # noqa: PLC0415
                from docx.opc.part import Part  # noqa: PLC0415
                
                image_part = Part(
                    PackURI(f'/word/{image_filename}'),
                    mime_type,
                    image_data,
                    doc.part.package
                )
                
                # Create relationship and store the actual rId
                actual_rid = doc.part.relate_to(image_part, IMAGE_RT)
                self._image_rid_map[r_id] = actual_rid
                
            except Exception:
                continue
    
    def _replace_image_sentinels_in_element(self, el: etree._Element, config: dict) -> None:
        """Replace image sentinels with drawing elements in an element."""
        to_replace = [
            (i, child) for i, child in enumerate(el)
            if child.tag == IMAGE_SENTINEL_TAG
        ]
        
        for orig_idx, sentinel in reversed(to_replace):  # Reverse to maintain indices
            # A sentinel must never survive into the body — Word refuses to open a
            # document containing elements outside the OOXML namespaces.  Any
            # failure below (unregistered rId, missing/unreadable image file,
            # drawing construction) degrades to a visible placeholder run.
            r_id = sentinel.get('rId')
            actual_rid = self._image_rid_map.get(r_id) if r_id else None
            
            drawing_run = None
            if actual_rid:
                drawing_run = self._create_image_drawing_element(
                    actual_rid,
                    sentinel.get('width'),
                    sentinel.get('height'),
                    sentinel.get('scale'),
                )
            
            replacement = drawing_run
            if replacement is None:
                replacement = self._make_run(f'[Image: {sentinel.get("url", "")}]')
            el.remove(sentinel)  # type: ignore
            el.insert(orig_idx, replacement)
        
        # Recursively process child elements
        for child in el:
            if isinstance(child, etree._Element):
                self._replace_image_sentinels_in_element(child, config)

    def _create_image_drawing_element(self, actual_rid: str, width: str | None, height: str | None, 
                                     scale: str | None) -> etree._Element | None:
        """Create a drawing element using the actual relationship ID."""
        # Namespace constants for drawing elements
        A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
        WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
        PIC = 'http://schemas.openxmlformats.org/drawingml/2006/picture'
        
        # Calculate dimensions in EMU (like XQuery)
        if width and height:
            cx = str(int(float(width) * 9525))
            cy = str(int(float(height) * 9525))
        elif scale:
            cx = str(int(3600000 * float(scale) / 100))  # 4 inches default
            cy = str(int(2743200 * float(scale) / 100))  # 3 inches default
        else:
            cx = '3600000'  # 4 inches in EMU
            cy = '2743200'  # 3 inches in EMU
        
        # Create XQuery-compatible w:r element with proper namespace map
        nsmap = {
            'w': W,
            'wp': WP,
            'a': A,
            'pic': PIC,
            'r': R_NS
        }
        
        run = etree.Element(f'{{{W}}}r', nsmap=nsmap)
        
        # Create drawing element
        drawing = etree.SubElement(run, f'{{{W}}}drawing')
        
        # Create inline drawing
        inline = etree.SubElement(drawing, f'{{{WP}}}inline')
        inline.set('distT', '0')
        inline.set('distB', '0')
        inline.set('distL', '0')
        inline.set('distR', '0')
        
        # Extent
        extent = etree.SubElement(inline, f'{{{WP}}}extent')
        extent.set('cx', cx)
        extent.set('cy', cy)
        
        # DocPr
        doc_pr = etree.SubElement(inline, f'{{{WP}}}docPr')
        doc_pr.set('id', '1')  # Use simple ID
        doc_pr.set('name', 'Image')
        doc_pr.set('descr', 'Image')
        
        # cNvGraphicFramePr
        cnv_frame_pr = etree.SubElement(inline, f'{{{WP}}}cNvGraphicFramePr')
        frame_locks = etree.SubElement(cnv_frame_pr, f'{{{A}}}graphicFrameLocks')
        frame_locks.set('noChangeAspect', '1')
        
        # Graphic
        graphic = etree.SubElement(inline, f'{{{A}}}graphic')
        graphic_data = etree.SubElement(graphic, f'{{{A}}}graphicData')
        graphic_data.set('uri', 'http://schemas.openxmlformats.org/drawingml/2006/picture')
        
        # Picture
        pic = etree.SubElement(graphic_data, f'{{{PIC}}}pic')
        
        # Non-visual picture properties
        nv_pic_pr = etree.SubElement(pic, f'{{{PIC}}}nvPicPr')
        c_nv_pr = etree.SubElement(nv_pic_pr, f'{{{PIC}}}cNvPr')
        c_nv_pr.set('id', '0')  # Use simple ID
        c_nv_pr.set('name', '')
        c_nv_pic_pr = etree.SubElement(nv_pic_pr, f'{{{PIC}}}cNvPicPr')
        
        # Blip fill
        blip_fill = etree.SubElement(pic, f'{{{PIC}}}blipFill')
        blip = etree.SubElement(blip_fill, f'{{{A}}}blip')
        blip.set(f'{{{R_NS}}}embed', actual_rid)  # Use actual relationship ID
        
        # Stretch
        stretch = etree.SubElement(blip_fill, f'{{{A}}}stretch')
        fill_rect = etree.SubElement(stretch, f'{{{A}}}fillRect')
        
        # Shape properties
        sp_pr = etree.SubElement(pic, f'{{{PIC}}}spPr')
        xfrm = etree.SubElement(sp_pr, f'{{{A}}}xfrm')
        
        # Offset
        off = etree.SubElement(xfrm, f'{{{A}}}off')
        off.set('x', '0')
        off.set('y', '0')
        
        # Extent
        ext = etree.SubElement(xfrm, f'{{{A}}}ext')
        ext.set('cx', cx)
        ext.set('cy', cy)
        
        # Geometry
        prst_geom = etree.SubElement(sp_pr, f'{{{A}}}prstGeom')
        prst_geom.set('prst', 'rect')
        av_lst = etree.SubElement(prst_geom, f'{{{A}}}avLst')
        
        return run

    def _create_drawing_element(self, r_id: str, width: str | None, height: str | None, 
                               scale: str | None, nsmap: dict) -> etree._Element:
        """Create the w:drawing element with proper sizing."""
        # Namespace constants for drawing
        A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
        WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
        PIC = 'http://schemas.openxmlformats.org/drawingml/2006/picture'
        
        # Use the exact structure that python-docx uses for images
        from docx.shared import Emu  # noqa: PLC0415
        
        # Create drawing element with minimal namespaces
        drawing = etree.Element(f'{{{W}}}drawing')
        
        # Create inline drawing
        inline = etree.SubElement(drawing, f'{{{WP}}}inline')
        inline.set(f'{{{WP}}}distT', '0')
        inline.set(f'{{{WP}}}distB', '0')
        inline.set(f'{{{WP}}}distL', '0')
        inline.set(f'{{{WP}}}distR', '0')
        
        # Calculate dimensions
        if width and height:
            cx = str(int(float(width) * 9525))  # Convert to EMU
            cy = str(int(float(height) * 9525))
        elif scale:
            cx = str(int(2000000 * float(scale) / 100))  # 200px default
            cy = str(int(1500000 * float(scale) / 100))  # 150px default
        else:
            cx = '2000000'  # 200px in EMU
            cy = '1500000'  # 150px in EMU
        
        # Extent
        extent = etree.SubElement(inline, f'{{{WP}}}extent')
        extent.set(f'{{{A}}}cx', cx)
        extent.set(f'{{{A}}}cy', cy)
        
        # Effect extent
        effect_extent = etree.SubElement(inline, f'{{{WP}}}effectExtent')
        effect_extent.set(f'{{{A}}}l', '0')
        effect_extent.set(f'{{{A}}}t', '0')
        effect_extent.set(f'{{{A}}}r', '0')
        effect_extent.set(f'{{{A}}}b', '0')
        
        # DocPr
        doc_pr = etree.SubElement(inline, f'{{{WP}}}docPr')
        doc_pr.set(f'{{{A}}}id', '1')
        doc_pr.set(f'{{{A}}}name', 'Picture')
        doc_pr.set(f'{{{A}}}descr', '')
        
        # Graphic
        graphic = etree.SubElement(inline, f'{{{A}}}graphic')
        graphic_data = etree.SubElement(graphic, f'{{{A}}}graphicData')
        graphic_data.set(f'{{{A}}}uri', PIC)
        
        # Picture
        pic = etree.SubElement(graphic_data, f'{{{PIC}}}pic')
        
        # Non-visual properties
        nv_pic_pr = etree.SubElement(pic, f'{{{PIC}}}nvPicPr')
        c_nv_pr = etree.SubElement(nv_pic_pr, f'{{{PIC}}}cNvPr')
        c_nv_pr.set(f'{{{A}}}id', '0')
        c_nv_pr.set(f'{{{A}}}name', 'Picture')
        c_nv_pic_pr = etree.SubElement(nv_pic_pr, f'{{{PIC}}}cNvPicPr')
        
        # Blip (image data)
        blip_fill = etree.SubElement(pic, f'{{{PIC}}}blipFill')
        blip = etree.SubElement(blip_fill, f'{{{A}}}blip')
        blip.set(f'{{{R_NS}}}embed', r_id)
        
        # Stretch
        stretch = etree.SubElement(blip_fill, f'{{{A}}}stretch')
        fill_rect = etree.SubElement(stretch, f'{{{A}}}fillRect')
        
        # Shape properties
        sp_pr = etree.SubElement(pic, f'{{{PIC}}}spPr')
        xfrm = etree.SubElement(sp_pr, f'{{{A}}}xfrm')
        
        # Offset
        off = etree.SubElement(xfrm, f'{{{A}}}off')
        off.set(f'{{{A}}}x', '0')
        off.set(f'{{{A}}}y', '0')
        
        # Extent
        ext = etree.SubElement(xfrm, f'{{{A}}}ext')
        ext.set(f'{{{A}}}cx', cx)
        ext.set(f'{{{A}}}cy', cy)
        
        # Geometry
        prst_geom = etree.SubElement(sp_pr, f'{{{A}}}prstGeom')
        prst_geom.set(f'{{{A}}}prst', 'rect')
        
        return drawing
