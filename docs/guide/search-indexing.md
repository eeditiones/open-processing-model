# Search indexing

`opm index` turns a document into JSONL records sized for an embedding model or
a full-text index — one line per retrievable passage, with flat metadata and a
link back to the published page.

```bash
uv run opm index examples/tei-test.xml -o records.jsonl
uv run opm index data/ -o corpus.jsonl          # a whole directory
```

## Why index the processing model

The obvious approach is to scrape text out of the source with XPath. The
problem is that the source is not what your readers see — the ODD has already
decided that, and those decisions are exactly the ones an index needs:

- `omit` drops the apparatus, deleted readings and editorial matter the page
  does not display. An XPath scrape indexes them, so searches match text that
  appears nowhere on the site.
- `alternate` picks a reading. `<choice><abbr>XML</abbr><expan>Extensible
  Markup Language</expan></choice>` renders as the expansion; scraped naively
  it becomes the string `XMLExtensible Markup Language`, which matches neither
  query.
- Templates expand abbreviations and inject generated text.

`opm index` runs the same processing model the site runs, so the index contains
the reading text and nothing else. Changing the ODD changes the index with it.

## Record shape

```json
{
  "id": "tei-test#pi-first-steps",
  "document": "First steps. To open the visual editor, click…",
  "metadata": {
    "source": "examples/tei-test.xml",
    "doc": "tei-test",
    "title": "TEI Publisher Manual",
    "href": "001.html#pi-first-steps",
    "chunk": "001.html",
    "xml_id": "pi-first-steps",
    "xpath": "/TEI/text[1]/body[1]/div[2]",
    "breadcrumb": "Manual > Getting started > First steps",
    "heading": "First steps",
    "part": 0,
    "n_parts": 1,
    "chars": 812,
    "hash": "9f2c1ab4c8e07d31"
  }
}
```

`metadata` holds **scalars only** — no lists, no nested objects. That is
ChromaDB's constraint, and the strictest of the common ones; Elasticsearch and
others accept the same shape.

### Stable ids

Re-indexing has to upsert in place. A positional counter would mean that adding
one paragraph reshuffles every id after it, so you either re-embed the whole
corpus or accumulate orphaned rows.

Ids are therefore derived from content: `{doc}#{xml:id}` where the passage has
an `xml:id`, otherwise `{doc}#{hash of chunk + xpath}`. The `xml:id` form is
deliberately not scoped to a chunk, so a passage keeps its identity even when
re-chunking moves it to a different page.

`hash` is a digest of `document`, so an incremental load can skip passages whose
text has not changed.

## How passages are chosen

The rollup walks the [`-t json`](output-formats.md#json) record tree — the web
channel, since that is the reading view a search hit links to — and opens a new
unit at each **titled division** — a `section` behaviour, or any record
carrying a heading. Keying on the behaviour name alone is not enough: ODDs
differ on whether a chapter or an act gets `section` or plain `block`, and
missing that collapses a whole work into one unit.

Text is gathered from the `children` runs in document order, so each passage
enters a unit exactly once. Units longer than `--max-chars` are split at record
boundaries with
`--overlap` records of context carried into the next part; units shorter than
`--min-chars` are dropped, since a bare heading is retrieval noise rather than
a passage. Records marked `suppressed` and their contents are skipped.

| Option | Config key | Default |
| --- | --- | --- |
| `--max-chars` | `[index] max_chars` | 1500 |
| `--min-chars` | `[index] min_chars` | 40 |
| `--overlap` | `[index] overlap` | 1 |

```toml
[index]
max_chars = 1200
min_chars = 60
overlap = 1
```

## Links back to the page

Where the project has a `[chunking]` section, each chunk is transformed on its
own and tagged with the file it will be published as, so `href` points at the
real page. That matters because a chunk selector may rebuild its region as a
detached tree whose ids never existed in the source document — an href that
depended on matching `xml:id` would resolve for nothing, while the chunk file is
known either way.

Without a `[chunking]` section the whole document is indexed as one unit tree
and records carry no `href`.

## Loading into ChromaDB

`chromadb` is not an `opm` dependency; the JSONL is store-neutral. A worked
script ships as `examples/index_chroma.py`:

```bash
pip install chromadb
uv run opm index examples/tei-test.xml -o records.jsonl
python examples/index_chroma.py records.jsonl
```

It upserts by `id` and skips records whose `hash` is unchanged, so re-running
after an edit re-embeds only what moved.

```python
collection.upsert(
    ids=[r['id'] for r in batch],
    documents=[r['document'] for r in batch],
    metadatas=[r['metadata'] for r in batch],
)
```

## Loading into Elasticsearch

The same records go in through `_bulk` — index `document` as the analysed text
field and spread `metadata` alongside it:

```python
from elasticsearch import Elasticsearch, helpers
import json

records = [json.loads(line) for line in open('records.jsonl')]
helpers.bulk(Elasticsearch('http://localhost:9200'), [
    {
        '_index': 'opm',
        '_id': r['id'],
        '_source': {'text': r['document'], **r['metadata']},
    }
    for r in records
])
```

`breadcrumb` and `heading` are worth boosting in a query; `href` and `chunk`
carry the link you render with each hit.
