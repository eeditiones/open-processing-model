"""Build hook: ship the worked projects under ``examples/`` inside the wheel.

``opm init --example <name>`` copies one of them into a new project, so they have
to travel with the package rather than living only in a git clone.

A plain ``force-include`` map cannot do this: hatchling's ``recurse_forced_files``
filters only ``__pycache__`` / ``.git`` / ``.venv``, never ``.gitignore``, so the
generated ``examples/*/chunks/`` trees — megabytes of HTML that differ per machine
— would end up in the distribution.
"""

from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

#: Directory names that never belong in the distribution.
_SKIP = frozenset({'chunks', 'output', 'site', '__pycache__', '.DS_Store'})

_SOURCE = 'examples'
_TARGET = 'opm/resources/examples'


class ExamplesBuildHook(BuildHookInterface):
    """Force-include ``examples/`` as package data, minus generated output."""

    PLUGIN_NAME = 'custom'

    def initialize(self, version: str, build_data: dict) -> None:
        # An editable install resolves examples from the source tree; copying
        # them into site-packages would only go stale.
        if version == 'editable':
            return

        root = Path(self.root) / _SOURCE
        if not root.is_dir():
            return

        force_include = build_data.setdefault('force_include', {})
        for path in sorted(root.rglob('*')):
            if not path.is_file() or _SKIP & set(path.parts):
                continue
            relative = path.relative_to(root)
            force_include[str(path)] = f'{_TARGET}/{relative.as_posix()}'
