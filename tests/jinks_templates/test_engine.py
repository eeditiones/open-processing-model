"""Unit tests for the jinks template engine beyond the ported jinks cases."""

from __future__ import annotations

import pytest
from lxml import etree

from opm.jinks_templates import (
    Environment,
    Markup,
    TemplateNotFound,
    TemplateRuntimeError,
    TemplateSyntaxError,
    merge_deep,
    mode_for,
    split_frontmatter,
)
from opm.jinks_templates.parser import (
    Block,
    CondAttr,
    For,
    If,
    Include,
    Let,
    Template,
    Text,
    Token,
    Value,
    parse,
    tokenize,
)

from .helpers import html_equal, write_files


def render(source: str, context=None, name='t.html', env=None, **variables):
    env = env or Environment()
    return env.from_string(source, name).render(context, **variables)


def squash(s: str) -> str:
    return ''.join(s.split())


# ── tokenizer ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(('source', 'kind', 'attrs'), [
    ('[% if $a %]', 'if', {'expr': '$a'}),
    ('[%if $a%]', 'if', {'expr': '$a'}),
    ('[%   elif   $a  =  1   %]', 'elif', {'expr': '$a = 1'}),
    ('[% else %]', 'else', {}),
    ('[% for $item in $items?* %]', 'for', {'var': '$item', 'expr': '$items?*'}),
    ('[% let $x-y = 1 + 2 %]', 'let', {'var': '$x-y', 'expr': '1 + 2'}),
    ('[% include "a/b.html" %]', 'include', {'target': '"a/b.html"'}),
    ('[% block menu %]', 'block', {'name': 'menu'}),
    ('[% template menu %]', 'template', {'name': 'menu', 'order': ''}),
    ('[% template menu 10 %]', 'template', {'name': 'menu', 'order': '10'}),
    ('[% template! menu %]', 'template', {'name': 'menu', 'overwrite': 'true'}),
    ('[% endtemplate %]', 'endtemplate', {}),
    ('[[ $a?b ]]', 'value', {'expr': '$a?b'}),
    (' class="![[ $c ]]"', 'cond-attr', {'name': 'class', 'expr': '$c'}),
])
def test_tokenize_directives(source, kind, attrs):
    tokens = tokenize(source)
    assert len(tokens) == 1
    token = tokens[0]
    assert isinstance(token, Token)
    assert token.kind == kind
    assert token.attrs == attrs


def test_tokenize_text_comments_and_raw():
    assert tokenize('a[# note\n spanning lines #]b[% raw %] [[ x ]]  [% if %] [% endraw %]c') == [
        'a', 'b', '[[ x ]] [% if %]', 'c']


def test_unknown_end_tag_is_a_syntax_error():
    with pytest.raises(TemplateSyntaxError, match='unknown directive'):
        parse('[% endfoo %]')


# ── parser ───────────────────────────────────────────────────────────────────


def test_parse_if_elif_else_chain():
    (node,) = parse('[% if $a %]A[% elif $b %]B[% elif $c %]C[% else %]D[% endif %]')
    assert isinstance(node, If) and node.expr == '$a' and node.body == (Text('A'),)
    (elif1,) = node.orelse
    assert elif1.expr == '$b' and elif1.body == (Text('B'),)
    (elif2,) = elif1.orelse
    assert elif2.expr == '$c' and elif2.orelse == (Text('D'),)


def test_parse_deep_nesting():
    (outer,) = parse('[% for $a in 1 %][% let $b = 2 %][% if $b %][% for $c in 3 %]'
                     '[[ $c ]][% endfor %][% endif %][% endlet %][% endfor %]')
    assert isinstance(outer, For)
    (let,) = outer.body
    assert isinstance(let, Let)
    (cond,) = let.body
    (inner,) = cond.body
    assert isinstance(inner, For) and isinstance(inner.body[0], Value)


def test_parse_short_form_value():
    assert parse('[[ title ]]') == (Value('$title', parse('[[ title ]]')[0].pos),)
    assert parse('[[ $title ]]')[0].expr == '$title'
    assert parse('[[ string-join($a) ]]')[0].expr == 'string-join($a)'


def test_parse_blocks_and_templates():
    nodes = parse('[% block a %]x[% endblock %][% template a 2 %]y[% endtemplate %]'
                  '[% template! a %]z[% endtemplate %]')
    assert isinstance(nodes[0], Block) and nodes[0].body == (Text('x'),)
    assert isinstance(nodes[1], Template) and nodes[1].order == '2' and not nodes[1].overwrite
    assert nodes[2].overwrite


