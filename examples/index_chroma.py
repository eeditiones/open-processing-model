#!/usr/bin/env python3
"""Load ``opm index`` output into a ChromaDB collection.

``chromadb`` is deliberately not an ``opm`` dependency — the JSONL that
``opm index`` writes is store-neutral, and this script is one of several
possible sinks.  Install it yourself::

    pip install chromadb
    opm index examples/tei-test.xml -o records.jsonl
    python examples/index_chroma.py records.jsonl

Re-running is cheap: every record carries a ``hash`` of its text, so unchanged
passages are skipped rather than re-embedded, and ids are derived from
``xml:id`` (or a hash of the XPath) so edits upsert in place instead of
accumulating orphans.

The same records go into Elasticsearch with a ``_bulk`` request — index
``document`` as ``text`` and spread ``metadata`` into sibling fields.  Nothing
in the record shape is Chroma-specific; metadata is flat scalars only, which
is the strictest of the common constraints.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BATCH = 200


def load(path: Path) -> list[dict]:
    with path.open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def existing_hashes(collection, ids: list[str]) -> dict[str, str]:
    """Fetch the stored hash for *ids* so unchanged records can be skipped."""
    found: dict[str, str] = {}
    for start in range(0, len(ids), BATCH):
        got = collection.get(
            ids=ids[start:start + BATCH], include=['metadatas'],
        )
        for record_id, metadata in zip(got['ids'], got['metadatas']):
            if metadata and 'hash' in metadata:
                found[record_id] = metadata['hash']
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('jsonl', type=Path, help='records file from `opm index`')
    parser.add_argument(
        '--path', default='.chroma', help='persistent Chroma directory (default: .chroma)',
    )
    parser.add_argument(
        '--collection', default='opm', help='collection name (default: opm)',
    )
    parser.add_argument(
        '--force', action='store_true', help='re-embed every record, ignoring hashes',
    )
    args = parser.parse_args()

    try:
        import chromadb
    except ImportError:
        print('chromadb is not installed — run: pip install chromadb', file=sys.stderr)
        return 1

    records = load(args.jsonl)
    if not records:
        print(f'no records in {args.jsonl}', file=sys.stderr)
        return 1

    client = chromadb.PersistentClient(path=args.path)
    collection = client.get_or_create_collection(args.collection)

    if args.force:
        pending = records
    else:
        stored = existing_hashes(collection, [r['id'] for r in records])
        pending = [
            r for r in records
            if stored.get(r['id']) != r['metadata'].get('hash')
        ]

    for start in range(0, len(pending), BATCH):
        batch = pending[start:start + BATCH]
        collection.upsert(
            ids=[r['id'] for r in batch],
            documents=[r['document'] for r in batch],
            metadatas=[r['metadata'] for r in batch],
        )

    skipped = len(records) - len(pending)
    print(
        f'upserted {len(pending)} record(s) into {args.collection!r} '
        f'({skipped} unchanged) — {collection.count()} total',
    )

    if pending:
        hit = collection.query(query_texts=[pending[0]['document'][:200]], n_results=1)
        meta = hit['metadatas'][0][0] if hit['metadatas'][0] else {}
        print(f'sanity query → {hit["ids"][0][0]} ({meta.get("href") or "no href"})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
