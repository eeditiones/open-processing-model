# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Profile support for opm.

Profiles are reusable packages of templates, CSS, JavaScript, and configuration
that can be shared across multiple opm projects. They are inspired by jinks'
profile system but adapted for opm's static site generation model.

A profile is a directory containing:
- opm-profile.toml: Profile metadata and configuration
- templates/: Template files (.tpl)
- assets/: CSS, JavaScript, and other static assets
- README.md: Documentation

Profiles can be loaded from:
1. The project's local profiles/ directory
2. ~/.opm/profiles/ (user profiles)
3. Bundled profiles in opm.resources.profiles
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from opm.template_frontmatter import merge_deep


# Default locations to search for profiles, in order of precedence
PROFILE_LOCATIONS = [
    # Project-local profiles
    Path("profiles"),
    # User profiles
    Path.home() / ".opm" / "profiles",
]


@dataclass
class ProfileConfig:
    """Configuration for a single profile.
    
    Loaded from opm-profile.toml in the profile directory.
    """
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    
    # Templates every HTML page uses, from [templating] use: their blocks
    # fill the page's blocks unless the page template sets them itself.
    use: tuple[str, ...] = ()

    # Files or directories, relative to the profile directory, copied into
    # the output's assets/ directory; stylesheets among them are linked
    # from every page, before the project's own.
    assets: list[str] = field(default_factory=list)

    # [[chunking.fragments]] tables, added to every chunking run unless the
    # project declares a fragment of the same name.
    fragments: list[dict[str, Any]] = field(default_factory=list)

    # [[pages]] tables, added to the site unless the project declares a page
    # with the same path. Parsed by opm.config.parse_pages when the project
    # merges them: template/odd resolve against the profile directory,
    # source against the project root.
    pages: list[dict[str, Any]] = field(default_factory=list)

    # Configuration defaults to merge into project config
    config: dict[str, Any] = field(default_factory=dict)

    # Functions to call at fixed points, by hook name (see HOOKS), each
    # written as ``file.py:function`` relative to the profile directory.
    hooks: dict[str, tuple[str, ...]] = field(default_factory=dict)
    
    @classmethod
    def from_path(cls, profile_path: Path) -> ProfileConfig:
        """Load a profile from its directory."""
        profile_file = profile_path / "opm-profile.toml"
        if not profile_file.is_file():
            raise FileNotFoundError(
                f"Profile {profile_path} is missing required opm-profile.toml"
            )
        
        with open(profile_file, "rb") as f:
            data = tomllib.load(f)
        
        _check_keys(data, profile_file)

        # Extract known fields
        config_data = {}
        known_fields = {'name', 'version', 'description', 'author', 'assets'}
        
        for key in known_fields:
            if key in data:
                config_data[key] = data[key]
        
        # Handle config: can be provided as [config] or individual top-level keys
        # Build the config dict from [config] section, plus handle [context] at top level
        profile_config = {}
        if 'config' in data:
            profile_config.update(data['config'])
        # Also check for top-level [context] and merge into config.context
        if 'context' in data:
            profile_config.setdefault('context', {}).update(data['context'])
        
        if profile_config:
            config_data['config'] = profile_config

        use = (data.get('templating') or {}).get('use')
        if use:
            config_data['use'] = (use,) if isinstance(use, str) else tuple(str(u) for u in use)
        fragments = (data.get('chunking') or {}).get('fragments')
        if fragments:
            if not isinstance(fragments, list) or not all(isinstance(f, dict) for f in fragments):
                raise ValueError(f'Profile {profile_path}: [[chunking.fragments]] must be tables')
            config_data['fragments'] = fragments

        pages = data.get('pages')
        if pages:
            if not isinstance(pages, list) or not all(isinstance(p, dict) for p in pages):
                raise ValueError(f'Profile {profile_path}: [[pages]] must be an array of tables')
            config_data['pages'] = pages

        if 'hooks' in data:
            config_data['hooks'] = _parse_hooks(data['hooks'], profile_path)
        
        # Ensure name is set
        if 'name' not in config_data:
            config_data['name'] = profile_path.name
        
        return cls(**config_data)


#: The keys an ``opm-profile.toml`` may hold, and those of its tables.
_PROFILE_KEYS = {
    '': {'name', 'version', 'description', 'author', 'assets', 'pages',
         'templating', 'chunking', 'hooks', 'context', 'config'},
    'templating': {'use'},
    'chunking': {'fragments'},
}


