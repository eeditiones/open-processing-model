# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bring a project created by ``opm init`` up to date with a newer opm.

``opm init`` records in ``.opm/init.json`` the options it was given and, for
every file it wrote, a sha-256 of the version it shipped. ``opm update``
plans the same project again with the installed opm
([`plan_project`][opm.scaffold.plan_project]) and compares three versions of
each file: the one recorded, the one now on disk and the one opm would write
today.

* Unchanged upstream: nothing to do, whatever the project did to the file.
* Changed upstream, untouched in the project: the file is replaced.
* Changed on both sides: a conflict. The file stays as it is and the new
  version is written beside it as ``<name>.opm-new``. After merging by hand,
  ``opm update --resolve <path>`` marks it done.

``opm.toml`` holds the project's own configuration and is never replaced; a
newer version only ever arrives as ``opm.toml.opm-new``.

The manifest also records the version of every profile the project uses, so
an update can point out profiles that changed, and flag a new major version
as possibly breaking. Profiles themselves are never copied into a project.

The scheme follows jinks (``.jinks.json`` and ``.jinks-versions.json``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opm.scaffold import InitOptions, ScaffoldError, ScaffoldPlan, plan_project

#: Where ``opm init`` records what it wrote, relative to the project root.
MANIFEST_PATH = '.opm/init.json'
#: Suffix of the file a conflicting new version is written to.
CONFLICT_SUFFIX = '.opm-new'

#: The [`InitOptions`][opm.scaffold.InitOptions] fields that shape a project,
#: and so are recorded to plan it again.
_OPTION_FIELDS = (
    'vocabulary', 'html_template', 'example', 'outputs', 'chunking', 'chunk_depth',
    'webcomponents', 'copy_base_odd', 'templates', 'base', 'bare', 'profiles', 'title',
)


class UpdateError(Exception):
    """User-facing update failure (no manifest, unknown path, …)."""


def file_hash(data: bytes) -> str:
    """sha-256 of *data*, ignoring the difference between CRLF and LF line ends."""
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def opm_version() -> str:
    from opm.resources import opm_version as version

    return version()


@dataclass
class InitManifest:
    """The contents of ``.opm/init.json``."""

    #: The opm version that last wrote the project's files.
    opm: str
    #: The options ``opm init`` was given, as JSON values.
    options: dict[str, Any]
    #: Project path → hash of the version opm shipped for it.
    files: dict[str, str] = field(default_factory=dict)
    #: Profile name → the version the project last used.
    profiles: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                'opm': self.opm,
                'options': self.options,
                'files': dict(sorted(self.files.items())),
                'profiles': dict(sorted(self.profiles.items())),
            },
            indent=2,
        ) + '\n'


def read_manifest(project_root: Path) -> InitManifest | None:
    """The manifest of the project at *project_root*, or ``None`` if it has none."""
    path = project_root / MANIFEST_PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise UpdateError(f'{path}: cannot read: {e}') from e
    if not isinstance(data, dict):
        raise UpdateError(f'{path}: expected a JSON object')
    return InitManifest(
        opm=str(data.get('opm', '')),
        options=dict(data.get('options') or {}),
        files={str(k): str(v) for k, v in (data.get('files') or {}).items()},
        profiles={str(k): str(v) for k, v in (data.get('profiles') or {}).items()},
    )


def save_manifest(project_root: Path, manifest: InitManifest) -> None:
    path = project_root / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.to_json(), encoding='utf-8')


def options_to_json(options: InitOptions) -> dict[str, Any]:
    """The project-shaping fields of *options*, as JSON values."""
    data: dict[str, Any] = {}
    for name in _OPTION_FIELDS:
        value = getattr(options, name)
        if isinstance(value, (frozenset, set)):
            value = sorted(value)
        elif isinstance(value, tuple):
            value = list(value)
        data[name] = value
    return data


def options_from_json(directory: Path, data: dict[str, Any]) -> InitOptions:
    """[`InitOptions`][opm.scaffold.InitOptions] for *directory* from recorded *data*."""
    kwargs: dict[str, Any] = {}
    for name in _OPTION_FIELDS:
        if name not in data:
            continue
        value = data[name]
        if name == 'outputs':
            value = frozenset(value)
        elif name == 'profiles':
            value = tuple(value)
        kwargs[name] = value
    return InitOptions(directory=directory, **kwargs)


