# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Open Processing Model: transform XML with the processing models in an ODD.

Start with :class:`Project`::

    from opm import Project

    html = Project.load().transform('data/doc.xml')
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opm.config import ProjectConfig
    from opm.project import ChunkRun, Project
    from opm.runtime.xpath_diagnostics import XPathErrorLog, collect_xpath_errors

    __version__: str

__all__ = [
    'ChunkRun',
    'Project',
    'ProjectConfig',
    'XPathErrorLog',
    '__version__',
    'collect_xpath_errors',
]

# Imported on first use, so `import opm.config` does not load the whole library.
_EXPORTS = {
    'ChunkRun': 'opm.project',
    'Project': 'opm.project',
    'ProjectConfig': 'opm.config',
    'XPathErrorLog': 'opm.runtime.xpath_diagnostics',
    'collect_xpath_errors': 'opm.runtime.xpath_diagnostics',
}


def __getattr__(name: str) -> Any:
    if name == '__version__':
        from opm.resources import opm_version

        return opm_version()
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
