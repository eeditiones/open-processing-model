# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Files a web template references, copied next to the pages that use them.

A project lists them under ``[transform.web] assets`` (or ``[chunking]
assets`` for one chunking run). ``opm chunk`` and ``opm transform`` copy them
into an ``assets/`` directory beside their output and hand the template the
stylesheets among them as ``asset_styles``.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

#: The directory the assets are copied into, relative to the output root.
ASSETS_DIR = 'assets'


def resolve_assets(root: Path, assets: Sequence[Path]) -> list[Path]:
    """Expand ``assets`` entries to the paths to copy.

    An entry holding ``*``, ``?`` or ``[`` is matched against the filesystem, so
    ``iiif/*`` copies every document's directory in one line instead of naming
    each one — and keeps working when a document is added. Matches are sorted,
    which fixes the cascade order of any stylesheets among them. Every other
    entry is taken literally. Relative entries resolve against *root*.

    A literal path that does not exist, or a pattern matching nothing, raises
    ``FileNotFoundError``. The alternative is output quietly missing a file a
    template or model expects, which surfaces much later as a 404.
    """
    resolved: list[Path] = []
    for asset in assets:
        source = asset if asset.is_absolute() else root / asset
        text = str(source)
        if any(char in text for char in '*?['):
            pattern = str(source.relative_to(source.anchor))
            matches = sorted(Path(source.anchor).glob(pattern))
            if not matches:
                raise FileNotFoundError(f'Asset pattern matched nothing: {source}')
            resolved.extend(matches)
        elif source.exists():
            resolved.append(source)
        else:
            raise FileNotFoundError(f'Asset not found: {source}')
    return resolved


def copy_assets(root: Path, assets: Sequence[Path], output_root: Path) -> list[Path]:
    """Copy *assets* into ``<output_root>/assets/`` and return their sources.

    Each entry keeps its own name, a directory its whole tree. Copying again
    over an earlier run is safe.
    """
    sources = resolve_assets(root, assets)
    if not sources:
        return sources
    target_dir = output_root / ASSETS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    for source in sources:
        target = target_dir / source.name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return sources


def asset_styles(sources: Sequence[Path], prefix: str = '') -> list[str]:
    """URLs of the stylesheets among *sources*, in the order they were declared.

    That is the cascade order, so a template can link them blind. *prefix* is
    the path from the page back to the output root (``../`` for a chunk page).
    """
    return [
        f'{prefix}{ASSETS_DIR}/{source.name}'
        for source in sources
        if source.suffix.lower() == '.css'
    ]
