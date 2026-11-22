[#
  Blocks the edition-navigation profile adds to every HTML page: two rows of
  links above the text, the edition's own order first, then the documents
  exchanged between the same correspondents.

  The edition_navigation fragment is a hidden <nav> whose data-* attributes
  carry the neighbouring documents' names, from the project ODD's
  edition-navigation mode (see opm-profile.toml).
  Only documents chunked in the same run have a page to link to, so a name
  counts only if it is among $context?documents, as a directory name or as
  a file name without its .xml.

  Every document is chunked into a directory of its own. A link points at
  the page with the same file name there, or at the directory itself when
  pages are called index.html ([chunking] file_pattern), so it works for one
  page per document. Settings: [context.features.edition-navigation].
#]
<template>
    [% template above-content %]
    [% let $settings = $context?features?edition-navigation %]
    [% if $settings?enabled and exists($context?chunk) and $context?fragments?edition_navigation %]
    [% let $nav = $context?fragments?edition_navigation %]
    [% let $value = function($name) { normalize-space(($nav//@*[local-name() = 'data-' || $name])[1]) } %]
    [% let $target = function($name) {
        let $v := $value($name)
        return ($context?documents?*[. = ($v, $v || '.xml')][$v != ''])[1]
      } %]
    [% let $page = if ($context?chunk?file = 'index.html') then '' else $context?chunk?file %]
    <nav class="edition-nav" aria-label="[[ $settings?label ]]">
      [% for $row in (
          [
            map { 'name': 'previous', 'label': $settings?previous_label, 'icon': 'M15 6 9 12l6 6' },
            map { 'name': 'next', 'label': $settings?next_label, 'icon': 'm9 6 6 6-6 6', 'end': true() }
          ],
          [
            map { 'name': 'previous-in-correspondence', 'label': $settings?previous_in_correspondence_label, 'icon': 'M13 6 7 12l6 6M18 6l-6 6 6 6' },
            map { 'name': 'next-in-correspondence', 'label': $settings?next_in_correspondence_label, 'icon': 'm6 6 6 6-6 6M11 6l6 6-6 6', 'end': true() }
          ]
        ) %]
      [% if $row(1)?name = 'previous' or exists($row?* ! $target(?name)) or $value('correspondence') != '' %]
      <div class="edition-nav__row[[ if ($row(1)?name = 'previous') then '' else ' edition-nav__row--thread' ]]">
        [% for $link in $row?* %]
        [% if $link?name = 'next-in-correspondence' and $value('correspondence') != '' %]
        <span class="edition-nav__mark">[[ $settings?correspondence_label ]]: [[ $value('correspondence') ]]</span>
        [% endif %]
        [% let $dir = $target($link?name) %]
        <a class="edition-nav__link[[ if ($link?end) then ' edition-nav__link--end' else '' ]]" href="![[ $dir ! ('../' || . || '/' || $page) ]]" title="![[ $dir ]]" aria-hidden="![[ empty($dir) ]]"><svg class="edition-nav__icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="[[ $link?icon ]]"></path></svg><span class="edition-nav__dir">[[ $link?label ]]</span></a>
        [% endlet %]
        [% endfor %]
      </div>
      [% endif %]
      [% endfor %]
    </nav>
    [% endlet %][% endlet %][% endlet %][% endlet %]
    [% endif %]
    [% endlet %]
    [% endtemplate %]
</template>
