[#
  Blocks the iiif profile adds to every HTML page with text: a IIIF viewer
  in the layout's `after` column, listening on the "transcription" channel
  the <pb-facs-link> of each page break emits on. pb-tify ships as its own
  script beside the pb-components bundle, so its URL is derived from
  webcomponents_url. Settings: [context.features.iiif].

  pb-facsimile prefixes the image each <pb-facs-link facs> names with
  base-uri. Like pb-tify it emits on "transcription" as well: a link that
  subscribes to that channel (teipublisher.odd's pb-facsimile model does)
  only waits for viewers emitting on it (wait() in pb-mixin.js), and would
  otherwise announce its image before the viewer, later on the page, listens. Tiles from another origin need cors="Anonymous", or
  OpenSeadragon's WebGL drawer may not upload them and the viewer stays
  empty. The sequence mode shows one page at a time instead of stacking them.
#]
<template>
    [% template scripts %]
    [% let $settings = $context?features?iiif %]
    [% if $settings?enabled and $settings?viewer = 'pb-tify' and $context?webcomponents_url and exists($context?content_html) %]
    <script type="module" src="[[ replace($context?webcomponents_url, '[^/]+\.js$', 'pb-tify.js') ]]"></script>
    [% endif %]
    [% endlet %]
    [% endtemplate %]

    [% template body_class %][% if $context?features?iiif?enabled and $context?webcomponents_url and exists($context?content_html) %] iiif--with-facs[% endif %][% endtemplate %]

    [% template after %]
    [% let $settings = $context?features?iiif %]
    [% if $settings?enabled and $context?webcomponents_url and exists($context?content_html) %]
    <aside class="iiif-facs" aria-label="[[ $settings?label ]]">
      [% if $settings?viewer = 'pb-facsimile' %]
      <pb-facsimile base-uri="[[ $settings?base_uri ]]" cors="Anonymous" default-zoom-level="0"
        show-sequence-control show-navigator show-navigation-control subscribe="transcription" emit="transcription"></pb-facsimile>
      [% else %]
      <pb-tify subscribe="transcription" emit="transcription"></pb-tify>
      [% endif %]
    </aside>
    [% endif %]
    [% endlet %]
    [% endtemplate %]
</template>
