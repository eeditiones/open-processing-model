#
# Copyright (c), 2018-2026, SISSA (International School for Advanced Studies).
# All rights reserved.
# This file is distributed under the terms of the MIT License.
# See the file 'LICENSE' in the root directory of the present
# distribution, or http://opensource.org/licenses/MIT.
#
# @author Wolfgang Meier <wolfgangmm@gmail.com>
#
"""
XQuery 3.1 implementation - scanner for direct constructors.

The XPath tokenizer is a regex that cannot tokenize XML content, so the direct
constructors are scanned from the raw source, switching back to the tokenizer
(using parser.seek()) for parsing enclosed expressions.

Refs:
  - https://www.w3.org/TR/xquery-31/#id-element-constructor
  - https://www.w3.org/TR/xquery-31/#id-otherConstructors
"""
import re
from contextlib import nullcontext
from typing import Any, Optional

from opm._vendor.elementpath.exceptions import ElementPathError
from opm._vendor.elementpath.namespaces import XML_NAMESPACE, XMLNS_NAMESPACE
from opm._vendor.elementpath.helpers import collapse_white_spaces, is_xml_codepoint
from opm._vendor.elementpath.xpath_tokens import XPathToken

from ._constructor_tokens import DirectConstructor, DirElementConstructor, \
    DirCommentConstructor, DirPIConstructor, AttributeValuePart, ContentPart, \
    QNAME_PATTERN, NCNAME_PATTERN

__all__ = ['DirectConstructorScanner']

REFERENCE_PATTERN = re.compile(r'&(?:(lt|gt|amp|quot|apos)|#([0-9]+)|#x([0-9a-fA-F]+));')
XML_WHITESPACES = ' \t\r\n'

PREDEFINED_ENTITIES = {'lt': '<', 'gt': '>', 'amp': '&', 'quot': '"', 'apos': "'"}


