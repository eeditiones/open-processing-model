# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""One place to build the XML parsers opm reads documents with.

Two things every parser here has in common:

* ``collect_ids=False``. TEI and ``p5subset.xml`` repeat ``xml:id`` across
  their inlined specs, and lxml's default parser rejects a document with
  duplicate IDs outright.
* A resolver that refuses remote DTDs and entities. This is not optional
  hardening — on libxml2 2.14 ``collect_ids=False`` by itself makes the parser
  try to fetch a document's external DTD, so a JATS file whose DOCTYPE points
  at ``jats.nlm.nih.gov`` fails to parse at all without a network. Blocking
  the fetch also keeps opm from reaching out to whatever URL a document names,
  which is the XXE footgun the same switch would otherwise open.
"""

from __future__ import annotations

from lxml import etree

#: Schemes we will not fetch a DTD or entity over.
_REMOTE_SCHEMES = frozenset({'http', 'https', 'ftp', 'ftps'})


class NoRemoteEntities(etree.Resolver):
    """Resolve remote DTDs and entities to nothing, leaving local ones alone.

    A local DTD may carry entity declarations the document needs, so those
    still resolve normally. A remote one is answered with an empty document:
    the DOCTYPE stays harmless, and a document that genuinely depends on
    remote entity declarations fails on the undefined entity rather than on a
    network timeout, which is the more useful error.
    """

    def resolve(self, system_url, public_id, context):  # noqa: D102
        if system_url and system_url.split(':', 1)[0].lower() in _REMOTE_SCHEMES:
            return self.resolve_string('', context)
        return None


def make_parser(**kwargs) -> etree.XMLParser:
    """An ``XMLParser`` that tolerates duplicate IDs and never fetches a DTD.

    Keyword arguments are passed to ``etree.XMLParser``; ``collect_ids``
    defaults to ``False`` and can be overridden.
    """
    kwargs.setdefault('collect_ids', False)
    parser = etree.XMLParser(**kwargs)
    parser.resolvers.add(NoRemoteEntities())
    return parser


def parse(source, parser: etree.XMLParser | None = None) -> etree._ElementTree:
    """``etree.parse`` with opm's default parser."""
    return etree.parse(source, parser if parser is not None else make_parser())
