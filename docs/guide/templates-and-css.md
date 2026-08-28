# Templates & CSS

When a transform returns a **full document** (the `document` behaviour), HTML and
Typst output are wrapped in a Jinja2 template. Fragment output — for example when
you select a single element with `--xpath`, or when `opm chunk` transforms a
section — is **not** a complete HTML document; the template supplies the shell.

## HTML templates

Pass a template with `--template`, or set a default under `[document]` in
`opm.toml`. Chunk pages use `chunking.template` instead. If none is given, a
packaged default template is used. `opm init` copies editable shells into
`templates/`: the `chapbook` and `handbook` HTML shells, the `tufte` and
`bootstrap` demo shells, plus the Typst and Word templates. Edit them in place —
they are yours once copied.

```bash
uv run opm transform data/sample.xml \
  --template templates/tufte.html.j2 --css styles/main.css -o out.html
```

The same Jinja file can wrap both a full-document transform and chunked pages.
What you put in `<head>` has to work for **both** pipelines, which differ in
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
| `head_html` | Inner HTML of `<head>` — charset meta **and** the ODD stylesheet |
| `content_html` | Inner HTML of `<body>` |
| `odd_css` | Empty (the same CSS is already inside `head_html`, so it is not passed twice) |

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

A template that works in both cases therefore always renders `head_html` **and**
`odd_css`:

```jinja
<head>
  <meta charset="utf-8">
  {{ head_html | safe }}
  {% if odd_css %}
  <style type="text/css">{{ odd_css }}</style>
  {% endif %}
</head>
```

On a full document, `head_html` already contains the ODD `<style>` and the
`odd_css` branch is skipped. On a chunk page, `head_html` is empty and
`odd_css` supplies the classes the fragment uses (`tei-title`, …).

`{{ head_html | safe }}` on a chunk page is a no-op. Leave it in so the
template can also wrap `opm transform`.

### Template variables

A document or chunk template receives:

| Variable | Contents |
| --- | --- |
| `content_html` | The transformed document body, or the chunk/fragment markup |
| `head_html` | Inner HTML of the transform `<head>`, or empty for fragments (see above) |
| `odd_css` | ODD-generated stylesheet text when it is **not** already in `head_html` |
| `context` | The project's own `[context]` values — see [Template context](#template-context) |
| `lang` | Document language (defaults to `en`) |
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

This is how a project drives its own template without a code change. Two
properties matter:

- **TOML types survive.** Booleans stay booleans, numbers stay numbers, and
  arrays and sub-tables arrive as lists and dicts. Nothing but the template
  reads these values, so there is no conversion to a string. `parameters` is
  different — it is bound to XPath `$parameters` and is a flat map of strings.
- **Keys are namespaced.** They live under `context.` rather than at the top
  level, so a project key can never shadow `content_html` or `fragments`, and a
  template makes plain which values are the project's own.

A missing key is falsy rather than an error, so `{% if context.foo %}` is safe
for a value the project has not set.

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

## Two kinds of CSS

- **ODD-generated CSS** — produced at compile time from `<outputRendition>`
  rules and linked stylesheets in the ODD (see [ODD files](odd-files.md)). It
  styles the classes the transform emits. How it reaches the page is described
  above: inside `head_html` for `document` output, via `odd_css` for fragments.

    It opens with a packaged set of base rules for markup the runtime emits
    regardless of ODD — the `.alternate` / `.altcontent` popover behind
    `choice`, `.tei-cb` column breaks, margin notes. They come first, so an
    ODD's own `outputRendition` overrides them, and they travel with the ODD
    stylesheet everywhere it is used.

- **Base override** (`--css` / `[document] css`) — replaces those packaged base
  rules. It is compiled into the ODD stylesheet rather than layered after it,
  and forms part of the ODD cache key. Use it to restyle what the runtime
  emits; for a project's own design CSS use `[chunking] assets`, which can also
  carry the images and fonts that stylesheet references.

## Web components

With web components mode enabled (`--webcomponents` or
`[transform.web.webcomponents] enabled`),
`alternate` behaviours emit `<pb-alternate>` and `context.webcomponents_url` is
set to the configured `cdn`, so the template can load the tei-publisher
`pb-components` bundle:

```jinja
{% if context.webcomponents_url %}
<script type="module" src="{{ context.webcomponents_url }}"></script>
{% endif %}
```

This integrates output with the [TEI Publisher](https://teipublisher.com/) web
component ecosystem. Setting `webcomponents_url` in `[context]` yourself wins
over the derived value — useful to serve the bundle from your own host instead
of the CDN.

## Typst and DOCX templates

- **Typst** uses `.typ.j2` Jinja2 templates configured under `[transform.typst]`.
  `opm init` copies `book.typ.j2` (TEI) or `docbook.typ.j2` (DocBook). If none
  is given, the packaged `default_document.typ.j2` is used.
- **DOCX** uses a binary `.docx` file as a *style* template (not Jinja2),
  configured under `[transform.docx]` or passed with `--template`. `opm init`
  copies `templates/default.docx`; a one-off transform falls back to that same
  packaged file — see [Output formats](output-formats.md#docx).
