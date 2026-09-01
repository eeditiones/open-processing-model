# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: CC0-1.0

"""Build the IIIF manifest the facsimile viewer reads.

A deployed TEI Publisher answers ``api/iiif/<doc>`` with a generated manifest.
This example is a static export with no such endpoint, so the manifest is built
once, here, and shipped as a chunking asset. See the Facsimiles section of the
README for how ``[transform.parameters] static`` makes ``<pb-facs-link>`` point
at it.

Run it from the example root after changing the source document, or if the
image server ever moves::

    uv run python scripts/build_manifest.py

The output path mirrors what the ODD emits: ``iiif/<document-name>/manifest.json``,
which ``[chunking] assets`` copies to ``chunks/assets/<document-name>/manifest.json``.

Dimensions are read from each image's IIIF ``info.json`` rather than assumed —
the folios differ (1320, 1380, 1384, …) and Tify places tiles from them, so a
single hard-coded size would misalign the deep-zoom levels.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from lxml import etree

from opm.transform import xpath_select

# Where the Bodleian First Folio scans are served from. The same host the
# TEI Publisher demo's manifest points at.
IMAGE_BASE = 'https://apps.existsolutions.com/cantaloupe/iiif/2'
# Canvas identifiers only have to be stable and unique; nothing dereferences
# them. This keeps the shape the TEI Publisher demo uses.
CANVAS_BASE = 'https://e-editiones.org/canvas'
MANIFEST_BASE = 'https://e-editiones.org/manifest'

DEFAULT_SOURCE = Path('data/F-ado.xml')


def first(result: list):
    """First item of an XPath result, or ``None`` when it selected nothing."""
    return result[0] if result else None


def facs_filename(pb: etree._Element) -> str:
    """Image filename from ``@facs``.

    The Folio files use a ``FFimg:`` prefix (a TEI ``prefixDef`` convention);
    the image server addresses the bare filename.
    """
    return pb.get('facs', '').split(':', 1)[-1]


def image_size(service_id: str) -> tuple[int, int]:
    try:
        with urllib.request.urlopen(f'{service_id}/info.json', timeout=30) as fh:
            info = json.load(fh)
    except urllib.error.URLError as e:
        raise SystemExit(f'could not read {service_id}/info.json: {e}') from e
    return info['width'], info['height']


def build(source: Path) -> dict:
    # opm's own XPath helper: unprefixed names resolve against the document's
    # default namespace, so TEI needs no prefix bookkeeping here. normalize-space
    # collapses the line breaks the title carries in the source.
    root = etree.parse(str(source)).getroot()
    title = first(
        xpath_select(root, 'normalize-space((//teiHeader/fileDesc/titleStmt/title)[1])'),
    ) or source.name

    canvases = []
    # The predicate skips a pb without @facs — nothing to show for one.
    for pb in xpath_select(root, '//pb[@facs]'):
        name = facs_filename(pb)
        service_id = f'{IMAGE_BASE}/{name}'
        width, height = image_size(service_id)
        print(f'  {name}  {width}x{height}', file=sys.stderr)
        canvas_id = f'{CANVAS_BASE}/{name}'
        canvases.append({
            '@id': canvas_id,
            '@type': 'sc:Canvas',
            'label': f'Folio {pb.get("n")}',
            'width': width,
            'height': height,
            'images': [{
                '@type': 'oa:Annotation',
                'motivation': 'sc:painting',
                'on': canvas_id,
                'resource': {
                    '@id': f'{service_id}/full/full/0/default.jpg',
                    '@type': 'dctypes:Image',
                    'format': 'image/jpeg',
                    'width': width,
                    'height': height,
                    'service': {
                        '@context': 'http://iiif.io/api/image/2/context.json',
                        '@id': service_id,
                        'profile': 'http://iiif.io/api/image/2/level2.json',
                    },
                },
            }],
        })

    if not canvases:
        raise SystemExit(f'{source}: no <pb facs="…"/> found, nothing to build')

    return {
        '@context': 'http://iiif.io/api/presentation/2/context.json',
        '@id': f'{MANIFEST_BASE}/{source.name}',
        '@type': 'sc:Manifest',
        'label': title,
        'metadata': [
            {'label': 'Source', 'value': 'Bodleian First Folio, Arch. G c.7'},
        ],
        'sequences': [{'@type': 'sc:Sequence', 'canvases': canvases}],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        'source', nargs='?', type=Path, default=DEFAULT_SOURCE,
        help=f'TEI document to read pb/@facs from (default: {DEFAULT_SOURCE})',
    )
    parser.add_argument(
        '-o', '--output', type=Path, default=None,
        help='manifest path (default: iiif/<document-name>/manifest.json)',
    )
    args = parser.parse_args()

    out = args.output or Path('iiif') / args.source.name / 'manifest.json'
    manifest = build(args.source)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')

    count = len(manifest['sequences'][0]['canvases'])
    print(f'{count} canvases -> {out}', file=sys.stderr)


if __name__ == '__main__':
    main()
