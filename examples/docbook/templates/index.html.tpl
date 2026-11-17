[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  DocBook collection index extending the default index template.
  Uses shared pagefind.html.tpl for Pagefind integration.
#]
---toml
[templating]
extends = "default_index.html.tpl"
use = ["pagefind.html.tpl"]
---
