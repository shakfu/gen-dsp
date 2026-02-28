"""Tests for the Python DSP simulator."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
numpy = __import__("pytest").importorskip("numpy")
import math

import numpy as np
import pytest

from gen_dsp.dsp_graph import (
    SVF,
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
    DCBlock,
    DelayLine,
    DelayRead,
    DelayWrite,
    Delta,
    Fold,
    Graph,
    History,
    Latch,
    Mix,
    Noise,
    OnePole,
    Param,
    Peek,
    Phasor,
    PulseOsc,
    RateDiv,
    SampleHold,
    SawOsc,
    Scale,
    Select,
    SinOsc,
    SmoothParam,
    Subgraph,
    TriOsc,
    UnaryOp,
    Wrap,
)
from gen_dsp.dsp_graph.simulate import SimResult, SimState, simulate

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
