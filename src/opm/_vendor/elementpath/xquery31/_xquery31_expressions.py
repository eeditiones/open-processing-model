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
XQuery 3.1 implementation - part 5 (switch, typeswitch and try/catch expressions)

Refs:
  - https://www.w3.org/TR/xquery-31/#id-switch
  - https://www.w3.org/TR/xquery-31/#id-typeswitch
  - https://www.w3.org/TR/xquery-31/#id-try-catch
"""
import re
from collections.abc import Iterator
from copy import copy
from typing import Any, NamedTuple, Optional

import opm._vendor.elementpath.aliases as ta

from opm._vendor.elementpath.compare import deep_equal
from opm._vendor.elementpath.datatypes import AnyURI, QName
from opm._vendor.elementpath.exceptions import ElementPathError, MissingContextError
from opm._vendor.elementpath.namespaces import XQT_ERRORS_NAMESPACE
from opm._vendor.elementpath.xpath_tokens import XPathToken, ValueToken

from ._constructor_tokens import NCNAME
from ._xquery31_constructors import BRACE_PATTERN
from ._xquery31_flwor import is_keyword, parse_variable
from ._xquery31_prolog import XQuery31Parser

__all__ = ['XQuery31Parser']

NAME_TEST_PATTERN = re.compile(
    rf'\*:{NCNAME}|{NCNAME}:\*|Q\{{[^{{}}]*\}}\*|\*|'
    rf'Q\{{[^{{}}]*\}}{NCNAME}|{NCNAME}(?::{NCNAME})?'
)


class XQueryExpression(XPathToken):
    """Base class of XQuery expressions that evaluate one of their branches."""
    label = 'expression'
    raw_source: str = ''

    def __str__(self) -> str:
        return f'{self.symbol[1:-1]} expression {self.raw_source!r}'

    @property
    def source(self) -> str:
        return self.raw_source

    @property
    def tree(self) -> str:
        return f'({self.symbol} {self.raw_source})'

    def nud(self) -> XPathToken:
        return self

    def set_source(self, start: int) -> None:
        self.span = (start, self.parser.token.span[1])
        self.raw_source = self.parser.source[self.span[0]:self.span[1]]

    def get_branch(self, context: ta.ContextType) -> tuple[XPathToken, ta.ContextType]:
        """Returns the expression to evaluate and its dynamic context."""
        raise NotImplementedError()

    def evaluate(self, context: ta.ContextType = None) -> ta.ValueType:
        expr, context = self.get_branch(context)
        return expr.evaluate(context)

    def select(self, context: ta.ContextType = None) -> Iterator[ta.ItemType]:
        expr, context = self.get_branch(context)
        yield from expr.select(context)

    def bind_variable(self, context: ta.ContextType, varname: Optional[str],
                      value: Any) -> ta.ContextType:
        if varname is None:
            return context
        elif context is None:
            raise self.missing_context()

        context = copy(context)
        context.variables = {**context.variables, varname: value}
        return context


###
# Switch expressions
class SwitchCase(NamedTuple):
    operands: list[XPathToken]
    expr: XPathToken


class SwitchExpression(XQueryExpression):
    symbol = lookup_name = '(switch)'
    operand: XPathToken
    cases: list[SwitchCase]
    default: XPathToken

    def get_switch_value(self, token: XPathToken, context: ta.ContextType) -> list[Any]:
        values = [x for x in token.atomization(copy(context))]
        if len(values) > 1:
            msg = "a switch operand must be a single atomic value or an empty sequence"
            raise token.error('XPTY0004', msg)
        return values

    def get_branch(self, context: ta.ContextType) -> tuple[XPathToken, ta.ContextType]:
        value = self.get_switch_value(self.operand, context)
        collation = self.parser.default_collation
        for case in self.cases:
            for operand in case.operands:
                case_value = self.get_switch_value(operand, context)
                if not value and not case_value or value and case_value and \
                        deep_equal(value, case_value, collation, token=self):
                    return case.expr, context
        return self.default, context


def nud__switch_expression(self: XPathToken) -> XPathToken:
    parser = self.parser
    if parser.next_token.symbol != '(':
        return self.as_name()

    token = SwitchExpression(parser)
    parser.advance('(')
    token.operand = parser.expression()
    parser.advance(')')
    token.append(token.operand)

    token.cases = []
    while is_keyword(parser.next_token, 'case'):
        operands = []
        while is_keyword(parser.next_token, 'case'):
            parser.advance()
            operands.append(parser.expression(5))
        parser.advance('return')
        token.cases.append(SwitchCase(operands, parser.expression(5)))
        token.extend(operands)
        token.append(token.cases[-1].expr)

    if not token.cases or not is_keyword(parser.next_token, 'default'):
        raise parser.next_token.wrong_syntax()
    parser.advance()
    parser.advance('return')
    token.default = parser.expression(5)
    token.append(token.default)

    token.set_source(self.span[0])
    return token


###
# Typeswitch expressions
class TypeswitchCase(NamedTuple):
    varname: Optional[str]
    sequence_types: list[XPathToken]
    expr: XPathToken


class TypeswitchExpression(XQueryExpression):
    symbol = lookup_name = '(typeswitch)'
    operand: XPathToken
    cases: list[TypeswitchCase]
    default_varname: Optional[str] = None
    default: XPathToken

    def get_branch(self, context: ta.ContextType) -> tuple[XPathToken, ta.ContextType]:
        value = self.operand.evaluate(copy(context))
        for case in self.cases:
            if any(self.match_sequence_type(value, st, context) for st in case.sequence_types):
                return case.expr, self.bind_variable(context, case.varname, value)
        return self.default, self.bind_variable(context, self.default_varname, value)

    def match_sequence_type(self, value: Any, sequence_type: XPathToken,
                            context: ta.ContextType) -> bool:
        # Matches like an 'instance of' expression, that supports all the kind tests
        token = self.parser.symbol_table['instance'](self.parser)
        token[:] = ValueToken(self.parser, value=value), sequence_type
        return bool(token.evaluate(copy(context)))


def nud__typeswitch_expression(self: XPathToken) -> XPathToken:
    parser = self.parser
    if parser.next_token.symbol != '(':
        return self.as_name()

    token = TypeswitchExpression(parser)
    parser.advance('(')
    token.operand = parser.expression()
    parser.advance(')')
    token.append(token.operand)

    token.cases = []
    while is_keyword(parser.next_token, 'case'):
        parser.advance()
        varname = None
        if parser.next_token.symbol == '$':
            varname = parse_variable(token)
            parser.advance('as')

        sequence_types = [parser.parse_sequence_type()]
        while parser.next_token.symbol == '|':
            parser.advance('|')
            sequence_types.append(parser.parse_sequence_type())

        parser.advance('return')
        token.cases.append(TypeswitchCase(varname, sequence_types, parser.expression(5)))
        token.append(token.cases[-1].expr)

    if not token.cases or not is_keyword(parser.next_token, 'default'):
        raise parser.next_token.wrong_syntax()
    parser.advance()
    if parser.next_token.symbol == '$':
        token.default_varname = parse_variable(token)
    parser.advance('return')
    token.default = parser.expression(5)
    token.append(token.default)

    token.set_source(self.span[0])
    return token


XQuery31Parser.register('switch', label='expression', nud=nud__switch_expression)
XQuery31Parser.register('typeswitch', label='expression', nud=nud__typeswitch_expression)


###
# Try/catch expressions
class NameTest(NamedTuple):
    uri: Optional[str]  # None matches any namespace
    local_name: Optional[str]  # None matches any local name

    def matches(self, qname: QName) -> bool:
        return (self.uri is None or self.uri == (qname.uri or '')) and \
            (self.local_name is None or self.local_name == qname.local_name)


class CatchClause(NamedTuple):
    name_tests: list[NameTest]
    expr: Optional[XPathToken]


def get_error_qname(error: ElementPathError) -> QName:
    """Returns the error code of an exception as an xs:QName."""
    qname = getattr(error, 'error_qname', None)
    if isinstance(qname, QName):
        return qname

    code = error.code or 'err:FOER0000'
    if code.startswith('{'):
        uri, local_name = code[1:].split('}')
        return QName(uri, local_name)

    prefix, _, local_name = code.rpartition(':')
    if prefix in ('', 'err'):
        return QName(XQT_ERRORS_NAMESPACE, f'err:{local_name}')
    return QName('', local_name)


class TryCatchExpression(XQueryExpression):
    symbol = lookup_name = '(try)'
    try_expr: Optional[XPathToken] = None
    catch_clauses: list[CatchClause]

    def evaluate(self, context: ta.ContextType = None) -> ta.ValueType:
        try:
            if self.try_expr is None:
                return []
            # Materialize the results, for catching the errors of lazy evaluations
            return self.try_expr.evaluate(copy(context))
        except ElementPathError as err:
            expr, catch_context = self.get_catch_branch(err, context)
            return [] if expr is None else expr.evaluate(catch_context)

    def select(self, context: ta.ContextType = None) -> Iterator[ta.ItemType]:
        try:
            results = [] if self.try_expr is None else \
                [x for x in self.try_expr.select(copy(context))]
        except ElementPathError as err:
            expr, catch_context = self.get_catch_branch(err, context)
            if expr is not None:
                yield from expr.select(catch_context)
        else:
            yield from results

    def get_catch_branch(self, err: ElementPathError, context: ta.ContextType) \
            -> tuple[Optional[XPathToken], ta.ContextType]:
        if context is None and isinstance(err, MissingContextError):
            raise err  # a static evaluation, the dynamic context is required

        code = get_error_qname(err)
        if code.uri == XQT_ERRORS_NAMESPACE and code.local_name.startswith(('XPST', 'XQST')):
            raise err  # static errors can't be caught

        for clause in self.catch_clauses:
            if any(test.matches(code) for test in clause.name_tests):
                break
        else:
            raise err

        if clause.expr is None:
            return None, context
        elif context is None:
            raise self.missing_context()

        variables = dict(context.variables)
        prefixes = [pfx for pfx, uri in self.parser.namespaces.items()
                    if pfx and uri == XQT_ERRORS_NAMESPACE]
        line_number: Any = []
        column_number: Any = []
        if err.token is not None:
            line_number, column_number = err.token.position

        for name, value in (('code', code),
                            ('description', err.message),
                            ('value', getattr(err, 'error_value', [])),
                            ('module', [] if not self.parser.base_uri
                                else AnyURI(self.parser.base_uri)),
                            ('line-number', line_number),
                            ('column-number', column_number),
                            ('additional', [])):
            variables[f'{{{XQT_ERRORS_NAMESPACE}}}{name}'] = value
            for prefix in prefixes:
                variables[f'{prefix}:{name}'] = value  # shadows outer variables

        catch_context = copy(context)
        catch_context.variables = variables
        return clause.expr, catch_context


def parse_name_test(token: XPathToken) -> NameTest:
    parser = token.parser
    next_token = parser.next_token
    match = NAME_TEST_PATTERN.match(parser.source, next_token.span[0])
    if match is None:
        raise next_token.wrong_syntax()
    parser.seek(match.end())

    name = match.group()
    if name == '*':
        return NameTest(None, None)
    elif name.startswith('*:'):
        return NameTest(None, name[2:])
    elif name.startswith('Q{'):
        uri, _, local_name = name[2:].partition('}')
        return NameTest(uri.strip(), None if local_name == '*' else local_name)
    elif ':' not in name:
        return NameTest('', name)

    prefix, local_name = name.split(':')
    try:
        uri = parser.namespaces[prefix]
    except KeyError:
        raise next_token.error('XPST0081', f"prefix {prefix!r} is not declared") from None
    return NameTest(uri, None if local_name == '*' else local_name)


def parse_enclosed_expression(token: XPathToken) -> Optional[XPathToken]:
    parser = token.parser
    parser.advance('{')
    if parser.next_token.symbol == '}':
        expr = None
    else:
        expr = parser.expression()
        token.append(expr)
    parser.advance('}')
    return expr


def parse_try_catch_expression(name_token: XPathToken) -> XPathToken:
    parser = name_token.parser
    token = TryCatchExpression(parser)
    token.try_expr = parse_enclosed_expression(token)

    token.catch_clauses = []
    if not is_keyword(parser.next_token, 'catch'):
        raise parser.next_token.wrong_syntax("a catch clause expected")

    while is_keyword(parser.next_token, 'catch'):
        parser.advance()
        name_tests = [parse_name_test(token)]
        while parser.next_token.symbol == '|':
            parser.advance('|')
            name_tests.append(parse_name_test(token))
        token.catch_clauses.append(CatchClause(name_tests, parse_enclosed_expression(token)))

    token.set_source(name_token.span[0])
    return token


_name_class = XQuery31Parser.symbol_table['(name)']


class _XQueryNameToken(_name_class):  # type: ignore[misc, valid-type]

    def nud(self) -> XPathToken:
        if self.value == 'try' and not self.namespace and \
                BRACE_PATTERN.match(self.parser.source, self.span[1]):
            return parse_try_catch_expression(self)
        return super().nud()  # type: ignore[no-any-return]


XQuery31Parser.symbol_table['(name)'] = _XQueryNameToken


###
# fn:error() keeps the error code and the error value for the catch clauses
_error_class = XQuery31Parser.symbol_table['error']


class _ErrorFunction(_error_class):  # type: ignore[misc, valid-type]

    def evaluate(self, context: ta.ContextType = None) -> Any:
        try:
            return super().evaluate(context)
        except ElementPathError as err:
            if self.label == 'constructor function' or not self:
                raise

            if self.context is not None:
                context = self.context
            try:
                qname = self.get_argument(context, cls=QName)
                value = self[2].evaluate(context) if len(self) == 3 else []
            except ElementPathError:
                raise err from None

            if qname is not None and err.code is not None and \
                    err.code.endswith(qname.local_name):
                setattr(err, 'error_qname', qname)
            setattr(err, 'error_value', value)
            raise


XQuery31Parser.symbol_table['error'] = _ErrorFunction
