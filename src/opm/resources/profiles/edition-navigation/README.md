### edition-navigation: previous and next document

Adds two rows of links above the text: the previous and next document of the
edition, and the previous and next letter exchanged between the same
correspondents. It is meant for correspondence editions which record these
links in `<correspContext>`.

#### Before you start

Your ODD has to say which documents are the neighbours. `teipublisher.odd`
hands each document's `<correspContext>` to the `edition-navigation` mode, but
leaves rendering it to you: add a model for `correspContext` in that mode to
your project's ODD. It writes a hidden element whose attributes name the
neighbouring documents, e.g.

```html
<nav hidden="hidden" data-previous="B0095" data-next="B0097"
     data-previous-in-correspondence="" data-next-in-correspondence="B0097"
     data-correspondence="Heinrich Schweizer – Alfred Escher"></nav>
```

The ODDs of the Serafin and Escher examples show how to write it
(`opm init --example serafin`).

The names are those of the documents' folders in the output, or their file
names; a trailing `.xml` does not matter. A neighbour gets a link only if it
was chunked in the same run, so chunk the whole folder of letters at once:
`opm chunk data/letters`.

#### Settings

| Setting (`[context.features.edition-navigation]`) | Default |
|---|---|
| `previous_label`, `next_label` | `"Previous in edition"`, `"Next in edition"` |
| `previous_in_correspondence_label`, `next_in_correspondence_label` | `"Previous letter"`, `"Next letter"` |
| `correspondence_label` | `"Correspondence"` |
| `label` | `"Edition navigation"` (read out by screen readers) |
