# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Markdown serialisation for the TEI processing model (``markdown-functions.xql`` equivalent)."""

from __future__ import annotations

import re
from lxml import etree

from opm.runtime.output_functions import (
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

MD_INDENT = '    '

# CSS properties → markdown markers (checked in order; markers are stacked outermost-first)
_CSS_TO_MD_MARKERS = [
    # (property, value_substring_to_match, open_marker, close_marker)
    ('font-weight',    'bold',         '**', '**'),
    ('font-style',     'italic',       '_',  '_'),
    ('text-decoration','line-through', '~~', '~~'),
    ('text-decoration','underline',    '<u>', '</u>'),
    ('font-family',    'monospace',    '`',  '`'),
]


def _parse_css_classes(css_text: str) -> dict:
    """Parse *css_text* and return ``{class_name: {property: value}}`` for simple class selectors.

    Only plain single-class selectors (e.g. ``.simple_bold``) are indexed;
    complex selectors (combinators, pseudo-classes, attribute selectors) are skipped.
    """
    # Strip comments first so they don't contaminate selector strings between blocks.
    css_text = re.sub(r'/\*.*?\*/', '', css_text, flags=re.DOTALL)
    result: dict = {}
    for block in re.finditer(r'([^{}]+)\{([^{}]*)\}', css_text):
        selector_part = block.group(1).strip()
        props_text = block.group(2)
        props: dict = {}
        for pm in re.finditer(r'([\w-]+)\s*:\s*([^;]+)', props_text):
            props[pm.group(1).strip().lower()] = pm.group(2).strip().lower()
        if not props:
            continue
        for sel in selector_part.split(','):
            sel = sel.strip()
            m = re.match(r'^\.([a-zA-Z0-9_-]+)$', sel)
            if m:
                cls_name = m.group(1)
                result.setdefault(cls_name, {}).update(props)
    return result


def _get_css_map(config: dict) -> dict:
    """Return (and cache) the parsed CSS class map from ``config['odd_css']``."""
    if '_css_map' not in config:
        config['_css_map'] = _parse_css_classes(config.get('odd_css', ''))
    return config['_css_map']


def _css_class_names(cls: list) -> set[str]:
    """Flatten dispatch class list entries into individual class names."""
    class_names: set[str] = set()
    for item in cls:
        if item:
            for name in str(item).split():
                class_names.add(name)
    return class_names


def _css_trailing_space(config: dict, cls: list) -> str:
    """Return a trailing space when ODD CSS specifies ``margin-right``.

    HTML margins have no plain-text equivalent; a space after the span keeps
  emphasis markers like ``_Leon._`` from running into the following word.
    """
    css_map = _get_css_map(config)
    for name in _css_class_names(cls):
        margin = css_map.get(name, {}).get('margin-right', '')
        if margin and margin not in ('0', '0px', '0em', '0rem', '0%'):
            return ' '
    return ''


def _css_md_markers(config: dict, cls: list) -> tuple[str, str]:
    """Return ``(prefix, suffix)`` markdown markers derived from the CSS classes in *cls*.

    Looks up each class name against the ODD-generated CSS and converts recognised
    styling properties (bold, italic, strikethrough, underline, monospace) to the
    corresponding CommonMark markers.  Multiple properties are stacked in the order
    defined by :data:`_CSS_TO_MD_MARKERS`.
    """
    css_map = _get_css_map(config)
    # Collect CSS properties for the matched classes
    combined: dict = {}
    for name in _css_class_names(cls):
        if name in css_map:
            combined.update(css_map[name])
    if not combined:
        return '', ''
    prefix = ''
    suffix = ''
    for prop, val_fragment, open_m, close_m in _CSS_TO_MD_MARKERS:
        css_val = combined.get(prop, '')
        if val_fragment in css_val:
            prefix += open_m
            suffix = close_m + suffix
    return prefix, suffix


def normalize_markdown_xml_text(s: str) -> str:
    """Collapse pretty-print line breaks and indentation in XML text/tail nodes.

    Browsers collapse this in HTML; plain-text markdown must do the same so
    flowing prose matches tei-publisher-lib and does not carry XML indentation
    into the output.
    """
    if not s:
        return s
    t = re.sub(r'\r?\n[ \t]*', ' ', s)
    t = re.sub(r'[ \t]{2,}', ' ', t)
    # Drop fragments that were only pretty-print padding (must not remove a lone
    # inter-element space: </foo> <bar>).
    if not s.strip() and '\n' in s:
        return ''
    return t


def _join_buf(buf: list) -> str:
    return ''.join(x if isinstance(x, str) else '' for x in buf)


_HTML_VOID_ELEMENTS = frozenset({
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
    'source', 'track', 'wbr',
})

_XML_NS = 'http://www.w3.org/XML/1998/namespace'


def _html_attr_name(key: str) -> str:
    q = etree.QName(key)
    return f'xml:{q.localname}' if q.namespace == _XML_NS else q.localname


def _serialize_html(el: etree._Element) -> str:
    """Serialise an element produced by a pass-through template as HTML.

    Definition lists, anchors, embeds etc. survive into the markdown for the renderer.
    Text is emitted as is, since it is already markdown.  ``<dd>``/``<li>``
    content is padded with blank lines so CommonMark still parses markdown
    inside the HTML block.
    """
    name = etree.QName(el).localname
    attrs = ''.join(
        f' {_html_attr_name(k)}="'
        + v.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;')
        + '"'
        for k, v in el.attrib.items()
    )
    parts: list[str] = [el.text or '']
    for child in el:
        if not callable(child.tag):
            parts.append(_serialize_html(child))
        parts.append(child.tail or '')
    inner = ''.join(parts)
    if name in _HTML_VOID_ELEMENTS and not inner:
        return f'<{name}{attrs}>'
    if name in ('dd', 'li') and inner.strip():
        inner = f'\n\n{inner}\n'
    return f'<{name}{attrs}>{inner}</{name}>'


def _strip_template_indentation(template_str: str) -> str:
    """Drop the pretty-print whitespace of a ``pb:template`` literal.

    Remove leading spaces inside HTML produced by pass-through templates (e.g. ``dl/dt/dd``); indented
    template markup would otherwise reach the markdown and CommonMark would read
    it as an indented code block.  Cleaning the literal before substitution
    leaves the indentation of the rendered content (list items) intact.
    """
    s = re.sub(r'>\s*\n\s*<', '><', template_str)
    s = re.sub(r'^\s*\n\s*|\s*\n\s*$', '', s)
    return re.sub(r'\n[ \t]+', '\n', s)


def _serialize_pm_result(nodes: list) -> str:
    """Concatenate transform fragments the same way ``pmf:finish`` string-joins input."""
    parts: list[str] = []
    for item in nodes:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, etree._Element):
            parts.append(_serialize_html(item))
    return ''.join(parts)


