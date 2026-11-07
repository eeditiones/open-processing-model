# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""jinks templates in Python.

A port of [jinks-templates](https://github.com/eeditiones/jinks-templates), the
templating engine of TEI Publisher, with XPath 3.1 (via elementpath) in place
of XQuery. Templates use ``[[ expr ]]`` for values and ``[% … %]`` for
directives (``if``, ``for``, ``let``, ``include``, ``block``, ``template``),
carry JSON or TOML frontmatter, and inherit from each other through
``templating.extends`` and ``templating.use``.

This package imports nothing from the rest of opm, so it can become a
package of its own. opm connects it to its projects in
[`opm.template_rendering`][opm.template_rendering].

Example:
    >>> from opm.jinks_templates import Environment
    >>> env = Environment()
    >>> env.from_string('<p>[[ $title ]]</p>', 'page.html').render({'title': 'A & B'})
    '<p>A &amp; B</p>'
"""

from .environment import (
    HTML,
    TEXT,
    Environment,
    FileSystemResolver,
    Markup,
    Template,
    convert_results,
    mode_for,
)
from .errors import TemplateError, TemplateNotFound, TemplateRuntimeError, TemplateSyntaxError
from .frontmatter import split_frontmatter
from .merge import merge_deep

__all__ = [
    'HTML',
    'TEXT',
    'Environment',
    'FileSystemResolver',
    'Markup',
    'Template',
    'TemplateError',
    'TemplateNotFound',
    'TemplateRuntimeError',
    'TemplateSyntaxError',
    'convert_results',
    'merge_deep',
    'mode_for',
    'split_frontmatter',
]
