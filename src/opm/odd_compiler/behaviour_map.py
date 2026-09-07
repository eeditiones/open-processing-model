# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Map ODD @behaviour names to :class:`~opm.output_functions.ProcessingModelFunctions` method names."""

from __future__ import annotations

# TEI processing model behaviour ident -> Python method name on ProcessingModelFunctions subclasses
BEHAVIOUR_METHOD = {
    'paragraph': 'paragraph',
    'pass-through': 'pass_through',
    'inline': 'inline',
    'alternate': 'alternate',
    'omit': 'omit',
    'note': 'note',
    'anchor': 'anchor',
    'block': 'block',
    'index': 'index',
    'list': 'list',
    'listItem': 'list_item',
    'break': 'break_',
    'cell': 'cell',
    'cit': 'cit',
    'section': 'section',
    'graphic': 'graphic',
    'webcomponent': 'webcomponent',
    'glyph': 'glyph',
    'heading': 'heading',
    'figure': 'figure',
    'link': 'link',
    'table': 'table',
    'document': 'document',
    'body': 'body',
    'metadata': 'metadata',
    'row': 'row',
    'text': 'text',
    'title': 'title',
    'match': 'match',
    'template': 'template',
    'code': 'code',
    'code-inline': 'code_inline',
}


def method_for_behaviour(behaviour: str) -> str:
    if behaviour not in BEHAVIOUR_METHOD:
        raise KeyError(f'Unknown behaviour: {behaviour!r}')
    return BEHAVIOUR_METHOD[behaviour]
