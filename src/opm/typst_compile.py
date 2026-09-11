# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compile Typst output to PDF with the ``typst`` command.

``opm transform -t typst`` compiles for a ``.pdf`` output file or ``--preview``.
From Python, pass the Typst output of ``transform_file()`` to
:func:`compile_pdf`.

The source goes to ``typst compile`` on stdin, with the project root set to
the source document's directory. Image paths in the output are copied from the
XML as they are, so they resolve the way they would next to the document;
Typst refuses a path that leaves that directory (``../``). Typst's own
messages, warnings and errors alike, go straight to stderr.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

_INSTALL_HINT = (
    'Install it from https://typst.app/open-source/, or write the Typst source '
    'instead (an output file ending in .typ).'
)


class TypstError(ValueError):
    """``typst compile`` failed; Typst has reported why on stderr."""


def typst_available() -> bool:
    """Whether the ``typst`` command is on ``PATH``."""
    return shutil.which('typst') is not None


def typst_executable() -> str:
    """The ``typst`` command on ``PATH``; ``FileNotFoundError`` when there is none."""
    executable = shutil.which('typst')
    if executable is None:
        raise FileNotFoundError(f'PDF output needs the typst command on PATH. {_INSTALL_HINT}')
    return executable


def compile_pdf(source: str, *, root: Path, open_viewer: bool = False) -> bytes:
    """Compile Typst *source* to PDF and return the PDF.

    *root* is the directory relative paths in *source* resolve against. With
    *open_viewer*, Typst opens the result in the default PDF viewer
    (``--open``). The PDF then goes to a temporary file that is kept, since
    the viewer reads it after Typst has exited.
    """
    command = [typst_executable(), 'compile', '--root', str(root), '-']
    target: Path | None = None
    if open_viewer:
        with tempfile.NamedTemporaryFile(
            suffix='.pdf', prefix='opm-preview-', delete=False,
        ) as handle:
            target = Path(handle.name)
        command += [str(target), '--open']
    else:
        command += ['-', '--format', 'pdf']
    result = subprocess.run(
        command, input=source.encode('utf-8'), stdout=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        raise TypstError(
            f'typst compile failed with exit status {result.returncode}; '
            'see its messages above.',
        )
    return target.read_bytes() if target is not None else result.stdout
