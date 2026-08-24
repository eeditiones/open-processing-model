# Templates & CSS

When a transform returns a **full document** (the `document` behaviour), HTML and
Typst output are wrapped in a Jinja2 template. Fragment output — for example when
you select a single element with `--xpath`, or when `opm chunk` transforms a
section — is **not** a complete HTML document; the template supplies the shell.

## HTML templates

Pass a template with `--template`, or set a default under `[document]` in
`opm.toml`. Chunk pages use `chunking.template` instead. If none is given, a
packaged default template is used. `opm init` copies editable shells into
`templates/` (chapbook HTML plus Typst and Word templates). Example templates
in this repo (`tufte.html.j2`, `bootstrap.html.j2`, …) are demos, not packaged.

```bash
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd \
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
  {% if user_css %}
  <style type="text/css">{{ user_css }}</style>
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
| `user_css` | The stylesheet passed via `--css` / `[document] css` |
| `webcomponents_url` | Script URL when web components mode is enabled |
| `lang` | Document language (defaults to `en`) |
| `chunk` | Chunk metadata (`id`, `file`, `prev`, `next`, …) when rendering via `opm chunk` |
| `fragments` | Named HTML or text from `[chunking.fragments]` (chunk templates only) |

A minimal template:

```jinja
<!DOCTYPE html>
<html lang="{{ lang|default('en') }}">
  <head>
    <meta charset="utf-8">
    {{ head_html | safe }}
    {% if odd_css %}<style type="text/css">{{ odd_css }}</style>{% endif %}
    {% if user_css %}<style type="text/css">{{ user_css }}</style>{% endif %}
    {% if webcomponents_url %}<script type="module" src="{{ webcomponents_url }}"></script>{% endif %}
  </head>
  <body>
    {% if fragments is defined and fragments.title %}
    <p>{{ fragments.title | striptags }}</p>
    {% endif %}
    {{ content_html | safe }}
  </body>
</html>
```

## Two kinds of CSS

- **ODD-generated CSS** — produced at compile time from `<outputRendition>`
  rules and linked stylesheets in the ODD (see [ODD files](odd-files.md)). It
  styles the classes the transform emits. How it reaches the page is described
  above: inside `head_html` for `document` output, via `odd_css` for fragments.
- **User CSS** (`user_css`) — your own stylesheet, supplied with `--css` or
  `[document] css`, layered on top. Always passed as a separate variable; it is
  never folded into `head_html`.

## Web components

With web components mode enabled (`--webcomponents` or
`[transform.web.webcomponents] enabled`),
`alternate` behaviours emit `<pb-alternate>` and the template loads the
tei-publisher `pb-components` bundle from the configured `cdn`. This integrates
output with the [TEI Publisher](https://teipublisher.com/) web component
ecosystem.

## Typst and DOCX templates

- **Typst** uses `.typ.j2` Jinja2 templates configured under `[transform.typst]`.
  `opm init` copies `book.typ.j2` (TEI) or `docbook.typ.j2` (DocBook). If none
  is given, the packaged `default_document.typ.j2` is used.
- **DOCX** uses a binary `.docx` file as a *style* template (not Jinja2),
  configured under `[transform.docx]` or passed with `--template`. `opm init`
  copies `templates/default.docx`; a one-off transform falls back to that same
  packaged file — see [Output formats](output-formats.md#docx).
