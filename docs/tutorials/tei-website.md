---
title: Publish a TEI edition as a website
description: A step-by-step tutorial for turning one or more TEI XML documents into a static website with opm, without a database or server software.
---

# Publish a TEI edition as a website

A long TEI document, or a whole collection of letters, is too much for a single
web page. This tutorial shows how to split your TEI files into smaller pages,
with navigation between them, and turn the result into a website.

The website `opm` creates is *static*: it is just a folder of HTML files. You do
not need a database or special server software to publish it. Any web space
will do, including free services such as GitHub Pages or GitLab Pages.

## Before you start

You need `opm` installed on your computer (see the
[installation instructions](../getting-started/installation.md)) and a project
folder. If you do not have a project yet, create one:

```bash
opm init my-edition --vocabulary tei
cd my-edition
```

If you have followed [Convert TEI to HTML](tei-to-html.md), you can use the
project from that tutorial.

## 1. Split a document into pages

Splitting a document into pages is called *chunking*. Try it on the sample
document:

```bash
opm chunk data/sample.xml --force --preview
```

`opm` creates a folder called `chunks`, writes one HTML page for each division
of the text into it, and opens the first page in your browser. Use the arrows
to move between pages.

`--force` allows `opm` to overwrite the `chunks` folder when you run the command
again. Without `--preview`, the pages are written but not opened.

## 2. Decide where to split

In a new project, `opm` starts a new page for each `div` in the body of the
text, up to two levels deep. You can change this in `opm.toml`, in the section
headed `[chunking]`:

```toml
[chunking]
selector = "opm.navigation.tei_div_chunks"
depth = 2
```

`depth` controls how deep `opm` looks: with `depth = 1`, only top-level
divisions get their own page; with `depth = 3`, divisions three levels down
do as well.

Some editions are better read page by page, following the original source. To
start a new web page at every page break (`pb`) in the text, use:

```toml
[chunking]
selector = "opm.navigation.tei_pb_chunks"
view = "page"
```

Save `opm.toml` and run the `opm chunk` command again to see the difference.

## 3. Add your whole collection

Put all your TEI files into the `data` folder, then pass the folder rather than
a single file:

```bash
opm chunk data --force --preview
```

Every document gets its own set of pages, and `opm` adds a start page listing
all documents in the collection.

## 4. Look at the result

Open the `chunks` folder. You will find:

| Path | What it is |
| --- | --- |
| `index.html` | the start page |
| `letter.xml/001.html`, `002.html`, … | the pages of each document |
| `letter.xml/manifest.json` | information about the pages, used for navigation |
| `css/` | the stylesheets |

To view the site again later without rebuilding it, run:

```bash
opm serve
```

!!! note "Why not just open the files?"

    Some features, such as navigation, need the pages to be loaded from a web
    server rather than directly from disk. `opm serve` runs a small one on your
    computer for testing.

## 5. Publish it

To publish the edition, copy the contents of the `chunks` folder to your web
space. That is all.

If you rebuild the site after editing your TEI files, copy the folder again.
Many projects automate this step, so the website updates itself whenever the
TEI files change. GitHub and GitLab both offer this for free.

## Next steps

* Change the page layout, or add a site title and a logo: see
  [Templates & CSS](../guide/templates-and-css.md) and
  [Configuration](../guide/configuration.md).
* Add a table of contents, breadcrumbs, or other navigation: see
  [Chunking](../guide/chunking.md).
* Build a more elaborate site with a static site generator such as
  [Eleventy](https://www.11ty.dev/) or [Hugo](https://gohugo.io/): run
  `opm chunk data --format json` to produce data files they can read. See
  [Chunking](../guide/chunking.md).
* Add full-text search: see [Search indexing](../guide/search-indexing.md).
* For a complete worked example, create a copy of the correspondence edition
  with `opm init --example serafin` or the Shakespeare edition with
  `opm init --example shakespeare`.
