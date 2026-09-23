# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The one ``tp:`` function tagdocs needs beyond the generic ones.

Everything else a documentation page shows is written into the tree before
rendering, by [`opm.odd_expand`][opm.odd_expand]; what remains is formatting
the node being rendered.
"""

from __future__ import annotations

from typing import Any

from lxml import etree

from opm.runtime.xpath_extensions import expect_element
from opm.spec_index import TEI_NS


def serialize_spec(node: Any) -> str:
    """Pretty-print a spec subtree (content model, Schematron, ``pb:template``)
    without a default TEI xmlns declaration.

    ``with_tail=False`` so mixed-content examples (element + following text)
    stay well-formed; tails are handled by
    [`serialize_egxml`][opm.runtime.common_xpath_functions.serialize_egxml].
    """
    if node is None or node == [] or node == ():
        return ''
    el = expect_element(node, arg_name='serialize_spec(node)')
    copy = etree.fromstring(etree.tostring(el, with_tail=False))
    etree.cleanup_namespaces(copy)
    text = etree.tostring(copy, encoding='unicode', pretty_print=True)
    return text.replace(f' xmlns="{TEI_NS}"', '').strip()
