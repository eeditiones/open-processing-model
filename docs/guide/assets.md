# Assets

A web page rarely consists of HTML alone. Your template will usually need a
stylesheet with the design of your edition, perhaps a logo, a background
image, web fonts or a small script making the page interactive. opm calls
such files **assets**.

Assets have to end up next to the pages which use them, so the browser can
find them. You therefore do not copy them into the output yourself. Instead,
you list them in `opm.toml`, and opm copies them for you every time it writes
the output. This matters in particular for `opm chunk`: it deletes and
recreates its output folder on every run, so anything you put there by hand
would be lost.

## Listing your assets

Assets are listed under `assets` in the `[transform.web]` section of
`opm.toml`, right next to the template which uses them. The Serafin example
needs a stylesheet, a background image and a folder of fonts:

```toml
[transform.web]
template = "templates/letter.html.j2"
assets = ["templates/letter.css", "templates/parchment.jpg", "templates/fonts"]
```

Each entry is a path relative to the folder containing `opm.toml`. Where you
keep the files in your project is up to you. A common choice is to keep them
in `templates/`, next to the template.

An entry can be a single file or a whole folder. A folder is copied with
everything inside it, so you do not have to list every font file separately.

An entry may also contain the wildcard characters `*` and `?`. This is useful
if a project has one file or folder per document and you do not want to
extend the list each time you add a document. The Shakespeare example keeps
the IIIF manifests of its facsimiles in one folder per play:

```toml
assets = ["templates/chapbook.css", "iiif/*", "icon.png"]
```

`iiif/*` matches everything directly inside `iiif/`, e.g. the folder `iiif/F-ado.xml`. A matching folder is always copied with all its contents.

If a file in the list does not exist, or a wildcard matches nothing, opm stops
with an error. This way you notice a missing file immediately, rather than
much later as a broken image in the browser.

opm copies every entry into a folder called `assets/`. Only the last part of
the path you listed is kept, i.e. the name of the file or folder itself. The
folders leading to it are dropped:

| Entry in `assets` | Copied to |
| --- | --- |
| `templates/letter.css` | `assets/letter.css` |
| `templates/images/logo.svg` | `assets/logo.svg` |
| `templates/fonts` (a folder) | `assets/fonts/`, with everything inside it |
| `iiif/*` | one folder per match, e.g. `iiif/F-ado.xml` becomes `assets/F-ado.xml/` |

Two entries with the same name, e.g. `templates/logo.svg` and
`images/logo.svg`, therefore end up in the same place, and one overwrites the
other.

Where the `assets/` folder is created depends on the command:

| Command | Location of `assets/` |
| --- | --- |
| `opm chunk` | In the output folder, shared by all documents and the collection index |
| `opm transform --output page.html` | Next to the output file |
| `opm transform --preview` | In a temporary folder, next to the page opened in the browser |

By default, `opm chunk` uses the same assets as `[transform.web]`. If a
chunking run needs different ones, give it its own list under `[chunking]`,
or write `assets = []` to copy none at all:

```toml
[chunking]
assets = ["templates/letter.css", "assets/search.js", "index.jsonl"]
```

## Stylesheets

Stylesheets are the simplest case: you only have to list them. Every entry
ending in `.css` is linked into the page automatically by opm's templates, in
the order in which you listed them. Since later stylesheets take precedence
over earlier ones, put the general ones first and the more specific ones
after them:

```toml
assets = ["templates/chapbook.css", "templates/letter.css"]
```

Stylesheets inside a listed folder are copied, but not linked. Listing a
`fonts` folder therefore does not add any stylesheets to the page by
accident.

A stylesheet can refer to the other assets by their plain filename, because
the browser looks for them next to the stylesheet. With the assets of the
Serafin example above, a background image and a font from the `fonts` folder
are referenced like this:

```css
body {
  background: url("parchment.jpg");
}

@font-face {
  font-family: "Junicode";
  src: url("fonts/Junicode.woff2");
}
```

## Images and scripts in templates

Images, scripts and all other assets are not added to the page automatically.
Your template has to refer to them. Since a chunk page lies in a subfolder of
the output, the path to the `assets/` folder differs from page to page. The
template therefore receives the path in the variable `assets`. Put it
in front of the filename:

```jinja
<img src="{{ assets }}/parchment.jpg" alt="">
```

A script is added in the same way. Put it into the `body_end` block, so it
runs once the content of the page is in place. This is how the Escher example
loads the script which switches between its two readings of a letter:

```jinja
{% block body_end %}
  <script src="{{ assets }}/escher.js"></script>
{% endblock %}
```

The logo in the menu bar is an exception: if `logo` in `[context]` is just a
filename, opm looks for it in the `assets/` folder (see
[The menu bar and the toolbar](templates-and-css.md#the-menu-bar-and-the-toolbar)):

```toml
[transform.web]
assets = ["templates/logo.svg"]

[context]
logo = "logo.svg"
```

## Assets in the ODD

Sometimes the ODD, not the template, needs to point to an asset. In the
Shakespeare example, the model for `<pb>` links each page break to its facsimile,
whose IIIF manifest is an asset. The ODD cannot use the `assets` variable of
the templates, but it can read parameters. Define one in `opm.toml`, using
the placeholder `{prefix}`:

```toml
[transform.parameters]
context-path = "{prefix}assets"
```

opm replaces `{prefix}` with the path from the current page back to the top
of the output: `../` for a chunk page, and nothing for `opm transform`. The
ODD then finds the parameter as `$parameters?context-path`.

## Images in your documents

Images which your XML documents refer to, e.g. with `<graphic url="…"/>` in
TEI, do not need to be listed. When opm writes a chunk page with an image
whose address is a relative path, it looks for the file next to the XML
document, and then in a folder `images/` beside it, and copies it to the
output. EPUB output follows the same rule. Images given as a full web address
are left alone, and images which cannot be found are skipped.
