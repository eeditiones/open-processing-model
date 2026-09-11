# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Scaffold a local opm project from packaged resources."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from jinja2 import Environment, PackageLoader

from opm.output_modes import RENDER_MODES

VOCABULARIES = ('tei', 'docbook', 'jats')
DEFAULT_OUTPUTS = frozenset(name for name, mode in RENDER_MODES.items() if mode.scaffold)

_TITLE_XPATH = {
    'tei': "(//teiHeader/fileDesc/titleStmt/title)[1]",
    'docbook': "(/article/info/title, /book/info/title)[1]",
    'jats': "(/article/front/article-meta/title-group)[1]",
}
_ODD_PATH = {
    'tei': 'odd/custom.odd',
    'docbook': 'odd/docbook.odd',
    'jats': 'odd/jats.odd',
}
# JATS has no Typst-specific shell of its own; the generic one fits an article.
_TYPST_TEMPLATE = {
    'tei': 'templates/book.typ.j2',
    'docbook': 'templates/docbook.typ.j2',
    'jats': 'templates/book.typ.j2',
}
# Which of the copied HTML shells `opm.toml` wires up. A journal article wants
# the journal surface; the rest read as books or documentation.
_HTML_TEMPLATE = {
    'tei': 'chapbook',
    'docbook': 'chapbook',
    'jats': 'journal',
}
# Elements the commented-out [[index.fields]] examples point at, per vocabulary:
# (footnote-like element, person-name element).
_INDEX_FIELD_ELEMENTS = {
    'tei': ('note', 'persName'),
    'docbook': ('footnote', 'personname'),
    'jats': ('fn', 'name'),
}
_CHUNK_SELECTOR = {
    'tei': 'opm.navigation.tei_div_chunks',
    'docbook': 'opm.navigation.dbk_section_chunks',
    'jats': 'opm.navigation.jats_sec_chunks',
}
# jats.odd has no mode='breadcrumb' models, so asking for that fragment would
# render each chunk's whole content into the breadcrumb bar.
_BREADCRUMBS = {'tei', 'docbook'}


@dataclass(frozen=True)
class ExampleProject:
    """Example project shipped with the package, offered by ``opm init``."""

    name: str
    title: str
    summary: str
    vocabulary: str
    #: Transform target shown in the "Next:" hint, relative to the project root.
    sample: str


#: Bundled example projects, in the order the picker lists them. Kept in step
#: with the directories under ``examples/`` by a test.
EXAMPLES: tuple[ExampleProject, ...] = (
    ExampleProject(
        name='jats',
        title='Journal article (JATS)',
        summary='Masthead, TOC rail, margin notes in print',
        vocabulary='jats',
        sample='data/article/hertziana-digital-editions.xml',
    ),
    ExampleProject(
        name='docbook',
        title='Software handbook (DocBook)',
        summary='Section chunking, global TOC, breadcrumbs, print and EPUB',
        vocabulary='docbook',
        sample='data/doc/quickstart.xml',
    ),
    ExampleProject(
        name='serafin',
        title='Correspondence (TEI)',
        summary='Transcription and translation, with person/place registers',
        vocabulary='tei',
        sample='data/letters/serafin01.xml',
    ),
    ExampleProject(
        name='shakespeare',
        title='Shakespeare Play (TEI)',
        summary='Chunked by page rather than division, with IIIF facsimiles',
        vocabulary='tei',
        sample='data/F-ado.xml',
    ),
)

EXAMPLE_NAMES = tuple(example.name for example in EXAMPLES)

# Copied from an example only as project furniture; generated output and editor
# leavings never belong in a new project.
_EXAMPLE_SKIP = frozenset({'chunks', '__pycache__', '.DS_Store'})

# Lines between these markers describe the example's place in the repo clone
# ("cd examples/jats", links into ../../docs) and are dropped on copy.
_REPO_ONLY_OPEN = '<!-- opm:repo-only -->'
_REPO_ONLY_CLOSE = '<!-- /opm:repo-only -->'


