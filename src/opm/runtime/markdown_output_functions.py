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


def _css_md_markers(config: dict, cls: list) -> tuple[str, str]:
    """Return ``(prefix, suffix)`` markdown markers derived from the CSS classes in *cls*.

    Looks up each class name against the ODD-generated CSS and converts recognised
    styling properties (bold, italic, strikethrough, underline, monospace) to the
    corresponding CommonMark markers.  Multiple properties are stacked in the order
    defined by :data:`_CSS_TO_MD_MARKERS`.
    """
    css_map = _get_css_map(config)
    # Flatten class names from the cls list (entries may be space-separated strings or None)
    class_names: set[str] = set()
    for item in cls:
        if item:
            for name in str(item).split():
                class_names.add(name)
    # Collect CSS properties for the matched classes
    combined: dict = {}
    for name in class_names:
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


def _serialize_pm_result(nodes: list) -> str:
    """Concatenate transform fragments the same way ``pmf:finish`` string-joins input."""
    parts: list[str] = []
    for item in nodes:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, etree._Element):
            parts.append(etree.tostring(item, encoding='unicode', method='html'))
    return ''.join(parts)


def apply_markdown_finish_regexes(text: str) -> str:
    """Regex cleanups from ``pmf:finish`` in ``markdown-functions.xql`` (after tree normalisation there)."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'_\s*(\S.*?)\s*_', r'_\1_', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*\s*(\S.*?)\s*\*\*', r'**\1**', text, flags=re.MULTILINE)
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

        # Explicit @rend attribute takes priority over CSS-derived formatting.
        rend = (node.get('rend') or '').split()
        if 'bold' in rend:
            return [f'**{text}**']
        if 'italic' in rend or 'italics' in rend:
            return [f'_{text}_']

        # Fall back to CSS-based formatting derived from the element's class list.
        prefix, suffix = _css_md_markers(config, cls)
        if prefix:
            return [f'{prefix}{text}{suffix}']
        return [text]

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
        pos = len(list(node.itersiblings(preceding=True))) + 1
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
        return apply_pb_template(template_str, params, config)

    def code(self, config, node, cls, content, language=None) -> PMResult:
        lang = language or ''
        body = literal_code_body(node, content)
        return [TemplateOutput(f'```{lang}\n{body}\n```')]

    def code_inline(self, config, node, cls, content) -> PMResult:
        body = literal_code_body(node, content)
        return [TemplateOutput(f'`{body}`')]
