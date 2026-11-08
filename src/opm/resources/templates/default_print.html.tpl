[#
  The packaged print template: a minimal shell for paged-media CSS, without
  the page layout.
#]
---json
{ "templating": { "extends": "opm/base.html.tpl" } }
---
[% template meta %]<!-- opm-default-print-template: minimal shell for paged-media CSS -->[% endtemplate %]
[% template body_class %]content print[% endtemplate %]
[% template body %]
  [[ $context?content_html ]]
[% endtemplate %]