@dataclass
class InitOptions:
    """Options for ``opm init``. Flags fill this today; a wizard can later."""

    directory: Path
    force: bool = False
    title: str | None = None
    vocabulary: str = 'tei'
    html_template: str = ''  # empty: pick the shell that suits the vocabulary
    example: str | None = None  # copy a bundled example instead of scaffolding
    outputs: frozenset[str] = field(default_factory=lambda: frozenset(DEFAULT_OUTPUTS))
    chunking: str = 'div'
    chunk_depth: int = 2
    webcomponents: bool = False
    copy_base_odd: bool = False


#: Sample document written into an empty project, relative to its root.
SAMPLE_PATH = 'data/sample.xml'


@dataclass
class ScaffoldResult:
    directory: Path
    written: list[Path]
    skipped: list[Path]
    title: str
    vocabulary: str
    #: Document the project's own commands transform, relative to its root.
    sample_path: str = SAMPLE_PATH
    #: Name of the example this project was copied from, if any.
    example: str | None = None


class ScaffoldError(Exception):
    """User-facing scaffold failure (existing project, bad vocabulary, …)."""


def _resource_root():
    return resources.files('opm').joinpath('resources')


def _copy_packaged(src_rel: str, dest: Path, *, force: bool) -> bool:
    """Copy a packaged resource to *dest*. Return True if written."""
    packaged = _resource_root().joinpath(*src_rel.split('/'))
    with resources.as_file(packaged) as src:
        src_path = Path(src)
        if not src_path.exists():
            raise FileNotFoundError(f'Packaged resource not found: {src_rel}')
        if dest.exists() and not force:
            return False
        if src_path.is_dir():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and force:
                shutil.copytree(src_path, dest, dirs_exist_ok=True)
            else:
                shutil.copytree(src_path, dest)
            return True
        return _copy_file(src_path, dest, force=force)


def _copy_file(src: Path, dest: Path, *, force: bool) -> bool:
    """Copy one file to *dest*, honouring *force*. Return True if written."""
    if dest.exists() and not force:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def strip_repo_only(text: str) -> str:
    """Drop ``opm:repo-only`` blocks from an example README.

    Those passages explain how to run the example *inside the repo clone*, which
    is wrong once the tree is the reader's own project.
    """
    out: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped == _REPO_ONLY_OPEN:
            skipping = True
            continue
        if stripped == _REPO_ONLY_CLOSE:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    # A block usually sits between blank lines; dropping it would otherwise
    # leave a gap where the paragraph used to be.
    return re.sub(r'\n{3,}', '\n\n', ''.join(out))


def _write_text(dest: Path, text: str, *, force: bool) -> bool:
    if dest.exists() and not force:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding='utf-8')
    return True


def _record(dest: Path, written: list[Path], skipped: list[Path], did_write: bool) -> None:
    (written if did_write else skipped).append(dest)


def _jinja_env() -> Environment:
    return Environment(
        loader=PackageLoader('opm', 'resources/scaffold'),
        autoescape=False,
        keep_trailing_newline=True,
    )


def find_example(name: str) -> ExampleProject:
    """Return the catalogue entry for *name*."""
    for example in EXAMPLES:
        if example.name == name:
            return example
    raise ScaffoldError(
        f'Unknown example {name!r}. Choose: {", ".join(EXAMPLE_NAMES)}.'
    )


def _agent_guidance(
    env: Environment,
    dest_dir: Path,
    *,
    vocabulary: str,
    odd_path: str,
    html_template: str,
    sample: str,
    written: list[Path],
    skipped: list[Path],
) -> None:
    """Write AGENTS.md / CLAUDE.md — never overwritten, even with ``--force``."""
    context = {
        'vocabulary': vocabulary,
        'odd_path': odd_path,
        'sample': sample,
        'html_template': html_template,
    }
    template = env.get_template('agent_guidance.md.j2')
    for name, heading, intro in (
        (
            'AGENTS.md',
            'Agent guidance',
            'Guidance for AI coding agents working in this project.',
        ),
        (
            'CLAUDE.md',
            'CLAUDE.md',
            'This file provides guidance to Claude Code (claude.ai/code) when working with this project.',
        ),
    ):
        text = template.render(heading=heading, intro=intro, **context)
        _record(
            dest_dir / name,
            written,
            skipped,
            _write_text(dest_dir / name, text, force=False),
        )


