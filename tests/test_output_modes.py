"""The output-mode table (:mod:`opm.output_modes`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opm.config import ProjectConfig
from opm.output_modes import CONFIG_SECTIONS, MODES, RENDER_MODES, output_mode
from opm.runtime.output_functions import ProcessingModelFunctions
from opm.transform import template_arguments


def test_every_mode_names_output_functions_and_settings_that_exist() -> None:
    for mode in MODES.values():
        assert issubclass(mode.output_functions(), ProcessingModelFunctions)
        for setting in mode.context_settings().values():
            assert callable(setting)


def test_json_channel_aliases_cover_every_render_mode() -> None:
    for name, channel in RENDER_MODES.items():
        mode = output_mode(f'json-{name}')
        assert mode.records
        assert mode.channel == name
        assert mode.accepts == ('json', *channel.accepts)
        assert mode.section == 'json'

    # print and epub carry their own web fallback into the JSON view.
    assert output_mode('json-print').accepts == ('json', 'print', 'web')
    assert output_mode('json-epub').accepts == ('json', 'epub', 'web')
    # typst and markdown build on plain, not web, and so do their JSON modes.
    assert output_mode('json-typst').accepts == ('json', 'typst', 'plain')
    assert output_mode('json-markdown').accepts == ('json', 'markdown', 'plain')
    assert not output_mode('typst').records
    assert output_mode('json').channel == 'web'


def test_lookup_normalises_and_defaults_to_web() -> None:
    assert output_mode(' Typst ').name == 'typst'
    assert output_mode(None).name == 'web'
    assert output_mode('').name == 'web'
    with pytest.raises(ValueError, match='Unknown output mode'):
        output_mode('plain')


def test_config_sections_are_the_render_modes_plus_json() -> None:
    assert set(CONFIG_SECTIONS) == {*RENDER_MODES, 'json'}


def test_template_arguments_follow_the_mode(tmp_path: Path) -> None:
    cfg = ProjectConfig(
        document_template=tmp_path / 'web.html.j2',
        print_template=tmp_path / 'print.html.j2',
        typst_template=tmp_path / 'doc.typ.j2',
        document_docx_template=tmp_path / 'style.docx',
    )
    override = tmp_path / 'override'
    assert template_arguments(output_mode('web'), cfg) == {'template_path': cfg.document_template}
    # Print never falls back to the web shell.
    assert template_arguments(output_mode('print'), ProjectConfig()) == {'template_path': None}
    assert template_arguments(output_mode('typst'), cfg, override) == {
        'typst_template_path': override,
    }
    assert template_arguments(output_mode('docx'), cfg) == {'docx_template': cfg.document_docx_template}
    assert template_arguments(output_mode('markdown'), cfg, override) == {}
    assert template_arguments(output_mode('epub'), cfg) == {}


def test_docx_falls_back_to_the_packaged_style_template() -> None:
    from opm.resources import packaged_default_docx

    assert template_arguments(output_mode('docx'), ProjectConfig()) == {
        'docx_template': packaged_default_docx(),
    }


def test_json_channels_read_the_json_config_section(tmp_path: Path) -> None:
    odd = tmp_path / 'debug.odd'
    cfg = ProjectConfig(transform_odds={'json': odd})
    assert cfg.odd_for_type('json-typst') == odd
    assert cfg.odd_for_type('json') == odd
    assert cfg.odd_for_type('typst') is None
