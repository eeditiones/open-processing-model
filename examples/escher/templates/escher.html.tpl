[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  The Escher page shell for the letters: the "paper" theme
  (opm-theme-paper.css, EB Garamond for the text, Alegreya Sans for the
  furniture) on opm's packaged layout. letter.css adds what a letter needs
  on top. Templates extending this one fill the layout's blocks.
#]
---toml
[theme.body]
classes = ["opm-reader", "escher"]

[templating]
extends = "opm/layout.html.tpl"
---

