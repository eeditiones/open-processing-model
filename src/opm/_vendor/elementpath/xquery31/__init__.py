#
# Copyright (c), 2018-2026, SISSA (International School for Advanced Studies).
# All rights reserved.
# This file is distributed under the terms of the MIT License.
# See the file 'LICENSE' in the root directory of the present
# distribution, or http://opensource.org/licenses/MIT.
#
# @author Wolfgang Meier <wolfgangmm@gmail.com>
#
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .xquery31_parser import XQuery31Parser
else:
    from ._xquery31_expressions import XQuery31Parser

__all__ = ['XQuery31Parser']
