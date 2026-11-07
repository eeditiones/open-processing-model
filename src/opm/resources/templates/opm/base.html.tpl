[#
  jinks version of opm/base.html.j2: the document skeleton every opm HTML
  template can extend, <head> handling only. For a page with header,
  sidebars and footer, extend opm/layout.html.tpl instead.

  Blocks: html_attributes (more attributes for <html>), meta, title, styles,
  layout_styles, odd_overrides, scripts, body_class, body, body_end (for
  scripts that need the page content in place).

  A template adds to a block rather than replacing it, so the description
  meta tag is written outside the meta block and stays when a page adds to it.

  Stylesheets are linked in cascade order: the layout's own (block
  layout_styles), context.styles, the assets' stylesheets (asset_styles),
  block styles, the ODD's generated CSS, then block odd_overrides for rules
  that must win over the ODD's renditions.
#]
<!doctype html>
<html lang="![[ $context?lang ]]"[% block html_attributes %][% endblock %]>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  [% if $context?description %]<meta name="description" content="[[ $context?description ]]">[% endif %]
  [% block meta %][% endblock %]
  [% block title %][% if $context?title %]<title>[[ $context?title ]]</title>[% endif %][% endblock %]
  [% if $context?base_css %]
  <style type="text/css">
[[ $context?base_css ]]
  </style>
  [% endif %]
  [[ $context?head_html ]]
  [% block layout_styles %][% endblock %]
  [% for $href in $context?styles?* %]
  <link rel="stylesheet" href="[[ $href ]]">
  [% endfor %]
  [% for $href in $context?asset_styles?* %]
  <link rel="stylesheet" href="[[ $href ]]">
  [% endfor %]
  [% block styles %][% endblock %]
  [% if $context?odd_css_url %]
  <link rel="stylesheet" href="[[ $context?odd_css_url ]]">
  [% elif $context?odd_css %]
  <style type="text/css">
[[ $context?odd_css ]]
  </style>
  [% endif %]
  [% block odd_overrides %][% endblock %]
  [% if $context?webcomponents_url %]
  <script type="module" src="[[ $context?webcomponents_url ]]"></script>
  [% endif %]
  [% for $src in $context?scripts?* %]
  <script type="module" src="[[ $src ]]"></script>
  [% endfor %]
  [% block scripts %][% endblock %]
</head>
<body class="[[ string-join($context?body?classes?*, ' ') ]] [% block body_class %][% endblock %]">
[% block body %]
  <article class="content">
    [[ $context?content_html ]]
  </article>
[% endblock %]
[% block body_end %][% endblock %]
</body>
</html>
