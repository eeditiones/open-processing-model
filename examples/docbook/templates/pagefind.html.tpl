<template>
    [% template scripts %]
    <!-- Pagefind UI: script and stylesheet for the search modal -->
    <script defer src="[[ $context?assets ]]/search/pagefind-component-ui.js"></script>
    <link rel="stylesheet" href="[[ $context?assets ]]/search/pagefind-component-ui.css">
    [% endtemplate %]

    [% template menu.toggles %]
    <li><pagefind-modal-trigger></pagefind-modal-trigger></li>
    [% endtemplate %]

    [% template body_end %]
    <!-- Pagefind search modal -->
    <pagefind-modal></pagefind-modal>
    [% endtemplate %]
</template>
