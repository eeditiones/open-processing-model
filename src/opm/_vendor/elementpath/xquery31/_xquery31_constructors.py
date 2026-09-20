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
XQuery 3.1 implementation - part 2 (constructors)
"""
import re
from typing import Optional

import opm._vendor.elementpath.aliases as ta

from opm._vendor.elementpath.namespaces import XML_NAMESPACE, XMLNS_NAMESPACE
from opm._vendor.elementpath.xpath_context import XPathSchemaContext
from opm._vendor.elementpath.xpath_nodes import XPathNode, DocumentNode
from opm._vendor.elementpath.xpath_tokens import XPathToken, NameToken

from .xquery31_parser import XQuery31Parser
from opm._vendor.elementpath.helpers import collapse_white_spaces

from ._constructor_tokens import CONSTRUCTED_POSITIONS_BASE, NCNAME, QNAME_PATTERN, \
    ComputedConstructor, \
    CompElementConstructor, CompAttributeConstructor, CompTextConstructor, \
    CompCommentConstructor, CompPIConstructor, CompNamespaceConstructor, \
    CompDocumentConstructor
from ._dir_scanner import DirectConstructorScanner

__all__ = ['XQuery31Parser']


###
# Direct constructors: the '<' symbol is a comparison operator in the
# operator position and the start of a direct constructor in the operand
# position.
_less_than_class = XQuery31Parser.symbol_table['<']


class _LessThanOperator(_less_than_class):  # type: ignore[misc, valid-type]

    def nud(self) -> XPathToken:
        source = self.parser.source
        pos = self.span[1]
        if source.startswith(('!--', '?'), pos) or QNAME_PATTERN.match(source, pos):
            return DirectConstructorScanner(self.parser).parse(self.span[0])
        raise self.wrong_syntax()


XQuery31Parser.symbol_table['<'] = _LessThanOperator


def is_constructed(node: XPathNode) -> bool:
    return node.root_node.position >= CONSTRUCTED_POSITIONS_BASE


###
# Node order comparisons and fn:root(): extended to the nodes of constructed
# trees, that are not reachable from the dynamic context.
def evaluate__node_order_comparison(self: XPathToken, context: ta.ContextType = None) \
        -> ta.OneOrEmpty[bool]:
    operands = []
    for token in self:
        items = [x for x in token.select(context)]
        if not items:
            return []
        elif len(items) > 1 or not isinstance(items[0], XPathNode):
            msg = f"operands of {self.symbol!r} must be single nodes"
            raise token.error('XPTY0004', msg)
        operands.append(items[0])

    left, right = operands
    if left is right or context is None:
        return False
    elif is_constructed(left) or is_constructed(right):
        if self.symbol == '<<':
            return left.position < right.position
        return left.position > right.position

    documents = [context.root]
    documents.extend(v for v in context.variables.values() if isinstance(v, DocumentNode))
    for root in documents:
        if root is not None:
            for item in root.iter_document():
                if left is item:
                    return self.symbol == '<<'
                elif right is item:
                    return self.symbol == '>>'
    raise self.error('FOCA0002', "operands are not nodes of the XML tree!")


_precedes_class = XQuery31Parser.symbol_table['<<']
_follows_class = XQuery31Parser.symbol_table['>>']


class _PrecedesOperator(_precedes_class):  # type: ignore[misc, valid-type]
    evaluate = evaluate__node_order_comparison


class _FollowsOperator(_follows_class):  # type: ignore[misc, valid-type]
    evaluate = evaluate__node_order_comparison


XQuery31Parser.symbol_table['<<'] = _PrecedesOperator
XQuery31Parser.symbol_table['>>'] = _FollowsOperator


_root_class = XQuery31Parser.symbol_table['root']


class _RootFunction(_root_class):  # type: ignore[misc, valid-type]

    def evaluate(self, context: ta.ContextType = None) -> ta.OneOrEmpty[XPathNode]:
        if self.context is not None:
            context = self.context
        elif context is None:
            raise self.missing_context()

        if isinstance(context, XPathSchemaContext):
            return []
        elif not self:
            item = context.item
        elif (item := self.get_argument(context)) is None:
            return []

        if not isinstance(item, XPathNode):
            raise self.error('XPTY0004')
        elif is_constructed(item):
            return item.root_node

        root = context.get_root(item)
        return root if root is not None else []


XQuery31Parser.symbol_table['root'] = _RootFunction

###
# Computed constructors: the keywords are not reserved and are tokenized
# as names when they are not followed by '(' or '::', so they are parsed
# by the nud() of the '(name)' token.
_SPACES = r'\s*(?:\(:.*?:\)\s*)*'
BRACE_PATTERN = re.compile(rf'{_SPACES}\{{')
QNAME_BRACE_PATTERN = re.compile(
    rf'{_SPACES}(Q\{{[^{{}}]*\}}{NCNAME}|(?:{NCNAME}:)?{NCNAME}){_SPACES}\{{'
)
NCNAME_BRACE_PATTERN = re.compile(rf'{_SPACES}({NCNAME}){_SPACES}\{{')

COMPUTED_CONSTRUCTORS: dict[str, tuple[type[ComputedConstructor], Optional[re.Pattern[str]]]] = {
    'element': (CompElementConstructor, QNAME_BRACE_PATTERN),
    'attribute': (CompAttributeConstructor, QNAME_BRACE_PATTERN),
    'processing-instruction': (CompPIConstructor, NCNAME_BRACE_PATTERN),
    'namespace': (CompNamespaceConstructor, NCNAME_BRACE_PATTERN),
    'text': (CompTextConstructor, None),
    'comment': (CompCommentConstructor, None),
    'document': (CompDocumentConstructor, None),
}


class XQueryNameToken(NameToken):

    def nud(self) -> XPathToken:
        if self.value in COMPUTED_CONSTRUCTORS and not self.namespace:
            cls, name_pattern = COMPUTED_CONSTRUCTORS[self.value]
            source = self.parser.source
            pos = self.span[1]

            if BRACE_PATTERN.match(source, pos) is not None:
                return self.parse_computed_constructor(cls, None)
            elif name_pattern is not None:
                match = name_pattern.match(source, pos)
                if match is not None:
                    return self.parse_computed_constructor(cls, match)

        return super().nud()

    def parse_computed_constructor(self, cls: type[ComputedConstructor],
                                   match: Optional['re.Match[str]']) -> ComputedConstructor:
        parser = self.parser
        token = cls(parser)
        token.span = self.span

        if match is not None:
            self.set_literal_name(token, match.group(1), match.start(1))
            parser.seek(match.end() - 1)
        elif cls in (CompElementConstructor, CompAttributeConstructor,
                     CompPIConstructor, CompNamespaceConstructor):
            parser.advance('{')
            token.name_token = parser.expression()
            parser.advance('}')

        parser.advance('{')
        if parser.next_token.symbol != '}':
            token.content_token = parser.expression()
        parser.advance('}')

        token[:] = [tk for tk in (token.name_token, token.content_token) if tk is not None]
        token.span = (self.span[0], parser.token.span[1])
        token.raw_source = parser.source[token.span[0]:token.span[1]]
        return token

    def set_literal_name(self, token: ComputedConstructor, name: str, pos: int) -> None:
        position_token = XQueryNameToken(self.parser, name)
        position_token.span = (pos, pos + len(name))

        if not isinstance(token, (CompElementConstructor, CompAttributeConstructor)):
            token.name = name
            return

        if name.startswith('Q{'):
            uri, _, local_name = name[2:].partition('}')
            token.uri = collapse_white_spaces(self.parser.unescape(f'"{uri}"'))
            token.name = local_name
            return

        prefix, _, local_name = name.rpartition(':')
        if not prefix:
            uri = self.parser.default_namespace or '' \
                if isinstance(token, CompElementConstructor) else ''
        else:
            try:
                uri = self.parser.namespaces[prefix]
            except KeyError:
                msg = f"namespace prefix {prefix!r} is not declared"
                raise position_token.error('XPST0081', msg) from None

        if isinstance(token, CompElementConstructor):
            if prefix == 'xmlns' or uri == XMLNS_NAMESPACE or \
                    (prefix == 'xml') is not (uri == XML_NAMESPACE):
                raise position_token.error('XQDY0096', f"invalid element name {name!r}")
            token.prefix = prefix
        elif prefix == 'xmlns' or uri == XMLNS_NAMESPACE or \
                not prefix and local_name == 'xmlns' or \
                (prefix == 'xml') is not (uri == XML_NAMESPACE):
            raise position_token.error('XQDY0044', f"invalid attribute name {name!r}")

        token.uri = uri
        token.name = local_name


XQuery31Parser.symbol_table['(name)'] = XQueryNameToken
