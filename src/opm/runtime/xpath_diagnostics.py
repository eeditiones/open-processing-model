# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Collect the XPath errors raised while documents are transformed.

A predicate that raises is treated as false and a param as empty: the processing
model has to carry on, and an ODD shared with TEI Publisher may hold expressions
only one of the two runtimes can evaluate. The ones the compiler can recognise
never reach the runtime (`opm.odd_compiler.expression_check`). What is
recorded here is what is left, in two kinds:

* **Hints** — the project configuration is missing something the expression
  needs: an undeclared prefix, an unset variable, an unregistered ``tp:``
  function, an unknown collection. Each is recorded once.
* **Failures** — everything else: a cast on bad data, a type error, a mistake
  in a config-supplied XPath. Recorded once per expression and error code, with
  a count and the location of the first occurrence.

Collection is opt-in and scoped. ``with collect_xpath_errors() as log:`` records
what is evaluated inside the block, in the current thread or task only; with no
block active, recording is a no-op. The CLI wraps each command in one.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote, urlsplit

from lxml import etree

from . import source_map

_PREFIX_RE = re.compile(r"prefix '([^']+)' is not declared")
_VARIABLE_RE = re.compile(r"unknown variable '([^']+)'")
_FUNCTION_RE = re.compile(r"unknown function '([^']+)'")
_COLLECTION_RE = re.compile(r"'([^']+)' collection not found")
# elementpath names Python classes in some messages; keep only the class name.
_CLASS_REPR_RE = re.compile(r"<class '(?:[\w.]+\.)?(\w+)'>")
_MESSAGE_LIMIT = 140


@dataclass
class XPathFailure:
    """One expression that raised at run time, and where it first did."""

    expression: str
    code: str
    message: str
    count: int = 0
    element: str | None = None
    #: Source document the failing node belongs to (a path, not a URI).
    document: str | None = None
    line: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class XPathErrorLog:
    """Everything [`collect_xpath_errors`][opm.runtime.xpath_diagnostics.collect_xpath_errors] saw."""

    failures: dict[tuple[str, str], XPathFailure] = field(default_factory=dict)
    #: Missing project configuration, keyed so each is reported once.
    hints: dict[str, str] = field(default_factory=dict)

    def record(
        self,
        expression: str,
        exc: Exception,
        node: etree._Element | None = None,
        base_uri: str | None = None,
    ) -> None:
        code = str(getattr(exc, 'code', '') or '').removeprefix('err:')
        message = _clean_message(exc)
        hint = _config_hint(code, message)
        if hint is not None:
            key, text = hint
            self.hints.setdefault(key, text)
            return
        failure = self.failures.get((expression, code))
        if failure is None:
            failure = XPathFailure(expression=expression, code=code, message=message)
            _locate(failure, node, base_uri)
            self.failures[(expression, code)] = failure
        failure.count += 1

    def ordered_failures(self) -> list[XPathFailure]:
        """Failures, the most frequent first."""
        return sorted(self.failures.values(), key=lambda f: (-f.count, f.expression))


_ACTIVE: ContextVar[XPathErrorLog | None] = ContextVar('opm_xpath_error_log', default=None)


@contextmanager
def collect_xpath_errors() -> Iterator[XPathErrorLog]:
    """Record the XPath errors raised inside the ``with`` block."""
    log = XPathErrorLog()
    token = _ACTIVE.set(log)
    try:
        yield log
    finally:
        _ACTIVE.reset(token)


def record_xpath_error(
    expression: str,
    exc: Exception,
    node: etree._Element | None = None,
    base_uri: str | None = None,
) -> None:
    """Hand one error to the active log; does nothing outside a collection block."""
    log = _ACTIVE.get()
    if log is not None:
        log.record(expression, exc, node, base_uri)


def _clean_message(exc: Exception) -> str:
    # "'xs:date' constructor function at line 1, column 4: [err:FORG0001] Invalid …"
    # — the position is within the expression, which is shown whole anyway.
    text = str(exc).split('] ', 1)[-1]
    # Version-suffixed internals read as their XSD type: Date10 → Date.
    text = _CLASS_REPR_RE.sub(
        lambda m: re.sub(r'\d+$', '', m.group(1)) or m.group(1), ' '.join(text.split()),
    )
    if len(text) > _MESSAGE_LIMIT:
        text = text[: _MESSAGE_LIMIT - 1].rstrip() + '…'
    return text


def _config_hint(code: str, message: str) -> tuple[str, str] | None:
    """``(key, text)`` when the error means the project configuration is missing something."""
    if code == 'XPST0081':
        match = _PREFIX_RE.search(message)
        prefix = match.group(1) if match else '?'
        return (
            f'prefix:{prefix}',
            f'namespace prefix "{prefix}" is not declared; bind it in '
            '[transform.namespaces] in opm.toml.',
        )
    if code == 'XPST0008':
        match = _VARIABLE_RE.search(message)
        name = match.group(1) if match else '?'
        return (
            f'variable:{name}',
            f'variable ${name} is not set; define it under [transform.variables] in opm.toml.',
        )
    if code == 'XPST0017':
        match = _FUNCTION_RE.search(message)
        name = match.group(1) if match else ''
        if name.startswith('tp:'):
            return (
                f'function:{name}',
                f'{name}() is not defined; add the Python module that provides it '
                'to [transform] xpath_extensions in opm.toml.',
            )
        return None
    if code == 'FODC0002':
        match = _COLLECTION_RE.search(message)
        if match:
            uri = match.group(1)
            return (
                f'collection:{uri}',
                f'collection "{uri}" is not configured; add it under '
                '[[transform.collections]] in opm.toml.',
            )
        return (
            'document',
            'doc() could not load a document; list it under [transform] documents in opm.toml.',
        )
    return None


def _locate(failure: XPathFailure, node, base_uri: str | None) -> None:
    """Fill in element, document and line from the node that raised."""
    if not isinstance(node, etree._Element) or not isinstance(node.tag, str):
        return
    failure.element = etree.QName(node).localname
    # A chunk is a detached copy; its source node carries the real line.
    source = source_map.source_of(node)
    failure.line = (source if source is not None else node).sourceline
    if base_uri:
        parts = urlsplit(base_uri)
        failure.document = unquote(parts.path) if parts.scheme == 'file' else base_uri