def _scaffold_example(options: InitOptions) -> ScaffoldResult:
    """Copy a bundled example project into *options.directory*."""
    from opm.config import load_project_config
    from opm.resources import example_dir

    example = find_example((options.example or '').strip().lower())
    try:
        source = example_dir(example.name)
    except FileNotFoundError as e:
        raise ScaffoldError(str(e)) from e

    dest_dir = options.directory.expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    config_path = dest_dir / 'opm.toml'
    if config_path.exists() and not options.force:
        raise ScaffoldError(
            f'{config_path} already exists. Pass --force to overwrite.'
        )

    written: list[Path] = []
    skipped: list[Path] = []
    force = options.force

    for src in sorted(source.rglob('*')):
        if not src.is_file() or _EXAMPLE_SKIP & set(src.relative_to(source).parts):
            continue
        dest = dest_dir / src.relative_to(source)
        if src.name == 'README.md':
            text = strip_repo_only(src.read_text(encoding='utf-8'))
            _record(dest, written, skipped, _write_text(dest, text, force=force))
        else:
            _record(dest, written, skipped, _copy_file(src, dest, force=force))

    _record(
        dest_dir / '.gitignore',
        written,
        skipped,
        _copy_packaged('scaffold/gitignore', dest_dir / '.gitignore', force=force),
    )

    # The ODD and reading shell the example actually wires up, so its agent
    # guidance points at the right files.
    cfg = load_project_config(config_path)
    odd_path = (
        cfg.transform_odd.relative_to(dest_dir).as_posix()
        if cfg.transform_odd is not None and cfg.transform_odd.is_relative_to(dest_dir)
        else 'odd/'
    )
    html_template = (
        cfg.document_template.stem.removesuffix('.html')
        if cfg.document_template is not None
        else _HTML_TEMPLATE.get(example.vocabulary, 'chapbook')
    )
    _agent_guidance(
        _jinja_env(),
        dest_dir,
        vocabulary=example.vocabulary,
        odd_path=odd_path,
        html_template=html_template,
        # The example's own document — an example has no data/sample.xml, and
        # guidance that told an agent to transform one would simply be wrong.
        sample=example.sample,
        written=written,
        skipped=skipped,
    )

    return ScaffoldResult(
        directory=dest_dir,
        written=sorted(written),
        skipped=sorted(skipped),
        title=example.title,
        vocabulary=example.vocabulary,
        sample_path=example.sample,
        example=example.name,
    )


