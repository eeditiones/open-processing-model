# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: CC0-1.0

"""Your ``tp:`` functions for this documentation site.

opm.toml lists this module after the packaged ones, so every public function
here is callable from odd/tagdocs.odd as ``tp:<name>(...)``, and one named like
a packaged function replaces it — ``contained_by``, ``spec_catalog``,
``heading_label``, and so on (see opm/runtime/spec_xpath_functions.py for the
full set and how each is built).

Two layers are there to build on:

* ``opm.runtime.spec_primitives`` — lookups into the schema's index:
  ``spec_members_of``, ``spec_referrers``, ``spec_class_members``,
  ``spec_model_ancestors``, ``spec_content_refs``. They are callable from the
  ODD too, so a list can often be changed with XPath alone.
* ``opm.runtime.spec_xpath_functions`` — the packaged functions, to call from
  yours when you only want to change part of what one does.

Import them as modules, as below: every public callable in this file becomes a
``tp:`` function, imported names included.
"""

from __future__ import annotations

from opm.runtime import spec_xpath_functions as packaged  # noqa: F401

# Two examples, left inactive — uncomment one to see it on the next build.
#
# Replace a packaged function, building on it: attribute status in lower case
# ("optional" rather than "Optional") on every reference page.
#
# def usage_label(usage):
#     return packaged.usage_label(usage).lower()
#
# Add a function of your own, composed from the primitives: how many elements
# a class admits, for a model's reference page — call it in odd/tagdocs.odd as
# tp:class_size(@ident, .).
#
# from opm.runtime import spec_primitives as primitives
#
# def class_size(ident, node=None):
#     return len(primitives.spec_class_members(ident, node))
