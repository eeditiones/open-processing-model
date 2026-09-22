# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``tp:`` primitives: lookups into the [`SpecIndex`][opm.spec_index.SpecIndex] of the document.

The bottom layer of the documentation functions, and the one meant to stay
Python: each is a lookup into facts the index holds — direct memberships and
content-model references — or one of the two graph walks, all answered
without scanning the document. Everything a page *says* about a spec
(contained-by, may-contain, …) is composed from these in
[`opm.runtime.spec_xpath_functions`][opm.runtime.spec_xpath_functions], and
can be composed differently in an ODD, a project's own extension module, or —
once opm runs XQuery modules — in XQuery.

Each takes an optional node of the document, to find its index outside a
chunk run, and returns spec idents as a sequence of strings.
"""

from __future__ import annotations

from typing import Any

from lxml import etree

# Aliased: every public callable of an extension module becomes a tp: function.
from opm.runtime.xpath_env import current_environment as _current_environment
from opm.runtime.xpath_extensions import expect_element as _expect_element
from opm.runtime.xpath_extensions import expect_string as _expect_string
from opm.spec_index import SpecIndex

#: Indexes built for documents nobody handed one: (id(root), lang) → (root,
#: index). The chunker evaluates every chunk through a fresh environment view,
#: so caching on the environment would rebuild the index per page; this cache
#: outlives the views. It holds the root itself, which keeps the id from being
#: reused, and only the last few documents, so a long-running process does not
#: keep every tree it ever documented. (lxml elements take no weak references.)
_INDEXES: dict[tuple[int, str], tuple[etree._Element, SpecIndex]] = {}
_INDEXES_KEPT = 4


def _index(node: Any = None) -> SpecIndex | None:
    """The spec index of the document being evaluated.

    The one the caller bound (``opm odd document`` passes its own), else one
    built from the whole document — never from ``$parameters?root``, which is
    only the chunk being rendered — and shared by every chunk of it.
    """
    env = _current_environment()
    if env is not None and env.spec_index is not None:
        return env.spec_index
    start = env.root if env is not None and env.root is not None else node
    if start is None:
        return None
    try:
        root = _expect_element(start, arg_name='spec').getroottree().getroot()
    except ValueError:
        return None
    lang = 'en'
    if env is not None:
        lang = str((env.parameters or {}).get('lng') or 'en')
    key = (id(root), lang)
    cached = _INDEXES.get(key)
    if cached is not None and cached[0] is root:
        return cached[1]
    index = SpecIndex.from_tree(root, lang=lang)
    _INDEXES[key] = (root, index)
    while len(_INDEXES) > _INDEXES_KEPT:
        del _INDEXES[next(iter(_INDEXES))]
    return index


# ── Relations ────────────────────────────────────────────────────────────────
#
# What a documentation page means by "contained by", "may contain", "members",
# "used by" and the attribute tree, derived from the index's primitives: direct
# memberships and content references, and the two graph walks. This is the
# reading of the schema a project changes when it changes one of these lists;
# the index underneath only answers lookups. Each result is computed once per
# document and kept in ``index.memo``.




def _idents(refs) -> list[str]:
    return [ref.ident for ref in refs]


def _keys(value: Any) -> list[str]:
    items = value if isinstance(value, (list, tuple)) else [value]
    return [_expect_string(item, arg_name='key') for item in items if item not in (None, '')]


def spec_members_of(key: Any, node: Any = None) -> list[str]:
    """Specs whose ``memberOf`` names *key* directly, A–Z."""
    index = _index(node)
    return _idents(index.members_of(_expect_string(key, arg_name='key'))) if index else []


def spec_referrers(kind: Any, key: Any, node: Any = None) -> list[str]:
    """Specs whose content model refers to *key* directly.

    *kind*: ``element``, ``class``, ``macro`` or ``data`` — which ``*Ref``.
    """
    index = _index(node)
    if index is None:
        return []
    refs = index.referrers(
        _expect_string(kind, arg_name='kind'), _expect_string(key, arg_name='key'),
    )
    return list(dict.fromkeys(_idents(refs)))


def spec_class_members(key: Any, node: Any = None) -> list[str]:
    """Elements in class *key* or any of its subclasses."""
    index = _index(node)
    return _idents(index.class_members_transitive(_expect_string(key, arg_name='key'))) if index else []


def spec_model_ancestors(keys: Any, node: Any = None) -> list[str]:
    """*keys* and every model class they belong to, walking upward."""
    index = _index(node)
    return index.expand_model_ancestors(_keys(keys)) if index else []


def spec_content_refs(ident: Any, kind: Any = None, node: Any = None) -> list[str]:
    """Keys referenced by *ident*'s content model, of *kind* when given."""
    index = _index(node)
    if index is None:
        return []
    wanted = _expect_string(kind, arg_name='kind') if kind not in (None, '', []) else None
    refs = index.content_refs(_expect_string(ident, arg_name='ident'))
    return list(dict.fromkeys(key for ref_kind, key in refs if wanted in (None, ref_kind)))
