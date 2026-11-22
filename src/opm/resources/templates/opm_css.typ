// Dispatch ODD @cssClass / @rend wrappers emitted as #opm-css("name")[…].
// Define ``opm-css-fns`` before including this fragment.
#let opm-css(name, body) = {
  let fn = opm-css-fns.at(name, default: none)
  if fn == none { body } else { fn(body) }
}

// Aliases for behaviours that call these by name (e.g. note place=margin).
#let pb(body) = opm-css("pb", body)
// A margin note with a ``marker`` (the note's @n) shows it at the note and at
// its anchor in the text; without one the note is unmarked.
#let marginnote(body, marker: none) = {
  let fn = opm-css-fns.at("marginnote", default: none)
  if fn == none { body } else if marker == none { fn(body) } else { fn(body, marker: marker) }
}
