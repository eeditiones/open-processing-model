"""Frontmatter, context merging and the packaged opm/ layouts."""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import TemplateSyntaxError

from opm.template_frontmatter import merge_deep, split_frontmatter, template_context
from opm.template_rendering import (
    load_template,
    render_document_template,
    template_environment,
)

_DOC = '<html><head></head><body><p>text</p></body></html>'


# ── split_frontmatter ───────────────────────────────────────────────────────


@pytest.mark.parametrize('opening, body', [
    ('---json', '{"title": "T", "n": 1}'),
    ('---', '{"title": "T", "n": 1}'),
    ('---toml', 'title = "T"\nn = 1'),
])
def test_frontmatter_syntaxes(opening: str, body: str) -> None:
    data, rest = split_frontmatter(f'{opening}\n{body}\n---\n<p>{{{{ x }}}}</p>\n')
    assert data == {'title': 'T', 'n': 1}
    assert rest.endswith('#}<p>{{ x }}</p>\n')
    assert rest.count('\n') == body.count('\n') + 4


def test_frontmatter_after_a_comment_keeps_line_numbers() -> None:
    source = '{# SPDX header #}\n---toml\na = 1\nb = 2\n---\nline six\n'
    data, rest = split_frontmatter(source)
    assert data == {'a': 1, 'b': 2}
    assert rest.startswith('{# SPDX header #}')
    assert rest.splitlines()[5].endswith('line six')


def test_source_without_frontmatter_is_unchanged() -> None:
    source = '<p>--- not frontmatter ---</p>\n'
    assert split_frontmatter(source) == ({}, source)


def test_invalid_frontmatter_names_the_template() -> None:
    with pytest.raises(ValueError, match='page.j2: invalid toml'):
        split_frontmatter('---toml\nnot toml\n---\n', 'page.j2')
    with pytest.raises(ValueError, match='unsupported frontmatter syntax'):
        split_frontmatter('---yaml\na: 1\n---\n')


# ── merge_deep ──────────────────────────────────────────────────────────────


def test_merge_scalars_maps_and_arrays() -> None:
    merged = merge_deep(
        {'title': 'a', 'layout': {'before': {'width': '10rem', 'label': 'TOC'}}, 'styles': ['x.css']},
        {'title': 'b', 'layout': {'before': {'width': '20rem'}}, 'styles': ['y.css', 'x.css']},
    )
    assert merged == {
        'title': 'b',
        'layout': {'before': {'width': '20rem', 'label': 'TOC'}},
        'styles': ['x.css', 'y.css'],
    }


def test_merge_arrays_of_maps_by_id() -> None:
    merged = merge_deep(
        {'nav': [{'id': 'home', 'url': 'a'}, {'url': 'b'}]},
        {'nav': [{'id': 'home', 'url': 'other'}, {'url': 'b'}, {'url': 'c'}]},
    )
    assert merged == {'nav': [{'id': 'home', 'url': 'a'}, {'url': 'b'}, {'url': 'c'}]}


def test_merge_replace() -> None:
    base = {'layout': {'before': {'width': '1rem'}, 'after': {'width': '2rem'}}}
    assert merge_deep(base, {'layout': {'$replace': True, 'class': 'x'}}) == {'layout': {'class': 'x'}}
    assert merge_deep(base, {'layout': {'$replace': ['before'], 'before': {'label': 'L'}}}) == {
        'layout': {'before': {'label': 'L'}, 'after': {'width': '2rem'}},
    }


# ── extends chains ──────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding='utf-8')
    return path


def test_context_merges_along_the_extends_chain(tmp_path: Path) -> None:
    _write(tmp_path / 'root.j2', '---toml\nwho = "root"\nlevel = ["root"]\n[box]\na = 1\n---\n'
           '{% block body %}{% endblock %}')
    _write(tmp_path / 'middle.j2', '---json\n{"who": "middle", "level": ["middle"], "box": {"b": 2}}\n---\n'
           '{% extends "root.j2" %}')
    page = _write(tmp_path / 'page.j2', '---toml\nlevel = ["page"]\n---\n{% extends "middle.j2" %}'
                  '{% block body %}{{ context.who }} {{ context.level | join(",") }} '
                  '{{ context.box.a }}{{ context.box.b }} {{ context.project }}{% endblock %}')
    env = template_environment(page)
    context = template_context(env, 'page.j2', {'who': 'config', 'project': 'p', 'level': ['config']})
    assert context['who'] == 'middle'  # frontmatter wins over the project context
    assert context['level'] == ['config', 'root', 'middle', 'page']
    assert load_template(env, page).render(context=context) == 'middle config,root,middle,page 12 p'