def apply_markdown_finish_regexes(text: str) -> str:
    """Regex cleanups from ``pmf:finish`` in ``markdown-functions.xql`` (after tree normalisation there)."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'_\s*(\S.*?)\s*_', r'_\1_', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*\s*(\S.*?)\s*\*\*', r'**\1**', text, flags=re.MULTILINE)
    # CommonMark requires a blank line between an HTML block and an ATX heading.
    text = re.sub(r'(</[^>]+>)\n(#{1,6}\s)', r'\1\n\n\2', text, flags=re.MULTILINE)
    return text


class MarkdownOutputFunctions(ProcessingModelFunctions):
    """Serialise to Markdown text fragments (CommonMark-style).

    Mirrors ``pmf:*`` in ``tei-publisher-lib/content/markdown-functions.xql``:
    paragraph breaks, headings with ``#``, list markers, pipe tables, links,
    reference-style notes, and simple ``rend``-based emphasis.
    """

    def finish(self, config, nodes: list) -> list:
        """Run ``pmf:finish``-style cleanup: collapse blank lines, tighten ``_`` / ``**`` spans."""
        text = apply_markdown_finish_regexes(_serialize_pm_result(nodes))
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
        trailing = _css_trailing_space(config, cls)

        # Explicit @rend attribute takes priority over CSS-derived formatting.
        rend = (node.get('rend') or '').split()
        if 'bold' in rend:
            return [f'**{text}**{trailing}']
        if 'italic' in rend or 'italics' in rend:
            return [f'_{text}_{trailing}']

        # Fall back to CSS-based formatting derived from the element's class list.
        prefix, suffix = _css_md_markers(config, cls)
        if prefix:
            return [f'{prefix}{text}{suffix}{trailing}']
        return [text]

    def paragraph(self, config, node, cls, content) -> PMResult:
        out: list = []
        # No indent for the first child: inside a list item the marker already
        # sits on this line, and the extra indent would push the text into an
        # indented code block (same rule as pmf:paragraph).
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
        hashes = '#' * lvl
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
        out: list = []
        ind = config.get('indent', '')
        list_type = config.get('listType', 'unordered')
        # Count only siblings of the same element, so an ordered list whose items
        # follow a heading (JATS <ref-list><title>… then <ref>) still starts at 1.
        pos = sum(1 for s in node.itersiblings(preceding=True) if s.tag == node.tag) + 1
        marker = f'{pos}. ' if list_type == 'ordered' else '- '
        out.append('\n')
        out.append(ind)
        out.append(marker)
        deeper = {**config, 'indent': ind + MD_INDENT}
        config['apply_children'](deeper, node, content, out)
        out.append('\n')
        return out

    def link(self, config, node, cls, content, uri, target, optional) -> PMResult:
        if isinstance(uri, etree._Element):
            href = uri.get(XLINK_HREF)
        else:
            href = uri
        href_s = str(href) if href else ''
        out: list = ['[']
        config['apply_children'](config, node, content, out)
        out.append(f']({href_s})')
        return out

    def table(self, config, node, cls, content) -> PMResult:
        out: list = ['\n']
        config['apply_children'](config, node, content, out)
        out.append('\n')
        return out

    def row(self, config, node, cls, content) -> PMResult:
        out: list = ['|']
        config['apply_children'](config, node, content, out)
        out.append('\n')
        if node.getprevious() is None:
            n = len(node)
            if n > 0:
                out.append('|' + '|'.join([' --- '] * n) + '|\n')
        return out

    def cell(self, config, node, cls, content, type=None) -> PMResult:
        _ = type
        out: list = [' ']
        config['apply_children'](config, node, content, out)
        out.append(' |')
        return out

    def figure(self, config, node, cls, content, title=None) -> PMResult:
        out: list = ['\n']
        config['apply_children'](config, node, content, out)
        if title:
            out.append('\n\n_')
            tbuf: list = []
            config['apply_children'](config, node, title, tbuf)
            out.extend(tbuf)
            out.append('_')
        out.append('\n\n')
        return out

    def graphic(self, config, node, cls, content, url,
                width, height, scale, title) -> PMResult:
        _ = content, width, height, scale
        if isinstance(url, etree._Element):
            href = url.get(XLINK_HREF) or ''
        else:
            href = str(url) if url else ''
        tit = str(title) if title else ''
        return [f'![{tit}]({href})']

    def note(self, config, node, cls, content, place=None, label=None) -> PMResult:
        from . import output_functions as of

        of._note_counter += 1
        nr = of._note_counter
        node_id = node.get(XML_ID) or node.get('id') or str(nr)
        safe_id = re.sub(r'[-.]', '_', node_id)
        ref = f'[^{safe_id}]'
        buf: list = []
        config['apply_children'](config, node, content, buf)
        body = _join_buf(buf).strip()
        config.setdefault('footnotes', []).append(f'\n[^{safe_id}]: {body}\n')
        return [ref]

    def cit(self, config, node, cls, content, source=None) -> PMResult:
        out: list = ['\n> ']
        config['apply_children'](config, node, content, out)
        if source:
            out.append('\n> — ')
            config['apply_children'](config, node, source, out)
        return out

    def webcomponent(self, config, node, cls, content, name, optional=None) -> PMResult:
        out: list = [f'<{name}']
        for k, v in (optional or {}).items():
            if isinstance(v, bool):
                if v:
                    out.append(f' {k}')
            else:
                out.append(f' {k}="{v}"')
        out.append('>')
        config['apply_children'](config, node, content, out)
        out.append(f'</{name}>')
        return out

    def omit(self, config, node, cls, content) -> PMResult:
        return []

    def index(self, config, node, cls, content, type=None) -> PMResult:
        _ = type
        return []

    def break_(self, config, node, cls, content, type=None, label=None) -> PMResult:
        if (type or '').lower() == 'page':
            lb = _join_buf(normalize(label)) if label is not None else ''
            return [f'|{lb}|']
        return ['  \n']

    def anchor(self, config, node, cls, content, id=None) -> PMResult:
        sid = str(id) if id else ''
        return [f"<a id='{sid}'></a>"]

    def alternate(self, config, node, cls, content, default, alternate, optional=None) -> PMResult:
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
        out: list = ['==']
        config['apply_children'](config, node, content, out)
        out.append('==')
        return out

    def template(self, config, node, cls, template_str: str, params: dict) -> PMResult:
        nodes = apply_pb_template(_strip_template_indentation(template_str), params, config)
        # Serialise HTML here rather than in finish: the runtime stringifies
        # elements as soon as they are appended to a list buffer, which would
        # skip the <dd>/<li> padding.  A nested template (varlistentry inside
        # variablelist) thus arrives as finished text in its parent's markup.
        return [
            TemplateOutput(_serialize_html(n)) if isinstance(n, etree._Element) else n
            for n in nodes
        ]

    def code(self, config, node, cls, content, language=None) -> PMResult:
        lang = language or ''
        body = literal_code_body(node, content)
        # The fences must sit on lines of their own: without the breaks a
        # closing fence runs into the next opening one (``````xml) or into the
        # following text.  The trailing blank line matches pmf:code's <lb2/>.
        return [TemplateOutput(f'\n```{lang}\n{body}\n```\n\n')]

    def code_inline(self, config, node, cls, content) -> PMResult:
        body = literal_code_body(node, content)
        return [TemplateOutput(f'`{body}`')]
