# Search indexing

`opm index` turns a document into JSONL records sized for an embedding model or
a full-text index — one line per retrievable passage, with flat metadata and a
link back to the published page.

```bash
opm index examples/tei-test.xml -o records.jsonl
opm index data/ -o corpus.jsonl          # a directory, subdirectories included
opm index -o corpus.jsonl                # no path: defaults to ./data
```

## Why index the processing model

While an obvious approach would be to retrieve text out of the source files with XPath, indexing the results of applying the processing model allows you to have better control of what it’s actually indexed. For example:

- `omit` allows you to drop the apparatus, delete readings and editorial matter the page
  does not display. 
- `alternate` picks a reading. For example, if we were to naively scrape `<choice><abbr>XML</abbr><expan>Extensible
  Markup Language</expan></choice>` we will retrieve the string `XMLExtensible Markup Language`, which wouldn’t match neither of the expected
  queries.

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

`metadata` holds **scalars only** — no lists, no nested objects, just single, atomic values. 

Two more keys appear when the project declares
[fields](#fields-notes-names-dates): `kind` and `parent` on a record extracted
from a passage, plus one key per metadata field (e.g. `persons`, `dates`, whatever
you name them).

### Stable ids

Ids are derived from content: `{doc}#{xml:id}` where the passage has
an `xml:id`, otherwise `{doc}#{hash of chunk + xpath}`. The `xml:id` form is
deliberately not scoped to a chunk, so a passage keeps its identity even when
re-chunking moves it to a different page.

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

## Fields: notes, names, dates

By default a passage is indexed as one block of text, and everything inside it —
a footnote, a person name, a date — is part of that block. Often that is not
what you want. A long footnote in the middle of a paragraph blurs what the
paragraph is *about*, and it is frequently the thing a reader is searching for
in its own right. A person name, by contrast, should stay in the sentence, but
you would also like to filter a search by it.

`[[index.fields]]` covers both. A field names the records to pick out — by
`elements`, `behaviours` or `models`, the three handles a JSON record carries —
and says where their text goes:

```toml
[[index.fields]]
name = "note"
elements = ["note"]
metadata = false        # its own record

[[index.fields]]
name = "persons"
elements = ["persName"]
metadata = true         # a facet on the passage (the default)
```

With `metadata = true` the text is joined onto the passage that contains it,
under the field's name, and stays in the prose:

```json
"metadata": {
  "persons": "Aldo Manuzio; Serafino",
  ...
}
```

Repeated values are reported once, and the joining string is `separator`
(default `"; "`). Metadata is scalars (atomic values). If several values that you would like to separate become one string, you need to create a new entry.

With `metadata = false` each match becomes a record of its own, tagged
`kind` and carrying the id of the passage it was taken from:

```json
{
  "id": "letters01#n7",
  "document": "Serafino writes from Kraków, where he had been since March.",
  "metadata": { "kind": "note", "parent": "letters01#pi-1450-03", ... }
}
```

Nothing is decided for you there: whether notes are embedded alongside the prose
is a filter on `kind` in your load script, or a `where` clause at query time. The
same file serves both choices.

### What `inline` decides

One thing cannot be deferred: whether the text stays inside the passage's
`document` string, because that string is what gets embedded. `inline` controls
it, and defaults to whatever `metadata` is — a name reads as part of the
sentence, an extracted note does not:

```toml
[[index.fields]]
name = "note"
elements = ["note"]
metadata = false
inline = true           # keep it in the paragraph as well as extracting it
```

Fields never see content the ODD suppressed — an apparatus with the `omit` behaviour
will stay out of the index whatever you declare. An
extracted record is a unit like any other, so `min_chars` applies: a two-word
note could be dropped as noise, thus you need to lower `[index] min_chars` if short notes matter to
you.

An extracted record takes its own `xml:id` and `xpath` where the fragment has
them, and otherwise inherits the page link of the passage around it — a note
sits on the same page as the text it annotates, so the link is never wrong, only
less precise.

## Links back to the page

A search hit is only useful if the reader can open the passage it came from.
That is the job of `href`: it names the published page, and, where possible, the
exact spot on it.

If the project chunks its documents (a `[chunking]` section in `opm.toml`),
`opm index` splits each document into the very same pages `opm chunk` publishes,
and indexes them one page at a time. Every record then knows which page it came
from, and `href` is that page's filename, followed by `#` and the passage's
`xml:id` where it has one:

```json
"chunk": "002.html",
"href": "002.html#pi-first-steps"
```

`opm index` also notes which page each `xml:id` in the document ended up on, and
prefers that page when it builds the link. So a passage whose id lives on a
different page than the one being indexed still links where a reader will
actually find it.

Without a `[chunking]` section there are no pages to point at: the document is
indexed as a whole and records carry no `href` at all. The `xml_id` and `xpath`
fields are still there, so you can build your own links to wherever you publish.

### Turning `href` into a URL

`href` is relative to the document's own pages, not to the site root, because
each document is chunked into a directory of its own. Chunking a whole
directory, `opm chunk` names that directory after the source *file*, extension
included — `data/doc/quickstart.xml` becomes `chunks/quickstart.xml/001.html`.
A search interface covering several documents therefore has to put the two
halves together:

```python
# 'data/doc/quickstart.xml' and '002.html#pi-first-steps'
# give 'quickstart.xml/002.html#pi-first-steps'
url = metadata['source'].split('/')[-1] + '/' + metadata['href']
```

Take the prefix from `source`, not from `doc`: `doc` is the bare filename stem
(`quickstart`), while the published directory keeps the extension
(`quickstart.xml`).

### When the fragment does not jump

 `opm index` appends the fragment whenever
the source passage has an `xml:id`, but the HTML only gets an `id` attribute
where the ODD's behaviour writes one. An ODD that renders no ids gives you
links that open the right page and leave the reader at the top of it. If deep
links matter to you, search a chunk's HTML for the id before suspecting the
index.

## Use the indexes

The JSONL generated by OPM is store-neutral so you need to install an additional library to actually exploit the indexes. See below some options. 


### Loading into ChromaDB

In the [source code repository of OPM](https://github.com/eeditiones/open-processing-model) you can find a worked example using [`chromadb`](https://www.trychroma.com/) (see `examples/index_chroma.py`):

```bash
pip install chromadb
opm index examples/tei-test.xml -o records.jsonl
python examples/index_chroma.py records.jsonl
```

It upserts by `id` and skips records whose `hash` is unchanged, so re-running
after an edit re-embeds only what changed.

```python
collection.upsert(
    ids=[r['id'] for r in batch],
    documents=[r['document'] for r in batch],
    metadatas=[r['metadata'] for r in batch],
)
```

### Loading into Elasticsearch

You can also use [Elasticsearch](https://www.elastic.co/elasticsearch) to query the indexed records. The same records go in through `_bulk` — index `document` as the analysed text
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

`breadcrumb` and `heading` are worth boosting in a query; and remember that `href` and `chunk` carry the link you render with each hit (see [Links back to the page](#links-back-to-the-page)).

### Searching in the browser

The JSONL is already
one passage per line with the link and the breadcrumb attached, so it can ship
as a static asset beside the pages and be searched client-side with
[MiniSearch](https://github.com/lucaong/minisearch) — no index server, no build
step, and the site stays deployable to any static host.

Copy the records in with the rest of the site. Under `[chunking]`, `assets`
lands files in `<output>/assets/`, and templates receive an `assets` URL prefix
(`assets` from the collection index, `../assets` from a chunk page):

```toml
[chunking]
assets = ["assets/search.js", "index.jsonl"]
```

Run `opm index` **before** `opm chunk`, or the site ships the previous index.

The client is small, because the records carry everything a result needs:

```js
import MiniSearch from 'https://cdn.jsdelivr.net/npm/minisearch@7.2.0/dist/es/index.js';

const records = (await (await fetch('assets/index.jsonl')).text())
  .split('\n').filter((line) => line.trim())
  .map((line) => JSON.parse(line))
  .map((r) => ({ id: r.id, text: r.document, ...r.metadata }));

const index = new MiniSearch({
  fields: ['heading', 'breadcrumb', 'title', 'text'],
  storeFields: ['heading', 'breadcrumb', 'href', 'source', 'title'],
});
index.addAll(records);

const hits = index.search(query, {
  prefix: true,
  fuzzy: 0.2,
  boost: { heading: 4, title: 2, breadcrumb: 2 },
});
```

Three things are worth getting right:

- **Load lazily.** Build the index on the first keystroke, not on page load — a
  few hundred passages is comfortably under a megabyte, but it should never sit
  in front of first paint.
- **Collapse `part` splits.** A unit longer than `--max-chars` becomes several
  records sharing one `href`, which otherwise fill the result list with the same
  heading. Results come back score-ordered, so keeping the first record per
  `href` keeps the best one.
- **Group by `title`.** It turns a flat ranking into "where in the corpus this
  is", which is what `breadcrumb` and `title` are there for.

This scales to a few thousand passages. Past that the whole index still has to
reach the browser on first search, and a tool that shards its index across
fragments — e.g. [Pagefind](https://pagefind.app/) — will be more adequate.