def test_parse_dynamic_include():
    (node,) = parse('[% include $path %]')
    assert isinstance(node, Include) and node.target == '$path'


@pytest.mark.parametrize(('source', 'message'), [
    ('[% for $a in 1 %]', 'Missing endfor'),
    ('[% let $a = 1 %]', 'Missing endlet'),
    ('[% if 1 %][% else %]', 'Missing endif'),
    ('[% block a %]', 'Missing endblock'),
    ('[% template a %]', 'Missing endtemplate'),
    ('[% endif %]', 'unexpected'),
    ('x[% else %]', 'outside'),
    ('[% for $a in 1 %][% endif %][% endfor %]', 'unexpected'),
])
def test_parse_errors(source, message):
    with pytest.raises(TemplateSyntaxError, match=message):
        parse(source)


def test_error_line_numbers():
    with pytest.raises(TemplateSyntaxError) as info:
        Environment().from_string('---json\n{"a": 1}\n---\n<p>\n[% if $a %]\n</p>', 'p.html')
    assert info.value.name == 'p.html'
    assert info.value.line == 5


def test_cond_attr_moved_into_tag():
    nodes = parse('<a href="x" class="![[ $c ]]" id="y">t</a>')
    assert [type(n) for n in nodes] == [Text, Text, CondAttr, Text, Text]
    assert ''.join(n.text for n in nodes[:2]) == '<a href="x" id="y"'
    assert nodes[3].text == '>'


# ── values ───────────────────────────────────────────────────────────────────


def test_value_kinds_in_html_mode():
    ctx = {'m': {'a': [1, 2], 'b': 'x'}, 'arr': [1, [2, 3]], 'n': None, 'b': True}
    assert render('[[ $m ]]', ctx) == '{&quot;a&quot;:[1,2],&quot;b&quot;:&quot;x&quot;}'
    assert render('[[ $arr ]]', ctx) == '1 2 3'
    assert render('[[ (1, "a", 2.5) ]]', ctx) == '1 a 2.5'
    assert render('[[ 1 ]][[ 2 ]]', ctx) == '12'
    assert render('[[ $n ]]|[[ $b ]]', ctx) == '|true'
    assert render('[[ $context?missing ]]', ctx) == ''


def test_undefined_short_form_variable_is_an_error():
    with pytest.raises(TemplateRuntimeError, match='author'):
        render('[[ $author ]]')


def test_invalid_expression_is_reported():
    with pytest.raises(TemplateRuntimeError, match='invalid expression'):
        render('[[ 1 + ]]')


def test_context_and_top_level_variables():
    ctx = {'theme': {'fonts': {'content': 'serif'}}, 'odd key': 1}
    assert render('[[ $context?theme?fonts?content ]] [[ $theme?fonts?content ]]', ctx) == 'serif serif'
    assert render('[[ $context?("odd key") ]]', ctx) == '1'


def test_variables_win_over_context_and_frontmatter():
    source = '---json\n{"title": "fm"}\n---\n[[ $title ]]/[[ $context?title ]]'
    assert render(source, {'title': 'ctx'}, title='var') == '\nvar/var'
    assert render(source, {'title': 'ctx'}) == '\nfm/fm'


def test_nodes_in_html_and_text_mode():
    doc = etree.fromstring('<doc><p n="1">a &amp; <b>b</b></p></doc>')
    ctx = {'doc': doc}
    assert render('[[ $doc/p ]]', ctx) == '<p n="1">a &amp; <b>b</b></p>'
    assert render('[[ $doc/p/text() ]]|[[ $doc/p/@n ]]', ctx) == 'a &amp; |1'
    assert render('[[ $doc/p ]]', ctx, name='t.txt') == 'a & b'


def test_namespaces_from_frontmatter():
    doc = etree.fromstring('<TEI xmlns="http://www.tei-c.org/ns/1.0"><title>T</title></TEI>')
    source = ('---json\n{"templating": {"namespaces": {"tei": "http://www.tei-c.org/ns/1.0"}}}\n---\n'
              '[[ $doc//tei:title/string() ]]')
    # As in jinks, the line break after the frontmatter stays.
    assert render(source, {'doc': doc}) == '\nT'


