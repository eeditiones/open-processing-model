[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  A letter: parallel transcription and translation, with the register tabs
  in the layout's `after` column. The shell comes from serafin.html.tpl.
#]
---json
{ "templating": { "extends": "serafin.html.tpl" } }
---
[# The letter's title, from the breadcrumbs without their markup. #]
[% template title %]
<title>[[ (normalize-space($context?fragments?breadcrumbs), 'Serafin')[. != ''][1] ]]</title>
[% endtemplate %]

[% template body_class %][[
  string-join((
    if (exists($context?chunk)) then 'letter--chunk' else (),
    if ($context?fragments?translation) then 'letter--parallel' else (),
    if ($context?fragments?register_people or $context?fragments?register_places) then 'letter--with-register' else ()
  ), ' ')
]][% endtemplate %]

[% template breadcrumb %]
  [% if $context?fragments?breadcrumbs %]
  [[ $context?fragments?breadcrumbs ]]
  [% else %]
  Serafin
  [% endif %]
[% endtemplate %]

<div class="letter-body">
  [% if exists($context?chunk) or $context?fragments?letter_head %]
  <div class="letter-intro">
    [% if exists($context?chunk) %]
    [#
      The edition_navigation fragment is a hidden <nav> whose data-* attributes
      carry the neighbouring letters' stems (see correspContext in the ODD).
      Only letters chunked in this run have a page to link to; the example
      holds two letters of a larger correspondence. $target gives the stem a
      link points to, or an empty string.
    #]
    [% let $nav = $context?fragments?edition_navigation %]
    [% let $target = function($name) {
        let $stem := normalize-space(($nav//@*[local-name() = 'data-' || $name])[1])
        return if ($stem != '' and $stem || '.xml' = $context?documents?*) then $stem else ''
      } %]
    [# Every letter is chunked into its own directory, named after the source file. #]
    [% let $letter-href = function($stem) { '../' || $stem || '.xml/001.html' } %]
    [% let $icon = function($path) {
        parse-xml-fragment('<svg class="letter-nav__icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="' || $path || '"></path></svg>')
      } %]
    [% let $prev-letter = $target('previous') %]
    [% let $next-letter = $target('next') %]
    [% let $prev-corr = $target('previous-in-correspondence') %]
    [% let $next-corr = $target('next-in-correspondence') %]
    [#
      Within a letter first, then across letters — a Serafin letter is a
      single chunk, so in practice this is always the cross-letter case.
    #]
    [% let $prev-href = if ($context?chunk?prev) then $context?chunk?prev || '.html' else if ($prev-letter != '') then $letter-href($prev-letter) else '' %]
    [% let $next-href = if ($context?chunk?next) then $context?chunk?next || '.html' else if ($next-letter != '') then $letter-href($next-letter) else '' %]
    [% let $folio = replace($context?chunk?file, '.html', '', 'q') %]
    [% if $prev-href != '' or $next-href != '' or $prev-corr != '' or $next-corr != '' %]
    [# Correspondence toolbar: previous / next in the edition, plus the
       same-correspondent thread when the TEI records it. #]
    <nav class="letter-nav" aria-label="Letter navigation">
      <div class="letter-nav__side letter-nav__side--prev">
        <div class="letter-nav__group">
          [% if $prev-href != '' %]
          <a class="letter-nav__link" href="[[ $prev-href ]]" title="[[ if ($context?chunk?prev) then 'Verso' else $prev-letter ]]">
            [[ $icon('M15 6 9 12l6 6') ]]
            <span class="letter-nav__dir">Previous</span>
          </a>
          [% elif $next-href != '' %]
          <span class="letter-nav__link letter-nav__link--disabled" aria-hidden="true">
            [[ $icon('M15 6 9 12l6 6') ]]
            <span class="letter-nav__dir">Previous</span>
          </span>
          [% endif %]
          [% if $prev-corr != '' %]
          <a class="letter-nav__link letter-nav__link--thread" href="[[ $letter-href($prev-corr) ]]" title="Previous in correspondence: [[ $prev-corr ]]">
            [[ $icon('M13 6 7 12l6 6M18 6l-6 6 6 6') ]]
            <span class="letter-nav__dir">Correspondence</span>
          </a>
          [% endif %]
        </div>
      </div>

      [# The letter, as in the Astro edition; its folio only when it has several. #]
      <div class="letter-nav__mark">[[ if ($context?document) then replace($context?document, '.xml', '', 'q') else $folio ]][% if $context?chunk?prev or $context?chunk?next %] · [[ $folio ]][% endif %]</div>

      <div class="letter-nav__side letter-nav__side--next">
        <div class="letter-nav__group letter-nav__group--end">
          [% if $next-corr != '' %]
          <a class="letter-nav__link letter-nav__link--thread" href="[[ $letter-href($next-corr) ]]" title="Next in correspondence: [[ $next-corr ]]">
            <span class="letter-nav__dir">Correspondence</span>
            [[ $icon('m6 6 6 6-6 6M11 6l6 6-6 6') ]]
          </a>
          [% endif %]
          [% if $next-href != '' %]
          <a class="letter-nav__link" href="[[ $next-href ]]" title="[[ if ($context?chunk?next) then 'Recto' else $next-letter ]]">
            <span class="letter-nav__dir">Next</span>
            [[ $icon('m9 6 6 6-6 6') ]]
          </a>
          [% elif $prev-href != '' %]
          <span class="letter-nav__link letter-nav__link--disabled" aria-hidden="true">
            <span class="letter-nav__dir">Next</span>
            [[ $icon('m9 6 6 6-6 6') ]]
          </span>
          [% endif %]
        </div>
      </div>
    </nav>
    [% endif %]
    [% endlet %][% endlet %][% endlet %][% endlet %][% endlet %][% endlet %]
    [% endlet %][% endlet %][% endlet %][% endlet %][% endlet %]
    [% endif %]

    [% if $context?fragments?letter_head %]
    <header class="letter-head">
      [[ $context?fragments?letter_head ]]
    </header>
    [% elif exists($context?chunk) %]
    <header class="letter-head letter-head--plain">
      <h1>Letter [[ (replace(replace($context?chunk?file, '.html', '', 'q'), '^0+', ''), '0')[. != ''][1] ]]</h1>
    </header>
    [% endif %]
  </div>
  [% endif %]

  <div class="letter-parallel[[ if ($context?fragments?translation) then '' else ' letter-parallel--single' ]]">
    <section class="letter-pane letter-pane--source" aria-label="Transcription">
      <article class="content">
        [[ $context?content_html ]]
      </article>
    </section>

    [% if $context?fragments?translation %]
    <section class="letter-pane letter-pane--translation" aria-label="Translation">
      <article class="content">
        [[ $context?fragments?translation ]]
      </article>
    </section>
    [% endif %]
  </div>
</div>

[% template after %]
  [% let $people = $context?fragments?register_people %]
  [% let $places = $context?fragments?register_places %]
  [% if $people or $places %]
  <div class="letter-register">
    [% if $people %]
    <input type="radio" name="register-tab" id="register-tab-people" class="register-tabs__radio" checked autocomplete="off">
    [% endif %]
    [% if $places %]
    <input type="radio" name="register-tab" id="register-tab-places" class="register-tabs__radio"[% if not($people) %] checked[% endif %] autocomplete="off">
    [% endif %]

    <div class="register-tabs__strip">
      [% if $people %]
      <label for="register-tab-people" class="register-tabs__tab register-tabs__tab--people">People</label>
      [% endif %]
      [% if $places %]
      <label for="register-tab-places" class="register-tabs__tab register-tabs__tab--places">Places</label>
      [% endif %]
    </div>

    [% if $people %]
    <div class="register-tabs__panel register-tabs__panel--people">
      [[ $people ]]
    </div>
    [% endif %]
    [% if $places %]
    <div class="register-tabs__panel register-tabs__panel--places">
      [[ $places ]]
    </div>
    [% endif %]
  </div>
  [% endif %]
  [% endlet %]
  [% endlet %]
[% endtemplate %]
