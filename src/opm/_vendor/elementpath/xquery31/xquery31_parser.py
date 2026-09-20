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
XQuery 3.1 implementation - part 1 (parser class)

Refs:
  - https://www.w3.org/TR/xquery-31/
"""
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
import re
from typing import TYPE_CHECKING, Any, ClassVar, Optional, Union, cast

from opm._vendor.elementpath.exceptions import MissingContextError, xpath_error
from opm._vendor.elementpath.helpers import is_xml_codepoint
from opm._vendor.elementpath.namespaces import XSI_NAMESPACE, XQUERY_LOCAL_FUNCTIONS_NAMESPACE
from opm._vendor.elementpath.xpath31 import XPath31Parser

if TYPE_CHECKING:
    from opm._vendor.elementpath.xpath_tokens import XPathToken
    from ._xquery31_prolog import ModuleRegistry, StaticModule

REFERENCE_PATTERN = re.compile(r'&(?:(lt|gt|amp|quot|apos)|#([0-9]+)|#x([0-9a-fA-F]+));|&')
PREDEFINED_ENTITIES = {'lt': '<', 'gt': '>', 'amp': '&', 'quot': '"', 'apos': "'"}


class ModuleBinding:
    """
    Base class of the values bound in the dynamic context by the evaluation of
    a query with a prolog, that are not XPath values (e.g. global variables not
    yet evaluated).
    """


class XQuery31Parser(XPath31Parser):
    """
    XQuery 3.1 expression parser class. Currently, it extends the XPath 3.1 parser
    with direct and computed node constructors, FLWOR expressions (except group by
    and window clauses), the query prolog and library modules. Accepts all XPath 3.1
    options as keyword arguments.

    :param boundary_space: the boundary-space policy of the static context, \
    can be 'strip' (the default) or 'preserve'.
    :param modules: an optional mapping from library module namespace URIs to \
    the modules to import for them. Each value is the source of a library module, \
    a file path, or a list of them. For namespaces not in the mapping the location \
    hints of the import are used, if allowed by *allow_external_resources*.
    :param kwargs: the same keyword arguments of class :class:`elementpath.XPath31Parser`.
    """
    version = '3.1'

    # https://www.w3.org/TR/xquery-31/#id-basics
    DEFAULT_NAMESPACES: ClassVar[dict[str, str]] = {
        'xsi': XSI_NAMESPACE,
        'local': XQUERY_LOCAL_FUNCTIONS_NAMESPACE,
        **XPath31Parser.DEFAULT_NAMESPACES
    }

    PATH_STEP_LABELS = (  # type: ignore[assignment]
        'axis', 'function', 'kind test', 'element constructor', 'attribute constructor',
        'text constructor', 'comment constructor', 'processing instruction constructor',
        'document constructor', 'namespace constructor',
    )
    PATH_STEP_SYMBOLS = {
        '(integer)', '(string)', '(float)', '(decimal)', '(name)',
        '*', '@', '..', '.', '(', '{', 'Q{', '$', '<',
    }

    boundary_space = 'strip'
    empty_order = 'least'
    modules: Optional[dict[str, Union[str, list[str]]]] = None
    module_registry: Optional['ModuleRegistry'] = None
    "The registry of the modules of a query, shared by the parsers of imported modules."
    current_module: Optional['StaticModule'] = None
    "The module being parsed, used for resolving calls of declared functions."

    def __init__(self, *args: Any, boundary_space: Optional[str] = None,
                 modules: Optional[dict[str, Union[str, list[str]]]] = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if boundary_space is not None:
            if boundary_space not in ('strip', 'preserve'):
                raise ValueError("boundary_space must be 'strip' or 'preserve'")
            self.boundary_space = boundary_space
        if modules is not None:
            self.modules = dict(modules)

    def parse(self, source: str) -> 'XPathToken':
        self.module_registry = None
        root_token = self.parse_module(source)
        if not isinstance(root_token, self.token_base_class):
            raise xpath_error('XPST0003', "a library module cannot be evaluated")
        elif root_token.label in ('sequence type', 'function test'):
            raise root_token.error('XPST0003', "not allowed in XQuery expression")

        try:
            root_token.evaluate()  # Static context evaluation
        except MissingContextError:
            pass

        if self.schema is not None:
            # Static evaluation using a schema context
            context = self.schema.get_context()
            for _ in root_token.select(context):
                pass

        return root_token

    def parse_module(self, source: str) -> Union['XPathToken', 'StaticModule']:
        """
        Parses the source of an XQuery module. Returns the root token of the query
        body for a main module, or the static module for a library module.
        """
        if self.tokenizer is None:
            self.tokenizer = self.create_tokenizer(self.symbol_table)

        try:
            try:
                self.tokens = iter(self.tokenizer.finditer(source))
            except TypeError as err:
                token = cast(Any, self.symbol_table['(invalid)'])(self, source)
                raise token.wrong_syntax(f'invalid source type, {err}')

            self.source = source
            self.advance()
            result = cast(Any, self.symbol_table['(module)'])(self).parse_module()
            self.next_token.expected('(end)')
            return cast(Union['XPathToken', 'StaticModule'], result)
        finally:
            self.tokens = iter(())
            self.next_match = None
            self.token = self.next_token = self._start_token

    def check_variables(self, values: MutableMapping[str, Any]) -> None:
        super().check_variables(
            {k: v for k, v in values.items() if not isinstance(v, ModuleBinding)}
        )

    @staticmethod
    def unescape(string_literal: str) -> str:
        """
        Unescapes an XQuery string literal: in addition to doubled delimiters,
        predefined entity references and character references are expanded.
        """
        value = XPath31Parser.unescape(string_literal)
        if '&' not in value:
            return value

        def replace(match: 're.Match[str]') -> str:
            entity, dec_ref, hex_ref = match.groups()
            if entity is not None:
                return PREDEFINED_ENTITIES[entity]
            elif dec_ref is None and hex_ref is None:
                msg = f"invalid entity reference in string literal {string_literal}"
                raise xpath_error('XPST0003', msg)

            codepoint = int(dec_ref) if dec_ref is not None else int(hex_ref, 16)
            if not is_xml_codepoint(codepoint):
                msg = f"character reference {match.group()!r} is not a valid XML character"
                raise xpath_error('XQST0090', msg)
            return chr(codepoint)

        return REFERENCE_PATTERN.sub(replace, value)

    @contextmanager
    def in_scope_namespaces(self, namespaces: dict[str, str]) -> Iterator[None]:
        """
        Temporarily replaces the statically known namespaces and the default element
        namespace of the parser, e.g. for parsing and evaluating the content of a
        direct element constructor that has namespace declaration attributes.
        """
        status = self.namespaces, self.default_namespace
        self.namespaces = namespaces
        self.default_namespace = namespaces.get('', self.default_namespace)
        try:
            yield
        finally:
            self.namespaces, self.default_namespace = status
