"""Tests for the 'nearest' interpolation mode on BufRead / DelayRead."""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")
np = pytest.importorskip("numpy")

from gen_dsp.graph.compile import compile_graph  # noqa: E402
from gen_dsp.graph.models import (  # noqa: E402
    AudioInput,
    AudioOutput,
    BufRead,
    Buffer,
    Graph,
)
from gen_dsp.graph.serialize import graph_to_gdsp  # noqa: E402
from gen_dsp.graph.simulate import SimState, simulate  # noqa: E402


@pytest.mark.parametrize("field", ["interp"])
@pytest.mark.parametrize("interp", ["none", "nearest", "linear", "cubic"])
def test_bufread_accepts_nearest(field: str, interp: str) -> None:
    node = BufRead(id="o", buffer="b", index="ix", interp=interp)
    assert node.interp == interp


def test_nearest_rounds_half_up() -> None:
    g = Graph(
        name="br",
        inputs=[AudioInput(id="ix")],
        nodes=[
            Buffer(id="b", size=8),
            BufRead(id="o", buffer="b", index="ix", interp="nearest"),
        ],
        outputs=[AudioOutput(id="out1", source="o")],
    )
    table = np.arange(8, dtype=np.float32) * 10.0
    st = SimState(g, 44100.0)
    st.set_buffer("b", table)
    # 0.4->0, 0.6->1, 1.5->2 (half up), 2.9->3, 7.2->7 (clamped)
    idx = np.array([0.4, 0.6, 1.5, 2.9, 7.2], dtype=np.float32)
    res = simulate(g, {"ix": idx}, n_samples=5, state=st)
    np.testing.assert_array_equal(
        res.outputs["out1"], np.array([0.0, 10.0, 20.0, 30.0, 70.0], dtype=np.float32)
    )


def test_nearest_differs_from_none() -> None:
    # idx=2.9: none truncates to 2, nearest rounds to 3.
    def run(interp: str) -> float:
        g = Graph(
            name="br",
            inputs=[AudioInput(id="ix")],
            nodes=[
                Buffer(id="b", size=8),
                BufRead(id="o", buffer="b", index="ix", interp=interp),
            ],
            outputs=[AudioOutput(id="out1", source="o")],
        )
        st = SimState(g, 44100.0)
        st.set_buffer("b", np.arange(8, dtype=np.float32) * 10.0)
        return float(
            simulate(
                g, {"ix": np.array([2.9], dtype=np.float32)}, n_samples=1, state=st
            ).outputs["out1"][0]
        )

    assert run("none") == 20.0
    assert run("nearest") == 30.0


def test_nearest_compiles_and_serializes() -> None:
    g = Graph(
        name="br",
        inputs=[AudioInput(id="ix")],
        nodes=[
            Buffer(id="b", size=8),
            BufRead(id="o", buffer="b", index="ix", interp="nearest"),
        ],
        outputs=[AudioOutput(id="out1", source="o")],
    )
    assert "floorf(ix[i] + 0.5f)" in str(compile_graph(g))
    assert "interp=nearest" in graph_to_gdsp(g)
