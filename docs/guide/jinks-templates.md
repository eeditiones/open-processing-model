# jinks templates

Templates define the page around your transformed text: the HTML head, the
menu, the sidebars, the footer (see [Templates & CSS](templates-and-css.md)).
opm's templates are written in the template language of
[TEI Publisher](https://tei-publisher.org) 10, called _jinks_. If you already
have templates for a TEI Publisher application, or you know their syntax, you
can use the same style of template in opm. Expressions inside the templates
are written in XPath, the language you already use in your ODD.

Like TEI Publisher, opm can process XML as well as plain text with jinks:
next to HTML pages, a template may produce Typst, CSS or any other text
format. Most of this page concentrates on HTML templates, because those are
the files you will most likely want to change.

opm decides from the file name which language a template is written in:

| File name | Template language |
| --- | --- |
| ends in `.tpl`, e.g. `page.html.tpl` or `book.typ.tpl` | jinks |
| anything else, e.g. `page.html.j2` | Jinja2 |

Jinja2 is the template language earlier versions of opm used, and opm still
reads it. Both kinds of template receive the same information from opm, so
you can move a project from one language to the other one page at a time.
All packaged templates, the templates `opm init` writes and all examples but
`shakespeare` use jinks; `opm init --jinja` writes Jinja2 templates
instead.

## Templating syntax

jinks uses a simple syntax with three kinds of markers:

- `[% … %]`: directives for control structures, includes, blocks and
  templates
- `[[ … ]]`: inserts the result of an XPath expression
- `---json` or `---toml`: starts the frontmatter, a block of configuration
  that ends with `---`

The directives cover common tasks like `[% if %]`, `[% for %]` or
`[% include %]`. The following sections introduce them one by one. For a
complete reference, see the
[jinks-templates README](https://github.com/eeditiones/jinks-templates).

## A first template

Create `templates/page.html.tpl` in your project:

```html
<html lang="[[ $lang ]]">
    <head>
        <title>[[ $context?title ]]</title>
        [[ $head_html ]]
        <style>[[ $odd_css ]]</style>
    </head>
    <body>
        <main>[[ $content_html ]]</main>
    </body>
</html>
```

Then tell opm to use it in `opm.toml`:

```toml
[transform.web]
template = "templates/page.html.tpl"
```

and transform a document:

```bash
uv run opm transform data/letter.xml --preview
```

Each `[[ … ]]` is replaced by the value of the expression it contains.
`$content_html` is your document, transformed by the ODD. `$head_html` adds
whatever the transformation wants to place in the `<head>`, and `$odd_css`
holds the styles generated from the ODD.

## The context map

Every template receives a context map, which it uses to look up the
information it needs. The context map is filled from three sources:

- the values opm passes to the template: the transformed text, the
  fragments, the current chunk and so on
- the settings in the `[context]` table of `opm.toml`
- the frontmatter of the template and of any template it inherits from (see
  [Frontmatter](#frontmatter))

Where `[context]` uses the same name as a value from opm, such as `lang`,
your setting wins.

### Accessing the context

Within an expression, you can access the context map in two ways:

1. Through the `$context` variable. This is an XPath map, so you use the
   lookup operator `?` to reach its entries, and the nested maps and arrays
   within them:

    ```html
    <p>Published [[ $context?year ]] by [[ string-join($context?editors?*, ', ') ]]</p>
    ```

2. Through a variable of the same name. Every top-level entry of the context
   map is also available as a variable of its own, so `$context?title` can be
   shortened to `$title`.

Note that the second way results in an error if there is no entry of that
name in the context map, while `$context?title` simply gives an empty result.
So unless you are certain a setting will always be there, use the first way.

XPath cannot use a map directly as a condition. To check if a map is there,
for example the current chunk, use `exists($context?chunk)`.

### Inserting HTML

In HTML templates, opm escapes characters with a special meaning, such as
`<` and `&`. This way, text coming from a setting can never break the page.
The HTML opm produces itself, that is `$content_html`, `$head_html`,
`$odd_css` and the fragments, is inserted as it is.

The fragments are also elements you can query. `normalize-space($context?fragments?title)`
gives the plain text of the title, for example to use it as the page title,
and `$context?fragments?toc//a` gives the links in the table of contents.
Inserting a fragment unchanged with
`[[ $context?fragments?toc ]]` gives exactly the HTML opm produced.

Once you change HTML with an XPath function, though, the result is plain text
again and will be escaped. To insert it as HTML, turn it back into elements
with `parse-xml-fragment()`. The `monograph` example uses this to mark the
current page in the table of contents: `serialize()` turns the fragment into
text, `replace()` adds the attribute, and `parse-xml-fragment()` turns the
result into elements again:

```html
[% let $link = 'href="#' || $context?chunk?xml_id || '"' %]
[[ parse-xml-fragment(replace(serialize($context?fragments?toc), $link, $link || ' aria-current="page"', 'q')) ]]
[% endlet %]
```

## Conditions and loops

`[% if %]` shows its content only if a condition is true. It may be followed
by any number of `[% elif %]` and one `[% else %]`. `[% for %]` repeats its
content for each item in a sequence:

```html
[% if $context?menu %]
<nav>
    <ul>
    [% for $item in $context?menu?items?* %]
        <li><a href="[[ $item?url ]]">[[ $item?label ]]</a></li>
    [% endfor %]
    </ul>
</nav>
[% elif $context?chunk?next %]
<a href="[[ $context?chunk?next ]].html">Next</a>
[% else %]
<p>No menu.</p>
[% endif %]
```

A list in `opm.toml` becomes an XPath array, so you need to add `?*` to loop
through its members, as in `$context?menu?items?*` above.

`[% let $name = expr %] … [% endlet %]` stores the value of an expression
under a name, which you can then use until `[% endlet %]`.

Attributes have a shortcut: if you write the value as `![[ expr ]]`, the
attribute is only written if the expression has a value. In the following
example, the link only gets a `class` attribute if `highlight` is set:

```html
<a class="![[ $context?highlight ]]" href="index.html">Home</a>
```

## Frontmatter

A template can start with configuration of its own, written in JSON or TOML
between two lines of `---`. This frontmatter is added to the context map:

```html
---json
{
    "title": "Letters of Alfred Escher",
    "theme": { "layout": { "after": { "width": "22rem" } } }
}
---
<html>…</html>
```

To keep an HTML template valid XML, you may also put the frontmatter after
the first tag of the file, as TEI Publisher does.

### How settings are merged

When opm processes a template, it merges the settings from `opm.toml` with
the frontmatter of every template in the inheritance chain (see
[Template inheritance](#template-inheritance)). The settings of the page come
last, so they win over those of `opm.toml` and of the layouts it extends. The
merging works as follows:

- Single values (text, numbers, true or false): a later value replaces an
  earlier one.
- Maps: the entries of both maps are merged one by one, following the same
  rules.
- Lists: the values are appended, leaving out duplicates. For a list of maps,
  two maps count as the same if they have the same `id`.

This means you can change a single setting deep inside a nested map without
repeating the others. For example, opm's default document template turns on
the navigation buttons of the toolbar with:

```json
{ "features": { "toolbar": { "navigation": true } } }
```

All other settings under `features.toolbar` stay as they are. Likewise, a
page can add a stylesheet to `styles` without losing those listed elsewhere.

Sometimes merging is not what you want. Adding `"$replace": true` to a map
replaces the earlier map completely. `"$replace": ["styles"]` replaces only
the entries listed and merges the rest.

## Template inheritance

Most pages of a site share their layout. Instead of repeating it in every
template, a template can extend another one, which in turn may extend a
third. Together they form an inheritance chain. You name the template to
extend under `templating.extends` in the frontmatter.

opm ships its own page layout as jinks templates, and the `monograph` example
builds on it. Its inheritance chain looks like this:

- `templates/monograph.html.tpl`: is loaded first. It sets some
  configuration, fills the sidebar with the table of contents, adds buttons
  to change the text size and links to turn the page, and places the
  transformed text in the content area.
- `opm/layout.html.tpl`: the page layout, with a menu bar, a toolbar with
  breadcrumbs, the main content area and sidebars before and after it.
- `opm/base.html.tpl`: the bare page skeleton, which writes the HTML head
  with all scripts and styles, and the body.

opm walks through the entire chain, in the order shown above. The frontmatter
of `monograph.html.tpl`, written in TOML, starts like this:

```toml
---toml
[theme.body]
classes = ["opm-reader"]

[templating]
extends = "opm/layout.html.tpl"
---
```

It adds a class to the `body` element and names the layout it builds upon. The regions of opm's layout and the
settings it accepts are described under
[Template inheritance](templates-and-css.md#template-inheritance). As in TEI
Publisher, the layout writes every region, and its stylesheet
(`opm-layout.css`) hides the empty ones. (The Jinja2 version of the layout
leaves them out instead.) The layout's blocks and settings have the same names
as in TEI Publisher's base layout, e.g. the `before-top` and `menu.toggles`
blocks or the `theme.layout.before.width` setting. The Jinja2 version uses
underscores in block names instead (`before_top`, `menu_toggles`), since
Jinja2 does not allow `-` or `.` in them.

Besides the layout, opm provides `default_document.html.tpl`, which shows the
transformed document in the layout. It is a good starting point for your own
templates.

## Blocks and templates

To make inheritance really useful, templates further down the chain need a
way to put content into certain places of the templates they extend. jinks
uses two directives for this, which work together:

`[% block name %]` marks a place in a layout where other templates may add
content. Usually a block is empty. If it does have content, that content is
used as a default, which only appears as long as no template adds to the
block.

`[% template name %] … [% endtemplate %]` provides content for the block of
the same name. If several templates in the chain add to the same block,
their content appears one after the other, the layout's first. To put a
template at a fixed position, add a number: `[% template menu 1 %]` comes
before all templates without a number, which keep their order.

`[% template! name %]` overrides the block: its content replaces everything
other templates have added, including the default content.

Here is a simple layout with three blocks:

```html
<!-- templates/layout.html.tpl -->
<html>
    <body>
        <header>
            <ul>
                <li><a href="index.html">Home</a></li>
                [% block menu %][% endblock %]
            </ul>
        </header>
        <main>[% block content %][% endblock %]</main>
        <footer>[% block footer %]© e-editiones[% endblock %]</footer>
    </body>
</html>
```

The `content` block is treated specially: it receives everything in the
extending template that is not inside a `[% template %]`. So to add an entry
to the menu and show the transformed text in the content area, a page can
use:

```html
---json
{ "templating": { "extends": "layout.html.tpl" } }
---
[% template menu %]
<li><a href="about.html">About</a></li>
[% endtemplate %]

<article>[[ $content_html ]]</article>
```

The footer is not mentioned, so it shows its default text. A page that
contains nothing but templates, apart from blank lines, keeps the default
content of the `content` block as well. If it extends a layout which in turn
extends another, the content of the page it was given is passed on.

If you know Jinja2, note that there is no equivalent of `super()`: as soon as
a template adds to a block, the block's default content disappears.

## Template-only files

Sometimes you want to add a component to every page, for example a viewer
for facsimiles, without changing the page templates themselves. For this,
you can write a file that contains nothing but `[% template %]` definitions,
wrapped in a `<template>` element:

```html
<!-- templates/iiif-viewer.html.tpl -->
<template>
    [% template after %]
    <pb-facsimile></pb-facsimile>
    [% endtemplate %]
</template>
```

and list it under `templating.use`:

```toml
# opm.toml
[context.templating]
use = ["iiif-viewer.html.tpl"]
```

Its templates now go into the matching blocks of every page, here the
sidebar after the content, without the pages having to include anything.

## Including other files

`[% include "footer.html.tpl" %]` inserts another template at this place. The
included file sees the same context map and may contain blocks of its own.

opm looks for the files named in `extends`, `use` and `include` first in the
folder of the page template, then among its own templates.

## Comments and raw text

Text between `[#` and `#]` is a comment and does not appear in the output.
Text between `[% raw %]` and `[% endraw %]` is copied as it is, without
looking for template expressions.

## Typst and other text templates

A template whose name, without `.tpl`, does not end in `.html`, `.xhtml`,
`.xml` or `.svg`, such as `book.typ.tpl` or `site.css.tpl`, produces plain
text. Nothing is escaped, and an XML element is inserted as its text content.
If you want to decide this yourself, set `"mode": "html"` or `"mode": "text"`
under `templating` in the frontmatter.

Typst uses square brackets as well, so a few things need care:

- A Typst `[` directly before a template tag stays a Typst bracket:
  `title: [[[ $title ]]]` gives `title: [The title]`, and
  `align(center)[[% if … %]…[% endif %]]` works as well. TEI Publisher reads
  `[[[` differently, so templates relying on this work in opm only.
- `[#` starts a template comment, which ends at the next `#]`. Typst content
  like `[#emph[x]]` is safe as long as no `#]` follows. If text goes missing
  from your output, check for this.
- Line breaks around template tags remain in the output, and in Typst markup
  a line break counts as a space. Keep tags within a line of markup, or use
  code mode.

For complete examples, see `templates/book.typ.tpl` in the `monograph`
example and `templates/article.typ.tpl` in the `jats` example.

## XPath functions and namespaces

Expressions can call the [XPath extension functions](xpath-extensions.md) of
your project (`tp:` functions) and use the namespace prefixes declared in
`[transform.namespaces]`. A template can declare more prefixes in its
frontmatter:

```json
{ "templating": { "namespaces": { "tei": "http://www.tei-c.org/ns/1.0" } } }
```

## Differences from TEI Publisher

TEI Publisher evaluates template expressions as XQuery, opm as XPath. As a
consequence, `[% import %]` and the `templating.modules` setting, which load
XQuery modules in TEI Publisher, do not work in opm. Write the function as an
XPath extension instead. Functions specific to eXist, such as
`system:get-version()`, are not available either.

When a page and the layout it extends both set the same value in their
frontmatter, the page wins in opm.

A `[` directly before `[[` or `[%` is plain text in opm (see
[Typst and other text templates](#typst-and-other-text-templates)), while
TEI Publisher reads it as part of the tag.
