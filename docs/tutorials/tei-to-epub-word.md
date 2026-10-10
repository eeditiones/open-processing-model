---
title: Create an EPUB or Word file from TEI
description: A step-by-step tutorial for converting a TEI XML document into an EPUB e-book, a Word document or Markdown with opm.
---

# Create an EPUB or Word file from TEI

This tutorial shows how to turn a TEI XML document into an e-book (EPUB) for
e-readers, or into a Word document you can share with colleagues who do not
work with XML. Both are made from the same rules (the ODD) as your web and PDF
versions, so a change you make once shows up everywhere.

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

## Creating an EPUB

### 1. Create the e-book

```bash
opm transform data/sample.xml -t epub -o sample.epub
```

`-t epub` selects the EPUB format, and `-o` names the file to write. Open
`sample.epub` in an e-book reader, for example Apple Books, Calibre or your
e-reader's desktop application. To open it right away in the default
application on your computer, use `--preview` instead of `-o`.

### 2. Decide on the chapters

An EPUB is divided into chapters. `opm` divides it the same way it divides a
[website](tei-website.md) into pages, following the `[chunking]` section of
`opm.toml`. In a new project, that means a new chapter for each `div`, up to
two levels deep.

Sometimes an e-book should be divided differently from a website. In that case,
add a section `[transform.epub]` to `opm.toml` with its own setting:

```toml
[transform.epub]
depth = 1
```

With `depth = 1`, only top-level divisions become chapters. A higher number
also turns nested divisions into chapters of their own. If your website is
split at page breaks, the e-book is still divided into chapters by `div`, since
e-readers lay out the pages themselves.

### 3. Change the look

E-readers have their own ideas about fonts and page size, so EPUB styling is
best kept simple. `opm` uses a plain stylesheet for e-books, combined with the
styling from your ODD. To add your own rules, put them into a CSS file, for
example `templates/epub.css`, and name it in `opm.toml`:

```toml
[transform.epub]
css = "templates/epub.css"
```

## Creating a Word document

```bash
opm transform data/sample.xml -t docx -o sample.docx
```

Open `sample.docx` in Word, LibreOffice or any other word processor.

Headings, paragraphs, lists, tables, notes and emphasis come out as regular
Word formatting, so the document can be edited further like any other.

### Using your own Word styles

If your institution or publisher has a Word template, `opm` can use its styles.
Save the template as a normal `.docx` file in the `templates` folder and name it
in `opm.toml`:

```toml
[transform.docx]
template = "templates/my-styles.docx"
```

`opm` then uses the paragraph and character styles from that file, such as
*Heading 1* or *Caption*, so the result looks like the rest of your documents.

## Creating Markdown

Markdown is a plain-text format, useful for example for notes, wikis or
further processing with other tools:

```bash
opm transform data/sample.xml -t markdown -o sample.md
```

## Next steps

* Learn more about each format: see [Output formats](../guide/output-formats.md).
* Create a [PDF](tei-to-pdf.md) from the same document.
* For a complete e-book example, create a copy of the Shakespeare edition with
  `opm init --example shakespeare`, or of the DocBook handbook with
  `opm init --example docbook`.