def test_xpath31_features():
    ctx = {'items': [{'id': 'a', 'n': 1}, {'id': 'b', 'n': 2}]}
    assert render('[% for $i in $items?* %][[ $i?id ]][% endfor %]', ctx) == 'ab'
    assert render('[[ sum($items?*?n) ]]', ctx) == '3'
    assert render('[[ if (map:contains($context, "items")) then "y" else "n" ]]', ctx) == 'y'
    assert render('[[ array:size($items) ]]', ctx) == '2'
    assert render('[[ string-join(for $i in $items?* return $i?id, ",") ]]', ctx) == 'a,b'


def test_let_binds_sequences():
    assert render('[% let $s = (1, 2, 3) %][[ count($s) ]]:[[ $s ]][% endlet %]') == '3:1 2 3'
    assert render('[% let $e = () %][[ empty($e) ]][% endlet %]') == 'true'


def test_for_scoping_restores_variables():
    assert render('[% for $x in (1, 2) %][[ $x ]][% endfor %][[ $x ]]', {'x': 'outer'}) == '12outer'


def test_dataclass_values():
    from dataclasses import dataclass

    @dataclass
    class Chunk:
        id: str
        prev: str | None = None

    assert render('[[ $chunk?id ]]|[[ empty($chunk?prev) ]]', chunk=Chunk('c1')) == 'c1|true'


# ── modes ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(('name', 'mode'), [
    ('page.html', 'html'), ('page.HTM', 'html'), ('a/b.xhtml', 'html'), ('expath-pkg.xml', 'html'),
    ('icon.svg', 'html'), ('api.tpl.html', 'html'), ('page.html.tpl', 'html'),
    ('doc.typ', 'text'), ('style.css', 'text'), ('README.md', 'text'), ('x.js.jinks', 'text'),
    ('Makefile', None), ('<string>', None), (None, None),
])
def test_mode_for(name, mode):
    assert mode_for(name) == mode


def test_escaping_only_in_html_mode():
    ctx = {'s': 'a < b & "c"'}
    assert render('[[ $s ]]', ctx) == 'a &lt; b &amp; &quot;c&quot;'
    assert render('[[ $s ]]', ctx, name='t.typ') == 'a < b & "c"'
    assert render('[[ $s ]]', {**ctx, 'templating': {'mode': 'text'}}) == 'a < b & "c"'
    assert render('[[ $s ]]', {**ctx, 'templating': {'mode': 'html'}}, name='t.css') == \
        'a &lt; b &amp; &quot;c&quot;'
    assert render('[[ $s ]]', ctx, name='<string>', env=Environment(mode='html')) == \
        'a &lt; b &amp; &quot;c&quot;'


def test_markup_is_never_escaped():
    m = Markup('<b>x</b>')
    ctx = {'m': m, 'map': {'k': m}, 'list': [m, '<i>']}
    assert render('[[ $m ]]', ctx) == '<b>x</b>'
    assert render('[[ $map?k ]]', ctx) == '<b>x</b>'
    assert render('[% for $x in $list?* %][[ $x ]][% endfor %]', ctx) == '<b>x</b>&lt;i&gt;'
    # Anything computed from it is an ordinary string again.
    assert render('[[ concat($m, "") ]]', ctx) == '&lt;b&gt;x&lt;/b&gt;'


def test_conditional_attribute_escaping_and_values():
    assert render('<a title="![[ $t ]]"/>', {'t': 'a"b<c&d'}) == '<a title="a&quot;b&lt;c&amp;d"/>'
    assert render('<a title="![[ $t ]]"/>', {'t': ('x', 'y')}) == '<a title="x y"/>'
    assert render('<a title="![[ $t ]]"/>', {'t': 0}) == '<a/>'
    assert render('<a title="![[ $t ]]"/>', {'t': False}) == '<a/>'
    assert render('<a title="![[ $t ]]"/>', {'t': None}) == '<a/>'
    # The whitespace before the closing bracket stays, as in jinks.
    assert render('<a title="![[ $t ]]" >x</a>', {'t': 'v'}) == '<a  title="v">x</a>'


def test_include_follows_the_mode_of_the_page(tmp_path):
    write_files(tmp_path, {'part.css': 'a::before { content: "[[ $s ]]" }'})
    env = Environment(tmp_path)
    assert env.from_string('<style>[% include "part.css" %]</style>', 'p.html').render({'s': '>'}) == \
        '<style>a::before { content: "&gt;" }</style>'
    assert env.from_string('[% include "part.css" %]', 'p.typ').render({'s': '>'}) == \
        'a::before { content: ">" }'


