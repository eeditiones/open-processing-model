---
title: Create a PDF from TEI
description: A step-by-step tutorial for creating a print-ready PDF from a TEI XML document with opm, using Typst or CSS for print.
---

# Create a PDF from TEI

This tutorial shows how to create a PDF from a TEI XML document, for example to
print an edition, to share a reading copy, or to submit a text to a publisher.

`opm` offers two ways of doing this. Both use the same rules (the ODD) as the
HTML and EPUB versions, so you do not have to maintain a separate set of
stylesheets for print.

| Way | Good for | Additional software |
| --- | --- | --- |
| Typst | high-quality typesetting, quick to set up | [Typst](https://typst.app/open-source/), free |
| HTML and CSS for print | reusing your web stylesheets, complex page layouts | a CSS print processor such as [PrinceXML](https://www.princexml.com/) |

If you are unsure, start with Typst.

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

## Using Typst

[Typst](https://typst.app) is a modern typesetting system, similar in purpose to
LaTeX but easier to use and much faster. `opm` converts your TEI document into
Typst, and Typst produces the PDF.

### 1. Install Typst

Follow the [installation instructions on the Typst website](https://github.com/typst/typst#installation).
On a Mac with [Homebrew](https://brew.sh), for example, it is:

```bash
brew install typst
```

Check that it works by typing `typst --version` in a terminal.

### 2. Create the PDF

```bash
opm transform data/sample.xml -t typst -o sample.pdf
```

`-t typst` tells `opm` to produce Typst. Because the output file ends in
`.pdf`, `opm` then asks Typst to turn it into a PDF for you.

To see the result straight away, use `--preview` instead of `-o`:

```bash
opm transform data/sample.xml -t typst --preview
```

### 3. Change the page layout

The paper size, fonts, margins and title page are set in a template,
`templates/book.typ.j2`. Open it in a text editor to make changes. The
template uses a ready-made book layout for Typst called
[ilm](https://typst.app/universe/package/ilm). For example, to print on A5
paper, look for the lines starting with `#show: ilm.with(` and add a
`paper-size` setting:

```typst
#show: ilm.with(
  title: [...],
  ...
  listing-index: (enabled: true),
  paper-size: "a5",
)
```

Save the template and create the PDF again. The
[Typst documentation](https://typst.app/docs/) explains what else you can set.

If you want to see what `opm` passes on to Typst, write the Typst file instead
of the PDF:

```bash
opm transform data/sample.xml -t typst -o sample.typ
```

### 4. Change how individual elements look

Changes made in the ODD apply to the PDF as well. If you followed
[Convert TEI to HTML](tei-to-html.md) and made person names italic and red,
they are italic and red in the PDF too.

Not every CSS property has a counterpart in Typst. `opm` carries over bold,
italic, strike-through, text colour and font size. For anything else, see
[CSS class mapping](../guide/output-formats.md#css-class-mapping), which explains
how to add your own Typst styling for an element.

## Using HTML and CSS for print

The second way produces an HTML file meant for printing, and leaves the step to
PDF to a separate program. Page size, margins, running headers and footnotes are
all set in CSS.

There are different processors available for generating a PDF based on CSS for print. The example below uses [Prince XML](https://www.princexml.com/).

```bash
opm transform data/sample.xml -t print -o print.html
prince print.html -o print.pdf
```

To check the print version in your browser first, use:

```bash
opm transform data/sample.xml -t print --preview
```

This approach is useful if you already have CSS for your web edition and want
the PDF to look similar. The DocBook example shows a complete setup, including
running headers and a table of contents. Create a copy with
`opm init --example docbook`.

## Next steps

* Learn more about each format: see [Output formats](../guide/output-formats.md).
* Create an [EPUB or Word file](tei-to-epub-word.md) from the same document.
