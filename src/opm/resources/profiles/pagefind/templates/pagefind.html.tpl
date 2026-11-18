<template>
    [% template scripts %]
    <!-- Pagefind UI: script and stylesheet for the search modal -->
    [% let $search = $context?site_root || 'assets/' || $context?features?pagefind?base %]
    <script defer src="[[ $search ]]/pagefind-component-ui.js"></script>
    <link rel="stylesheet" href="[[ $search ]]/pagefind-component-ui.css">
    [% endlet %]
    [% endtemplate %]

    [% template menu.toggles %]
    <li><pagefind-modal-trigger></pagefind-modal-trigger></li>
    [% endtemplate %]

    [% template body_end %]
    <!-- Pagefind search modal -->
    <pagefind-modal></pagefind-modal>
    [% endtemplate %]
</template>