# ── frontmatter and merging ──────────────────────────────────────────────────


def test_frontmatter_syntaxes():
    assert split_frontmatter('---json\n{"a": 1}\n---\nrest').data == {'a': 1}
    assert split_frontmatter('---\n{"a": 1}\n---\nrest').data == {'a': 1}
    assert split_frontmatter('---toml\na = 1\n[b]\nc = "d"\n---\nrest').data == {'a': 1, 'b': {'c': 'd'}}
    fm = split_frontmatter('---json\n{"a": 1}\n---\nrest')
    assert fm.source == '\nrest'
    with pytest.raises(TemplateSyntaxError, match='unsupported'):
        split_frontmatter('---yaml\na: 1\n---\n')
    with pytest.raises(TemplateSyntaxError, match='invalid json'):
        split_frontmatter('---json\n{a: 1}\n---\n')


def test_frontmatter_after_root_element_and_comment():
    fm = split_frontmatter('[# SPDX #]\n<article>\n  ---json\n  {"a": 1}\n  ---\n  <h1/>\n</article>')
    assert fm.data == {'a': 1}
    assert fm.source == '[# SPDX #]\n<article>\n  <h1/>\n</article>'
    assert split_frontmatter('<p>a</p>\n---\n{"a": 1}\n---\n').data == {}


def test_merge_deep():
    assert merge_deep({'a': {'x': 1, 'y': 2}}, {'a': {'y': 3}}) == {'a': {'x': 1, 'y': 3}}
    assert merge_deep({'a': {'x': 1, 'y': 2}}, {'a': {'$replace': True, 'y': 3}}) == {'a': {'y': 3}}
    assert merge_deep({'a': {'x': {'p': 1}, 'y': {'q': 1}}},
                      {'a': {'$replace': ['x'], 'x': {'r': 2}, 'y': {'s': 2}}}) == \
        {'a': {'x': {'r': 2}, 'y': {'q': 1, 's': 2}}}
    assert merge_deep({'l': [1, 2]}, {'l': [2, 3]}) == {'l': [1, 2, 3]}
    assert merge_deep({'l': [{'id': 'a', 'v': 1}]}, {'l': [{'id': 'a', 'v': 2}, {'id': 'b'}]}) == \
        {'l': [{'id': 'a', 'v': 1}, {'id': 'b'}]}
    assert merge_deep({'l': [{'v': 1}]}, {'l': [{'v': 1}, {'v': 2}]}) == {'l': [{'v': 1}, {'v': 2}]}
    assert merge_deep(None, {'a': 1}) == {'a': 1}


# ── inheritance ──────────────────────────────────────────────────────────────


def env_with(tmp_path, files):
    return Environment(write_files(tmp_path, files))


def test_overwrite_wins_over_all_levels(tmp_path):
    env = env_with(tmp_path, {
        'root.html': '<ul>[% block menu %][% endblock %]</ul>[% block content %][% endblock %]',
        'mid.html': '---json\n{"templating": {"extends": "root.html"}}\n---\n'
                    '[% template menu %]<li>mid</li>[% endtemplate %][% block content %][% endblock %]',
        'extra.html': '[% template menu %]<li>extra</li>[% endtemplate %]',
    })
    child = ('---json\n{"templating": {"extends": "mid.html", "use": ["extra.html"]}}\n---\n'
             '[% template! menu %]<li>only</li>[% endtemplate %]<p/>')
    assert squash(env.from_string(child, 'c.html').render()) == '<ul><li>only</li></ul><p/>'


def test_order_mixed_with_unordered(tmp_path):
    env = env_with(tmp_path, {
        'root.html': '[% block m %][% endblock %]|[% block content %][% endblock %]',
        'u1.html': '[% template m %]u1[% endtemplate %][% template m 5 %]o5[% endtemplate %]',
        'u2.html': '[% template m %]u2[% endtemplate %]',
    })
    child = ('---json\n{"templating": {"extends": "root.html", "use": ["u1.html", "u2.html"]}}\n---\n'
             '[% template m 1 %]o1[% endtemplate %][% template m %]c[% endtemplate %]x')
    assert env.from_string(child, 'c.html').render() == 'o1o5cu2u1|\nx'


