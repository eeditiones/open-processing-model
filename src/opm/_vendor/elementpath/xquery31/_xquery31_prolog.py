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
XQuery 3.1 implementation - part 4 (prolog, declared functions and library modules)

Schema imports and external functions are not supported.

Refs:
  - https://www.w3.org/TR/xquery-31/#id-query-prolog
  - https://www.w3.org/TR/xquery-31/#id-module-import
"""
import re
from collections.abc import Iterator
from copy import copy
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Union, cast
from urllib.parse import urljoin
from urllib.request import urlopen

import opm._vendor.elementpath.aliases as ta

from opm._vendor.elementpath.collations import CollationManager
from opm._vendor.elementpath.datatypes import QName
from opm._vendor.elementpath.exceptions import ElementPathError
from opm._vendor.elementpath.helpers import collapse_white_spaces, is_allowed_uri, split_function_test
from opm._vendor.elementpath.namespaces import XML_NAMESPACE, XMLNS_NAMESPACE, XSD_NAMESPACE, \
    XSI_NAMESPACE, XPATH_FUNCTIONS_NAMESPACE, XPATH_MATH_FUNCTIONS_NAMESPACE, \
    XPATH_MAP_FUNCTIONS_NAMESPACE, XPATH_ARRAY_FUNCTIONS_NAMESPACE
from opm._vendor.elementpath.sequences import xlist
from opm._vendor.elementpath.sequence_types import match_sequence_type
from opm._vendor.elementpath.xpath_context import XPathContext, XPathSchemaContext
from opm._vendor.elementpath.xpath_nodes import XPathNode, DocumentNode
from opm._vendor.elementpath.xpath_tokens import XPathToken, XPathFunction, NameToken

from ._constructor_tokens import NCNAME
from ._xquery31_constructors import _SPACES
from ._xquery31_flwor import XQuery31Parser, is_keyword, parse_type_declaration
from .xquery31_parser import ModuleBinding

__all__ = ['XQuery31Parser', 'ModuleRegistry', 'StaticModule']

XQUERY_NAMESPACE = 'http://www.w3.org/2012/xquery'
XQUERY_OPTIONS_NAMESPACE = 'http://www.w3.org/2011/xquery-options'

RESERVED_FUNCTION_NAMESPACES = frozenset((
    XML_NAMESPACE, XSD_NAMESPACE, XSI_NAMESPACE, XPATH_FUNCTIONS_NAMESPACE,
    XPATH_MATH_FUNCTIONS_NAMESPACE, XPATH_MAP_FUNCTIONS_NAMESPACE,
    XPATH_ARRAY_FUNCTIONS_NAMESPACE,
))

_KEYWORD_END = r'(?![\w.\-\u00B7\u0300-\u036F\u203F\u2040:])'
EQNAME_PATTERN = re.compile(rf'Q\{{[^{{}}]*\}}{NCNAME}|{NCNAME}(?::{NCNAME})?')
VERSION_DECL_PATTERN = re.compile(rf'{_SPACES}(?:version|encoding){_KEYWORD_END}')
MODULE_DECL_PATTERN = re.compile(rf'{_SPACES}namespace{_KEYWORD_END}')
IMPORT_PATTERN = re.compile(rf'{_SPACES}(?:module|schema){_KEYWORD_END}')
DECLARE_PATTERN = re.compile(
    rf'{_SPACES}(?:%|(?:namespace|default|variable|function|context|option|'
    rf'boundary-space|base-uri|ordering|copy-namespaces|construction|'
    rf'decimal-format){_KEYWORD_END})'
)
ENCODING_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9._\-]*')
LIBRARY_SOURCE_PATTERN = re.compile(r'\bmodule\s+namespace\b')

DECIMAL_FORMAT_PROPERTIES = frozenset((
    'decimal-separator', 'grouping-separator', 'infinity', 'minus-sign', 'NaN',
    'percent', 'per-mille', 'zero-digit', 'digit', 'pattern-separator',
    'exponent-separator',
))

MODULE_STATE_KEY = '(module state)'
"Key of the dynamic context variables that links the evaluation state of a query."


class VariableDecl:
    """A declared global variable."""

    def __init__(self, name: str, lexical_name: str, sequence_type: Optional[str],
                 expr: Optional[XPathToken], external: bool, private: bool,
                 module: 'StaticModule', token: XPathToken) -> None:
        self.name = name
        self.lexical_name = lexical_name
        self.sequence_type = sequence_type
        self.expr = expr
        self.external = external
        self.private = private
        self.module = module
        self.token = token


class ContextItemDecl:
    """A context item declaration of a main module."""

    def __init__(self, sequence_type: Optional[str], expr: Optional[XPathToken],
                 external: bool, token: XPathToken) -> None:
        self.sequence_type = sequence_type
        self.expr = expr
        self.external = external
        self.token = token


class FunctionDecl:
    """A declared function."""

    def __init__(self, name: str, lexical_name: str, params: list[str],
                 param_types: list[str], return_type: str,
                 body: Optional[XPathToken], private: bool,
                 module: 'StaticModule', token: XPathToken) -> None:
        self.name = name
        self.lexical_name = lexical_name
        self.params = params
        self.param_types = param_types
        self.return_type = return_type
        self.body = body
        self.private = private
        self.module = module
        self.token = token

    @property
    def sequence_types(self) -> tuple[str, ...]:
        return *self.param_types, self.return_type

    def call(self, args: list[Any], context: XPathContext, token: XPathToken) -> Any:
        """Calls the function with argument values, in a new focus-free context."""
        state = context.variables.get(MODULE_STATE_KEY)
        if isinstance(state, ModuleState):
            context = copy(state.context)
            variables = dict(state.context.variables)
        else:
            context = copy(context)
            variables = {}

        context.item = None  # type: ignore[assignment]
        context.position = context.size = 1
        for name, sequence_type, value in zip(self.params, self.param_types, args):
            variables[name] = convert_value(token, value, sequence_type, f'${name}')
        context.variables = variables

        if self.body is None:
            return []
        result = self.body.evaluate(context)
        return convert_value(token, result, self.return_type, 'result')


class StaticModule:
    """The static part of an XQuery module: its declarations and imports."""

    def __init__(self, parser: XQuery31Parser, uri: Optional[str] = None) -> None:
        self.parser = parser
        self.uri = uri
        self.variables: dict[str, VariableDecl] = {}
        self.functions: dict[tuple[str, int], FunctionDecl] = {}
        self.imports: dict[str, list[StaticModule]] = {}
        self.context_item: Optional[ContextItemDecl] = None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(uri={self.uri!r})'

    def iter_imported_modules(self, uri: Optional[str] = None) -> Iterator['StaticModule']:
        if uri is None:
            for modules in self.imports.values():
                yield from modules
        else:
            yield from self.imports.get(uri, ())

    def find_function(self, name: str, arity: int) -> Optional[FunctionDecl]:
        """Finds a function visible from the module, by expanded name and arity."""
        decl = self.functions.get((name, arity))
        if decl is not None:
            return decl

        uri = name[1:name.index('}')] if name.startswith('{') else ''
        for module in self.iter_imported_modules(uri):
            decl = module.functions.get((name, arity))
            if decl is not None and not decl.private:
                return decl
        return None


class ModuleRegistry:
    """The modules of a query, shared by the parsers of all its modules."""

    def __init__(self) -> None:
        self.modules: dict[str, list[StaticModule]] = {}
        self.function_calls: list[DeclaredFunction] = []

    def iter_modules(self, main: StaticModule) -> Iterator[StaticModule]:
        yield main
        for modules in self.modules.values():
            yield from modules

    def iter_variables(self, main: StaticModule) -> Iterator[VariableDecl]:
        for module in self.iter_modules(main):
            yield from module.variables.values()

    def find_function(self, main: StaticModule, name: str, arity: int) \
            -> Optional[FunctionDecl]:
        decl = main.find_function(name, arity)
        if decl is not None:
            return decl
        for modules in self.modules.values():
            for module in modules:
                decl = module.functions.get((name, arity))
                if decl is not None and not decl.private:
                    return decl
        return None


###
# Dynamic evaluation of global variables and functions

class ModuleState(ModuleBinding):
    """The evaluation state of a query, linked to its dynamic context."""
    context: XPathContext

    def __init__(self, registry: ModuleRegistry, main: StaticModule) -> None:
        self.registry = registry
        self.main = main


class GlobalVariable(ModuleBinding):
    """A global variable in the dynamic context, evaluated on first reference."""
    _pending, _evaluating, _evaluated = range(3)

    def __init__(self, decl: VariableDecl, state: ModuleState) -> None:
        self.decl = decl
        self.state = state
        self.status = self._pending
        self.value: Any = None

    def get_value(self, token: XPathToken) -> Any:
        if self.status == self._evaluated:
            return self.value
        elif self.status == self._evaluating:
            msg = f"circular dependency in the initialization of ${self.decl.lexical_name}"
            raise token.error('XQDY0054', msg)

        decl = self.decl
        if decl.expr is None:
            msg = f"no value provided for external variable ${decl.lexical_name}"
            raise decl.token.error('XPDY0002', msg)

        self.status = self._evaluating
        try:
            context = copy(self.state.context)
            if decl.module is not self.state.main:
                context.item = None  # type: ignore[assignment]
            value = decl.expr.evaluate(context)
            check_variable_type(decl.token, value, decl.sequence_type, decl.lexical_name)
        except BaseException:
            self.status = self._pending
            raise

        self.value = value
        self.status = self._evaluated
        return value


def check_variable_type(token: XPathToken, value: Any, sequence_type: Optional[str],
                        name: str) -> None:
    if sequence_type is not None and not match_sequence_type(value, sequence_type, token.parser):
        msg = f"${name}: {value!r} does not match sequence type {sequence_type}"
        raise token.error('XPTY0004', msg)


def convert_value(token: XPathToken, value: Any, sequence_type: str, name: str) -> Any:
    """Applies the function conversion rules to an argument or to a result."""
    if sequence_type == 'item()*':
        return value
    elif isinstance(value, XPathFunction) and sequence_type.startswith('function('):
        # Function coercion: the types of arguments and result are checked by calls
        sequence_types = split_function_test(sequence_type)
        if sequence_types and (sequence_types[0] == '*' or
                               len(sequence_types) - 1 == value.arity):
            return value
    elif match_sequence_type(value, sequence_type, token.parser):
        return value
    elif sequence_type.startswith('xs:'):
        items = value if isinstance(value, list) else [] if value is None else [value]
        values = []
        for item in items:
            for v in token.atomize_item(item):
                if sequence_type.startswith(('xs:double', 'xs:float')) and \
                        isinstance(v, (int, Decimal)) and not isinstance(v, bool):
                    v = float(v)
                values.append(v)

        converted = values[0] if len(values) == 1 else xlist(values)
        converted = token.cast_to_primitive_type(converted, sequence_type)
        if match_sequence_type(converted, sequence_type, token.parser):
            return converted

    msg = f"{name}: {value!r} does not match sequence type {sequence_type}"
    raise token.error('XPTY0004', msg)


class DeclaredFunction(XPathFunction):
    """
    A call of a declared function, or a function item for a declared function.
    Calls are resolved when all the modules of a query are parsed.
    """
    symbol = lookup_name = '(declared function)'
    label = 'function'
    lbp = rbp = 90

    declaration: Optional[FunctionDecl] = None
    module: Optional[StaticModule] = None
    call_arity: int = 0

    def __init__(self, parser: ta.XPathParserType, name: str, lexical_name: str,
                 nargs: Optional[int] = None) -> None:
        super().__init__(parser, nargs)
        self.name = name
        self.lexical_name = lexical_name
        uri = name[1:name.index('}')] if name.startswith('{') else None
        self.namespace = uri
        local_name = lexical_name[lexical_name.index('}') + 1:] \
            if lexical_name.startswith('Q{') else lexical_name
        self._qname = QName(uri, local_name)

    def __str__(self) -> str:
        return f'{self.lexical_name!r} function'

    @property
    def source(self) -> str:
        return f"{self.lexical_name}({', '.join(t.source for t in self)}){self.occurrence}"

    def resolve(self, decl: FunctionDecl) -> None:
        self.declaration = decl
        self.sequence_types = decl.sequence_types

    def evaluate(self, context: ta.ContextType = None) -> ta.ValueType:
        if context is None:
            raise self.missing_context()

        decl = self.declaration
        assert decl is not None, "unresolved function call"
        if isinstance(context, XPathSchemaContext):
            for tk in self:
                tk.evaluate(context)
            return []

        # The placeholders of a partial function have the value of the arguments
        args = [tk.value if tk.symbol == '?' and not tk else tk.evaluate(context)
                for tk in self]
        return cast(ta.ValueType, decl.call(args, context, self))


###
# Module and prolog parsing

class XQueryModule(XPathToken):
    """
    A token for parsing an XQuery module. For a main module with declarations
    or imports it's also the root token of the query.
    """
    symbol = lookup_name = '(module)'
    label = 'module'
    raw_source: str = ''
    body: XPathToken
    static_module: StaticModule
    module_registry: ModuleRegistry

    def __str__(self) -> str:
        return f'XQuery module {self.raw_source!r}'

    @property
    def source(self) -> str:
        return self.raw_source

    @property
    def tree(self) -> str:
        return f'({self.symbol} {self.raw_source})'

    def nud(self) -> XPathToken:
        return self

    def evaluate(self, context: ta.ContextType = None) -> ta.ValueType:
        return self.body.evaluate(self.get_module_context(context))

    def select(self, context: ta.ContextType = None) -> Iterator[ta.ItemType]:
        yield from self.body.select(self.get_module_context(context))

    def get_results(self, context: ta.ContextType) -> \
            'list[ta.ResultType] | ta.AtomicType | XPathFunction':
        return self.body.get_results(self.get_module_context(context))

    def get_module_context(self, context: ta.ContextType) -> XPathContext:
        if context is None:
            self.body.evaluate()  # static evaluation
            raise self.missing_context()

        state = ModuleState(self.module_registry, self.static_module)
        caller_variables = context.variables
        context = copy(context)
        variables: dict[str, Any] = dict(caller_variables)
        variables[MODULE_STATE_KEY] = state

        for decl in self.module_registry.iter_variables(self.static_module):
            for key in (decl.name, decl.lexical_name):
                if decl.external and key in caller_variables:
                    value = caller_variables[key]
                    check_variable_type(decl.token, value, decl.sequence_type,
                                        decl.lexical_name)
                    variables[decl.name] = value
                    break
            else:
                variables[decl.name] = GlobalVariable(decl, state)

        context.variables = variables
        state.context = context

        item_decl = self.static_module.context_item
        if item_decl is not None and not isinstance(context, XPathSchemaContext):
            if item_decl.expr is not None and not (item_decl.external and context.item is not None):
                item_context = copy(context)
                item_context.item = None  # type: ignore[assignment]
                value = item_decl.expr.evaluate(item_context)
                if isinstance(value, list):
                    if len(value) != 1:
                        msg = "the context item must be a single item"
                        raise item_decl.token.error('XPTY0004', msg)
                    value = value[0]
                context.item = value
                if isinstance(value, XPathNode):
                    context.root = cast(ta.RootNodeType, value.root_node)
                    context.document = value.root_node \
                        if isinstance(value.root_node, DocumentNode) else None

        if context.item is not None and not isinstance(context, XPathSchemaContext):
            for module in self.module_registry.iter_modules(self.static_module):
                module_decl = module.context_item
                if module_decl is not None and module_decl.sequence_type is not None and \
                        not match_sequence_type(context.item, module_decl.sequence_type,
                                                self.parser):
                    msg = "the context item does not match sequence type " \
                          f"{module_decl.sequence_type}"
                    raise module_decl.token.error('XPTY0004', msg)

        return context

    def parse_module(self) -> Union[XPathToken, StaticModule]:
        parser = cast(XQuery31Parser, self.parser)
        source = parser.source
        is_main_parser = parser.module_registry is None
        if parser.module_registry is None:
            parser.module_registry = ModuleRegistry()
        registry = parser.module_registry

        module = StaticModule(parser)
        parser.current_module = module
        prolog = PrologParser(self, module)

        next_token = parser.next_token
        if is_keyword(next_token, 'xquery') and \
                VERSION_DECL_PATTERN.match(source, next_token.span[1]):
            prolog.parse_version_declaration()
            parser.advance(';')

        next_token = parser.next_token
        if is_keyword(next_token, 'module') and \
                MODULE_DECL_PATTERN.match(source, next_token.span[1]):
            prolog.parse_module_declaration()
            parser.advance(';')

        while True:
            next_token = parser.next_token
            if is_keyword(next_token, 'declare') and \
                    DECLARE_PATTERN.match(source, next_token.span[1]):
                parser.advance()
                prolog.parse_declaration()
            elif is_keyword(next_token, 'import') and \
                    IMPORT_PATTERN.match(source, next_token.span[1]):
                parser.advance()
                prolog.parse_import()
            else:
                break
            parser.advance(';')

        if module.uri is not None:
            if prolog.unsupported is not None:
                raise prolog.unsupported
            return module

        body = parser.expression()
        if body.label in ('sequence type', 'function test'):
            raise body.error('XPST0003', "not allowed in XQuery expression")
        elif prolog.unsupported is not None:
            raise prolog.unsupported

        if is_main_parser:
            for call in registry.function_calls:
                assert call.module is not None
                decl = call.module.find_function(call.name, call.call_arity)
                if decl is None:
                    msg = f"unknown function {call.lexical_name}#{call.call_arity}"
                    raise call.error('XPST0017', msg)
                call.resolve(decl)

        if not module.variables and not module.functions and \
                not module.imports and module.context_item is None:
            return body

        self.body = body
        self.static_module = module
        self.module_registry = registry
        self[:] = body,
        self.span = (0, len(source))
        self.raw_source = source
        return self


class PrologParser:
    """Parses the declarations of a module prolog into a static module."""

    def __init__(self, token: XQueryModule, module: StaticModule) -> None:
        self.token = token
        self.parser = cast(XQuery31Parser, token.parser)
        self.module = module
        self.declared: set[str] = set()
        self.namespace_prefixes: set[str] = set()
        self.decimal_formats: set[Optional[str]] = set()
        self.first_part = True
        self.unsupported: Optional[ElementPathError] = None
        "An error for a feature not supported, raised if the module has no syntax errors."

    def check_setter(self, name: str, code: str, token: XPathToken) -> None:
        if not self.first_part:
            msg = f"{name} declaration after variable, function or option declarations"
            raise token.error('XPST0003', msg)
        elif name in self.declared:
            raise token.error(code, f"multiple {name} declarations")
        self.declared.add(name)

    def check_first_part(self, token: XPathToken) -> None:
        if not self.first_part:
            msg = "import and namespace declarations must precede variable, " \
                  "function and option declarations"
            raise token.error('XPST0003', msg)

    def read_eqname(self) -> tuple[str, XPathToken]:
        parser = self.parser
        token = parser.next_token
        match = EQNAME_PATTERN.match(parser.source, token.span[0])
        if match is None:
            raise token.wrong_syntax()
        parser.seek(match.end())
        return match.group(), token

    def read_ncname(self) -> tuple[str, XPathToken]:
        name, token = self.read_eqname()
        if ':' in name or name.startswith('Q{'):
            raise token.wrong_syntax(f"{name!r} is not an NCName")
        return name, token

    def read_keyword(self, *names: str) -> str:
        next_token = self.parser.next_token
        if next_token.symbol != '(name)' or next_token.value not in names:
            raise next_token.wrong_syntax()
        self.parser.advance()
        return str(next_token.value)

    def read_string(self) -> str:
        return str(self.parser.advance('(string)').value)

    def resolve_name(self, name: str, default_uri: str, token: XPathToken) \
            -> tuple[str, str]:
        """Returns the expanded name and the namespace URI of a lexical EQName."""
        if name.startswith('Q{'):
            uri, _, local_name = name[2:].partition('}')
            uri = collapse_white_spaces(uri)
        elif ':' in name:
            prefix, local_name = name.split(':')
            try:
                uri = self.parser.namespaces[prefix]
            except KeyError:
                raise token.error('XPST0081', f"prefix {prefix!r} is not declared") from None
        else:
            uri, local_name = default_uri, name

        return (f'{{{uri}}}{local_name}' if uri else local_name), uri

    def parse_version_declaration(self) -> None:
        parser = self.parser
        parser.advance()
        if is_keyword(parser.next_token, 'version'):
            parser.advance()
            version = self.read_string()
            if version not in ('1.0', '3.0', '3.1'):
                raise parser.token.error('XQST0031', f"unsupported version {version!r}")

        if is_keyword(parser.next_token, 'encoding'):
            parser.advance()
            encoding = self.read_string()
            if ENCODING_PATTERN.fullmatch(encoding) is None:
                raise parser.token.error('XQST0087', f"invalid encoding {encoding!r}")
        elif parser.token.symbol != '(string)':
            raise parser.next_token.wrong_syntax()

    def parse_module_declaration(self) -> None:
        parser = self.parser
        parser.advance()
        self.read_keyword('namespace')
        prefix, token = self.read_ncname()
        parser.advance('=')
        uri = collapse_white_spaces(self.read_string())

        if prefix in ('xml', 'xmlns'):
            raise token.error('XQST0070', f"prefix {prefix!r} cannot be declared")
        elif not uri:
            raise parser.token.error('XQST0088', "empty target namespace of a library module")
        elif uri in (XML_NAMESPACE, XMLNS_NAMESPACE):
            raise parser.token.error('XQST0070', f"namespace {uri!r} cannot be declared")

        self.module.uri = uri
        parser.namespaces[prefix] = uri
        self.namespace_prefixes.add(prefix)

        assert parser.module_registry is not None
        parser.module_registry.modules.setdefault(uri, []).append(self.module)

    def parse_declaration(self) -> None:
        parser = self.parser
        declare_token = parser.token
        private, duplicate = self.parse_annotations()
        keyword = parser.next_token
        if private is not None and not is_keyword(keyword, 'variable') and \
                not is_keyword(keyword, 'function'):
            raise keyword.wrong_syntax()
        elif duplicate is not None:
            msg = "multiple %public or %private annotations"
            code = 'XQST0116' if is_keyword(keyword, 'variable') else 'XQST0106'
            raise duplicate.error(code, msg)

        name = self.read_keyword(
            'namespace', 'default', 'variable', 'function', 'context', 'option',
            'boundary-space', 'base-uri', 'ordering', 'copy-namespaces',
            'construction', 'decimal-format'
        )
        if name == 'namespace':
            self.parse_namespace_declaration()
        elif name == 'default':
            self.parse_default_declaration()
        elif name == 'variable':
            self.first_part = False
            self.parse_variable_declaration(bool(private))
        elif name == 'function':
            self.first_part = False
            self.parse_function_declaration(bool(private))
        elif name == 'context':
            self.first_part = False
            self.parse_context_item_declaration()
        elif name == 'option':
            self.first_part = False
            option_name, token = self.read_eqname()
            self.resolve_name(option_name, XQUERY_OPTIONS_NAMESPACE, token)
            self.read_string()
        elif name == 'boundary-space':
            self.check_setter(name, 'XQST0068', declare_token)
            parser.boundary_space = self.read_keyword('preserve', 'strip')
        elif name == 'base-uri':
            self.check_setter(name, 'XQST0032', declare_token)
            uri = collapse_white_spaces(self.read_string())
            parser.base_uri = urljoin(parser.base_uri, uri) if parser.base_uri else uri
        elif name == 'ordering':
            self.check_setter(name, 'XQST0065', declare_token)
            self.read_keyword('ordered', 'unordered')
        elif name == 'copy-namespaces':
            self.check_setter(name, 'XQST0055', declare_token)
            self.read_keyword('preserve', 'no-preserve')
            parser.advance(',')
            self.read_keyword('inherit', 'no-inherit')
        elif name == 'construction':
            self.check_setter(name, 'XQST0067', declare_token)
            self.read_keyword('strip', 'preserve')
        else:
            self.parse_decimal_format_declaration(None, declare_token)

    def parse_annotations(self) -> tuple[Optional[bool], Optional[XPathToken]]:
        """
        Parses the annotations of a declaration. Returns the visibility and the
        token of a duplicate %public or %private annotation, if any.
        """
        parser = self.parser
        private = None
        duplicate = None
        while parser.next_token.symbol == '%':
            parser.advance('%')
            name, token = self.read_eqname()
            _, uri = self.resolve_name(name, XQUERY_NAMESPACE, token)
            if uri == XQUERY_NAMESPACE:
                local_name = name.rpartition(':')[2].rpartition('}')[2]
                if local_name not in ('public', 'private'):
                    raise token.error('XQST0045', f"unknown annotation %{name}")
                elif private is not None:
                    duplicate = duplicate or token
                private = local_name == 'private'
            elif uri in RESERVED_FUNCTION_NAMESPACES:
                raise token.error('XQST0045', f"annotation %{name} is in a reserved namespace")

            if parser.next_token.symbol == '(':
                parser.advance('(')
                while True:
                    if parser.next_token.symbol == '-':
                        parser.advance()
                    parser.advance('(string)', '(integer)', '(decimal)', '(float)')
                    if parser.next_token.symbol != ',':
                        break
                    parser.advance(',')
                parser.advance(')')

        return private, duplicate

    def parse_namespace_declaration(self) -> None:
        parser = self.parser
        self.check_first_part(parser.token)
        prefix, token = self.read_ncname()
        parser.advance('=')
        uri = collapse_white_spaces(self.read_string())

        if prefix in ('xml', 'xmlns'):
            raise token.error('XQST0070', f"prefix {prefix!r} cannot be declared")
        elif uri in (XML_NAMESPACE, XMLNS_NAMESPACE):
            raise parser.token.error('XQST0070', f"namespace {uri!r} cannot be declared")
        elif prefix in self.namespace_prefixes:
            raise token.error('XQST0033', f"multiple declarations of prefix {prefix!r}")

        self.namespace_prefixes.add(prefix)
        if uri:
            parser.namespaces[prefix] = uri
        else:
            parser.namespaces.pop(prefix, None)

    def parse_default_declaration(self) -> None:
        parser = self.parser
        declare_token = parser.token
        name = self.read_keyword('element', 'function', 'collation', 'order', 'decimal-format')

        if name in ('element', 'function'):
            self.check_first_part(declare_token)
            if name in self.declared:
                raise declare_token.error('XQST0066', f"multiple default {name} namespaces")
            self.declared.add(name)
            self.read_keyword('namespace')
            uri = collapse_white_spaces(self.read_string())
            if uri in (XML_NAMESPACE, XMLNS_NAMESPACE):
                raise parser.token.error('XQST0070', f"namespace {uri!r} cannot be declared")

            if name == 'function':
                parser.function_namespace = uri
            else:
                parser.default_namespace = uri
                if uri:
                    parser.namespaces[''] = uri
                else:
                    parser.namespaces.pop('', None)

        elif name == 'collation':
            self.check_setter('default collation', 'XQST0038', declare_token)
            collation = collapse_white_spaces(self.read_string())
            if parser.base_uri:
                collation = urljoin(parser.base_uri, collation)
            try:
                with CollationManager(collation, token=parser.token):
                    pass
            except ElementPathError:
                msg = f"unsupported collation {collation!r}"
                raise parser.token.error('XQST0038', msg) from None
            parser.default_collation = collation

        elif name == 'order':
            self.check_setter('empty order', 'XQST0069', declare_token)
            self.read_keyword('empty')
            parser.empty_order = self.read_keyword('greatest', 'least')
        else:
            self.parse_decimal_format_declaration('', declare_token)

    def parse_decimal_format_declaration(self, name: Optional[str],
                                         declare_token: XPathToken) -> None:
        parser = self.parser
        self.check_first_part(declare_token)
        if name is None:
            lexical_name, token = self.read_eqname()
            name, _ = self.resolve_name(lexical_name, '', token)

        key = name or None
        if key in self.decimal_formats:
            raise declare_token.error('XQST0111', "multiple declarations of a decimal format")
        self.decimal_formats.add(key)

        decimal_format = parser.__class__.decimal_formats[None].copy()
        properties = set()
        while parser.next_token.symbol == '(name)' and \
                parser.next_token.value in DECIMAL_FORMAT_PROPERTIES:
            property_name = str(parser.advance().value)
            if property_name in properties:
                msg = f"multiple declarations of property {property_name!r}"
                raise parser.token.error('XQST0114', msg)
            properties.add(property_name)
            parser.advance('=')
            decimal_format[property_name] = self.read_string()

        if parser.decimal_formats is parser.__class__.decimal_formats:
            parser.decimal_formats = {k: v.copy() for k, v in parser.decimal_formats.items()}
        parser.decimal_formats[key] = decimal_format

    def parse_variable_declaration(self, private: bool) -> None:
        parser = self.parser
        module = self.module
        parser.advance('$')
        lexical_name, token = self.read_eqname()
        name, uri = self.resolve_name(lexical_name, '', token)

        if module.uri is not None and uri != module.uri:
            msg = f"variable ${lexical_name} is not in the library module namespace"
            raise token.error('XQST0048', msg)
        elif name in module.variables or \
                any(name in m.variables for m in module.iter_imported_modules()):
            raise token.error('XQST0049', f"multiple declarations of variable ${lexical_name}")

        sequence_type = parse_type_declaration(self.token)
        expr = None
        external = is_keyword(parser.next_token, 'external')
        if external:
            parser.advance()
            if parser.next_token.symbol == ':=':
                parser.advance()
                expr = parser.expression(5)
        else:
            parser.advance(':=')
            expr = parser.expression(5)

        module.variables[name] = VariableDecl(
            name, lexical_name, sequence_type, expr, external, private, module, token
        )

    def parse_function_declaration(self, private: bool) -> None:
        parser = self.parser
        module = self.module
        lexical_name, token = self.read_eqname()
        parser.next_token.expected('(')
        name, uri = self.resolve_name(lexical_name, parser.function_namespace, token)

        if lexical_name in parser.RESERVED_FUNCTION_NAMES:
            raise token.error('XPST0003', f"{lexical_name!r} is a reserved function name")
        elif not uri:
            raise token.error('XQST0060', f"function {lexical_name!r} has no namespace")
        elif uri in RESERVED_FUNCTION_NAMESPACES:
            msg = f"function {lexical_name!r} is declared in a reserved namespace"
            raise token.error('XQST0045', msg)
        elif module.uri is not None and uri != module.uri:
            msg = f"function {lexical_name!r} is not in the library module namespace"
            raise token.error('XQST0048', msg)

        params: list[str] = []
        param_types: list[str] = []
        parser.advance('(')
        while parser.next_token.symbol != ')':
            parser.advance('$')
            param_name, param_token = self.read_eqname()
            param_name, _ = self.resolve_name(param_name, '', param_token)
            if param_name in params:
                raise param_token.error('XQST0039', f"duplicate parameter ${param_name}")
            params.append(param_name)
            param_types.append(parse_type_declaration(self.token) or 'item()*')

            if parser.next_token.symbol != ',':
                break
            parser.advance(',')
        parser.advance(')')

        return_type = parse_type_declaration(self.token) or 'item()*'
        if is_keyword(parser.next_token, 'external'):
            raise parser.next_token.error('XPST0003', "external functions are not supported")

        parser.advance('{')
        body = None if parser.next_token.symbol == '}' else parser.expression()
        parser.advance('}')

        key = name, len(params)
        if key in module.functions or \
                any(key in m.functions for m in module.iter_imported_modules(uri)):
            msg = f"multiple declarations of function {lexical_name}#{len(params)}"
            raise token.error('XQST0034', msg)

        module.functions[key] = FunctionDecl(
            name, lexical_name, params, param_types, return_type, body, private, module, token
        )

    def parse_context_item_declaration(self) -> None:
        parser = self.parser
        token = parser.token
        self.read_keyword('item')
        if self.module.context_item is not None:
            raise token.error('XQST0099', "multiple context item declarations")

        sequence_type = parse_type_declaration(self.token)
        if sequence_type is not None and sequence_type[-1] in '?*+' and \
                not sequence_type.endswith(')'):
            msg = "the type of a context item declaration cannot have an occurrence indicator"
            raise parser.token.error('XPST0003', msg)

        expr = None
        external = is_keyword(parser.next_token, 'external')
        if external:
            parser.advance()
            if parser.next_token.symbol == ':=':
                parser.advance()
                expr = parser.expression(5)
        else:
            parser.advance(':=')
            expr = parser.expression(5)

        if self.module.uri is not None and expr is not None:
            msg = "a context item declaration in a library module cannot have a value"
            raise token.error('XQST0113', msg)
        self.module.context_item = ContextItemDecl(sequence_type, expr, external, token)

    def parse_import(self) -> None:
        parser = self.parser
        import_token = parser.token
        self.check_first_part(import_token)
        if is_keyword(parser.next_token, 'schema'):
            self.parse_schema_import()
            return
        self.read_keyword('module')

        prefix = None
        if is_keyword(parser.next_token, 'namespace'):
            parser.advance()
            prefix, prefix_token = self.read_ncname()
            if prefix in ('xml', 'xmlns'):
                raise prefix_token.error('XQST0070', f"prefix {prefix!r} cannot be declared")
            elif prefix in self.namespace_prefixes:
                msg = f"multiple declarations of prefix {prefix!r}"
                raise prefix_token.error('XQST0033', msg)
            parser.advance('=')

        uri = collapse_white_spaces(self.read_string())
        uri_token = parser.token
        if not uri:
            raise uri_token.error('XQST0088', "empty namespace in a module import")
        elif uri in self.module.imports:
            raise uri_token.error('XQST0047', f"multiple imports of module {uri!r}")

        locations = []
        if is_keyword(parser.next_token, 'at'):
            parser.advance()
            while True:
                locations.append(collapse_white_spaces(self.read_string()))
                if parser.next_token.symbol != ',':
                    break
                parser.advance(',')

        self.module.imports[uri] = load_modules(parser, uri, locations, uri_token)
        if prefix is not None:
            self.namespace_prefixes.add(prefix)
            parser.namespaces[prefix] = uri

    def parse_schema_import(self) -> None:
        parser = self.parser
        token = parser.advance()
        if is_keyword(parser.next_token, 'namespace'):
            parser.advance()
            self.read_ncname()
            parser.advance('=')
        elif is_keyword(parser.next_token, 'default'):
            parser.advance()
            self.read_keyword('element')
            self.read_keyword('namespace')

        self.read_string()
        if is_keyword(parser.next_token, 'at'):
            parser.advance()
            while True:
                self.read_string()
                if parser.next_token.symbol != ',':
                    break
                parser.advance(',')

        if self.unsupported is None:
            self.unsupported = token.error('XQST0009', "schema import is not supported")


def load_modules(parser: XQuery31Parser, uri: str, locations: list[str],
                 token: XPathToken) -> list[StaticModule]:
    """Loads the library modules of a namespace, parsing them if not already loaded."""
    registry = parser.module_registry
    assert registry is not None
    if uri in registry.modules:
        return registry.modules[uri]

    sources: list[tuple[str, Optional[str]]] = []
    items = parser.modules.get(uri) if parser.modules else None
    try:
        if items is not None:
            for item in [items] if isinstance(items, str) else items:
                if LIBRARY_SOURCE_PATTERN.search(item):
                    sources.append((item, parser.base_uri))
                else:
                    path = Path(item)
                    sources.append((path.read_text(encoding='utf-8'), path.resolve().as_uri()))
        else:
            for location in locations:
                url = urljoin(parser.base_uri, location) if parser.base_uri else location
                if not is_allowed_uri(url, parser.allow_external_resources):
                    msg = f"access to module location {url!r} is not allowed"
                    raise token.error('XQST0059', msg)
                with urlopen(url) as fp:
                    sources.append((fp.read().decode('utf-8'), url))
    except (OSError, ValueError) as err:
        raise token.error('XQST0059', f"cannot load module {uri!r}: {err}") from None

    if not sources:
        raise token.error('XQST0059', f"cannot locate a module for namespace {uri!r}")

    modules = registry.modules[uri] = []
    for source, base_uri in sources:
        module_parser = parser.__class__(
            xsd_version=parser.xsd_version,
            compatibility_mode=parser.compatibility_mode,
            base_uri=base_uri,
            defuse_xml=parser.defuse_xml,
            allow_environment=parser.allow_environment,
            allow_external_resources=parser.allow_external_resources,
            modules=parser.modules,
        )
        module_parser.module_registry = registry
        module = module_parser.parse_module(source)
        if not isinstance(module, StaticModule) or module.uri != uri:
            msg = f"the module for namespace {uri!r} is not a library module " \
                  f"with this target namespace"
            raise token.error('XQST0059', msg)

    return modules


XQuery31Parser.register(';')
XQuery31Parser.register('%')
XQuery31Parser.symbol_table['(module)'] = XQueryModule


###
# Calls and references of declared functions

def get_function_name(parser: XQuery31Parser, token: XPathToken) \
        -> Optional[tuple[str, str]]:
    """
    Returns the expanded and the lexical name of a function call or reference,
    if it can refer to a declared function, otherwise returns `None`.
    """
    if token.symbol == '(name)':
        uri = parser.function_namespace
        if token.value in parser.RESERVED_FUNCTION_NAMES:
            return None
        lexical_name = str(token.value)
        local_name = lexical_name
    elif token.symbol == ':' and len(token) == 2 and token[1].symbol == '(name)':
        uri = token[1].namespace or ''
        lexical_name = str(token.value)
        local_name = str(token[1].value)
    elif token.symbol == 'Q{' and len(token) == 2 and token[1].symbol == '(name)':
        uri = str(token[0].value)
        local_name = str(token[1].value)
        lexical_name = f'Q{{{uri}}}{local_name}'
    else:
        return None

    if not uri or uri in RESERVED_FUNCTION_NAMESPACES:
        return None
    return f'{{{uri}}}{local_name}', lexical_name


_parenthesized_class = XQuery31Parser.symbol_table['(']


class _ParenthesizedExpression(_parenthesized_class):  # type: ignore[misc, valid-type]

    def led(self, left: XPathToken) -> XPathToken:
        parser = cast(XQuery31Parser, self.parser)
        names = get_function_name(parser, left)
        if names is None or parser.current_module is None or parser.module_registry is None:
            return cast(XPathToken, super().led(left))

        token = DeclaredFunction(parser, *names)
        token.module = parser.current_module
        if parser.next_token.symbol != ')':
            while True:
                token.append(parser.expression(5))
                if parser.next_token.symbol != ',':
                    break
                parser.advance(',')
        parser.advance(')')

        token.span = (left.span[0], parser.token.span[1])
        token.call_arity = token.nargs = len(token)
        parser.module_registry.function_calls.append(token)

        if any(tk.symbol == '?' and not tk for tk in token):
            token.to_partial_function()
        return token


XQuery31Parser.symbol_table['('] = _ParenthesizedExpression


_prefixed_name_class = XQuery31Parser.symbol_table[':']


class _PrefixedNameToken(_prefixed_name_class):  # type: ignore[misc, valid-type]

    def led(self, left: XPathToken) -> XPathToken:
        # A prefixed name with the local part of a built-in function (e.g. local:count)
        # is tokenized as the built-in function: replace it with a name token if the
        # prefix is not a namespace of the function.
        parser = self.parser
        next_token = parser.next_token
        if isinstance(left, NameToken) and isinstance(next_token, XPathFunction) \
                and not self.is_spaced() and left.value in parser.namespaces:
            try:
                copy(next_token).bind_namespace(parser.namespaces[str(left.value)])
            except ElementPathError:
                name_token = parser.symbol_table['(name)'](parser, next_token.symbol)
                name_token.span = next_token.span
                parser.next_token = name_token

        return cast(XPathToken, super().led(left))


XQuery31Parser.symbol_table[':'] = _PrefixedNameToken


_function_reference_class = XQuery31Parser.symbol_table['#']


class _FunctionReference(_function_reference_class):  # type: ignore[misc, valid-type]
    module: Optional[StaticModule] = None

    def led(self, left: XPathToken) -> XPathToken:
        self.module = cast(XQuery31Parser, self.parser).current_module
        return cast(XPathToken, super().led(left))

    def evaluate(self, context: ta.ContextType = None) -> XPathFunction:
        names = get_function_name(cast(XQuery31Parser, self.parser), self[0])
        if names is None or self.module is None:
            return cast(XPathFunction, super().evaluate(context))
        elif context is None:
            raise self.missing_context()

        arity = cast(int, self[1].value)
        decl = self.module.find_function(names[0], arity)
        if decl is None:
            raise self.error('XPST0017', f"unknown function {names[1]}#{arity}")

        func = DeclaredFunction(self.parser, *names, nargs=arity)
        func.module = self.module
        func.resolve(decl)
        func.context = copy(context)
        return func


XQuery31Parser.symbol_table['#'] = _FunctionReference


_function_lookup_class = XQuery31Parser.symbol_table['function-lookup']


class _FunctionLookup(_function_lookup_class):  # type: ignore[misc, valid-type]

    def evaluate(self, context: ta.ContextType = None) -> ta.OneOrEmpty[XPathFunction]:
        if self.context is not None:
            context = self.context
        elif context is None:
            raise self.missing_context()  # declared functions are known at evaluation

        if context is not None:
            state = context.variables.get(MODULE_STATE_KEY)
            if isinstance(state, ModuleState):
                qname = self.get_argument(context, cls=QName, required=True)
                arity = self.get_argument(context, index=1, cls=int, required=True)
                name = qname.expanded_name
                decl = state.registry.find_function(state.main, name, arity)
                if decl is not None:
                    func = DeclaredFunction(self.parser, name, qname.qname, nargs=arity)
                    func.module = decl.module
                    func.resolve(decl)
                    func.context = copy(context)
                    return func

        return cast(ta.OneOrEmpty[XPathFunction], super().evaluate(context))


XQuery31Parser.symbol_table['function-lookup'] = _FunctionLookup


###
# Variable references: global variables are evaluated on first reference
_variable_class = XQuery31Parser.symbol_table['$']


class _VariableReference(_variable_class):  # type: ignore[misc, valid-type]

    def evaluate(self, context: ta.ContextType = None) -> ta.ValueType:
        value = super().evaluate(context)
        if isinstance(value, GlobalVariable):
            return cast(ta.ValueType, value.get_value(self))
        return cast(ta.ValueType, value)


XQuery31Parser.symbol_table['$'] = _VariableReference
