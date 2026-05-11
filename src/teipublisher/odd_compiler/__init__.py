"""Compile TEI Publisher ODD processing models to target language transformation modules."""

from __future__ import annotations

from .codegen import CodeGenerator
from .codegen.python_generator import PythonGenerator
from .parse_odd import load_odd

__all__ = [
    'CodeGenerator',
    'PythonGenerator',
    'compile_odd',
    'load_odd',
]


# Registry of available code generators
_GENERATORS: dict[str, type[CodeGenerator]] = {
    'python': PythonGenerator,
}


def compile_odd(
    odd_path: str,
    *,
    target: str = 'python',
    module_name: str = 'generated_odd',
    output_mode: str = 'web',
) -> str:
    """Compile an ODD file to target language source code.

    Args:
        odd_path: Path to the ODD file
        target: Target language ('python', or future 'rust')
        module_name: Logical name for the generated module
        output_mode: Output channel (web, markdown, print, etc.)

    Returns:
        Generated source code as a string

    Raises:
        ValueError: If target language is not supported
    """
    if target not in _GENERATORS:
        raise ValueError(f"Unsupported target: {target!r}. "
                         f"Supported: {list(_GENERATORS.keys())}")

    parsed = load_odd(odd_path)
    generator = _GENERATORS[target]()
    return generator.generate_module(parsed, module_name, output_mode=output_mode)
