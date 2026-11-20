# Profiles

Many digital editions need the same building blocks: a search box, links to
the previous and next letter, a register of the people and places a text
mentions, or a facsimile beside the transcription. Instead of building these
into your own templates, you can switch on a **profile** that brings
everything a feature needs: the markup on the page, its stylesheet, the
fragments it takes from your documents, and any work to be done once the site
is written.

Profiles follow the profiles of [jinks](https://github.com/eeditiones/jinks),
TEI Publisher's application generator, and use the same names and settings
where they exist there.

## Switching a profile on

List the profiles you want under `profiles` in the `[project]` section of
`opm.toml`:

```toml
[project]
profiles = ["edition-navigation", "registers"]
```

The next time you run `opm chunk`, every page gets the profiles' additions.
You do not need to change your templates, as long as they extend opm's page
layout, `opm/layout.html.tpl`, which provides the places a profile fills in:
the columns beside the text, the menu bar and the area above the text.
Profiles only work with jinks templates (ending in `.tpl`), not with Jinja2
templates.

## Changing a profile's settings

Each profile has settings with sensible defaults. You change them in your own
`[context.features.<name>]` section, where `<name>` is the profile's name for
its feature. You only list what you want to change. The Escher example, for
instance, puts the register in the left column under a German heading:

```toml
[context.features.register]
column = "before"
label = "Kontexte"
```

Every profile has the setting `enabled`. Set it to `false` to hide a profile's
additions without removing it from the list.

A profile's stylesheet is linked before your own, so you can restyle anything
it shows in your project's stylesheet.

## The bundled profiles

### pagefind: search

Adds a search button to the menu bar and builds a search index of all your
documents with [Pagefind](https://pagefind.app) once `opm chunk` has written
the pages. Search works without a server: the index is a set of files next to
your pages, in `assets/search/`.

| Setting (`[context.features.pagefind]`) | Default | Meaning |
|---|---|---|
| `base` | `"search"` | Folder below `assets/` the index goes into |
| `language` | `[context] lang`, else `"en"` | Language of the index |

The index is built from the same records as `opm index`, so the `[index]`
section of `opm.toml` applies. With `granularity = "page"`, each search result
is one page. See [Search indexing](search-indexing.md).

### edition-navigation: previous and next document

Adds two rows of links above the text: the previous and next document of the
edition, and the previous and next letter exchanged between the same
correspondents. It is meant for correspondence editions which record these
links in `<correspContext>`.

Your ODD provides the information through the `edition-navigation` mode: a
hidden element whose attributes name the neighbouring documents, e.g.

```html
<nav hidden="hidden" data-previous="B0095" data-next="B0097"
     data-previous-in-correspondence="" data-next-in-correspondence="B0097"
     data-correspondence="Heinrich Schweizer – Alfred Escher"></nav>
```

The names are those of the documents' folders in the output, or their file
names; a trailing `.xml` does not matter. A neighbour gets a link only if it
was chunked in the same run. The ODDs of the Serafin and Escher examples show
how to write the model.

| Setting (`[context.features.edition-navigation]`) | Default |
|---|---|
| `previous_label`, `next_label` | `"Previous in edition"`, `"Next in edition"` |
| `previous_in_correspondence_label`, `next_in_correspondence_label` | `"Previous letter"`, `"Next letter"` |
| `correspondence_label` | `"Correspondence"` |
| `label` | `"Edition navigation"` (read out by screen readers) |

### registers: people and places

Shows the register of a document beside its text, and adds browse pages for
the people and places registers, rendered into the chunk output after the
reading view.

The overviews, `people/index.html` and `places/index.html`, list every entry
alphabetically under its first letter, with a row of letters to jump by. Each
entry is rendered by your ODD's `register-overview` mode, as in TEI Publisher.
When the entries carry coordinates (`teipublisher.odd` gives places a map pin),
a map with all of them sits above the list.

Each entry also gets a page of its own, `people/{xml:id}.html` or
`places/{xml:id}.html`. It shows the entry as your ODD renders it and lists
the documents that mention it, that is, whose text points to the entry with
`@key` or `@ref`.

The pages read `data/registers/persons.xml` The pages read `data/registers/persons.xml`
and `data/registers/places.xml` by default. Point them at your own register
files with a `[[pages]]` entry of the same `path` in `opm.toml`, or switch one
off with `enabled = false`; when a source file is missing, that register's
pages are skipped. To link the overviews in the menubar, add them to
`[context.menu] items` yourself (see
[The menu bar and the toolbar](templates-and-css.md#the-menu-bar-and-the-toolbar)).
See [Auxiliary pages](chunking.md#auxiliary-pages).

What the sidebar register lists is
decided by your ODD's `register` mode: `teipublisher.odd` looks up every
person and place a document names in the registers under
`$global:register-root`.

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

### iiif: facsimile viewer

Shows the facsimile in the right column. The viewer follows the
`<pb-facs-link>` elements your ODD writes for page breaks, so the facsimile
turns with the text. It needs TEI Publisher's web components:
`webcomponents = true` under `[transform.web]`.

| Setting (`[context.features.iiif]`) | Default | Meaning |
|---|---|---|
| `viewer` | `"pb-tify"` | `"pb-tify"` for IIIF manifests, `"pb-facsimile"` for single images from a IIIF image server |
| `base_uri` | `""` | For `pb-facsimile`: the image server address each image name is added to |
| `label` | `"Facsimile"` | Read out by screen readers |

The Shakespeare example uses `pb-tify` with manifests it ships itself, the
Escher example `pb-facsimile` with the edition's image server.

## Writing your own profile

A profile is a folder with a file called `opm-profile.toml`. Put it in a
folder called `profiles/` in your project, and list its name under
`[project] profiles` like any other profile. opm looks for profiles in your
project's `profiles/` folder first, then in `~/.opm/profiles/` on your
computer, then among the bundled ones. A profile of your own with the name of
a bundled one replaces it.

A profile can contain:

```
profiles/my-feature/
├── opm-profile.toml
├── templates/
│   └── my-feature.html.tpl
├── assets/
│   └── my-feature.css
└── build.py
```

`opm-profile.toml` says what to do with these files:

```toml
name = "my-feature"
description = "What the profile adds"

# Copied to the output's assets/ folder; stylesheets are linked from every page.
assets = ["assets/my-feature.css"]

# Templates whose blocks are added to every page.
[templating]
use = ["my-feature.html.tpl"]

# Fragments added to every chunking run, unless the project has one of the
# same name.
[[chunking.fragments]]
name = "my_fragment"
xpath = "./ancestor-or-self::*[last()]"
parameters = { mode = "my-mode" }

# Auxiliary pages added to the site, unless the project declares a page with
# the same path. "template" resolves against the profile folder, "source"
# against the project root.
[[pages]]
path = "places/{xml_id}.html"
menu = "Places"
source = "data/registers/places.xml"
xpath = "//listPlace/place"
template = "templates/place.html.tpl"

# Python functions to call once all pages are written.
[hooks]
after_chunking = ["build.py:build"]

# Default settings, merged into the project's [context].
[context.features.my-feature]
enabled = true
```

Keep the order: in TOML, everything below a `[section]` heading belongs to that
section, so `assets` has to come before the first heading. opm reports a
setting it does not expect, which usually means it ended up in the wrong
section.

The template fills blocks of opm's page layout, e.g. `after` for the right
column or `above-content` for the area above the text. If both your page
template and a profile fill the same block, both appear, one after the other:

```html
<template>
    [% template after %]
    [% if $context?features?my-feature?enabled %]
    <aside class="my-feature">[[ $context?fragments?my_fragment ]]</aside>
    [% endif %]
    [% endtemplate %]
</template>
```

A `[[pages]]` entry makes the profile contribute standalone pages of the site
— register browsers, an about page — rendered by `opm chunk` after the
chunking runs; see [Auxiliary pages](chunking.md#auxiliary-pages). A hook is
a Python function in a file of the profile, for everything that is not a
page: it receives the project and a description of the finished run, including
the output folder and the documents. The bundled `pagefind` profile's
`search.py` is a complete example.
