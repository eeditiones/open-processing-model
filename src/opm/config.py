"""Project-level configuration loaded from ``opm.toml``.

All relative paths in the config (templates, CSS, documents, ODDs,
``pythonpath``) are resolved relative to the directory containing the
config file, so ``opm`` commands work regardless of the current working
directory.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEFAULT_CDN_TEMPLATE = (
    'https://cdn.jsdelivr.net/npm/@teipublisher/pb-components'
    '@{version}/dist/pb-components-bundle.js'
)
DEFAULT_VERSION = '3.6.7'

CONFIG_FILENAME = 'opm.toml'

# Output types that may declare ``[transform.<type>]`` (odd + optional template).
TRANSFORM_TYPE_SECTIONS = ('web', 'docx', 'typst', 'markdown', 'print')


def _section_table(value: Any) -> dict[str, Any]:
    """Return *value* if it is a TOML table, else an empty dict.

    Nested keys like ``[transform.docx]`` appear as dicts under ``transform``;
    scalar keys (``odd``, ``xpath_extensions``, …) must be ignored.
    """
    return value if isinstance(value, dict) else {}


def resolve_base_css(css_path: Path | None, project_root: Path) -> str:
    """Return the base stylesheet compiled into the ODD's generated CSS.

    ``[document] css`` / ``--css`` replaces the packaged default wholesale — it
    is an override for the rules the runtime's markup needs, not an extra layer.
    Project design CSS belongs in ``[chunking] assets`` instead, where it can
    sit beside the images and fonts it references.
    """
    from opm.odd_compiler.css_generator import default_base_css

    if css_path is not None:
        path = css_path if css_path.is_absolute() else project_root / css_path
        if not path.is_file():
            # Silently returning '' here would drop every base rule — the
            # popover and column-break styles included — for a typo.
            raise FileNotFoundError(f'Stylesheet not found: {path}')
        return path.read_text(encoding='utf-8')

    local = project_root / 'styles' / 'default-styles.css'
    if local.is_file():
        return local.read_text(encoding='utf-8')

    return default_base_css()


@dataclass
class FragmentConfig:
    name: str
    scope: str  # "global" or "per-chunk"
    xpath: str
    xpath_dynamic: str | None = None
    """The ``xpath`` the consuming ``pb-view`` sends, when it differs from *xpath*.

    Used only to build ``--format pb-view`` index keys. See
    :attr:`ChunkingConfig.xpath_dynamic`.
    """
    parameters: dict[str, Any] | None = None
    module: Path | None = None
    """Resolved compiled transform path (set after compile-on-demand, not from TOML)."""
    odd: Path | None = None
    """ODD to compile on demand for this fragment."""
    mode: str = 'web'
    """Output channel used when compiling ``odd`` (default: web)."""


@dataclass
class ChunkingConfig:
    xpath: str | None = None
    xpath_dynamic: str | None = None
    """The ``xpath`` the consuming ``pb-view`` sends, when it differs from *xpath*.

    ``--format pb-view`` writes an ``index.json`` whose keys mirror
    ``createKey()`` in ``pb-view.js``, and pb-view looks itself up by the
    literal value of its own ``xpath`` attribute. That attribute names the
    *region a view displays* (``//text[@type = 'source']``), while *xpath* here
    selects *chunk roots* (``.//text[@type='source']/div``) — different
    expressions that are nonetheless compared as exact strings, so the lookup
    misses and pb-view requests a URL ending in ``undefined``. Set this to the
    attribute's exact value to register the key pb-view will ask for. Only the
    index key changes; chunk selection still uses *xpath*.
    """
    selector: str | None = None
    depth: int = 1
    output_dir: str = "chunks"
    template: Path | None = None
    index_template: Path | None = None
    """Optional Jinja2 template for the collection index written when chunking a directory.

    Rendered to ``<output_dir>/index.html`` so ``opm serve`` shows a real
    landing page instead of the bare directory listing. When *None* the
    packaged ``default_index.html.j2`` is used.
    """
    index_title: str | None = None
    """Heading for the generated collection index (default: the output directory name)."""
    assets: tuple[Path, ...] = ()
    """Files or directories copied into ``<output-root>/assets/``.

    Chunk output directories are wiped on every rebuild, so anything a template
    references — a stylesheet, an image, a font — has to be placed there by the
    build. Templates receive ``assets`` as a relative URL prefix
    (``assets`` from the index, ``../assets`` from a chunk page), and a
    stylesheet copied here can reference a sibling asset by plain filename,
    since its URLs resolve against its own location rather than the page's.
    """
    fragments: list[FragmentConfig] | None = None
    link_pattern: str | None = None
    """Optional URL template for cross-chunk links.

    Placeholders:
      ``{file}``   – full filename, e.g. ``002.html``
      ``{stem}``   – stem without extension, e.g. ``002``
      ``{anchor}`` – the fragment identifier, e.g. ``Pers``
      ``{doc}``    – document subdirectory when directory-chunking, e.g.
                     ``quickstart.xml`` (empty for a single-file output)

    When *None* (default) the rewriter falls back to the relative form
    ``{file}#{anchor}``.  Example values::

        link_pattern = "/{doc}/{file}"              # per-document absolute paths
        link_pattern = "/{doc}/{stem}/"             # clean URLs under the doc dir
        link_pattern = "/{stem}#{anchor}"           # site-root absolute (single doc)
        link_pattern = "http://localhost:8080/{stem}#{anchor}"
    """
    link_doc: str | None = None
    """Document path segment for ``{doc}`` in ``link_pattern`` (not from TOML).

    Set by the CLI when chunking a directory of XML files into per-document
    output subdirectories (e.g. ``quickstart.xml``).
    """
    module: Path | None = None
    """Resolved compiled transform path (set after compile-on-demand, not from TOML)."""
    odd: Path | None = None
    """ODD to compile on demand for chunking."""
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


@dataclass
class CollectionConfig:
    """One ``fn:collection`` URI and the documents it contains.

    *uri* is matched against the argument of ``collection()`` after elementpath
    resolves it (``get_absolute_uri``). A URI with a scheme, or an absolute path
    such as ``/db/apps/serafin/data/registers``, is passed through verbatim, so
    the same string an eXist ``$config:register-root`` holds can be used here and
    will match from any source document. A relative URI would instead resolve
    against each document's own base URI, so it is rejected.
    """

    uri: str
    documents: tuple[Path, ...]


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
    xpath_collections: tuple[CollectionConfig, ...] = ()
    """Collections addressable from XPath via ``fn:collection`` (``[[transform.collections]]``)."""
    xpath_variables: dict[str, Any] = field(default_factory=dict)
    """XPath variables in Clark notation (``{ns}local``).

    From ``[transform.variables.<prefix>]``, where *prefix* is one declared in
    ``[transform.namespaces]``; a namespace URI may be used as the key instead.
    Scalars directly under ``[transform.variables]`` are in no namespace.
    """
    xpath_namespaces: dict[str, str] = field(default_factory=dict)
    """Prefix -> namespace URI for XPath in the ODD (``[transform.namespaces]``).

    Merged over the ODD root's own declarations, so a project can bind prefixes
    the ODD never declares — variables in particular, whose prefix is meaningful
    only to XPath and has no XML meaning inside an attribute value.
    """
    parameters: dict[str, str] = field(default_factory=dict)
    """User parameters bound to XPath ``$parameters`` (from ``[transform.parameters]``)."""
    chunking: ChunkingConfig | None = None
    pythonpath: tuple[Path, ...] = ()
    transform_odd: Path | None = None
    """Default transform ODD from ``[transform].odd`` or ``[transform.web].odd``."""
    transform_odds: dict[str, Path] = field(default_factory=dict)
    """Map of transform type → ODD path (compiled on demand).

    Per-type ``[transform.<type>].odd`` entries override ``[transform].odd``.
    """

    def odd_for_type(self, transform_type: str) -> Path | None:
        """Return the ODD for *transform_type*.

        Precedence: ``[transform.<type>].odd`` → ``[transform].odd`` → ``None``.
        """
        key = transform_type.strip().lower()
        return self.transform_odds.get(key) or self.transform_odd


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

    raw_collections = transform.get('collections', [])
    if isinstance(raw_collections, dict):
        raw_collections = [raw_collections]
    elif not isinstance(raw_collections, list):
        raise ValueError(
            'opm.toml: transform.collections must be an array of tables',
        )
    collections: list[CollectionConfig] = []
    for entry in raw_collections:
        if not isinstance(entry, dict):
            raise ValueError('opm.toml: each transform.collections entry must be a table')
        uri = str(entry.get('uri', '')).strip()
        if not uri:
            raise ValueError('opm.toml: transform.collections entry is missing "uri"')
        parts = urlsplit(uri)
        if not parts.scheme and not parts.netloc and not parts.path.startswith('/'):
            raise ValueError(
                f'opm.toml: transform.collections uri {uri!r} must be absolute — a relative '
                'URI resolves against each source document, so it would not match reliably',
            )
        raw_members = entry.get('documents', [])
        if isinstance(raw_members, str):
            raw_members = [raw_members]
        elif not isinstance(raw_members, list):
            raise ValueError(
                f'opm.toml: transform.collections["{uri}"].documents must be a string or list',
            )
        collections.append(
            CollectionConfig(
                uri=uri,
                documents=tuple(config_path.parent / str(p) for p in raw_members),
            ),
        )

    raw_namespaces = transform.get('namespaces', {})
    if not isinstance(raw_namespaces, dict):
        raise ValueError('opm.toml: transform.namespaces must be a table of prefix = uri')
    xpath_namespaces: dict[str, str] = {}
    for prefix, uri in raw_namespaces.items():
        if not isinstance(uri, str):
            raise ValueError(
                f'opm.toml: transform.namespaces["{prefix}"] must be a namespace URI string',
            )
        xpath_namespaces[str(prefix)] = uri

    raw_variables = transform.get('variables', {})
    if not isinstance(raw_variables, dict):
        raise ValueError('opm.toml: transform.variables must be a table')
    xpath_variables: dict[str, Any] = {}

    def _scalar(value: Any, where: str) -> Any:
        # Keep TOML scalars typed. Stringifying a boolean is actively wrong:
        # ``str(False)`` is 'False', a non-empty string, whose effective boolean
        # value in XPath is *true* — so ``if ($global:address-by-id)`` would take
        # the wrong branch for ``address-by-id = false``.
        if isinstance(value, (bool, int, float, str)):
            return value
        raise ValueError(f'opm.toml: {where} must be a string, number or boolean')

    for key, entries in raw_variables.items():
        if not isinstance(entries, dict):
            # A scalar straight under [transform.variables] is a variable in no
            # namespace, referenced as ``$name``.
            xpath_variables[str(key)] = _scalar(entries, f'transform.variables.{key}')
            continue
        # A sub-table groups variables by the namespace *prefix* declared in
        # [transform.namespaces], so the URI is written once. A key that is
        # itself a URI is still accepted, for a namespace used only here.
        if ':' in key or '/' in key:
            namespace = str(key)
        else:
            namespace = xpath_namespaces.get(str(key), '')
            if not namespace:
                known = ', '.join(sorted(xpath_namespaces)) or '(none declared)'
                raise ValueError(
                    f'opm.toml: transform.variables.{key} — prefix "{key}" is not declared in '
                    f'[transform.namespaces]. Declared prefixes: {known}',
                )
        for local_name, value in entries.items():
            where = f'transform.variables.{key}.{local_name}'
            # Clark notation: elementpath accepts it directly as a variable key.
            clark = f'{{{namespace}}}{local_name}' if namespace else str(local_name)
            xpath_variables[clark] = _scalar(value, where)

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
            raw_frag_odd = frag_data.get('odd')
            fragment = FragmentConfig(
                name=frag_data.get('name', ''),
                scope=frag_data.get('scope', 'per-chunk'),
                xpath=frag_data.get('xpath', '.'),
                xpath_dynamic=frag_data.get('xpath_dynamic'),
                parameters=frag_data.get('parameters'),
                odd=config_path.parent / str(raw_frag_odd) if raw_frag_odd else None,
                mode=str(frag_data.get('mode', 'web')).strip().lower() or 'web',
            )
            if fragment.name and fragment.scope in ('global', 'per-chunk'):
                fragments.append(fragment)

        chunking_template = chunking_data.get('template')
        chunking_index_template = chunking_data.get('index_template')
        raw_chunking_odd = chunking_data.get('odd')
        chunking = ChunkingConfig(
            xpath=chunking_data.get('xpath'),
            xpath_dynamic=chunking_data.get('xpath_dynamic'),
            selector=chunking_data.get('selector'),
            depth=chunking_data.get('depth', 1),
            output_dir=chunking_data.get('output_dir', 'chunks'),
            template=config_path.parent / str(chunking_template) if chunking_template else None,
            index_template=(
                config_path.parent / str(chunking_index_template)
                if chunking_index_template
                else None
            ),
            index_title=chunking_data.get('index_title'),
            assets=tuple(
                config_path.parent / str(asset)
                for asset in (chunking_data.get('assets') or ())
            ),
            fragments=fragments if fragments else None,
            link_pattern=chunking_data.get('link_pattern'),
            odd=config_path.parent / str(raw_chunking_odd) if raw_chunking_odd else None,
            view=chunking_data.get('view', 'div'),
            map=chunking_data.get('map'),
            parameters=chunking_data.get('parameters'),
            doc_path=chunking_data.get('doc_path'),
        )

    raw_pythonpath = project_data.get('pythonpath', [])
    if isinstance(raw_pythonpath, str):
        raw_pythonpath = [raw_pythonpath]
    pythonpath = tuple(config_path.parent / p for p in raw_pythonpath)

    raw_default_odd = transform.get('odd')
    transform_odd = (
        config_path.parent / str(raw_default_odd) if raw_default_odd else None
    )

    transform_odds: dict[str, Path] = {}
    for type_name, section in type_sections.items():
        raw_type_odd = section.get('odd')
        if raw_type_odd:
            transform_odds[type_name] = config_path.parent / str(raw_type_odd)

    # Legacy convenience: [transform.web].odd alone still acts as the default
    # when [transform].odd is omitted (keeps transform_odd / chunking fallbacks).
    if transform_odd is None:
        transform_odd = transform_odds.get('web')

    # Chunking inherits the shared transform ODD when [chunking].odd is omitted.
    if chunking is not None and chunking.odd is None and transform_odd is not None:
        chunking = replace(chunking, odd=transform_odd)

    return ProjectConfig(
        webcomponents_enabled=wc.get('enabled'),
        webcomponents_cdn=resolved_cdn,
        document_template=config_path.parent / str(template) if template else None,
        document_css=config_path.parent / str(css_file) if css_file else None,
        document_docx_template=config_path.parent / docx_template_file if docx_template_file else None,
        typst_template=config_path.parent / typst_template_file if typst_template_file else None,
        xpath_extensions=xpath_extensions,
        xpath_documents=xpath_documents,
        xpath_collections=tuple(collections),
        xpath_variables=xpath_variables,
        xpath_namespaces=xpath_namespaces,
        parameters=parameters,
        chunking=chunking,
        pythonpath=pythonpath,
        transform_odd=transform_odd,
        transform_odds=transform_odds,
    )
