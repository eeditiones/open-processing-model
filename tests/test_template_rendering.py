"""Tests for Jinja2 document template helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from teipublisher.template_rendering import default_template_path
from teipublisher.template_rendering import resolve_template_path


def test_default_template_is_packaged_and_resolvable() -> None:
    path = default_template_path()
    assert path.is_file()
    assert 'teipublisher-default-template' in path.read_text(encoding='utf-8')


def test_resolve_template_path_raises_for_missing_override(tmp_path: Path) -> None:
    missing = tmp_path / 'does-not-exist.j2'
    with pytest.raises(FileNotFoundError):
        resolve_template_path(missing)