def profile_versions(project_root: Path, names: list[str]) -> dict[str, str]:
    """The version of each profile in *names* that the project at *project_root* would use."""
    from opm.profile import ProfileConfig, available_profiles

    found = {p.name: p for p in available_profiles(project_root)}
    versions: dict[str, str] = {}
    for name in names:
        profile = found.get(name)
        if profile is None:
            continue
        try:
            versions[name] = ProfileConfig.from_path(profile.path).version
        except (OSError, ValueError):
            continue
    return versions


def _planned_profiles(plan: ScaffoldPlan) -> list[str]:
    import tomllib

    toml = next((f for f in plan.files if f.path == 'opm.toml'), None)
    if toml is None:
        return []
    project = tomllib.loads(toml.data.decode('utf-8')).get('project')
    raw = project.get('profiles', []) if isinstance(project, dict) else []
    return [raw] if isinstance(raw, str) else [str(n) for n in raw]


def write_init_manifest(project_root: Path, options: InitOptions, plan: ScaffoldPlan) -> None:
    """Record what ``opm init`` planned for the project at *project_root*.

    Every planned file is recorded with the hash of what opm shipped, also one
    that was skipped because the project already had it: the project's copy
    then counts as changed, so an update never replaces it unasked.
    """
    manifest = InitManifest(
        opm=opm_version(),
        options=options_to_json(options),
        files={f.path: file_hash(f.data) for f in plan.files},
        profiles=profile_versions(project_root, _planned_profiles(plan)),
    )
    save_manifest(project_root, manifest)


def record_profiles(project_root: Path) -> None:
    """Record the versions of the profiles the project now uses.

    Called after ``opm profile add`` / ``remove``. A project without a
    manifest is left alone.
    """
    from opm.profile import read_project_profiles

    manifest = read_manifest(project_root)
    config = project_root / 'opm.toml'
    if manifest is None or not config.is_file():
        return
    manifest.profiles = profile_versions(project_root, read_project_profiles(config))
    save_manifest(project_root, manifest)


@dataclass(frozen=True)
class FileChange:
    """What an update does, or would do, to one file."""

    path: str
    #: ``added`` (new in opm), ``updated`` (replaced), ``conflict`` (changed on
    #: both sides; the new version goes to ``<path>.opm-new``), ``replaced``
    #: (a conflict overwritten with ``--theirs``), ``deleted`` (changed in opm
    #: but deleted in the project, so left out), ``removed`` (no longer shipped
    #: by opm; the project's copy stays), ``resolved`` (marked merged with
    #: ``--resolve``).
    action: str


@dataclass(frozen=True)
class ProfileChange:
    """A profile whose version differs from the one the project last used."""

    name: str
    recorded: str | None
    available: str | None
    #: The major version went up: the profile may expect changes in the project.
    breaking: bool = False
    #: A project or user profile shadows a packaged one of another version.
    shadowed: str | None = None


@dataclass
class UpdateReport:
    directory: Path
    #: opm version recorded in the manifest, and the one running now.
    recorded_opm: str
    opm: str
    applied: bool
    files: list[FileChange] = field(default_factory=list)
    profiles: list[ProfileChange] = field(default_factory=list)

    def by_action(self, action: str) -> list[FileChange]:
        return [c for c in self.files if c.action == action]


def _major(version: str | None) -> int:
    try:
        return int((version or '0').split('.')[0])
    except ValueError:
        return 0


def _profile_changes(project_root: Path, manifest: InitManifest) -> tuple[list[ProfileChange], dict[str, str]]:
    from opm.profile import PACKAGED_PROFILES, ProfileConfig, available_profiles, read_project_profiles

    config = project_root / 'opm.toml'
    names = read_project_profiles(config) if config.is_file() else []
    current = profile_versions(project_root, names)
    found = {p.name: p for p in available_profiles(project_root)}
    changes: list[ProfileChange] = []
    for name in names:
        recorded = manifest.profiles.get(name)
        available = current.get(name)
        shadowed = None
        profile = found.get(name)
        packaged = PACKAGED_PROFILES / name
        if profile is not None and profile.origin != 'packaged' and (packaged / 'opm-profile.toml').is_file():
            try:
                packaged_version = ProfileConfig.from_path(packaged).version
            except (OSError, ValueError):
                packaged_version = None
            if packaged_version and packaged_version != available:
                shadowed = packaged_version
        if recorded == available and shadowed is None:
            continue
        changes.append(ProfileChange(
            name=name,
            recorded=recorded,
            available=available,
            breaking=recorded is not None and _major(available) > _major(recorded),
            shadowed=shadowed,
        ))
    return changes, current


