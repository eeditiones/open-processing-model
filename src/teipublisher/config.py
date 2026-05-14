"""Project-level configuration loaded from ``teipublisher.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CDN_TEMPLATE = (
    'https://cdn.jsdelivr.net/npm/@teipublisher/pb-components'
    '@{version}/dist/pb-components-bundle.js'
)
DEFAULT_VERSION = '3.0.5'

CONFIG_FILENAME = 'teipublisher.toml'


@dataclass
class FragmentConfig:
    name: str
    scope: str  # "global" or "per-chunk"
    xpath: str
    params: dict[str, Any] | None = None


@dataclass
class ChunkingConfig:
    enabled: bool = False
    xpath: str = "//text/body/div"
    selector: str | None = None
    depth: int = 1
    output_dir: str = "chunks"
    template: Path | None = None
    fragments: list[FragmentConfig] | None = None


@dataclass
class ProjectConfig:
    webcomponents_enabled: bool | None = None
    webcomponents_cdn: str | None = None
    document_template: Path | None = None
    document_css: Path | None = None
    xpath_extensions: tuple[str, ...] = ()
    chunking: ChunkingConfig | None = None


def load_project_config(path: Path | None = None) -> ProjectConfig:
    """Load ``teipublisher.toml`` from *path* or CWD; return defaults if absent."""
    config_path = path if path is not None else Path(CONFIG_FILENAME)
    if not config_path.is_file():
        return ProjectConfig()

    with config_path.open('rb') as f:
        data = tomllib.load(f)

    wc = data.get('webcomponents', {})
    doc = data.get('document', {})
    transform = data.get('transform', {})
    chunking_data = data.get('chunking', {})

    cdn_template = wc.get('cdn', DEFAULT_CDN_TEMPLATE)
    version = wc.get('version', DEFAULT_VERSION)
    resolved_cdn = cdn_template.replace('{version}', version)

    template = doc.get('template')
    css_file = doc.get('css')
    raw_xpath_extensions = transform.get('xpath_extensions')
    xpath_extensions: tuple[str, ...]
    if raw_xpath_extensions is None:
        xpath_extensions = ()
    elif isinstance(raw_xpath_extensions, str):
        xpath_extensions = (raw_xpath_extensions,)
    elif isinstance(raw_xpath_extensions, list):
        xpath_extensions = tuple(str(item) for item in raw_xpath_extensions)
    else:
        raise ValueError(
            'teipublisher.toml: transform.xpath_extensions must be a string or list of strings',
        )

    # Parse chunking configuration
    chunking: ChunkingConfig | None = None
    if chunking_data:
        fragments: list[FragmentConfig] = []
        for frag_data in chunking_data.get('fragments', []):
            if not isinstance(frag_data, dict):
                continue
            fragment = FragmentConfig(
                name=frag_data.get('name', ''),
                scope=frag_data.get('scope', 'per-chunk'),
                xpath=frag_data.get('xpath', '.'),
                params=frag_data.get('params')
            )
            if fragment.name and fragment.scope in ('global', 'per-chunk'):
                fragments.append(fragment)

        chunking_template = chunking_data.get('template')
        chunking = ChunkingConfig(
            enabled=chunking_data.get('enabled', False),
            xpath=chunking_data.get('xpath', '//text/body/div'),
            selector=chunking_data.get('selector'),
            depth=chunking_data.get('depth', 1),
            output_dir=chunking_data.get('output_dir', 'chunks'),
            template=Path(chunking_template) if chunking_template else None,
            fragments=fragments if fragments else None
        )

    return ProjectConfig(
        webcomponents_enabled=wc.get('enabled'),
        webcomponents_cdn=resolved_cdn,
        document_template=Path(template) if template else None,
        document_css=Path(css_file) if css_file else None,
        xpath_extensions=xpath_extensions,
        chunking=chunking,
    )
