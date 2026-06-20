"""Shared primitives for C++ code generation."""

from __future__ import annotations

import re
from typing import Callable


_Writer = Callable[[str], None]


_C_ID_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _to_pascal(name: str) -> str:
    """Convert underscore_name to PascalCase."""
    return "".join(part.capitalize() for part in name.split("_"))


def _float_lit(v: float) -> str:
    """Format a float as a C literal with 'f' suffix."""
    s = repr(v)
    if "." not in s and "e" not in s and "E" not in s:
        s += ".0"
    return s + "f"


def _emit_ref(ref: str | float, input_ids: set[str], param_names: set[str]) -> str:
    """Emit a C expression for a Ref value."""
    if isinstance(ref, float):
        return _float_lit(ref)
    if ref in input_ids:
        return ref + "[i]"
    # param names and node IDs are both local C variables
    return ref