def _check_keys(data: dict[str, Any], profile_file: Path) -> None:
    """Reject unknown keys, which are mostly keys written below the wrong table.

    In TOML a key after a ``[table]`` header belongs to that table, so
    ``assets = [...]`` placed after ``[templating]`` would otherwise be
    silently ignored.
    """
    for table, allowed in _PROFILE_KEYS.items():
        values = data if table == '' else data.get(table)
        if not isinstance(values, dict):
            continue
        unknown = sorted(set(values) - allowed)
        if unknown:
            where = f'[{table}]' if table else 'the top level'
            raise ValueError(
                f"{profile_file}: unknown key(s) {', '.join(unknown)} in {where}. "
                'A key written after a [table] header belongs to that table; '
                'top-level keys go before the first header.'
            )


#: The hooks a profile can register in its ``[hooks]`` table.
HOOKS = ('after_chunking',)


def _parse_hooks(table: Any, profile_path: Path) -> dict[str, tuple[str, ...]]:
    """Validate a profile's ``[hooks]`` table: known names, ``file:function`` entries."""
    if not isinstance(table, dict):
        raise ValueError(f'Profile {profile_path}: [hooks] must be a table')
    hooks: dict[str, tuple[str, ...]] = {}
    for name, value in table.items():
        if name not in HOOKS:
            raise ValueError(
                f"Profile {profile_path}: unknown hook '{name}' (known: {', '.join(HOOKS)})"
            )
        entries = (value,) if isinstance(value, str) else tuple(value)
        for entry in entries:
            if not isinstance(entry, str) or ':' not in entry:
                raise ValueError(
                    f"Profile {profile_path}: hook '{name}' entry {entry!r} "
                    "must be written as 'file.py:function'"
                )
        hooks[name] = entries
    return hooks


def load_hook(profile_name: str, profile_path: Path, entry: str) -> Callable[..., Any]:
    """The function a hook *entry* (``file.py:function``) names in a profile.

    The file is loaded from *profile_path* under a module name of its own, so
    two profiles may each ship a ``search.py`` without clashing.

    Raises:
        FileNotFoundError: The file does not exist.
        AttributeError: The file has no such function.
    """
    file_name, _, function_name = entry.rpartition(':')
    path = profile_path / file_name
    if not path.is_file():
        raise FileNotFoundError(f"Profile '{profile_name}': hook file not found: {path}")
    module_name = f'opm_profile_{profile_name}_{path.stem}'.replace('-', '_')
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered like an import, so dataclasses and pickling in it work.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[module_name]
        raise
    function = getattr(module, function_name, None)
    if not callable(function):
        raise AttributeError(f"Profile '{profile_name}': {path.name} has no function '{function_name}'")
    return function


def find_profile(profile_name: str, search_paths: list[Path] | None = None) -> Path:
    """Find a profile by name in the search paths.
    
    Args:
        profile_name: Name of the profile to find
        search_paths: List of paths to search (defaults to PROFILE_LOCATIONS)
        
    Returns:
        Path to the profile directory
        
    Raises:
        FileNotFoundError: If the profile is not found in any search path
    """
    if search_paths is None:
        search_paths = PROFILE_LOCATIONS
    
    for base_path in search_paths:
        profile_path = base_path / profile_name
        if profile_path.is_dir():
            return profile_path
    
    raise FileNotFoundError(
        f"Profile '{profile_name}' not found in any of: "
        f"{', '.join(str(p) for p in search_paths)}"
    )


def load_profile(profile_name: str, search_paths: list[Path] | None = None) -> ProfileConfig:
    """Load a profile by name.
    
    Args:
        profile_name: Name of the profile to load
        search_paths: List of paths to search (defaults to PROFILE_LOCATIONS)
        
    Returns:
        ProfileConfig for the profile
    """
    profile_path = find_profile(profile_name, search_paths)
    return ProfileConfig.from_path(profile_path)


def load_profiles(profile_names: list[str], search_paths: list[Path] | None = None) -> list[ProfileConfig]:
    """Load multiple profiles by name.
    
    Args:
        profile_names: List of profile names to load
        search_paths: List of paths to search (defaults to PROFILE_LOCATIONS)
        
    Returns:
        List of ProfileConfig objects
    """
    profiles = []
    for name in profile_names:
        profiles.append(load_profile(name, search_paths))
    return profiles


