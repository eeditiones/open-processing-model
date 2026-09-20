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
XQuery 3.1 implementation - part 3 (FLWOR expressions)

Window clauses are not supported.

Refs:
  - https://www.w3.org/TR/xquery-31/#id-flwor-expressions
  - https://www.w3.org/TR/xquery-31/#id-group-by
"""
import math
import re
from collections.abc import Iterable, Iterator
from copy import copy
from decimal import Decimal
from functools import cmp_to_key
from typing import Any, NamedTuple, Optional, Union

import opm._vendor.elementpath.aliases as ta

from opm._vendor.elementpath.collations import CollationManager
from opm._vendor.elementpath.compare import deep_equal
from opm._vendor.elementpath.exceptions import ElementPathLocaleError
from opm._vendor.elementpath.datatypes import AnyURI, UntypedAtomic
from opm._vendor.elementpath.sequence_types import is_sequence_type, match_sequence_type
from opm._vendor.elementpath.xpath_context import XPathContext, XPathSchemaContext
from opm._vendor.elementpath.xpath_tokens import XPathToken, XPathFunction

from ._constructor_tokens import QNAME_PATTERN
from ._xquery31_constructors import XQuery31Parser

__all__ = ['XQuery31Parser']

Bindings = dict[str, Any]


class ForClause(NamedTuple):
    varname: str
    position_varname: Optional[str]
    sequence_type: Optional[str]
    allowing_empty: bool
    expr: XPathToken


class LetClause(NamedTuple):
    varname: str
    sequence_type: Optional[str]
    expr: XPathToken


class WhereClause(NamedTuple):
    expr: XPathToken


class OrderSpec(NamedTuple):
    expr: XPathToken
    descending: bool
    empty_greatest: bool
    collation: Optional[str]


class OrderByClause(NamedTuple):
    specs: list[OrderSpec]


class CountClause(NamedTuple):
    varname: str


class GroupingSpec(NamedTuple):
    varname: str
    sequence_type: Optional[str]
    expr: Optional[XPathToken]  # the ':=' expression, None for a bare grouping variable
    var_token: XPathToken  # the reference used to atomize the grouping key
    collation: Optional[str]


class GroupByClause(NamedTuple):
    specs: list[GroupingSpec]
    non_grouping_varnames: frozenset[str]


Clause = Union[ForClause, LetClause, WhereClause, OrderByClause, CountClause, GroupByClause]

WINDOW_PATTERN = re.compile(r'\s*(?:tumbling|sliding)\s+window\b')
INTERMEDIATE_KEYWORDS = frozenset(('where', 'order', 'stable', 'count', 'group'))

EMPTY_KEY = ('empty',)
"""The normalized grouping key of an empty sequence."""

NAN_KEY = ('nan',)
"""The normalized grouping key of NaN, that is grouped with itself."""


class DeepEqualKey:
    """
    A normalized grouping key for the atomic values that can't be hashed
    consistently with their equality rules. All these keys share the same
    hash, so they are compared with fn:deep-equal within a single bucket.
    """
    __slots__ = 'value', 'collation', 'token'

    def __init__(self, value: Any, collation: Optional[str], token: XPathToken) -> None:
        self.value = value
        self.collation = collation
        self.token = token

    def __hash__(self) -> int:
        return hash(DeepEqualKey)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DeepEqualKey):
            return NotImplemented
        return deep_equal((self.value,), (other.value,), self.collation, self.token)


class FLWORExpression(XPathToken):
    """A token for an XQuery FLWOR expression."""
    symbol = lookup_name = '(flwor)'
    label = 'expression'
    raw_source: str = ''
    clauses: list[Clause]
    return_expr: XPathToken

    def __str__(self) -> str:
        return f'FLWOR expression {self.raw_source!r}'

    @property
    def source(self) -> str:
        return self.raw_source

    @property
    def tree(self) -> str:
        return f'({self.symbol} {self.raw_source})'

    def nud(self) -> XPathToken:
        return self

    def get_results(self, context: ta.ContextType) -> \
            'list[ta.ResultType] | ta.AtomicType | XPathFunction':
        # Like XPath 'for' and 'let' expressions, a single atomic result is
        # returned in a list only if the expression starts with a for clause.
        results = super().get_results(context)
        if isinstance(self.clauses[0], ForClause) and \
                not isinstance(results, (list, XPathFunction)):
            return [results]
        return results

    def select(self, context: ta.ContextType = None) -> Iterator[ta.ItemType]:
        if context is None:
            raise self.missing_context()

        tuples: Iterable[Bindings] = (context.variables,)
        for clause in self.clauses:
            if isinstance(clause, ForClause):
                tuples = self.iter_for_clause(clause, tuples, context)
            elif isinstance(clause, LetClause):
                tuples = self.iter_let_clause(clause, tuples, context)
            elif isinstance(clause, WhereClause):
                tuples = self.iter_where_clause(clause, tuples, context)
            elif isinstance(clause, CountClause):
                tuples = self.iter_count_clause(clause, tuples)
            elif isinstance(clause, GroupByClause):
                tuples = self.group_tuples(clause, tuples, context)
            else:
                tuples = self.sort_tuples(clause, tuples, context)

        for variables in tuples:
            yield from self.return_expr.select(self.get_tuple_context(context, variables))

    @staticmethod
    def get_tuple_context(context: XPathContext, variables: Bindings) -> XPathContext:
        context = copy(context)
        context.variables = variables
        return context

    def check_type(self, value: Any, clause: Union[ForClause, LetClause],
                   context: XPathContext) -> None:
        if clause.sequence_type is None or isinstance(context, XPathSchemaContext):
            return
        elif not match_sequence_type(value, clause.sequence_type, self.parser):
            msg = f"${clause.varname}: {value!r} does not match " \
                  f"sequence type {clause.sequence_type}"
            raise clause.expr.error('XPTY0004', msg)

    def iter_for_clause(self, clause: ForClause, tuples: Iterable[Bindings],
                        context: XPathContext) -> Iterator[Bindings]:
        for variables in tuples:
            tuple_context = self.get_tuple_context(context, variables)
            position = 0
            for position, item in enumerate(clause.expr.select(tuple_context), start=1):
                self.check_type(item, clause, context)
                bindings = {**variables, clause.varname: item}
                if clause.position_varname is not None:
                    bindings[clause.position_varname] = position
                yield bindings

            if not position and clause.allowing_empty:
                self.check_type([], clause, context)
                bindings = {**variables, clause.varname: []}
                if clause.position_varname is not None:
                    bindings[clause.position_varname] = 0
                yield bindings

    def iter_let_clause(self, clause: LetClause, tuples: Iterable[Bindings],
                        context: XPathContext) -> Iterator[Bindings]:
        for variables in tuples:
            value = clause.expr.evaluate(self.get_tuple_context(context, variables))
            self.check_type(value, clause, context)
            yield {**variables, clause.varname: value}

    def iter_where_clause(self, clause: WhereClause, tuples: Iterable[Bindings],
                          context: XPathContext) -> Iterator[Bindings]:
        for variables in tuples:
            tuple_context = self.get_tuple_context(context, variables)
            if self.boolean_value(clause.expr.select(tuple_context)):
                yield variables

    @staticmethod
    def iter_count_clause(clause: CountClause, tuples: Iterable[Bindings]) \
            -> Iterator[Bindings]:
        for position, variables in enumerate(tuples, start=1):
            yield {**variables, clause.varname: position}

    def group_tuples(self, clause: GroupByClause, tuples: Iterable[Bindings],
                     context: XPathContext) -> list[Bindings]:
        tuples = list(tuples)

        # A grouping spec with an expression binds its variable like a let clause,
        # and is visible to the specs that follow it.
        for spec in clause.specs:
            if spec.expr is not None:
                let_clause = LetClause(spec.varname, spec.sequence_type, spec.expr)
                tuples = list(self.iter_let_clause(let_clause, tuples, context))

        if isinstance(context, XPathSchemaContext):
            return tuples  # the grouping variables are bound, don't partition

        # Atomize the grouping variables, collecting the key values used for
        # binding and the normalized keys used for matching the groups.
        key_values: list[list[Any]] = [[] for _ in tuples]
        group_keys: list[list[Any]] = [[] for _ in tuples]

        for spec in clause.specs:
            collation = spec.collation or self.parser.default_collation
            with CollationManager(collation, token=spec.var_token) as manager:
                for variables, values, keys in zip(tuples, key_values, group_keys):
                    tuple_context = self.get_tuple_context(context, variables)
                    value = self.get_group_key(spec, tuple_context)
                    values.append(value)
                    keys.append(self.normalize_group_key(value, spec, collation, manager))

        # Groups are yielded in order of their first occurrence in the tuple stream
        groups: dict[tuple[Any, ...], tuple[list[Any], list[Bindings]]] = {}
        for variables, values, keys in zip(tuples, key_values, group_keys):
            group = groups.setdefault(tuple(keys), (values, []))
            group[1].append(variables)

        return [self.merge_group(clause, values, group) for values, group in groups.values()]

    @staticmethod
    def merge_group(clause: GroupByClause, key_values: list[Any],
                    group: list[Bindings]) -> Bindings:
        # The variables that are not grouping variables are bound to the
        # concatenation of their values in the tuples of the group. The other
        # variables come from an outer scope, so they are left untouched.
        variables = {**group[0]}

        for varname in clause.non_grouping_varnames:
            sequence: list[Any] = []
            for item in (t.get(varname) for t in group):
                if isinstance(item, list):
                    sequence.extend(item)
                elif item is not None:
                    sequence.append(item)
            variables[varname] = sequence

        for spec, value in zip(clause.specs, key_values):
            variables[spec.varname] = [] if value is EMPTY_KEY else value

        return variables

    @staticmethod
    def get_group_key(spec: GroupingSpec, context: XPathContext) -> Any:
        values = [x for x in spec.var_token.atomization(context)]
        if not values:
            return EMPTY_KEY
        elif len(values) > 1:
            msg = "a grouping key must be a single atomic value or an empty sequence"
            raise spec.var_token.error('XPTY0004', msg)

        value = values[0]
        if isinstance(value, UntypedAtomic):
            return str(value)  # untyped values are grouped as xs:string
        return value

    @staticmethod
    def normalize_group_key(value: Any, spec: GroupingSpec, collation: Optional[str],
                            manager: CollationManager) -> Any:
        # Builds a hashable key that is equal for the values that fn:deep-equal
        # considers equal, so that the groups can be matched with a mapping.
        if value is EMPTY_KEY:
            return EMPTY_KEY
        elif isinstance(value, bool):
            return 'boolean', value
        elif isinstance(value, (str, AnyURI)):
            return 'string', manager.strxfrm(str(value))
        elif isinstance(value, (int, float, Decimal)):
            if isinstance(value, float) and math.isnan(value):
                return NAN_KEY
            try:
                return 'number', float(value)
            except (OverflowError, ValueError):
                pass
        return 'other', DeepEqualKey(value, collation, spec.var_token)

    def sort_tuples(self, clause: OrderByClause, tuples: Iterable[Bindings],
                    context: XPathContext) -> list[Bindings]:
        tuples = list(tuples)
        if isinstance(context, XPathSchemaContext):
            return tuples

        keys: list[list[Any]] = [[] for _ in tuples]
        for spec in clause.specs:
            collation = spec.collation or self.parser.default_collation
            with CollationManager(collation, token=spec.expr) as manager:
                for variables, tuple_keys in zip(tuples, keys):
                    tuple_context = self.get_tuple_context(context, variables)
                    tuple_keys.append(self.get_sort_key(spec, tuple_context, manager))

        def compare(k1: tuple[int, list[Any]], k2: tuple[int, list[Any]]) -> int:
            for spec, v1, v2 in zip(clause.specs, k1[1], k2[1]):
                result = self.compare_sort_keys(spec, v1, v2)
                if result:
                    return -result if spec.descending else result
            return 0

        # Python's sort is stable, so the 'stable' modifier requires nothing more
        indexes = sorted(enumerate(keys), key=cmp_to_key(compare))
        return [tuples[k] for k, _ in indexes]

    @staticmethod
    def get_sort_key(spec: OrderSpec, context: XPathContext,
                     manager: CollationManager) -> Any:
        values = [x for x in spec.expr.atomization(context)]
        if not values:
            return None
        elif len(values) > 1:
            msg = "an order by key must be a single atomic value or an empty sequence"
            raise spec.expr.error('XPTY0004', msg)

        value = values[0]
        if isinstance(value, (str, AnyURI, UntypedAtomic)):
            return manager.strxfrm(str(value))
        return value

    @staticmethod
    def compare_sort_keys(spec: OrderSpec, v1: Any, v2: Any) -> int:
        # Empty keys and NaN values are ordered before (empty least) or
        # after (empty greatest) all the other values, with NaN nearest.
        def rank(v: Any) -> int:
            if v is None:
                return 2 if spec.empty_greatest else 0
            elif isinstance(v, float) and math.isnan(v):
                return 1
            return 0 if spec.empty_greatest else 2

        r1, r2 = rank(v1), rank(v2)
        if r1 != r2:
            return -1 if r1 < r2 else 1
        elif v1 is None or isinstance(v1, float) and math.isnan(v1):
            return 0
        elif isinstance(v1, bool) ^ isinstance(v2, bool):
            raise spec.expr.error('XPTY0004', f"cannot compare {v1!r} with {v2!r}")

        try:
            if v1 < v2:
                return -1
            elif v1 > v2:
                return 1
            return 0
        except TypeError as err:
            raise spec.expr.error('XPTY0004', str(err)) from None


def is_keyword(token: XPathToken, name: str) -> bool:
    return token.symbol == '(name)' and token.value == name


def nud__flwor_expression(self: XPathToken) -> XPathToken:
    parser = self.parser
    if parser.next_token.symbol != '$':
        if self.symbol == 'for' and WINDOW_PATTERN.match(parser.source, self.span[1]):
            raise self.error('XPST0003', "window clauses are not supported")
        return self.as_name()

    token = FLWORExpression(parser)
    token.clauses = []
    keyword = self.symbol

    while True:
        if keyword == 'for':
            parse_for_clause(token)
        elif keyword == 'let':
            parse_let_clause(token)
        elif keyword == 'where':
            token.clauses.append(WhereClause(parser.expression(5)))
        elif keyword == 'count':
            token.clauses.append(CountClause(parse_variable(token)))
        elif keyword == 'group':
            parse_group_by_clause(token)
        else:
            if keyword == 'stable':
                parser.next_token.expected('(name)')
                if not is_keyword(parser.next_token, 'order'):
                    raise parser.next_token.wrong_syntax()
                parser.advance()
            parse_order_by_clause(token)

        next_token = parser.next_token
        if next_token.symbol in ('for', 'let'):
            parser.advance()
            parser.next_token.expected('$')
        elif next_token.symbol != '(name)' or next_token.value not in INTERMEDIATE_KEYWORDS:
            break
        else:
            parser.advance()
        keyword = str(next_token.symbol if next_token.symbol != '(name)' else next_token.value)

    parser.advance('return')
    token.return_expr = parser.expression(5)
    token.append(token.return_expr)

    token.span = (self.span[0], parser.token.span[1])
    token.raw_source = parser.source[token.span[0]:token.span[1]]
    return token


###
# The 'for' and 'let' keywords start a FLWOR expression. They have no
# left binding power, so the expression of a clause stops before them.
_for_class = XQuery31Parser.symbol_table['for']
_let_class = XQuery31Parser.symbol_table['let']


class _ForExpression(_for_class):  # type: ignore[misc, valid-type]
    lbp = 0
    nud = nud__flwor_expression


class _LetExpression(_let_class):  # type: ignore[misc, valid-type]
    lbp = 0
    nud = nud__flwor_expression


XQuery31Parser.symbol_table['for'] = _ForExpression
XQuery31Parser.symbol_table['let'] = _LetExpression


def parse_variable_reference(token: XPathToken) -> XPathToken:
    token.parser.advance('$')
    variable = token.parser.token.nud()
    token.append(variable)
    return variable


def parse_variable(token: XPathToken) -> str:
    return str(parse_variable_reference(token).value)


def parse_collation(token: XPathToken) -> Optional[str]:
    parser = token.parser
    if not is_keyword(parser.next_token, 'collation'):
        return None

    parser.advance()
    collation = str(parser.advance('(string)').value)
    try:
        with CollationManager(collation, token=parser.token):
            pass
    except ElementPathLocaleError:
        msg = f"unsupported collation {collation!r}"
        raise parser.token.error('XQST0076', msg) from None
    return collation


def parse_type_declaration(token: XPathToken) -> Optional[str]:
    parser = token.parser
    if parser.next_token.symbol != 'as':
        return None

    parser.advance('as')
    type_token = parser.parse_sequence_type()
    sequence_type = type_token.source
    if type_token.occurrence and not sequence_type.endswith(type_token.occurrence):
        sequence_type += type_token.occurrence

    if not is_sequence_type(sequence_type, parser):
        if QNAME_PATTERN.fullmatch(sequence_type.rstrip('?*+')):
            raise type_token.error('XPST0051', f"unknown atomic type {sequence_type!r}")
        raise type_token.error('XPST0003', "a sequence type expected")
    return sequence_type


def parse_for_clause(token: FLWORExpression) -> None:
    parser = token.parser
    while True:
        varname = parse_variable(token)
        sequence_type = parse_type_declaration(token)

        allowing_empty = False
        if is_keyword(parser.next_token, 'allowing'):
            parser.advance()
            if not is_keyword(parser.next_token, 'empty'):
                raise parser.next_token.wrong_syntax()
            parser.advance()
            allowing_empty = True

        position_varname = None
        if is_keyword(parser.next_token, 'at'):
            parser.advance()
            position_varname = parse_variable(token)
            if position_varname == varname:
                msg = f"positional variable ${varname} has the same name of the bound variable"
                raise token[-1].error('XQST0089', msg)

        parser.advance('in')
        expr = parser.expression(5)
        token.append(expr)
        token.clauses.append(
            ForClause(varname, position_varname, sequence_type, allowing_empty, expr)
        )

        if parser.next_token.symbol != ',':
            break
        parser.advance()


def parse_let_clause(token: FLWORExpression) -> None:
    parser = token.parser
    while True:
        varname = parse_variable(token)
        sequence_type = parse_type_declaration(token)
        parser.advance(':=')
        expr = parser.expression(5)
        token.append(expr)
        token.clauses.append(LetClause(varname, sequence_type, expr))

        if parser.next_token.symbol != ',':
            break
        parser.advance()


def parse_order_by_clause(token: FLWORExpression) -> None:
    parser = token.parser
    if not is_keyword(parser.next_token, 'by'):
        raise parser.next_token.wrong_syntax()
    parser.advance()

    specs = []
    while True:
        expr = parser.expression(5)
        token.append(expr)

        descending = False
        if is_keyword(parser.next_token, 'ascending'):
            parser.advance()
        elif is_keyword(parser.next_token, 'descending'):
            parser.advance()
            descending = True

        empty_greatest = getattr(parser, 'empty_order', 'least') == 'greatest'
        if is_keyword(parser.next_token, 'empty'):
            parser.advance()
            if is_keyword(parser.next_token, 'greatest'):
                empty_greatest = True
            elif is_keyword(parser.next_token, 'least'):
                empty_greatest = False
            else:
                raise parser.next_token.wrong_syntax()
            parser.advance()

        specs.append(OrderSpec(expr, descending, empty_greatest, parse_collation(token)))
        if parser.next_token.symbol != ',':
            break
        parser.advance()

    token.clauses.append(OrderByClause(specs))


def iter_bound_varnames(clauses: Iterable[Clause]) -> Iterator[str]:
    """Yields the names of the variables bound in the tuple stream by the clauses."""
    for clause in clauses:
        if isinstance(clause, ForClause):
            yield clause.varname
            if clause.position_varname is not None:
                yield clause.position_varname
        elif isinstance(clause, (LetClause, CountClause)):
            yield clause.varname
        elif isinstance(clause, GroupByClause):
            yield from (spec.varname for spec in clause.specs)
            yield from clause.non_grouping_varnames


def parse_group_by_clause(token: FLWORExpression) -> None:
    parser = token.parser
    if not is_keyword(parser.next_token, 'by'):
        raise parser.next_token.wrong_syntax()
    parser.advance()

    specs = []
    while True:
        var_token = parse_variable_reference(token)
        sequence_type = parse_type_declaration(token)

        expr = None
        if parser.next_token.symbol == ':=':
            parser.advance(':=')
            expr = parser.expression(5)
            token.append(expr)
        elif sequence_type is not None:
            # A type declaration is allowed only with an initializing expression
            raise parser.next_token.wrong_syntax()

        specs.append(GroupingSpec(
            str(var_token.value), sequence_type, expr, var_token, parse_collation(token)
        ))
        if parser.next_token.symbol != ',':
            break
        parser.advance()

    grouping_varnames = {spec.varname for spec in specs}
    non_grouping_varnames = frozenset(
        name for name in iter_bound_varnames(token.clauses)
        if name not in grouping_varnames
    )
    token.clauses.append(GroupByClause(specs, non_grouping_varnames))
