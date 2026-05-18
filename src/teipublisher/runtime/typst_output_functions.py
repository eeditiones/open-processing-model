"""Typst serialisation for the TEI processing model."""

from __future__ import annotations

import html
import re

from lxml import etree

from teipublisher.runtime.markdown_output_functions import (
    _get_css_map,
    _join_buf,
    apply_markdown_finish_regexes,
    normalize_markdown_xml_text,
)
from teipublisher.runtime.output_functions import (
    PMResult,
    TemplateOutput,
    XLINK_HREF,
    XML_ID,
    ProcessingModelFunctions,
    apply_children_without_normalization,
    apply_pb_template,
    literal_code_body,
    child_nodes,
    maybe_normalize_text,
    normalize,
    should_preserve_whitespace,
)

TYPST_INDENT = '  '

_HTML_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_FENCED_CODE_RE = re.compile(r'```[^\n]*\n.*?```', re.DOTALL)


def typst_ident_from_class(class_name: str) -> str:
    """Map a CSS class name (e.g. ``tei-pb2``) to a valid Typst identifier."""
    return class_name.replace('-', '_').replace(':', '_')

# CSS properties → Typst wrappers (outermost first)
_CSS_TO_TYPST_WRAPPERS = [
    ('font-weight', 'bold', 'strong'),
    ('font-style', 'italic', 'emph'),
    ('font-style', 'oblique', 'emph'),
    ('text-decoration', 'line-through', 'strike'),
]


def _css_typst_wrap(config: dict, cls: list, inner: str) -> str:
    """Wrap *inner* with Typst functions derived from CSS classes (simple_* / tei-*)."""
    css_map = _get_css_map(config)
    class_names: set[str] = set()
    for item in cls:
        if item:
            for name in str(item).split():
                class_names.add(name)
    combined: dict = {}
    for name in class_names:
        if name in css_map:
            combined.update(css_map[name])
    if not combined:
        return inner
    result = inner
    for prop, val_fragment, fn in _CSS_TO_TYPST_WRAPPERS:
        css_val = combined.get(prop, '')
        if val_fragment in css_val:
            # Bracket form avoids ``strong(NB:)`` being parsed as a named argument.
            result = f'{fn}[{result}]'
    return result


def css_length_to_typst(val: str | int | float | None) -> str | None:
    """Map a CSS length (e.g. ``512px``) to a Typst length literal."""
    if val is None:
        return None
    s = str(val).strip().strip('"').strip("'")
    if not s:
        return None
    m = re.match(r'^([\d.]+)\s*(px|pt|mm|cm|in|em|rem|%)?$', s, re.IGNORECASE)
    if not m:
        return s
    num_s, unit = m.group(1), (m.group(2) or '').lower()
    if unit == 'px':
        pt = float(num_s) * 0.75
        return f'{int(pt)}pt' if pt == int(pt) else f'{pt}pt'
    if unit == 'in':
        return f'{num_s}in'
    if unit:
        return f'{num_s}{unit}'
    return num_s


def escape_typst_underscores(text: str) -> str:
    """Escape lone ``_`` characters except paired ``_emphasis_`` spans from ``@rend``.

    Preserves ``#tei_*`` / ``@tei-fn-*`` references and does not treat long spans
    crossing ``[``/``]`` as emphasis.
    """
    protected: list[str] = []

    def protect(m: re.Match) -> str:
        protected.append(m.group(0))
        return f'\x00{len(protected) - 1}\x00'

    t = text
    t = re.sub(r'#[A-Za-z][A-Za-z0-9_]*', protect, t)
    t = re.sub(r'@tei-fn-[A-Za-z0-9_-]+', protect, t)
    emphasis = re.compile(r'(?<![\w\\])_([^_\n\[\]#:]+?)_(?![\w])')
    t = emphasis.sub(protect, t)
    t = t.replace('_', '\\_')
    for i, orig in enumerate(protected):
        t = t.replace(f'\x00{i}\x00', orig)
    return t


def escape_typst_at_signs(text: str) -> str:
    """Escape ``@`` so prose like ``@mode`` is not parsed as a label reference.

    Preserves footnote references ``@tei-fn-*`` emitted by :meth:`TypstOutputFunctions.note`.
    """
    protected: list[str] = []

    def protect(m: re.Match) -> str:
        protected.append(m.group(0))
        return f'\x00{len(protected) - 1}\x00'

    t = re.sub(r'@tei-fn-[A-Za-z0-9_-]+', protect, text)
    t = t.replace('@', '\\@')
    for i, orig in enumerate(protected):
        t = t.replace(f'\x00{i}\x00', orig)
    return t


def _get_typst_functions(config: dict) -> frozenset[str]:
    """Return Typst function names compiled from the ODD (``TYPST_RENDITION_FUNCTIONS``)."""
    if '_typst_functions' not in config:
        raw = config.get('typst_functions')
        config['_typst_functions'] = frozenset(raw) if raw is not None else frozenset()
    return config['_typst_functions']


