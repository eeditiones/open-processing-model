"""Access packaged stock ODDs, CSS, and related resources."""

from __future__ import annotations

import shutil
from importlib import metadata, resources
from pathlib import Path

from platformdirs import user_cache_dir

_PACKAGE = 'opm'
_RESOURCES = 'resources'


def opm_version() -> str:
    """Return the installed package version, or ``'0'`` if unknown."""
    try:
        return metadata.version('open-processing-model')
    except metadata.PackageNotFoundError:
        return '0'


def user_opm_cache_dir() -> Path:
    """Return the per-user cache root for compiled modules and mirrored resources."""
    return Path(user_cache_dir('opm', appauthor='e-editiones'))


def _packaged_root():
    return resources.files(_PACKAGE).joinpath(_RESOURCES)


def ensure_packaged_odd_dir() -> Path:
    """Mirror packaged ``resources/odd`` into the user cache and return that directory.

    Extracting the whole tree keeps ODD inheritance and sibling ``.css`` files
    resolvable. The mirror is versioned so an upgrade refreshes stock files.
    """
    dest = user_opm_cache_dir() / 'resources' / opm_version() / 'odd'
    if dest.is_dir() and any(dest.glob('*.odd')):
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)

    packaged = _packaged_root().joinpath('odd')
    with resources.as_file(packaged) as src:
        shutil.copytree(src, dest)
    return dest


def packaged_odd(name: str = 'teipublisher') -> Path:
    """Return a filesystem path to a packaged stock ODD (default: teipublisher)."""
    stem = name.removesuffix('.odd')
    path = ensure_packaged_odd_dir() / f'{stem}.odd'
    if not path.is_file():
        available = sorted(p.stem for p in ensure_packaged_odd_dir().glob('*.odd'))
        raise FileNotFoundError(
            f'Packaged ODD {stem!r} not found. Available: {available}',
        )
    return path


def packaged_default_css() -> Path | None:
    """Return the packaged ``default-styles.css``, or ``None`` if absent."""
    packaged = _packaged_root().joinpath('styles', 'default-styles.css')
    try:
        with resources.as_file(packaged) as path:
            if path.is_file():
                # Copy into versioned cache so callers get a stable path.
                dest = user_opm_cache_dir() / 'resources' / opm_version() / 'styles'
                dest.mkdir(parents=True, exist_ok=True)
                out = dest / 'default-styles.css'
                if not out.is_file():
                    shutil.copy2(path, out)
                return out
    except (FileNotFoundError, TypeError, OSError):
        return None
    return None