def get_profile_paths(profile_config: ProfileConfig, profile_path: Path) -> tuple[Path, ...]:
    """Get the full paths for a profile's assets.
    
    Args:
        profile_config: The profile configuration
        profile_path: Path to the profile directory
        
    Returns:
        Tuple of absolute paths to the profile's assets
    """
    assets = []
    for asset_pattern in profile_config.assets:
        asset_path = profile_path / asset_pattern
        if asset_path.is_file():
            assets.append(asset_path.resolve())
        elif asset_path.is_dir():
            # For directories, include all files recursively
            assets.extend(p.resolve() for p in asset_path.rglob("*") if p.is_file())
    return tuple(assets)


def merge_profile_configs(
    base_config: dict[str, Any],
    profile_configs: list[ProfileConfig]
) -> dict[str, Any]:
    """Merge configuration from multiple profiles into a base configuration.
    
    Profile configurations are merged in order, with later profiles overriding
    earlier ones. Each profile's config is merged deeply with the base.
    
    Args:
        base_config: Base configuration to merge into
        profile_configs: List of profile configurations to merge
        
    Returns:
        Merged configuration dictionary
    """
    merged = base_config.copy()
    for profile in profile_configs:
        merged = merge_deep(merged, profile.config)
    return merged


# ── choosing a project's profiles ────────────────────────────────────────────

#: The profiles that ship with opm.
PACKAGED_PROFILES = Path(__file__).parent / 'resources' / 'profiles'


def profile_search_paths(project_root: Path | None = None) -> list[Path]:
    """Where a project's profiles are looked up, first match wins.

    The project's own ``profiles/`` directory, then ``~/.opm/profiles``, then
    the profiles packaged with opm. Without *project_root*, the current
    directory stands in for the project.
    """
    root = project_root if project_root is not None else Path.cwd()
    return [root / 'profiles', Path.home() / '.opm' / 'profiles', PACKAGED_PROFILES]


@dataclass(frozen=True)
class AvailableProfile:
    """A profile a project can use, as [`available_profiles`][opm.profile.available_profiles] finds it."""

    name: str
    description: str
    path: Path
    #: ``project``, ``user`` or ``packaged``: which search path it came from.
    origin: str


def available_profiles(project_root: Path | None = None) -> list[AvailableProfile]:
    """Every profile a project at *project_root* can name, sorted by name.

    A profile found in several places is listed once, from the place that
    wins (see [`profile_search_paths`][opm.profile.profile_search_paths]).
    A directory without ``opm-profile.toml`` is not a profile.
    """
    origins = ('project', 'user', 'packaged')
    found: dict[str, AvailableProfile] = {}
    for origin, base in zip(origins, profile_search_paths(project_root)):
        if not base.is_dir():
            continue
        for path in sorted(base.iterdir()):
            if path.name in found or not (path / 'opm-profile.toml').is_file():
                continue
            try:
                description = ProfileConfig.from_path(path).description
            except (OSError, ValueError, tomllib.TOMLDecodeError):
                description = ''
            found[path.name] = AvailableProfile(path.name, description, path, origin)
    return [found[name] for name in sorted(found)]


_TABLE_HEADER = re.compile(r'^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$')
_PROFILES_KEY = re.compile(r'^\s*profiles\s*=')
_PROFILES_HINT = re.compile(r'^\s*#\s*profiles\s*=.*$')


def read_project_profiles(config_path: Path) -> list[str]:
    """The ``[project] profiles`` of the ``opm.toml`` at *config_path*."""
    with config_path.open('rb') as f:
        data = tomllib.load(f)
    project = data.get('project')
    raw = project.get('profiles', []) if isinstance(project, dict) else []
    if isinstance(raw, str):
        return [raw]
    return [str(name) for name in raw] if isinstance(raw, list) else []


