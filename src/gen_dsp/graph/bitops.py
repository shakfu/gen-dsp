"""Shared scalar semantics for gen~ bitwise operators.

gen~ bitwise operators act on the integer value of their float operands. To keep
the three independent Python evaluators (``simulate``, constant-fold in
``optimize``, and the transpile differential evaluator) and the emitted C++ in
``compile/nodes.py`` in lock-step, the scalar semantics live here once. Operands
are cast to a 32-bit signed integer exactly as C's ``(int32_t)`` cast does:
truncate toward zero, then keep the low 32 bits as two's complement.

This module imports nothing from the package so it can be used from
``optimize`` without the import cycle that ``compile`` participates in.

Parity caveat: gen~'s exact ``bitshift`` direction convention is not verified
against Max here (CI has no Max). The convention below -- non-negative shift
counts shift left, negative shift right, amount masked to ``[0, 31]`` -- is
applied consistently across all emitters so the differential harness stays
meaningful.
"""

from __future__ import annotations


def _i32(x: float) -> int:
    """Cast a float to a 32-bit signed integer with C ``(int32_t)`` semantics."""
    v = int(x) & 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def _eval_bitop(op: str, a: float, b: float) -> float:
    """Evaluate a binary gen~ bitwise op on float operands."""
    ia, ib = _i32(a), _i32(b)
    if op == "bitand":
        return float(_i32(ia & ib))
    if op == "bitor":
        return float(_i32(ia | ib))
    if op == "bitxor":
        return float(_i32(ia ^ ib))
    if op == "bitshift":
        sh = int(b)
        if sh >= 0:
            return float(_i32(ia << (sh & 31)))
        return float(_i32(ia >> ((-sh) & 31)))
    raise ValueError(f"unknown bitwise op: {op!r}")


def _eval_bitnot(a: float) -> float:
    """Evaluate the unary gen~ ``bitnot`` op on a float operand."""
    return float(_i32(~_i32(a)))
