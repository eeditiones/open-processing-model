# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Helpers for wrapping transform output in page templates (HTML and Typst).

Page templates are jinks templates
([`opm.jinks_templates`][opm.jinks_templates.environment]), conventionally
named ``*.tpl`` (``page.html.tpl``, ``book.typ.tpl``). Jinja2 templates
(``*.j2``) are no longer supported.
"""

from __future__ import annotations

import dataclasses
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree

from opm import jinks_templates as jinks
from opm.jinks_templates.environment import convert_results
from opm.output_modes import RENDER_MODES
from opm.runtime.xpath_env import XPathEnvironment
from opm.runtime.xpath_extensions import build_extension_parser, load_extension_callables
from opm.template_frontmatter import template_context

if TYPE_CHECKING:
    from opm.project import Project

DEFAULT_TEMPLATE_NAME: str = RENDER_MODES['web'].default_template  # type: ignore[assignment]
DEFAULT_PRINT_TEMPLATE_NAME: str = RENDER_MODES['print'].default_template  # type: ignore[assignment]
DEFAULT_TYPST_TEMPLATE_NAME: str = RENDER_MODES['typst'].default_template  # type: ignore[assignment]
DEFAULT_INDEX_TEMPLATE_NAME = 'default_index.html.tpl'


def default_template_path(template_name: str = DEFAULT_TEMPLATE_NAME) -> Path:
    """Return the path to a packaged default document template."""
    return Path(
        str(resources.files('opm').joinpath(f'resources/templates/{template_name}'))
    )


def resolve_template_path(
    template_path: Path | None,
    *,
    default_name: str = DEFAULT_TEMPLATE_NAME,
    project: Any = None,
) -> Path:
    """Resolve override template path or the default template.

    Without *template_path*, a template named *default_name* in one of
    *project*'s profiles replaces the packaged default; where several profiles
    ship one, the profile listed last wins.
    """
    path = template_path
    if path is None and project is not None:
        for _, profile_path in reversed(getattr(project, '_profiles', ())):
            candidate = profile_path / 'templates' / default_name
            if candidate.is_file():
                path = candidate
                break
    if path is None:
        path = default_template_path(default_name)
    if not path.is_file():
        raise FileNotFoundError(f'Template not found: {path}')
    return path


#: The stylesheet of the packaged page layout (``opm/layout.html.tpl``), in
#: ``resources/templates/opm/``.
LAYOUT_CSS_NAME = 'opm-layout.css'


def layout_css(templates_dir: Path | None = None) -> str:
    """The stylesheet behind ``opm/layout.html.tpl``.

    Chunking writes it to ``css/opm-layout.css`` and passes ``layout_css_url``;
    a single transformed page has no such file, so the layout inlines it.
    A copy at ``opm/opm-layout.css`` under *templates_dir* wins over the
    packaged one, as the template loader does for the inlined case.
    """
    if templates_dir is not None:
        local = templates_dir / 'opm' / LAYOUT_CSS_NAME
        if local.is_file():
            return local.read_text(encoding='utf-8')
    return (packaged_templates_dir() / 'opm' / LAYOUT_CSS_NAME).read_text(encoding='utf-8')


def packaged_templates_dir() -> Path:
    """The directory holding the packaged templates, ``opm/`` layouts included."""
    return default_template_path().parent


#: Suffix of jinks templates.
JINKS_SUFFIX = '.tpl'

#: Suffix of Jinja2 templates, which opm no longer renders.
_JINJA_SUFFIX = '.j2'

#: Variables holding HTML opm rendered itself, written unescaped by jinks
#: templates in html mode.
_MARKUP_VARIABLES = ('content_html', 'head_html', 'odd_css', 'base_css')


def _reject_jinja(template_path: Path) -> None:
    if template_path.name.endswith(_JINJA_SUFFIX):
        raise ValueError(
            f'{template_path}: Jinja2 templates are no longer supported; '
            f'rewrite it as a jinks template ({JINKS_SUFFIX}).'
        )


def template_search_dirs(template_dir: Path, project: Any = None) -> list[tuple[Path, str]]:
    """The directories a template in *template_dir* is looked up in, in order.

    Each comes with its origin: ``project`` for *template_dir* itself,
    ``profile <name>`` for the ``templates/`` of a profile (the project's
    profiles first, then any under a ``profiles/`` folder beside
    *template_dir*'s parent), ``opm`` for the packaged templates last. The
    first directory holding a name wins, for ``extends``, ``use`` and
    ``include`` alike; `opm templates` lists them from the same order.
    """
    template_dir = template_dir.resolve()
    packaged = packaged_templates_dir().resolve()
    dirs: list[tuple[Path, str]] = [
        (template_dir, 'opm' if template_dir == packaged else 'project'),
    ]

    # Profile template directories from the project, so that profiles can
    # override the packaged templates.
    if project is not None:
        for _profile_config, profile_path in project._profiles:
            templates_dir = profile_path / 'templates'
            if templates_dir.is_dir():
                dirs.append((templates_dir.resolve(), f'profile {profile_path.name}'))

    # Also a profiles/ directory in the project (templates/ -> project root).
    profiles_dir = template_dir.parent / 'profiles'
    if profiles_dir.is_dir():
        for profile_dir in sorted(profiles_dir.iterdir()):
            templates_dir = profile_dir / 'templates'
            if templates_dir.is_dir() and templates_dir.resolve() not in {d for d, _ in dirs}:
                dirs.append((templates_dir.resolve(), f'profile {profile_dir.name}'))

    # The packaged templates last.
    if packaged not in {d for d, _ in dirs}:
        dirs.append((packaged, 'opm'))
    return dirs


def _searchpaths(template_path: Path, project: Any = None) -> list[str]:
    """Search paths for loading *template_path* and what it extends or includes.

    See [`template_search_dirs`][opm.template_rendering.template_search_dirs].
    """
    return [str(d) for d, _ in template_search_dirs(template_path.parent, project)]


def _jinks_parser_factory(xpath_env: XPathEnvironment | None):
    """Parsers with the project's namespaces and ``tp:`` extension functions."""
    plain = jinks.Environment().parser(frozenset())
    callables: dict = {}
    project_ns: dict[str, str] = {}
    if xpath_env is not None:
        project_ns = xpath_env.namespaces
        for module in xpath_env.extensions:
            callables.update(load_extension_callables(module))
    callables = {name: convert_results(fn, plain) for name, fn in callables.items()}

    def factory(namespaces: dict[str, str]):
        return build_extension_parser('', callables, namespaces={**project_ns, **namespaces})
    return factory


class JinksPageTemplate:
    """A jinks page template rendered with ``render(**variables)``.

    The variables opm passes (``content_html``, ``chunk``, ``fragments``, …)
    and ``context`` form one jinks context map, with the frontmatter merged
    over it by the engine. Where a key exists in both, the project's
    ``context`` wins. HTML opm produced itself (``content_html``, ``head_html`` and the
    stylesheets) is marked as markup, so html mode writes it unescaped. Each
    fragment is a [`Fragment`][opm.jinks_templates.Fragment]: expressions see
    it as nodes, and writing it gives back the HTML unchanged.
    """

    def __init__(self, template: jinks.Template, use: tuple[str, ...] = ()) -> None:
        self.template = template
        #: Templates the profiles add to every page, before any the context names.
        self.use = use

    def render(self, **variables: Any) -> str:
        context = variables.pop('context', None) or {}
        if self.use:
            templating = dict(context.get('templating') or {})
            named = templating.get('use') or []
            named = [named] if isinstance(named, str) else list(named)
            templating['use'] = [*self.use, *(f for f in named if f not in self.use)]
            context = {**context, 'templating': templating}
        for name in _MARKUP_VARIABLES:
            if isinstance(variables.get(name), str):
                variables[name] = jinks.Markup(variables[name])
        if isinstance(variables.get('fragments'), dict):
            variables['fragments'] = _markup_fragments(variables['fragments'])
        if isinstance(variables.get('documents'), list):
            # Index entries carry the fragments of each document.
            variables['documents'] = [_index_entry_map(entry) for entry in variables['documents']]
        return self.template.render({**variables, **context})


def _markup_fragments(fragments: dict) -> dict:
    return {k: jinks.Fragment(v) if isinstance(v, str) else v for k, v in fragments.items()}


def _index_entry_map(entry: Any) -> Any:
    if dataclasses.is_dataclass(entry) and not isinstance(entry, type):
        entry = {f.name: getattr(entry, f.name) for f in dataclasses.fields(entry)}
    if isinstance(entry, dict) and isinstance(entry.get('fragments'), dict):
        entry = {**entry, 'fragments': _markup_fragments(entry['fragments'])}
    return entry


def template_environment(
    template_path: Path, xpath_env: XPathEnvironment | None = None, project: Any = None,
) -> jinks.Environment:
    """The jinks environment for rendering *template_path*.

    Templates are looked up in *template_path*'s directory first, then among
    the packaged ones, so a project template can extend
    ``opm/layout.html.tpl`` and can replace a packaged file by giving its
    own the same relative path. ``extends``, ``use`` and includes resolve
    along that search path. XPath in the template sees the project's
    namespaces, ``tp:`` extension functions, documents and collections
    (``doc()``, ``collection()``) from *xpath_env*.

    Raises:
        ValueError: *template_path* is a Jinja2 template (``.j2``).
    
    If *project* is provided, profile template directories are added to the
    search path, allowing templates to use profile templates via the ``use``
    directive.
    """
    _reject_jinja(template_path)
    searchpaths = _searchpaths(template_path, project)
    env = jinks.Environment(searchpaths, parser_factory=_jinks_parser_factory(xpath_env))
    if xpath_env is not None:
        # The project's documents and [[transform.collections]], so that a
        # template, like the ODD, can read them with doc() and collection():
        # e.g. a landing page listing works it has no source for.
        env.documents = xpath_env.documents
        env.collections = xpath_env.collections
    # HTML pages take the blocks of every profile's `use` templates; a
    # Typst template, sharing the context, must not.
    if project is not None and '.html' in template_path.name:
        env.profile_use = tuple(
            file for profile, _ in getattr(project, '_profiles', ()) for file in profile.use
        )
    return env


def load_template(env: jinks.Environment, template_path: Path,
                  label: str = 'Template') -> JinksPageTemplate:
    """Load *template_path* from *env*, raising ``FileNotFoundError`` if missing."""
    try:
        return JinksPageTemplate(
            env.get_template(template_path.name), use=getattr(env, 'profile_use', ()),
        )
    except jinks.TemplateNotFound as e:
        raise FileNotFoundError(f'{label} not found: {e}') from e


def _inner_html(el: etree._Element | None) -> str:
    if el is None:
        return ''
    parts: list[str] = [el.text or '']
    for child in el:
        parts.append(etree.tostring(child, encoding='unicode', method='html'))  # type: ignore[arg-type]
    return ''.join(parts)


def _first_html_root(serialized_html: str) -> etree._Element | None:
    parser = etree.HTMLParser(encoding='utf-8')
    root = etree.fromstring(serialized_html.encode('utf-8'), parser=parser)
    if etree.QName(root).localname == 'html':
        return root
    return root.find('.//html')


def is_full_html_document(serialized_html: str) -> bool:
    """Whether serialized output contains a full ``<html>`` document element."""
    return _first_html_root(serialized_html) is not None


def render_document_template(
    *,
    serialized_html: str,
    template_path: Path,
    odd_css: str | None,
    parameters: dict[str, str],
    context: dict | None = None,
    base_css: str | None = None,
    assets: str = '',
    asset_styles: list[str] | None = None,
    fragments: dict[str, str] | None = None,
    xpath_env: XPathEnvironment | None = None,
    project: Any = None,
) -> str:
    """Render a full HTML document through the selected page template.

    *context* is the project's ``[context]`` table (see
    [`context_for`][opm.config.ProjectConfig.context_for]), exposed to the template
    under the single name ``context`` so a project key can never shadow a
    built-in like ``content_html``.

    *base_css* is a packaged baseline stylesheet (e.g. the print channel's
    paged-media rules) rendered via its own ``{{ base_css }}`` template slot,
    kept separate from *odd_css* rather than concatenated into it — so the
    ``<style>`` that ``HtmlOutputFunctions.document()`` embedded in the
    document's own ``<head>`` still matches *odd_css* exactly. That element is
    removed from ``head_html``; the template gets the stylesheet as
    ``odd_css`` instead and decides where it goes.

    *assets* and *asset_styles* are the URL prefix of the copied
    ``[transform.web] assets`` and the stylesheets among them, the same
    values chunk pages receive.

    *fragments* are the rendered global fragments of ``[chunking]`` (the
    title, a table of contents), under the same ``fragments`` name chunk pages
    get them, so one template serves both.

    *xpath_env* supplies namespaces and ``tp:`` functions to a jinks template.
    """
    html_root = _first_html_root(serialized_html)
    if html_root is None:
        return serialized_html

    head = html_root.find('head')
    body = html_root.find('body')
    # HtmlOutputFunctions.document() already puts the ODD CSS in <head>. Take
    # it out again and hand it over as odd_css, so a template places it where
    # it belongs in the cascade (opm/base.html.tpl: after the page's own
    # stylesheets) and a template rendering both variables does not repeat it.
    if head is not None and odd_css:
        for style in head.findall('style'):
            if (style.text or '').strip() == odd_css.strip():
                head.remove(style)
    head_content = _inner_html(head)
    effective_odd_css = odd_css or ''
    env = template_environment(template_path, xpath_env, project)
    tpl = load_template(env, template_path)
    return tpl.render(
        head_html=head_content,
        content_html=_inner_html(body),
        odd_css=effective_odd_css,
        base_css=base_css or '',
        parameters=parameters or {},
        lang=html_root.get('lang', ''),
        context=template_context(context),
        assets=assets,
        asset_styles=asset_styles or [],
        fragments=fragments or {},
    )


def render_index_template(
    *,
    entries: list,
    template_path: Path,
    title: str,
    odd_css: str | None = None,
    odd_css_url: str = '',
    assets: str = '',
    asset_styles: list[str] | None = None,
    layout_css_url: str = '',
    context: dict | None = None,
    xpath_env: XPathEnvironment | None = None,
    project: Any = None,
    site_root: str = '',
) -> str:
    """Render a collection index listing chunked documents.

    The template receives ``documents`` (a list of
    [`IndexEntry`][opm.chunking.IndexEntry]), ``title``, the ``odd_css`` string, the
    ``odd_css_url`` file chunking writes, and — when
    an assets setting is configured — an ``assets`` URL prefix plus
    ``asset_styles``, the stylesheets among those assets in declared order. The
    index sits at the output root, so those URLs carry no ``../`` prefix.

    Each entry exposes ``fragments``, so a project controls what the index shows
    by declaring global fragments in ``opm.toml`` — no code change needed to add
    an author or date column.
    """
    env = template_environment(template_path, xpath_env, project)
    tpl = load_template(env, template_path)
    return tpl.render(
        documents=entries,
        # The index sits at the output root, so menu URLs need no prefix.
        site_root=site_root,
        title=title,
        odd_css=odd_css or '',
        odd_css_url=odd_css_url,
        assets=assets,
        asset_styles=asset_styles or [],
        layout_css_url=layout_css_url,
        context=template_context(context),
    )


def render_typst_document_template(
    *,
    content_typst: str,
    template_path: Path,
    odd_typst: str | None,
    parameters: dict[str, str],
    metadata: dict | None = None,
    context: dict | None = None,
    xpath_env: XPathEnvironment | None = None,
) -> str:
    """Render Typst body content through the selected document shell."""
    env = template_environment(template_path, xpath_env)
    tpl = load_template(env, template_path, 'Typst template')
    return tpl.render(
        content_typst=content_typst,
        odd_typst=odd_typst or '',
        parameters=parameters or {},
        metadata=metadata or {},
        context=template_context(context),
    )


# ── listing the templates (opm templates) ────────────────────────────────────

#: Files `opm templates` lists: templates and the files they extend or include.
#: Binary files (default.docx) and Python caches are left out.
TEMPLATE_FILE_SUFFIXES = ('.tpl', '.css', '.js', '.toml', '.typ')


@dataclasses.dataclass(frozen=True)
class TemplateEntry:
    """One template file as `opm templates list` shows it."""

    #: The name a template uses for it in ``extends``/``include``, e.g.
    #: ``opm/layout.html.tpl``.
    name: str
    #: ``project``, ``profile <name>`` or ``opm``.
    origin: str
    path: Path
    #: A copy earlier in the lookup order is used instead of this one.
    overridden: bool
    #: The first sentence of its header comment, or ``''``.
    summary: str


def project_template_dir(project: Any) -> Path:
    """The folder a project's page templates live in, ``templates/`` by convention."""
    return Path(project.root) / 'templates'


def available_templates(project: Any = None, *, include_project: bool = False) -> list[TemplateEntry]:
    """Every template file, in lookup order per name, as rendering resolves them.

    Without *project*, opm's packaged templates. With one, its profiles'
    templates and its own copies of packaged or profile templates come first,
    and the copies they shadow are marked ``overridden``. The project's other
    templates (its page templates) are listed only with *include_project*.
    """
    by_name: dict[str, list[tuple[Path, str]]] = {}
    for directory, origin in _listing_dirs(project):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob('*')):
            if not path.is_file() or path.suffix not in TEMPLATE_FILE_SUFFIXES:
                continue
            if '__pycache__' in path.parts:
                continue
            name = path.relative_to(directory).as_posix()
            by_name.setdefault(name, []).append((path, origin))
    entries: list[TemplateEntry] = []
    for name in sorted(by_name, key=lambda n: (n.count('/') == 0, n)):
        copies = by_name[name]
        if copies[0][1] == 'project' and len(copies) == 1 and not include_project:
            continue
        for i, (path, origin) in enumerate(copies):
            entries.append(TemplateEntry(name, origin, path, i > 0, template_summary(path)))
    return entries


