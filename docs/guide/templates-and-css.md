# Templates & CSS

When a transform returns a **full document** (the `document` behaviour), HTML and
Typst output are wrapped in a [Jinja2 template](https://jinja.palletsprojects.com). Fragment output — for example when
you select a single element with `--xpath`, or when `opm chunk` transforms a
section — is **not** a complete HTML document; the template supplies the rest
of the page around it.

## HTML templates

The HTML template used for a page is the first one found among:

1. the template given with `--template` on the command line
2. `[transform.web] template` in `opm.toml`
3. opm's own default template

Chunk pages use the same template, unless `[chunking]` names a template of its
own.

### Templates created by opm init

`opm init` copies one HTML template into the project's `templates/` folder:
`journal` for a JATS project, `chapbook` for all others. With `--templates`,
it copies the alternatives as well:

| Template | Suited for |
| --- | --- |
| `chapbook` | reading a text page by page |
| `journal` | a scholarly article, with masthead and table of contents |
| `handbook` | documentation, with navigation on the left |
| `tufte` | a demo, styled with [Tufte CSS](https://edwardtufte.github.io/tufte-css/) |
| `bootstrap` | a demo, styled with [Bootstrap](https://getbootstrap.com) |

It also copies `document.typ.j2`, the plain Typst template opm uses when no
other is set. Once copied, the templates are yours: edit them in place.

When you run `opm init` in a terminal without `--templates`, it asks whether
you want the alternatives. Combined with `--example`, `--templates` adds them
next to the templates the example already has, without overwriting any of
them.

`chapbook`, `journal` and `handbook` extend opm's page layout
(`opm/layout.html.j2`), so they only contain what makes each of them
different. `tufte` and `bootstrap` extend just `opm/base.html.j2`, because
their frameworks lay out the page themselves. See
[Template inheritance](#template-inheritance).

### Switching to another template

`chapbook`, `journal` and `handbook` each come with a stylesheet of the same
name, which `opm.toml` lists under `assets`. To switch to another template,
change both lines:

```toml
[transform.web]
template = "templates/handbook.html.j2"
assets = ["templates/handbook.css"]
```

To try a template for a single run, pass it on the command line instead:

```bash
opm transform data/sample.xml --template templates/tufte.html.j2 -o out.html
```

### Print templates

`-t print` uses its own template<!-- so reading-view chrome (nav, web components) stays
out of paged output-->:

1. `--template`
2. `[transform.print] template`
3. Packaged `default_print.html.j2` (not `[transform.web] template`)

```toml
[transform.print]
template = "templates/print.html.j2"
```

The DocBook example project contains a complete print template in
`examples/docbook/templates/print.html.j2`.

The same Jinja file can wrap both a full-document transform and chunked pages.
The contents of `<head>` have to work for **both** pipelines, which differ in
how CSS arrives.

### Document vs fragment output

A model with `behaviour="document"` (typically the TEI / DocBook root) emits a
complete HTML tree:

```html
<html>
  <head>
    <meta charset="utf-8">
    <style type="text/css">/* ODD-generated CSS */</style>
  </head>
  <body>…transformed content…</body>
</html>
```

Before the Jinja template runs, that tree is split:

| Variable | Full-document transform (`opm transform` of the root) |
| --- | --- |
| `head_html` | Inner HTML of `<head>`, without the ODD stylesheet |
| `content_html` | Inner HTML of `<body>` |
| `odd_css` | The ODD-generated stylesheet, taken out of `<head>` so the template decides where it goes |

`opm chunk` does **not** start at that root. It transforms each selected
division (`div`, DocBook `section`, a reconstructed page, …). Those elements
use `block` / `heading` / `pb-observable` models and produce a **fragment** —
a `<div>` or similar, not `<html>`. There is no `<head>` to extract:

| Variable | Chunked / `--xpath` fragment |
| --- | --- |
| `head_html` | Empty string |
| `content_html` | The serialized fragment |
| `odd_css` | ODD-generated stylesheet text — the template must emit it |

JSON chunk files expose the same split as `head` and `odd_css` keys: `head` is
empty for normal section chunks.

Either way the ODD stylesheet arrives as `odd_css`. A template that works in
both cases renders `head_html` **and** `odd_css`, the ODD stylesheet last so its
renditions win over the page's own styles:

```jinja
<head>
  <meta charset="utf-8">
  {{ head_html | safe }}
  {% if odd_css %}
  <style type="text/css">{{ odd_css }}</style>
  {% endif %}
</head>
```

`{{ head_html | safe }}` on a chunk page is a no-op. Leave it in so the
template can also wrap `opm transform`. A template that extends one of opm's
templates (see [Template inheritance](#template-inheritance)) does all of this
for you.

### Template variables

A document or chunk template receives:

| Variable | Contents |
| --- | --- |
| `content_html` | The transformed document body, or the chunk/fragment markup |
| `head_html` | Inner HTML of the transform `<head>`, or empty for fragments (see above) |
| `odd_css` | ODD-generated stylesheet text (with chunking also written to a file, see `odd_css_url`) |
| `context` | The project's own `[context]` values — see [Template context](#template-context) |
| `lang` | Document language, from the transformed document's `<html lang>`; empty when unknown (set `context.lang` to fix it) |
| `chunk` | Chunk metadata (`id`, `file`, `prev`, `next`, …) when rendering via `opm chunk` |
| `fragments` | Named HTML or text from `[chunking.fragments]` (chunk templates only) |
| `parameters` | The `[transform.parameters]` map, as also bound to XPath `$parameters` |

A minimal template:

```jinja
<!DOCTYPE html>
<html lang="{{ lang|default('en') }}">
  <head>
    <meta charset="utf-8">
    {{ head_html | safe }}
    {% if odd_css %}<style type="text/css">{{ odd_css }}</style>{% endif %}
    {% if context.webcomponents_url %}<script type="module" src="{{ context.webcomponents_url }}"></script>{% endif %}
  </head>
  <body>
    {% if fragments is defined and fragments.title %}
    <p>{{ fragments.title | striptags }}</p>
    {% endif %}
    {{ content_html | safe }}
  </body>
</html>
```

### Template context

Everything a template needs beyond the transform output comes through one
variable, `context`, filled from a `[context]` table in `opm.toml`:

```toml
[context]
site_name = "The Serafin Letters"
show_downloads = true
nav = [
    { label = "Home", url = "/" },
    { label = "About", url = "/about" },
]
```

```jinja
<h1>{{ context.site_name }}</h1>
<nav>
  {% for item in context.nav %}<a href="{{ item.url }}">{{ item.label }}</a>{% endfor %}
</nav>
{% if context.show_downloads %}<a href="{{ chunk.file }}.pdf">PDF</a>{% endif %}
```
<!--This is how a project drives its own template without a code change. Two
properties matter:

- **TOML types survive.** Booleans stay booleans, numbers stay numbers, and
  arrays and sub-tables arrive as lists and dicts. Nothing but the template
  reads these values, so there is no conversion to a string. `parameters` is
  different — it is bound to XPath `$parameters` and is a flat map of strings.
- **Keys are namespaced.** They live under `context.` rather than at the top
  level, so a project key can never shadow `content_html` or `fragments`, and a
  template makes plain which values are the project's own.
-->

<!--A missing key is falsy rather than an error, so `{% if context.foo %}` is safe
for a value the project has not set.-->

The same `context` reaches document templates, chunk templates, the collection
index template, and Typst templates. To vary it by output type, add a
`[transform.<type>.context]` table — it overlays `[context]` for that type
only:

```toml
[context]
site_name = "The Serafin Letters"

[transform.typst.context]
site_name = "The Serafin Letters — print edition"
paper = "a5"
```

## Template inheritance

Templates can extend other templates, creating an inheritance chain. This lets
you build a page by composing simpler templates: each template in the chain
only adds what is particular to it, and inherits everything else.

opm ships two templates at the root of such chains:

- `opm/base.html.j2` – defines the HTML document itself: the `<head>` with
  stylesheets and scripts, and an empty `<body>`.
- `opm/layout.html.j2` – extends `opm/base.html.j2` and defines the overall
  page structure: header, side columns, content area and footer, and how they
  rearrange on a phone screen.

For example, the inheritance chain for a letter page in the Serafin example is
as follows:

- `templates/letter.html.j2` – is loaded first. It fills the content area with
  the transcription and translation, and the right-hand column with the
  people and places mentioned. Everything else is inherited via the extended
  `serafin.html.j2`.
- `templates/serafin.html.j2` – adds the edition's menu bar and the parchment
  breadcrumb band at the top of the page. The letter list (`index.html.j2`)
  extends it too, so both share the same look.
- `opm/layout.html.j2` – contributes the page layout.
- `opm/base.html.j2` – the root template.

A template says which one it extends in its first line:

```jinja
{% extends "serafin.html.j2" %}
```

### Layout areas and blocks

For template inheritance to be useful, templates further down the chain need a
way to put content into places defined by the templates they extend. These
places are called **blocks**. `opm/layout.html.j2` defines one block for each
area of the page; they are the same layout areas a TEI Publisher (jinks)
application has:

| Block | Where it appears |
| --- | --- |
| `header` | Across the top of the page; it stays visible while the reader scrolls |
| `hero` | Across the page, below the header |
| `before_top`, `before` | A column left of the text, e.g. a table of contents |
| `content_top`, `content` | The text itself; `content` shows the transformed document unless a template fills it |
| `after_top`, `after` | A column right of the text, e.g. a list of people and places |
| `footer` | Across the bottom of the page |

A template fills a block by repeating it with new content:

```jinja
{% block header %}<a href="index.html">My edition</a>{% endblock %}
```

An area left empty takes no room on the page. Besides the layout areas, these
blocks can be filled:

| Block | What it holds |
| --- | --- |
| `title` | The `<title>` element |
| `meta` | More tags in `<head>` |
| `styles`, `scripts` | Extra stylesheets and scripts |
| `odd_overrides` | Styles that must win over the ODD's own, as they come after them |
| `body_class` | Classes for `<body>` |
| `body_end` | Scripts that need the page content to be in place |

Filling a block replaces what the extended template put there. To add to it
instead, start the block with `{{ super() }}`.

If you only want the `<head>` handling without the page layout, extend
`opm/base.html.j2` directly and fill its `body` block. To change one of opm's
templates itself, put a file with the same name in your templates folder, e.g.
`templates/opm/layout.html.j2`: your copy is used in place of opm's.

### Writing your own template

1. Create `templates/page.html.j2` in your project and start it with this
   line:

    ```jinja
    {% extends "opm/layout.html.j2" %}
    ```

2. Add a block for each area you want to fill. This puts the edition's title
   in the header and the work's title above the text:

    ```jinja
    {% block header %}<a href="index.html">My edition</a>{% endblock %}

    {% block content_top %}
      {% if fragments is defined and fragments.title %}{{ fragments.title | safe }}{% endif %}
    {% endblock %}
    ```

3. Point `opm.toml` at the template. Chunk pages use it too, unless
   `[chunking]` names a template of its own:

    ```toml
    [transform.web]
    template = "templates/page.html.j2"
    assets = ["templates/page.css"]
    ```

4. Put your own design in `templates/page.css`, which `assets` copies next to
   the output. The template links it for you.

### Adjusting the layout

The layout's stylesheet is copied to `css/opm-layout.css` when you chunk, and
written into the page for a single transformed document. Change its
measurements from your own stylesheet with these properties:

| Property | Meaning |
| --- | --- |
| `--opm-layout-content-max` | The widest the text column grows (default: all available room) |
| `--opm-layout-before-width`, `--opm-layout-after-width` | Width of the side columns |
| `--opm-layout-gap` | Space between a side column and the text |
| `--opm-layout-gutter` | Smallest space at the left and right edges of the page |
| `--opm-layout-sticky-top` | How far below the top of the window the side columns stop when scrolling, e.g. the height of your header |

```css
body.my-edition {
  --opm-layout-content-max: 42rem;
  --opm-layout-after-width: 16rem;
}
```

On narrow screens the side columns move. By default the `before` column turns
into a panel that slides in when the reader taps a "Contents" button, and the
`after` column moves below the text. The next section shows how to change
that.

## Frontmatter

A template may start with a frontmatter block: settings enclosed between two
lines of three dashes, as in TEI Publisher (jinks). The settings extend the
context map, i.e. the `context` every template receives:

```jinja
{# Comments may come first. #}
---toml
title = "Letters of Mikołaj Serafin"
styles = ["https://fonts.googleapis.com/css2?family=Belleza"]

[body]
classes = ["letter"]

[layout.before]
width = "16rem"
label = "Letters"
mobile = "stack"
---
{% extends "opm/layout.html.j2" %}
```

The settings may be written in TOML (`---toml`), like `opm.toml`, or in JSON
(`---json`, or just `---`), like jinks frontmatter.

opm's templates understand the following settings:

| Setting | Effect |
| --- | --- |
| `title` | The page title, unless a template fills the `title` block |
| `description` | A `<meta name="description">` tag |
| `lang` | The page language |
| `styles` | Stylesheets to link, e.g. web fonts |
| `scripts` | Module scripts to load |
| `body.classes` | Classes for `<body>` |
| `layout.class` | Classes for the layout grid |
| `layout.before.width`, `layout.after.width` | Width of the side columns |
| `layout.before.mobile`, `layout.after.mobile` | On narrow screens, `"drawer"` (slides in) or `"stack"` (below the text) |
| `layout.before.label`, `layout.after.label` | Text of the button that opens a drawer |

Your own templates can read any other setting as `context.<name>`.

### The same settings in opm.toml

Every one of these settings can also go in `opm.toml`, under `[context]`. This
is the easier route when you are happy with a template and only want to adjust
it for your project:

```toml
[context.layout.after]
width = "20rem"
label = "Notes"
```

To change a setting for web pages only, write `[transform.web.context.layout.after]`
instead. The `layout` defaults are listed, with comments, in `opm/defaults.toml`
among opm's templates; the `opm.toml` that `opm init` writes repeats them as a
starting point.

### How the context map is merged

The context map a template receives is merged from several sources, in this
order:

1. opm's defaults (`opm/defaults.toml`)
2. `[context]` in `opm.toml`
3. `[transform.<type>.context]` in `opm.toml`
4. the frontmatter of each template in the inheritance chain, starting with
   the root template and ending with the template being rendered

Merging works as in jinks:

- a setting with a single value (text, number, true/false) overwrites the same
  setting from an earlier source
- tables are merged setting by setting
    - to replace a table entirely, add `"$replace" = true` to it
    - to replace only some of its settings and merge the rest, list them:
      `"$replace" = ["before"]`
- lists are joined, dropping repeated entries. For example, the `styles` of a
  template are added to those of the template it extends.

So frontmatter wins over `opm.toml`: a setting a template fixes in its
frontmatter cannot be changed from `opm.toml`. A template meant to be adjusted
per project should leave such settings out of its frontmatter.

## Two kinds of CSS

- **ODD-generated CSS** — produced at compile time from `<outputRendition>`
  rules and linked stylesheets in the ODD (see [ODD files](odd-files.md)). It
  styles the classes the transform emits. How it reaches the page is described
  above: inside `head_html` for `document` output, via `odd_css` for fragments.
<!--
    It opens with a packaged set of base rules for markup the runtime emits
    regardless of ODD — the `.alternate` / `.altcontent` popover behind
    `choice`, `.tei-cb` column breaks, margin notes. They come first, so an
    ODD's own `outputRendition` overrides them, and they travel with the ODD
    stylesheet everywhere it is used.
-->
- **Base override** (`--css` / `[transform] css`) — replaces those packaged base
  rules for every output mode. It is compiled into the ODD stylesheet rather
  than layered after it, and forms part of the ODD cache key. Use it to restyle
  what the runtime emits; for a project's own design CSS use `[transform.web]
  assets`, which can also carry the images and fonts that stylesheet
  references. Note that `[transform.epub] css` is not a per-mode version of
  this key: it adds a stylesheet to the EPUB package on top of everything else.

## Web components

With web components mode enabled (`--webcomponents` or
`[transform.web] webcomponents = true`),
`alternate` behaviours emit `<pb-alternate>` and `context.webcomponents_url` is
filled in with the pinned default bundle, so the template can load the
tei-publisher `pb-components` bundle:

```jinja
{% if context.webcomponents_url %}
<script type="module" src="{{ context.webcomponents_url }}"></script>
{% endif %}
```

This integrates output with the [TEI Publisher](https://teipublisher.com/) web
component ecosystem. The URL is an ordinary template value with a default, not
a setting of its own: give `webcomponents_url` in `[context]` or
`[transform.web.context]` and yours wins — useful to serve the bundle from your
own host, or to pin a different version.

## Typst and DOCX templates

- **Typst** uses `.typ.j2` Jinja2 templates configured under `[transform.typst]`.
  `opm init` copies `book.typ.j2` (TEI) or `docbook.typ.j2` (DocBook). If none
  is given, the packaged `default_document.typ.j2` is used.
- **DOCX** uses a binary `.docx` file as a *style* template (not Jinja2),
  configured under `[transform.docx]` or passed with `--template`. `opm init`
  copies `templates/default.docx`; a one-off transform falls back to that same
  packaged file — see [Output formats](output-formats.md#docx).
