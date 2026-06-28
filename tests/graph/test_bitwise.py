"""Tests for gen~ bitwise operators (bitand/bitor/bitxor/bitshift/bitnot)."""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")

from gen_dsp.graph.bitops import _eval_bitnot, _eval_bitop, _i32  # noqa: E402
from gen_dsp.graph.compile import compile_graph  # noqa: E402
from gen_dsp.graph.models import (  # noqa: E402
    AudioInput,
    AudioOutput,
    BinOp,
    Graph,
    UnaryOp,
)
from gen_dsp.graph.optimize import constant_fold  # noqa: E402


# ---------------------------------------------------------------------------
# Shared scalar semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "x,expected",
    [
        (0.0, 0),
        (5.0, 5),
        (-1.0, -1),
        (-2.7, -2),  # truncates toward zero, like C (int32_t)
        (2.9, 2),
        (float(2**31), -(2**31)),  # wraps modulo 2**32
        (float(2**32 + 7), 7),
    ],
)
def test_i32_matches_c_cast(x: float, expected: int) -> None:
    assert _i32(x) == expected


@pytest.mark.parametrize(
    "op,a,b,expected",
    [
        ("bitand", 12.0, 10.0, 8.0),
        ("bitor", 12.0, 10.0, 14.0),
        ("bitxor", 12.0, 10.0, 6.0),
        ("bitand", -1.0, 5.0, 5.0),  # -1 is all ones
        ("bitor", -2.0, 1.0, -1.0),
        ("bitxor", -1.0, -1.0, 0.0),
        ("bitshift", 1.0, 4.0, 16.0),  # non-negative -> left shift
        ("bitshift", 16.0, -2.0, 4.0),  # negative -> right shift
        ("bitshift", -8.0, -1.0, -4.0),  # arithmetic right shift keeps sign
    ],
)
def test_eval_bitop(op: str, a: float, b: float, expected: float) -> None:
    assert _eval_bitop(op, a, b) == expected


@pytest.mark.parametrize(
    "a,expected",
    [(0.0, -1.0), (5.0, -6.0), (-1.0, 0.0)],
)
def test_eval_bitnot(a: float, expected: float) -> None:
    assert _eval_bitnot(a) == expected


def test_eval_bitop_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown bitwise op"):
        _eval_bitop("bogus", 1.0, 2.0)


# ---------------------------------------------------------------------------
# Model acceptance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("op", ["bitand", "bitor", "bitxor", "bitshift"])
def test_binop_accepts_bitwise(op: str) -> None:
    node = BinOp(id="n", op=op, a="x", b="y")
    assert node.op == op


def test_unaryop_accepts_bitnot() -> None:
    node = UnaryOp(id="n", op="bitnot", a="x")
    assert node.op == "bitnot"


# ---------------------------------------------------------------------------
# Constant folding
# ---------------------------------------------------------------------------


def _const_graph(node: BinOp | UnaryOp) -> Graph:
    return Graph(name="f", nodes=[node], outputs=[AudioOutput(id="out1", source="o")])


@pytest.mark.parametrize(
    "node,expected",
    [
        (BinOp(id="o", op="bitand", a=12.0, b=10.0), 8.0),
        (BinOp(id="o", op="bitshift", a=3.0, b=2.0), 12.0),
        (UnaryOp(id="o", op="bitnot", a=5.0), -6.0),
    ],
)
def test_bitwise_constant_folds(node: BinOp | UnaryOp, expected: float) -> None:
    folded = constant_fold(_const_graph(node))
    assert folded.nodes[0].op == "constant"
    assert folded.nodes[0].value == expected


# ---------------------------------------------------------------------------
# C++ emission
# ---------------------------------------------------------------------------


def test_compile_emits_bitwise_cpp() -> None:
    g = Graph(
        name="bits",
        inputs=[AudioInput(id="a"), AudioInput(id="b")],
        nodes=[
            BinOp(id="n1", op="bitand", a="a", b="b"),
            BinOp(id="n2", op="bitor", a="a", b="b"),
            BinOp(id="n3", op="bitxor", a="a", b="b"),
            BinOp(id="n4", op="bitshift", a="a", b="b"),
            UnaryOp(id="n5", op="bitnot", a="a"),
            BinOp(id="o", op="add", a="n1", b="n4"),
        ],
        outputs=[AudioOutput(id="out1", source="o")],
    )
    cpp = compile_graph(g)
    src = cpp if isinstance(cpp, str) else str(cpp)
    assert "(int32_t)(a[i]) & (int32_t)(b[i])" in src
    assert "(int32_t)(a[i]) | (int32_t)(b[i])" in src
    assert "(int32_t)(a[i]) ^ (int32_t)(b[i])" in src
    assert "~(int32_t)(a[i])" in src
    # bitshift emits the signed-direction ternary
    assert "n4_sh >= 0" in src
