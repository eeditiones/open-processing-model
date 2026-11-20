[#
  A register entry (people/{xml_id}.html, places/{xml_id}.html), as the ODD
  renders it in register-details mode, including the documents that mention
  it. The entry's name, for the title and breadcrumb, is the text of its
  first heading (read with regular expressions: the HTML need not be XML).
#]
---toml
[theme.body]
classes = ["register-page"]

[templating]
extends = "opm/layout.html.tpl"
---
[% template title %]
<title>[[ ((let $html := string($context?content_html) return if (matches($html, '<h[1-3][\s>]')) then normalize-space(replace(replace($html, '^.*?<h[1-3][^>]*>(.*?)</h[1-3]>.*$', '$1', 's'), '<[^>]+>', '')) else '')[. != ''], $context?chunk?xml_id)[1] ]]</title>
[% endtemplate %]

[% template breadcrumb %]
<a href="index.html">[[ $context?page_label ]]</a>
<span>[[ (let $html := string($context?content_html) return if (matches($html, '<h[1-3][\s>]')) then normalize-space(replace(replace($html, '^.*?<h[1-3][^>]*>(.*?)</h[1-3]>.*$', '$1', 's'), '<[^>]+>', '')) else '') ]]</span>
[% endtemplate %]

<article class="register-entry">
  [[ $context?content_html ]]
</article>
