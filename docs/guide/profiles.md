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

When you create a project with `opm init`, you are asked which profiles you
want. You can also name them on the command line:

```bash
opm init my-edition --profile registers --profile pagefind
```

To see which profiles exist, and which ones your project already uses, run
this inside the project:

```bash
opm profile list
```

To switch a profile on or off later:

```bash
opm profile add edition-navigation
opm profile remove pagefind
```

These commands only change one line in `opm.toml`: the list of profiles in
its `[project]` section. You can just as well edit that line yourself:

```toml
[project]
profiles = ["edition-navigation", "registers"]
```

Some profiles need data or settings of your own before they show anything.
The registers profile, for example, needs your register files. The sections
below say what each profile expects.

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

Each profile's description below is its README, which `opm profile show <name>`
prints in the terminal.

--8<-- "src/opm/resources/profiles/pagefind/README.md"

--8<-- "src/opm/resources/profiles/edition-navigation/README.md"

--8<-- "src/opm/resources/profiles/registers/README.md"

--8<-- "src/opm/resources/profiles/iiif/README.md"

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
├── README.md
├── templates/
│   └── my-feature.html.tpl
├── assets/
│   └── my-feature.css
└── build.py
```

`README.md` is the profile's documentation: `opm profile show my-feature`
prints it. Describe what the profile adds and what it needs from a project,
and its settings. Put what a project must prepare under a heading
"Before you start": `opm profile add my-feature` prints that section, so
whoever switches the profile on sees what is left to do.

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

# Auxiliary pages added to the site. A project's page with the same path
# changes only the keys it sets. "template" resolves against the profile folder, "source"
# against the project root.
[[pages]]
path = "places/{xml_id}.html"
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
