### pagefind: search

Adds a search button to the menu bar and builds a search index of all your
documents with [Pagefind](https://pagefind.app) once `opm chunk` has written
the pages. Search works without a server: the index is a set of files next to
your pages, in `assets/search/`.

#### Before you start

Nothing to prepare: Pagefind comes with opm. Run `opm chunk` and the search
button appears on every page. To decide what a search result is, a whole
document or a single page, set `granularity` in the `[index]` section of
`opm.toml`.

#### Settings

| Setting (`[context.features.pagefind]`) | Default | Meaning |
|---|---|---|
| `base` | `"search"` | Folder below `assets/` the index goes into |
| `language` | `[context] lang`, else `"en"` | Language of the index |

The index is built from the same records as `opm index`, so the `[index]`
section of `opm.toml` applies. With `granularity = "page"`, each search result
is one page. See [Search indexing](search-indexing.md).