def test_use_from_context(tmp_path):
    env = env_with(tmp_path, {
        'page.html': '<aside>[% block before %][% endblock %]</aside>',
        'iiif.html': '<template>[% template before %]<pb-iiif/>[% endtemplate %]</template>',
    })
    tpl = env.get_template('page.html')
    assert tpl.render({'templating': {'use': ['iiif.html']}}) == '<aside><pb-iiif/></aside>'
    assert tpl.render() == '<aside></aside>'


def test_strip_root_and_template_unwrapping(tmp_path):
    env = env_with(tmp_path, {'root.html': '<main>[% block content %][% endblock %]</main>'})
    child = '---json\n{"templating": {"extends": "root.html"}}\n---\n<template>\n  <p>x</p>\n</template>'
    assert squash(env.from_string(child, 'c.html').render()) == '<main><p>x</p></main>'
    stripped = ('<div class="wrapper">\n---json\n{"templating": {"extends": "root.html", '
                '"strip-root": true}}\n---\n<p>x</p><p>y</p></div>')
    assert squash(env.from_string(stripped, 'c.html').render()) == '<main><p>x</p><p>y</p></main>'
    kept = '---json\n{"templating": {"extends": "root.html"}}\n---\n<div><p>x</p></div>'
    assert squash(env.from_string(kept, 'c.html').render()) == '<main><div><p>x</p></div></main>'
    two = '---json\n{"templating": {"extends": "root.html", "strip-root": true}}\n---\n<p>x</p><p>y</p>'
    assert squash(env.from_string(two, 'c.html').render()) == '<main><p>x</p><p>y</p></main>'


def test_strip_root_keeps_text_mode_content(tmp_path):
    env = env_with(tmp_path, {'root.typ': '#show: doc => [% block content %][% endblock %]'})
    child = '---json\n{"templating": {"extends": "root.typ"}}\n---\n<template>x</template>'
    assert env.from_string(child, 'c.typ').render() == '#show: doc => \n<template>x</template>'


def test_blocks_inside_static_includes(tmp_path):
    env = env_with(tmp_path, {
        'root.html': '[% include "nav.html" %]|[% block content %][% endblock %]',
        'nav.html': '<nav>[% block links %]default[% endblock %]</nav>',
    })
    child = ('---json\n{"templating": {"extends": "root.html"}}\n---\n'
             '[% template links %]<a/>[% endtemplate %]body')
    assert env.from_string(child, 'c.html').render() == '<nav><a/></nav>|\nbody'
    assert env.get_template('root.html').render() == '<nav>default</nav>|'


def test_three_levels_with_block_redefined_midway(tmp_path):
    env = env_with(tmp_path, {
        'a.html': '<a>[% block content %][% endblock %]<f>[% block footer %]fa[% endblock %]</f></a>',
        'b.html': '---json\n{"templating": {"extends": "a.html"}}\n---\n'
                  '<b>[% block content %][% endblock %]</b>[% template footer %]fb[% endtemplate %]',
    })
    child = ('---json\n{"templating": {"extends": "b.html"}}\n---\n'
             '[% template footer %]fc[% endtemplate %]<c/>')
    assert squash(env.from_string(child, 'c.html').render()) == '<a><b><c/></b><f>fbfc</f></a>'


def test_frontmatter_child_overrides_parent(tmp_path):
    env = env_with(tmp_path, {
        'a.html': '---json\n{"title": "a", "layout": {"w": 1, "h": 2}}\n---\n'
                  '[[ $title ]] [[ $layout?w ]] [[ $layout?h ]] [% block content %][% endblock %]',
    })
    child = '---json\n{"templating": {"extends": "a.html"}, "title": "c", "layout": {"w": 9}}\n---\nx'
    tpl = env.from_string(child, 'c.html')
    assert tpl.render({'title': 'ctx'}) == '\nc 9 2 \nx'
    assert tpl.context({'title': 'ctx'})['title'] == 'c'


def test_dynamic_include_with_blocks_and_context(tmp_path):
    env = env_with(tmp_path, {
        'root.html': '[% include $part %]|[% block content %][% endblock %]',
        'p1.html': '<p1>[[ $who ]][% block extra %][% endblock %]</p1>',
    })
    child = ('---json\n{"templating": {"extends": "root.html"}}\n---\n'
             '[% template extra %]+[% endtemplate %]body')
    out = env.from_string(child, 'c.html').render({'part': 'p1.html', 'who': 'me'})
    assert out == '<p1>me+</p1>|\nbody'
    with pytest.raises(TemplateNotFound):
        env.from_string('[% include $part %]', 'c.html').render({'part': 'nope.html'})


