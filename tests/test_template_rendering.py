"""Tests for Jinja2 document template helpers."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest

from opm.template_rendering import DEFAULT_TYPST_TEMPLATE_NAME
from opm.template_rendering import default_template_path
from opm.template_rendering import render_typst_document_template
from opm.template_rendering import resolve_template_path


def _scaffold_template(name: str) -> Path:
    return Path(str(resources.files('opm').joinpath(f'resources/scaffold/templates/{name}')))


def test_default_template_is_packaged_and_resolvable() -> None:
    path = default_template_path()
    assert path.is_file()
    assert 'opm-default-template' in path.read_text(encoding='utf-8')


def test_default_typst_template_is_packaged() -> None:
    path = default_template_path(DEFAULT_TYPST_TEMPLATE_NAME)
    assert path.is_file()
    assert 'content_typst' in path.read_text(encoding='utf-8')


def test_render_typst_document_template() -> None:
    tpl = default_template_path(DEFAULT_TYPST_TEMPLATE_NAME)
    out = render_typst_document_template(
        content_typst='= Hello\n',
        template_path=tpl,
        odd_typst='#let tei_pb2(body) = body\n',
        parameters={'title': 'Test'},
    )
    assert '#let opm-css(name, body)' in out
    assert '#let pb(body) = opm-css("pb", body)' in out
    assert '#let image(source, ..args)' in out
    assert 'std.image' in out
    assert '@preview/marginalia' in out
    assert 'marginalia.setup.with' in out
    assert '#let tei_pb2(body)' in out
    assert '= Hello' in out
    assert 'title: "Test"' in out


def test_render_typst_docbook_template_includes_packaged_opm_css() -> None:
    tpl = _scaffold_template('docbook.typ.j2')
    out = render_typst_document_template(
        content_typst='= Hello\n',
        template_path=tpl,
        odd_typst='',
        parameters={},
        metadata={'title': ['Doc Title']},
    )
    assert '#let opm-css(name, body)' in out
    assert '@preview/ilm' in out
    assert '@preview/marginalia' in out
    assert 'guilabel:' in out
    assert 'note:' in out
    assert '= Hello' in out
    assert 'title: [Doc Title]' in out
    assert 'inner: (far: 2.5cm)' in out


def test_render_typst_book_template_fills_metadata() -> None:
    tpl = _scaffold_template('book.typ.j2')
    out = render_typst_document_template(
        content_typst='= Hello\n',
        template_path=tpl,
        odd_typst='',
        parameters={},
        metadata={'title': ['Book Title'], 'authors': ['Alice Smith', 'Bob Jones']},
    )
    assert 'title: [Book Title]' in out
    assert '"Alice Smith"' in out
    assert '"Bob Jones"' in out
    assert '@preview/ilm' in out
    assert '@preview/marginalia' in out
    assert '= Hello' in out
    assert 'Your Title' not in out
    assert 'guilabel:' not in out


def test_resolve_typst_template_path_raises_for_missing(tmp_path: Path) -> None:
    missing = tmp_path / 'missing.typ.j2'
    with pytest.raises(FileNotFoundError):
        resolve_template_path(missing, default_name=DEFAULT_TYPST_TEMPLATE_NAME)


def test_resolve_template_path_raises_for_missing_override(tmp_path: Path) -> None:
    missing = tmp_path / 'does-not-exist.j2'
    with pytest.raises(FileNotFoundError):
        resolve_template_path(missing)
