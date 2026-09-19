# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

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


def packaged_document_dir() -> Path:
    """Mirror packaged ``resources/document`` into the user cache and return it.

    The documentation site's ``opm.toml``, page template and static assets live
    here. The mirror is versioned like [`ensure_packaged_odd_dir`][opm.resources.ensure_packaged_odd_dir]
    so editable-install edits show up.
    """
    dest = user_opm_cache_dir() / 'resources' / opm_version() / 'document'
    packaged = _packaged_root().joinpath('document')
    with resources.as_file(packaged) as src:
        _sync_tree(Path(src), dest)
    return dest


def examples_root() -> Path | None:
    """Return the directory holding the bundled example projects, if any.

    Installed wheels carry them as package data (see ``hatch_build.py``). An
    editable install has no such copy, so fall back to the ``examples/`` tree of
    the source checkout — which is also the one a contributor edits.
    """
    packaged = _packaged_root().joinpath('examples')
    try:
        with resources.as_file(packaged) as path:
            if path.is_dir():
                return Path(path)
    except (FileNotFoundError, TypeError, OSError):
        pass
    # src/opm/resources/__init__.py → src/opm/resources → src/opm → src → repo
    source_tree = Path(__file__).resolve().parents[3] / 'examples'
    return source_tree if source_tree.is_dir() else None


def example_names() -> list[str]:
    """Return the names of the bundled example projects, sorted.

    A real bundled example always ships an ``opm.toml`` at its root; that's
    what distinguishes one from an incidental sibling directory under
    ``examples/`` — such as ``output/``, where ad hoc build scripts write
    generated files that were never meant to join the picker's catalogue.
    """
    root = examples_root()
    if root is None:
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and not p.name.startswith('.') and (p / 'opm.toml').is_file()
    )


def example_dir(name: str) -> Path:
    """Return a filesystem path to one bundled example project."""
    root = examples_root()
    path = root / name if root is not None else None
    if path is None or not path.is_dir():
        raise FileNotFoundError(
            f'Example project {name!r} not found. Available: {example_names()}',
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


def packaged_print_css() -> Path | None:
    """Return the packaged print base stylesheet, or ``None`` if absent."""
    return _mirror_packaged_file(('styles', 'print.css'))


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
