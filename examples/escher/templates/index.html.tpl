[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  The letter list `opm chunk data/letters` writes at the output root, in the
  same shell as the letters (escher.html.tpl).
#]
---json
{ "templating": { "extends": "escher.html.tpl" } }
---
[% template title %]<title>[[ $context?title ]] · [[ $context?site_name ]]</title>[% endtemplate %]

[% template breadcrumb %][[ $context?title ]][% endtemplate %]

<div class="chap-page">
  <div class="chap-body">
    <article class="content">
      <ul class="letter-list">
        [% for $doc in $context?documents?* %]
        <li class="letter-list__item">
          [% if $doc?fragments?browse %]
          [[ $doc?fragments?browse ]]
          [% else %]
          <a class="letter-list__title" href="[[ $doc?href ]]">[[ $doc?label ]]</a>
          [% endif %]
        </li>
        [% endfor %]
      </ul>
    </article>
  </div>
</div>
