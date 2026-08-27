"""Compile-on-demand cache for ODD → Python transform modules."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from opm.odd_compiler import compile_odd
from opm.odd_compiler.parse_odd import resolve_schema_source
from opm.resources import opm_version, user_opm_cache_dir

TEI_NS = 'http://www.tei-c.org/ns/1.0'
_PARSER = etree.XMLParser(collect_ids=False)


@dataclass(frozen=True)
class ResolvedTransform:
    """A loadable transform module, optionally produced from an ODD."""

    module_path: Path
    source_odd: Path | None = None
    freshly_compiled: bool = False


def modules_cache_dir() -> Path:
    """Return ``…/opm/modules`` under the platform user cache directory."""
    return user_opm_cache_dir() / 'modules'


def _iter_input_files(odd_path: Path, *, leaf_dir: Path, seen: set[Path]) -> list[Path]:
    """Collect the ODD inheritance chain and referenced CSS files for hashing."""
    odd_path = odd_path.resolve()
    if odd_path in seen:
        return []
    seen.add(odd_path)
    files = [odd_path]

    tree = etree.parse(str(odd_path), _PARSER)
    root = tree.getroot()

    for spec in root.iter(f'{{{TEI_NS}}}schemaSpec'):
        for token in (spec.get('source') or '').split():
            parent = resolve_schema_source(token, odd_path)
            files.extend(_iter_input_files(parent, leaf_dir=leaf_dir, seen=seen))

    for rend in root.iter(f'{{{TEI_NS}}}rendition'):
        src = (rend.get('source') or '').strip()
        if not src:
            continue
        # Match css_generator: sources resolve against the leaf ODD directory,
        # but also accept a sibling of the declaring ODD.
        for candidate in (leaf_dir / src, odd_path.parent / src):
            resolved = candidate.resolve()
            if resolved.is_file() and resolved not in seen:
                seen.add(resolved)
                files.append(resolved)
                break

    return files


def cache_key(odd_path: Path, output_mode: str, base_css: str | None = None) -> str:
    """Return a content hash covering the ODD chain, CSS inputs, mode, and opm version."""
    odd_path = odd_path.resolve()
    h = hashlib.sha256()
    h.update(opm_version().encode())
    h.update(b'\0')
    h.update(output_mode.encode())
    h.update(b'\0')

    # The base rules are compiled into ODD_GENERATED_CSS, so a project that
    # overrides them via [document] css needs its own cached module — and
    # editing the packaged default in a checkout has to invalidate too.
    from opm.odd_compiler.css_generator import default_base_css

    effective_base = default_base_css() if base_css is None else base_css
    h.update(effective_base.encode())
    h.update(b'\0')

    for path in _iter_input_files(odd_path, leaf_dir=odd_path.parent, seen=set()):
        h.update(str(path).encode())
        h.update(b'\0')
        h.update(path.read_bytes())
        h.update(b'\0')

    return h.hexdigest()


def cached_module_path(
    odd_path: Path,
    output_mode: str,
    digest: str | None = None,
    base_css: str | None = None,
) -> Path:
    """Return the cache path for *odd_path* in *output_mode* (does not compile)."""
    odd_path = Path(odd_path)
    digest = digest or cache_key(odd_path, output_mode, base_css)
    return modules_cache_dir() / f'{odd_path.stem}-{output_mode}-{digest[:12]}.py'


def ensure_compiled_module(
    odd_path: Path | str,
    *,
    output_mode: str = 'web',
    module_name: str | None = None,
    base_css: str | None = None,
) -> tuple[Path, bool]:
    """Return ``(module_path, freshly_compiled)`` for *odd_path*.

    On a cache miss, compiles the ODD into the user cache directory and returns
    the new path. On a hit, returns the existing cached module unchanged.
    """
    odd_path = Path(odd_path).resolve()
    if not odd_path.is_file():
        raise FileNotFoundError(f'ODD not found: {odd_path}')

    mode = (output_mode or 'web').strip().lower() or 'web'
    digest = cache_key(odd_path, mode, base_css)
    dest = cached_module_path(odd_path, mode, digest, base_css)
    if dest.is_file():
        return dest, False

    dest.parent.mkdir(parents=True, exist_ok=True)
    name = module_name or odd_path.stem
    src = compile_odd(
        str(odd_path), module_name=name, output_mode=mode, base_css=base_css
    )
    dest.write_text(src, encoding='utf-8')
    return dest, True


def resolve_transform_module(
    *,
    module: Path | None = None,
    odd: Path | None = None,
    output_mode: str = 'web',
    use_packaged_default: bool = True,
    base_css: str | None = None,
) -> ResolvedTransform:
    """Resolve a loadable ``.py`` module from an explicit path, ODD, or packaged default.

    Precedence: *module* → *odd* → packaged ``teipublisher.odd`` (when
    *use_packaged_default* is true).

    *base_css* replaces the packaged rules prepended to the generated
    stylesheet, and is part of the cache key, so a project overriding them gets
    its own compiled module.
    """
    if module is not None:
        return ResolvedTransform(module_path=Path(module), source_odd=None, freshly_compiled=False)

    odd_path = Path(odd) if odd is not None else None
    if odd_path is None and use_packaged_default:
        from opm.resources import packaged_odd

        odd_path = packaged_odd('teipublisher')

    if odd_path is None:
        raise ValueError(
            'No transform ODD specified. '
            'Pass --odd, set transform.odd (or transform.<type>.odd) in config, '
            'or install the package with stock ODDs.',
        )

    path, fresh = ensure_compiled_module(
        odd_path, output_mode=output_mode, base_css=base_css
    )
    return ResolvedTransform(module_path=path, source_odd=odd_path, freshly_compiled=fresh)
