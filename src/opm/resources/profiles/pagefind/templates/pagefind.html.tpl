[#
  Blocks the pagefind profile adds to every HTML page: the search button in
  the menubar and the search window. search.py writes the index and the
  Pagefind UI to assets/<base> once all pages are written. A project switches
  them off with [context.features.pagefind] enabled = false.
#]
<template>
    [% template scripts %]
    [% if $context?features?pagefind?enabled %]
    <!-- Pagefind UI: script and stylesheet for the search modal -->
    [% let $search = $context?site_root || 'assets/' || $context?features?pagefind?base %]
    <script defer src="[[ $search ]]/pagefind-component-ui.js"></script>
    <link rel="stylesheet" href="[[ $search ]]/pagefind-component-ui.css">
    [% endlet %]
    [% endif %]
    [% endtemplate %]

    [% template menu.toggles %]
    [% if $context?features?pagefind?enabled %]
    <li><pagefind-modal-trigger></pagefind-modal-trigger></li>
    [% endif %]
    [% endtemplate %]

    [% template body_end %]
    [% if $context?features?pagefind?enabled %]
    <!-- Pagefind search modal -->
    <pagefind-modal></pagefind-modal>
    [% endif %]
    [% endtemplate %]
</template>
