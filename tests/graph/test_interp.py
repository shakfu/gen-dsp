"""Tests for the interp node (linear/cosine 2-point interpolation)."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("pydantic")

from gen_dsp.graph.compile import compile_graph  # noqa: E402
from gen_dsp.graph.dsl import parse  # noqa: E402
from gen_dsp.graph.models import (  # noqa: E402
    AudioInput,
    AudioOutput,
    Graph,
    Interp,
)
from gen_dsp.graph.optimize import constant_fold  # noqa: E402
from gen_dsp.graph.serialize import graph_to_gdsp  # noqa: E402


def _graph(node: Interp) -> Graph:
    return Graph(
        name="it",
        inputs=[AudioInput(id="a"), AudioInput(id="b"), AudioInput(id="t")],
        nodes=[node],
        outputs=[AudioOutput(id="out1", source="o")],
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_interp_defaults_to_linear() -> None:
    node = Interp(id="o", a="a", b="b", t="t")
    assert node.op == "interp"
    assert node.mode == "linear"


@pytest.mark.parametrize("mode", ["linear", "cosine"])
def test_interp_accepts_modes(mode: str) -> None:
    assert Interp(id="o", a="a", b="b", t="t", mode=mode).mode == mode


def test_interp_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        Interp(id="o", a="a", b="b", t="t", mode="cubic")


# ---------------------------------------------------------------------------
# Constant folding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,t,expected",
    [
        ("linear", 0.0, 0.0),
        ("linear", 0.25, 2.5),
        ("linear", 1.0, 10.0),
        ("cosine", 0.0, 0.0),
        ("cosine", 0.5, 5.0),
        ("cosine", 1.0, 10.0),
    ],
)
def test_interp_folds(mode: str, t: float, expected: float) -> None:
    g = _graph(Interp(id="o", a=0.0, b=10.0, t=t, mode=mode))
    folded = constant_fold(g)
    assert folded.nodes[0].op == "constant"
    assert folded.nodes[0].value == pytest.approx(expected)


def test_interp_cosine_endpoints_match_linear() -> None:
    # Cosine interpolation must agree with linear at t in {0, 1}.
    for t in (0.0, 1.0):
        lin = constant_fold(_graph(Interp(id="o", a=-3.0, b=7.0, t=t, mode="linear")))
        cos = constant_fold(_graph(Interp(id="o", a=-3.0, b=7.0, t=t, mode="cosine")))
        assert lin.nodes[0].value == pytest.approx(cos.nodes[0].value)


def test_interp_cosine_formula() -> None:
    a, b, t = -2.0, 6.0, 0.3
    f = (1.0 - math.cos(math.pi * t)) * 0.5
    expected = a + (b - a) * f
    folded = constant_fold(_graph(Interp(id="o", a=a, b=b, t=t, mode="cosine")))
    assert folded.nodes[0].value == pytest.approx(expected)


# ---------------------------------------------------------------------------
# C++ emission
# ---------------------------------------------------------------------------


def test_compile_linear_is_lerp() -> None:
    src = str(compile_graph(_graph(Interp(id="o", a="a", b="b", t="t"))))
    assert "a[i] + (b[i] - a[i]) * t[i]" in src


def test_compile_cosine_uses_cosf() -> None:
    src = str(compile_graph(_graph(Interp(id="o", a="a", b="b", t="t", mode="cosine"))))
    assert "cosf(3.14159265f * t[i])" in src


# ---------------------------------------------------------------------------
# DSL + serialize round-trip
# ---------------------------------------------------------------------------


def test_dsl_parses_interp_with_mode() -> None:
    g = parse("graph rt { in a in b in t y = interp(a, b, t, mode=cosine) out o = y }")
    node = next(n for n in g.nodes if n.op == "interp")
    assert node.mode == "cosine"


def test_serialize_omits_default_mode() -> None:
    g = _graph(Interp(id="o", a="a", b="b", t="t", mode="linear"))
    text = graph_to_gdsp(g)
    assert "interp(a, b, t)" in text
    assert "mode=" not in text


def test_serialize_includes_cosine_mode() -> None:
    g = _graph(Interp(id="o", a="a", b="b", t="t", mode="cosine"))
    text = graph_to_gdsp(g)
    assert "interp(a, b, t, mode=cosine)" in text