def _typst_wrap_class_names(cls: list, defined: frozenset[str]) -> list[str]:
    """Return class names to wrap as ``#ident[content]``, innermost first.

    - ``tei-*`` / ``simple_*`` with an ODD-generated ``#let`` (in *defined*)
    - any other dispatch class (from ``@cssClass``); the project Typst template
      must define matching ``#let`` functions
    """
    tei_and_simple: list[str] = []
    custom: list[str] = []
    seen: set[str] = set()
    for item in cls:
        if not item:
            continue
        for name in str(item).split():
            if not name or name == 'r' or name in seen:
                continue
            seen.add(name)
            if name.startswith(('tei-', 'simple_')):
                if typst_ident_from_class(name) in defined:
                    tei_and_simple.append(name)
            else:
                custom.append(name)
    tei_names = [n for n in tei_and_simple if n.startswith('tei-')]
    other = [n for n in tei_and_simple if not n.startswith('tei-')]
    tei_names.sort(key=lambda n: (len(n), n))
    return tei_names + other + custom


def _css_classes_without_typst_wrap(config: dict, cls: list) -> list:
    """Return *cls* with names removed that are emitted as ``#let`` function calls."""
    skip = set(_typst_wrap_class_names(cls, _get_typst_functions(config)))
    filtered: list = []
    for item in cls:
        if not item:
            continue
        kept = [n for n in str(item).split() if n and n != 'r' and n not in skip]
        if kept:
            filtered.append(' '.join(kept))
    return filtered


def _wrap_typst_classes(config: dict, cls: list, inner: str) -> str:
    """Wrap *inner* in Typst functions for ODD renditions and ``@cssClass`` names."""
    defined = _get_typst_functions(config)
    for name in _typst_wrap_class_names(cls, defined):
        fn = typst_ident_from_class(name)
        inner = f'#{fn}[{inner}]'
    return inner


def _element_text_content(el: etree._Element) -> str:
    """Extract plain text from an HTML/XML fragment (e.g. from ``pb:template``)."""
    parts: list[str] = [el.text or '']
    for child in el:
        if isinstance(child.tag, str):
            parts.append(_element_text_content(child))
        parts.append(child.tail or '')
    return ''.join(parts)


def _flatten_nodes_to_text(nodes: list) -> str:
    """Join transform fragments as plain text, never serializing markup to HTML."""
    parts: list[str] = []
    for item in nodes:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, etree._Element):
            parts.append(_element_text_content(item))
    return ''.join(parts)


