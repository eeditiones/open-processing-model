[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  The Serafin page shell for the letter pages, on opm's packaged layout,
  which writes the menubar (the wordmark, context.logo) and the breadcrumb
  toolbar (letter.css turns it into the parchment band). letter.css (from
  [transform.web] assets) supplies the theme and its fonts. Templates
  extending this one fill the layout's blocks: `breadcrumb`, `menu_toggles`,
  content and sidebars.
#]
---toml
[theme.body]
classes = ["letter"]

[templating]
extends = "opm/layout.html.tpl"
---
