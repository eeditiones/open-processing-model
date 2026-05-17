"""DOCX serialisation for the TEI processing model (docx-functions.xql equivalent).

Uses python-docx for OPC packaging and raw lxml OOXML elements for content.
Content is accumulated as a flat list (like Markdown mode), then assembled
into a .docx binary in finish().
"""

from __future__ import annotations

import re
from io import BytesIO

from lxml import etree

from teipublisher.runtime.output_functions import (
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

FOOTNOTES_RT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes'
FOOTNOTES_CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml'
HYPERLINK_RT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def docx_apply_children(config, source_node, content, parent_el) -> None:
    """apply_children variant for DOCX: keeps lxml elements as elements in list parents.

    The standard pm_runtime.apply_children serializes elements to HTML strings when
    the parent accumulator is a list (Markdown mode).  DOCX needs actual lxml OOXML
    elements in the list so they can be assembled into a document later.
    """
    from teipublisher.runtime.pm_runtime import apply as _pm_apply, append_to  # noqa: PLC0415

    norm = config.get('normalize_text')
    for item in normalize(content):
        if isinstance(item, str):
            s = norm(item) if norm else item
            if isinstance(parent_el, list):
                parent_el.append(s)
            else:
                append_to(parent_el, s)
        elif isinstance(item, etree._Element):
            dispatch = config['dispatch']
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


def _wsub(parent: etree._Element, tag: str) -> etree._Element:
    return etree.SubElement(parent, f'{{{W}}}{tag}')


def _wset(el: etree._Element, attr: str, val: str) -> None:
    el.set(f'{{{W}}}{attr}', val)


# ── CSS parsing (shared with Markdown approach) ────────────────────────────────

def _parse_css_classes(css_text: str) -> dict:
    """Parse CSS and return ``{class_name: {property: value}}`` for simple class selectors."""
    css_text = re.sub(r'/\*.*?\*/', '', css_text, flags=re.DOTALL)
    result: dict = {}
    for block in re.finditer(r'([^{}]+)\{([^{}]*)\}', css_text):
        props: dict = {}
        for pm in re.finditer(r'([\w-]+)\s*:\s*([^;]+)', block.group(2)):
            props[pm.group(1).strip().lower()] = pm.group(2).strip().lower()
        if not props:
            continue
        for sel in block.group(1).strip().split(','):
            m = re.match(r'^\.([a-zA-Z0-9_-]+)$', sel.strip())
            if m:
                result.setdefault(m.group(1), {}).update(props)
    return result


def _get_css_map(config: dict) -> dict:
    if '_css_map' not in config:
        config['_css_map'] = _parse_css_classes(config.get('odd_css', ''))
    return config['_css_map']


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

    # ── Style index ────────────────────────────────────────────────────────────

    def _ensure_styles(self, config: dict) -> None:
        if self._styles_loaded:
            return
        from docx import Document  # noqa: PLC0415
        template = config.get('docx_template')
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
            id_key = sid.lower()
            if style.type == WD_STYLE_TYPE.PARAGRAPH:
                target = self._para_styles
            elif style.type == WD_STYLE_TYPE.CHARACTER:
                target = self._char_styles
            elif style.type == WD_STYLE_TYPE.TABLE:
                target = self._table_styles
            else:
                continue
            target[name_key] = sid
            if id_key != name_key:
                target[id_key] = sid
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
        config['apply_children'](config, node, content, items)
        return items

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
            elif isinstance(item, etree._Element):
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
        if preserve:
            saved_norm = config.pop('normalize_text', None)
        items = self._collect(config, node, content)
        if preserve:
            if saved_norm is not None:
                config['normalize_text'] = saved_norm
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
        lvl = max(1, min(9, int(level) if level else 1))
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
        prev_type = config.get('_docx_list_type')
        prev_depth = config.get('_docx_list_depth', -1)
        prev_numid = config.get('_docx_list_num_id')
        effective_type = type or 'unordered'
        config['_docx_list_type'] = effective_type
        config['_docx_list_depth'] = prev_depth + 1
        # Allocate a fresh numId when:
        # - this is a top-level list (prev_depth < 0), OR
        # - this is a nested list of a DIFFERENT type than the parent
        #   (e.g. ordered inside bullet needs its own decimal counter).
        # Same-type nested lists reuse the parent numId so the ilvl drives indentation.
        is_ordered = effective_type == 'ordered'
        parent_type = prev_type or 'unordered'
        type_changed = effective_type != parent_type
        if prev_depth < 0 or type_changed:
            instances: list = config.setdefault('_docx_num_instances', [])
            new_numid = 100 + len(instances)
            instances.append((new_numid, 'ordered' if is_ordered else 'bullet'))
            config['_docx_list_num_id'] = new_numid
        items = self._collect(config, node, content)
        config['_docx_list_type'] = prev_type
        config['_docx_list_depth'] = prev_depth
        config['_docx_list_num_id'] = prev_numid
        return items

    def list_item(self, config, node, cls, content, n=None) -> PMResult:
        self._ensure_styles(config)
        items = self._collect(config, node, content)
        list_type = config.get('_docx_list_type', 'unordered')
        depth = config.get('_docx_list_depth', 0)
        numid = config.get('_docx_list_num_id') or (
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
        return self._collect(config, node, content)

    def graphic(self, config, node, cls, content, url=None,
                width=None, height=None, scale=None, title=None) -> PMResult:
        self._ensure_styles(config)
        # Images deferred — emit a placeholder run
        return [self._make_run(f'[Image: {url or ""}]')]

    def note(self, config, node, cls, content, place=None, label=None) -> PMResult:
        self._ensure_styles(config)
        if '_docx_footnotes' not in config:
            config['_docx_footnotes'] = {}
        fn_id = len(config['_docx_footnotes']) + 1
        config['_docx_footnotes'][fn_id] = self._collect(config, node, content)
        sentinel = etree.Element(FOOTNOTE_SENTINEL_TAG)
        sentinel.set('id', str(fn_id))
        return [sentinel]

    def cit(self, config, node, cls, content, source=None) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

    def webcomponent(self, config, node, cls, content, name=None, optional=None) -> PMResult:
        self._ensure_styles(config)
        return self._collect(config, node, content)

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

    def metadata(self, config, node, cls, content) -> PMResult:
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
        """Inject built-in character styles (Hyperlink, …) absent from the template.

        Mirrors the XQuery pmf:ensure-builtin-styles logic so templates that
        don't ship these styles still produce correctly formatted output.
        """
        WP = f'{{{W}}}'
        styles_el = doc.part.styles._element
        existing_ids = {el.get(f'{WP}styleId') for el in styles_el.findall(f'{WP}style')}

        if 'Hyperlink' in existing_ids:
            return

        default_char = 'DefaultParagraphFont'
        for style_el in styles_el.findall(f'{WP}style'):
            if (style_el.get(f'{WP}type') == 'character'
                    and style_el.get(f'{WP}default') == '1'):
                sid = style_el.get(f'{WP}styleId')
                if sid:
                    default_char = sid
                    break

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

    def finish(self, config: dict, nodes: list) -> list:
        """Assemble body elements into a ``.docx`` and return ``[bytes]``."""
        from docx import Document  # noqa: PLC0415
        from docx.opc.part import Part  # noqa: PLC0415
        from docx.opc.packuri import PackURI  # noqa: PLC0415

        template_path = config.get('docx_template')
        doc = Document(template_path) if template_path else Document()
        if not self._styles_loaded:
            self._load_style_index(doc)
        self._inject_missing_builtin_styles(doc)

        if self._needs_numbering:
            import docx as _docx_pkg  # noqa: PLC0415
            import os  # noqa: PLC0415
            _default_path = os.path.join(os.path.dirname(_docx_pkg.__file__), 'templates', 'default.docx')
            _default_doc = Document(_default_path)
            _np = _default_doc.part.numbering_part
            from docx.opc.constants import RELATIONSHIP_TYPE as _RT  # noqa: PLC0415
            _new_np = type(_np)(_np.partname, _np.content_type, _np._element, doc.part.package)
            doc.part.relate_to(_new_np, _RT.NUMBERING)

        # Add per-list w:num instances so each list gets its own counter
        instances = config.get('_docx_num_instances', [])
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

        body_elements = [item for item in nodes if isinstance(item, etree._Element)]
        self._replace_footnote_sentinels(body_elements)
        self._replace_hyperlink_sentinels(body_elements, doc)

        for el in body_elements:
            if sectPr is not None:
                sectPr.addprevious(el)
            else:
                body.append(el)

        footnotes_data = config.get('_docx_footnotes', {})
        if footnotes_data:
            xml_bytes = self._build_footnotes_xml(footnotes_data)
            footnotes_part = Part(
                PackURI('/word/footnotes.xml'),
                FOOTNOTES_CT,
                xml_bytes,
                doc.part.package,
            )
            doc.part.relate_to(footnotes_part, FOOTNOTES_RT)

        buf = BytesIO()
        doc.save(buf)
        return [buf.getvalue()]

    def _replace_footnote_sentinels(self, elements: list) -> None:
        for el in elements:
            self._replace_sentinels_in(el)

    def _replace_sentinels_in(self, el: etree._Element) -> None:
        to_replace = [(i, child) for i, child in enumerate(el) if child.tag == FOOTNOTE_SENTINEL_TAG]
        offset = 0
        for orig_idx, sentinel in to_replace:
            fn_id = int(sentinel.get('id', '0'))
            ref_run = _w('r')
            rPr = _wsub(ref_run, 'rPr')
            rStyle = _wsub(rPr, 'rStyle')
            _wset(rStyle, 'val', 'FootnoteReference')
            fn_ref = _wsub(ref_run, 'footnoteReference')
            _wset(fn_ref, 'id', str(fn_id))
            el.remove(sentinel)
            el.insert(orig_idx + offset, ref_run)
            offset += 1 - 1  # remove + insert → net 0
        for child in el:
            self._replace_sentinels_in(child)

    def _replace_hyperlink_sentinels(self, body_elements: list, doc) -> None:
        for el in body_elements:
            self._replace_hyperlinks_in(el, doc)

    def _replace_hyperlinks_in(self, el: etree._Element, doc) -> None:
        to_replace = [
            (i, child) for i, child in enumerate(el)
            if child.tag == HYPERLINK_SENTINEL_TAG
        ]
        offset = 0
        for orig_idx, sentinel in to_replace:
            href = sentinel.get('href', '')
            r_id = doc.part.relate_to(href, HYPERLINK_RT, is_external=True)
            hl = _w('hyperlink')
            hl.set(f'{{{R_NS}}}id', r_id)
            for child in list(sentinel):
                hl.append(child)
            el.remove(sentinel)
            el.insert(orig_idx + offset, hl)
        for child in el:
            self._replace_hyperlinks_in(child, doc)

    def _build_footnotes_xml(self, footnotes_data: dict) -> bytes:
        nsmap = {'w': W}
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
            _wset(pStyle, 'val', self._para_styles.get('footnote text', 'FootnoteText'))

            marker_r = _wsub(para, 'r')
            marker_rPr = _wsub(marker_r, 'rPr')
            marker_rStyle = _wsub(marker_rPr, 'rStyle')
            _wset(marker_rStyle, 'val',
                  self._char_styles.get('footnote reference', 'FootnoteReference'))
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

        return etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