def scaffold(options: InitOptions) -> ScaffoldResult:
    """Write a project tree from *options* and return what was created."""
    if options.example:
        return _scaffold_example(options)

    vocab = options.vocabulary.strip().lower()
    if vocab not in VOCABULARIES:
        raise ScaffoldError(
            f'Unknown vocabulary {options.vocabulary!r}. Choose: {", ".join(VOCABULARIES)}.'
        )

    dest_dir = options.directory.expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    config_path = dest_dir / 'opm.toml'
    if config_path.exists() and not options.force:
        raise ScaffoldError(
            f'{config_path} already exists. Pass --force to overwrite.'
        )

    title = (options.title or dest_dir.name).strip() or dest_dir.name
    is_tei = vocab == 'tei'
    odd_path = _ODD_PATH[vocab]
    typst_template = _TYPST_TEMPLATE[vocab]
    chunk_selector = _CHUNK_SELECTOR[vocab]
    title_xpath = _TITLE_XPATH[vocab]
    html_template = options.html_template.strip() or _HTML_TEMPLATE[vocab]

    written: list[Path] = []
    skipped: list[Path] = []
    force = options.force

    env = _jinja_env()
    toml_text = env.get_template('opm.toml.j2').render(
        odd_path=odd_path,
        webcomponents=options.webcomponents,
        outputs=set(options.outputs),
        typst_template=typst_template,
        chunk_selector=chunk_selector if options.chunking else '',
        chunk_depth=options.chunk_depth,
        title_xpath=title_xpath,
        breadcrumbs=vocab in _BREADCRUMBS,
        html_template=html_template,
        index_note_element=_INDEX_FIELD_ELEMENTS[vocab][0],
        index_name_element=_INDEX_FIELD_ELEMENTS[vocab][1],
    )
    _record(config_path, written, skipped, _write_text(config_path, toml_text, force=force))

    readme_text = env.get_template('README.md.j2').render(
        title=title,
        vocabulary=vocab,
        odd_path=odd_path,
        sample=SAMPLE_PATH,
        html_template=html_template,
    )
    _record(
        dest_dir / 'README.md',
        written,
        skipped,
        _write_text(dest_dir / 'README.md', readme_text, force=force),
    )

    _agent_guidance(
        env,
        dest_dir,
        vocabulary=vocab,
        odd_path=odd_path,
        html_template=html_template,
        sample=SAMPLE_PATH,
        written=written,
        skipped=skipped,
    )

    _record(
        dest_dir / '.gitignore',
        written,
        skipped,
        _copy_packaged('scaffold/gitignore', dest_dir / '.gitignore', force=force),
    )

    _record(
        dest_dir / 'extensions' / '__init__.py',
        written,
        skipped,
        _write_text(
            dest_dir / 'extensions' / '__init__.py',
            # Scaffolded files are CC0 (LICENSING.md, Part A §4), so they say so
            # in the reader's own tree rather than only in ours. Fenced off because
            # this file is AGPL and REUSE would otherwise read the literal below as
            # a second licence declaration for scaffold.py itself.
            # REUSE-IgnoreStart
            '# SPDX-FileCopyrightText: 2026 e-editiones\n'
            '# SPDX-License-Identifier: CC0-1.0\n\n'
            # REUSE-IgnoreEnd
            '"""Project-local XPath extension modules (imported via [project] pythonpath)."""\n',
            force=force,
        ),
    )

    copies: list[tuple[str, Path]] = [
        ('scaffold/templates/chapbook.html.j2', dest_dir / 'templates' / 'chapbook.html.j2'),
        ('scaffold/templates/chapbook.css', dest_dir / 'templates' / 'chapbook.css'),
        ('scaffold/templates/handbook.html.j2', dest_dir / 'templates' / 'handbook.html.j2'),
        ('scaffold/templates/handbook.css', dest_dir / 'templates' / 'handbook.css'),
        ('scaffold/templates/journal.html.j2', dest_dir / 'templates' / 'journal.html.j2'),
        ('scaffold/templates/journal.css', dest_dir / 'templates' / 'journal.css'),
        ('scaffold/templates/tufte.html.j2', dest_dir / 'templates' / 'tufte.html.j2'),
        ('scaffold/templates/bootstrap.html.j2', dest_dir / 'templates' / 'bootstrap.html.j2'),
    ]
    if 'typst' in options.outputs:
        copies.append(
            (
                f'scaffold/templates/{Path(typst_template).name}',
                dest_dir / typst_template,
            )
        )
    if 'docx' in options.outputs:
        copies.append(('templates/default.docx', dest_dir / 'templates' / 'default.docx'))

    if is_tei:
        copies.append(('scaffold/odd/custom.odd', dest_dir / 'odd' / 'custom.odd'))
        if options.copy_base_odd:
            copies.append(('odd/teipublisher.odd', dest_dir / 'odd' / 'teipublisher.odd'))
            copies.append(('odd/tp.css', dest_dir / 'odd' / 'tp.css'))
    else:
        # The ODD's tagsDecl points at its stylesheet by name, so both travel together.
        stem = Path(odd_path).stem
        copies.append((f'odd/{stem}.odd', dest_dir / 'odd' / f'{stem}.odd'))
        copies.append((f'odd/{stem}.css', dest_dir / 'odd' / f'{stem}.css'))
    copies.append((f'scaffold/sample/{vocab}.xml', dest_dir / SAMPLE_PATH))

    for src_rel, dest in copies:
        _record(dest, written, skipped, _copy_packaged(src_rel, dest, force=force))

    return ScaffoldResult(
        directory=dest_dir,
        written=sorted(written),
        skipped=sorted(skipped),
        title=title,
        vocabulary=vocab,
        sample_path=SAMPLE_PATH,
    )