def test_frontmatter_reaches_render_document_template(tmp_path: Path) -> None:
    page = _write(tmp_path / 'page.j2', '{# header #}\n---toml\ntitle = "From frontmatter"\n---\n'
                  '{% extends "opm/base.html.j2" %}')
    out = render_document_template(serialized_html=_DOC, template_path=page, odd_css='', parameters={})
    assert '<title>From frontmatter</title>' in out
    assert '<p>text</p>' in out


def test_jinja_errors_keep_their_line_numbers(tmp_path: Path) -> None:
    page = _write(tmp_path / 'page.j2', '---toml\na = 1\n---\n\n{% if %}\n')
    with pytest.raises(TemplateSyntaxError) as info:
        load_template(template_environment(page), page)
    assert info.value.lineno == 5


# ── packaged layouts ────────────────────────────────────────────────────────


def test_layout_renders_only_filled_regions(tmp_path: Path) -> None:
    page = _write(tmp_path / 'page.j2', '{% extends "opm/layout.html.j2" %}'
                  '{% block header %}<h1>Site</h1>{% endblock %}'
                  '{% block after %}<p>Notes</p>{% endblock %}')
    out = render_document_template(serialized_html=_DOC, template_path=page, odd_css='', parameters={})
    assert '<header class="page-header">' in out
    assert '<aside class="after" id="opm-after">' in out
    assert 'class="opm-layout has-after opm-after--stack"' in out
    assert 'class="before"' not in out
    assert 'class="page-footer"' not in out
    # A single page has no css/ directory, so the layout stylesheet is inlined.
    assert 'grid-template-areas' in out
    # No width configured: the stylesheet's default applies.
    assert 'style="--opm-layout' not in out
    assert '<a class="opm-skip" href="#opm-content">Skip to content</a>' in out


def test_layout_settings_from_frontmatter(tmp_path: Path) -> None:
    page = _write(tmp_path / 'page.j2', '---toml\n[layout]\nclass = "wide"\n'
                  '[layout.before]\nwidth = "12rem"\nlabel = "Inhalt"\n---\n'
                  '{% extends "opm/layout.html.j2" %}{% block before %}<nav>toc</nav>{% endblock %}')
    out = render_document_template(serialized_html=_DOC, template_path=page, odd_css='', parameters={})
    assert 'class="opm-layout wide has-before opm-before--drawer" style="--opm-layout-before-width: 12rem;"' in out
    assert '>Inhalt</label>' in out
    assert 'id="opm-before-toggle"' in out


def test_layout_menubar_takes_menu_items_and_slots(tmp_path: Path) -> None:
    page = _write(tmp_path / 'page.j2', '{% extends "opm/layout.html.j2" %}'
                  '{% set work_title = "The Work" %}'
                  '{% block menu_left %}<li class="left">L</li>{% endblock %}'
                  '{% block menu_toggles %}<li class="right">R</li>{% endblock %}'
                  '{% block header %}<div class="band">B</div>{% endblock %}'
                  '{% block before %}<nav>toc</nav>{% endblock %}')
    out = render_document_template(
        serialized_html=_DOC, template_path=page, odd_css='', parameters={},
        context={'menu': {'items': [{'label': 'About', 'url': 'about.html'}]}},
    )
    menubar = out[out.index('<nav class="menubar"'):out.index('</nav>', out.index('<nav class="menubar"'))]
    left, right = menubar.split('</ul>')[:2]
    assert '<span class="logo__title">The Work</span>' in left
    assert left.index('logo__title') < left.index('<a href="about.html">About</a>') < left.index('class="left"')
    # The drawer trigger follows the template's own controls.
    assert right.index('class="right"') < right.index('<li class="trigger">')
    # The header block is a slot after the menubar, not a replacement for it.
    assert out.index('</nav>', out.index('class="menubar"')) < out.index('<div class="band">B</div>')


