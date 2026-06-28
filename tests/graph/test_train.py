"""Tests for the train node (impulse-train generator)."""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")
np = pytest.importorskip("numpy")

from gen_dsp.graph.compile import compile_graph  # noqa: E402
from gen_dsp.graph.dsl import parse  # noqa: E402
from gen_dsp.graph.models import AudioOutput, Graph, Train  # noqa: E402
from gen_dsp.graph.optimize import constant_fold  # noqa: E402
from gen_dsp.graph.serialize import graph_to_gdsp  # noqa: E402
from gen_dsp.graph.simulate import simulate  # noqa: E402


def _graph(freq: float = 10.0, sr: float = 50.0) -> Graph:
    return Graph(
        name="tr",
        sample_rate=sr,
        nodes=[Train(id="o", freq=freq)],
        outputs=[AudioOutput(id="out1", source="o")],
    )


def test_train_model() -> None:
    node = Train(id="o", freq=440.0)
    assert node.op == "train"
    assert node.freq == 440.0


def test_train_emits_one_impulse_per_period() -> None:
    # sr=50, freq=10 -> phase increment 0.2 -> wraps every 5 samples.
    res = simulate(_graph(freq=10.0, sr=50.0), n_samples=20, sample_rate=50.0)
    out = res.outputs["out1"]
    impulses = np.nonzero(out)[0].tolist()
    assert impulses == [4, 9, 14, 19]
    # Every non-zero sample is exactly 1.0.
    assert set(out[out != 0.0].tolist()) == {1.0}


def test_train_is_stateful_not_folded() -> None:
    # A generator with a constant freq must not be constant-folded away.
    folded = constant_fold(_graph())
    assert folded.nodes[0].op == "train"


def test_train_compiles_with_phase_state() -> None:
    src = str(compile_graph(_graph()))
    assert "o_phase += 10.0f / sr;" in src
    assert "o_phase >= 1.0f ? 1.0f : 0.0f" in src


def test_train_dsl_and_serialize_roundtrip() -> None:
    g = parse("graph t { y = train(440) out o = y }")
    node = next(n for n in g.nodes if n.op == "train")
    assert node.freq == 440.0
    assert "train(440)" in graph_to_gdsp(g)
