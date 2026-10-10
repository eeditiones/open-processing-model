---
title: Convert TEI to HTML
description: A step-by-step tutorial for turning a TEI XML document into a web page with opm, and for changing how it looks.
---

# Convert TEI to HTML

This tutorial shows how to turn a TEI XML document into a web page you can open
in any browser. It takes about ten minutes. You do not need to know XSLT or any
programming language: the rules for how each TEI element should look are
written in a TEI document of their own, called an ODD.

By the end you will have:

1. a small project folder with your TEI file in it
2. an HTML version of that file
3. your first change to the way the output looks

## Before you start

You need `opm` installed on your computer. If you have not done this yet,
follow the [installation instructions](../getting-started/installation.md).
To check that it worked, open a terminal and type:

```bash
opm --help
```

You should see a list of commands.

## 1. Create a project

A project is simply a folder that holds your TEI files, the ODD with your
rendering rules, and a configuration file. Create a new one with:

```bash
opm init my-edition --vocabulary tei
cd my-edition
```

`opm` creates the folder `my-edition` and fills it with everything you need to
get started. The most important parts are:

| Path | What it is for |
| --- | --- |
| `data/` | your TEI documents. There is already a small `sample.xml` in it. |
| `odd/custom.odd` | your rendering rules. It starts out empty and inherits sensible defaults for all common TEI elements. |
| `templates/` | the page layout and stylesheet wrapped around your text |
| `opm.toml` | the project settings |

## 2. Convert the sample document

Let us first try the sample document that came with the project:

```bash
opm transform data/sample.xml --preview
```

`--preview` opens the result in your web browser. The first run takes a few
seconds longer, because `opm` first reads the ODD and prepares it. Later runs
reuse that work and are much faster.

To save the result as a file instead, name the output with `-o`:

```bash
opm transform data/sample.xml -o sample.html
```

## 3. Convert your own document

Now copy one of your own TEI files into the `data` folder and run the same
command on it:

```bash
opm transform data/letter.xml --preview
```

Most TEI documents will display reasonably well right away, since the default
rules cover many of the common elements: divisions, headings,
paragraphs, notes, lists, tables, figures, verse, drama, and many more.

## 4. Change how something looks

Suppose you want person names to appear in italics and in dark red. Open
`odd/custom.odd` in a text editor. Inside the `schemaSpec` element, add an
`elementSpec` for `persName`:

```xml
<schemaSpec ident="custom" start="TEI teiCorpus" source="teipublisher.odd">
    <elementSpec ident="persName" mode="change">
        <model behaviour="inline">
            <outputRendition>font-style: italic; color: #8b0000;</outputRendition>
        </model>
    </elementSpec>
</schemaSpec>
```

!!! tip "Graphical Editor"

    If you don't feel comfortable with editing the XML, there's also a graphical editor
    as a plugin for Visual Studio Code and derived editors like Cursor or Antigravity, called [ODDity](https://open-vsx.org/extension/e-editiones/oddity).

Let us look at what this says:

* `elementSpec ident="persName"` selects the TEI element we want to change.
  `mode="change"` means we only replace its rendering rules and keep everything
  else from the default ODD.
* `model behaviour="inline"` says that a person name should run along with the
  surrounding text, rather than start a new block like a paragraph would.
* `outputRendition` holds the styling, written in CSS.

Save the file and run the transform command again. The names are now shown in
italic red. `opm` notices that the ODD has changed and prepares it anew.

This is the general pattern for all changes: find the element, decide on a
*behaviour* (paragraph, heading, inline, note, link, …), and add styling where
needed. The [TEI Publisher documentation](https://teipublisher.org/doc/documentation.xml?id=odd#odd)
explains the available behaviours and includes a short tutorial on writing
processing models.

!!! tip "One set of rules for all formats"

    The same ODD is also used when you create a [PDF](tei-to-pdf.md), an
    [EPUB or Word file](tei-to-epub-word.md), or a [website](tei-website.md).
    Your change to `persName` applies to all of them.

## Why not XSLT?

The [TEI Stylesheets](https://github.com/TEIC/Stylesheets) and custom XSLT are
well-established ways of transforming TEI. The approach taken by `opm` differs
in where the rules live. Instead of a program, you write a TEI document that
describes the desired output, following the *TEI Processing Model* which is part
of the TEI Guidelines. This has some practical advantages:

* the rules are easier to read and change for people who know TEI but are not
  programmers
* one set of rules produces HTML, PDF, EPUB, Word and Markdown
* ODD expands to _One Document Does it all_ for a reason: it can host schema definitions,
encoding guidelines, documentation and the processing document — all in the same TEI file
* the same ODD also works in [TEI Publisher](https://teipublisher.org), so you
  can move between a static setup and a full web application without starting
  over

## Next steps

* Split a long document into pages and [publish it as a website](tei-website.md).
* Change the page layout and stylesheet: see [Templates & CSS](../guide/templates-and-css.md).
* Learn more about writing rules: see [ODD files](../guide/odd-files.md).
