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
XQuery 3.1 implementation - node constructor tokens and the builder of new node trees.

Refs:
  - https://www.w3.org/TR/xquery-31/#id-constructors
"""
import re
import threading
from collections.abc import Iterator
from contextlib import nullcontext
from copy import copy, deepcopy
from types import ModuleType
from typing import Any, Optional, Union

import opm._vendor.elementpath.aliases as ta

from opm._vendor.elementpath.exceptions import ElementPathError
from opm._vendor.elementpath.namespaces import XML_NAMESPACE, XMLNS_NAMESPACE, XML_ID
from opm._vendor.elementpath.helpers import collapse_white_spaces
from opm._vendor.elementpath.datatypes import QName, UntypedAtomic
from opm._vendor.elementpath.xpath_nodes import XPathNode, AttributeNode, CommentNode, DocumentNode, \
    ElementNode, NamespaceNode, ProcessingInstructionNode, TextNode, TextAttributeNode
from opm._vendor.elementpath.tree_builders import get_node_tree
from opm._vendor.elementpath.xpath_tokens import XPathToken, XPathFunction

__all__ = ['NodeConstructor', 'DirectConstructor', 'DirElementConstructor',
           'DirCommentConstructor', 'DirPIConstructor', 'ComputedConstructor',
           'CompElementConstructor', 'CompAttributeConstructor', 'CompTextConstructor',
           'CompCommentConstructor', 'CompPIConstructor', 'CompDocumentConstructor',
           'CompNamespaceConstructor', 'NodeTreeBuilder', 'ContentPart',
           'AttributeValuePart', 'NCNAME', 'QNAME_PATTERN', 'NCNAME_PATTERN',
           'EQNAME_PATTERN', 'CONSTRUCTED_POSITIONS_BASE']

NCNAME = r'[^\W\d][\w.\-\u00B7\u0300-\u036F\u203F\u2040]*'
QNAME_PATTERN = re.compile(rf'({NCNAME})(?::({NCNAME}))?')
NCNAME_PATTERN = re.compile(NCNAME)
EQNAME_PATTERN = re.compile(rf'Q\{{([^{{}}]*)\}}({NCNAME})')

# A part of an attribute value or of the content of an element: literal
# text, an enclosed expression or a nested direct constructor.
AttributeValuePart = Union[str, XPathToken]
ContentPart = Union[str, XPathToken]


###
# Positions for document order of constructed node trees. Each new tree
# gets a separate range of positions, placed after the ones usually used
# by the node trees built from input documents.
CONSTRUCTED_POSITIONS_BASE = 1 << 40

_position_lock = threading.Lock()
_next_position = CONSTRUCTED_POSITIONS_BASE


def reserve_positions(size: int) -> int:
    global _next_position
    with _position_lock:
        position = _next_position
        _next_position += size + 1
    return position


def _positions_size(elem: Any) -> int:
    size = 2
    for e in elem.iter():
        try:
            size += len(e.attrib) + 4
        except (AttributeError, TypeError):
            size += 4
        nsmap = getattr(e, 'nsmap', None)
        if nsmap:
            size += len(nsmap)
    return size


class NodeTreeBuilder:
    """
    Helper for building the ElementTree or lxml structure of a constructed node.

    :param context: the XPath dynamic context used for evaluation.
    """
    def __init__(self, context: ta.ContextType) -> None:
        self.etree: ModuleType
        if context is None:
            import xml.etree.ElementTree as ElementTree
            self.etree = ElementTree
        else:
            self.etree = context.etree

        self.is_lxml = self.etree.__name__ == 'lxml.etree'
        self.namespaces: dict[str, str] = {}  # namespaces collected for an ElementTree tree

    def add_namespace(self, prefix: str, uri: str) -> None:
        if prefix == 'xml' or not uri or uri == XML_NAMESPACE:
            return
        elif prefix not in self.namespaces:
            if not prefix or uri not in self.namespaces.values():
                self.namespaces[prefix] = uri
        elif self.namespaces[prefix] != uri and uri not in self.namespaces.values():
            self.add_generated_prefix(uri)

    def add_generated_prefix(self, uri: str) -> None:
        k = 0
        while f'ns{k}' in self.namespaces:
            k += 1
        self.namespaces[f'ns{k}'] = uri

    def create_element(self, tag: str, nsmap: dict[str, str], parent: Any = None) -> Any:
        for prefix, uri in nsmap.items():
            self.add_namespace(prefix, uri)

        if not self.is_lxml:
            if parent is None:
                return self.etree.Element(tag)
            return self.etree.SubElement(parent, tag)

        lxml_nsmap = {pfx or None: uri for pfx, uri in nsmap.items() if uri and pfx != 'xml'}
        if parent is None:
            return self.etree.Element(tag, nsmap=lxml_nsmap)
        return self.etree.SubElement(parent, tag, nsmap=lxml_nsmap)

    def add_element_namespace(self, elem: Any, prefix: str, uri: str) -> Any:
        """
        Adds a namespace binding to an element without content, returning the element
        (with lxml a new element is created because the nsmap is not modifiable).
        """
        self.add_namespace(prefix, uri)
        if not self.is_lxml:
            return elem

        key = prefix or None
        if elem.nsmap.get(key) == uri:
            return elem

        nsmap = {k: v for k, v in elem.nsmap.items()}
        nsmap[key] = uri
        new_elem = self.etree.Element(elem.tag, attrib=dict(elem.attrib), nsmap=nsmap)
        parent = elem.getparent()
        if parent is not None:
            parent.replace(elem, new_elem)
        return new_elem

    @staticmethod
    def append_text(elem: Any, text: str) -> None:
        if not text:
            return
        elif len(elem):
            last = elem[-1]
            last.tail = text if last.tail is None else last.tail + text
        else:
            elem.text = text if elem.text is None else elem.text + text

    def create_comment(self, text: str) -> Any:
        return self.etree.Comment(text)

    def create_pi(self, target: str, content: str) -> Any:
        return self.etree.ProcessingInstruction(target, content or None)

    def copy_element(self, node: ElementNode) -> Any:
        elem: Any = node.value
        if not hasattr(elem, 'tag') or callable(elem.tag):
            raise TypeError(f"cannot copy {node!r}")

        if not self.is_lxml and isinstance(node.nsmap, dict):
            uris = {name[1:].split('}')[0] for e in elem.iter() if not callable(e.tag)
                    for name in (e.tag, *e.attrib) if name[0] == '{'}
            for prefix, uri in node.nsmap.items():
                if prefix and uri in uris:
                    self.add_namespace(prefix, uri)

        if elem.__class__.__module__.startswith('lxml') == self.is_lxml:
            new_elem = deepcopy(elem)
            new_elem.tail = None
            return new_elem

        # Convert between ElementTree and lxml
        tail, elem.tail = elem.tail, None
        try:
            if self.is_lxml:
                import xml.etree.ElementTree as ElementTree
                data = ElementTree.tostring(elem)
            else:
                import lxml.etree as lxml_etree
                data = lxml_etree.tostring(elem)
        finally:
            elem.tail = tail
        return self.etree.fromstring(data)

    def get_node(self, elem: Any, base_uri: Optional[str] = None) -> ElementNode:
        if not self.is_lxml:
            # Each namespace used in names must be mapped to a prefix
            uris = set(self.namespaces.values())
            for e in elem.iter():
                if callable(e.tag):
                    continue
                for name in (e.tag, *e.attrib):
                    if name[0] == '{':
                        uri = name[1:].split('}')[0]
                        if uri not in uris and uri != XML_NAMESPACE:
                            self.add_generated_prefix(uri)
                            uris.add(uri)

        position = reserve_positions(_positions_size(elem))
        node = get_node_tree(
            root=elem,
            namespaces=None if self.is_lxml else self.namespaces,
            uri=base_uri,
            fragment=True,
            position=position
        )
        assert isinstance(node, ElementNode)
        return node


class NodeConstructor(XPathToken):
    """Base class for XQuery 3.1 node constructors."""
    symbol = '(node constructor)'
    label = 'node constructor'
    raw_source: str = ''

    def __str__(self) -> str:
        return f'{self.label} {self.raw_source!r}'

    @property
    def source(self) -> str:
        return self.raw_source

    @property
    def tree(self) -> str:
        return f'({self.symbol} {self.raw_source})'

    def nud(self) -> XPathToken:
        return self

    def iter_enclosed_items(self, token: XPathToken, context: ta.ContextType) \
            -> Iterator[ta.ItemType]:
        # Materialize results, for not exiting from in-scope namespaces
        yield from [x for x in token.select_flatten(copy(context))]

    def atomized_strings(self, token: Optional[XPathToken],
                         context: ta.ContextType) -> Optional[list[str]]:
        """
        Returns the atomized values of an enclosed expression as strings,
        or `None` if the expression is empty or produces the empty sequence.
        """
        if token is None:
            return None

        values: list[str] = []
        for item in self.iter_enclosed_items(token, context):
            if isinstance(item, XPathFunction) and item.label != 'array':
                raise token.error('FOTY0013', f"{item.label!r} has no typed value")
            values.extend(self.string_value(x) for x in self.atomize_item(item))
        return values if values else None

    def add_enclosed_content(self, token: XPathToken,
                             context: ta.ContextType,
                             builder: NodeTreeBuilder,
                             elem: Any,
                             has_content: bool,
                             document: bool = False) -> tuple[Any, bool]:
        """
        Adds the content sequence of an enclosed expression to an element.

        Ref: https://www.w3.org/TR/xquery-31/#id-content

        :return: a couple with the element and a boolean that is `True` \
        if the element has content that is not an attribute or a namespace.
        """
        atomics: list[str] = []

        for item in self.iter_enclosed_items(token, context):
            if not isinstance(item, XPathNode):
                if isinstance(item, XPathFunction):
                    msg = f"{item.label!r} cannot be the content of a node"
                    raise token.error('XQTY0105', msg)
                atomics.extend(self.string_value(x) for x in self.atomize_item(item))
                continue

            if atomics:
                text = ' '.join(atomics)
                atomics.clear()
                if text:
                    builder.append_text(elem, text)
                    has_content = True

            if isinstance(item, AttributeNode):
                if document:
                    raise token.error('XPTY0004', "a document cannot contain attributes")
                elif has_content:
                    msg = "an attribute node cannot follow other content of an element"
                    raise token.error('XQTY0024', msg)

                assert item.name is not None
                if item.name in elem.attrib:
                    raise token.error('XQDY0025', f"duplicate attribute {item.name!r}")
                self.add_attribute_namespace(item, builder)
                elem.set(item.name, item.string_value)

            elif isinstance(item, NamespaceNode):
                if document:
                    raise token.error('XPTY0004', "a document cannot contain namespaces")
                elif has_content:
                    msg = "a namespace node cannot follow other content of an element"
                    raise token.error('XQTY0024', msg)
                elem = builder.add_element_namespace(elem, item.prefix or '', item.uri)

            elif isinstance(item, DocumentNode):
                for child in item.children:
                    if self.add_child_node(child, builder, elem, token):
                        has_content = True
            elif self.add_child_node(item, builder, elem, token):
                has_content = True

        if atomics:
            text = ' '.join(atomics)
            if text:
                builder.append_text(elem, text)
                has_content = True

        return elem, has_content

    @staticmethod
    def add_attribute_namespace(attr: AttributeNode, builder: NodeTreeBuilder) -> None:
        if attr.name and attr.name[0] == '{' and isinstance(attr.parent, ElementNode):
            namespace = attr.name[1:].split('}')[0]
            for prefix, uri in attr.parent.nsmap.items():
                if uri == namespace and prefix:
                    builder.add_namespace(prefix, uri)
                    break

    @staticmethod
    def add_child_node(node: XPathNode, builder: NodeTreeBuilder,
                       elem: Any, token: XPathToken) -> bool:
        """Copies a node into the element, returns `True` if content is added."""
        if isinstance(node, TextNode):
            builder.append_text(elem, node.value)
            return bool(node.value)
        elif isinstance(node, ElementNode):
            try:
                elem.append(builder.copy_element(node))
            except TypeError as err:
                raise token.error('XPTY0004', err) from None
        elif isinstance(node, CommentNode):
            elem.append(builder.create_comment(node.string_value))
        elif isinstance(node, ProcessingInstructionNode):
            elem.append(builder.create_pi(node.name, node.content))
        else:
            raise token.error('XPTY0004', f"cannot add {node!r} to element content")
        return True


###
# Direct constructors

class DirectConstructor(NodeConstructor):
    """Base class for direct constructors of XQuery 3.1."""
    symbol = '(direct constructor)'
    label = 'direct constructor'

    def build(self, context: ta.ContextType, builder: NodeTreeBuilder,
              parent: Any = None) -> Any:
        """Builds the ElementTree/lxml object of the constructed node."""
        raise NotImplementedError()


class DirCommentConstructor(DirectConstructor):
    symbol = '(direct comment)'
    label = 'comment constructor'
    value: str

    def build(self, context: ta.ContextType, builder: NodeTreeBuilder,
              parent: Any = None) -> Any:
        comment = builder.create_comment(self.value)
        if parent is not None:
            parent.append(comment)
        return comment

    def evaluate(self, context: ta.ContextType = None) -> CommentNode:
        if context is None:
            raise self.missing_context()
        builder = NodeTreeBuilder(context)
        return CommentNode(self.build(context, builder), position=reserve_positions(1))


class DirPIConstructor(DirectConstructor):
    symbol = '(direct processing-instruction)'
    label = 'processing instruction constructor'
    value: str
    target: str

    def build(self, context: ta.ContextType, builder: NodeTreeBuilder,
              parent: Any = None) -> Any:
        pi = builder.create_pi(self.target, self.value)
        if parent is not None:
            parent.append(pi)
        return pi

    def evaluate(self, context: ta.ContextType = None) -> ProcessingInstructionNode:
        if context is None:
            raise self.missing_context()
        builder = NodeTreeBuilder(context)
        return ProcessingInstructionNode(
            self.build(context, builder), position=reserve_positions(1)
        )


class DirElementConstructor(DirectConstructor):
    """
    A direct element constructor. The token's children are the attribute value
    enclosed expressions and the content tokens, for having a complete token tree.

    :ivar name: the expanded name of the element.
    :ivar qname: the lexical QName of the element.
    :ivar nsmap: the in-scope namespaces map if the constructor declares \
    namespaces, `None` otherwise.
    :ivar declared: the namespaces declared by the constructor.
    :ivar element_nsmap: the declared namespaces plus the ones used by names.
    :ivar attributes: a list of couples with the expanded name and the parts \
    of the value of each attribute.
    :ivar content: the parts of the element's content.
    """
    symbol = '(direct element)'
    label = 'element constructor'

    name: str
    qname: str
    nsmap: Optional[dict[str, str]] = None
    declared: dict[str, str]
    element_nsmap: dict[str, str]
    attributes: list[tuple[str, list[AttributeValuePart]]]
    content: list[ContentPart]

    def evaluate(self, context: ta.ContextType = None) -> ElementNode:
        if context is None:
            raise self.missing_context()

        builder = NodeTreeBuilder(context)
        try:
            elem = self.build(context, builder)
        except ValueError as err:
            if isinstance(err, ElementPathError):
                raise
            raise self.error('XQDY0074', err) from None  # e.g. names rejected by lxml
        return builder.get_node(elem, self.parser.base_uri)

    def attribute_value(self, parts: list[AttributeValuePart],
                        context: ta.ContextType) -> str:
        chunks = []
        for part in parts:
            if isinstance(part, str):
                chunks.append(part)
            else:
                chunks.append(' '.join(self.atomized_strings(part, context) or ()))
        return ''.join(chunks)

    def build(self, context: ta.ContextType, builder: NodeTreeBuilder,
              parent: Any = None) -> Any:
        if self.nsmap is not None:
            scope: Any = self.parser.in_scope_namespaces(self.nsmap)  # type: ignore[attr-defined]
        else:
            scope = nullcontext()

        with scope:
            attrib = {name: self.attribute_value(parts, context)
                      for name, parts in self.attributes}
            if XML_ID in attrib:
                attrib[XML_ID] = collapse_white_spaces(attrib[XML_ID])

            elem = builder.create_element(self.name, self.element_nsmap, parent)
            for name, value in attrib.items():
                elem.set(name, value)

            has_content = False
            for part in self.content:
                if isinstance(part, str):
                    if part:
                        builder.append_text(elem, part)
                        has_content = True
                elif isinstance(part, DirectConstructor):
                    part.build(context, builder, elem)
                    has_content = True
                else:
                    elem, has_content = self.add_enclosed_content(
                        part, context, builder, elem, has_content
                    )

        return elem


###
# Computed constructors

class ComputedConstructor(NodeConstructor):
    """
    Base class for computed constructors of XQuery 3.1. A computed constructor
    has a name (a literal name or an expression), and a content expression.
    Both the name expression and the content expression are also children of
    the token.

    :ivar name: the name or target, if it's specified as a literal.
    :ivar name_token: the expression that computes the name or the target.
    :ivar content_token: the content expression, `None` if the content is empty.
    """
    symbol = '(computed constructor)'
    label = 'computed constructor'

    keyword: str = ''
    name: str = ''
    name_token: Optional[XPathToken] = None
    content_token: Optional[XPathToken] = None

    def get_single_atomic(self, token: XPathToken, context: ta.ContextType) -> Any:
        values = [x for item in self.iter_enclosed_items(token, context)
                  for x in self.atomize_item(item)]
        if len(values) != 1:
            msg = f"the name expression of {self.keyword} constructor " \
                  f"must be a single atomic value"
            raise token.error('XPTY0004', msg)
        return values[0]

    def get_qname(self, context: ta.ContextType, default_namespace: str) \
            -> tuple[str, str, str]:
        """Returns the prefix, the namespace URI and the local name."""
        assert self.name_token is not None
        value = self.get_single_atomic(self.name_token, context)

        if isinstance(value, QName):
            return value.prefix or '', value.uri or '', value.local_name
        elif not isinstance(value, (str, UntypedAtomic)):
            msg = f"invalid type {type(value)!r} for the name of a node"
            raise self.name_token.error('XPTY0004', msg)

        eqname_match = EQNAME_PATTERN.fullmatch(str(value).strip())
        if eqname_match is not None:
            return '', collapse_white_spaces(eqname_match.group(1)), eqname_match.group(2)

        match = QNAME_PATTERN.fullmatch(str(value).strip())
        if match is None:
            raise self.name_token.error('XQDY0074', f"invalid QName {str(value)!r}")
        elif match.group(2) is None:
            return '', default_namespace, match.group(1)

        prefix, local_name = match.groups()
        try:
            return prefix, self.parser.namespaces[prefix], local_name
        except KeyError:
            msg = f"namespace prefix {prefix!r} is not declared"
            raise self.name_token.error('XQDY0074', msg) from None

    def get_ncname(self, context: ta.ContextType) -> str:
        assert self.name_token is not None
        value = self.get_single_atomic(self.name_token, context)
        if not isinstance(value, (str, UntypedAtomic)):
            msg = f"invalid type {type(value)!r} for an NCName"
            raise self.name_token.error('XPTY0004', msg)
        return str(value).strip()


class CompElementConstructor(ComputedConstructor):
    symbol = '(computed element)'
    label = 'element constructor'
    keyword = 'element'
    prefix: str = ''
    uri: str = ''

    def evaluate(self, context: ta.ContextType = None) -> ElementNode:
        if context is None:
            raise self.missing_context()

        builder = NodeTreeBuilder(context)
        try:
            elem = self.build(context, builder)
        except ValueError as err:
            if isinstance(err, ElementPathError):
                raise
            raise self.error('XQDY0074', err) from None  # e.g. names rejected by lxml
        return builder.get_node(elem, self.parser.base_uri)

    def build(self, context: ta.ContextType, builder: NodeTreeBuilder,
              parent: Any = None) -> Any:
        if self.name_token is None:
            prefix, uri, name = self.prefix, self.uri, self.name
        else:
            prefix, uri, name = self.get_qname(context, self.parser.default_namespace or '')
            if prefix == 'xmlns' or uri == XMLNS_NAMESPACE or \
                    (prefix == 'xml') is not (uri == XML_NAMESPACE):
                msg = f"invalid element name {name!r}"
                raise self.name_token.error('XQDY0096', msg)

        tag = f'{{{uri}}}{name}' if uri else name
        elem = builder.create_element(tag, {prefix: uri} if uri else {}, parent)
        if self.content_token is not None:
            elem, _ = self.add_enclosed_content(self.content_token, context, builder, elem, False)
        return elem


class CompAttributeConstructor(ComputedConstructor):
    symbol = '(computed attribute)'
    label = 'attribute constructor'
    keyword = 'attribute'
    uri: str = ''

    def evaluate(self, context: ta.ContextType = None) -> AttributeNode:
        if context is None:
            raise self.missing_context()

        if self.name_token is None:
            uri, name = self.uri, self.name
        else:
            prefix, uri, name = self.get_qname(context, '')
            if prefix == 'xmlns' or uri == XMLNS_NAMESPACE or \
                    not prefix and name == 'xmlns' or \
                    (prefix == 'xml') is not (uri == XML_NAMESPACE):
                msg = f"invalid attribute name {name!r}"
                raise self.name_token.error('XQDY0044', msg)

        value = ' '.join(self.atomized_strings(self.content_token, context) or ())
        name = f'{{{uri}}}{name}' if uri else name
        if name == XML_ID:
            value = collapse_white_spaces(value)
        return TextAttributeNode(name, value, position=reserve_positions(1))


class CompTextConstructor(ComputedConstructor):
    symbol = '(computed text)'
    label = 'text constructor'
    keyword = 'text'

    def evaluate(self, context: ta.ContextType = None) -> Union[TextNode, list[XPathNode]]:
        if context is None:
            raise self.missing_context()

        values = self.atomized_strings(self.content_token, context)
        if values is None:
            return []
        return TextNode(' '.join(values), position=reserve_positions(1))


class CompCommentConstructor(ComputedConstructor):
    symbol = '(computed comment)'
    label = 'comment constructor'
    keyword = 'comment'

    def evaluate(self, context: ta.ContextType = None) -> CommentNode:
        if context is None:
            raise self.missing_context()

        text = ' '.join(self.atomized_strings(self.content_token, context) or ())
        if '--' in text or text.endswith('-'):
            msg = "a comment cannot contain '--' or end with '-'"
            raise self.error('XQDY0072', msg)

        builder = NodeTreeBuilder(context)
        return CommentNode(builder.create_comment(text), position=reserve_positions(1))


class CompPIConstructor(ComputedConstructor):
    symbol = '(computed processing-instruction)'
    label = 'processing instruction constructor'
    keyword = 'processing-instruction'

    def evaluate(self, context: ta.ContextType = None) -> ProcessingInstructionNode:
        if context is None:
            raise self.missing_context()

        if self.name_token is None:
            target = self.name
        else:
            target = self.get_ncname(context)
            if NCNAME_PATTERN.fullmatch(target) is None:
                msg = f"invalid processing instruction target {target!r}"
                raise self.name_token.error('XQDY0041', msg)

        if target.lower() == 'xml':
            raise self.error('XQDY0064', f"invalid processing instruction target {target!r}")

        text = ' '.join(self.atomized_strings(self.content_token, context) or ())
        text = text.lstrip(' \t\r\n')
        if '?>' in text:
            raise self.error('XQDY0026', "processing instruction content cannot contain '?>'")

        builder = NodeTreeBuilder(context)
        return ProcessingInstructionNode(
            builder.create_pi(target, text), position=reserve_positions(1)
        )


class CompNamespaceConstructor(ComputedConstructor):
    symbol = '(computed namespace)'
    label = 'namespace constructor'
    keyword = 'namespace'

    def evaluate(self, context: ta.ContextType = None) -> NamespaceNode:
        if context is None:
            raise self.missing_context()

        if self.name_token is None:
            prefix = self.name
        else:
            prefix = self.get_ncname(context)
            if prefix and NCNAME_PATTERN.fullmatch(prefix) is None:
                raise self.name_token.error('XQDY0074', f"invalid prefix {prefix!r}")

        uri = ''.join(self.atomized_strings(self.content_token, context) or ())
        if prefix == 'xmlns' or uri == XMLNS_NAMESPACE or not uri or \
                (prefix == 'xml') is not (uri == XML_NAMESPACE):
            raise self.error('XQDY0101', f"invalid namespace binding {prefix!r} -> {uri!r}")

        return NamespaceNode(prefix, uri, position=reserve_positions(1))


class CompDocumentConstructor(ComputedConstructor):
    symbol = '(computed document)'
    label = 'document constructor'
    keyword = 'document'

    def evaluate(self, context: ta.ContextType = None) -> DocumentNode:
        if context is None:
            raise self.missing_context()

        builder = NodeTreeBuilder(context)
        elem = builder.create_element('document', {})
        if self.content_token is not None:
            elem, _ = self.add_enclosed_content(
                self.content_token, context, builder, elem, False, document=True
            )

        return builder.get_node(elem, self.parser.base_uri).get_document_node(replace=True)
