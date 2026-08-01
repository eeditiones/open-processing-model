"""Project-level configuration loaded from ``opm.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CDN_TEMPLATE = (
    'https://cdn.jsdelivr.net/npm/@teipublisher/pb-components'
    '@{version}/dist/pb-components-bundle.js'
)
DEFAULT_VERSION = '3.0.5'

CONFIG_FILENAME = 'opm.toml'

# Output types that may declare ``[transform.<type>]`` (module + optional template).
TRANSFORM_TYPE_SECTIONS = ('web', 'docx', 'typst', 'markdown', 'print')


def _section_table(value: Any) -> dict[str, Any]:
    """Return *value* if it is a TOML table, else an empty dict.

    Nested keys like ``[transform.docx]`` appear as dicts under ``transform``;
    scalar keys (``module``, ``xpath_extensions``, …) must be ignored.
    """
    return value if isinstance(value, dict) else {}


@dataclass
class FragmentConfig:
    name: str
    scope: str  # "global" or "per-chunk"
    xpath: str
    parameters: dict[str, Any] | None = None
    module: Path | None = None


@dataclass
class ChunkingConfig:
    xpath: str | None = None
    selector: str | None = None
    depth: int = 1
    output_dir: str = "chunks"
    template: Path | None = None
    fragments: list[FragmentConfig] | None = None
    link_pattern: str | None = None
    module: Path | None = None
    view: str = "div"
    """View mode (``div``, ``page`` or ``single``) used in pb-view lookup keys."""
    map: str | None = None
    """Optional ``map`` parameter included in pb-view lookup keys."""
    parameters: dict[str, Any] | None = None
    """Optional user parameters for pb-view lookup keys.

    Each entry is emitted as ``user.<key>=<value>`` and must match the
    ``pb-param`` children declared on the consuming ``pb-view``.
    """
    doc_path: str | None = None
    """Document path subdirectory for ``--format pb-view`` output.

    pb-view resolves static data as ``${static}/${path}/...``; the data is
    written to ``<output_dir>/<doc_path>/`` (CSS stays shared at
    ``<output_dir>/css/``). Must match the ``path`` of the consuming
    ``pb-document``. When unset the data is written directly into ``output_dir``.
    """
    """Optional URL template for cross-chunk links.

    Placeholders:
      ``{file}``   – full filename, e.g. ``002.html``
      ``{stem}``   – stem without extension, e.g. ``002``
      ``{anchor}`` – the fragment identifier, e.g. ``Pers``

    When *None* (default) the rewriter falls back to the relative form
    ``{file}#{anchor}``.  Example values::

        link_pattern = "/{stem}#{anchor}"           # absolute path, no extension
        link_pattern = "http://localhost:8080/{stem}#{anchor}"
    """


@dataclass
class ProjectConfig:
    webcomponents_enabled: bool | None = None
    webcomponents_cdn: str | None = None
    document_template: Path | None = None
    document_css: Path | None = None
    document_docx_template: Path | None = None
    typst_template: Path | None = None
    xpath_extensions: tuple[str, ...] = ()
    xpath_documents: tuple[Path, ...] = ()
    parameters: dict[str, str] = field(default_factory=dict)
    """User parameters bound to XPath ``$parameters`` (from ``[transform.parameters]``)."""
    chunking: ChunkingConfig | None = None
    pythonpath: tuple[Path, ...] = ()
    transform_module: Path | None = None
    """Web transform module from ``[transform.web].module``."""
    transform_modules: dict[str, Path] = field(default_factory=dict)
    """Map of transform type (``web``, ``docx``, ``typst``, …) → module path."""

    def module_for_type(self, transform_type: str) -> Path | None:
        """Return the configured module for *transform_type*, or ``None``."""
        return self.transform_modules.get(transform_type.strip().lower())


def _resolve_type_section(
    transform: dict[str, Any],
    data: dict[str, Any],
    type_name: str,
) -> dict[str, Any]:
    """Return the config table for *type_name*.

    Prefer ``[transform.<type>]``; fall back to a legacy top-level ``[<type>]``
    section for backward compatibility.
    """
    nested = _section_table(transform.get(type_name))
    if nested:
        return nested
    return _section_table(data.get(type_name))


def load_project_config(path: Path | None = None) -> ProjectConfig:
    """Load ``opm.toml`` from *path* or CWD; return defaults if absent."""
    config_path = path if path is not None else Path(CONFIG_FILENAME)
    if not config_path.is_file():
        return ProjectConfig()

    with config_path.open('rb') as f:
        data = tomllib.load(f)

    doc = _section_table(data.get('document'))
    transform = _section_table(data.get('transform'))
    chunking_data = _section_table(data.get('chunking'))
    project_data = _section_table(data.get('project'))

    # Per-type tables: prefer [transform.<type>], accept legacy top-level [<type>].
    type_sections = {
        type_name: _resolve_type_section(transform, data, type_name)
        for type_name in TRANSFORM_TYPE_SECTIONS
    }
    docx_data = type_sections['docx']
    typst_data = type_sections['typst']
    web_data = type_sections['web']
    wc = _section_table(web_data.get('webcomponents'))

    cdn_template = wc.get('cdn', DEFAULT_CDN_TEMPLATE)
    version = wc.get('version', DEFAULT_VERSION)
    resolved_cdn = cdn_template.replace('{version}', version)

    template = doc.get('template')
    css_file = doc.get('css')
    docx_template_file = docx_data.get('template')
    typst_template_file = typst_data.get('template')
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
            'opm.toml: transform.xpath_extensions must be a string or list of strings',
        )

    raw_xpath_documents = transform.get('documents', [])
    if isinstance(raw_xpath_documents, str):
        raw_xpath_documents = [raw_xpath_documents]
    elif not isinstance(raw_xpath_documents, list):
        raise ValueError(
            'opm.toml: transform.documents must be a string or list of strings',
        )
    xpath_documents = tuple(config_path.parent / str(path) for path in raw_xpath_documents)

    raw_parameters = transform.get('parameters', {})
    if not isinstance(raw_parameters, dict):
        raise ValueError('opm.toml: transform.parameters must be a table')
    # Nested [transform.<type>] tables are also dict values; only keep scalar params.
    parameters = {
        str(key): str(value)
        for key, value in raw_parameters.items()
        if not isinstance(value, dict)
    }

    # Parse chunking configuration
    chunking: ChunkingConfig | None = None
    if chunking_data:
        fragments: list[FragmentConfig] = []
        for frag_data in chunking_data.get('fragments', []):
            if not isinstance(frag_data, dict):
                continue
            raw_frag_module = frag_data.get('module')
            fragment = FragmentConfig(
                name=frag_data.get('name', ''),
                scope=frag_data.get('scope', 'per-chunk'),
                xpath=frag_data.get('xpath', '.'),
                parameters=frag_data.get('parameters'),
                module=config_path.parent / raw_frag_module if raw_frag_module else None,
            )
            if fragment.name and fragment.scope in ('global', 'per-chunk'):
                fragments.append(fragment)

        chunking_template = chunking_data.get('template')
        raw_chunking_module = chunking_data.get('module')
        chunking = ChunkingConfig(
            xpath=chunking_data.get('xpath'),
            selector=chunking_data.get('selector'),
            depth=chunking_data.get('depth', 1),
            output_dir=chunking_data.get('output_dir', 'chunks'),
            template=Path(chunking_template) if chunking_template else None,
            fragments=fragments if fragments else None,
            link_pattern=chunking_data.get('link_pattern'),
            module=config_path.parent / raw_chunking_module if raw_chunking_module else None,
            view=chunking_data.get('view', 'div'),
            map=chunking_data.get('map'),
            parameters=chunking_data.get('parameters'),
            doc_path=chunking_data.get('doc_path'),
        )

    raw_pythonpath = project_data.get('pythonpath', [])
    if isinstance(raw_pythonpath, str):
        raw_pythonpath = [raw_pythonpath]
    pythonpath = tuple(config_path.parent / p for p in raw_pythonpath)

    transform_modules: dict[str, Path] = {}
    for type_name, section in type_sections.items():
        raw_type_module = section.get('module')
        if raw_type_module:
            transform_modules[type_name] = config_path.parent / str(raw_type_module)
    transform_module = transform_modules.get('web')

    return ProjectConfig(
        webcomponents_enabled=wc.get('enabled'),
        webcomponents_cdn=resolved_cdn,
        document_template=Path(template) if template else None,
        document_css=Path(css_file) if css_file else None,
        document_docx_template=config_path.parent / docx_template_file if docx_template_file else None,
        typst_template=config_path.parent / typst_template_file if typst_template_file else None,
        xpath_extensions=xpath_extensions,
        xpath_documents=xpath_documents,
        parameters=parameters,
        chunking=chunking,
        pythonpath=pythonpath,
        transform_module=transform_module,
        transform_modules=transform_modules,
    )
