<p align="center">
  <img src="assets/logo-wordmark.svg#only-light" alt="opm — Open Processing Model" width="380">
  <img src="assets/logo-wordmark-dark.svg#only-dark" alt="opm — Open Processing Model" width="380">
</p>

# Open Processing Model

**Open Processing Model** (`opm`) is an implementation of the [TEI Processing Model](https://tei-c.org/release/doc/tei-p5-doc/en/html/TD.html#TDPM) 
in Python. It provides a command-line client and library for transforming
XML documents — TEI, DocBook, and others — into (currently) HTML, Markdown, DOCX, [Typst](https://typst.app/), HTML for print and ePub. Instead of being hard-coded in XSLT or XQuery, transformation rules are declared in an **TEI ODD** document, which `opm` compiles into a reusable Python module.

`opm` is pure Python with minimal dependencies and implements the full _TEI Processing Model_. Most ODDs will be compatible and can be exchanged between _TEI Publisher_ and `opm`, allowing users to combine the benefits of a dynamic, database-backed website with the speed of static rendering.

To learn more about ODD, it is best to read the [TEI Publisher documentation](https://teipublisher.org/doc/documentation.xml?id=odd#odd).
It also includes a small tutorial in the [Gentle Introduction](https://teipublisher.org/doc/quickstart.xml?id=pm-tutorial#pm-tutorial) document.

## Uses

Typical usage scenarios for `opm` include:

* quick transformation of XML documents on the command line
* split large documents into chunks, so they can be read page by page
* prepare HTML data to be used by other systems such as static site generators
* provide [pre-rendered content for TEI Publisher](guide/tei-publisher.md) to speed up load times

## Where to go next

- New here? Start with [Installation](getting-started/installation.md) and the
  [Quickstart](getting-started/quickstart.md).
- Learn the concepts: [ODD files](guide/odd-files.md),
  [Output formats](guide/output-formats.md),
  [XPath extensions](guide/xpath-extensions.md),
  [Templates & CSS](guide/templates-and-css.md),
  [Chunking](guide/chunking.md),
  [Integration with TEI Publisher](guide/tei-publisher.md), and the
  [`opm.toml` configuration](guide/configuration.md).
- Reference: the [CLI](cli.md) and the [Python API](api/index.md).

## Supporters

Development of `opm` is supported by:

<ul class="supporters">
  <li>
    <a href="https://www.ernst-goehner-stiftung.ch/" title="Ernst Göhner Stiftung">
      <img src="assets/EGS_Logo_Standard_RGB.svg#only-light" alt="Ernst Göhner Stiftung">
      <img src="assets/EGS_Logo_Standard_RGB_white.svg#only-dark" alt="Ernst Göhner Stiftung">
    </a>
  </li>
  <li>
    <a href="https://www.sagw.ch/" title="Swiss Academy of Humanities and Social Sciences">
      <img src="assets/SAGW_Logo_addition_supported_pos.svg#only-light" alt="Swiss Academy of Humanities and Social Sciences">
      <img src="assets/SAGW_Logo_addition_supported_pos_white.svg#only-dark" alt="Swiss Academy of Humanities and Social Sciences">
    </a>
  </li>
  <li>
    <a href="https://www.zb.uzh.ch/" title="Zentralbibliothek Zürich">
      <img src="assets/ZB_Logo_RGB_1024px.png" alt="Zentralbibliothek Zürich">
    </a>
  </li>
  <li>
    <a href="https://www.zde.uzh.ch/" title="Zentrum Digitale Editionen &amp; Editionsanalytik, Universität Zürich">
      <img src="assets/uzh-logo-black.png#only-light" alt="Universität Zürich">
      <img src="assets/uzh-logo-white.png#only-dark" alt="Universität Zürich">
      <span class="supporters__note">Zentrum Digitale Editionen &amp; Editionsanalytik</span>
    </a>
  </li>
  <li>
    <a href="https://karlbarth.unibas.ch/" title="Karl Barth-Archiv, Universität Basel">
      <img src="assets/uni-basel-logo.svg#only-light" alt="Universität Basel">
      <img src="assets/uni-basel-logo-white.svg#only-dark" alt="Universität Basel">
      <span class="supporters__note">Karl Barth-Archiv</span>
    </a>
  </li>
</ul>

### An initiative of

<ul class="supporters supporters--initiative">
  <li>
    <a href="https://e-editiones.org/" title="e-editiones">
      <img src="assets/e-editiones-logo-color.svg#only-light" alt="e-editiones">
      <img src="assets/e-editiones-logo-white.svg#only-dark" alt="e-editiones">
    </a>
  </li>
</ul>
