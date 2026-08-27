# Integration with TEI Publisher

TEI Publisher normally turns XML into HTML at the moment a reader opens a page.
That is flexible, but for a large edition every click can mean waiting on the
server. `opm` can do that work in advance: it splits each document into the same
sections [`pb-view`](https://teipublisher.com/doc/documentation.xml?id=webcomponents#webcomponents)
would show, writes them as ready-made files, and TEI Publisher then serves those
files instead of transforming on the fly.

The walkthrough below uses the TEI Publisher documentation itself as an example.
The same steps apply to your own edition.

## Before you start

Every division that should appear as its own page must have an `xml:id`. In the
documentation those are DocBook `section` elements; in a TEI edition they are
usually `div`s:

```xml
<section xml:id="introduction">
    <title>Introduction</title>
    …
</section>
```

TEI Publisher can also address a section by an internal database identifier.
`opm` works on files and has no access to those, so a stable `xml:id` is the
only way to match a prepared page to what `pb-view` asks for. Identifiers must
be unique within the document.

You also need a TEI Publisher application — either one you generated with
[Jinks](https://github.com/eeditiones/jinks) using the docs blueprint, or an
app already installed under the name `tei-publisher`.

## 1. Generate the pages

From this repository, with the jinks sources checked out next to it, chunk every
documentation file in one go:

```bash
uv run opm chunk ../jinks/profiles/docs/data/doc -c teipublisher.toml --format pb-view
```

`--format pb-view` writes files in the layout `pb-view` expects when it loads
prepared content. The result lands in `chunks/`, with one subdirectory per
document (`chunks/doc/quickstart.xml/`, `chunks/doc/documentation.xml/`, …).

## 2. Upload them into the app

Copy the `chunks/` tree into a collection called `cached` inside the
application. [`xst`](https://github.com/eXist-db/xst) is the command-line client
for eXist-db:

```bash
xst upload chunks/ /db/apps/tei-publisher/cached/ -v
```

Change `tei-publisher` if your application uses a different name (the
`pkg.abbrev` value in Jinks).

After this, a section of the Gentle Introduction lives at a path such as
`/db/apps/tei-publisher/cached/doc/quickstart.xml/introduction.json`.

## 3. Point the app at the cache

In Jinks, open the application's `config.json` and add a `view-static` default.
The value is the name of the collection you uploaded to:

```json
"defaults": {
    "view-static": "cached"
}
```

If `defaults` is already there — for example with a `site-root` — add
`view-static` next to the other keys, do not replace the whole object.

Then regenerate the application so the page templates and URL routing pick up
the new setting. From then on, `pb-view` loads prepared pages from `cached/`
instead of calling the live transform. If a page is missing from the cache, TEI
Publisher falls back to transforming on the fly.

## Matching the split to TEI Publisher

The example command reads its settings from `teipublisher.toml` in this
repository. A smaller, self-contained copy of the same setup lives in
[`examples/docbook`](../../examples/docbook) (one article, handbook template,
local `opm.toml`). Two settings must line up with how TEI Publisher already
displays the documents.

### `depth`

How far down the section hierarchy to split. This is the same number
`pb-view` already uses for the document — typically in its
`<?teipublisher?>` processing instruction:

```xml
<?teipublisher odd="docbook.odd" template="documentation.html" fill="1" depth="2"?>
```

```toml
[chunking]
depth = 2
```

If `depth` here does not match the depth TEI Publisher uses, the prepared pages
will not correspond to what `pb-view` requests.

Most of the documentation files use depth 2, and that is what the example
config sets. A document with a different depth in its processing instruction
should be chunked with that same number.

### `doc_path`

`pb-view` looks up a document by its path relative to the app's data
collection. The documentation lives in the `doc/` subcollection
(`doc/quickstart.xml`, `doc/documentation.xml`, …), so:

```toml
[chunking]
doc_path = "doc"
```

`opm` then writes `chunks/doc/quickstart.xml/…`. Uploading `chunks/` to
`cached/` produces `cached/doc/quickstart.xml/…`, which is exactly where
`pb-view` looks when `view-static` is `cached`.

For a TEI collection stored under `letters/` or `edition/`, set `doc_path` to
that subcollection name.

### Other settings in the example

A few more keys in `teipublisher.toml` matter for this workflow:

| Setting | Role in this example |
| --- | --- |
| `[transform] odd` | `odd/docbook.odd` — the documentation is written in DocBook, not TEI |
| `selector` | `opm.navigation.dbk_section_chunks` — split on DocBook `section` (use `tei_div_chunks` for TEI `div`) |
| `[transform.web.webcomponents] enabled` | `true` — emit TEI Publisher web components so the cached HTML works inside `pb-view` |
| `[[chunking.fragments]]` | Extra pieces the documentation page also needs: title, table of contents, breadcrumbs |

The full set of chunking options is in [Chunking](chunking.md).

## Your own edition

The same three steps apply outside this repository: chunk your XML with
`--format pb-view`, upload the output into `cached/` of your app, and set
`defaults.view-static` to `cached` in that app's Jinks `config.json`. Point
`odd`, `selector`, `depth`, and `doc_path` at the vocabulary, split, and
collection you already use in TEI Publisher.
