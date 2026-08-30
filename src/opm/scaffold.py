"""Scaffold a local opm project from packaged resources."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from jinja2 import Environment, PackageLoader

VOCABULARIES = ('tei', 'docbook', 'jats')
DEFAULT_OUTPUTS = frozenset({'web', 'typst', 'docx', 'markdown'})

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
_CHUNK_SELECTOR = {
    'tei': 'opm.navigation.tei_div_chunks',
    'docbook': 'opm.navigation.dbk_section_chunks',
    'jats': 'opm.navigation.jats_sec_chunks',
}
# jats.odd has no mode='breadcrumb' models, so asking for that fragment would
# render each chunk's whole content into the breadcrumb bar.
_BREADCRUMBS = {'tei', 'docbook'}


@dataclass
class InitOptions:
    """Options for ``opm init``. Flags fill this today; a wizard can later."""

    directory: Path
    force: bool = False
    title: str | None = None
    vocabulary: str = 'tei'
    html_template: str = 'chapbook'
    outputs: frozenset[str] = field(default_factory=lambda: frozenset(DEFAULT_OUTPUTS))
    chunking: str = 'div'
    chunk_depth: int = 2
    webcomponents: bool = False
    copy_base_odd: bool = False
    include_sample: bool = True


@dataclass
class ScaffoldResult:
    directory: Path
    written: list[Path]
    skipped: list[Path]
    title: str
    vocabulary: str
    include_sample: bool


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
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src_path.is_dir():
            if dest.exists() and force:
                shutil.copytree(src_path, dest, dirs_exist_ok=True)
            else:
                shutil.copytree(src_path, dest)
        else:
            shutil.copy2(src_path, dest)
        return True


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


def scaffold(options: InitOptions) -> ScaffoldResult:
    """Write a project tree from *options* and return what was created."""
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
    )
    _record(config_path, written, skipped, _write_text(config_path, toml_text, force=force))

    readme_text = env.get_template('README.md.j2').render(
        title=title,
        vocabulary=vocab,
        odd_path=odd_path,
        include_sample=options.include_sample,
    )
    _record(
        dest_dir / 'README.md',
        written,
        skipped,
        _write_text(dest_dir / 'README.md', readme_text, force=force),
    )

    # Agent guidance: never overwrite existing CLAUDE.md / AGENTS.md (even with --force).
    agent_ctx = {
        'vocabulary': vocab,
        'odd_path': odd_path,
        'include_sample': options.include_sample,
    }
    agent_tpl = env.get_template('agent_guidance.md.j2')
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
        text = agent_tpl.render(heading=heading, intro=intro, **agent_ctx)
        _record(
            dest_dir / name,
            written,
            skipped,
            _write_text(dest_dir / name, text, force=False),
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
            '"""Project-local XPath extension modules (imported via [project] pythonpath)."""\n',
            force=force,
        ),
    )

    copies: list[tuple[str, Path]] = [
        ('scaffold/templates/chapbook.html.j2', dest_dir / 'templates' / 'chapbook.html.j2'),
        ('scaffold/templates/chapbook.css', dest_dir / 'templates' / 'chapbook.css'),
        ('scaffold/templates/handbook.html.j2', dest_dir / 'templates' / 'handbook.html.j2'),
        ('scaffold/templates/handbook.css', dest_dir / 'templates' / 'handbook.css'),
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
    if options.include_sample:
        copies.append((f'scaffold/sample/{vocab}.xml', dest_dir / 'data' / 'sample.xml'))

    for src_rel, dest in copies:
        _record(dest, written, skipped, _copy_packaged(src_rel, dest, force=force))

    return ScaffoldResult(
        directory=dest_dir,
        written=sorted(written),
        skipped=sorted(skipped),
        title=title,
        vocabulary=vocab,
        include_sample=options.include_sample,
    )
