# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Checks on ``scripts/build_tei_data.py``, which builds the downloaded artifact."""

from __future__ import annotations

import importlib.util
import re
from datetime import date
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
TEI = '{http://www.tei-c.org/ns/1.0}'


def _builder():
    """The script, loaded by path: scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location(
        'build_tei_data', ROOT / 'scripts' / 'build_tei_data.py',
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SOURCE = '''<TEI xmlns="http://www.tei-c.org/ns/1.0" version="5.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>The TEI Guidelines</title></titleStmt>
      <editionStmt>
        <edition>P5 <?insert version?>. Last updated on
        <?insert date?>, revision <?insert revision?></edition>
      </editionStmt>
      <publicationStmt><p>Copyright <?insert year?> TEI Consortium.</p></publicationStmt>
    </fileDesc>
  </teiHeader>
  <text><body>
    <div><head>Counts</head>
      <p>There are <?insert totalElements?> elements,
      <?insert totalModelClasses?> model classes,
      <?insert totalAttributeClasses?> attribute classes,
      <?insert totalAttributes?> attributes and
      <?insert totalDataSpec?> datatypes. See <?insert tab-content-models?>.</p>
      <elementSpec ident="p" module="core"><attList><attDef ident="rend"/></attList></elementSpec>
      <elementSpec ident="hi" module="core"><attList><attDef ident="rend"/></attList></elementSpec>
      <classSpec ident="model.pLike" type="model"/>
      <classSpec ident="att.global" type="atts"><attList><attDef ident="xml:id"/></attList></classSpec>
      <dataSpec ident="teidata.word"/>
      <egXML xmlns="http://www.tei-c.org/ns/Examples">
        <elementSpec ident="quoted" module="core"><attList><attDef ident="quotedOnly"/></attList></elementSpec>
      </egXML>
    </div>
  </body></text>
</TEI>'''


def _expanded(**kwargs) -> etree._Element:
    module = _builder()
    root = etree.fromstring(_SOURCE.encode('utf-8'))
    module.expand_insert_pis(root, **kwargs)
    return root


def _text(root: etree._Element, tag: str) -> str:
    el = root.find(f'.//{TEI}{tag}')
    assert el is not None
    return re.sub(r'\s+', ' ', ' '.join(el.itertext())).strip()


def test_release_placeholders_read_as_tei_writes_them() -> None:
    """The edition line and copyright year TEI's own Makefile would have filled."""
    root = _expanded(version='4.12.0', revision='113e933e2', when=date(2026, 7, 28))
    assert _text(root, 'edition') == (
        'P5 Version 4.12.0. Last updated on 28th July 2026, revision 113e933e2'
    )
    assert 'Copyright 2026 TEI Consortium.' in _text(root, 'publicationStmt')


def test_self_counts_come_from_the_assembled_tree() -> None:
    """The counts TEI's prose quotes of itself, examples excluded."""
    root = _expanded(version='4.12.0', revision='abc', when=date(2026, 7, 28))
    prose = root.find(f'.//{TEI}div/{TEI}p')
    assert prose is not None
    body = re.sub(r'\s+', ' ', ' '.join(prose.itertext())).strip()
    assert body.startswith(
        'There are 2 elements, 1 model classes, 1 attribute classes, '
        '2 attributes and 1 datatypes.'
    ), body


def test_a_placeholder_with_no_value_is_left_alone() -> None:
    """Better a visible gap a later build can fill than a silently empty one.

    ``tab-content-models`` is a table TEI generates and we do not, so it stays
    whatever we are given; without release metadata, so do version and date.
    """
    module = _builder()
    root = etree.fromstring(_SOURCE.encode('utf-8'))
    filled, unfilled = module.expand_insert_pis(root)
    assert filled == 5  # the counts, which need nothing passed in
    assert unfilled == [
        'date', 'revision', 'tab-content-models', 'version', 'year',
    ]
    remaining = {
        (pi.text or '').strip() for pi in root.iter(etree.ProcessingInstruction)
    }
    assert 'version' in remaining
    assert _text(root, 'edition') == 'P5 . Last updated on , revision'
