# Member Licence Grant

**DRAFT — not reviewed by counsel.**

Open Processing Model (`opm`) is licensed to the public under AGPL-3.0-or-later, with the
additional permissions in [LICENSE-EXCEPTIONS.md](LICENSE-EXCEPTIONS.md). This document
sets out an alternative licence available to members of e-editiones.

## 1. The grant

e-editiones grants to each member in good standing a licence to use, modify and convey
`opm` under the terms of the GNU Lesser General Public License, version 3 or later
(LGPL-3.0-or-later), as an alternative to the AGPL.

The grant is automatic on becoming a member. No application, signature or key is required.
On request, e-editiones will issue a written confirmation naming the member and the
covered releases, for members whose institutions require one for their records.

## 2. Which releases are covered

The grant covers every release of `opm` published during the member's membership.

For those releases the licence is perpetual and irrevocable: it survives the end of
membership, and the member and its downstream recipients keep their LGPL rights in them
indefinitely.

Releases published after membership ends are not covered and are available under the AGPL
like any other public release.

## 3. What this changes in practice

Under the LGPL, in contrast to the AGPL:

- an application that uses `opm` as a library may remain proprietary; and
- a hosted service built on `opm` owes its users nothing corresponding to AGPL section 13.

## 4. What still applies

The LGPL's own obligations remain in force. In particular, under section 4:

- modifications to `opm` itself must be made available under the LGPL when conveyed;
- recipients of your application must be able to substitute their own build of `opm`. In
  Python this is satisfied by depending on the published package rather than vendoring a
  patched copy — and, where you do ship a modified `opm`, by providing its source. Where
  the substitution cannot happen at install time at all — a vendored copy, a frozen binary,
  an image the user cannot alter — section 4d0 applies instead, and your application must
  be shipped in a form that permits relinking against a modified `opm`;
- copyright and licence notices must be preserved.

## 5. Onward distribution

This grant is a genuine LGPL licence. A member may therefore convey copies received under
it to third parties under the LGPL, including publicly, and those recipients acquire LGPL
rights directly. e-editiones accepts this consequence knowingly.

Membership is worth having for currency, support, participation in the roadmap and
assurance about future releases — not for exclusivity, which no LGPL grant could provide.

## 6. What requires a separate agreement

- Removing or altering copyright notices and licence information.
- Conveying `opm`, or a work containing it, on terms that do not satisfy the LGPL.

Write to `info@e-editiones.org`.

## 7. Relationship to the public licence

This grant does not modify, replace or restrict the AGPL licence under which `opm` is
published, nor the additional permissions in
[LICENSE-EXCEPTIONS.md](LICENSE-EXCEPTIONS.md). A member may rely on either licence, and
may rely on different licences for different projects.

---

```
e-editiones
c/o Stadtarchiv der Ortsbürgergemeinde St.Gallen
Notkerstrasse 22
CH-9000 St. Gallen
Switzerland

info@e-editiones.org
UID CHE-474.398.996
```

*Plain-language summary; the LGPL-3.0 text governs the terms it grants. This document is
governed by the laws of Switzerland.*
