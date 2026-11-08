[#
  The packaged collection index, written by `opm chunk` for a directory, on
  opm's page layout. Theme stylesheets linked as assets recolour it through
  --opm-* variables.
#]
---toml
[theme.layout]
class = "opm-index"

[templating]
extends = "opm/layout.html.tpl"
---
[% template meta %]<!-- opm-default-index-template -->[% endtemplate %]
[% template title %]<title>[[ ($context?site_name[. != ''], $context?title)[1] ]]</title>[% endtemplate %]
[# After the ODD's stylesheet, which may style headings and links too. #]
[% template odd_overrides %]
  <style type="text/css">
    .opm-index { --opm-layout-content-max: 46rem; }
    .opm-index .opm-main { padding: 2rem 0 4rem; }
    .index-list { list-style: none; margin: 0; padding: 0; }
    .index-item {
      padding: 1rem 0;
      border-top: 1px solid var(--opm-color-rule);
    }
    .index-item :is(h1, h2, h3, h4, h5, h6) {
      margin: 0 0 .25rem;
      font-size: 1.05rem;
      color: var(--opm-color);
    }
    .index-item a {
      color: inherit;
      text-decoration: none;
    }
    .index-item a:hover {
      color: var(--opm-color-accent);
      text-decoration: underline;
    }
    .index-meta {
      font-size: .85rem;
      color: var(--opm-color-muted);
    }
    .sample-description {
      font-size: .9rem;
      color: var(--opm-color-muted);
    }
  </style>
[% endtemplate %]

<ul class="index-list">
  [% for $doc in $context?documents?* %]
  <li class="index-item">
    [#
      Prefer the ODD's own browse record: models with
      $parameters?display='browse' emit heading, author and description, and
      build their own link from $parameters?doc. Fall back progressively when
      a project has not defined those models.
    #]
    [% if $doc?fragments?browse %]
    [[ $doc?fragments?browse ]]
    [% elif $doc?fragments?title %]
    <h2><a href="[[ $doc?href ]]">[[ $doc?fragments?title ]]</a></h2>
    [% else %]
    <h2><a href="[[ $doc?href ]]">[[ $doc?label ]]</a></h2>
    [% endif %]
    [#
      Always repeat the link here, outside the browse record. It keeps the
      entry reachable when an ODD's browse models emit no link of their own,
      and never nests inside the anchor they may have produced.
    #]
    <div class="index-meta">
      <a href="[[ $doc?href ]]">[[ $doc?name ]]</a> ·
      [[ $doc?chunks ]] [[ if ($doc?chunks = 1) then 'section' else 'sections' ]]
    </div>
  </li>
  [% endfor %]
</ul>
