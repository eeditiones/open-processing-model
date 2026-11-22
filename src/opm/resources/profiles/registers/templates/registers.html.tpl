[#
  Blocks the registers profile adds to every HTML page: the register in the
  `before` or `after` column, as [context.features.register] column says.
  The panel itself is registers-panel.html.tpl.
#]
<template>
    [% template before %]
    [% if $context?features?register?enabled and $context?features?register?column = 'before' %]
    [% include "registers-panel.html.tpl" %]
    [% endif %]
    [% endtemplate %]

    [% template after %]
    [% if $context?features?register?enabled and not($context?features?register?column = 'before') %]
    [% include "registers-panel.html.tpl" %]
    [% endif %]
    [% endtemplate %]
</template>
