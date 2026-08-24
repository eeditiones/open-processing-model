"""Tests for packaged resource mirroring."""

from __future__ import annotations

from pathlib import Path


def test_ensure_packaged_odd_dir_refreshes_stale_mirror(tmp_path: Path, monkeypatch) -> None:
    from opm.resources import ensure_packaged_odd_dir, packaged_odd

    pkg = tmp_path / 'pkg'
    odd_dir = pkg / 'odd'
    odd_dir.mkdir(parents=True)
    (odd_dir / 'teipublisher.odd').write_text('old-odd', encoding='utf-8')

    cache = tmp_path / 'cache'
    monkeypatch.setattr('opm.resources.user_opm_cache_dir', lambda: cache)
    monkeypatch.setattr('opm.resources.opm_version', lambda: '0')
    monkeypatch.setattr('opm.resources._packaged_root', lambda: pkg)

    first = packaged_odd('teipublisher')
    assert first.read_text(encoding='utf-8') == 'old-odd'

    (odd_dir / 'teipublisher.odd').write_text('new-odd', encoding='utf-8')
    second = packaged_odd('teipublisher')
    assert second == first
    assert second.read_text(encoding='utf-8') == 'new-odd'

    dest = ensure_packaged_odd_dir()
    assert dest == cache / 'resources' / '0' / 'odd'


def test_packaged_stock_odds_and_docx_exist() -> None:
    from opm.resources import packaged_default_docx, packaged_odd

    assert packaged_odd('teipublisher').is_file()
    assert packaged_odd('docbook').is_file()
    css = packaged_odd('docbook').with_suffix('.css')
    assert css.is_file()
    docx = packaged_default_docx()
    assert docx is not None and docx.is_file()