def write_project_profiles(config_path: Path, profiles: list[str]) -> None:
    """Set ``[project] profiles`` in the ``opm.toml`` at *config_path*.

    Only that one setting changes: the rest of the file, comments included,
    stays as written. An existing ``profiles = [...]`` (on one line or
    several) is replaced, else a commented-out ``# profiles = ...`` line;
    otherwise the line goes right below ``[project]``,
    and a missing ``[project]`` table is added before the first table.

    Raises:
        ValueError: The edited file would not read back with *profiles*.
    """
    text = config_path.read_text(encoding='utf-8')
    lines = text.splitlines(keepends=True)
    newline = '\r\n' if '\r\n' in text else '\n'
    value = f'profiles = [{", ".join(_toml_string(name) for name in profiles)}]{newline}'

    header = next(
        (i for i, line in enumerate(lines)
         if (m := _TABLE_HEADER.match(line)) and m.group(1) == 'project' and not line.lstrip().startswith('[[')),
        None,
    )
    if header is None:
        first_table = next((i for i, line in enumerate(lines) if _TABLE_HEADER.match(line)), len(lines))
        lines[first_table:first_table] = [f'[project]{newline}', value, newline]
    else:
        end = next(
            (i for i in range(header + 1, len(lines)) if _TABLE_HEADER.match(lines[i])),
            len(lines),
        )
        start = next((i for i in range(header + 1, end) if _PROFILES_KEY.match(lines[i])), None)
        hint = next((i for i in range(header + 1, end) if _PROFILES_HINT.match(lines[i])), None)
        if start is None and hint is not None:
            # The commented-out example `opm init` writes becomes the setting.
            lines[hint] = value
        elif start is None:
            lines.insert(header + 1, value)
        else:
            stop = start
            # A list over several lines ends at the line closing its bracket.
            depth = 0
            for stop in range(start, end):
                depth += _bracket_depth(lines[stop])
                if depth <= 0:
                    break
            lines[start:stop + 1] = [value]

    edited = ''.join(lines)
    if not edited.endswith(('\n', '\r\n')):
        edited += newline
    try:
        reread = tomllib.loads(edited).get('project', {}).get('profiles')
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f'{config_path}: could not set [project] profiles: {exc}') from exc
    if reread != list(profiles):
        raise ValueError(f'{config_path}: could not set [project] profiles; edit the file by hand')
    config_path.write_text(edited, encoding='utf-8')


def _toml_string(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _bracket_depth(line: str) -> int:
    """How many more ``[`` than ``]`` *line* opens, outside strings and comments."""
    depth = 0
    quote = ''
    for char in line:
        if quote:
            if char == quote:
                quote = ''
        elif char in '"\'':
            quote = char
        elif char == '#':
            break
        elif char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
    return depth


# ── a profile's README ───────────────────────────────────────────────────────

#: The README heading whose section ``opm profile add`` prints.
SETUP_HEADING = 'Before you start'

_HEADING = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')


def profile_readme(profile_path: Path) -> str | None:
    """The text of the profile's ``README.md``, or ``None`` without one."""
    readme = profile_path / 'README.md'
    return readme.read_text(encoding='utf-8') if readme.is_file() else None


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """``(line index, level, title)`` of every heading outside code blocks."""
    found = []
    fence = ''
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = ''
            continue
        if stripped.startswith(('```', '~~~')):
            fence = stripped[:3]
            continue
        if (m := _HEADING.match(line)):
            found.append((index, len(m.group(1)), m.group(2)))
    return found


def top_level_headings(text: str) -> str:
    """*text* with its headings shifted so the highest is level 1.

    The packaged READMEs start at level 3, to sit inside the documentation
    page that includes them; on their own they read from the top.
    """
    lines = text.splitlines()
    headings = _headings(lines)
    if not headings:
        return text
    shift = min(level for _, level, _ in headings) - 1
    for index, level, title in headings:
        lines[index] = f'{"#" * (level - shift)} {title}'
    return '\n'.join(lines) + ('\n' if text.endswith('\n') else '')


def readme_section(text: str, title: str = SETUP_HEADING) -> str | None:
    """The body of the section headed *title* (any level, case ignored), or ``None``.

    The section ends at the next heading of the same or a higher level.
    """
    lines = text.splitlines()
    headings = _headings(lines)
    for position, (index, level, heading) in enumerate(headings):
        if heading.strip().lower() != title.lower():
            continue
        end = next(
            (other for other, other_level, _ in headings[position + 1:] if other_level <= level),
            len(lines),
        )
        body = '\n'.join(lines[index + 1:end]).strip()
        return body or None
    return None
