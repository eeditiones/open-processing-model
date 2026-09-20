# Vendored dependencies

## elementpath

A fork of [elementpath](https://github.com/sissaschool/elementpath) adding an XQuery 3.1
parser, vendored because opm needs XQuery and the fork is not published anywhere PyPI
would let opm depend on it. MIT, as upstream; see `elementpath/LICENSE`.

| | |
|---|---|
| Upstream | <https://github.com/wolfgangmm/elementpath> |
| Commit | `6c2ea51b5679d1bcbb565dcbaa918427d50ccaaa` |
| Subject | Support group by expressions |
| Base version | 5.1.4 |

Imports are rewritten from `elementpath.*` to `opm._vendor.elementpath.*`, so this copy
never collides with a stock elementpath in the same environment.

**Do not edit anything here.** Fix the fork, then run:

```sh
python scripts/vendor_elementpath.py <path-to-fork>
```
