"""Project-level configuration loaded from ``teipublisher.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CDN_TEMPLATE = (
    'https://cdn.jsdelivr.net/npm/@teipublisher/pb-components'
    '@{version}/dist/pb-components-bundle.js'
)
DEFAULT_VERSION = '3.0.5'

CONFIG_FILENAME = 'teipublisher.toml'


@dataclass
class ProjectConfig:
    webcomponents_enabled: bool | None = None
    webcomponents_cdn: str | None = None
    document_template: Path | None = None
    document_css: Path | None = None


def load_project_config(path: Path | None = None) -> ProjectConfig:
    """Load ``teipublisher.toml`` from *path* or CWD; return defaults if absent."""
    config_path = path if path is not None else Path(CONFIG_FILENAME)
    if not config_path.is_file():
        return ProjectConfig()

    with config_path.open('rb') as f:
        data = tomllib.load(f)

    wc = data.get('webcomponents', {})
    doc = data.get('document', {})

    cdn_template = wc.get('cdn', DEFAULT_CDN_TEMPLATE)
    version = wc.get('version', DEFAULT_VERSION)
    resolved_cdn = cdn_template.replace('{version}', version)

    template = doc.get('template')
    css_file = doc.get('css')

    return ProjectConfig(
        webcomponents_enabled=wc.get('enabled'),
        webcomponents_cdn=resolved_cdn,
        document_template=Path(template) if template else None,
        document_css=Path(css_file) if css_file else None,
    )
