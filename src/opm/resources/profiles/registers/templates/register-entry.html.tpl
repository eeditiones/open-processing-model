[#
  A register entry (people/{xml_id}.html, places/{xml_id}.html): the entry
  as the ODD renders it, followed by the documents of the site that mention
  it with @key or @ref in their text. The documents come from the chunking
  run (site_documents: title, link to the first page, the ids referenced).
  The entry's name, for the title and breadcrumb, is its first heading.
#]
---toml
[theme.body]
classes = ["register-page"]

[templating]
extends = "opm/layout.html.tpl"
---
[% template title %]
<title>[[ (normalize-space((parse-xml-fragment(string($context?content_html))//(*:h1, *:h2, *:h3))[1])[. != ''], $context?chunk?xml_id)[1] ]]</title>
[% endtemplate %]

[% template breadcrumb %]
<a href="index.html">[[ $context?page_label ]]</a>
<span>[[ normalize-space((parse-xml-fragment(string($context?content_html))//(*:h1, *:h2, *:h3))[1]) ]]</span>
[% endtemplate %]

[% let $id = $context?chunk?xml_id %]
[% let $mentions = $context?site_documents?*[?refs?* = $id] %]
<article class="register-entry">
  [[ $context?content_html ]]
  [% if exists($mentions) %]
  <section class="register-entry__mentions">
    <h2>Mentioned in</h2>
    <ul>
      [% for $doc in $mentions %]
      <li><a href="[[ $doc?href ]]">[[ $doc?title ]]</a></li>
      [% endfor %]
    </ul>
  </section>
  [% endif %]
</article>
[% endlet %][% endlet %]
