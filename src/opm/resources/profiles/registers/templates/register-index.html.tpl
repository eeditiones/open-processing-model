[#
  A register overview (people/index.html, places/index.html): every entry
  as the ODD renders it in register-overview mode, a link to its detail
  page, sorted by name in the language of the site and grouped under the
  first letter. When entries carry a pb-geolocation (places), a map with
  every location goes above the list; a pin next to a name zooms to it.
#]
---toml
[theme.body]
classes = ["register-page"]

# No toolbar: these pages have no breadcrumb or prev/next.
[features.toolbar]
enabled = false

[templating]
extends = "opm/layout.html.tpl"
---
[% let $collation = 'http://www.w3.org/2013/collation/UCA?lang=' || ($context?lang[. != ''], 'en')[1] %]
[% let $entries = sort(parse-xml-fragment(string($context?content_html))//*:header/parent::*, $collation, function($entry) { normalize-space($entry/*:header) }) %]
[% let $initials = distinct-values($entries ! upper-case(substring(normalize-space(*:header), 1, 1))) %]
<div class="register-index">
  <header class="register-index__head">
    <h1>[[ $context?page_title ]]</h1>
    <p class="register-index__count">[[ count($entries) ]]</p>
  </header>
  [% if exists($entries//*:pb-geolocation) and $context?webcomponents_url %]
  <pb-leaflet-map class="register-index__map" subscribe="map" emit="map" zoom="5" cluster="cluster" fit-markers="fit-markers">
    <pb-map-layer show="show" base="base" label="OpenStreetMap"
      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" max-zoom="19"
      attribution="© &lt;a href=&quot;https://www.openstreetmap.org/copyright&quot;&gt;OpenStreetMap&lt;/a&gt; contributors"></pb-map-layer>
  </pb-leaflet-map>
  [% endif %]
  [% if count($initials) gt 1 %]
  <nav class="register-index__letters" aria-label="Initials">
    [% for $initial in $initials %]
    <a href="#letter-[[ $initial ]]">[[ $initial ]]</a>
    [% endfor %]
  </nav>
  [% endif %]
  [% for $initial in $initials %]
  <section class="register-index__group" id="letter-[[ $initial ]]">
    <h2 class="register-index__letter">[[ $initial ]]</h2>
    <ul class="register-index__list">
      [% for $entry in $entries[upper-case(substring(normalize-space(*:header), 1, 1)) = $initial] %]
      <li class="register-index__item">[[ $entry/node() ]]</li>
      [% endfor %]
    </ul>
  </section>
  [% endfor %]
</div>
[% endlet %][% endlet %][% endlet %]

[% template body_end %]
[% if $context?webcomponents_url and contains($context?content_html, 'pb-geolocation') %]
<script type="module" src="[[ replace($context?webcomponents_url, 'pb-components-bundle\.js$', 'pb-leaflet-map.js') ]]"></script>
<script type="module">
  // Every place with coordinates becomes a marker; a marker opens its page.
  const map = document.querySelector('.register-index__map');
  const places = [...document.querySelectorAll('.register-index__item')].flatMap((item) => {
    const geo = item.querySelector('pb-geolocation');
    const link = item.querySelector('a[href]');
    if (!geo || !geo.getAttribute('latitude') || !geo.getAttribute('longitude')) return [];
    return [{
      latitude: Number(geo.getAttribute('latitude')),
      longitude: Number(geo.getAttribute('longitude')),
      label: geo.getAttribute('label') || link?.textContent.trim(),
      id: link?.getAttribute('href'),
    }];
  });
  if (map && window.pbEvents) {
    window.pbEvents.ifReady(map).then(() => window.pbEvents.emit('pb-update-map', 'map', places));
    window.pbEvents.subscribe('pb-leaflet-marker-click', 'map', (ev) => {
      const href = ev.detail?.element?.id;
      if (href) window.location.href = href;
    });
  }
</script>
[% endif %]
[% endtemplate %]