def test_layout_without_menubar_moves_triggers_to_the_toolbar(tmp_path: Path) -> None:
    page = _write(tmp_path / 'page.j2', '---toml\n[features]\nmenubar = false\n---\n'
                  '{% extends "opm/layout.html.j2" %}{% set work_title = "W" %}'
                  '{% block before %}<nav>toc</nav>{% endblock %}')
    out = render_document_template(serialized_html=_DOC, template_path=page, odd_css='', parameters={})
    assert 'class="menubar"' not in out
    assert 'class="page-header"' not in out
    toolbar = out[out.index('<nav class="toolbar"'):]
    assert '<li class="trigger"><label for="opm-before-toggle"' in toolbar


def test_layout_toolbar_shows_breadcrumbs_and_page_links(tmp_path: Path) -> None:
    page = _write(tmp_path / 'page.j2', '{% extends "opm/layout.html.j2" %}'
                  '{% set chunk = {"prev": "001", "next": "003"} %}'
                  '{% block toolbar %}<li class="tool">T</li>{% endblock %}')

    def render(context: dict | None = None) -> str:
        return render_document_template(
            serialized_html=_DOC, template_path=page, odd_css='', parameters={}, context=context,
            fragments={'breadcrumbs': '<ol><li>Book</li><li>Chapter</li></ol>'},
        )

    out = render()
    assert '<div class="breadcrumb"><ol><li>Book</li><li>Chapter</li></ol></div>' in out
    assert '<li class="tool">T</li>' in out
    # Previous/next links only when the template or project asks for them.
    assert 'rel="prev"' not in out
    out = render({'features': {'toolbar': {'navigation': True}}})
    assert '<a href="001.html" rel="prev">&#8592; Previous</a>' in out
    assert '<a href="003.html" rel="next">Next &#8594;</a>' in out
    out = render({'features': {'toolbar': {'enabled': False}}})
    assert 'class="toolbar"' not in out


def test_project_file_replaces_a_packaged_one(tmp_path: Path) -> None:
    (tmp_path / 'opm').mkdir()
    _write(tmp_path / 'opm' / 'base.html.j2', 'OWN BASE {% block body %}{% endblock %}')
    page = _write(tmp_path / 'page.j2', '{% extends "opm/base.html.j2" %}{% block body %}X{% endblock %}')
    out = render_document_template(serialized_html=_DOC, template_path=page, odd_css='', parameters={})
    assert out == 'OWN BASE X'


def test_missing_parent_is_reported(tmp_path: Path) -> None:
    page = _write(tmp_path / 'page.j2', '{% extends "nowhere.j2" %}')
    with pytest.raises(FileNotFoundError, match='nowhere.j2'):
        render_document_template(serialized_html=_DOC, template_path=page, odd_css='', parameters={})


# ── defaults and opm.toml ───────────────────────────────────────────────────


def test_packaged_defaults_sit_beneath_project_context(tmp_path: Path) -> None:
    page = _write(tmp_path / 'page.j2', '{% extends "opm/layout.html.j2" %}')
    context = template_context(template_environment(page), 'page.j2', {'layout': {'after': {'width': '20rem'}}})
    assert context['layout']['after'] == {'width': '20rem', 'mobile': 'stack', 'label': 'More'}
    assert context['layout']['before'] == {'mobile': 'drawer', 'label': 'Contents'}


def test_layout_width_from_opm_toml(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        '[context.layout.after]\nwidth = "20rem"\n'
        '[transform.web.context.layout.after]\nlabel = "Notes"\n',
        encoding='utf-8',
    )
    context = load_project_config(tmp_path / 'opm.toml').context_for('web')
    # The per-type table adds to [context.layout] rather than replacing it.
    assert context == {'layout': {'after': {'width': '20rem', 'label': 'Notes'}}}

    page = _write(tmp_path / 'page.j2', '{% extends "opm/layout.html.j2" %}{% block after %}x{% endblock %}')
    out = render_document_template(
        serialized_html=_DOC, template_path=page, odd_css='', parameters={}, context=context,
    )
    assert '--opm-layout-after-width: 20rem;' in out


def test_frontmatter_still_wins_over_opm_toml(tmp_path: Path) -> None:
    page = _write(tmp_path / 'page.j2', '---toml\n[layout.after]\nwidth = "9rem"\n---\n'
                  '{% extends "opm/layout.html.j2" %}')
    out = render_document_template(
        serialized_html=_DOC, template_path=page, odd_css='', parameters={},
        context={'layout': {'after': {'width': '20rem'}}},
    )
    assert '--opm-layout-after-width: 9rem;' in out
