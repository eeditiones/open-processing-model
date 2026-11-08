[#
  The page layout, with the regions of the jinks base layout
  (opm/layout.html.j2 is the same layout for Jinja2 templates):

      header      (full width, sticky)
      hero        (full width)
      before-top  content-top  after-top
      before      content      after
      footer      (full width)

  Fill a region with a template of the same name (with underscores:
  before_top, content_top, after_top). As in jinks, every region is written;
  opm-layout.css gives an empty one no room. The content block defaults to
  the transformed document.

  The header and the content-top region are written by the layout, so a
  template fills slots in them instead of replacing them:

      header       menubar: logo, context.menu.items, menu_left |
                   menu_toggles, drawer triggers; then the header block
      content-top  toolbar: breadcrumb | toggle, prev/next, toolbar;
                   then the content_top block

  logo defaults to context.logo and the title (context.site_name or
  context.title); breadcrumb to the `breadcrumbs` fragment. menu_left,
  menu_toggles, toggle and toolbar take <li> items.

  Settings, under `layout` in the context (defaults in opm/defaults.toml,
  overridden by opm.toml [context] and then by template frontmatter):
    layout.class          extra classes on the layout container
    layout.before.width   width of the before column (CSS length)
    layout.before.mobile  "drawer" (slides in, opened from the menubar) or
                          "stack" (shown below the content)
    layout.before.label   label of the drawer's open button
    layout.before.span_top  start the column level with content-top, not below
                          it (ignored while before-top has content)
    layout.after.*        the same for the after column
    menu.items            links after the logo: [{ label, url }]
    features.menubar      false drops the menubar (the header block stays)
    features.toolbar.enabled     false drops the toolbar
    features.toolbar.navigation  previous/next links for chunk pages
#]
---json
{ "templating": { "extends": "opm/base.html.tpl" } }
---
[% template layout_styles %]
  [% if $context?layout_css_url %]
  <link rel="stylesheet" href="[[ $context?layout_css_url ]]">
  [% else %]
  <style type="text/css">
[% include "opm/opm-layout.css" %]
  </style>
  [% endif %]
[% endtemplate %]

[% template body %]
<div class="opm-layout [[ $layout?class ]] opm-before--[[ if ($layout?before?mobile = 'drawer') then 'drawer' else 'stack' ]] opm-after--[[ if ($layout?after?mobile = 'drawer') then 'drawer' else 'stack' ]][[ if ($layout?before?span_top) then ' opm-before--span-top' else '' ]][[ if ($layout?after?span_top) then ' opm-after--span-top' else '' ]]"
  style="![[ string-join((
      if ($layout?before?width) then '--opm-layout-before-width: ' || $layout?before?width || ';' else (),
      if ($layout?after?width) then '--opm-layout-after-width: ' || $layout?after?width || ';' else ()
    ), ' ') ]]">
  <a class="opm-skip" href="#opm-content">[[ $layout?skip_label ]]</a>
  [% if $layout?before?mobile = 'drawer' %]
  <input type="checkbox" id="opm-before-toggle" class="opm-drawer__toggle" autocomplete="off">
  [% endif %]
  [% if $layout?after?mobile = 'drawer' %]
  <input type="checkbox" id="opm-after-toggle" class="opm-drawer__toggle" autocomplete="off">
  [% endif %]

  <header class="page-header">
    [% if $features?menubar %]
    <nav class="menubar" aria-label="Site">
      <ul>
        <li class="logo">
        [% block logo %]
        [% let $logo = string($context?logo) %]
        [% let $logo-src = if ($logo != '' and $context?assets and not(contains($logo, '/')) and not(contains($logo, ':'))) then $context?assets || '/' || $logo else $logo %]
        [% let $logo-title = string(($context?site_name, $context?title)[string(.) != ''][1]) %]
        [% if $logo-src != '' or $logo-title != '' %]
        <a href="[[ ($context?home_url, $context?index_url, 'index.html')[string(.) != ''][1] ]]">
          [% if $logo-src != '' %]<img class="logo__image" src="[[ $logo-src ]]" alt="">[% endif %]
          [% if $logo-title != '' %]<span class="logo__title">[[ $logo-title ]]</span>[% endif %]
        </a>
        [% endif %]
        [% endlet %]
        [% endlet %]
        [% endlet %]
        [% endblock %]
        </li>
        [% for $item in $context?menu?items?* %]
        <li><a href="[[ $item?url ]]">[[ $item?label ]]</a></li>
        [% endfor %]
        [% block menu_left %][% endblock %]
      </ul>
      <ul>
        [% block menu_toggles %][% endblock %]
        [% if $layout?before?mobile = 'drawer' %]<li class="trigger"><label for="opm-before-toggle" class="opm-drawer__open opm-drawer__open--before">[[ $layout?before?label ]]</label></li>[% endif %]
        [% if $layout?after?mobile = 'drawer' %]<li class="trigger"><label for="opm-after-toggle" class="opm-drawer__open opm-drawer__open--after">[[ $layout?after?label ]]</label></li>[% endif %]
      </ul>
    </nav>
    [% endif %]
    [% block header %][% endblock %]
  </header>

  <div class="hero">[% block hero %][% endblock %]</div>

  <nav class="before-top">[% block before_top %][% endblock %]</nav>

  <aside class="before" id="opm-before">
    [% if $layout?before?mobile = 'drawer' %]
    <div class="opm-drawer__head">
      <span class="opm-drawer__title">[[ $layout?before?label ]]</span>
      <label for="opm-before-toggle" class="opm-drawer__close">[[ $layout?close_label ]]</label>
    </div>
    [% endif %]
    [% block before %][% endblock %]
  </aside>

  <header class="content-top">
    [% if $features?toolbar?enabled %]
    <nav class="toolbar" aria-label="Toolbar">
      <div class="breadcrumb">[% block breadcrumb %][[ $context?fragments?breadcrumbs ]][% endblock %]</div>
      <ul>
        [% block toggle %][% endblock %]
        [% if $features?toolbar?navigation and ($context?chunk?prev or $context?chunk?next) %]
        <li class="toolbar__navigation">
          [% if $context?chunk?prev %]<a href="[[ $context?chunk?prev ]].html" rel="prev">&#8592; [[ $layout?previous_label ]]</a>[% endif %]
          [% if $context?chunk?next %]<a href="[[ $context?chunk?next ]].html" rel="next">[[ $layout?next_label ]] &#8594;</a>[% endif %]
        </li>
        [% endif %]
        [% block toolbar %][% endblock %]
        [% if not($features?menubar) %]
        [% if $layout?before?mobile = 'drawer' %]<li class="trigger"><label for="opm-before-toggle" class="opm-drawer__open opm-drawer__open--before">[[ $layout?before?label ]]</label></li>[% endif %]
        [% if $layout?after?mobile = 'drawer' %]<li class="trigger"><label for="opm-after-toggle" class="opm-drawer__open opm-drawer__open--after">[[ $layout?after?label ]]</label></li>[% endif %]
        [% endif %]
      </ul>
    </nav>
    [% endif %]
    [% block content_top %][% endblock %]
  </header>

  <main class="opm-main" id="opm-content">
    [% block content %]
    <article class="content">
      [[ $context?content_html ]]
    </article>
    [% endblock %]
  </main>

  <nav class="after-top">[% block after_top %][% endblock %]</nav>

  <aside class="after" id="opm-after">
    [% if $layout?after?mobile = 'drawer' %]
    <div class="opm-drawer__head">
      <span class="opm-drawer__title">[[ $layout?after?label ]]</span>
      <label for="opm-after-toggle" class="opm-drawer__close">[[ $layout?close_label ]]</label>
    </div>
    [% endif %]
    [% block after %][% endblock %]
  </aside>

  <footer class="page-footer">[% block footer %][% endblock %]</footer>

  [% if $layout?before?mobile = 'drawer' or $layout?after?mobile = 'drawer' %]
  <div class="opm-drawer__backdrop" aria-hidden="true">
    [% if $layout?before?mobile = 'drawer' %]<label for="opm-before-toggle"></label>[% endif %]
    [% if $layout?after?mobile = 'drawer' %]<label for="opm-after-toggle"></label>[% endif %]
  </div>
  [% endif %]
</div>
[% endtemplate %]