def _rel(project_root: Path, path: str) -> str:
    # Relative to the current directory when it points into the project,
    # else relative to the project root.
    p = Path(path).expanduser()
    absolute = p if p.is_absolute() else Path.cwd() / p
    try:
        p = absolute.resolve().relative_to(project_root)
    except ValueError as e:
        if Path(path).is_absolute():
            raise UpdateError(f'{path} is not inside {project_root}') from e
    rel = p.as_posix()
    return rel[: -len(CONFLICT_SUFFIX)] if rel.endswith(CONFLICT_SUFFIX) else rel


def update_project(
    directory: Path,
    *,
    apply: bool = False,
    theirs: bool = False,
    resolve: tuple[str, ...] | list[str] = (),
) -> UpdateReport:
    """Compare the project at *directory* with what the installed opm would write.

    Without *apply* nothing is written: the report says what would happen.
    With *theirs*, conflicting files are replaced instead of getting an
    ``.opm-new`` file beside them (``opm.toml`` excepted). Paths in *resolve*
    (relative to the project, ``.opm-new`` suffix optional) are marked as
    merged: their ``.opm-new`` file is removed and the new version recorded
    as the one they are based on; nothing else is done in that run.

    Raises:
        UpdateError: No manifest, or the project cannot be planned again.
    """
    root = directory.expanduser().resolve()
    manifest = read_manifest(root)
    if manifest is None:
        raise UpdateError(
            f'{root} has no {MANIFEST_PATH}: opm update only knows projects '
            'created by `opm init` from this version on.'
        )
    options = options_from_json(root, manifest.options)
    try:
        plan = plan_project(options)
    except (ScaffoldError, FileNotFoundError) as e:
        raise UpdateError(str(e)) from e

    report = UpdateReport(directory=root, recorded_opm=manifest.opm, opm=opm_version(), applied=apply)
    planned = {f.path: f for f in plan.files}

    if resolve:
        for path in resolve:
            rel = _rel(root, path)
            if rel not in planned:
                raise UpdateError(f'{rel} is not a file opm init writes')
            manifest.files[rel] = file_hash(planned[rel].data)
            report.files.append(FileChange(rel, 'resolved'))
            if apply:
                (root / (rel + CONFLICT_SUFFIX)).unlink(missing_ok=True)
        if apply:
            save_manifest(root, manifest)
        return report

    files = dict(manifest.files)
    writes: list[tuple[Path, bytes]] = []
    for f in plan.files:
        new = file_hash(f.data)
        recorded = files.get(f.path)
        dest = root / f.path
        current = file_hash(dest.read_bytes()) if dest.is_file() else None

        if recorded == new:
            continue
        if current == new:
            files[f.path] = new
            continue
        if current is None:
            if recorded is None:
                report.files.append(FileChange(f.path, 'added'))
                writes.append((dest, f.data))
            else:
                report.files.append(FileChange(f.path, 'deleted'))
            files[f.path] = new
        elif current == recorded and not f.config:
            report.files.append(FileChange(f.path, 'updated'))
            writes.append((dest, f.data))
            files[f.path] = new
        elif theirs and not f.config:
            report.files.append(FileChange(f.path, 'replaced'))
            writes.append((dest, f.data))
            files[f.path] = new
        else:
            report.files.append(FileChange(f.path, 'conflict'))
            writes.append((root / (f.path + CONFLICT_SUFFIX), f.data))

    for path in sorted(set(files) - set(planned)):
        report.files.append(FileChange(path, 'removed'))
        del files[path]

    report.profiles, versions = _profile_changes(root, manifest)

    if apply:
        for dest, data in writes:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        manifest.files = files
        manifest.profiles = versions
        manifest.opm = report.opm
        save_manifest(root, manifest)
    return report
