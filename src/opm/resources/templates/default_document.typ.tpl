// TEI Publisher default Typst document shell
// Override via [transform.typst] template in project config or --template

// Handlers for ODD @cssClass / @rend names emitted as #opm-css("name")[…].
[% include "opm_css_fns_default.typ.j2" %]

#show: marginalia.setup.with(
  inner: (far: 1.8cm),
  outer: (far: opm-margin-note-far, width: opm-margin-note-width, sep: opm-margin-note-sep),
  top: 2.5cm,
  bottom: 2.5cm,
)

// Extra handlers for ODD @cssClass / @rend names:
// #let opm-css-fns = opm-css-fns + (
// center: (body) => align(center, body),
// note: (body) => block(
// width: 100%,
// inset: (left: 0.8em, y: 0.35em),
// stroke: (left: 4pt + rgb("#d07f00")),
// body,
// ),
// )

[% include "opm_css.typ.j2" %]

[[ $context?odd_typst ]]

#set document(
  title: "[[ ($context?metadata?title?*, $context?parameters?title, '')[1] ]]",
)

[[ $context?content_typst ]]
