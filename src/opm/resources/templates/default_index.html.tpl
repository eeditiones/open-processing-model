[#
  The packaged collection index, written by `opm chunk` for a directory, on
  opm's page layout (default_index.html.j2 is the same for Jinja2).

  A masthead in the hero region (context.site_name or the index title,
  context.description, the counts), a bar to filter the documents and switch
  between list and grid, and one entry per document. Styles are in
  opm/opm-layout.css, the script in opm/opm-index.js; a theme restyles it
  through the --opm-* design tokens, its words are under theme.index in
  opm/defaults.toml.

  Each entry shows the document's `browse` fragment when the project
  declares one (the ODD's browse record: title, author, description), else
  its `title` fragment, else a label made from the file name.

  To change one part, extend this template: replace the masthead with the
  layout's `hero` template, the filter bar with block index.controls, or add
  below the list with block index.after.
#]
---toml
[theme.layout]
class = "opm-index"

[templating]
extends = "opm/layout.html.tpl"
---
[% template meta %]<!-- opm-default-index-template -->[% endtemplate %]
[% template title %]<title>[[ ($context?site_name[. != ''], $context?title)[1] ]]</title>[% endtemplate %]

[% template hero %]
[% let $docs = $context?documents %]
[% let $n = array:size($docs) %]
[% let $sections = sum($docs?*?chunks) %]
[#
  theme.index.hero.image: a bare file name lives in the shared assets/
  folder, as for context.logo; a path or URL is used as given.
#]
[% let $hero = $context?theme?index?hero %]
[% let $image = string($hero?image) %]
[% let $image-src = if ($image != '' and $context?assets and not(contains($image, '/')) and not(contains($image, ':'))) then $context?assets || '/' || $image else $image %]
[% if $image-src != '' %]
<header class="opm-masthead opm-masthead--image opm-masthead--[[ if ($hero?text = 'dark') then 'dark' else 'light' ]]" style="![[ if ($hero?position) then '--opm-masthead-position: ' || $hero?position else '' ]]">
  <img class="opm-masthead__image" src="[[ $image-src ]]" alt="" fetchpriority="high">
[% else %]
<header class="opm-masthead">
[% endif %]
  <div class="opm-masthead__inner">
    [% if $context?theme?index?eyebrow %]<p class="opm-masthead__eyebrow">[[ $context?theme?index?eyebrow ]]</p>[% endif %]
    <h1 class="opm-masthead__title">[[ ($context?site_name[. != ''], $context?title)[1] ]]</h1>
    [% if $context?description %]<p class="opm-masthead__description">[[ $context?description ]]</p>[% endif %]
    <dl class="opm-masthead__stats">
      <div>
        <dt>[[ if ($n = 1) then $context?theme?index?document_one else $context?theme?index?document_many ]]</dt>
        <dd>[[ $n ]]</dd>
      </div>
      [% if $sections > $n %]
      <div>
        <dt>[[ $context?theme?index?section_many ]]</dt>
        <dd>[[ $sections ]]</dd>
      </div>
      [% endif %]
    </dl>
  </div>
</header>
[% endlet %]
[% endlet %]
[% endlet %]
[% endlet %]
[% endlet %]
[% endlet %]
[% endtemplate %]

[% let $ix = $context?theme?index %]
[% let $docs = $context?documents %]
<div class="opm-collection" data-opm-index="" data-one="[[ $ix?document_one ]]" data-many="[[ $ix?document_many ]]" data-filter-min="[[ $ix?filter_min ]]">
  [% block index.controls %]
  <div class="opm-index__controls" hidden="">
    <label class="opm-index__filter">
      <span class="opm-visually-hidden">[[ $ix?filter_label ]]</span>
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="7" cy="7" r="4.75"/><path d="m10.5 10.5 3.75 3.75" stroke-linecap="round"/></svg>
      <input type="search" placeholder="[[ $ix?filter_placeholder ]]" autocomplete="off" spellcheck="false">
      <kbd aria-hidden="true">/</kbd>
    </label>
    <span class="opm-index__count" aria-live="polite">[[ array:size($docs) ]] [[ if (array:size($docs) = 1) then $ix?document_one else $ix?document_many ]]</span>
    <div class="opm-index__views" role="group">
      <button type="button" data-opm-view="list" aria-pressed="[[ string($ix?view != 'grid') ]]" title="[[ $ix?list_label ]]">
        <span class="opm-visually-hidden">[[ $ix?list_label ]]</span>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M2.5 4h11M2.5 8h11M2.5 12h11"/></svg>
      </button>
      <button type="button" data-opm-view="grid" aria-pressed="[[ string($ix?view = 'grid') ]]" title="[[ $ix?grid_label ]]">
        <span class="opm-visually-hidden">[[ $ix?grid_label ]]</span>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="2.25" y="2.25" width="4.5" height="4.5" rx="1"/><rect x="9.25" y="2.25" width="4.5" height="4.5" rx="1"/><rect x="2.25" y="9.25" width="4.5" height="4.5" rx="1"/><rect x="9.25" y="9.25" width="4.5" height="4.5" rx="1"/></svg>
      </button>
    </div>
  </div>
  [% endblock %]

  <ol class="opm-doclist" data-view="[[ if ($ix?view = 'grid') then 'grid' else 'list' ]]">
    [% for $i in 1 to array:size($docs) %]
    [% let $doc = $docs($i) %]
    <li class="opm-doc">
      <span class="opm-doc__num" aria-hidden="true">[[ format-integer($i, '01') ]]</span>
      <div class="opm-doc__body">
        [#
          The ODD's browse record may hold a link of its own, so it never
          goes inside one: the arrow is then the entry's link.
        #]
        [% if $doc?fragments?browse %]
        [[ $doc?fragments?browse ]]
        [% elif $doc?fragments?title %]
        <h2 class="opm-doc__title"><a class="opm-doc__link" href="[[ $doc?href ]]">[[ $doc?fragments?title ]]</a></h2>
        [% else %]
        <h2 class="opm-doc__title"><a class="opm-doc__link" href="[[ $doc?href ]]">[[ $doc?label ]]</a></h2>
        [% endif %]
      </div>
      [% if $doc?fragments?browse %]
      <a class="opm-doc__go opm-doc__link" href="[[ $doc?href ]]" aria-label="[[ $ix?open_label ]] [[ $doc?name ]]">&#8594;</a>
      [% else %]
      <span class="opm-doc__go" aria-hidden="true">&#8594;</span>
      [% endif %]
      <div class="opm-doc__meta">
        <span class="opm-doc__name">[[ $doc?name ]]</span>
        [% if $doc?chunks > 1 %]
        <span class="opm-doc__length">
          <span class="opm-doc__ticks" aria-hidden="true">[% for $t in 1 to min(($doc?chunks, $ix?max_ticks)) %]<i></i>[% endfor %][% if $doc?chunks > $ix?max_ticks %]<i class="more">+</i>[% endif %]</span>
          [[ $doc?chunks ]] [[ $ix?section_many ]]
        </span>
        [% endif %]
      </div>
    </li>
    [% endlet %]
    [% endfor %]
  </ol>
  <p class="opm-index__empty" hidden="">[[ $ix?empty_label ]]</p>
  [% block index.after %][% endblock %]
</div>
[% endlet %]
[% endlet %]

[% template body_end %]
<script>
[% include "opm/opm-index.js" %]
</script>
[% endtemplate %]
