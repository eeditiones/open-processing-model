# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Decide, when an ODD is compiled, which of its XPath expressions opm cannot run.

ODDs are shared with TEI Publisher, whose eXist runtime evaluates XQuery and
offers functions such as ``util:document-name()``. An expression that relies on
either fails in opm on every run and for every document, so the answer is known
before any document is read. The code generator asks here once per expression,
emits the result a failing evaluation would have produced anyway (``False`` for
a predicate, an empty or context-node fallback for a param), and records why.
That keeps these expected failures out of the run-time error log
([`opm.runtime.xpath_diagnostics`][opm.runtime.xpath_diagnostics]), which is left with the errors that
depend on the document or on the project configuration.

The check is deliberately generous with what only a project can supply: any
prefix the ODD does not declare might still be bound in ``[transform.namespaces]``,
and ``tp:`` functions come from ``[transform] xpath_extensions``. The compiled
module is cached per ODD, not per project, so neither can count against an
expression here.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from opm._vendor.elementpath.exceptions import ElementPathError

# Any prefixed name in an expression.
_PREFIX_RE = re.compile(r'(?<![\w.-])([A-Za-z_][\w.-]*):[A-Za-z_]')
# A call to a tp: extension function.
_TP_CALL_RE = re.compile(r'(?<![\w.-])tp:([A-Za-z_][\w.-]*)\s*\(')
# elementpath spells this two ways: the XPath parser quotes the name,
# the XQuery one gives it unquoted with an arity suffix (``tp:missing#1``).
_UNKNOWN_FUNCTION_RE = re.compile(r"unknown function (?:'([^']+)'|([^\s']+?)(?:#\d+)?)(?:\s|$)")
_UNEXPECTED_RE = re.compile(r"unexpected '([^']+)'")

#: Function namespaces of eXist's own modules, as TEI Publisher ODDs bind them.
EXIST_PREFIXES = frozenset({
    'util', 'request', 'response', 'session', 'xmldb', 'sm', 'ft',
    'system', 'file', 'console', 'kwic', 'templates',
})


@dataclass(frozen=True)
class UnsupportedExpression:
    """One ODD expression opm skips, and why."""

    element: str
    #: ``predicate``, or ``param <name>``.
    where: str
    expression: str
    reason: str
    #: Model key (``tei-date3``) for a model's own predicate or params.
    model: str | None = None
    #: File name of the ODD the expression is written in.
    odd: str | None = None
    line: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _any_arity(*_args):
    """Stand-in for a ``tp:`` function: accepts any call, is never evaluated."""
    return None


def static_problem(
    expr: str,
    namespaces: dict[str, str],
    default_namespace: str = '',
) -> str | None:
    """Why *expr* can never be evaluated by opm, or ``None`` if it can.

    Parses *expr* the way the runtime will, with *namespaces* from the ODD root
    and every other prefix bound to a placeholder, and every ``tp:`` function
    it calls registered as a stub.
    """
    # Imported here: opm.runtime pulls in every output backend, which the
    # compiler package must not need just to be imported.
    from opm.runtime.xpath_extensions import build_extension_parser  # noqa: PLC0415

    bound = dict(namespaces)
    for prefix in set(_PREFIX_RE.findall(expr)):
        bound.setdefault(prefix, f'urn:opm:placeholder:{prefix}')
    stubs = {name: _any_arity for name in set(_TP_CALL_RE.findall(expr))}
    try:
        build_extension_parser(default_namespace, stubs, namespaces=bound).parse(expr)
    except ElementPathError as exc:
        return describe(exc, expr)
    return None


def describe(exc: ElementPathError, expr: str) -> str:
    """A short, author-facing reason for a static error in *expr*."""
    code = str(getattr(exc, 'code', '') or '').removeprefix('err:')
    message = ' '.join(str(exc).split('] ', 1)[-1].split())

    if code == 'XPST0017':
        match = _UNKNOWN_FUNCTION_RE.search(message)
        name = (match.group(1) or match.group(2)) if match else 'function'
        prefix = name.partition(':')[0] if ':' in name else ''
        if prefix in EXIST_PREFIXES:
            return f'eXist function {name}()'
        return f'unknown function {name}()'

    if code == 'XPST0003':
        unexpected = _UNEXPECTED_RE.search(message)
        token = unexpected.group(1) if unexpected else ''
        if re.search(r'(?<![\w.-])try\s*\{', expr):
            return 'XQuery try/catch'
        if token == '<':
            return 'XQuery element constructor'
        if token == 'let':
            return 'XQuery let chain'
        return f'not XPath 3.1: {message}'

    return f'{message} ({code})' if code else message
