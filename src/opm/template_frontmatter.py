# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frontmatter in Jinja2 templates, merged into the template ``context``.

A template may open with a block of JSON or TOML between two ``---`` lines,
as in jinks::

    {# SPDX header comments may come first #}
    ---toml
    styles = ["https://fonts.googleapis.com/css2?family=Belleza"]
    [layout.after]
    width = "22rem"
    ---
    {% extends "opm/layout.html.j2" %}

The block is removed before Jinja2 sees the source. Its values are merged over
the packaged defaults (``opm/defaults.toml``) and the project's ``[context]``
along the template's ``{% extends %}`` chain: the root layout first, the
rendered template last, so a child overrides its parent and frontmatter
overrides ``opm.toml``. See
[`merge_deep`][opm.template_frontmatter.merge_deep] for how values combine.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, nodes

# Leading whitespace and {# … #} comments, then ---[json|toml] … ---.
_FRONTMATTER = re.compile(
    r'\A(?P<prefix>(?:\s*\{#.*?#\})*\s*)'
    r'---(?P<syntax>[A-Za-z]*)[ \t]*\r?\n'
    r'(?P<body>.*?)\r?\n'
    r'---[ \t]*(?:\r?\n|\Z)',
    re.DOTALL,
)

_REPLACE = '$replace'

#: Defaults for the template context, among the packaged templates.
DEFAULTS_FILE = 'opm/defaults.toml'


def split_frontmatter(source: str, name: str = '<template>') -> tuple[dict[str, Any], str]:
    """Return the frontmatter of *source* as a dict, and the source without it.

    The block is replaced by a Jinja2 comment spanning as many lines, so it
    outputs nothing and line numbers in Jinja2 error messages still match the
    file. ``---json`` and a bare ``---``
    hold JSON, ``---toml`` holds TOML. A source without frontmatter comes back
    unchanged with an empty dict.

    Raises:
        ValueError: The block names another syntax or does not parse.
    """
    match = _FRONTMATTER.match(source)
    if match is None:
        return {}, source
    syntax = match['syntax'].lower() or 'json'
    body = match['body']
    try:
        if syntax == 'json':
            data = json.loads(body)
        elif syntax == 'toml':
            data = tomllib.loads(body)
        else:
            raise ValueError(f'unsupported frontmatter syntax "{syntax}" (use json or toml)')
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f'{name}: invalid {syntax} frontmatter: {e}') from e
    if not isinstance(data, dict):
        raise ValueError(f'{name}: frontmatter must be an object')
    # A Jinja comment spanning the same lines as the whitespace and block it
    # replaces: line numbers stay, and nothing is output in their place.
    prefix = match['prefix'].rstrip()
    lines = source[len(prefix):match.end()].count('\n')
    stripped = prefix + '{#' + '\n' * lines + '#}' + source[match.end():]
    return data, stripped


def _array_key(value: Any) -> Any:
    if isinstance(value, Mapping):
        if 'id' in value:
            return ('id', json.dumps(value['id'], sort_keys=True, default=str))
        return ('json', json.dumps(value, sort_keys=True, default=str))
    if isinstance(value, list):
        return ('json', json.dumps(value, sort_keys=True, default=str))
    return ('value', value)


def _merge_arrays(arrays: list[list[Any]]) -> list[Any]:
    merged: list[Any] = []
    seen: set[Any] = set()
    for array in arrays:
        for value in array:
            key = _array_key(value)
            if key not in seen:
                seen.add(key)
                merged.append(value)
    return merged


