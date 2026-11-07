# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Errors raised while loading, parsing or rendering a template."""

from __future__ import annotations


class TemplateError(Exception):
    """Base class of all template errors.

    Args:
        message: What went wrong.
        name: The template the error occurred in, when known.
        line: The 1-based line in that template, when known.
    """

    def __init__(self, message: str, name: str | None = None, line: int | None = None) -> None:
        self.message = message
        self.name = name
        self.line = line
        super().__init__(self._format())

    def _format(self) -> str:
        where = ''
        if self.name:
            where = self.name if self.line is None else f'{self.name}:{self.line}'
            where += ': '
        return where + self.message


class TemplateSyntaxError(TemplateError):
    """The template is malformed, e.g. a directive is unknown or never closed."""


class TemplateNotFound(TemplateError):
    """A template, include, ``extends`` parent or ``use`` file cannot be found."""


class TemplateRuntimeError(TemplateError):
    """An expression failed while the template was rendered.

    Attributes:
        expression: The XPath expression that failed.
    """

    def __init__(self, message: str, name: str | None = None, line: int | None = None,
                 expression: str | None = None) -> None:
        self.expression = expression
        super().__init__(message, name, line)