def test_missing_parent_and_use(tmp_path):
    env = env_with(tmp_path, {})
    with pytest.raises(TemplateNotFound, match='parent.html'):
        env.from_string('---json\n{"templating": {"extends": "parent.html"}}\n---\nx', 'c.html')
    with pytest.raises(TemplateNotFound, match='u.html'):
        env.from_string('---json\n{"templating": {"use": ["u.html"]}}\n---\nx', 'c.html').render()


def test_cycles_are_reported(tmp_path):
    env = env_with(tmp_path, {
        'a.html': '---json\n{"templating": {"extends": "b.html"}}\n---\n',
        'b.html': '---json\n{"templating": {"extends": "a.html"}}\n---\n',
        'i.html': '[% include "j.html" %]',
        'j.html': '[% include "i.html" %]',
    })
    with pytest.raises(TemplateSyntaxError, match='cycle'):
        env.get_template('a.html')
    with pytest.raises(TemplateSyntaxError, match='includes itself'):
        env.get_template('i.html')


def test_no_resolver():
    with pytest.raises(TemplateNotFound, match='no resolver'):
        render('[% include "x.html" %]')


def test_resolver_search_order(tmp_path):
    write_files(tmp_path / 'project', {'a.html': 'project'})
    write_files(tmp_path / 'packaged', {'a.html': 'packaged', 'b.html': 'b'})
    write_files(tmp_path, {'secret.html': 'secret'})
    env = Environment([tmp_path / 'project', tmp_path / 'packaged'])
    assert env.get_template('a.html').render() == 'project'
    assert env.get_template('b.html').render() == 'b'
    with pytest.raises(TemplateNotFound):
        env.get_template('../secret.html')
    with pytest.raises(TemplateNotFound):
        env.get_template(str(tmp_path / 'packaged' / 'a.html'))


def test_template_outside_inheritance_stays_in_place():
    assert render('a[% template x %]b[% endtemplate %]c') == 'abc'


# ── caching and functions ────────────────────────────────────────────────────


def test_expressions_compiled_once(tmp_path):
    env = env_with(tmp_path, {'p.html': '[% for $i in $items?* %][[ $i ]][% endfor %][[ $t ]]'})
    tpl = env.get_template('p.html')
    assert tpl.render({'items': [1, 2], 't': 'a'}) == '12a'
    count = env.compile_count
    assert env.get_template('p.html') is tpl
    assert tpl.render({'items': [3], 't': 'b'}) == '3b'
    assert env.compile_count == count


def test_registered_functions():
    env = Environment(namespaces={'x': 'urn:x'},
                      functions={'x:upper': lambda s: str(s).upper(),
                                 'x:items': lambda: ['a', 'b'],
                                 'x:el': lambda: etree.fromstring('<e>t</e>')})
    assert render('[[ x:upper("a") ]] [[ x:items() ]] [[ x:el() ]] [[ x:el()/text() ]]', env=env) == \
        'A a b <e>t</e> t'


def test_custom_conversion_hook():
    class Thing:
        pass

    env = Environment(convert=lambda value: 'thing' if isinstance(value, Thing) else str(value))
    assert render('[[ $t ]]', {'t': Thing()}, env=env) == 'thing'


def test_html_equal_helper():
    assert html_equal('<p> a  <b>b</b>\n</p>', '<p>a <b>b</b></p>')
    assert not html_equal('<p>a</p>', '<p>b</p>')


def test_child_with_only_templates_keeps_default_content(tmp_path):
    env = env_with(tmp_path, {
        'root.html': '<m>[% block content %]default[% endblock %]</m>[% block x %][% endblock %]',
    })
    only_templates = ('---json\n{"templating": {"extends": "root.html"}}\n---\n'
                      '[% template x %]X[% endtemplate %]\n  \n')
    assert env.from_string(only_templates, 'c.html').render() == '<m>default</m>X'
    with_content = '---json\n{"templating": {"extends": "root.html"}}\n---\nmine'
    assert env.from_string(with_content, 'c.html').render() == '<m>\nmine</m>'