class DirectConstructorScanner:
    """
    Scans a direct constructor from the parser source.

    :param parser: the XQuery parser instance.
    """
    def __init__(self, parser: Any) -> None:
        self.parser = parser
        self.source: str = parser.source
        self.length = len(self.source)

    def error(self, pos: int, message: str, code: str = 'XPST0003') -> ElementPathError:
        token: XPathToken = self.parser.symbol_table['(invalid)'](
            self.parser, self.source[pos:pos + 1]
        )
        token.span = (pos, pos + 1)
        return token.error(code, message)

    def check_end(self, pos: int, what: str) -> None:
        if pos >= self.length:
            raise self.error(self.length - 1, f"unterminated {what}")

    def skip_whitespaces(self, pos: int) -> int:
        while pos < self.length and self.source[pos] in XML_WHITESPACES:
            pos += 1
        return pos

    def parse(self, start: int) -> DirectConstructor:
        """
        Parses a direct constructor starting at the position of its '<' and
        positions the parser tokenizer after it.
        """
        token: DirectConstructor
        if self.source.startswith('<!--', start):
            token, end = self.parse_comment(start)
        elif self.source.startswith('<?', start):
            token, end = self.parse_pi(start)
        else:
            token, end = self.parse_element(start)

        self.parser.token = token
        self.parser.seek(end)
        return token

    def new_token(self, cls: type[DirectConstructor], start: int, end: int) -> Any:
        token = cls(self.parser)
        token.span = (start, end)
        token.raw_source = self.source[start:end]
        return token

    def parse_enclosed_expr(self, pos: int) -> tuple[Optional[XPathToken], int]:
        """Parses an enclosed expression, *pos* is the position after the '{'."""
        parser = self.parser
        parser.seek(pos)
        if parser.next_token.symbol == '}':
            token = None
        else:
            token = parser.expression()
            if parser.next_token.symbol != '}':
                raise parser.next_token.wrong_syntax("missing '}' of an enclosed expression")
        return token, parser.next_token.span[1]

    def skip_enclosed_expr(self, pos: int) -> int:
        """
        Skips an enclosed expression without parsing it, matching the braces
        of the tokens. *pos* is the position after the '{'.
        """
        depth = 1
        tokenizer: re.Pattern[str] = self.parser.tokenizer
        for match in tokenizer.finditer(self.source, pos):
            symbol = match.group(2)
            if symbol in ('{', 'Q{'):
                depth += 1
            elif symbol == '}':
                depth -= 1
                if not depth:
                    return match.end()
        raise self.error(pos - 1, "missing '}' of an enclosed expression")

    def parse_reference(self, pos: int) -> tuple[str, int]:
        match = REFERENCE_PATTERN.match(self.source, pos)
        if match is None:
            raise self.error(pos, "invalid entity or character reference")

        entity, dec_ref, hex_ref = match.groups()
        if entity is not None:
            return PREDEFINED_ENTITIES[entity], match.end()

        codepoint = int(dec_ref, 10) if dec_ref is not None else int(hex_ref, 16)
        if not is_xml_codepoint(codepoint):
            msg = f"character reference {match.group()!r} is not a valid XML character"
            raise self.error(pos, msg, 'XQST0090')
        return chr(codepoint), match.end()

    ###
    # Comments and processing instructions
    @staticmethod
    def normalize_newlines(text: str) -> str:
        return text.replace('\r\n', '\n').replace('\r', '\n')

    def parse_comment(self, start: int) -> tuple[DirCommentConstructor, int]:
        pos = start + 4
        end = self.source.find('-->', pos)
        if end < 0:
            raise self.error(start, "unterminated comment constructor")

        content = self.source[pos:end]
        if '--' in content or content.endswith('-'):
            raise self.error(start, "a comment constructor cannot contain '--' or end with '-'")

        token = self.new_token(DirCommentConstructor, start, end + 3)
        token.value = self.normalize_newlines(content)
        return token, end + 3

    def parse_pi(self, start: int) -> tuple[DirPIConstructor, int]:
        pos = start + 2
        match = NCNAME_PATTERN.match(self.source, pos)
        if match is None:
            raise self.error(pos, "missing target of a processing instruction constructor")

        target = match.group()
        if target.lower() == 'xml':
            raise self.error(pos, f"invalid processing instruction target {target!r}")

        pos = match.end()
        end = self.source.find('?>', pos)
        if end < 0:
            raise self.error(start, "unterminated processing instruction constructor")
        elif end > pos and self.source[pos] not in XML_WHITESPACES:
            raise self.error(pos, "invalid processing instruction target")

        token = self.new_token(DirPIConstructor, start, end + 2)
        token.target = target
        token.value = self.normalize_newlines(self.source[pos:end].lstrip(XML_WHITESPACES))
        return token, end + 2

    ###
    # Element constructors
    def parse_attributes(self, pos: int, skip_enclosed: bool = False) \
            -> tuple[list[tuple[str, int, list[AttributeValuePart]]], int]:
        """
        Scans the attribute list of a start tag, returns the attributes and the
        position of the end of the list ('>' or '/>'). With *skip_enclosed* the
        enclosed expressions are not parsed and are replaced by `None` in values.
        """
        attributes: list[tuple[str, int, list[AttributeValuePart]]] = []
        while True:
            end = self.skip_whitespaces(pos)
            self.check_end(end, "start tag")
            if self.source[end] == '>' or self.source.startswith('/>', end):
                return attributes, end
            elif end == pos:
                raise self.error(pos, "missing whitespace before an attribute")

            match = QNAME_PATTERN.match(self.source, end)
            if match is None:
                raise self.error(end, "invalid attribute name")

            qname_pos, pos = end, self.skip_whitespaces(match.end())
            self.check_end(pos, "start tag")
            if self.source[pos] != '=':
                raise self.error(pos, "missing '=' after attribute name")

            pos = self.skip_whitespaces(pos + 1)
            self.check_end(pos, "start tag")
            if self.source[pos] not in '"\'':
                raise self.error(pos, "an attribute value must be quoted")

            parts, pos = self.parse_attribute_value(pos, skip_enclosed)
            attributes.append((match.group(), qname_pos, parts))

    def parse_attribute_value(self, start: int, skip_enclosed: bool = False) \
            -> tuple[list[AttributeValuePart], int]:
        source = self.source
        quote = source[start]
        parts: list[Any] = []
        chunks: list[str] = []
        pos = start + 1

        while True:
            if pos >= self.length:
                raise self.error(start, "unterminated attribute value")

            char = source[pos]
            if char == quote:
                if source.startswith(quote, pos + 1):
                    chunks.append(quote)
                    pos += 2
                    continue
                break
            elif char == '{':
                if source.startswith('{', pos + 1):
                    chunks.append('{')
                    pos += 2
                    continue
                if chunks:
                    parts.append(''.join(chunks))
                    chunks.clear()
                if skip_enclosed:
                    pos = self.skip_enclosed_expr(pos + 1)
                    parts.append(None)
                    continue

                token, pos = self.parse_enclosed_expr(pos + 1)
                if token is not None:
                    parts.append(token)
                continue
            elif char == '}':
                if not source.startswith('}', pos + 1):
                    raise self.error(pos, "unescaped '}' in attribute value")
                chunks.append('}')
                pos += 2
                continue
            elif char == '<':
                raise self.error(pos, "unescaped '<' in attribute value")
            elif char == '&':
                text, pos = self.parse_reference(pos)
                chunks.append(text)
                continue
            elif char == '\r':
                chunks.append(' ')
                pos += 2 if source.startswith('\n', pos + 1) else 1
                continue
            elif char in XML_WHITESPACES:
                chunks.append(' ')  # attribute value normalization
            else:
                chunks.append(char)
            pos += 1

        if chunks:
            parts.append(''.join(chunks))
        return parts, pos + 1

    def process_namespace_declarations(
            self, attributes: list[tuple[str, int, list[AttributeValuePart]]]) \
            -> dict[str, str]:
        declared: dict[str, str] = {}
        for qname, pos, parts in attributes:
            if qname == 'xmlns':
                prefix = ''
            elif qname.startswith('xmlns:'):
                prefix = qname[6:]
            else:
                continue

            if any(not isinstance(p, str) for p in parts):
                msg = "a namespace declaration attribute value must be a URI literal"
                raise self.error(pos, msg, 'XQST0022')

            uri = collapse_white_spaces(''.join(parts))  # type: ignore[arg-type]
            if prefix in declared:
                raise self.error(pos, f"duplicate namespace declaration {qname!r}", 'XQST0071')
            elif prefix == 'xmlns' or uri == XMLNS_NAMESPACE or \
                    prefix == 'xml' and uri != XML_NAMESPACE or \
                    prefix != 'xml' and uri == XML_NAMESPACE:
                raise self.error(pos, f"invalid namespace declaration {qname!r}", 'XQST0070')
            elif prefix and not uri:
                msg = f"namespace declaration {qname!r} cannot undeclare a prefix"
                raise self.error(pos, msg, 'XQST0085')
            declared[prefix] = uri

        return declared

    def parse_element(self, start: int) -> tuple[DirElementConstructor, int]:
        parser = self.parser
        source = self.source

        match = QNAME_PATTERN.match(source, start + 1)
        if match is None:
            raise self.error(start, "invalid direct constructor")
        qname = match.group()
        attr_start = match.end()

        # Scan attributes skipping enclosed expressions, because the start tag
        # may declare namespaces after an attribute value that uses them.
        attributes, pos = self.parse_attributes(attr_start, skip_enclosed=True)

        declared = self.process_namespace_declarations(attributes)
        if declared:
            nsmap: Optional[dict[str, str]] = {**parser.namespaces, **declared}
            if '' not in declared and parser.default_namespace:
                nsmap[''] = parser.default_namespace  # type: ignore[index]
        else:
            nsmap = None

        has_enclosed_exprs = any(
            not isinstance(p, str) for _, _, parts in attributes for p in parts
        )
        if has_enclosed_exprs:
            # Rescan the attributes parsing enclosed expressions
            with parser.in_scope_namespaces(nsmap) if nsmap is not None else nullcontext():
                attributes, pos = self.parse_attributes(attr_start)

        token = self.new_token(DirElementConstructor, start, start)
        token.qname = qname
        token.declared = declared
        token.nsmap = nsmap
        in_scope = nsmap if nsmap is not None else parser.namespaces
        default_namespace = in_scope.get('', parser.default_namespace or '')

        # Resolve names and check attributes
        prefix = match.group(1) if match.group(2) else ''
        token.element_nsmap = element_nsmap = {k: v for k, v in declared.items()}
        token.name = self.expanded_name(match, in_scope, default_namespace, start + 1)
        if token.name.startswith('{'):
            element_nsmap.setdefault(prefix, token.name[1:].split('}')[0])

        token.attributes = []
        names = set()
        for attr_qname, attr_pos, parts in attributes:
            if attr_qname == 'xmlns' or attr_qname.startswith('xmlns:'):
                continue

            attr_match = QNAME_PATTERN.match(attr_qname)
            assert attr_match is not None
            name = self.expanded_name(attr_match, in_scope, '', attr_pos)
            if name in names:
                raise self.error(attr_pos, f"duplicate attribute {attr_qname!r}", 'XQST0040')
            names.add(name)

            if attr_match.group(2):
                element_nsmap.setdefault(attr_match.group(1), name[1:].split('}')[0])
            token.attributes.append((name, parts))
            token.extend(p for p in parts if isinstance(p, XPathToken))

        # Parse content
        if source.startswith('/>', pos):
            token.content = []
            end = pos + 2
        else:
            with parser.in_scope_namespaces(nsmap) if nsmap is not None else nullcontext():
                token.content, end = self.parse_content(pos + 1, qname)
            token.extend(p for p in token.content if isinstance(p, XPathToken))

        token.span = (start, end)
        token.raw_source = source[start:end]
        return token, end

    def expanded_name(self, match: 're.Match[str]', namespaces: dict[str, str],
                      default_namespace: str, pos: int) -> str:
        if match.group(2) is None:
            local_name = match.group(1)
            return f'{{{default_namespace}}}{local_name}' if default_namespace else local_name

        prefix, local_name = match.groups()
        if prefix == 'xmlns':
            raise self.error(pos, f"invalid name {match.group()!r}", 'XQST0070')

        try:
            uri = namespaces[prefix]
        except KeyError:
            raise self.error(pos, f"namespace prefix {prefix!r} is not declared",
                             'XPST0081') from None
        return f'{{{uri}}}{local_name}' if uri else local_name

    def parse_content(self, pos: int, qname: str) -> tuple[list[ContentPart], int]:
        source = self.source
        strip = self.parser.boundary_space == 'strip'
        content: list[ContentPart] = []
        chunks: list[str] = []
        whitespace_only = True
        start = pos

        def flush() -> None:
            nonlocal whitespace_only
            if chunks:
                if not (strip and whitespace_only):
                    if content and isinstance(content[-1], str):
                        content[-1] += ''.join(chunks)
                    else:
                        content.append(''.join(chunks))
                chunks.clear()
            whitespace_only = True

        while True:
            if pos >= self.length:
                raise self.error(start - 1, f"unterminated element constructor {qname!r}")

            char = source[pos]
            if char == '<':
                if source.startswith('</', pos):
                    flush()
                    match = QNAME_PATTERN.match(source, pos + 2)
                    if match is None:
                        raise self.error(pos, "invalid end tag")
                    elif match.group() != qname:
                        msg = f"end tag doesn't match the start tag name {qname!r}"
                        raise self.error(pos, msg, 'XQST0118')
                    end = self.skip_whitespaces(match.end())
                    if not source.startswith('>', end):
                        raise self.error(end, "missing '>' of the end tag")
                    return content, end + 1

                elif source.startswith('<![CDATA[', pos):
                    end = source.find(']]>', pos + 9)
                    if end < 0:
                        raise self.error(pos, "unterminated CDATA section")
                    chunks.append(self.normalize_newlines(source[pos + 9:end]))
                    whitespace_only = False
                    pos = end + 3
                    continue

                flush()
                constructor: DirectConstructor
                if source.startswith('<!--', pos):
                    constructor, pos = self.parse_comment(pos)
                elif source.startswith('<?', pos):
                    constructor, pos = self.parse_pi(pos)
                else:
                    constructor, pos = self.parse_element(pos)
                content.append(constructor)
                continue

            elif char == '{':
                if source.startswith('{', pos + 1):
                    chunks.append('{')
                    whitespace_only = False
                    pos += 2
                    continue

                flush()
                token, pos = self.parse_enclosed_expr(pos + 1)
                if token is not None:
                    content.append(token)
                continue

            elif char == '}':
                if not source.startswith('}', pos + 1):
                    raise self.error(pos, "unescaped '}' in element content")
                chunks.append('}')
                whitespace_only = False
                pos += 2
                continue

            elif char == '&':
                text, pos = self.parse_reference(pos)
                chunks.append(text)
                whitespace_only = False
                continue

            elif char == '\r':
                chunks.append('\n')
                pos += 2 if source.startswith('\n', pos + 1) else 1
                continue

            elif char not in XML_WHITESPACES:
                whitespace_only = False
            chunks.append(char)
            pos += 1
