# Templates & CSS

The transform turns your XML into HTML (or Typst), but that alone is not yet a
web page anyone would want to read: a page also needs a title, stylesheets,
perhaps a menu bar or a table of contents. This is what templates are for. A
template is a [Jinja2](https://jinja.palletsprojects.com) file describing the
page around the transformed text. opm puts the output of the transform into
it, and the result is the final page.

The template is used in two situations:

- you transform a **whole document**, e.g. a TEI file with `opm transform`
- you transform only a **part** of a document. This happens when you pick a
  single element with `--xpath`, or when `opm chunk` splits a document into
  sections and transforms each of them separately. The output is then just a
  piece of HTML, and it is the template which turns it into a complete page.

## HTML templates

opm looks for the HTML template in the following places and uses the first one
it finds:

1. the template given with `--template` on the command line
2. the `template` setting under `[transform.web]` in `opm.toml`
3. opm's own default template

Chunk pages use the same template, unless the `[chunking]` section names a
different one.

### Templates created by opm init

For a new project, `opm init` copies one HTML template into the project's
`templates/` folder: `chapbook` for TEI, `handbook` for DocBook and `journal`
for JATS. If you start from an example (`--example`), you get the templates of
that example instead. With `--templates`, opm copies the alternatives as well:

| Template | Suited for |
| --- | --- |
| `chapbook` | reading a text page by page |
| `journal` | a scholarly article, with masthead and table of contents |
| `handbook` | documentation, with navigation on the left |
| `tufte` | a demo, styled with [Tufte CSS](https://edwardtufte.github.io/tufte-css/) |
| `bootstrap` | a demo, styled with [Bootstrap](https://getbootstrap.com) |

Once copied, the templates are yours: you can edit them as you like.

If you run `opm init` in a terminal without `--templates`, it asks you
whether you want the other templates too. When you start from an example
(`--example`), `--templates` adds them to the templates which come with the
example, but does not overwrite any of them.

`chapbook`, `journal` and `handbook` build on opm's page layout
(`opm/layout.html.j2`), so each of them only contains what is particular to
it. `tufte` and `bootstrap` build only on `opm/base.html.j2`, because Tufte CSS
and Bootstrap come with a page layout of their own. See
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

Output for print (`-t print`) uses a template of its own<!-- so reading-view chrome (nav, web components) stays
out of paged output-->. A page meant for the screen contains many things which
make no sense on paper, like menus or navigation buttons. opm therefore looks
for the print template in different places:

1. the template given with `--template` on the command line
2. the `template` setting under `[transform.print]` in `opm.toml`
3. opm's own `default_print.html.j2`

Note that the template configured for the web is never used for print.

```toml
[transform.print]
template = "templates/print.html.j2"
```

You can find a complete print template in the DocBook example project:
`examples/docbook/templates/print.html.j2`.

### Template variables

Every page template receives the following variables:

| Variable | Contents |
| --- | --- |
| `content_html` | The transformed text: the body of a whole document, or the transformed part (chunk or `--xpath` selection) |
| `context` | Your project's own settings from `[context]` – see [Template context](#template-context) |
| `chunk` | Information about the current chunk (`id`, `file`, `prev`, `next`, …), only when the page is created by `opm chunk` |
| `fragments` | Named pieces of HTML or text configured in `[chunking.fragments]`. A page for a whole document only gets those with `scope = "global"` |
| `parameters` | The parameters from `[transform.parameters]`, which are also available in XPath as `$parameters` |
| `lang` | The language of the document, taken from `<html lang>` in the transformed output. It is empty if unknown; set `context.lang` to provide it |
| `head_html` | Additional content for `<head>` created by the transform. Empty for chunks and `--xpath` selections |
| `odd_css` | The stylesheet generated from the ODD. When chunking, opm also writes it to a file, whose address is in `odd_css_url` |

If your template extends one of opm's templates (see
[Template inheritance](#template-inheritance)), you will mostly use
`context`, `chunk` and `fragments`. opm's templates already take care of the
rest: they put `content_html` into the page and add `head_html` and `odd_css`
to `<head>`.

Only if you write a template from scratch, without extending opm's templates,
do you have to output these yourself. Put the ODD stylesheet last, so its
styles take precedence over other stylesheets in the page:

```jinja
<!DOCTYPE html>
<html lang="{{ lang|default('en') }}">
  <head>
    <meta charset="utf-8">
    {{ head_html | safe }}
    {% if odd_css %}<style type="text/css">{{ odd_css }}</style>{% endif %}
  </head>
  <body>
    {{ content_html | safe }}
  </body>
</html>
```

### Template context

Templates often need information which is not part of the transformed text:
the name of the edition, a logo, or whether to show a download link. You
provide such settings in a `[context]` section in `opm.toml`, and the template
finds them in the variable `context`:

```toml
[context]
site_name = "The Serafin Letters"
show_downloads = true
```

```jinja
<h1>{{ context.site_name }}</h1>
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

All templates receive the same `context`: templates for whole documents, for
chunks, for the collection index, and also Typst templates. If you need a
different value for one output type, add a `[transform.<type>.context]`
section. Its settings replace those in `[context]`, but only for that type:

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
- `templates/serafin.html.j2` – puts the edition's logo into the menu bar at
  the top of the page. The letter list (`index.html.j2`) extends it too, so
  both share the same look.
- `opm/layout.html.j2` – contributes the page layout, including the menu bar
  and the breadcrumb band, which the edition's stylesheet colours.
- `opm/base.html.j2` – the root template.

A template says which one it extends in its first line:

```jinja
{% extends "serafin.html.j2" %}
```

### Layout areas and blocks

For template inheritance to be useful, templates further down the chain need a
way to put content into places defined by the templates they extend. These
places are called **blocks**. `opm/layout.html.j2` defines one block for each
area of the page; they are the same layout areas a [TEI Publisher](https://tei-publisher.org) (jinks)
application has:

| Block | Where it appears |
| --- | --- |
| `header` | Across the top of the page, below the menu bar; it stays visible while the reader scrolls |
| `hero` | Across the page, below the header |
| `before_top`, `before` | A column left of the text, e.g. a table of contents |
| `content_top`, `content` | The text itself; `content` shows the transformed document unless a template fills it |
| `after_top`, `after` | A column right of the text, e.g. a list of people and places |
| `footer` | Across the bottom of the page |

As in a TEI Publisher application, the layout writes two bars itself, and a
template only fills the places it leaves for its own items:

- The **menu bar** at the top. On the left it shows the logo with the author
  and title, then the links listed in `[context.menu]`, then the `menu_left`
  block. On the right it shows the `menu_toggles` block and, on narrow
  screens, the button that opens the contents.
- The **toolbar** above the text. On the left it shows the breadcrumbs (the
  `breadcrumbs` fragment, or the `breadcrumb` block); on the right the
  `toggle` block, links to the previous and next page if you ask for them, and
  the `toolbar` block.

| Block | What it holds |
| --- | --- |
| `logo` | The left end of the menu bar. By default the image named in `context.logo`, `context.author` and the title: a `work_title` set by the page template, `context.site_name`, `context.title` or the collection index title |
| `menu_left` | Items after the menu links, as `<li>` elements |
| `menu_toggles` | Items at the right of the menu bar, as `<li>` elements |
| `breadcrumb` | The left side of the toolbar; by default the `breadcrumbs` fragment |
| `toggle`, `toolbar` | Items at the right of the toolbar, as `<li>` elements |

A bar with nothing in it is left out. The menu links come from `opm.toml`:

```toml
[context.menu]
items = [
    { label = "About", url = "about.html" },
    { label = "Letters", url = "index.html" },
]
```

A bare filename in `context.logo` is found in the shared `assets/` folder.
The packaged collection index uses the same menu bar, so chunk pages and the
index look alike.

Colour the bars (and the page background) by setting CSS variables in a
stylesheet listed under `[transform.web] assets`:

| Variable | Role |
| --- | --- |
| `--opm-surface` | Page and header background |
| `--opm-ink` | Body text |
| `--opm-muted` | Secondary text (author, meta) |
| `--opm-rule` | Hairlines |
| `--opm-accent` | Links and hover |
| `--opm-font-body`, `--opm-font-ui` | Reading and UI type |
| `--opm-menubar-max` | The widest the menu bar's content grows |

A template fills a block by repeating it with new content:

```jinja
{% block menu_toggles %}
  <li><a href="https://example.org/edition.pdf">PDF</a></li>
{% endblock %}
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

`opm init --base` does this for you. It copies `opm/base.html.j2`,
`opm/layout.html.j2` and the layout's stylesheet `opm/opm-layout.css` into
`templates/`, and opm's base stylesheet into `styles/default-styles.css`. Each
copy replaces opm's own from then on. With `--example`, it leaves alone any of
these files the example already has.

### Writing your own template

1. Create `templates/page.html.j2` in your project and start it with this
   line:

    ```jinja
    {% extends "opm/layout.html.j2" %}
    ```

2. Add a block for each area you want to fill. With `site_name` (or `author` /
   `logo`) in `[context]`, the layout already shows a menu bar. Add an item to
   it, and put the work's title above the text:

    ```jinja
    {% block menu_toggles %}
      <li><a href="about.html">About</a></li>
    {% endblock %}

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
| `layout.before.label`, `layout.after.label` | Text of the button that opens a drawer, and the drawer's heading |
| `layout.close_label` | Text of the link that closes a drawer |
| `layout.previous_label`, `layout.next_label` | Text of the toolbar's links to the previous and next page |
| `menu.items` | Links in the menu bar, each with a `label` and a `url` |
| `features.menubar` | `false` leaves out the menu bar |
| `features.toolbar.enabled` | `false` leaves out the toolbar |
| `features.toolbar.navigation` | `true` adds links to the previous and next page to the toolbar |

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

The styles of a page come from two different sources:

- **The ODD stylesheet.** opm creates it from the `<outputRendition>` rules in
  your ODD and from any stylesheets the ODD links to (see
  [ODD files](odd-files.md)). It styles the classes which the transform
  writes into the HTML. opm's templates add it to every page; a template
  written from scratch finds it in `odd_css` (see
  [Template variables](#template-variables)).
<!--
    It opens with a packaged set of base rules for markup the runtime emits
    regardless of ODD — the `.alternate` / `.altcontent` popover behind
    `choice`, `.tei-cb` column breaks, margin notes. They come first, so an
    ODD's own `outputRendition` overrides them, and they travel with the ODD
    stylesheet everywhere it is used.
-->
- **The base styles.** Some markup is created by opm itself, independent of
  the ODD, e.g. popups for alternate readings or column breaks. opm has a set
  of basic styles for it. You can replace them with your own using `--css` on
  the command line or the `css` setting under `[transform]`. The replacement
  becomes part of the ODD stylesheet and applies to all output types.

For the design of your project, use neither of the two. Instead, list your
stylesheets under `assets` in `[transform.web]`, together with any images and
fonts they use. opm copies them next to the output and the template links
them.

Note that `css` under `[transform.epub]` does something different from
`[transform] css`: it does not replace the base styles, but adds one more
stylesheet to the EPUB.

## Web components

TEI Publisher comes with a library of web
components – interactive HTML elements, e.g.
for showing alternate readings in a popup. To use them, turn on web components
mode with `--webcomponents` on the command line, or in `opm.toml`:

```toml
[transform.web]
webcomponents = true
```

The transform will then output `<pb-alternate>` elements for the `alternate`
behaviour, and `context.webcomponents_url` will contain the address of the
web components library. The template loads the library with:

```jinja
{% if context.webcomponents_url %}
<script type="module" src="{{ context.webcomponents_url }}"></script>
{% endif %}
```

By default, the address points to a fixed version of the library. To load it
from your own server, or to use a different version, set `webcomponents_url`
under `[context]` or `[transform.web.context]`.

## Typst and DOCX templates

- **Typst** uses Jinja2 templates as well, with the extension `.typ.j2`. They
  are configured under `[transform.typst]`. `opm init` copies `book.typ.j2`
  for TEI and JATS projects, and `docbook.typ.j2` for DocBook. If no template
  is configured, opm uses its own `default_document.typ.j2`, a plain template.
  `opm init --templates` copies it into your project as
  `templates/document.typ.j2`, so you can use it as a starting point.
- **DOCX** does not use Jinja2. Instead, the template is an ordinary Word file
  (`.docx`), from which the output takes its styles. Configure it under
  `[transform.docx]` or pass it with `--template`. `opm init` copies
  `templates/default.docx` into your project; without a template, opm uses its
  own copy of the same file – see [Output formats](output-formats.md#docx).
