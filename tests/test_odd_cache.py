"""Tests for compile-on-demand ODD module cache."""

from __future__ import annotations

from pathlib import Path

MINIMAL_ODD = '''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>
  <publicationStmt><p/></publicationStmt>
  <sourceDesc><p/></sourceDesc></fileDesc></teiHeader>
  <text><body>
    <schemaSpec ident="tiny" start="doc">
      <elementSpec ident="doc">
        <model behaviour="document"/>
      </elementSpec>
      <elementSpec ident="p">
        <model behaviour="paragraph"/>
      </elementSpec>
    </schemaSpec>
  </body></text>
</TEI>
'''


def _write_odd(path: Path, body: str = MINIMAL_ODD) -> Path:
    path.write_text(body, encoding='utf-8')
    return path


def test_ensure_compiled_module_writes_under_cache_dir(tmp_path: Path, monkeypatch) -> None:
    from opm.odd_cache import cache_key, ensure_compiled_module

    cache = tmp_path / 'cache'
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')

    odd = _write_odd(tmp_path / 'tiny.odd')
    path, fresh = ensure_compiled_module(odd, output_mode='web')

    assert fresh is True
    assert path.is_file()
    assert path.parent == cache / 'modules'
    digest = cache_key(odd, 'web')
    assert path.name == f'tiny-web-{digest[:12]}.py'
    assert 'def transform' in path.read_text(encoding='utf-8')


def test_ensure_compiled_module_cache_hit(tmp_path: Path, monkeypatch) -> None:
    from opm.odd_cache import ensure_compiled_module

    cache = tmp_path / 'cache'
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')

    odd = _write_odd(tmp_path / 'tiny.odd')
    first, fresh1 = ensure_compiled_module(odd, output_mode='web')
    second, fresh2 = ensure_compiled_module(odd, output_mode='web')

    assert fresh1 is True
    assert fresh2 is False
    assert first == second
    assert first.is_file()


def test_changing_odd_content_invalidates_cache(tmp_path: Path, monkeypatch) -> None:
    from opm.odd_cache import cache_key, ensure_compiled_module

    cache = tmp_path / 'cache'
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')

    odd = _write_odd(tmp_path / 'tiny.odd')
    digest1 = cache_key(odd, 'web')
    path1, fresh1 = ensure_compiled_module(odd, output_mode='web')
    assert fresh1 is True

    odd.write_text(
        MINIMAL_ODD.replace('ident="tiny"', 'ident="tiny2"'),
        encoding='utf-8',
    )
    digest2 = cache_key(odd, 'web')
    path2, fresh2 = ensure_compiled_module(odd, output_mode='web')

    assert digest1 != digest2
    assert fresh2 is True
    assert path1 != path2
    assert path2.is_file()
    assert path1.is_file()  # old entry remains until pruned
