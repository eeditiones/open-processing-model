# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The one ``tp:`` function tagdocs needs beyond the generic ones.

Everything else a documentation page shows is written into the tree before
rendering, by [`opm.odd_expand`][opm.odd_expand]; what remains is formatting
the node being rendered.
"""

from __future__ import annotations

from typing import Any

from opm.runtime.xpath_extensions import expect_element
from opm.spec_index import serialize_spec_xml


def serialize_spec(node: Any) -> str:
    """Pretty-print a spec subtree (content model, Schematron, ``pb:template``)."""
    if node is None or node == [] or node == ():
        return ''
    el = expect_element(node, arg_name='serialize_spec(node)')
    return serialize_spec_xml(el)
