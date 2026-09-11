# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TEI Publisher processing model runtime.

This package provides the runtime support for ODD-generated transformation modules:

- the render context passed to every output function
- XPath evaluation through a per-document environment
- apply/apply_children dispatch
- Output format implementations (HTML, Markdown, …)
- XPath extension support
"""

from __future__ import annotations

from .pm_runtime import (
    apply,
    apply_children,
    apply_template_param_value,
    inject_cached_footnotes,
    ns,
    serialize,
    tag,
)
from .output_functions import (
    ProcessingModelFunctions,
    child_nodes,
    normalize,
)
from .docx_output_functions import DocxOutputFunctions
from .html_output_functions import HtmlOutputFunctions
from .markdown_output_functions import MarkdownOutputFunctions
from .print_output_functions import PrintOutputFunctions
from .epub_output_functions import EpubOutputFunctions
from .typst_output_functions import TypstOutputFunctions
from .context import RenderContext, RunState
from .xpath_diagnostics import XPathErrorLog, XPathFailure, collect_xpath_errors
from .xpath_env import XPathEnvironment

__all__ = [
    # pm_runtime
    'apply',
    'apply_children',
    'apply_template_param_value',
    'inject_cached_footnotes',
    'ns',
    'serialize',
    'tag',
    # output_functions
    'ProcessingModelFunctions',
    'child_nodes',
    'normalize',
    # format implementations
    'DocxOutputFunctions',
    'HtmlOutputFunctions',
    'MarkdownOutputFunctions',
    'PrintOutputFunctions',
    'EpubOutputFunctions',
    'TypstOutputFunctions',
    # context
    'RenderContext',
    'RunState',
    'XPathEnvironment',
    # xpath_diagnostics
    'XPathErrorLog',
    'XPathFailure',
    'collect_xpath_errors',
]
