# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixes for elementpath parsing bugs that affect templates.

elementpath (5.1) rejects a path step right after a map or array lookup, so
``$context?fragments?toc//li`` is a syntax error although XPath 3.1 allows a
lookup as a step. This patch lets ``/`` and ``//`` take a lookup on their
left; everything else is handled by elementpath's own code. Remove it once
elementpath accepts such paths itself.
"""

from __future__ import annotations

from typing import Any

from elementpath.xpath31 import XPath31Parser
from elementpath.xpath31._xpath31_operators import LookupOperatorToken

_PATCHED = '_opm_lookup_step'


def _patch() -> None:
    for symbol in ('/', '//'):
        cls = XPath31Parser.symbol_table[symbol]
        if getattr(cls, _PATCHED, False):
            continue
        original = cls.led

        def led(self: Any, left: Any, _original: Any = original) -> Any:
            if isinstance(left, LookupOperatorToken) and len(left) > 0:
                parser = self.parser
                if parser.next_token.label not in parser.PATH_STEP_LABELS:
                    parser.expected_next(*parser.PATH_STEP_SYMBOLS)
                self[:] = left, parser.expression(75)
                return self
            return _original(self, left)

        cls.led = led
        setattr(cls, _PATCHED, True)


_patch()
