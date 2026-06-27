"""Differential tests: emitted gen~ codebox vs the simulate.py reference.

Each case transpiles a graph to GenExpr, runs the emitted codebox through the
Python gen~-semantics evaluator (``transpile_eval``), and asserts the result
matches ``simulate`` sample-for-sample. A divergence means the transpiler emitted
GenExpr that does not compute what the graph specifies -- a transcription bug.

This is the automated half of the differential harness. It does NOT validate
gen-dsp against Cycling '74's gen~ (that needs Max in the loop); it validates the
transpiler's emission against an independent Python reference.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")
np = pytest.importorskip("numpy")

from gen_dsp.graph.models import (
    SVF,
    ADSR,
    Accum,
    Allpass,
    AudioInput,
    AudioOutput,
    BinOp,
    Biquad,
    Buffer,
    BufRead,
    BufWrite,
    Change,
    Clamp,
    Compare,
    Counter,
    Cycle,
    DCBlock,
    DelayLine,
    DelayRead,
    DelayWrite,
    Delta,
    Elapsed,
    Fold,
    GateOut,
    GateRoute,
    Graph,
    Latch,
    Lookup,
    Mix,
    MulAccum,
    NamedConstant,
    OnePole,
    Param,
    Pass,
    Phasor,
    PulseOsc,
    RateDiv,
    SampleHold,
    SawOsc,
    Scale,
    Select,
    Selector,
    SinOsc,
    Slide,
    Smoothstep,
    SmoothParam,
    Splat,
    TriOsc,
    UnaryOp,
    Wrap,
)
from gen_dsp.graph.models import Noise
from gen_dsp.graph.simulate import SimState, simulate
from gen_dsp.graph.transpile import NON_DETERMINISTIC_OPS, transpile_to_genexpr
from gen_dsp.graph.transpile_eval import eval_genexpr

SR = 48000.0
N = 512


def _signal(seed_phase: float = 0.0) -> "np.ndarray":
    t = np.arange(N)
    return (0.7 * np.sin(2 * np.pi * 220 * t / SR + seed_phase)).astype(np.float32)


def _pulse(period: int) -> "np.ndarray":
    return ((np.arange(N) % period) < 1).astype(np.float32)


_TABLE = np.sin(2 * np.pi * np.arange(64) / 64).astype(np.float32)


def _o(src: str, oid: str = "out1") -> AudioOutput:
    return AudioOutput(id=oid, source=src)


# A case is (graph, inputs_by_id, data_init_by_buffer_id).
def _cases() -> list[tuple[str, Graph, dict, dict]]:
    x = _signal()
    x2 = _signal(1.1)
    trig = _pulse(31)
    sel = (np.arange(N) % 3).astype(np.float32)
    idx = ((np.arange(N) % 63) + 0.5).astype(np.float32)
    gate = (np.arange(N) % 200 < 100).astype(np.float32)
    cases: list[tuple[str, Graph, dict, dict]] = []

    def add(name, nodes, *, inputs=None, outs=None, buf=None):
        g = Graph(
            name=name,
            inputs=[AudioInput(id=i) for i in (inputs or {})],
            nodes=nodes,
            outputs=outs or [_o(nodes[-1].id)],
        )
        cases.append((name, g, inputs or {}, buf or {}))

    # -- native-operator nodes (sanity: must also match) --------------------
    add(
        "clamp",
        [Pass(id="p", a="a"), Clamp(id="o", a="p", lo=-0.5, hi=0.5)],
        inputs={"a": x},
    )
    add(
        "wrap",
        [Pass(id="p", a="a"), Wrap(id="o", a="p", lo=-0.3, hi=0.3)],
        inputs={"a": x},
    )
    add(
        "fold",
        [Pass(id="p", a="a"), Fold(id="o", a="p", lo=-0.3, hi=0.3)],
        inputs={"a": x},
    )
    add(
        "scale",
        [
            Pass(id="p", a="a"),
            Scale(id="o", a="p", in_lo=-1.0, in_hi=1.0, out_lo=0.0, out_hi=2.0),
        ],
        inputs={"a": x},
    )
    add(
        "mix",
        [Pass(id="p", a="a"), Pass(id="q", a="b"), Mix(id="o", a="p", b="q", t=0.3)],
        inputs={"a": x, "b": x2},
    )
    add("compare", [Compare(id="o", op="gte", a="a", b="b")], inputs={"a": x, "b": x2})
    add(
        "select",
        [Select(id="o", cond="s", a="a", b="b")],
        inputs={"a": x, "b": x2, "s": sel},
    )
    add(
        "smoothstep",
        [Smoothstep(id="o", a="a", edge0=-0.5, edge1=0.5)],
        inputs={"a": x},
    )
    add(
        "mtof_chain",
        [UnaryOp(id="m", op="mtof", a="a"), UnaryOp(id="o", op="ftom", a="m")],
        inputs={"a": (x * 12 + 60).astype(np.float32)},
    )
    add(
        "namedconst",
        [NamedConstant(id="k", op="phi"), BinOp(id="o", op="mul", a="k", b="a")],
        inputs={"a": x},
    )
    add("delta", [Delta(id="o", a="a")], inputs={"a": x})
    add(
        "change",
        [Change(id="o", a="q")],
        inputs={"q": np.round(x * 3).astype(np.float32)},
    )
    add("accum", [Accum(id="o", incr=0.01, reset="r")], inputs={"r": _pulse(50)})
    add("elapsed", [Elapsed(id="el"), BinOp(id="o", op="mul", a="el", b=0.001)])

    # -- oscillators --------------------------------------------------------
    add("sinosc", [SinOsc(id="o", freq=440.0)])
    add("phasor", [Phasor(id="o", freq=330.0)])
    add("triosc", [TriOsc(id="o", freq=330.0)])
    add("sawosc", [SawOsc(id="o", freq=330.0)])
    add("pulseosc", [PulseOsc(id="o", freq=330.0, width=0.3)])
    add(
        "sinosc_fm",
        [
            SinOsc(id="lfo", freq=5.0),
            BinOp(id="f", op="add", a="lfo", b=440.0),
            SinOsc(id="o", freq="f"),
        ],
    )

    # -- filters ------------------------------------------------------------
    add("onepole", [OnePole(id="o", a="a", coeff=0.05)], inputs={"a": x})
    add(
        "biquad",
        [Biquad(id="o", a="a", b0=0.2, b1=0.1, b2=0.05, a1=-0.3, a2=0.1)],
        inputs={"a": x},
    )
    for mode in ("lp", "hp", "bp", "notch"):
        add(
            f"svf_{mode}",
            [SVF(id="o", a="a", freq=1200.0, q=0.7, mode=mode)],
            inputs={"a": x},
        )
    add("dcblock", [DCBlock(id="o", a="a")], inputs={"a": (x + 0.3).astype(np.float32)})
    add("allpass", [Allpass(id="o", a="a", coeff=0.5)], inputs={"a": x})

    # -- delays (feedback topology: read-before-write) ----------------------
    for interp in ("none", "linear", "cubic"):
        add(
            f"comb_{interp}",
            [
                DelayLine(id="dl", max_samples=400),
                DelayRead(id="rd", delay="dl", tap=123.0, interp=interp),
                BinOp(id="fb", op="mul", a="rd", b=0.6),
                BinOp(id="w", op="add", a="a", b="fb"),
                DelayWrite(id="wr", delay="dl", value="w"),
            ],
            inputs={"a": x},
            outs=[_o("rd")],
        )

    # -- buffers ------------------------------------------------------------
    add(
        "cycle",
        [Buffer(id="b", size=64), Cycle(id="o", buffer="b", phase="ph")],
        inputs={"ph": (np.arange(N) / 97.0).astype(np.float32)},
        buf={"b": _TABLE},
    )
    add(
        "lookup",
        [Buffer(id="b", size=64), Lookup(id="o", buffer="b", index="ix")],
        inputs={"ix": np.linspace(0, 1, N).astype(np.float32)},
        buf={"b": _TABLE},
    )
    for interp in ("none", "linear", "cubic"):
        add(
            f"bufread_{interp}",
            [
                Buffer(id="b", size=64),
                BufRead(id="o", buffer="b", index="ix", interp=interp),
            ],
            inputs={"ix": idx},
            buf={"b": _TABLE},
        )
    add(
        "bufwrite_read",
        [
            Buffer(id="b", size=64),
            BufWrite(id="w", buffer="b", index=7.0, value="v"),
            BufRead(id="o", buffer="b", index=7.0, interp="none"),
        ],
        inputs={"v": x},
    )
    add(
        "splat_read",
        [
            Buffer(id="b", size=64),
            Splat(id="w", buffer="b", index=7.0, value="v"),
            BufRead(id="o", buffer="b", index=7.0, interp="none"),
        ],
        inputs={"v": x},
    )

    # -- state / timing -----------------------------------------------------
    add("samplehold", [SampleHold(id="o", a="a", trig="t")], inputs={"a": x, "t": trig})
    add("latch", [Latch(id="o", a="a", trig="t")], inputs={"a": x, "t": trig})
    add("counter", [Counter(id="o", trig="t", max=5.0)], inputs={"t": trig})
    add("ratediv", [RateDiv(id="o", a="a", divisor=4.0)], inputs={"a": x})
    add(
        "mulaccum",
        [MulAccum(id="o", incr="a", reset="r")],
        inputs={"a": (1.0 + 0.001 * x).astype(np.float32), "r": _pulse(60)},
    )
    add("slide", [Slide(id="o", a="a", up=10.0, down=100.0)], inputs={"a": x})
    add("smoothparam", [SmoothParam(id="o", a="a", coeff=0.9)], inputs={"a": x})
    add(
        "adsr",
        [ADSR(id="o", gate="g", attack=1.0, decay=2.0, sustain=0.5, release=3.0)],
        inputs={"g": gate},
    )

    # -- routing ------------------------------------------------------------
    add(
        "selector",
        [Selector(id="o", index="s", inputs=["a", "b"])],
        inputs={"a": x, "b": x2, "s": sel},
    )
    add(
        "gate",
        [
            GateRoute(id="gr", a="a", index="s", count=2),
            GateOut(id="o1", gate="gr", channel=1),
            GateOut(id="o2", gate="gr", channel=2),
        ],
        inputs={"a": x, "s": sel},
        outs=[_o("o1", "out1"), _o("o2", "out2")],
    )

    # -- a combined graph with a param --------------------------------------
    combined = Graph(
        name="combined",
        inputs=[AudioInput(id="a")],
        params=[Param(name="cutoff", min=0.0, max=1.0, default=0.2)],
        nodes=[
            SinOsc(id="lfo", freq=3.0),
            Scale(id="g", a="lfo", in_lo=-1.0, in_hi=1.0, out_lo=0.0, out_hi=0.5),
            OnePole(id="lp", a="a", coeff="cutoff"),
            BinOp(id="o", op="mul", a="lp", b="g"),
            DCBlock(id="dc", a="o"),
        ],
        outputs=[_o("dc")],
    )
    cases.append(("combined", combined, {"a": x}, {}))

    return cases


_CASES = _cases()


@pytest.mark.parametrize("case", _CASES, ids=[c[0] for c in _CASES])
def test_genexpr_matches_simulate(case) -> None:
    name, graph, inputs, buf = case
    code = transpile_to_genexpr(graph)

    # Reference: simulate (seed any buffers identically).
    st = SimState(graph, SR)
    for bid, arr in buf.items():
        st.set_buffer(bid, arr)
    sim = simulate(graph, dict(inputs) or None, n_samples=N, state=st)

    # Candidate: run the emitted codebox through the gen~-semantics evaluator.
    ev_inputs = {f"in{i + 1}": inputs[inp.id] for i, inp in enumerate(graph.inputs)}
    ev = eval_genexpr(code, ev_inputs or None, SR, N, buf or None)

    for i, out in enumerate(graph.outputs):
        ref = sim.outputs[out.id]
        got = ev[f"out{i + 1}"]
        np.testing.assert_allclose(
            got.astype(np.float64),
            ref.astype(np.float64),
            atol=1e-4,
            rtol=1e-4,
            err_msg=f"{name}: output {out.id} diverges from simulate",
        )


def test_corpus_covers_many_node_types() -> None:
    # Guard against the corpus silently shrinking.
    assert len(_CASES) >= 45


def test_corpus_excludes_nondeterministic_nodes() -> None:
    # Non-deterministic ops (noise) emit valid codeboxes but cannot be diffed
    # against simulate, so they must never appear in the differential corpus.
    for name, graph, _inputs, _buf in _CASES:
        for node in graph.nodes:
            assert node.op not in NON_DETERMINISTIC_OPS, (
                f"case {name!r} contains non-comparable op {node.op!r}"
            )


def test_evaluator_refuses_noise() -> None:
    # The emitted codebox is valid for Max, but running it through the
    # differential evaluator must fail loudly rather than fake a value.
    code = transpile_to_genexpr(
        Graph(name="n", nodes=[Noise(id="o")], outputs=[_o("o")])
    )
    assert "noise()" in code
    with pytest.raises(ValueError, match="nondeterministic"):
        eval_genexpr(code, None, SR, 8)


class TestEvaluatorSemantics:
    """Direct checks of gen~-specific semantics the evaluator must model."""

    def test_history_is_unit_delay(self) -> None:
        code = "History h(0);\nout1 = h;\nh = in1;\n"
        sig = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        out = eval_genexpr(code, {"in1": sig}, SR, 4)["out1"]
        # output is the previous sample's input; first sample is the init (0).
        np.testing.assert_array_equal(out, np.array([0, 1, 2, 3], dtype=np.float32))

    def test_protected_division_by_zero(self) -> None:
        code = "out1 = in1 / in2;\n"
        a = np.array([1.0, 2.0], dtype=np.float32)
        b = np.array([0.0, 4.0], dtype=np.float32)
        out = eval_genexpr(code, {"in1": a, "in2": b}, SR, 2)["out1"]
        np.testing.assert_array_equal(out, np.array([0.0, 0.5], dtype=np.float32))

    def test_peek_out_of_range_returns_zero(self) -> None:
        code = "Data d(4);\nout1 = peek(d, in1);\n"
        idx = np.array([-1.0, 0.0, 3.0, 9.0], dtype=np.float32)
        seed = np.array([5, 6, 7, 8], dtype=np.float32)
        out = eval_genexpr(code, {"in1": idx}, SR, 4, {"d": seed})["out1"]
        np.testing.assert_array_equal(out, np.array([0, 5, 8, 0], dtype=np.float32))

    def test_poke_out_of_range_is_ignored(self) -> None:
        # Poke past the end must not raise or corrupt anything; reading it is 0.
        code = "Data d(4);\npoke(d, 1, 99);\nout1 = peek(d, 99);\n"
        out = eval_genexpr(code, None, SR, 1)["out1"]
        np.testing.assert_array_equal(out, np.array([0.0], dtype=np.float32))
