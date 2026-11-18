[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  A letter: parallel transcription and translation, on opm's packaged
  layout, which writes the menubar (the wordmark, context.logo) and the
  breadcrumb toolbar (letter.css turns it into the parchment band).
  letter.css (from [transform.web] assets) supplies the theme and its fonts.
  The links to neighbouring letters and the register tabs in the layout's
  `after` column come from the edition-navigation and registers profiles
  ([project] profiles in opm.toml).
#]
---toml
[theme.body]
classes = ["letter"]

[templating]
extends = "opm/layout.html.tpl"
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
