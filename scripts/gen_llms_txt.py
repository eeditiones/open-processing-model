# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Write ``llms.txt``, ``llms-full.txt`` and Markdown copies of each page into ``site/``.

Run after ``zensical build``. Follows https://llmstxt.org: ``llms.txt`` is an
index of the documentation in ``mkdocs.yml`` nav order, linking to a plain
Markdown copy of each page; ``llms-full.txt`` is the prose documentation in one
file. API reference pages consisting of mkdocstrings directives only are listed
under "Optional" and left out of the full text, since their content exists only
in the rendered HTML.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
SITE = ROOT / 'site'

# Sections whose pages go under "Optional" in llms.txt and stay out of llms-full.txt.
OPTIONAL_SECTIONS = {'API Reference', 'License'}

SUMMARY = """\
`opm` is a Python command-line tool and library that converts TEI XML (and
DocBook or JATS) into HTML, PDF (via Typst or CSS for print), EPUB, Word,
Markdown or JSON, and splits documents into static websites. Rendering rules
are written in a TEI ODD file following the TEI Processing Model; `opm`
compiles the ODD into a Python module on demand. ODDs are compatible with
TEI Publisher.

Key facts for agents:

- Install with `pip install open-processing-model` (Python 3.12+). The command is `opm`.
- `opm init` scaffolds a project: `opm.toml` (settings), `odd/custom.odd`
  (rendering rules, inheriting `teipublisher.odd`), `templates/`, `data/`.
- `opm transform FILE -t TYPE -o OUT` converts one file; TYPE is one of web,
  print, epub, markdown, docx, typst, json. `-o out.pdf` with `-t typst` compiles a PDF.
- `opm chunk FILE_OR_DIR --force` splits documents into pages for a static site;
  `opm serve` previews it.
- There is no separate compile step: change the ODD and rerun.
- Change rendering in the ODD first (elementSpec/model/@behaviour/outputRendition),
  then in templates; Python XPath extensions are a last resort.
"""


@dataclass
class Page:
    title: str
    src: str        # path relative to docs/, e.g. guide/odd-files.md
    section: str


def _load_config() -> dict:
    class Loader(yaml.SafeLoader):
        pass

    # Tolerate tags such as !!python/name used by some markdown extensions.
    Loader.add_multi_constructor('', lambda loader, suffix, node: None)
    with open(ROOT / 'mkdocs.yml', encoding='utf-8') as f:
        return yaml.load(f, Loader=Loader)


def _walk_nav(nav: list, section: str = '') -> list[Page]:
    pages: list[Page] = []
    for item in nav:
        if isinstance(item, str):
            pages.append(Page(item, item, section))
            continue
        for title, value in item.items():
            if isinstance(value, str):
                # A top-level page is a section of its own.
                pages.append(Page(title, value, section or title))
            else:
                pages.extend(_walk_nav(value, title))
    return pages


def _page_url(src: str) -> str:
    """Site-relative URL of the rendered page (directory URLs)."""
    stem = src.removesuffix('.md')
    if stem == 'index':
        return ''
    if stem.endswith('/index'):
        return stem.removesuffix('index')
    return stem + '/'


def _split_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith('---\n'):
        end = text.find('\n---\n', 4)
        if end != -1:
            meta = yaml.safe_load(text[4:end]) or {}
            return meta, text[end + 5:].lstrip('\n')
    return {}, text


_LINK = re.compile(r'(!?\[[^\]]*\]\()([^)\s]+)(\))')


def _clean(text: str, src: str, site_url: str) -> str:
    """Make a page readable outside the site: absolute links, no HTML furniture."""
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    # Raw HTML blocks at the top level (logo, slideshow, supporter logos).
    text = re.sub(r'^<(\w+)\b.*?^</\1>\n*', '', text, flags=re.M | re.S)
    base = posixpath.dirname(src)

    def absolute(m: re.Match) -> str:
        target = m.group(2)
        if re.match(r'^[a-z]+:|^#', target):
            return m.group(0)
        path, _, anchor = target.partition('#')
        resolved = posixpath.normpath(posixpath.join(base, path))
        url = site_url + (_page_url(resolved) if resolved.endswith('.md') else resolved)
        return f'{m.group(1)}{url}{"#" + anchor if anchor else ""}{m.group(3)}'

    return _LINK.sub(absolute, text).strip() + '\n'


def _first_sentence(text: str) -> str:
    in_code = False
    for block in re.split(r'\n\s*\n', text):
        stripped = block.strip()
        if stripped.startswith('```'):
            in_code = stripped.count('```') % 2 == 1 if not in_code else False
            continue
        if in_code or not stripped or stripped[0] in '#<!|>-*:' or stripped[0].isdigit():
            continue
        para = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', ' '.join(stripped.split()))
        para = para.replace('**', '')
        sentence = re.split(r'(?<=[.!?])\s', para, maxsplit=1)[0]
        return sentence if len(sentence) <= 200 else sentence[:197].rstrip() + '…'
    return ''


def _is_reference_only(body: str) -> bool:
    return bool(re.search(r'^:::', body, flags=re.M))


def main() -> None:
    if not SITE.is_dir():
        raise SystemExit('site/ not found: run `zensical build` first')
    config = _load_config()
    site_url = config['site_url'].rstrip('/') + '/'
    pages = _walk_nav(config['nav'])

    index_lines = [
        f'# {config["site_name"]} (opm)',
        '',
        f'> {config["site_description"]}',
        '',
        SUMMARY,
        f'The complete prose documentation in one file: {site_url}llms-full.txt',
        '',
    ]
    full_parts = [
        f'# {config["site_name"]} (opm)\n\n> {config["site_description"]}\n\n{SUMMARY}',
    ]

    section = None
    optional: list[str] = []
    for page in pages:
        source = DOCS / page.src
        if not source.is_file():
            print(f'skipping {page.src}: not found')
            continue
        meta, body = _split_front_matter(source.read_text(encoding='utf-8'))
        cleaned = _clean(body, page.src, site_url)

        (SITE / page.src).parent.mkdir(parents=True, exist_ok=True)
        (SITE / page.src).write_text(cleaned, encoding='utf-8')

        desc = meta.get('description') or _first_sentence(cleaned)
        entry = f'- [{page.title}]({site_url}{page.src})' + (f': {desc}' if desc else '')
        if page.section in OPTIONAL_SECTIONS:
            optional.append(entry)
            continue
        if page.section != section:
            if section is not None:
                index_lines.append('')
            section = page.section
            index_lines += [f'## {section}', '']
        index_lines.append(entry)
        if not _is_reference_only(body):
            full_parts.append(f'{cleaned}\nSource: {site_url}{_page_url(page.src)}\n')

    if optional:
        index_lines += ['', '## Optional', '', *optional]

    (SITE / 'llms.txt').write_text('\n'.join(index_lines) + '\n', encoding='utf-8')
    (SITE / 'llms-full.txt').write_text('\n---\n\n'.join(full_parts), encoding='utf-8')
    size = (SITE / 'llms-full.txt').stat().st_size
    print(f'Wrote site/llms.txt, site/llms-full.txt ({size // 1024} KB) and {len(pages)} Markdown pages')


if __name__ == '__main__':
    main()
