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


def _sync_tree(src: Path, dest: Path) -> None:
    """Copy *src* into *dest*, replacing files whose contents differ."""
    dest.mkdir(parents=True, exist_ok=True)
    src_files = {p.relative_to(src) for p in src.rglob('*') if p.is_file()}
    dest_files = {p.relative_to(dest) for p in dest.rglob('*') if p.is_file()}
    for rel in dest_files - src_files:
        (dest / rel).unlink(missing_ok=True)
    for rel in src_files:
        s = src / rel
        d = dest / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if not d.is_file() or d.read_bytes() != s.read_bytes():
            shutil.copy2(s, d)


def ensure_packaged_odd_dir() -> Path:
    """Mirror packaged ``resources/odd`` into the user cache and return that directory.

    Extracting the whole tree keeps ODD inheritance and sibling ``.css`` files
    resolvable. The mirror is versioned so an upgrade refreshes stock files, and
    file contents are compared so editable installs pick up ODD edits.
    """
    dest = user_opm_cache_dir() / 'resources' / opm_version() / 'odd'
    packaged = _packaged_root().joinpath('odd')
    with resources.as_file(packaged) as src:
        _sync_tree(Path(src), dest)
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
    return _mirror_packaged_file(('styles', 'default-styles.css'))


def packaged_default_docx() -> Path | None:
    """Return the packaged Word style template, or ``None`` if absent."""
    return _mirror_packaged_file(('templates', 'default.docx'))


def packaged_epub_css() -> Path | None:
    """Return the packaged EPUB base stylesheet, or ``None`` if absent."""
    return _mirror_packaged_file(('styles', 'epub.css'))


def _mirror_packaged_file(parts: tuple[str, ...]) -> Path | None:
    """Copy a packaged resource into the user cache and return that path."""
    packaged = _packaged_root().joinpath(*parts)
    try:
        with resources.as_file(packaged) as path:
            if path.is_file():
                dest_dir = user_opm_cache_dir() / 'resources' / opm_version() / Path(*parts[:-1])
                dest_dir.mkdir(parents=True, exist_ok=True)
                out = dest_dir / parts[-1]
                shutil.copy2(path, out)
                return out
    except (FileNotFoundError, TypeError, OSError):
        return None
    return None
