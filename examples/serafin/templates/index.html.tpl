[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  The letter list `opm chunk data/letters` writes at the output root, in the
  same shell as the letters (serafin.html.tpl).
#]
---json
{ "templating": { "extends": "serafin.html.tpl" } }
---
[% template title %]<title>[[ $context?title ]]</title>[% endtemplate %]

[% template menu.toggles %]
  <li class="letter-count">[[ array:size($context?documents) ]] letters</li>
[% endtemplate %]

[% template breadcrumb %][[ $context?title ]][% endtemplate %]

<div class="letter-body">
  <article class="content">
    <ul class="letter-list">
      [% for $doc in $context?documents?* %]
      <li class="letter-list__item">
        <div class="letter-list__entry">
          [% if $doc?fragments?browse %]
          [[ $doc?fragments?browse ]]
          [% else %]
          <h5><a href="[[ $doc?href ]]">[[ ($doc?fragments?title[. != ''], $doc?label)[1] ]]</a></h5>
          [% endif %]
          <div class="letter-list__meta">
            <a href="[[ $doc?href ]]">[[ $doc?name ]]</a>
          </div>
        </div>
      </li>
      [% endfor %]
    </ul>
  </article>
</div>
