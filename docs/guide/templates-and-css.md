# Templates & CSS

The transform turns your XML into HTML, but that alone is not yet a
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

A template which extends another one needs a way to say where its content
should go. Jinja2 provides **blocks** for this: named places, which the
extended template defines and which a template further down the chain can
fill. To fill a block, a template simply repeats it with new content. For
example, to put a list of letters into the column left of the text:

```jinja
{% extends "opm/layout.html.j2" %}

{% block before %}
  <h2>Letters</h2>
  <ul>
    <li><a href="letter-1.html">Letter 1</a></li>
    <li><a href="letter-2.html">Letter 2</a></li>
  </ul>
{% endblock %}
```

`opm/layout.html.j2` divides the page into areas, the same ones a
[TEI Publisher](https://tei-publisher.org) (jinks) application has, and
defines one block for each of them:

```text
+-------------------------------------------------+
|                     header                      |
+-------------------------------------------------+
|                      hero                       |
+------------+----------------------+-------------+
| before_top |     content_top      |  after_top  |
+------------+----------------------+-------------+
|   before   |       content        |    after    |
+------------+----------------------+-------------+
|                     footer                      |
+-------------------------------------------------+
```

| Block | Where it appears |
| --- | --- |
| `header` | Across the top of the page, below the menu bar. It stays in place while the reader scrolls |
| `hero` | Across the page, below the header, e.g. for a large title image |
| `before_top`, `before` | The column left of the text, e.g. for a table of contents |
| `content_top`, `content` | The text itself. `content` shows the transformed document, unless a template fills it with something else |
| `after_top`, `after` | The column right of the text, e.g. for a list of people and places |
| `footer` | Across the bottom of the page |

You only fill the areas you need. An area left empty takes no room on the
page: without a `before` block, for example, there is no left column, and the
text moves to the left edge.

### The menu bar and the toolbar

Two bars are part of the layout itself, again as in a TEI Publisher
application: the **menu bar** at the very top of the page, and the
**toolbar** right above the text. You do not have to write them yourself,
but you decide what goes into them.

The menu bar shows the logo of your edition on the left, followed by the
links you list in `opm.toml`:

```toml
[context]
site_name = "The Serafin Letters"
logo = "logo.svg"

[context.menu]
items = [
    { label = "About", url = "about.html" },
    { label = "Letters", url = "index.html" },
]
```

The logo is made from three settings in `[context]`: an image (`logo`), the
name of an author (`author`) and a title (`site_name`). Each of them is
optional. If `logo` is just a filename, as above, opm looks for the image in
the `assets/` folder of the output. Instead of `site_name`, a page template may
also set its own title in the variable `work_title`, e.g. the title of the
letter shown.

The toolbar shows the breadcrumbs of the current page on the left, i.e. the
path from the start of the document to the current section. They come from
the `breadcrumbs` fragment configured for chunking (see
[Chunking](chunking.md)). On the right, the toolbar can show links to the
previous and next page. Turn them on in `opm.toml`:

```toml
[context.features.toolbar]
navigation = true
```

To add your own items to either bar, fill one of the following blocks. Each
item must be a list entry (`<li>`):

| Block | Where it appears |
| --- | --- |
| `menu_left` | In the menu bar, after the menu links |
| `menu_toggles` | At the right end of the menu bar |
| `toggle`, `toolbar` | At the right end of the toolbar, before and after the links to the previous and next page |

For example, to add a link to download a PDF:

```jinja
{% block menu_toggles %}
  <li><a href="https://example.org/edition.pdf">PDF</a></li>
{% endblock %}
```

Two more blocks let you replace what the layout shows by default: `logo` for
the logo, and `breadcrumb` for the breadcrumbs. The Serafin example uses the
first to show its own drawing of the edition's name instead of a plain
image:

```jinja
{% block logo %}
  <a href="{{ index_url or 'index.html' }}" aria-label="Home">{% include "logo-textmark.svg" %}</a>
{% endblock %}
```

### Blocks for the head of the page

Besides the layout areas, a few blocks control the `<head>` of the HTML page
and the `<body>` element. They come from `opm/base.html.j2`:

| Block | What it holds |
| --- | --- |
| `title` | The `<title>` element, shown in the browser tab |
| `meta` | Additional tags in `<head>`, e.g. `<meta>` or `<link>` |
| `styles` | Additional stylesheets |
| `scripts` | Additional scripts |
| `odd_overrides` | Styles which must take precedence over those of the ODD. They are placed after the ODD stylesheet |
| `body_class` | Classes for the `<body>` element |
| `body_end` | Scripts at the end of the page, for scripts which need the content of the page to be in place |

### Adding to a block

Filling a block replaces whatever the extended template put there. Often you
want to keep that content and only add something. To do so, start your block
with `{{ super() }}`, which inserts the content of the extended template:

```jinja
{% block meta %}{{ super() }}
  <link rel="preconnect" href="https://fonts.googleapis.com">
{% endblock %}
```

### Changing opm's own templates

Sometimes filling blocks is not enough, e.g. if you want a different page
structure altogether. You then have two options:

- Extend `opm/base.html.j2` instead of `opm/layout.html.j2`. You keep opm's
  handling of `<head>` (stylesheets, scripts, title), but write the page
  structure yourself in the `body` block.
- Replace one of opm's templates with your own version. opm always looks in
  your project's `templates/` folder first, so a file
  `templates/opm/layout.html.j2` is used instead of opm's own layout.

`opm init --base` helps with the second option. It copies opm's templates
into your project, so you can start from them:

| Copied file | Contents |
| --- | --- |
| `templates/opm/base.html.j2` | The root template |
| `templates/opm/layout.html.j2` | The page layout |
| `templates/opm/opm-layout.css` | The stylesheet of the page layout |
| `styles/default-styles.css` | opm's base styles (see [Adding custom CSS](#adding-custom-css)) |

From then on, opm uses these copies instead of its own. When used together
with `--example`, `opm init --base` leaves alone any of these files which the
example already provides.

### Writing your own template

The following steps create a simple template of your own, building on opm's
page layout.

1. Create a file `templates/page.html.j2` in your project. Its first line
   says that it extends the layout:

    ```jinja
    {% extends "opm/layout.html.j2" %}
    ```

    This alone already gives you a complete page. If `[context]` in
    `opm.toml` contains a `site_name` or `logo`, the page also has a menu bar,
    which shows the logo and the name.

2. Add a block for each area you want to fill. For example, add a link to
   the menu bar, and show the title of the work above the text:

    ```jinja
    {% block menu_toggles %}
      <li><a href="about.html">About</a></li>
    {% endblock %}

    {% block content_top %}
      {% if fragments is defined and fragments.title %}{{ fragments.title | safe }}{% endif %}
    {% endblock %}
    ```

    The title comes from a fragment named `title`, which you configure for
    chunking (see [Chunking](chunking.md)). The `if` makes sure the template
    still works for pages without it.

3. Tell opm to use the template, and name a stylesheet for it, in
   `opm.toml`:

    ```toml
    [transform.web]
    template = "templates/page.html.j2"
    assets = ["templates/page.css"]
    ```

    Chunk pages use the same template, unless `[chunking]` names a different
    one.

4. Create `templates/page.css` with the design of your project. opm copies it
   next to the output, and the template links it automatically. Images,
   fonts or scripts the page needs are listed under `assets` too (see
   [Assets](assets.md)).

## Frontmatter

Some settings belong to a template rather than to a project: the stylesheets
for the fonts a template uses, for example, or the label of a side column.
Such settings can go at the top of the template itself, in a block enclosed
between two lines of three dashes. This block is called the
**frontmatter**, as in TEI Publisher (jinks):

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

This frontmatter gives the page a title, loads a web font and adds the class
`letter` to `<body>`. It also makes the left column `16rem` wide, labels it
"Letters", and on a phone shows it below the text instead of as a sliding
panel.

You can write the frontmatter in TOML (`---toml`), like `opm.toml`, or in
JSON (`---json`, or just `---`), like the frontmatter of jinks templates.

The settings in the frontmatter end up in the variable `context`, together
with those from `[context]` in `opm.toml` (see
[How the settings are combined](#how-the-settings-are-combined) below). So
your own templates can read any setting of the frontmatter as
`context.<name>`. opm's templates understand the following settings:

| Setting | Effect |
| --- | --- |
| `title` | The title of the page, unless a template fills the `title` block |
| `description` | A short description of the page, for search engines (`<meta name="description">`) |
| `lang` | The language of the page |
| `styles` | A list of stylesheets to load, e.g. web fonts |
| `scripts` | A list of scripts to load (as JavaScript modules) |
| `body.classes` | A list of classes for `<body>` |
| `layout.class` | Classes for the element which holds the layout areas |
| `layout.before.width`, `layout.after.width` | Width of the left and right column |
| `layout.before.mobile`, `layout.after.mobile` | What happens to the column on a phone: `"drawer"` (it slides in when the reader taps a button) or `"stack"` (it moves below the text) |
| `layout.before.label`, `layout.after.label` | Text of the button which opens the sliding panel, also used as the panel's heading |
| `layout.close_label` | Text of the link which closes the sliding panel |
| `layout.previous_label`, `layout.next_label` | Text of the toolbar's links to the previous and next page |
| `menu.items` | Links in the menu bar, each with a `label` and a `url` |
| `features.menubar` | `false` removes the menu bar |
| `features.toolbar.enabled` | `false` removes the toolbar |
| `features.toolbar.navigation` | `true` adds links to the previous and next page to the toolbar |

## Context merging

A template receives its settings from several places. opm reads them in the
following order, and a later source takes precedence over an earlier one:

1. opm's defaults (`opm/defaults.toml`)
2. `[context]` in `opm.toml`
3. `[transform.<type>.context]` in `opm.toml`, e.g. `[transform.web.context]`
4. the frontmatter of each template in the inheritance chain, starting with
   the root template and ending with the template being rendered

How a setting is combined depends on its kind, following the same rules as [TEI Publisher](https://tei-publisher.org/exist/apps/tei-publisher/doc/documentation.xml?id=templates-frontmatter-merging#templates-frontmatter-merging):

- A single value, such as a text, a number or `true`/`false`, replaces the
  value from an earlier source.
- A table, such as `[layout.before]`, is combined setting by setting: the
  settings it contains replace those of an earlier source, all others are
  kept.
- A list, such as `styles`, is joined with the list from an earlier source.
  Entries which appear in both are kept only once. This is why a template's
  `styles` are added to those of the template it extends, instead of
  replacing them.

To replace a table entirely instead of combining it, add `"$replace" = true`
to it. To replace only some of its entries and combine the rest, list them,
e.g. `"$replace" = ["before"]`.

Since the frontmatter comes last, it always wins!

## Colours, fonts and measurements

The look of opm's page layout, from the colours of the menu bar to the width
of the side columns, is controlled by CSS variables. You do not need to touch
the layout's own stylesheet to change them: set the variables in your own
stylesheet, the one listed under `assets` in `[transform.web]` (e.g.
`templates/page.css` from the steps above).

For example, to give the page a warm background, a different link colour and
font, narrow the text to a comfortable reading width and make the right
column a bit smaller:

```css
:root {
  --opm-background-color: #fbf7ee;
  --opm-color-accent: #8a3b12;
  --opm-font-body: "Albert Sans", sans-serif;
  --opm-layout-content-max: 42rem;
  --opm-layout-after-width: 16rem;
}
```

The following variables set colours and fonts. By default, opm uses the
standard colours and fonts of the reader's system.

| Variable | What it controls |
| --- | --- |
| `--opm-background-color` | Background of the page and the header |
| `--opm-color` | Colour of the text |
| `--opm-color-muted` | Colour of less important text |
| `--opm-color-rule` | Colour of thin dividing lines |
| `--opm-color-accent` | Colour of links, and of buttons when the mouse is over them |
| `--opm-background-color-drawer` | Background of a side column which slides in on a phone (see below) |
| `--opm-font-body` | Font of the text |
| `--opm-font-ui` | Font of menus and buttons |

These variables set the measurements of the layout:

| Variable | What it controls |
| --- | --- |
| `--opm-layout-content-max` | Maximum width of the text. By default the text takes all the available room |
| `--opm-layout-before-width`, `--opm-layout-after-width` | Width of the left and right column (default: `18rem`) |
| `--opm-layout-gap` | Space between a side column and the text |
| `--opm-layout-gutter` | Minimum space at the left and right edge of the page |
| `--opm-layout-sticky-top` | The side columns stay in place while the reader scrolls. This sets how far below the top of the window they stop, e.g. the height of your header |
| `--opm-menubar-max` | Maximum width of the menu bar's content |

## Adding custom CSS

The styles of a page come from three different places, each with its own
purpose:

- **The base styles** define basic styling to be applied to any content rendered via ODD, e.g. popups for alternate readings or column breaks. They are
  placed at the start of the ODD stylesheet, so your ODD's own renditions can
  change them.
- **The ODD stylesheet** styles the transformed text. opm creates it from the
  `<outputRendition>` elements in your ODD, and adds any stylesheets the ODD
  links to (see [ODD files](odd-files.md)). opm's templates include it in
  every page. A template written from scratch finds it in the variable
  `odd_css` (see [Template variables](#template-variables)).
- **Your own stylesheets** contain the design of your project: page colours,
  fonts, the look of the menu bar and so on. List them under `assets` in
  `[transform.web]`, together with any images and fonts they use. opm copies
  them next to the output, and the template links them (see
  [Assets](assets.md)).

As a rule of thumb, keep the ODD to typographic features of the text (italic,
bold, indentation, …) and put everything else into your own stylesheets.

!!! note
    The `css` setting under `[transform.epub]` does something different from
    the one under `[transform]`: it does not replace the base styles, but adds
    one more stylesheet to the EPUB.

## Web components

TEI Publisher comes with a library of web components: interactive HTML
elements, e.g. for showing alternate readings in a popup. To use them, turn on
web components with `--webcomponents` on the command line, or in `opm.toml`:

```toml
[transform.web]
webcomponents = true
```

The transform then outputs `<pb-alternate>` elements for the `alternate`
behaviour. opm's templates also load the library for you. In a template
written from scratch, you find the address of the library in
`context.webcomponents_url`, and load it like this:

```jinja
{% if context.webcomponents_url %}
<script type="module" src="{{ context.webcomponents_url }}"></script>
{% endif %}
```

By default, the address points to a fixed version of the library on the web.
To load it from your own server, or to use a different version, set
`webcomponents_url` under `[context]` or `[transform.web.context]`.

## Typst and DOCX templates

Typst (for PDF) uses Jinja2 templates as well, with the extension `.typ.j2`.
You configure them under `[transform.typst]`. `opm init` copies
`book.typ.j2` into TEI and JATS projects, and `docbook.typ.j2` into DocBook
projects. Without a template, opm uses its own plain
`default_document.typ.j2`. `opm init --templates` copies this one into your
project as `templates/document.typ.j2`, as a starting point for your own.

DOCX does not use Jinja2. Here the template is an ordinary Word file
(`.docx`), from which the output takes its styles: change a style in Word,
and the output follows. Configure the template under `[transform.docx]`, or
pass it with `--template`. `opm init` copies `templates/default.docx` into
your project. Without a template, opm uses its own copy of the same file. See
[Output formats](output-formats.md#docx).