def strip_html_markup(text: str) -> str:
    """Remove HTML/XML tags leaked from web-oriented ODD ``pb:template`` rules."""
    if not text:
        return text
    text = _HTML_COMMENT_RE.sub('', text)
    text = _HTML_TAG_RE.sub('', text)
    text = html.unescape(text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    return text


def _typst_code_mode_body(s: str) -> str:
    """Normalize markup emitted inside another function's ``(...)`` argument list.

    Typst is in code mode there, so nested show rules must drop the leading ``#``.
    """
    s = re.sub(r'#image\(', 'image(', s)
    s = re.sub(r'#link\(', 'link(', s)
    return s


def _protect_fenced_code_blocks(text: str) -> tuple[str, list[str]]:
    """Temporarily replace fenced code blocks so finish cleanup cannot strip literal XML."""
    protected: list[str] = []

    def replace(m: re.Match) -> str:
        protected.append(m.group(0))
        return f'\x00F{len(protected) - 1}\x00'

    return _FENCED_CODE_RE.sub(replace, text), protected


def _restore_fenced_code_blocks(text: str, protected: list[str]) -> str:
    for i, orig in enumerate(protected):
        text = text.replace(f'\x00F{i}\x00', orig)
    return text


def apply_typst_finish_cleanup(text: str) -> str:
    """Post-process Typst body text after the transform tree is flattened."""
    text, fenced = _protect_fenced_code_blocks(text)
    text = strip_html_markup(text)
    text = escape_typst_underscores(text)
    text = escape_typst_at_signs(text)
    text = apply_markdown_finish_regexes(text)
    return _restore_fenced_code_blocks(text, fenced)


def _serialize_typst_pm_result(nodes: list) -> str:
    """Concatenate transform output without HTML serialization of elements."""
    return _flatten_nodes_to_text(nodes)


def _apply_inline_styling(config, node, cls: list, text: str) -> str:
    rend = (node.get('rend') or '').split()
    if 'bold' in rend:
        text = f'*{text}*'
    elif 'italic' in rend or 'italics' in rend:
        text = f'_{text}_'
    else:
        css_cls = _css_classes_without_typst_wrap(config, cls)
        wrapped = _css_typst_wrap(config, css_cls, 'body')
        if wrapped != 'body':
            text = wrapped.replace('body', text, 1)
    return _wrap_typst_classes(config, cls, text)


class TypstOutputFunctions(ProcessingModelFunctions):
    """Serialise to Typst markup text fragments."""

    def finish(self, config, nodes: list) -> list:
        text = apply_typst_finish_cleanup(_serialize_typst_pm_result(nodes))
        return [text]

    def block(self, config, node, cls, content) -> PMResult:
        out: list = []
        ind = config.get('indent', '')
        if ind:
            out.append(ind)
        if should_preserve_whitespace(cls):
            apply_children_without_normalization(config, node, content, out)
        else:
            config['apply_children'](config, node, content, out)
        out.append('\n\n')
        return out

    def inline(self, config, node, cls, content) -> PMResult:
        out: list = []
        config['apply_children'](config, node, content, out)
        text = _join_buf(out)
        return [_apply_inline_styling(config, node, cls, text)]

    def paragraph(self, config, node, cls, content) -> PMResult:
        out: list = []
        if node.getprevious() is not None:
            out.append('\n')
        ind = config.get('indent', '')
        if ind:
            out.append(ind)
        config['apply_children'](config, node, content, out)
        out.append('\n\n')
        return out

    def heading(self, config, node, cls, content, level) -> PMResult:
        try:
            lvl = int(level) if level is not None else 1
        except (TypeError, ValueError):
            lvl = 1
        lvl = max(1, min(6, lvl))
        hashes = '=' * lvl
        out: list = ['\n', config.get('indent', ''), hashes, ' ']
        config['apply_children'](config, node, content, out)
        out.append('\n\n')
        return out

    def section(self, config, node, cls, content) -> PMResult:
        return self.block(config, node, cls, content)

    def body(self, config, node, cls, content) -> PMResult:
        out: list = []
        config['apply_children'](config, node, content, out)
        return out

    def document(self, config, node, cls, content) -> PMResult:
        out: list = []
        config['apply_children'](config, node, content, out)
        return out

    def pass_through(self, config, node, cls, content) -> PMResult:
        norm = config.get('normalize_text')
        result: list = []
        for item in normalize(content):
            if isinstance(item, str):
                result.append(maybe_normalize_text(item, norm))
            elif isinstance(item, etree._Element):
                sub = (
                    config['apply'](config, child_nodes(node))
                    if item is node
                    else config['apply'](config, [item])
                )
                result.extend(sub)
        return result

    def list(self, config, node, cls, content, type=None) -> PMResult:
        effective = type or node.get('type')
        sub = {**config}
        sub['listType'] = 'ordered' if effective == 'ordered' else 'unordered'
        out: list = []
        config['apply_children'](sub, node, content, out)
        out.append('\n')
        return out

    def list_item(self, config, node, cls, content, n=None) -> PMResult:
        _ = n
        out: list = []
        ind = config.get('indent', '')
        list_type = config.get('listType', 'unordered')
        pos = len(list(node.itersiblings(preceding=True))) + 1
        marker = f'{pos}. ' if list_type == 'ordered' else '- '
        out.append('\n')
        out.append(ind)
        out.append(marker)
        deeper = {**config, 'indent': ind + TYPST_INDENT}
        config['apply_children'](deeper, node, content, out)
        out.append('\n')
        return out

    def link(self, config, node, cls, content, uri, target, optional) -> PMResult:
        _ = target, optional
        if isinstance(uri, etree._Element):
            href = uri.get(XLINK_HREF)
        else:
            href = uri
        href_s = str(href) if href else ''
        out: list = [f'#link("{href_s}")[']
        config['apply_children'](config, node, content, out)
        out.append(']')
        return out

    def table(self, config, node, cls, content) -> PMResult:
        rows_buf: list = []
        sub = {**config, '_typst_table_rows': rows_buf}
        config['apply_children'](sub, node, content, rows_buf)
        if not rows_buf:
            return ['\n']
        row_strs = [_join_buf(r) if isinstance(r, list) else str(r) for r in rows_buf]
        cols = max(len(r.split('|')) for r in row_strs if r.strip()) if row_strs else 1
        col_spec = ','.join(['auto'] * cols)
        lines = ['\n#table(\n  columns: (' + col_spec + '),\n']
        for i, row in enumerate(row_strs):
            cells = [c.strip() for c in row.split('|') if c.strip() or row.count('|') > 0]
            if not cells and row:
                cells = [row.strip()]
            cell_exprs = ', '.join(f'[{c}]' for c in cells) if cells else '[]'
            lines.append(f'  {cell_exprs},\n')
        lines.append(')\n\n')
        return [''.join(lines)]

    def row(self, config, node, cls, content) -> PMResult:
        out: list = []
        config['apply_children'](config, node, content, out)
        row_text = _join_buf(out).strip()
        rows = config.get('_typst_table_rows')
        if rows is not None:
            rows.append(row_text)
            return []
        return [row_text + '\n']

    def cell(self, config, node, cls, content, type=None) -> PMResult:
        _ = type
        out: list = []
        config['apply_children'](config, node, content, out)
        return [_join_buf(out) + ' |']

    def figure(self, config, node, cls, content, title=None) -> PMResult:
        body: list = []
        config['apply_children'](config, node, content, body)
        body_text = _typst_code_mode_body(_join_buf(body).strip())
        parts = [f'\n#figure(\n  {body_text}']
        if title:
            tbuf: list = []
            config['apply_children'](config, node, title, tbuf)
            caption = _join_buf(tbuf).strip()
            parts.append(f',\n  caption: [{caption}]')
        parts.append('\n)\n\n')
        return [''.join(parts)]

    def graphic(self, config, node, cls, content, url,
                width, height, scale, title) -> PMResult:
        _ = content, scale, title
        if isinstance(url, etree._Element):
            href = url.get(XLINK_HREF) or ''
        else:
            href = str(url) if url else ''
        opts: list[str] = []
        w = css_length_to_typst(width)
        if w:
            opts.append(f'width: {w}')
        h = css_length_to_typst(height)
        if h:
            opts.append(f'height: {h}')
        opt_s = ', '.join(opts)
        if opt_s:
            return [f'#image("{href}", {opt_s})']
        return [f'#image("{href}")']

    def note(self, config, node, cls, content, place=None, label=None) -> PMResult:
        _ = place, label
        from . import output_functions as of

        of._note_counter += 1
        nr = of._note_counter
        node_id = node.get(XML_ID) or node.get('id') or str(nr)
        safe_id = re.sub(r'[-.]', '_', node_id)
        fn_label = f'tei-fn-{safe_id}'
        buf: list = []
        config['apply_children'](config, node, content, buf)
        body = _join_buf(buf).strip()
        # Use @label references (not #footnote(<label>)) so HTML cleanup does not
        # strip angle-bracket labels like <1>.
        config.setdefault('footnotes', []).append(
            f'#footnote[{body}] <{fn_label}>\n'
        )
        return [f'@{fn_label}']

    def cit(self, config, node, cls, content, source=None) -> PMResult:
        out: list = ['#quote(block: true)[\n']
        config['apply_children'](config, node, content, out)
        if source:
            out.append('\n---\n')
            config['apply_children'](config, node, source, out)
        out.append('\n]')
        return out

    def webcomponent(self, config, node, cls, content, name, optional=None) -> PMResult:
        _ = name, optional
        out: list = []
        config['apply_children'](config, node, content, out)
        return out

    def omit(self, config, node, cls, content) -> PMResult:
        return []

    def index(self, config, node, cls, content, type=None) -> PMResult:
        _ = type
        return []

    def break_(self, config, node, cls, content, type=None, label=None) -> PMResult:
        _ = content
        if (type or '').lower() == 'page':
            lb = _join_buf(normalize(label)) if label is not None else ''
            if lb:
                return [f'\n#pagebreak()\n_{lb}_\n']
            return ['\n#pagebreak()\n']
        return [' \\\n']

    def anchor(self, config, node, cls, content, id=None) -> PMResult:
        sid = str(id) if id else ''
        return [f'<{sid}>\n']

    def alternate(self, config, node, cls, content, default, alternate, optional=None) -> PMResult:
        _ = alternate, optional
        out: list = []
        config['apply_children'](config, node, default, out)
        return out

    def glyph(self, config, node, cls, content) -> PMResult:
        if content == 'char:EOLhyphen':
            return ['\u00ad']
        return []

    def text(self, config, node, cls, content) -> PMResult:
        norm = config.get('normalize_text')
        out = []
        for item in normalize(content):
            if isinstance(item, str):
                out.append(maybe_normalize_text(item, norm))
            else:
                out.append(str(item))
        return out

    def metadata(self, config, node, cls, content) -> PMResult:
        return []

    def title(self, config, node, cls, content) -> PMResult:
        out: list = []
        config['apply_children'](config, node, content, out)
        return out

    def match(self, config, node, cls, content) -> PMResult:
        out: list = ['#highlight[']
        config['apply_children'](config, node, content, out)
        out.append(']')
        return out

    def template(self, config, node, cls, template_str: str, params: dict) -> PMResult:
        nodes = apply_pb_template(template_str, params, config)
        text = _flatten_nodes_to_text(nodes)
        if not text or not text.strip():
            return []
        return [TemplateOutput(text)]

    def code(self, config, node, cls, content, language=None) -> PMResult:
        lang = language or ''
        body = literal_code_body(node, content)
        return [TemplateOutput(f'\n```{lang}\n{body}\n```\n')]
