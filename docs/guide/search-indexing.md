# Search indexing

A published edition is only as findable as its index. `opm index` prepares
that index from the same processing model that produces the reading view, so
what a reader sees on the page is also what a search can retrieve.

Each passage becomes one line of JSON: the text to search or embed, a handful
of labels, and — where the project is split into pages — a link back to the
spot in the edition.

```bash
opm index examples/tei-test.xml -o records.jsonl
opm index data/ -o corpus.jsonl          # a directory, subdirectories included
opm index -o corpus.jsonl                # no path: defaults to ./data
```

The file is not tied to a particular search engine. You load it into a vector
database, Elasticsearch, or even a small in-browser search. What `opm` takes
on is editorial: how the source is sliced into passages, and which labels and
extra hits those passages should carry.

## Why the processing model

Indexing the TEI as raw XML would copy every abbreviation twice (`Mr` and
`Mister`), keep apparatus the ODD had omitted, and miss expansions a template
had written out. `opm index` runs the ODD instead, in
[JSON output mode](output-formats.md#json). Change the processing model and
the index changes with it — the same relationship the HTML view already has
to the ODD.

Content the ODD suppresses (`omit`, and similar) never reaches the index,
whatever else you configure.

## Two questions to settle first

Two questions are easy to mix up.

The first is **how large a passage should be**. A chapter, a letter, a
paragraph? That is the size of the index: each passage becomes one retrievable
item. In the configuration this is a *unit*.

The second is **what to attach to a passage** without changing that size. A
person name should stay in the sentence, yet you may want to filter results by
who is mentioned. A footnote sits inside a paragraph, but readers often search
for the note. The trail in the page navigation should appear on every hit from
that page. In the configuration these are *fields*.

Units define passages. Fields annotate them, lift a nested piece out as an
extra hit, or copy a piece of page furniture the ODD already produces.

## What a record looks like

Each line of the JSONL file is one passage:

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

`document` is the text that will be searched or embedded. `metadata` is a
flat map of labels: a heading is a string, a character count is a number,
the people mentioned in a passage are a list of names. Nested objects are
left out, so a record loads into a search engine without reshaping.

Ids are stable across re-indexing: `{document}#{xml:id}` when the passage has
an `xml:id`, otherwise a hash of its path. The `xml:id` form is not tied to a
page filename, so a passage keeps its identity if you later split the edition
into different pages.

`heading` is the local title of a titled division. `breadcrumb` appears only
if you declare a field for it (see [Referencing fragments](#referencing-fragments)
below). `kind` names a declared unit or an extracted field; `parent` points
an extracted hit back at the passage it came from.

## Choosing passages

With no extra configuration, `opm index` treats **titled divisions** as
passages: a chapter, a section, a `div` that carries a heading. That is a
sensible default for a handbook or a monograph. Nested divisions with their
own headings become nested passages. A heading with no body to speak of is
dropped as noise (see [Controlling the length of passages](#controlling-the-length-of-passages)
below).

You do not have to think in XML element names here. The indexer follows the
*behaviour* the ODD assigned — `section`, or any block that opens with a
heading — so a TEI `div` and a DocBook `section` land in the same kind of
passage if the processing model presented them that way.

### Smaller passages

Correspondence, drama, or a lexicon often want a smaller item than a chapter.
`[[index.units]]` *replaces* the default. Each entry names the behaviours (or,
if you must, the elements or models) that should open a passage.

```toml
[[index.units]]
name = "paragraph"
behaviours = ["paragraph"]
```

Note that you can configure more than one `[[index.units]]`, each defining a certain type 
of passage to index.

## Extracting metadata

Metadata fields are attached to the passage, they stay connected to it. A full 
text search engine can use a metadata entry either as a facet or a field.

In the simplest case, a metadata field is directly copied from the text. It is not
removed from the passage. This would apply, for example, if you index people or places
mentioned:

```toml
[[index.fields]]
name = "persons"
elements = ["persName"]
```

The name remains in `document`. Distinct occurrences are also copied onto
the passage as a list, in document order:

```json
"metadata": {
  "persons": ["Aldo Manuzio", "Serafino"]
}
```

That is the shape a facet wants: each name is a value of its own, not a
string the engine would have to split. Meilisearch, Elasticsearch, and
Chroma all filter an array of strings as they stand. A store that still
wants one string can join the list when the records are loaded.

### Extracting into separate records 

A long note in the middle of a paragraph blurs what the paragraph is about,
and it is often the thing a reader is searching for. Here you want a second
record, tagged so you can include or exclude notes at query time, and linked
back to the paragraph it annotates.

The `metadata = false` setting does this: instead of attaching the field to its parent,
it generates a separate entry, but keeps the link back to the passage it came from.

```toml
[[index.fields]]
name = "note"
elements = ["note"]
metadata = false
```

```json
{
  "id": "letters01#n7",
  "document": "Serafino writes from Kraków, where he had been since March.",
  "metadata": { "kind": "note", "parent": "letters01#pi-1450-03" }
}
```

The paragraph remains a paragraph. The note is extra. Whether notes appear
next to prose in the search interface is then a filter on `kind`, not a
decision baked into the file.

This is also why notes should not be declared as units. A unit *is* a passage:
opening one in the middle of a paragraph would close that paragraph and lose
the sentences after the note. A field with `metadata = false` lifts the note
out while the paragraph continues.

### Referencing fragments

When indexing a document, `opm` uses the rules you defined in the `chunking`
sections of `opm.toml` to paginate the text. This is necessary because you later 
want to link search hits back to the page on which they appear.

However, each chunk may consist of multiple fragments. For example, `title`
or `breadcrumbs` are distinct fragments, computed for each chunk separately.

A field may reference one of those fragments to include its plain text into every record:

```toml
[[chunking.fragments]]
name = "breadcrumbs"
scope = "per-chunk"
xpath = "."
parameters = { mode = "breadcrumb" }

[[index.fields]]
name = "breadcrumb"
fragment = "breadcrumbs"
```

## Controlling the length of passages

A unit longer than `--max-chars` is split at natural boundaries (paragraphs,
blocks, list items, and the like), with `--overlap` pieces of context carried
into the next part so a sentence is not cut off mid-thought. Units shorter
than `--min-chars` are dropped: a heading with no body is retrieval noise, not
a passage.

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

A unit entry may set its own `min_chars` when the global floor would be wrong
for that kind of passage — headings you do intend to retrieve, for example.

## Opening the passage from a hit

A search hit is only useful if the reader can open the passage it came from.
That is the job of `href`: it names the published page and, where possible,
the exact spot on it.

If the project chunks its documents (a `[chunking]` section in `opm.toml`),
`opm index` splits each document into the same pages `opm chunk` publishes,
and indexes them one page at a time. Every record then knows which page it
came from. `href` is that page’s filename, followed by `#` and the passage’s
`xml:id` where it has one:

```json
"chunk": "002.html",
"href": "002.html#pi-first-steps"
```

Without a `[chunking]` section there are no pages to point at: the document is
indexed as a whole and records carry no `href`. The `xml_id` and `xpath`
fields are still there, so you can build your own links to wherever you
publish.

## Using the index

Load the JSONL into a store that matches how
you want to query — vectors, full text, or a script that runs in the browser.

### Loading into ChromaDB

The [source repository](https://github.com/eeditiones/open-processing-model)
includes a worked example using [`chromadb`](https://www.trychroma.com/)
(`examples/index_chroma.py`):

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

The same records go in through `_bulk`. Index `document` as the analysed text
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

`heading` and, if you declared it, `breadcrumb` are worth boosting in a query.
Array fields such as `persons` are keyword arrays; they facet without further
mapping. `href` and `chunk` are the link you render with each hit (see
[Opening the passage from a hit](#opening-the-passage-from-a-hit)).

### Searching in the browser

The JSONL is already one passage per line with the link (and, if you declared
it, the breadcrumb) attached, so it can ship as a static asset beside the
pages and be searched with [MiniSearch](https://github.com/lucaong/minisearch)
— no index server, no build step, and the site stays deployable to any static
host.

Copy the records in with the rest of the site. Under `[chunking]`, `assets`
lands files in `<output>/assets/`, and templates receive an `assets` URL
prefix (`assets` from the collection index, `../assets` from a chunk page):

```toml
[chunking]
assets = ["assets/search.js", "index.jsonl"]
```

Run `opm index` **before** `opm chunk`, or the site ships the previous index.

The client can be small, because the records carry everything a result needs:

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

- **Load lazily.** Build the index on the first keystroke, not on page load —
  a few hundred passages is comfortably under a megabyte, but it should never
  sit in front of first paint.
- **Collapse splits of one passage.** A unit longer than `--max-chars` becomes
  several records sharing one `href`, which otherwise fill the result list
  with the same heading. Results come back score-ordered, so keeping the first
  record per `href` keeps the best one.
- **Group by `title`.** It turns a flat ranking into “where in the corpus this
  is”, which is what `breadcrumb` and `title` are there for.

This scales to a few thousand passages. Past that the whole index still has to
reach the browser on first search, and a tool that shards its index across
files — e.g. [Pagefind](https://pagefind.app/) — will be more adequate.
