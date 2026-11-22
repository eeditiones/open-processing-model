# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frontmatter of jinks templates.

A template may carry a block of JSON (``---json`` or a bare ``---``) or TOML
(``---toml``) between two ``---`` lines. As in jinks, the block may follow the
template's first tag, so an HTML template can stay well-formed::

    <article>
    ---json
    { "templating": { "extends": "pages/page.html" } }
    ---
    ...
    </article>

Comments (``[# … #]``) may come before it, e.g. an SPDX header.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from typing import Any

from .errors import TemplateSyntaxError

_FRONTMATTER = re.compile(
    r'\A(?P<prefix>(?:\s*\[\#.*?\#\])*(?:\s*<[^>]*>)?)'
    r'\s*---(?P<syntax>[A-Za-z]*)[ \t]*\r?\n'
    r'(?P<body>.*?)\r?\n\s*---[ \t]*(?=\r?\n|\Z)'
    r'(?P<rest>.*)\Z',
    re.DOTALL,
)


@dataclass(frozen=True)
class Frontmatter:
    """A template's frontmatter and its source without it.

    Attributes:
        data: The parsed frontmatter, empty when there is none.
        source: The template with the frontmatter block removed.
        start: Offset in *source* where the removed block was.
        lines: Number of lines the removed block spanned, to keep line numbers
            in error messages pointing into the original file.
    """

    data: dict[str, Any]
    source: str
    start: int = 0
    lines: int = 0

    def line_of(self, offset: int) -> int:
        """The 1-based line in the original file of *offset* in *source*."""
        line = self.source.count('\n', 0, offset) + 1
        return line + self.lines if offset >= self.start and self.lines else line


def split_frontmatter(source: str, name: str | None = None) -> Frontmatter:
    """Split *source* into its frontmatter and the rest.

    Raises:
        TemplateSyntaxError: The block names another syntax, does not parse, or
            is not an object.
    """
    match = _FRONTMATTER.match(source)
    if match is None:
        return Frontmatter({}, source)
    syntax = match['syntax'].lower() or 'json'
    body = match['body']
    try:
        if syntax == 'json':
            data = json.loads(body)
        elif syntax == 'toml':
            data = tomllib.loads(body)
        else:
            raise TemplateSyntaxError(
                f'unsupported frontmatter type "{syntax}" (use json or toml)', name)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as e:
        raise TemplateSyntaxError(f'invalid {syntax} frontmatter: {e}', name) from e
    if not isinstance(data, dict):
        raise TemplateSyntaxError('frontmatter must be an object', name)
    prefix = match['prefix']
    removed = source[len(prefix):match.start('rest')]
    return Frontmatter(data, prefix + match['rest'], len(prefix), removed.count('\n'))