def _listing_dirs(project: Any) -> list[tuple[Path, str]]:
    """Lookup order for `opm templates`: a project's, or opm's templates alone.

    Outside a project no profile is in use, so only the packaged templates
    count (opm's own profiles/ folder beside them is not a project's).
    """
    if project is None:
        return [(packaged_templates_dir().resolve(), 'opm')]
    return template_search_dirs(project_template_dir(project), project)


def find_template(name: str, project: Any = None) -> Path | None:
    """The file rendering would use for the template *name*, or ``None``."""
    for directory, _origin in _listing_dirs(project):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def template_header(path: Path) -> str | None:
    """The leading comment of a template file: its documentation, or ``None``.

    ``[# … #]`` in a ``.tpl``, ``/* … */`` in a ``.css`` or ``.js``, the
    leading ``#`` lines of a ``.toml`` and ``//`` lines of a ``.typ``. The
    comment markers are kept, so the result is the file's own opening text.
    """
    text = path.read_text(encoding='utf-8')
    stripped = text.lstrip()
    for opening, closing in (('[#', '#]'), ('/*', '*/')):
        if stripped.startswith(opening):
            end = stripped.find(closing, len(opening))
            return stripped[:end + len(closing)] if end != -1 else None
    for marker in ('#', '//'):
        if stripped.startswith(marker) and not stripped.startswith('#let'):
            lines = []
            for line in stripped.splitlines():
                if not line.startswith(marker):
                    break
                lines.append(line)
            return '\n'.join(lines)
    return None


def template_summary(path: Path) -> str:
    """The first sentence of *path*'s header comment, on one line."""
    header = template_header(path)
    if not header:
        return ''
    words: list[str] = []
    for line in header.splitlines():
        line = line.strip()
        for marker in ('[#', '#]', '/*', '*/', '//', '#'):
            line = line.removeprefix(marker).removesuffix(marker) if marker in ('#]', '*/') else line.removeprefix(marker)
        line = line.strip()
        if line.startswith('SPDX-'):
            continue
        if not line:
            if words:
                break
            continue
        words.append(line)
    text = ' '.join(words)
    cut = text.find('. ')
    if cut != -1:
        text = text[:cut + 1]
    if len(text) > _SUMMARY_MAX:
        text = text[:_SUMMARY_MAX - 1].rsplit(' ', 1)[0] + ' …'
    return text.rstrip(':')


#: Longest summary `opm templates list` shows.
_SUMMARY_MAX = 100
