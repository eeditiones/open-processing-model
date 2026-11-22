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
    <style>
        /* Fit the search button to the menubar: a block, so it does not sit
           on the text baseline, and sized and coloured like the other
           controls. Override the --pf-* variables in a theme to change it. */
        .menubar pagefind-modal-trigger {
            display: block;
            --pf-input-height: 2rem;
            --pf-font: var(--opm-font-ui);
            --pf-background: var(--opm-surface);
            --pf-border: var(--opm-color-rule);
            --pf-border-focus: var(--opm-color-accent);
            --pf-text-muted: var(--opm-color-muted);
            --pf-border-radius: var(--opm-radius-sm);
        }
    </style>
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
