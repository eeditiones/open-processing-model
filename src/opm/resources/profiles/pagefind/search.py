# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: CC0-1.0

"""Build the Pagefind search index once `opm chunk` has written the site.

Registered as the profile's ``after_chunking`` hook. The records come from
[`Project.index`][opm.project.Project.index], so the ``[index]`` settings of
the project apply; ``granularity = "page"`` gives one search result per page.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from opm.assets import ASSETS_DIR


def build_search(project: Any, run: Any) -> None:
    """Write the search index and the Pagefind UI below ``assets/<base>``.

    Settings come from ``[context.features.pagefind]``: ``base`` (default
    ``search``) and ``language`` (default ``[context] lang``, then ``en``).
    """
    if run.format != 'html':
        return
    try:
        from pagefind.index import IndexConfig, PagefindIndex
    except ImportError as e:
        raise RuntimeError(
            "The 'pagefind' profile needs the pagefind package, which comes with opm. "
            "Reinstall opm to get it, e.g. pip install --upgrade open-processing-model."
        ) from e

    context = project.config.template_context
    settings = (context.get('features') or {}).get('pagefind') or {}
    if not settings.get('enabled', True):
        return
    output = run.output_dir / ASSETS_DIR / str(settings.get('base') or 'search')
    language = str(settings.get('language') or context.get('lang') or 'en')
    dirs = {Path(source).resolve(): name for source, name in run.document_dirs.items()}
    records = project.index(list(run.documents))

    async def write() -> None:
        config = IndexConfig(output_path=str(output), verbose=False, default_language=language)
        async with PagefindIndex(config=config) as index:
            for record in records:
                metadata = record.get('metadata', {})
                source = Path(metadata.get('source', '')).resolve()
                href = metadata.get('href', '')
                # opm chunk writes each document into a directory of its own;
                # result URLs are relative to the site root.
                url = f"{dirs.get(source, source.name)}/{href}" if href else ''
                await index.add_custom_record(
                    url=url,
                    content=record.get('document', ''),
                    language=language,
                    meta={
                        'title': str(metadata.get('heading') or metadata.get('title') or ''),
                        'breadcrumb': str(metadata.get('breadcrumb') or ''),
                    },
                )
            await index.write_files()

    output.mkdir(parents=True, exist_ok=True)
    asyncio.run(write())