def merge_deep(*maps: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge *maps* left to right, the way jinks merges context maps.

    - A scalar replaces an earlier value under the same key.
    - Maps merge recursively. A map holding ``"$replace": true`` replaces the
      earlier map instead; ``"$replace": ["a", "b"]`` replaces only those keys
      and merges the rest.
    - Arrays are concatenated with duplicates dropped: maps with an ``id``
      compare by it, other values by their JSON form.

    ``$replace`` itself never ends up in the result.
    """
    return _merge([m for m in maps if m])


def _copy(value: Any) -> Any:
    return _merge([value]) if isinstance(value, Mapping) else value


def _merge(maps: list[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for incoming in maps:
        replace = incoming.get(_REPLACE)
        if replace is True:
            result = {}
        replaced = set(replace) if isinstance(replace, list) else set()
        for key, value in incoming.items():
            if key == _REPLACE:
                continue
            current = result.get(key)
            if key in replaced or key not in result:
                result[key] = _copy(value)
            elif isinstance(current, dict) and isinstance(value, Mapping):
                result[key] = _merge([current, value])
            elif isinstance(current, list) and isinstance(value, list):
                result[key] = _merge_arrays([current, value])
            else:
                result[key] = _copy(value)
    return result


class FrontmatterLoader(FileSystemLoader):
    """A ``FileSystemLoader`` that removes frontmatter and remembers it."""

    def __init__(self, searchpath: Any, **kwargs: Any) -> None:
        super().__init__(searchpath, **kwargs)
        self._frontmatter: dict[str, dict[str, Any]] = {}
        self._contexts: dict[str, dict[str, Any]] = {}

    def get_source(self, environment: Environment, template: str):  # type: ignore[override]
        source, filename, uptodate = super().get_source(environment, template)
        data, stripped = split_frontmatter(source, filename or template)
        self._frontmatter[template] = data
        return stripped, filename, uptodate

    def frontmatter(self, environment: Environment, template: str) -> dict[str, Any]:
        """The frontmatter of *template*, loading it if need be."""
        if template not in self._frontmatter:
            self.get_source(environment, template)
        return self._frontmatter[template]

    def chain(self, environment: Environment, template: str) -> list[str]:
        """*template* and the templates it extends, root layout first."""
        names: list[str] = []
        current: str | None = template
        while current is not None and current not in names:
            names.append(current)
            source, _, _ = self.get_source(environment, current)
            current = _extended(environment, source)
        return names[::-1]

    def context(self, environment: Environment, template: str) -> dict[str, Any]:
        """The frontmatter of *template*'s extends chain, merged root first."""
        if template not in self._contexts:
            self._contexts[template] = merge_deep(
                *(self.frontmatter(environment, name) for name in self.chain(environment, template))
            )
        return self._contexts[template]


def _extended(environment: Environment, source: str) -> str | None:
    """The template *source* extends, when it names one by a constant."""
    for node in environment.parse(source).find_all(nodes.Extends):
        if isinstance(node.template, nodes.Const) and isinstance(node.template.value, str):
            return node.template.value
        return None
    return None


def template_context(
    environment: Environment,
    template: str,
    base: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The ``context`` to render *template* with: *base*, then its frontmatter.

    *base* is the project's context (``[context]`` overlaid by
    ``[transform.<type>.context]``). It is merged over the packaged
    [`context_defaults`][opm.template_frontmatter.context_defaults], and the
    frontmatter along the extends chain over both, with
    [`merge_deep`][opm.template_frontmatter.merge_deep].
    An environment whose loader is not a
    [`FrontmatterLoader`][opm.template_frontmatter.FrontmatterLoader] adds
    neither.
    """
    loader = environment.loader
    if not isinstance(loader, FrontmatterLoader):
        return dict(base or {})
    try:
        frontmatter = loader.context(environment, template)
    except TemplateNotFound:
        frontmatter = {}
    return merge_deep(context_defaults(), base, frontmatter)


@cache
def _context_defaults() -> dict[str, Any]:
    path = Path(str(resources.files('opm').joinpath(f'resources/templates/{DEFAULTS_FILE}')))
    return tomllib.loads(path.read_text(encoding='utf-8'))


def context_defaults() -> dict[str, Any]:
    """The packaged defaults beneath every template ``context``.

    Read from ``opm/defaults.toml`` among the packaged templates: the settings
    the packaged layouts understand, such as ``layout.after.width``. A project
    overrides them in ``[context]`` and a template in its frontmatter.
    """
    return merge_deep(_context_defaults())
