# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: CC0-1.0

"""Project-local XPath extension functions, exposed to the ODD as ``tp:``.

Every public callable in a module listed under ``[transform] xpath_extensions``
is registered, so helpers imported from elsewhere are aliased with a leading
underscore to keep them out of the ``tp:`` namespace.
"""

from __future__ import annotations

from typing import Any

from opm.runtime.xpath_extensions import expect_string as _expect_string

# Beyond a handful of dots a reader counts rather than reads, so the ODD switches
# to "[c. 24]" above this many characters; the constant lives here so the
# function and the model predicate can be read against each other.
MAX_DOTS = 10

# Leiden marker for a lacuna of undetermined extent.
_UNDETERMINED = '[- - -]'


def gap_dots(quantity: Any) -> str:
    """Render a lost passage of known extent in Leiden brackets.

    One dot per lost character: ``tp:gap_dots(4)`` → ``[....]``. A quantity that
    is not a positive number has no dotted spelling, so it falls back to the
    undetermined marker rather than printing empty brackets.
    """
    raw = _expect_string(quantity, arg_name='gap_dots(quantity)').strip()
    try:
        count = int(raw)
    except ValueError:
        return _UNDETERMINED
    if count < 1 or count > MAX_DOTS:
        return _UNDETERMINED
    return '[' + '.' * count + ']'
