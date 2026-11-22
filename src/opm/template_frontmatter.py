# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ``context`` page templates are rendered with.

The packaged defaults (``opm/defaults.toml``) lie beneath the project's
``[context]``; the jinks engine merges each template's frontmatter over both
while rendering. See [`merge_deep`][opm.jinks_templates.merge.merge_deep] for
how values combine.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from opm.jinks_templates.merge import merge_deep

__all__ = ['merge_deep', 'template_context', 'context_defaults']

#: Defaults for the template context, among the packaged templates.
DEFAULTS_FILE = 'opm/defaults.toml'


def template_context(base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The ``context`` to render a page template with.

    *base* is the project's context (``[context]`` overlaid by
    ``[transform.<type>.context]``), merged over the packaged
    [`context_defaults`][opm.template_frontmatter.context_defaults] with
    [`merge_deep`][opm.jinks_templates.merge.merge_deep]. The template's
    frontmatter is not added here: the jinks engine merges it when it renders.
    """
    return merge_deep(context_defaults(), base)


@cache
def _context_defaults() -> dict[str, Any]:
    path = Path(str(resources.files('opm').joinpath(f'resources/templates/{DEFAULTS_FILE}')))
    return tomllib.loads(path.read_text(encoding='utf-8'))


def context_defaults() -> dict[str, Any]:
    """The packaged defaults beneath every template ``context``.

    Read from ``opm/defaults.toml`` among the packaged templates: the settings
    the packaged layouts understand, such as ``theme.layout.after.width``. A project
    overrides them in ``[context]`` and a template in its frontmatter.
    """
    return merge_deep(_context_defaults())
