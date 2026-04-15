"""Compile TEI Publisher ODD processing models to Python transformation modules."""

from __future__ import annotations

from .emit_python import compile_odd_to_python, generate_python_module

__all__ = ['compile_odd_to_python', 'generate_python_module']
