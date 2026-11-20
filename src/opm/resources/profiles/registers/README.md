### registers: people and places

Shows the register of a document beside its text: the people and places it
mentions. It also adds pages to browse the registers:

- `people/index.html` and `places/index.html` list every entry alphabetically
  under its first letter, with a row of letters to jump by. When the entries
  carry coordinates, as places do in `teipublisher.odd`, a map with all of
  them sits above the list.
- `people/{xml:id}.html` and `places/{xml:id}.html` show one entry each,
  followed by the documents that mention it.

#### Before you start

1. Put your registers in `data/registers/persons.xml` (a `<listPerson>` of
   `<person>` entries) and `data/registers/places.xml` (a `<listPlace>` of
   `<place>` entries), each entry with an `xml:id`. A register you do not
   have is skipped.
2. Tell your ODD where the registers are, so the column beside the text can
   look up the people and places a document names. In `opm.toml`,
   `register-root` under `[transform.variables.global]` gives the registers a
   name; a project made with `opm init` already has
   `register-root = "urn:registers"`. List the files under that name. In a
   project made with `opm init`, this entry is already there, commented out:

    ```toml
    [[transform.collections]]
    uri = "urn:registers"
    documents = ["data/registers/persons.xml", "data/registers/places.xml"]
    ```

3. Tell your ODD where your documents are, so an entry's page can list the
   ones that mention it. Give them a name as `data-default` and list them
   under that name; a pattern such as `*.xml` takes every matching file:

    ```toml
    [transform.variables.global]
    register-root = "urn:registers"
    data-default = "urn:documents"

    [[transform.collections]]
    uri = "urn:documents"
    documents = ["data/*.xml"]
    ```

4. Link the overviews in the menu bar:

    ```toml
    [context.menu]
    items = [
        { label = "People", url = "people/index.html" },
        { label = "Places", url = "places/index.html" },
    ]
    ```

To change one of these pages, declare a `[[pages]]` entry with the same `path`
in `opm.toml`. Only the keys you set change; the rest stays as the profile has
it. Your registers are elsewhere? Set your own `source`. Want the overview
headed in another language? Set `menu`, which also leads the breadcrumb of
each entry's page:

```toml
[[pages]]
path = "people/index.html"
menu = "Personen"
```

To switch a page off, set `enabled = false`. See
[Auxiliary pages](chunking.md#auxiliary-pages).

#### What the pages show

The column beside the text comes from your ODD's `register` mode, the
overview entries from its `register-overview` mode, and an entry's own page
from its `register-details` mode, with the parameter `static` set:
`teipublisher.odd` has all three. Its `register-details` mode lists the
documents whose text names the entry with `<persName>` or `<placeName>`
and a matching `@key` or `@ref`. To count other references, change the
`person` and `place` models in your own ODD; the Escher example also counts
a letter's sender and addressee, and links each letter to its page.

#### Settings

| Setting (`[context.features.register]`) | Default | Meaning |
|---|---|---|
| `column` | `"after"` | `"before"` (left) or `"after"` (right) of the text |
| `label` | `"Register"` | Heading above the register; `""` for none |
| `categories` | `[]` | Show several registers as tabs, see below |
| `category_labels` | | Tab labels, e.g. `{ people = "Personen" }` |

To show people and places in separate tabs, as the Serafin example does, add
one fragment per category to your `[chunking]` section, named
`register_<category>`, and list the categories:

```toml
[context.features.register]
categories = ["people", "places"]

[[chunking.fragments]]
name = "register_people"
xpath = "./ancestor::TEI"
parameters = { mode = "register", category = "people" }

[[chunking.fragments]]
name = "register_places"
xpath = "./ancestor::TEI"
parameters = { mode = "register", category = "places" }
```
