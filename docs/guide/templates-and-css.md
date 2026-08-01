# Templates & CSS

When a transform returns a **full document** (the `document` behaviour), HTML and
Typst output are wrapped in a Jinja2 template. Fragment output — for example when
you select a single element with `--xpath` — is **not** wrapped.

## HTML templates

Pass a template with `--template`, or set a default under `[document]` in
`opm.toml`. If none is given, a packaged default template is used. Example
templates ship in `templates/` (`tufte.html.j2`, `bootstrap.html.j2`, …).

```bash
uv run opm transform modules/teipublisher-web.py demo/tei-test.xml \
  --template templates/tufte.html.j2 --css styles/main.css -o out.html
```

### Template variables

A document or chunk template receives:

| Variable | Contents |
| --- | --- |
| `content_html` | The transformed document body (or chunk body) |
| `head_html` | Contents of the transform `<head>` (for full `document` output this includes ODD CSS already) |
| `odd_css` | ODD-generated stylesheet text — use this for **chunk** pages, where the transform is a fragment and `head_html` is empty |
| `user_css` | The stylesheet passed via `--css` / `[document] css` |
| `webcomponents_url` | Script URL when web components mode is enabled |
| `lang` | Document language (defaults to `en`) |
| `chunk` | Chunk metadata (`id`, `file`, `prev`, `next`, …) when rendering via `opm chunk` |
| `fragments` | Named fragment HTML from `[chunking.fragments]` |

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
    {{ content_html | safe }}
  </body>
</html>
```

## Two kinds of CSS

- **ODD-generated CSS** (`odd_css` / sometimes already inside `head_html`) — produced at
  compile time from `<outputRendition>` rules and linked stylesheets in the ODD
  (see [ODD files](odd-files.md)). It styles the classes the transform emits.
  Full-document transforms inject it into `<head>` (so it appears in `head_html`);
  chunked fragment pages rely on the template rendering `{{ odd_css }}`.
- **User CSS** (`user_css`) — your own stylesheet, supplied with `--css` or
  `[document] css`, layered on top.

## Web components

With web components mode enabled (`--webcomponents` or
`[transform.web.webcomponents] enabled`),
`alternate` behaviours emit `<pb-alternate>` and the template loads the
tei-publisher `pb-components` bundle from the configured `cdn`. This integrates
output with the [TEI Publisher](https://teipublisher.com/) web component
ecosystem.

## Typst and DOCX templates

- **Typst** uses `.typ.j2` Jinja2 templates configured under `[transform.typst]`.
- **DOCX** uses a binary `.docx` file as a *style* template (not Jinja2),
  configured under `[transform.docx]` or passed with `--template` — see
  [Output formats](output-formats.md#docx).
