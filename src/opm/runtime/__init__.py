# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TEI Publisher processing model runtime.

This package provides the runtime support for ODD-generated transformation modules:

- XPath evaluation with caching
- apply/apply_children dispatch
- Output format implementations (HTML, Markdown)
- XPath extension support
"""

from __future__ import annotations

from .pm_runtime import (
    apply,
    apply_children,
    apply_template_param_value,
    clear_xpath_document_cache,
    inject_cached_footnotes,
    make_context,
    ns,
    resolve_context_element,
    serialize,
    tag,
    xpath_count,
    xpath_select_nodes,
    xpath_test,
)
from .output_functions import (
    ProcessingModelFunctions,
    child_nodes,
    normalize,
    reset_counters,
)
from .docx_output_functions import DocxOutputFunctions
from .html_output_functions import HtmlOutputFunctions
from .markdown_output_functions import MarkdownOutputFunctions
from .print_output_functions import PrintOutputFunctions
from .epub_output_functions import EpubOutputFunctions
from .typst_output_functions import TypstOutputFunctions

__all__ = [
    # pm_runtime
    'apply',
    'apply_children',
    'apply_template_param_value',
    'clear_xpath_document_cache',
    'inject_cached_footnotes',
    'make_context',
    'ns',
    'resolve_context_element',
    'serialize',
    'tag',
    'xpath_count',
    'xpath_select_nodes',
    'xpath_test',
    # output_functions
    'ProcessingModelFunctions',
    'child_nodes',
    'normalize',
    'reset_counters',
    # format implementations
    'DocxOutputFunctions',
    'HtmlOutputFunctions',
    'MarkdownOutputFunctions',
    'PrintOutputFunctions',
    'EpubOutputFunctions',
    'TypstOutputFunctions',
]
