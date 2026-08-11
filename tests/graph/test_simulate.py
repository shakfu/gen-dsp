"""Tests for the Python DSP simulator."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
numpy = __import__("pytest").importorskip("numpy")
import math

import numpy as np
import pytest

from gen_dsp.graph import (
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
    BufSize,
    BufWrite,
    Change,
    Clamp,
    Compare,
    Constant,
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
    History,
    Latch,
    Lookup,
    Mix,
    MulAccum,
    NamedConstant,
    Noise,
    OnePole,
    Param,
    Pass,
    Peek,
    Phasor,
    PulseOsc,
    RateDiv,
    SampleHold,
    SampleRate,
    SawOsc,
    Scale,
    Select,
    Selector,
    SinOsc,
    Slide,
    Smoothstep,
    SmoothParam,
    Splat,
    Subgraph,
    TriOsc,
    UnaryOp,
    Wave,
    Wrap,
)
from gen_dsp.graph.simulate import SimResult, SimState, simulate

SR = 44100.0


# ---------------------------------------------------------------------------
# A. API / smoke tests
# ---------------------------------------------------------------------------


class TestSimStateAPI:
    def test_create(self) -> None:
        g = Graph(name="empty", outputs=[])
        st = SimState(g, sample_rate=48000.0)
        assert st.sr == 48000.0

    def test_default_sample_rate(self) -> None:
        g = Graph(name="empty", sample_rate=22050.0, outputs=[])
        st = SimState(g)
        assert st.sr == 22050.0

    def test_param_get_set(self) -> None:
        g = Graph(
            name="p",
            params=[Param(name="vol", default=0.5)],
            outputs=[],
        )
        st = SimState(g)
        assert st.get_param("vol") == 0.5
        st.set_param("vol", 0.8)
        assert st.get_param("vol") == 0.8

    def test_param_unknown_raises(self) -> None:
        g = Graph(name="p", outputs=[])
        st = SimState(g)
        with pytest.raises(KeyError, match="Unknown param"):
            st.set_param("nope", 1.0)
        with pytest.raises(KeyError, match="Unknown param"):
            st.get_param("nope")

    def test_buffer_get_set(self) -> None:
        g = Graph(
            name="b",
            nodes=[Buffer(id="buf1", size=4)],
            outputs=[],
        )
        st = SimState(g)
        data = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        st.set_buffer("buf1", data)
        np.testing.assert_array_equal(st.get_buffer("buf1"), data)

    def test_buffer_unknown_raises(self) -> None:
        g = Graph(name="b", outputs=[])
        st = SimState(g)
        with pytest.raises(KeyError, match="Unknown buffer"):
            st.set_buffer("nope", np.zeros(1, dtype=np.float32))
        with pytest.raises(KeyError, match="Unknown buffer"):
            st.get_buffer("nope")

    def test_peek_value(self) -> None:
        g = Graph(
            name="pk",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="pk1")],
            nodes=[Peek(id="pk1", a="in1")],
        )
        st = SimState(g)
        assert st.get_peek("pk1") == 0.0

    def test_peek_unknown_raises(self) -> None:
        g = Graph(name="pk", outputs=[])
        st = SimState(g)
        with pytest.raises(KeyError, match="Unknown peek"):
            st.get_peek("nope")

    def test_reset(self) -> None:
        g = Graph(
            name="r",
            params=[Param(name="vol", default=0.5)],
            nodes=[History(id="h1", init=1.0, input="h1")],
            outputs=[AudioOutput(id="out1", source="h1")],
        )
        st = SimState(g)
        st.set_param("vol", 0.9)
        simulate(g, n_samples=10, state=st)
        st.reset()
        assert st.get_param("vol") == 0.5
        # History should be re-initialized
        assert st._state["h1"] == 1.0


class TestSimulateAPI:
    def test_result_shape(self) -> None:
        g = Graph(
            name="pass",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="g1")],
            nodes=[BinOp(id="g1", op="mul", a="in1", b=1.0)],
        )
        inp = np.ones(16, dtype=np.float32)
        result = simulate(g, inputs={"in1": inp})
        assert isinstance(result, SimResult)
        assert "out1" in result.outputs
        assert result.outputs["out1"].shape == (16,)
        assert result.outputs["out1"].dtype == np.float32

    def test_state_reuse(self) -> None:
        g = Graph(
            name="acc",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="a1")],
            nodes=[Accum(id="a1", incr="in1", reset=0.0)],
        )
        inp = np.ones(5, dtype=np.float32)
        r1 = simulate(g, inputs={"in1": inp})
        # sum should be 5 after 5 samples of 1.0
        assert r1.outputs["out1"][-1] == pytest.approx(5.0)
        r2 = simulate(g, inputs={"in1": inp}, state=r1.state)
        # sum continues: 10.0
        assert r2.outputs["out1"][-1] == pytest.approx(10.0)

    def test_generator_needs_n_samples(self) -> None:
        g = Graph(
            name="gen",
            outputs=[AudioOutput(id="out1", source="c1")],
            nodes=[Constant(id="c1", value=0.5)],
        )
        with pytest.raises(ValueError, match="n_samples required"):
            simulate(g)

    def test_input_length_mismatch(self) -> None:
        g = Graph(
            name="stereo",
            inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
            outputs=[AudioOutput(id="out1", source="s1")],
            nodes=[BinOp(id="s1", op="add", a="in1", b="in2")],
        )
        with pytest.raises(ValueError, match="mismatched lengths"):
            simulate(
                g,
                inputs={
                    "in1": np.ones(10, dtype=np.float32),
                    "in2": np.ones(5, dtype=np.float32),
                },
            )

    def test_unknown_param_error(self) -> None:
        g = Graph(
            name="p",
            outputs=[AudioOutput(id="out1", source="c1")],
            nodes=[Constant(id="c1", value=0.0)],
        )
        with pytest.raises(KeyError, match="Unknown param"):
            simulate(g, n_samples=1, params={"bogus": 1.0})

    def test_unknown_input_error(self) -> None:
        g = Graph(
            name="p",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="g1")],
            nodes=[BinOp(id="g1", op="mul", a="in1", b=1.0)],
        )
        with pytest.raises(ValueError, match="Unknown input"):
            simulate(g, inputs={"bogus": np.ones(1, dtype=np.float32)})

    def test_missing_input_error(self) -> None:
        g = Graph(
            name="p",
            inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
            outputs=[AudioOutput(id="out1", source="s1")],
            nodes=[BinOp(id="s1", op="add", a="in1", b="in2")],
        )
        with pytest.raises(ValueError, match="Missing inputs"):
            simulate(g, inputs={"in1": np.ones(1, dtype=np.float32)})

    def test_empty_graph(self) -> None:
        g = Graph(name="empty", outputs=[])
        r = simulate(g, n_samples=10)
        assert r.outputs == {}


# ---------------------------------------------------------------------------
# B. Pure arithmetic tests
# ---------------------------------------------------------------------------


class TestBinOp:
    @pytest.mark.parametrize(
        "op,a,b,expected",
        [
            ("add", 3.0, 4.0, 7.0),
            ("sub", 10.0, 3.0, 7.0),
            ("mul", 3.0, 4.0, 12.0),
            ("div", 10.0, 4.0, 2.5),
            ("min", 3.0, 7.0, 3.0),
            ("max", 3.0, 7.0, 7.0),
            ("mod", 7.0, 3.0, 1.0),
            ("pow", 2.0, 3.0, 8.0),
        ],
    )
    def test_binop(self, op: str, a: float, b: float, expected: float) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[BinOp(id="r", op=op, a=a, b=b)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(expected, abs=1e-6)

    def test_div_by_zero(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[BinOp(id="r", op="div", a=1.0, b=0.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == 0.0


class TestUnaryOp:
    @pytest.mark.parametrize(
        "op,a,expected",
        [
            ("neg", 5.0, -5.0),
            ("abs", -3.0, 3.0),
            ("sign", -7.0, -1.0),
            ("sign", 0.0, 0.0),
            ("sign", 3.0, 1.0),
            ("sin", 0.0, 0.0),
            ("cos", 0.0, 1.0),
            ("floor", 2.7, 2.0),
            ("ceil", 2.3, 3.0),
            ("round", 2.5, 2.0),  # Python banker's rounding
            ("sqrt", 9.0, 3.0),
            ("exp", 0.0, 1.0),
            ("log", 1.0, 0.0),
            ("tanh", 0.0, 0.0),
            ("atan", 0.0, 0.0),
            ("asin", 0.0, 0.0),
            ("acos", 1.0, 0.0),
        ],
    )
    def test_unaryop(self, op: str, a: float, expected: float) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[UnaryOp(id="r", op=op, a=a)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(expected, abs=1e-6)


class TestPureNodes:
    def test_clamp(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Clamp(id="r", a=1.5, lo=0.0, hi=1.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(1.0)

    def test_clamp_below(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Clamp(id="r", a=-0.5, lo=0.0, hi=1.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(0.0)

    def test_constant(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Constant(id="c", value=42.0)],
        )
        r = simulate(g, n_samples=3)
        np.testing.assert_allclose(r.outputs["out1"], 42.0)

    def test_compare_gt(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Compare(id="r", op="gt", a=5.0, b=3.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == 1.0

    def test_compare_eq(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Compare(id="r", op="eq", a=3.0, b=3.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == 1.0

    def test_select(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Select(id="r", cond=1.0, a=10.0, b=20.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(10.0)

    def test_select_false(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Select(id="r", cond=0.0, a=10.0, b=20.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(20.0)

    def test_wrap(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Wrap(id="r", a=1.5, lo=0.0, hi=1.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(0.5)

    def test_fold(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Fold(id="r", a=1.3, lo=0.0, hi=1.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(0.7, abs=1e-6)

    def test_mix(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Mix(id="r", a=0.0, b=1.0, t=0.5)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(0.5)

    def test_scale(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Scale(id="r", a=0.5, in_lo=0.0, in_hi=1.0, out_lo=0.0, out_hi=10.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# C. Stateful node tests
# ---------------------------------------------------------------------------


class TestStatefulNodes:
    def test_history_feedback(self) -> None:
        """Manual one-pole via history: y[n] = 0.5*x[n] + 0.5*y[n-1]."""
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="result")],
            params=[Param(name="coeff", default=0.5)],
            nodes=[
                BinOp(id="inv_coeff", op="sub", a=1.0, b="coeff"),
                BinOp(id="dry", op="mul", a="in1", b="inv_coeff"),
                History(id="prev", init=0.0, input="result"),
                BinOp(id="wet", op="mul", a="prev", b="coeff"),
                BinOp(id="result", op="add", a="dry", b="wet"),
            ],
        )
        # Step input
        inp = np.ones(10, dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # Analytical: y[n] = 1 - 0.5^(n+1) for step input with coeff=0.5
        for n in range(10):
            expected = 1.0 - 0.5 ** (n + 1)
            assert r.outputs["out1"][n] == pytest.approx(expected, abs=1e-6)

    def test_phasor_ramp(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="ph")],
            nodes=[Phasor(id="ph", freq=100.0)],
            sample_rate=1000.0,
        )
        r = simulate(g, n_samples=10)
        # freq=100, sr=1000 -> increment=0.1 per sample
        # Output is phase BEFORE increment: 0.0, 0.1, 0.2, ...
        for i in range(10):
            assert r.outputs["out1"][i] == pytest.approx(i * 0.1, abs=1e-6)

    def test_noise_determinism(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="n1")],
            nodes=[Noise(id="n1")],
        )
        r1 = simulate(g, n_samples=100)
        r2 = simulate(g, n_samples=100)
        np.testing.assert_array_equal(r1.outputs["out1"], r2.outputs["out1"])

    def test_noise_range(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="n1")],
            nodes=[Noise(id="n1")],
        )
        r = simulate(g, n_samples=1000)
        assert np.all(r.outputs["out1"] >= -1.0)
        assert np.all(r.outputs["out1"] <= 1.0)
        # Should have variance -- not all zeros
        assert np.std(r.outputs["out1"]) > 0.1

    def test_delta(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="d1")],
            nodes=[Delta(id="d1", a="in1")],
        )
        inp = np.array([0.0, 1.0, 3.0, 6.0, 10.0], dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        expected = np.array([0.0, 1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        np.testing.assert_allclose(r.outputs["out1"], expected, atol=1e-6)

    def test_change(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="c1")],
            nodes=[Change(id="c1", a="in1")],
        )
        inp = np.array([0.0, 0.0, 1.0, 1.0, 2.0], dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # prev starts at 0.0; sample 0: 0==0 -> 0, sample 1: 0==0 -> 0,
        # sample 2: 1!=0 -> 1, sample 3: 1==1 -> 0, sample 4: 2!=1 -> 1
        expected = np.array([0.0, 0.0, 1.0, 0.0, 1.0], dtype=np.float32)
        np.testing.assert_allclose(r.outputs["out1"], expected, atol=1e-6)

    def test_sample_hold(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sh1")],
            nodes=[SampleHold(id="sh1", a="in1", trig="in1")],
        )
        # trig transitions at sample 1 (0->1), sample 3 (1->0)
        inp = np.array([0.0, 1.0, 1.0, 0.0, 0.0], dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # ptrig starts at 0.0
        # s0: ptrig=0, t=0 -> no edge -> held=0 -> out=0
        # s1: ptrig=0, t=1 -> rising edge -> held=1 -> out=1
        # s2: ptrig=1, t=1 -> no edge -> held=1 -> out=1
        # s3: ptrig=1, t=0 -> falling edge -> held=0 -> out=0
        # s4: ptrig=0, t=0 -> no edge -> held=0 -> out=0
        expected = np.array([0.0, 1.0, 1.0, 0.0, 0.0], dtype=np.float32)
        np.testing.assert_allclose(r.outputs["out1"], expected, atol=1e-6)

    def test_latch(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1"), AudioInput(id="trig")],
            outputs=[AudioOutput(id="out1", source="l1")],
            nodes=[Latch(id="l1", a="in1", trig="trig")],
        )
        inp = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float32)
        trig = np.array([0.0, 1.0, 0.0, 1.0], dtype=np.float32)
        r = simulate(g, inputs={"in1": inp, "trig": trig})
        # Rising edges at sample 1 (0->1) and sample 3 (0->1)
        # s0: no edge -> held=0
        # s1: rising -> held=20
        # s2: falling, not rising -> held=20
        # s3: rising -> held=40
        expected = np.array([0.0, 20.0, 20.0, 40.0], dtype=np.float32)
        np.testing.assert_allclose(r.outputs["out1"], expected, atol=1e-6)

    def test_accum(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="a1")],
            nodes=[Accum(id="a1", incr=1.0, reset=0.0)],
        )
        r = simulate(g, n_samples=5)
        expected = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        np.testing.assert_allclose(r.outputs["out1"], expected, atol=1e-6)

    def test_accum_reset(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="rst")],
            outputs=[AudioOutput(id="out1", source="a1")],
            nodes=[Accum(id="a1", incr=1.0, reset="rst")],
        )
        rst = np.array([0.0, 0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        r = simulate(g, inputs={"rst": rst})
        # s0: no reset, sum=0+1=1
        # s1: no reset, sum=1+1=2
        # s2: reset -> sum=0, then sum=0+1=1
        # s3: no reset, sum=1+1=2
        # s4: no reset, sum=2+1=3
        expected = np.array([1.0, 2.0, 1.0, 2.0, 3.0], dtype=np.float32)
        np.testing.assert_allclose(r.outputs["out1"], expected, atol=1e-6)

    def test_counter(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="trig")],
            outputs=[AudioOutput(id="out1", source="c1")],
            nodes=[Counter(id="c1", trig="trig", max=3.0)],
        )
        # Rising edges at samples 1, 3, 5, 7
        trig = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0], dtype=np.float32)
        r = simulate(g, inputs={"trig": trig})
        # s0: no edge -> count=0
        # s1: edge -> count=1
        # s2: no edge -> count=1
        # s3: edge -> count=2
        # s4: no edge -> count=2
        # s5: edge -> count=3 -> wraps to 0
        # s6: no edge -> count=0
        # s7: edge -> count=1
        expected = np.array([0.0, 1.0, 1.0, 2.0, 2.0, 0.0, 0.0, 1.0], dtype=np.float32)
        np.testing.assert_allclose(r.outputs["out1"], expected, atol=1e-6)

    def test_rate_div(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd1")],
            nodes=[RateDiv(id="rd1", a="in1", divisor=3.0)],
        )
        inp = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0], dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # count starts at 0.
        # s0: count==0 -> held=10, count=1
        # s1: count!=0 -> held=10, count=2
        # s2: count!=0 -> held=10, count=3 -> wraps to 0
        # s3: count==0 -> held=40, count=1
        # s4: count!=0 -> held=40, count=2
        # s5: count!=0 -> held=40, count=3 -> wraps to 0
        expected = np.array([10.0, 10.0, 10.0, 40.0, 40.0, 40.0], dtype=np.float32)
        np.testing.assert_allclose(r.outputs["out1"], expected, atol=1e-6)

    def test_smooth_param(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="sm1")],
            nodes=[SmoothParam(id="sm1", a=1.0, coeff=0.5)],
        )
        r = simulate(g, n_samples=5)
        # y = (1-0.5)*1.0 + 0.5*prev
        # s0: (0.5)*1 + 0.5*0 = 0.5
        # s1: 0.5*1 + 0.5*0.5 = 0.75
        # ...exponential approach to 1.0
        assert r.outputs["out1"][0] == pytest.approx(0.5, abs=1e-6)
        assert r.outputs["out1"][1] == pytest.approx(0.75, abs=1e-6)

    def test_peek_captures_value(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="pk1")],
            nodes=[Peek(id="pk1", a="in1")],
        )
        inp = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # Output should be the input values
        np.testing.assert_allclose(r.outputs["out1"], inp, atol=1e-6)
        # Peek state should hold last value
        assert r.state.get_peek("pk1") == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# D. Oscillator tests
# ---------------------------------------------------------------------------


class TestOscillators:
    def test_sinosc(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="osc")],
            nodes=[SinOsc(id="osc", freq=100.0)],
            sample_rate=1000.0,
        )
        r = simulate(g, n_samples=10)
        # freq=100, sr=1000, phase_inc=0.1
        # output = sin(2*pi*phase) before increment
        for i in range(10):
            expected = math.sin(6.28318530 * (i * 0.1))
            assert r.outputs["out1"][i] == pytest.approx(expected, abs=1e-5)

    def test_triosc(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="osc")],
            nodes=[TriOsc(id="osc", freq=100.0)],
            sample_rate=1000.0,
        )
        r = simulate(g, n_samples=10)
        for i in range(10):
            phase = i * 0.1
            expected = 4.0 * abs(phase - 0.5) - 1.0
            assert r.outputs["out1"][i] == pytest.approx(expected, abs=1e-5)

    def test_sawosc(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="osc")],
            nodes=[SawOsc(id="osc", freq=100.0)],
            sample_rate=1000.0,
        )
        r = simulate(g, n_samples=10)
        for i in range(10):
            phase = i * 0.1
            expected = 2.0 * phase - 1.0
            assert r.outputs["out1"][i] == pytest.approx(expected, abs=1e-5)

    def test_pulseosc(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="osc")],
            nodes=[PulseOsc(id="osc", freq=100.0, width=0.5)],
            sample_rate=1000.0,
        )
        r = simulate(g, n_samples=10)
        for i in range(10):
            phase = i * 0.1
            expected = 1.0 if phase < 0.5 else -1.0
            assert r.outputs["out1"][i] == pytest.approx(expected, abs=1e-5)

    def test_phase_continuity(self) -> None:
        """Phase persists across simulate() calls."""
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="ph")],
            nodes=[Phasor(id="ph", freq=100.0)],
            sample_rate=1000.0,
        )
        r1 = simulate(g, n_samples=5)
        r2 = simulate(g, n_samples=5, state=r1.state)
        # After 5 samples at 0.1 inc, phase should be 0.5
        assert r2.outputs["out1"][0] == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# E. Filter tests
# ---------------------------------------------------------------------------


class TestFilters:
    def test_biquad_passthrough(self) -> None:
        """Biquad with b0=1, b1=b2=a1=a2=0 is passthrough."""
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="bq")],
            nodes=[Biquad(id="bq", a="in1", b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0)],
        )
        inp = np.random.default_rng(42).standard_normal(32).astype(np.float32)
        r = simulate(g, inputs={"in1": inp})
        np.testing.assert_allclose(r.outputs["out1"], inp, atol=1e-5)

    def test_onepole_step_response(self) -> None:
        """OnePole step response: y[n] = c*1 + (1-c)*y[n-1]."""
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="lp")],
            nodes=[OnePole(id="lp", a="in1", coeff=0.3)],
        )
        inp = np.ones(20, dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # Analytical: y[n] = 1 - (1-c)^(n+1)
        for n in range(20):
            expected = 1.0 - (1.0 - 0.3) ** (n + 1)
            assert r.outputs["out1"][n] == pytest.approx(expected, abs=1e-5)

    def test_dcblock_removes_dc(self) -> None:
        """DCBlock should remove the DC component from a signal."""
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="dc")],
            nodes=[DCBlock(id="dc", a="in1")],
        )
        # DC offset of 1.0
        inp = np.ones(1000, dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # After settling, output should be near zero
        assert abs(float(r.outputs["out1"][-1])) < 0.01

    def test_svf_lowpass(self) -> None:
        """SVF in lowpass mode should pass DC."""
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sv")],
            nodes=[SVF(id="sv", a="in1", freq=5000.0, q=0.707, mode="lp")],
            sample_rate=44100.0,
        )
        inp = np.ones(200, dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # DC should pass through, so after settling the output approaches 1.0
        assert r.outputs["out1"][-1] == pytest.approx(1.0, abs=0.01)

    def test_svf_cutoff_above_nyquist_stays_finite(self) -> None:
        """A cutoff at or above Nyquist must not blow the filter up.

        The prewarp tangent diverges at sr/2, which is easy to reach at low
        sample rates (hosts probe down to ~1 kHz), so the cutoff is clamped
        just below it.
        """
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sv")],
            nodes=[SVF(id="sv", a="in1", freq=2000.0, q=2.0, mode="lp")],
            sample_rate=1234.57,
        )
        rng = np.random.default_rng(7)
        inp = rng.standard_normal(200).astype(np.float32)
        r = simulate(g, inputs={"in1": inp})
        assert np.all(np.isfinite(r.outputs["out1"]))

    def test_allpass_energy_preservation(self) -> None:
        """Allpass should not change signal energy in steady state."""
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="ap")],
            nodes=[Allpass(id="ap", a="in1", coeff=0.5)],
        )
        rng = np.random.default_rng(123)
        inp = rng.standard_normal(500).astype(np.float32)
        r = simulate(g, inputs={"in1": inp})
        # For an allpass, input and output should have similar energy
        # (after transient). Compare last 400 samples.
        in_energy = float(np.sum(inp[100:] ** 2))
        out_energy = float(np.sum(r.outputs["out1"][100:] ** 2))
        # Within 10% after transient
        assert abs(in_energy - out_energy) / in_energy < 0.1


# ---------------------------------------------------------------------------
# F. Delay/Buffer tests
# ---------------------------------------------------------------------------


class TestDelayAndBuffer:
    def test_delay_write_read_roundtrip(self) -> None:
        """Read-before-write with tap=1 gives 1-sample delay."""
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="delayed")],
            nodes=[
                DelayLine(id="dline", max_samples=100),
                # "delayed" < "dwrite" alphabetically -> read before write in topo sort
                DelayRead(id="delayed", delay="dline", tap=1.0),
                DelayWrite(id="dwrite", delay="dline", value="in1"),
            ],
        )
        inp = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # Topo order: dline, delayed (read), dwrite (write)
        # s0: read from (0-1)%100=99 -> 0.0, then write buf[0]=1.0, wr=1
        # s1: read from (1-1)%100=0 -> 1.0, then write buf[1]=2.0, wr=2
        # s2: read from (2-1)%100=1 -> 2.0, etc.
        expected = np.array([0.0, 1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        np.testing.assert_allclose(r.outputs["out1"], expected, atol=1e-6)

    def test_delay_linear_interp(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[
                DelayLine(id="dl", max_samples=100),
                DelayWrite(id="dw", delay="dl", value="in1"),
                DelayRead(id="rd", delay="dl", tap=1.5, interp="linear"),
            ],
        )
        # Write [0, 1, 2, 3, 4], read with fractional tap
        inp = np.arange(5, dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # tap=1.5, linear interp between tap=1 and tap=2
        # Just verify it produces reasonable intermediate values
        assert r.outputs["out1"].dtype == np.float32

    def test_delay_cubic_interp(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[
                DelayLine(id="dl", max_samples=100),
                DelayWrite(id="dw", delay="dl", value="in1"),
                DelayRead(id="rd", delay="dl", tap=1.5, interp="cubic"),
            ],
        )
        inp = np.arange(10, dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        assert r.outputs["out1"].dtype == np.float32

    def test_buffer_set_get(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=8),
                BufRead(id="br", buffer="buf", index=3.0),
            ],
        )
        st = SimState(g)
        data = np.array(
            [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0], dtype=np.float32
        )
        st.set_buffer("buf", data)
        r = simulate(g, n_samples=1, state=st)
        assert r.outputs["out1"][0] == pytest.approx(30.0)

    def test_bufread_linear_interp(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=4),
                BufRead(id="br", buffer="buf", index=1.5, interp="linear"),
            ],
        )
        st = SimState(g)
        data = np.array([0.0, 10.0, 20.0, 30.0], dtype=np.float32)
        st.set_buffer("buf", data)
        r = simulate(g, n_samples=1, state=st)
        # Linear interp between index 1 (10) and index 2 (20) at frac 0.5
        assert r.outputs["out1"][0] == pytest.approx(15.0, abs=1e-4)

    def test_bufread_cubic_interp(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=8),
                BufRead(id="br", buffer="buf", index=3.0, interp="cubic"),
            ],
        )
        st = SimState(g)
        data = np.arange(8, dtype=np.float32) * 10.0
        st.set_buffer("buf", data)
        r = simulate(g, n_samples=1, state=st)
        # At integer index, cubic should return exact value
        assert r.outputs["out1"][0] == pytest.approx(30.0, abs=1e-4)

    def test_bufsize(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="bs")],
            nodes=[
                Buffer(id="buf", size=256),
                BufSize(id="bs", buffer="buf"),
            ],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(256.0)

    def test_bufwrite(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=10),
                BufWrite(id="bw", buffer="buf", index=5.0, value="in1"),
                BufRead(id="br", buffer="buf", index=5.0),
            ],
        )
        inp = np.array([42.0], dtype=np.float32)
        r = simulate(g, inputs={"in1": inp})
        # BufWrite writes 42.0 at index 5, BufRead reads from index 5
        # Topo order: buf, br, bw (alphabetical tie-break)
        # Actually: br depends on "buf", bw depends on "buf" and "in1"
        # So br and bw both depend on buf. Alphabetical: br < bw
        # br reads BEFORE bw writes -> reads 0.0
        # Let's verify the buffer was written
        assert r.state.get_buffer("buf")[5] == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# G. Integration tests using conftest fixtures
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_stereo_gain(self, stereo_gain_graph: Graph) -> None:
        n = 32
        inp1 = np.ones(n, dtype=np.float32) * 0.5
        inp2 = np.ones(n, dtype=np.float32) * 0.3
        r = simulate(
            stereo_gain_graph, inputs={"in1": inp1, "in2": inp2}, params={"gain": 2.0}
        )
        np.testing.assert_allclose(r.outputs["out1"], 1.0, atol=1e-6)
        np.testing.assert_allclose(r.outputs["out2"], 0.6, atol=1e-6)

    def test_onepole(self, onepole_graph: Graph) -> None:
        inp = np.ones(30, dtype=np.float32)
        r = simulate(onepole_graph, inputs={"in1": inp})
        # Analytical: y[n] = 1 - 0.5^(n+1) with default coeff=0.5
        for n in range(30):
            expected = 1.0 - 0.5 ** (n + 1)
            assert r.outputs["out1"][n] == pytest.approx(expected, abs=1e-5)

    def test_fbdelay_echo(self, fbdelay_graph: Graph) -> None:
        """Impulse through fbdelay should produce delayed echo."""
        n = 500
        inp = np.zeros(n, dtype=np.float32)
        inp[0] = 1.0
        r = simulate(
            fbdelay_graph,
            inputs={"in1": inp},
            params={"delay_ms": 5.0, "feedback": 0.0, "mix": 1.0},
        )
        # delay_ms=5, sr=44100 -> tap = 5 * 44.1 = 220.5 samples
        # With mix=1.0, output is entirely the delayed signal
        # First non-zero output should appear around sample 220
        out = r.outputs["out1"]
        # Find first significant output after sample 100
        peak_idx = int(np.argmax(np.abs(out[100:]))) + 100
        assert 200 <= peak_idx <= 240

    def test_subgraph_expansion(self) -> None:
        """Subgraph auto-expansion works with simulate."""
        inner = Graph(
            name="inner",
            inputs=[AudioInput(id="x")],
            outputs=[AudioOutput(id="y", source="doubled")],
            nodes=[BinOp(id="doubled", op="mul", a="x", b=2.0)],
        )
        outer = Graph(
            name="outer",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sg")],
            nodes=[Subgraph(id="sg", graph=inner, inputs={"x": "in1"})],
        )
        inp = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        r = simulate(outer, inputs={"in1": inp})
        np.testing.assert_allclose(r.outputs["out1"], inp * 2.0, atol=1e-6)

    def test_state_persistence(self) -> None:
        """State persists across multiple simulate() calls."""
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="a1")],
            nodes=[Accum(id="a1", incr=1.0, reset=0.0)],
        )
        r1 = simulate(g, n_samples=3)
        assert r1.outputs["out1"][-1] == pytest.approx(3.0)
        r2 = simulate(g, n_samples=3, state=r1.state)
        assert r2.outputs["out1"][-1] == pytest.approx(6.0)

    def test_all_node_types_smoke(self) -> None:
        """Smoke test that exercises every node type without crashing."""
        g = Graph(
            name="smoke",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="final")],
            params=[
                Param(name="freq", default=440.0),
                Param(name="gain", default=0.5),
            ],
            sample_rate=44100.0,
            nodes=[
                # Pure
                Constant(id="one", value=1.0),
                BinOp(id="sum1", op="add", a="in1", b="one"),
                UnaryOp(id="neg1", op="neg", a="sum1"),
                Clamp(id="cl1", a="neg1", lo=-1.0, hi=1.0),
                Compare(id="cmp1", op="gt", a="cl1", b=0.0),
                Select(id="sel1", cond="cmp1", a="cl1", b=0.0),
                Wrap(id="wr1", a="sel1", lo=0.0, hi=1.0),
                Fold(id="fo1", a="wr1", lo=0.0, hi=1.0),
                Mix(id="mx1", a="fo1", b=0.5, t=0.5),
                Scale(id="sc1", a="mx1", in_lo=0.0, in_hi=1.0, out_lo=-1.0, out_hi=1.0),
                # Oscillators
                Phasor(id="ph1", freq="freq"),
                SinOsc(id="sin1", freq="freq"),
                TriOsc(id="tri1", freq="freq"),
                SawOsc(id="saw1", freq="freq"),
                PulseOsc(id="pul1", freq="freq", width=0.5),
                # Noise
                Noise(id="ns1"),
                # Delay
                DelayLine(id="dl1", max_samples=100),
                DelayWrite(id="dw1", delay="dl1", value="sc1"),
                DelayRead(id="dr1", delay="dl1", tap=10.0),
                DelayRead(id="dr2", delay="dl1", tap=5.5, interp="linear"),
                DelayRead(id="dr3", delay="dl1", tap=5.5, interp="cubic"),
                # Buffer
                Buffer(id="buf1", size=64),
                BufRead(id="br1", buffer="buf1", index=0.0),
                BufWrite(id="bw1", buffer="buf1", index=0.0, value="sc1"),
                BufSize(id="bs1", buffer="buf1"),
                # Filters
                OnePole(id="lp1", a="sc1", coeff=0.3),
                DCBlock(id="dcb1", a="lp1"),
                Allpass(id="ap1", a="dcb1", coeff=0.5),
                Biquad(id="bq1", a="ap1", b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0),
                SVF(id="svf1", a="bq1", freq=1000.0, q=0.707, mode="lp"),
                # State/timing
                History(id="h1", init=0.0, input="svf1"),
                Delta(id="dt1", a="svf1"),
                Change(id="ch1", a="svf1"),
                SampleHold(id="sh1", a="svf1", trig="cmp1"),
                Latch(id="la1", a="svf1", trig="cmp1"),
                Accum(id="ac1", incr="gain", reset=0.0),
                Counter(id="ct1", trig="cmp1", max=10.0),
                RateDiv(id="rd1", a="svf1", divisor=4.0),
                SmoothParam(id="sp1", a="gain", coeff=0.9),
                Peek(id="pk1", a="svf1"),
                # Final mix
                BinOp(id="final", op="mul", a="svf1", b="gain"),
            ],
        )
        inp = np.random.default_rng(99).standard_normal(64).astype(np.float32)
        r = simulate(g, inputs={"in1": inp})
        assert r.outputs["out1"].shape == (64,)
        assert np.all(np.isfinite(r.outputs["out1"]))

    def test_gen_dsp_graph(self, gen_dsp_graph: Graph) -> None:
        """Test the rich gen_dsp_graph fixture from conftest."""
        n = 64
        inp1 = np.random.default_rng(1).standard_normal(n).astype(np.float32) * 0.1
        inp2 = np.random.default_rng(2).standard_normal(n).astype(np.float32) * 0.1
        r = simulate(gen_dsp_graph, inputs={"in1": inp1, "in2": inp2})
        assert "out1" in r.outputs
        assert "out2" in r.outputs
        assert r.outputs["out1"].shape == (n,)
        assert np.all(np.isfinite(r.outputs["out1"]))
        assert np.all(np.isfinite(r.outputs["out2"]))

    def test_param_change_between_calls(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="scaled")],
            params=[Param(name="gain", default=1.0)],
            nodes=[BinOp(id="scaled", op="mul", a="in1", b="gain")],
        )
        inp = np.ones(5, dtype=np.float32)
        r1 = simulate(g, inputs={"in1": inp}, params={"gain": 0.5})
        np.testing.assert_allclose(r1.outputs["out1"], 0.5, atol=1e-6)
        r2 = simulate(g, inputs={"in1": inp}, params={"gain": 2.0}, state=r1.state)
        np.testing.assert_allclose(r2.outputs["out1"], 2.0, atol=1e-6)


# ---------------------------------------------------------------------------
# H. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_sample(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="c1")],
            nodes=[Constant(id="c1", value=7.0)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(7.0)

    def test_zero_input_generator(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="n1")],
            nodes=[Noise(id="n1")],
        )
        r = simulate(g, n_samples=10)
        assert r.outputs["out1"].shape == (10,)

    def test_literal_float_refs(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[BinOp(id="r", op="add", a=3.5, b=1.5)],
        )
        r = simulate(g, n_samples=1)
        assert r.outputs["out1"][0] == pytest.approx(5.0)

    def test_invalid_graph_raises(self) -> None:
        g = Graph(
            name="bad",
            outputs=[AudioOutput(id="out1", source="missing")],
        )
        with pytest.raises(ValueError, match="Invalid graph"):
            SimState(g)

    def test_n_samples_mismatch_with_input(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="g1")],
            nodes=[BinOp(id="g1", op="mul", a="in1", b=1.0)],
        )
        with pytest.raises(ValueError, match="does not match input length"):
            simulate(g, inputs={"in1": np.ones(10, dtype=np.float32)}, n_samples=5)


# ---------------------------------------------------------------------------
# New ops and node types (v0.2) -- simulation correctness
# ---------------------------------------------------------------------------


class TestNewOpSimulation:
    """Simulation correctness for new UnaryOp, BinOp, Compare ops and new nodes."""

    def _run_unary(self, op: str, val: float) -> float:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="x")],
            nodes=[UnaryOp(id="x", op=op, a="in1")],
        )
        inp = np.array([val], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, sample_rate=SR)
        return float(res.outputs["out1"][0])

    def _run_binop(self, op: str, a: float, b: float) -> float:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="x")],
            nodes=[BinOp(id="x", op=op, a="in1", b=b)],
        )
        inp = np.array([a], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, sample_rate=SR)
        return float(res.outputs["out1"][0])

    def test_tan(self) -> None:
        assert self._run_unary("tan", 1.0) == pytest.approx(math.tan(1.0), rel=1e-5)

    def test_sinh(self) -> None:
        assert self._run_unary("sinh", 1.0) == pytest.approx(math.sinh(1.0), rel=1e-5)

    def test_cosh(self) -> None:
        assert self._run_unary("cosh", 1.0) == pytest.approx(math.cosh(1.0), rel=1e-5)

    def test_asinh(self) -> None:
        assert self._run_unary("asinh", 2.0) == pytest.approx(math.asinh(2.0), rel=1e-5)

    def test_acosh(self) -> None:
        assert self._run_unary("acosh", 2.0) == pytest.approx(math.acosh(2.0), rel=1e-5)

    def test_atanh(self) -> None:
        assert self._run_unary("atanh", 0.5) == pytest.approx(math.atanh(0.5), rel=1e-5)

    def test_exp2(self) -> None:
        assert self._run_unary("exp2", 3.0) == pytest.approx(8.0, rel=1e-5)

    def test_log2(self) -> None:
        assert self._run_unary("log2", 8.0) == pytest.approx(3.0, rel=1e-5)

    def test_log10(self) -> None:
        assert self._run_unary("log10", 100.0) == pytest.approx(2.0, rel=1e-5)

    def test_fract(self) -> None:
        assert self._run_unary("fract", 3.7) == pytest.approx(0.7, rel=1e-5)

    def test_fract_negative(self) -> None:
        # fract(-0.3) = -0.3 - floor(-0.3) = -0.3 - (-1) = 0.7
        assert self._run_unary("fract", -0.3) == pytest.approx(0.7, rel=1e-5)

    def test_trunc(self) -> None:
        assert self._run_unary("trunc", 3.7) == pytest.approx(3.0)

    def test_trunc_negative(self) -> None:
        assert self._run_unary("trunc", -3.7) == pytest.approx(-3.0)

    def test_not_zero(self) -> None:
        assert self._run_unary("not", 0.0) == 1.0

    def test_not_nonzero(self) -> None:
        assert self._run_unary("not", 5.0) == 0.0

    def test_bool_zero(self) -> None:
        assert self._run_unary("bool", 0.0) == 0.0

    def test_bool_nonzero(self) -> None:
        assert self._run_unary("bool", -3.0) == 1.0

    def test_atan2(self) -> None:
        assert self._run_binop("atan2", 1.0, 1.0) == pytest.approx(
            math.atan2(1.0, 1.0), rel=1e-5
        )

    def test_hypot(self) -> None:
        assert self._run_binop("hypot", 3.0, 4.0) == pytest.approx(5.0, rel=1e-5)

    def test_absdiff(self) -> None:
        assert self._run_binop("absdiff", 3.0, 5.0) == pytest.approx(2.0)

    def test_step_below(self) -> None:
        assert self._run_binop("step", 0.3, 0.5) == 0.0

    def test_step_above(self) -> None:
        assert self._run_binop("step", 0.7, 0.5) == 1.0

    def test_step_equal(self) -> None:
        assert self._run_binop("step", 0.5, 0.5) == 1.0

    def test_and_both_true(self) -> None:
        assert self._run_binop("and", 1.0, 2.0) == 1.0

    def test_and_one_false(self) -> None:
        assert self._run_binop("and", 1.0, 0.0) == 0.0

    def test_and_both_false(self) -> None:
        assert self._run_binop("and", 0.0, 0.0) == 0.0

    def test_or_both_true(self) -> None:
        assert self._run_binop("or", 1.0, 2.0) == 1.0

    def test_or_one_true(self) -> None:
        assert self._run_binop("or", 0.0, 3.0) == 1.0

    def test_or_both_false(self) -> None:
        assert self._run_binop("or", 0.0, 0.0) == 0.0

    def test_xor_both_true(self) -> None:
        assert self._run_binop("xor", 1.0, 2.0) == 0.0

    def test_xor_one_true(self) -> None:
        assert self._run_binop("xor", 1.0, 0.0) == 1.0

    def test_xor_both_false(self) -> None:
        assert self._run_binop("xor", 0.0, 0.0) == 0.0

    def test_compare_neq(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="x")],
            nodes=[Compare(id="x", op="neq", a="in1", b=0.0)],
        )
        inp = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, sample_rate=SR)
        np.testing.assert_array_equal(res.outputs["out1"], [0.0, 1.0, 0.0])

    def test_pass_node(self) -> None:
        g = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="x")],
            nodes=[Pass(id="x", a="in1")],
        )
        inp = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, sample_rate=SR)
        np.testing.assert_array_equal(res.outputs["out1"], inp)

    def test_named_constant_pi(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="x")],
            nodes=[NamedConstant(id="x", op="pi")],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(math.pi, rel=1e-5)

    def test_named_constant_e(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="x")],
            nodes=[NamedConstant(id="x", op="e")],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(math.e, rel=1e-5)

    def test_smoothstep_below(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="x")],
            nodes=[Smoothstep(id="x", a=-1.0, edge0=0.0, edge1=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(0.0)

    def test_smoothstep_above(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="x")],
            nodes=[Smoothstep(id="x", a=2.0, edge0=0.0, edge1=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(1.0)

    def test_smoothstep_mid(self) -> None:
        g = Graph(
            name="t",
            outputs=[AudioOutput(id="out1", source="x")],
            nodes=[Smoothstep(id="x", a=0.5, edge0=0.0, edge1=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        # t=0.5, result = 0.5*0.5*(3-2*0.5) = 0.25*2 = 0.5
        # Actually: 0.25 * 2.0 = 0.5
        assert float(res.outputs["out1"][0]) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Gate / Selector routing
# ---------------------------------------------------------------------------


class TestGateRouting:
    def _gate_graph(self, count: int = 3) -> Graph:
        """1-to-N gate with N outputs."""
        nodes = [
            GateRoute(id="gr", a="in1", index="idx", count=count),
        ]
        outputs = []
        for ch in range(1, count + 1):
            nid = f"go{ch}"
            nodes.append(GateOut(id=nid, gate="gr", channel=ch))
            outputs.append(AudioOutput(id=f"out{ch}", source=nid))
        return Graph(
            name="gate",
            inputs=[AudioInput(id="in1")],
            outputs=outputs,
            params=[Param(name="idx", min=0.0, max=float(count), default=0.0)],
            nodes=nodes,
        )

    def test_gate_index_zero_all_muted(self) -> None:
        g = self._gate_graph(3)
        inp = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, params={"idx": 0.0}, sample_rate=SR)
        for ch in range(1, 4):
            np.testing.assert_array_equal(res.outputs[f"out{ch}"], 0.0)

    def test_gate_index_1_routes_to_ch1(self) -> None:
        g = self._gate_graph(3)
        inp = np.array([0.7, 0.7], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, params={"idx": 1.0}, sample_rate=SR)
        np.testing.assert_array_almost_equal(res.outputs["out1"], 0.7)
        np.testing.assert_array_equal(res.outputs["out2"], 0.0)
        np.testing.assert_array_equal(res.outputs["out3"], 0.0)

    def test_gate_index_2_routes_to_ch2(self) -> None:
        g = self._gate_graph(3)
        inp = np.array([0.5], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, params={"idx": 2.0}, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == 0.0
        assert float(res.outputs["out2"][0]) == pytest.approx(0.5)
        assert float(res.outputs["out3"][0]) == 0.0

    def test_gate_index_clamps_to_count(self) -> None:
        g = self._gate_graph(2)
        inp = np.array([1.0], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, params={"idx": 5.0}, sample_rate=SR)
        # Clamped to 2 -> ch2 gets signal
        assert float(res.outputs["out1"][0]) == 0.0
        assert float(res.outputs["out2"][0]) == pytest.approx(1.0)

    def test_gate_negative_index_clamps_to_zero(self) -> None:
        g = self._gate_graph(2)
        inp = np.array([1.0], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, params={"idx": -1.0}, sample_rate=SR)
        # Clamped to 0 -> all muted
        np.testing.assert_array_equal(res.outputs["out1"], 0.0)
        np.testing.assert_array_equal(res.outputs["out2"], 0.0)

    def test_gate_float_index_truncated(self) -> None:
        g = self._gate_graph(2)
        inp = np.array([1.0], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, params={"idx": 1.9}, sample_rate=SR)
        # int(1.9) = 1 -> ch1
        assert float(res.outputs["out1"][0]) == pytest.approx(1.0)
        assert float(res.outputs["out2"][0]) == 0.0


class TestSelector:
    def _selector_graph(self, n: int = 3) -> Graph:
        """N-to-1 selector."""
        input_ids = [f"in{i}" for i in range(1, n + 1)]
        return Graph(
            name="selector",
            inputs=[AudioInput(id=iid) for iid in input_ids],
            outputs=[AudioOutput(id="out1", source="mux")],
            params=[Param(name="idx", min=0.0, max=float(n), default=0.0)],
            nodes=[
                Selector(id="mux", index="idx", inputs=input_ids),
            ],
        )

    def test_selector_index_zero_outputs_zero(self) -> None:
        g = self._selector_graph(3)
        ins = {f"in{i}": np.array([float(i)], dtype=np.float32) for i in range(1, 4)}
        res = simulate(g, inputs=ins, params={"idx": 0.0}, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == 0.0

    def test_selector_index_1_selects_first(self) -> None:
        g = self._selector_graph(3)
        ins = {f"in{i}": np.array([float(i)], dtype=np.float32) for i in range(1, 4)}
        res = simulate(g, inputs=ins, params={"idx": 1.0}, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(1.0)

    def test_selector_index_3_selects_third(self) -> None:
        g = self._selector_graph(3)
        ins = {f"in{i}": np.array([float(i)], dtype=np.float32) for i in range(1, 4)}
        res = simulate(g, inputs=ins, params={"idx": 3.0}, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(3.0)

    def test_selector_index_clamps_to_n(self) -> None:
        g = self._selector_graph(2)
        ins = {
            "in1": np.array([10.0], dtype=np.float32),
            "in2": np.array([20.0], dtype=np.float32),
        }
        res = simulate(g, inputs=ins, params={"idx": 5.0}, sample_rate=SR)
        # Clamped to 2 -> selects in2
        assert float(res.outputs["out1"][0]) == pytest.approx(20.0)

    def test_selector_negative_index_clamps_to_zero(self) -> None:
        g = self._selector_graph(2)
        ins = {
            "in1": np.array([10.0], dtype=np.float32),
            "in2": np.array([20.0], dtype=np.float32),
        }
        res = simulate(g, inputs=ins, params={"idx": -1.0}, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == 0.0

    def test_selector_float_index_truncated(self) -> None:
        g = self._selector_graph(3)
        ins = {f"in{i}": np.array([float(i)], dtype=np.float32) for i in range(1, 4)}
        res = simulate(g, inputs=ins, params={"idx": 2.7}, sample_rate=SR)
        # int(2.7) = 2 -> selects in2
        assert float(res.outputs["out1"][0]) == pytest.approx(2.0)

    def test_selector_with_literal_inputs(self) -> None:
        g = Graph(
            name="sel_lit",
            outputs=[AudioOutput(id="out1", source="mux")],
            params=[Param(name="idx", min=0.0, max=2.0, default=1.0)],
            nodes=[
                Selector(id="mux", index="idx", inputs=[42.0, 99.0]),
            ],
        )
        res = simulate(g, n_samples=1, params={"idx": 2.0}, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(99.0)


# ---------------------------------------------------------------------------
# Slide, SampleRate, convert ops
# ---------------------------------------------------------------------------


class TestSlideSimulate:
    def test_slide_instant_tracking(self) -> None:
        """With up=1 and down=1, output should track input instantly."""
        g = Graph(
            name="slide_instant",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sl")],
            nodes=[Slide(id="sl", a="in1", up=1.0, down=1.0)],
        )
        inp = np.array([1.0, 0.5, 0.0, -1.0], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, sample_rate=SR)
        np.testing.assert_allclose(res.outputs["out1"], inp, atol=1e-6)

    def test_slide_asymmetric_slew(self) -> None:
        """With large slide values, output should slew towards the input."""
        g = Graph(
            name="slide_slew",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sl")],
            nodes=[Slide(id="sl", a="in1", up=100.0, down=100.0)],
        )
        # Step from 0 to 1: output should ramp up slowly
        inp = np.ones(10, dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, sample_rate=SR)
        out = res.outputs["out1"]
        # First sample: prev=0, x=1, s=100 -> 0 + (1-0)/100 = 0.01
        assert float(out[0]) == pytest.approx(0.01, abs=1e-4)
        # Output should be monotonically increasing
        for i in range(1, len(out)):
            assert float(out[i]) > float(out[i - 1])

    def test_slide_sub_one_clamped(self) -> None:
        """Slide values < 1 should be clamped to 1 (instant tracking)."""
        g = Graph(
            name="slide_clamp",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sl")],
            nodes=[Slide(id="sl", a="in1", up=0.0, down=0.0)],
        )
        inp = np.array([1.0, 0.0], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, sample_rate=SR)
        np.testing.assert_allclose(res.outputs["out1"], inp, atol=1e-6)


class TestSampleRateSimulate:
    def test_samplerate_returns_sr(self) -> None:
        g = Graph(
            name="sr_test",
            outputs=[AudioOutput(id="out1", source="sr_node")],
            nodes=[SampleRate(id="sr_node")],
        )
        res = simulate(g, n_samples=4, sample_rate=48000.0)
        expected = np.full(4, 48000.0, dtype=np.float32)
        np.testing.assert_allclose(res.outputs["out1"], expected)


class TestConvertOpsSimulate:
    def test_mtof_a440(self) -> None:
        g = Graph(
            name="mtof_test",
            outputs=[AudioOutput(id="out1", source="conv")],
            nodes=[UnaryOp(id="conv", op="mtof", a=69.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(440.0, rel=1e-5)

    def test_ftom_440(self) -> None:
        g = Graph(
            name="ftom_test",
            outputs=[AudioOutput(id="out1", source="conv")],
            nodes=[UnaryOp(id="conv", op="ftom", a=440.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(69.0, rel=1e-5)

    def test_atodb_unity(self) -> None:
        g = Graph(
            name="atodb_test",
            outputs=[AudioOutput(id="out1", source="conv")],
            nodes=[UnaryOp(id="conv", op="atodb", a=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(0.0, abs=1e-5)

    def test_dbtoa_zero(self) -> None:
        g = Graph(
            name="dbtoa_test",
            outputs=[AudioOutput(id="out1", source="conv")],
            nodes=[UnaryOp(id="conv", op="dbtoa", a=0.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(1.0, rel=1e-5)

    def test_mtof_ftom_roundtrip(self) -> None:
        g = Graph(
            name="roundtrip",
            outputs=[AudioOutput(id="out1", source="back")],
            nodes=[
                UnaryOp(id="freq", op="mtof", a=60.0),
                UnaryOp(id="back", op="ftom", a="freq"),
            ],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(60.0, rel=1e-5)

    def test_atodb_dbtoa_roundtrip(self) -> None:
        g = Graph(
            name="roundtrip_db",
            outputs=[AudioOutput(id="out1", source="back")],
            nodes=[
                UnaryOp(id="db", op="atodb", a=0.5),
                UnaryOp(id="back", op="dbtoa", a="db"),
            ],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(0.5, rel=1e-5)


class TestElapsedSimulate:
    def test_elapsed_counts_samples(self) -> None:
        g = Graph(
            name="elapsed_test",
            outputs=[AudioOutput(id="out1", source="el")],
            nodes=[Elapsed(id="el")],
        )
        res = simulate(g, n_samples=5, sample_rate=SR)
        expected = np.array([0.0, 1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        np.testing.assert_allclose(res.outputs["out1"], expected)

    def test_elapsed_reset(self) -> None:
        g = Graph(
            name="elapsed_test",
            outputs=[AudioOutput(id="out1", source="el")],
            nodes=[Elapsed(id="el")],
        )
        res1 = simulate(g, n_samples=3, sample_rate=SR)
        assert float(res1.outputs["out1"][2]) == pytest.approx(2.0)
        # simulate again from scratch
        res2 = simulate(g, n_samples=3, sample_rate=SR)
        assert float(res2.outputs["out1"][0]) == pytest.approx(0.0)


class TestMulAccumSimulate:
    def test_mulaccum_basic(self) -> None:
        g = Graph(
            name="ma_test",
            outputs=[AudioOutput(id="out1", source="ma")],
            nodes=[MulAccum(id="ma", incr=2.0, reset=0.0)],
        )
        res = simulate(g, n_samples=4, sample_rate=SR)
        # prod starts at 1.0, multiplied by 2 each sample: 2, 4, 8, 16
        expected = np.array([2.0, 4.0, 8.0, 16.0], dtype=np.float32)
        np.testing.assert_allclose(res.outputs["out1"], expected)

    def test_mulaccum_with_reset(self) -> None:
        g = Graph(
            name="ma_test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="ma")],
            nodes=[MulAccum(id="ma", incr=2.0, reset="in1")],
        )
        # reset > 0 on sample 2
        inp = np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, sample_rate=SR)
        # sample 0: prod=1*2=2, sample 1: 2*2=4
        # sample 2: reset -> prod=1, then *2=2
        # sample 3: 2*2=4
        expected = np.array([2.0, 4.0, 2.0, 4.0], dtype=np.float32)
        np.testing.assert_allclose(res.outputs["out1"], expected)


class TestPhasewrapSimulate:
    def test_phasewrap_values(self) -> None:
        g = Graph(
            name="pw_test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="pw")],
            nodes=[UnaryOp(id="pw", op="phasewrap", a="in1")],
        )
        twopi = 2.0 * math.pi
        inp = np.array([0.0, math.pi, twopi, -twopi, 3 * math.pi], dtype=np.float32)
        res = simulate(g, inputs={"in1": inp}, sample_rate=SR)
        out = res.outputs["out1"]
        assert float(out[0]) == pytest.approx(0.0, abs=1e-5)
        # pi is at the boundary; float32 may give +pi or -pi (both correct)
        assert abs(float(out[1])) == pytest.approx(math.pi, abs=1e-4)
        assert abs(float(out[2])) < 1e-4  # 2pi wraps to ~0
        assert abs(float(out[3])) < 1e-4  # -2pi wraps to ~0
        assert abs(float(out[4])) == pytest.approx(
            math.pi, abs=1e-4
        )  # 3pi wraps to +/-pi


class TestCycleSimulate:
    def test_cycle_reads_buffer(self) -> None:
        g = Graph(
            name="cy_test",
            outputs=[AudioOutput(id="out1", source="cy")],
            nodes=[
                Buffer(id="buf", size=4),
                BufWrite(id="bw0", buffer="buf", index=0.0, value=10.0),
                BufWrite(id="bw1", buffer="buf", index=1.0, value=20.0),
                BufWrite(id="bw2", buffer="buf", index=2.0, value=30.0),
                BufWrite(id="bw3", buffer="buf", index=3.0, value=40.0),
                Cycle(id="cy", buffer="buf", phase=0.0),
            ],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        # phase=0.0 should read index 0
        assert float(res.outputs["out1"][0]) == pytest.approx(10.0, rel=1e-4)

    def test_cycle_wraps_phase(self) -> None:
        g = Graph(
            name="cy_test",
            outputs=[AudioOutput(id="out1", source="cy")],
            nodes=[
                Buffer(id="buf", size=4),
                BufWrite(id="bw0", buffer="buf", index=0.0, value=100.0),
                Cycle(id="cy", buffer="buf", phase=1.0),
            ],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        # phase=1.0 wraps to 0.0
        assert float(res.outputs["out1"][0]) == pytest.approx(100.0, rel=1e-4)

    def test_buffer_fill_sine(self) -> None:
        """Buffer with fill='sine' should be pre-filled with a sine cycle."""
        g = Graph(
            name="fill_test",
            outputs=[AudioOutput(id="out1", source="cy")],
            nodes=[
                Buffer(id="buf", size=512, fill="sine"),
                # phase=0.25 -> quarter cycle -> should read ~1.0 (sin(pi/2))
                Cycle(id="cy", buffer="buf", phase=0.25),
            ],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(1.0, abs=0.02)

    def test_buffer_fill_sine_zero_crossing(self) -> None:
        """phase=0.0 and phase=0.5 should both be ~0.0."""
        g = Graph(
            name="fill_test",
            outputs=[AudioOutput(id="out1", source="cy")],
            nodes=[
                Buffer(id="buf", size=512, fill="sine"),
                Cycle(id="cy", buffer="buf", phase=0.0),
            ],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(0.0, abs=0.02)


class TestWaveSimulate:
    def test_wave_reads_center(self) -> None:
        g = Graph(
            name="wv_test",
            outputs=[AudioOutput(id="out1", source="wv")],
            nodes=[
                Buffer(id="buf", size=4),
                BufWrite(id="bw0", buffer="buf", index=0.0, value=10.0),
                BufWrite(id="bw1", buffer="buf", index=1.0, value=20.0),
                BufWrite(id="bw2", buffer="buf", index=2.0, value=30.0),
                BufWrite(id="bw3", buffer="buf", index=3.0, value=40.0),
                Wave(id="wv", buffer="buf", phase=0.0),
            ],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        # phase=0 maps to center of buffer (index 2)
        assert float(res.outputs["out1"][0]) == pytest.approx(30.0, abs=5.0)


class TestLookupSimulate:
    def test_lookup_reads_start(self) -> None:
        g = Graph(
            name="lu_test",
            outputs=[AudioOutput(id="out1", source="lu")],
            nodes=[
                Buffer(id="buf", size=4),
                BufWrite(id="bw0", buffer="buf", index=0.0, value=10.0),
                BufWrite(id="bw1", buffer="buf", index=1.0, value=20.0),
                BufWrite(id="bw2", buffer="buf", index=2.0, value=30.0),
                BufWrite(id="bw3", buffer="buf", index=3.0, value=40.0),
                Lookup(id="lu", buffer="buf", index=0.0),
            ],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        # index=0.0 maps to buffer start
        assert float(res.outputs["out1"][0]) == pytest.approx(10.0, rel=1e-4)

    def test_lookup_reads_end(self) -> None:
        g = Graph(
            name="lu_test",
            outputs=[AudioOutput(id="out1", source="lu")],
            nodes=[
                Buffer(id="buf", size=4),
                BufWrite(id="bw0", buffer="buf", index=0.0, value=10.0),
                BufWrite(id="bw3", buffer="buf", index=3.0, value=40.0),
                Lookup(id="lu", buffer="buf", index=1.0),
            ],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        # index=1.0 maps to last sample
        assert float(res.outputs["out1"][0]) == pytest.approx(40.0, rel=1e-4)


# ---------------------------------------------------------------------------
# P. Batch 3: reverse ops, p-comparisons, angle/sample convert, DSP safety,
#             fast approx, splat
# ---------------------------------------------------------------------------


class TestBatch3Simulate:
    """Correctness tests for batch 3 operators."""

    def test_rsub(self) -> None:
        g = Graph(
            name="rsub_test",
            outputs=[AudioOutput(id="out1", source="rsb")],
            nodes=[BinOp(id="rsb", op="rsub", a=3.0, b=5.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(2.0)

    def test_rdiv(self) -> None:
        g = Graph(
            name="rdiv_test",
            outputs=[AudioOutput(id="out1", source="rdv")],
            nodes=[BinOp(id="rdv", op="rdiv", a=2.0, b=10.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(5.0)

    def test_rmod(self) -> None:
        g = Graph(
            name="rmod_test",
            outputs=[AudioOutput(id="out1", source="rmd")],
            nodes=[BinOp(id="rmd", op="rmod", a=3.0, b=7.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(1.0)

    def test_gtp_pass(self) -> None:
        g = Graph(
            name="gtp_test",
            outputs=[AudioOutput(id="out1", source="gtp_n")],
            nodes=[BinOp(id="gtp_n", op="gtp", a=5.0, b=3.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(5.0)

    def test_gtp_zero(self) -> None:
        g = Graph(
            name="gtp_test",
            outputs=[AudioOutput(id="out1", source="gtp_n")],
            nodes=[BinOp(id="gtp_n", op="gtp", a=2.0, b=3.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(0.0)

    def test_ltp(self) -> None:
        g = Graph(
            name="ltp_test",
            outputs=[AudioOutput(id="out1", source="ltp_n")],
            nodes=[BinOp(id="ltp_n", op="ltp", a=2.0, b=3.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(2.0)

    def test_eqp(self) -> None:
        g = Graph(
            name="eqp_test",
            outputs=[AudioOutput(id="out1", source="eqp_n")],
            nodes=[BinOp(id="eqp_n", op="eqp", a=3.0, b=3.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(3.0)

    def test_neqp(self) -> None:
        g = Graph(
            name="neqp_test",
            outputs=[AudioOutput(id="out1", source="neqp_n")],
            nodes=[BinOp(id="neqp_n", op="neqp", a=3.0, b=5.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(3.0)

    def test_fastpow(self) -> None:
        g = Graph(
            name="fastpow_test",
            outputs=[AudioOutput(id="out1", source="fp")],
            nodes=[BinOp(id="fp", op="fastpow", a=3.0, b=2.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(9.0)

    def test_degrees(self) -> None:
        g = Graph(
            name="deg_test",
            outputs=[AudioOutput(id="out1", source="deg")],
            nodes=[UnaryOp(id="deg", op="degrees", a=math.pi)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(180.0, rel=1e-4)

    def test_radians(self) -> None:
        g = Graph(
            name="rad_test",
            outputs=[AudioOutput(id="out1", source="rad")],
            nodes=[UnaryOp(id="rad", op="radians", a=180.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(math.pi, rel=1e-4)

    def test_mstosamps(self) -> None:
        g = Graph(
            name="ms2s_test",
            outputs=[AudioOutput(id="out1", source="ms2s")],
            nodes=[UnaryOp(id="ms2s", op="mstosamps", a=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=44100.0)
        assert float(res.outputs["out1"][0]) == pytest.approx(44.1, rel=1e-4)

    def test_sampstoms(self) -> None:
        g = Graph(
            name="s2ms_test",
            outputs=[AudioOutput(id="out1", source="s2ms")],
            nodes=[UnaryOp(id="s2ms", op="sampstoms", a=44.1)],
        )
        res = simulate(g, n_samples=1, sample_rate=44100.0)
        assert float(res.outputs["out1"][0]) == pytest.approx(1.0, rel=1e-4)

    def test_t60(self) -> None:
        g = Graph(
            name="t60_test",
            outputs=[AudioOutput(id="out1", source="t")],
            nodes=[UnaryOp(id="t", op="t60", a=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=44100.0)
        expected = math.exp(-6.9078 / (1.0 * 44100.0))
        assert float(res.outputs["out1"][0]) == pytest.approx(expected, rel=1e-4)

    def test_t60time(self) -> None:
        # t60time is the inverse of t60: given a decay coefficient, compute time
        # Use the coefficient from t60(1.0) at 44100 Hz, should return ~1.0
        coeff = math.exp(-6.9078 / (1.0 * 44100.0))
        g = Graph(
            name="t60time_test",
            outputs=[AudioOutput(id="out1", source="t")],
            nodes=[UnaryOp(id="t", op="t60time", a=coeff)],
        )
        res = simulate(g, n_samples=1, sample_rate=44100.0)
        expected = -6.9078 / (math.log(coeff) * 44100.0)
        assert float(res.outputs["out1"][0]) == pytest.approx(expected, rel=1e-4)
        assert float(res.outputs["out1"][0]) == pytest.approx(1.0, rel=1e-4)

    def test_fixdenorm_normal(self) -> None:
        g = Graph(
            name="fd_test",
            outputs=[AudioOutput(id="out1", source="fd")],
            nodes=[UnaryOp(id="fd", op="fixdenorm", a=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(1.0)

    def test_fixdenorm_tiny(self) -> None:
        g = Graph(
            name="fd_test",
            outputs=[AudioOutput(id="out1", source="fd")],
            nodes=[UnaryOp(id="fd", op="fixdenorm", a=1e-39)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(0.0)

    def test_isdenorm(self) -> None:
        g = Graph(
            name="isd_test",
            outputs=[AudioOutput(id="out1", source="isd")],
            nodes=[UnaryOp(id="isd", op="isdenorm", a=1e-39)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(1.0)

    def test_isdenorm_normal(self) -> None:
        g = Graph(
            name="isd_test",
            outputs=[AudioOutput(id="out1", source="isd")],
            nodes=[UnaryOp(id="isd", op="isdenorm", a=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(0.0)

    def test_fastsin_approx(self) -> None:
        g = Graph(
            name="fs_test",
            outputs=[AudioOutput(id="out1", source="fs")],
            nodes=[UnaryOp(id="fs", op="fastsin", a=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        # Simulation uses exact math.sin
        assert float(res.outputs["out1"][0]) == pytest.approx(math.sin(1.0), rel=1e-4)

    def test_fastcos_approx(self) -> None:
        g = Graph(
            name="fc_test",
            outputs=[AudioOutput(id="out1", source="fc")],
            nodes=[UnaryOp(id="fc", op="fastcos", a=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(math.cos(1.0), rel=1e-4)

    def test_fastexp_approx(self) -> None:
        g = Graph(
            name="fe_test",
            outputs=[AudioOutput(id="out1", source="fe")],
            nodes=[UnaryOp(id="fe", op="fastexp", a=1.0)],
        )
        res = simulate(g, n_samples=1, sample_rate=SR)
        assert float(res.outputs["out1"][0]) == pytest.approx(math.exp(1.0), rel=1e-4)

    def test_splat_accumulates(self) -> None:
        """Splat adds to buffer instead of overwriting."""
        g = Graph(
            name="splat_test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=4),
                Splat(id="sp", buffer="buf", index=0.0, value=1.0),
                BufRead(id="br", buffer="buf", index=0.0),
            ],
        )
        # Run 4 samples, each adds 1.0 to buf[0]
        res = simulate(g, n_samples=4, sample_rate=SR)
        # BufRead has no topo dep on Splat -- it reads *before* write in same sample
        # So output lags by one sample: sample 0 reads 0, sample 1 reads 1, etc.
        assert float(res.outputs["out1"][0]) == pytest.approx(0.0)
        assert float(res.outputs["out1"][1]) == pytest.approx(1.0)
        assert float(res.outputs["out1"][2]) == pytest.approx(2.0)
        assert float(res.outputs["out1"][3]) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# ADSR envelope tests
# ---------------------------------------------------------------------------


class TestADSRSimulation:
    """Test ADSR envelope generator simulation."""

    def _make_adsr_graph(
        self,
        attack_ms: float = 10.0,
        decay_ms: float = 100.0,
        sustain: float = 0.7,
        release_ms: float = 200.0,
    ) -> Graph:
        return Graph(
            name="adsr_sim",
            outputs=[AudioOutput(id="out1", source="env")],
            params=[Param(name="gate")],
            nodes=[
                ADSR(
                    id="env",
                    gate="gate",
                    attack=attack_ms,
                    decay=decay_ms,
                    sustain=sustain,
                    release=release_ms,
                ),
            ],
        )

    def test_idle_output_zero(self) -> None:
        """Gate=0, output should stay at 0."""
        g = self._make_adsr_graph()
        res = simulate(g, n_samples=100, sample_rate=SR)
        assert float(res.outputs["out1"][-1]) == 0.0

    def test_attack_ramp(self) -> None:
        """Gate on -> output should ramp up during attack."""
        g = self._make_adsr_graph(attack_ms=10.0)
        state = SimState(g, sample_rate=SR)
        state.set_param("gate", 1.0)
        res = simulate(g, n_samples=100, state=state, sample_rate=SR)
        out = res.outputs["out1"]
        # After 1 sample, output should be > 0
        assert float(out[1]) > 0.0
        # Output should be monotonically increasing during attack
        for i in range(1, min(50, len(out) - 1)):
            if float(out[i]) >= 1.0:
                break
            assert float(out[i + 1]) >= float(out[i])

    def test_full_adsr_cycle(self) -> None:
        """Full A->D->S->R->idle cycle."""
        # Use very short times at 1000 Hz sample rate for quick testing
        sr = 1000.0
        g = self._make_adsr_graph(
            attack_ms=10.0, decay_ms=20.0, sustain=0.5, release_ms=10.0
        )
        state = SimState(g, sample_rate=sr)

        # Attack + decay + sustain: gate on for 100 samples
        state.set_param("gate", 1.0)
        res = simulate(g, n_samples=100, state=state, sample_rate=sr)
        out = res.outputs["out1"]

        # Attack: 10ms at 1000Hz = 10 samples, rate=0.1/sample.
        # Sample 0: edge detect + first increment -> 0.1
        # Sample 9: reaches 1.0, enters decay
        assert float(out[9]) == pytest.approx(1.0, abs=0.01)

        # After decay (10+20=30 samples), should be near sustain (0.5)
        assert float(out[30]) == pytest.approx(0.5, abs=0.05)

        # Sustain: should hold at 0.5
        assert float(out[50]) == pytest.approx(0.5, abs=0.01)

        # Release: gate off
        state.set_param("gate", 0.0)
        res2 = simulate(g, n_samples=50, state=state, sample_rate=sr)
        out2 = res2.outputs["out1"]

        # After release (10ms = 10 samples at sr=1000), output should reach 0
        # Release ramps from 0.5 at rate 1.0/10 = 0.1/sample, so 5 samples to reach 0
        assert float(out2[6]) == pytest.approx(0.0, abs=0.01)

    def test_retrigger_mid_release(self) -> None:
        """Retrigger during release should resume attack from current level."""
        sr = 1000.0
        g = self._make_adsr_graph(
            attack_ms=10.0, decay_ms=20.0, sustain=0.5, release_ms=100.0
        )
        state = SimState(g, sample_rate=sr)

        # Gate on, run through attack to sustain
        state.set_param("gate", 1.0)
        simulate(g, n_samples=50, state=state, sample_rate=sr)

        # Gate off, start release
        state.set_param("gate", 0.0)
        res = simulate(g, n_samples=10, state=state, sample_rate=sr)
        release_level = float(res.outputs["out1"][-1])
        assert release_level < 0.5  # Should be decreasing
        assert release_level > 0.0  # Not yet at 0

        # Retrigger: gate on again
        state.set_param("gate", 1.0)
        res2 = simulate(g, n_samples=2, state=state, sample_rate=sr)
        retrig_level = float(res2.outputs["out1"][1])
        # Should continue from current output level, not restart from 0
        assert retrig_level > release_level
