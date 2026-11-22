"""Examples' copies of the scaffold templates stay in step with the scaffold.

An example carries its own copy of the shell and theme ``opm init`` would
give it, because its ``opm.toml`` points at them by path. A copy is either
identical to the scaffold version, or deliberately customised and listed in
``CUSTOMISED`` — so editing one without the other fails here instead of
drifting unnoticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCAFFOLD = ROOT / 'src' / 'opm' / 'resources' / 'scaffold' / 'templates'

# Example copies that differ from the scaffold on purpose, with the reason.
CUSTOMISED = {
    'docbook/templates/docbook.typ.tpl': 'narrower margin-note column',
    'docbook/templates/handbook.html.tpl': 'notes the pagefind profile',
    'monograph/templates/book.typ.tpl': 'printed monograph design',
    'shakespeare/templates/book.typ.tpl': 'Folio reading edition layout',
    'shakespeare/templates/chapbook.html.tpl': 'IIIF facsimile column',
}


def _copies() -> list[str]:
    examples = ROOT / 'examples'
    return sorted(
        path.relative_to(examples).as_posix()
        for path in examples.glob('*/templates/*')
        if path.is_file() and (SCAFFOLD / path.name).is_file()
    )


@pytest.mark.parametrize('copy', _copies())
def test_example_template_matches_scaffold(copy: str) -> None:
    example = (ROOT / 'examples' / copy).read_bytes()
    scaffold = (SCAFFOLD / Path(copy).name).read_bytes()
    if copy in CUSTOMISED:
        assert example != scaffold, (
            f'{copy} is identical to the scaffold again: remove it from CUSTOMISED'
        )
    else:
        assert example == scaffold, (
            f'examples/{copy} differs from the scaffold version: update one to '
            'match the other, or list it in CUSTOMISED if the difference is deliberate'
        )


def test_customised_entries_exist() -> None:
    missing = sorted(set(CUSTOMISED) - set(_copies()))
    assert not missing, f'CUSTOMISED lists files that are gone: {missing}'
