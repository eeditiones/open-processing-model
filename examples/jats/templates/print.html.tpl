[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0
#]
<!doctype html>
<html lang="[[ ($context?lang[. != ''], 'en')[1] ]]">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>[[ ($context?site_name[. != ''], 'Journal article')[1] ]]</title>
  <!-- journal print shell: no masthead, TOC rail or web components — the paged
       view keeps the reading view's typography by including opm-theme-journal.css. -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link
    href="https://fonts.googleapis.com/css2?family=Source+Sans+3:ital,wght@0,400;0,600;0,700;1,400&family=Source+Serif+4:ital,opsz,wght@0,8..60,400..700;1,8..60,400..600&display=swap"
    rel="stylesheet"
  >
  [[ $context?head_html ]]
  <style type="text/css">
    [% include "opm-theme-journal.css" %]
  </style>
  <style type="text/css">
    [% include "print.css" %]
  </style>
  [% if $context?odd_css %]
  <style type="text/css">
[[ $context?odd_css ]]
  </style>
  [% endif %]
</head>
<body class="print">
  <article class="content">
    [[ $context?content_html ]]
  </article>
</body>
</html>
