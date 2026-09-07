#!/usr/bin/env python3
"""Query a ChromaDB collection built by ``examples/index_chroma.py``.

Chroma stores the embedding function with the collection, so a query only has
to open the same persistent directory and pass text — the same model that
embedded the passages embeds the question::

    uv run --with chromadb examples/query_chroma.py "how do I chunk a document"

Point ``--path``/``--collection`` at whatever ``index_chroma.py`` wrote, and
narrow with metadata: ``--doc quickstart`` or a raw ``--where`` filter.  The
metadata fields available are the ones ``opm index`` emits — ``doc``, ``source``,
``xpath``, ``title``, ``heading``, ``breadcrumb``, ``xml_id``, ``chunk``,
``href``, ``part``, ``n_parts``, ``chars``, ``hash``.

``href`` is the reason to index at all: it points at the chunk file and anchor
that ``opm chunk`` produced, so a hit can be turned straight into a link.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap


def build_where(args) -> dict | None:
    """Combine the ``--doc`` shorthand with a raw ``--where`` filter."""
    clauses: list[dict] = []
    if args.doc:
        clauses.append({'doc': args.doc})
    if args.where:
        clauses.append(json.loads(args.where))
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {'$and': clauses}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query', help='the question, in plain language')
    parser.add_argument(
        '--path', default='.chroma', help='persistent Chroma directory (default: .chroma)',
    )
    parser.add_argument(
        '--collection', default='opm', help='collection name (default: opm)',
    )
    parser.add_argument(
        '-n', '--n-results', type=int, default=5, help='hits to show (default: 5)',
    )
    parser.add_argument('--doc', help='restrict to one document id')
    parser.add_argument('--where', help='raw Chroma metadata filter, as JSON')
    parser.add_argument(
        '--full', action='store_true', help='print whole passages, not a snippet',
    )
    args = parser.parse_args()

    try:
        import chromadb
    except ImportError:
        print(
            'chromadb is not installed — run: uv run --with chromadb '
            'examples/query_chroma.py ...',
            file=sys.stderr,
        )
        return 1

    client = chromadb.PersistentClient(path=args.path)
    try:
        collection = client.get_collection(args.collection)
    except Exception:
        names = [c.name for c in client.list_collections()]
        print(
            f'no collection {args.collection!r} in {args.path} — '
            f'found: {", ".join(names) or "none"}',
            file=sys.stderr,
        )
        return 1

    hit = collection.query(
        query_texts=[args.query],
        n_results=args.n_results,
        where=build_where(args),
        include=['documents', 'metadatas', 'distances'],
    )

    ids = hit['ids'][0]
    if not ids:
        print('no matches')
        return 0

    for rank, (record_id, document, metadata, distance) in enumerate(
        zip(ids, hit['documents'][0], hit['metadatas'][0], hit['distances'][0]), start=1,
    ):
        metadata = metadata or {}
        label = metadata.get('breadcrumb') or metadata.get('heading') or record_id
        print(f'{rank}. {label}  [distance {distance:.4f}]')
        print(f'   id {record_id}')
        if metadata.get('href'):
            print(f'   href {metadata["href"]}')
        body = document if args.full else textwrap.shorten(document, 300, placeholder=' …')
        print(textwrap.indent(textwrap.fill(body, 88), '   '))
        print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
