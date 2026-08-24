"""Scaffold a local opm project from packaged resources."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from jinja2 import Environment, PackageLoader

VOCABULARIES = ('tei', 'docbook')
DEFAULT_OUTPUTS = frozenset({'web', 'typst', 'docx', 'markdown'})

_TEI_TITLE_XPATH = "string((//teiHeader/fileDesc/titleStmt/title)[1])"
_DBK_TITLE_XPATH = "string((/article/info/title, /book/info/title)[1])"


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
    odd_path = 'odd/custom.odd' if is_tei else 'odd/docbook.odd'
    typst_template = 'templates/book.typ.j2' if is_tei else 'templates/docbook.typ.j2'
    chunk_selector = (
        'opm.navigation.tei_div_chunks' if is_tei else 'opm.navigation.dbk_section_chunks'
    )
    title_xpath = _TEI_TITLE_XPATH if is_tei else _DBK_TITLE_XPATH

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
        ('styles/default-styles.css', dest_dir / 'styles' / 'default-styles.css'),
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
        if options.include_sample:
            copies.append(('scaffold/sample/tei.xml', dest_dir / 'data' / 'sample.xml'))
    else:
        copies.append(('odd/docbook.odd', dest_dir / 'odd' / 'docbook.odd'))
        copies.append(('odd/docbook.css', dest_dir / 'odd' / 'docbook.css'))
        if options.include_sample:
            copies.append(('scaffold/sample/docbook.xml', dest_dir / 'data' / 'sample.xml'))

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
