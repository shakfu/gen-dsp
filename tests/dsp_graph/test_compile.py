"""Tests for C++ code generation from DSP graphs."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
import shutil
import subprocess
import tempfile
from pathlib import Path

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
    TriOsc,
    UnaryOp,
    Wrap,
    compile_graph,
    compile_graph_to_file,
)


class TestStructure:
    """Verify structural elements of generated C++."""

    def test_includes(self, stereo_gain_graph: Graph) -> None:
        code = compile_graph(stereo_gain_graph)
        assert "#include <cmath>" in code
        assert "#include <cstdlib>" in code
        assert "#include <cstdint>" in code

    def test_struct_name_pascal_case(self, stereo_gain_graph: Graph) -> None:
        code = compile_graph(stereo_gain_graph)
        assert "struct StereoGainState {" in code

    def test_function_signatures(self, stereo_gain_graph: Graph) -> None:
        code = compile_graph(stereo_gain_graph)
        assert "StereoGainState* stereo_gain_create(float sr)" in code
        assert "void stereo_gain_destroy(StereoGainState* self)" in code
        assert "stereo_gain_perform(StereoGainState* self, float** ins" in code
        assert "int stereo_gain_num_inputs(void)" in code
        assert "int stereo_gain_num_outputs(void)" in code
        assert "int stereo_gain_num_params(void)" in code

    def test_num_inputs_outputs(self, stereo_gain_graph: Graph) -> None:
        code = compile_graph(stereo_gain_graph)
        assert "return 2; }" in code  # 2 inputs and 2 outputs

    def test_single_name(self) -> None:
        g = Graph(
            name="gain",
            nodes=[Constant(id="c", value=1.0)],
            outputs=[AudioOutput(id="out1", source="c")],
        )
        code = compile_graph(g)
        assert "struct GainState {" in code
        assert "GainState* gain_create(float sr)" in code


class TestNodeEmission:
    """Verify per-node C++ code generation."""

    def test_binop_mul(self, stereo_gain_graph: Graph) -> None:
        code = compile_graph(stereo_gain_graph)
        assert "float scaled1 = in1[i] * gain;" in code

    def test_binop_sub_with_literal(self, onepole_graph: Graph) -> None:
        code = compile_graph(onepole_graph)
        assert "float inv_coeff = 1.0f - coeff;" in code

    def test_binop_add(self, onepole_graph: Graph) -> None:
        code = compile_graph(onepole_graph)
        assert "float result = dry + wet;" in code

    def test_binop_min(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[BinOp(id="r", op="min", a="in1", b=1.0)],
        )
        code = compile_graph(g)
        assert "float r = fminf(in1[i], 1.0f);" in code

    def test_binop_max(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[BinOp(id="r", op="max", a="in1", b=0.0)],
        )
        code = compile_graph(g)
        assert "float r = fmaxf(in1[i], 0.0f);" in code

    def test_binop_mod(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[BinOp(id="r", op="mod", a="in1", b=2.0)],
        )
        code = compile_graph(g)
        assert "float r = fmodf(in1[i], 2.0f);" in code

    def test_binop_pow(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[BinOp(id="r", op="pow", a="in1", b=2.0)],
        )
        code = compile_graph(g)
        assert "float r = powf(in1[i], 2.0f);" in code

    def test_unaryop_sin(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="s")],
            nodes=[UnaryOp(id="s", op="sin", a="in1")],
        )
        code = compile_graph(g)
        assert "float s = sinf(in1[i]);" in code

    def test_unaryop_neg(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="n")],
            nodes=[UnaryOp(id="n", op="neg", a="in1")],
        )
        code = compile_graph(g)
        assert "float n = -in1[i];" in code

    def test_unaryop_floor(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[UnaryOp(id="r", op="floor", a="in1")],
        )
        code = compile_graph(g)
        assert "float r = floorf(in1[i]);" in code

    def test_unaryop_ceil(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[UnaryOp(id="r", op="ceil", a="in1")],
        )
        code = compile_graph(g)
        assert "float r = ceilf(in1[i]);" in code

    def test_unaryop_round(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[UnaryOp(id="r", op="round", a="in1")],
        )
        code = compile_graph(g)
        assert "float r = roundf(in1[i]);" in code

    def test_unaryop_sign(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[UnaryOp(id="r", op="sign", a="in1")],
        )
        code = compile_graph(g)
        assert "in1[i] > 0.0f ? 1.0f" in code
        assert "in1[i] < 0.0f ? -1.0f : 0.0f" in code

    def test_clamp(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Clamp(id="c", a="in1")],
        )
        code = compile_graph(g)
        assert "fminf(fmaxf(in1[i], 0.0f), 1.0f)" in code

    def test_constant(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Constant(id="c", value=3.14)],
        )
        code = compile_graph(g)
        assert "float c = 3.14f;" in code

    def test_phasor(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="p")],
            params=[Param(name="freq", min=0.0, max=20000.0, default=440.0)],
            nodes=[Phasor(id="p", freq="freq")],
        )
        code = compile_graph(g)
        assert "float p = p_phase;" in code
        assert "p_phase += freq / sr;" in code
        assert "m_p_phase" in code

    def test_noise(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="n")],
            nodes=[Noise(id="n")],
        )
        code = compile_graph(g)
        assert "1664525u" in code
        assert "1013904223u" in code
        assert "m_n_seed" in code

    def test_compare(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Compare(id="c", op="gt", a="in1", b=0.0)],
        )
        code = compile_graph(g)
        assert "float c = (float)(in1[i] > 0.0f);" in code

    def test_compare_all_ops(self) -> None:
        expected = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<=", "eq": "=="}
        for op, sym in expected.items():
            g = Graph(
                name="test",
                inputs=[AudioInput(id="in1")],
                outputs=[AudioOutput(id="out1", source="c")],
                nodes=[Compare(id="c", op=op, a="in1", b=0.0)],
            )
            code = compile_graph(g)
            assert f"(float)(in1[i] {sym} 0.0f)" in code

    def test_select(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="s")],
            nodes=[
                Compare(id="cond", op="gt", a="in1", b=0.0),
                Select(id="s", cond="cond", a="in1", b=0.0),
            ],
        )
        code = compile_graph(g)
        assert "float s = cond > 0.0f ? in1[i] : 0.0f;" in code

    def test_wrap(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="w")],
            nodes=[Wrap(id="w", a="in1")],
        )
        code = compile_graph(g)
        assert "w_range" in code
        assert "fmodf" in code
        assert "w_raw" in code

    def test_fold(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="f")],
            nodes=[Fold(id="f", a="in1")],
        )
        code = compile_graph(g)
        assert "f_range" in code
        assert "f_t" in code
        assert "fmodf" in code

    def test_mix(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="m")],
            nodes=[
                Constant(id="one", value=1.0),
                Mix(id="m", a="in1", b="one", t=0.5),
            ],
        )
        code = compile_graph(g)
        assert "float m = in1[i] + (one - in1[i]) * 0.5f;" in code


class TestDeltaChangeState:
    """Verify Delta and Change state management."""

    def test_delta_struct_field(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="d")],
            nodes=[Delta(id="d", a="in1")],
        )
        code = compile_graph(g)
        assert "float m_d_prev;" in code

    def test_delta_init(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="d")],
            nodes=[Delta(id="d", a="in1")],
        )
        code = compile_graph(g)
        assert "self->m_d_prev = 0.0f;" in code

    def test_delta_load_save(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="d")],
            nodes=[Delta(id="d", a="in1")],
        )
        code = compile_graph(g)
        assert "float d_prev = self->m_d_prev;" in code
        assert "self->m_d_prev = d_prev;" in code

    def test_delta_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="d")],
            nodes=[Delta(id="d", a="in1")],
        )
        code = compile_graph(g)
        assert "float d_cur = in1[i];" in code
        assert "float d = d_cur - d_prev;" in code
        assert "d_prev = d_cur;" in code

    def test_change_struct_field(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Change(id="c", a="in1")],
        )
        code = compile_graph(g)
        assert "float m_c_prev;" in code

    def test_change_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Change(id="c", a="in1")],
        )
        code = compile_graph(g)
        assert "float c_cur = in1[i];" in code
        assert "(c_cur != c_prev) ? 1.0f : 0.0f" in code
        assert "c_prev = c_cur;" in code


class TestInverseTrig:
    """Verify inverse trig code generation."""

    def test_atan(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[UnaryOp(id="r", op="atan", a="in1")],
        )
        code = compile_graph(g)
        assert "float r = atanf(in1[i]);" in code

    def test_asin(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[UnaryOp(id="r", op="asin", a="in1")],
        )
        code = compile_graph(g)
        assert "float r = asinf(in1[i]);" in code

    def test_acos(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[UnaryOp(id="r", op="acos", a="in1")],
        )
        code = compile_graph(g)
        assert "float r = acosf(in1[i]);" in code


class TestFilterNodes:
    """Verify filter node code generation."""

    def test_biquad_struct_fields(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="bq")],
            nodes=[Biquad(id="bq", a="in1", b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0)],
        )
        code = compile_graph(g)
        assert "float m_bq_s1;" in code
        assert "float m_bq_s2;" in code

    def test_biquad_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="bq")],
            nodes=[Biquad(id="bq", a="in1", b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0)],
        )
        code = compile_graph(g)
        assert "float bq_in = in1[i];" in code
        assert "float bq = 1.0f * bq_in + bq_s1;" in code
        assert "bq_s1 =" in code
        assert "bq_s2 =" in code

    def test_svf_lp(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="f")],
            params=[Param(name="freq", default=1000.0), Param(name="q", default=0.707)],
            nodes=[SVF(id="f", a="in1", freq="freq", q="q", mode="lp")],
        )
        code = compile_graph(g)
        assert "tanf(" in code
        assert "float f = f_v2;" in code

    def test_svf_hp(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="f")],
            nodes=[SVF(id="f", a="in1", freq=1000.0, q=0.707, mode="hp")],
        )
        code = compile_graph(g)
        assert "float f = in1[i] - f_k * f_v1 - f_v2;" in code

    def test_svf_bp(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="f")],
            nodes=[SVF(id="f", a="in1", freq=1000.0, q=0.707, mode="bp")],
        )
        code = compile_graph(g)
        assert "float f = f_v1;" in code

    def test_svf_notch(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="f")],
            nodes=[SVF(id="f", a="in1", freq=1000.0, q=0.707, mode="notch")],
        )
        code = compile_graph(g)
        assert "float f = in1[i] - f_k * f_v1;" in code

    def test_onepole_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="op")],
            nodes=[OnePole(id="op", a="in1", coeff=0.5)],
        )
        code = compile_graph(g)
        assert "float m_op_prev;" in code
        assert "0.5f * in1[i] + (1.0f - 0.5f) * op_prev" in code
        assert "op_prev = op;" in code

    def test_dcblock_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="dc")],
            nodes=[DCBlock(id="dc", a="in1")],
        )
        code = compile_graph(g)
        assert "float m_dc_xprev;" in code
        assert "float m_dc_yprev;" in code
        assert "0.995f" in code
        assert "dc_xprev = dc_x;" in code
        assert "dc_yprev = dc;" in code

    def test_allpass_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="ap")],
            nodes=[Allpass(id="ap", a="in1", coeff=0.5)],
        )
        code = compile_graph(g)
        assert "float m_ap_xprev;" in code
        assert "float m_ap_yprev;" in code
        assert "ap_xprev = ap_x;" in code
        assert "ap_yprev = ap;" in code


class TestOscillatorNodes:
    """Verify oscillator node code generation."""

    def test_sinosc_compute(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="s")],
            nodes=[SinOsc(id="s", freq=440.0)],
        )
        code = compile_graph(g)
        assert "sinf(6.28318530f * s_phase)" in code
        assert "s_phase +=" in code
        assert "m_s_phase" in code

    def test_triosc_compute(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="t")],
            nodes=[TriOsc(id="t", freq=440.0)],
        )
        code = compile_graph(g)
        assert "4.0f * fabsf(t_phase - 0.5f) - 1.0f" in code
        assert "t_phase +=" in code

    def test_sawosc_compute(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="s")],
            nodes=[SawOsc(id="s", freq=440.0)],
        )
        code = compile_graph(g)
        assert "2.0f * s_phase - 1.0f" in code
        assert "s_phase +=" in code

    def test_pulseosc_compute(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="p")],
            nodes=[PulseOsc(id="p", freq=440.0, width=0.5)],
        )
        code = compile_graph(g)
        assert "p_phase < 0.5f ? 1.0f : -1.0f" in code
        assert "p_phase +=" in code

    def test_oscillator_phase_state(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="s")],
            nodes=[SinOsc(id="s", freq=440.0)],
        )
        code = compile_graph(g)
        assert "float m_s_phase;" in code
        assert "float s_phase = self->m_s_phase;" in code
        assert "self->m_s_phase = s_phase;" in code


class TestStateTimingNodes:
    """Verify state/timing node code generation."""

    def test_sample_hold_struct(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sh")],
            nodes=[SampleHold(id="sh", a="in1", trig=0.0)],
        )
        code = compile_graph(g)
        assert "float m_sh_held;" in code
        assert "float m_sh_ptrig;" in code

    def test_sample_hold_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sh")],
            nodes=[SampleHold(id="sh", a="in1", trig=0.0)],
        )
        code = compile_graph(g)
        assert "sh_held = in1[i];" in code
        assert "float sh = sh_held;" in code

    def test_latch_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="la")],
            nodes=[Latch(id="la", a="in1", trig=0.0)],
        )
        code = compile_graph(g)
        assert "la_ptrig <= 0.0f && la_t > 0.0f" in code
        assert "la_held = in1[i];" in code
        assert "float la = la_held;" in code

    def test_accum_compute(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="ac")],
            nodes=[Accum(id="ac", incr=1.0, reset=0.0)],
        )
        code = compile_graph(g)
        assert "float m_ac_sum;" in code
        assert "ac_sum += 1.0f;" in code
        assert "float ac = ac_sum;" in code

    def test_counter_int_state(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="ct")],
            nodes=[Counter(id="ct", trig=0.0, max=16.0)],
        )
        code = compile_graph(g)
        assert "int m_ct_count;" in code
        assert "ct_count++;" in code
        assert "(int)16.0f" in code
        assert "float ct = (float)ct_count;" in code

    def test_counter_ptrig(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="ct")],
            nodes=[Counter(id="ct", trig=0.0, max=16.0)],
        )
        code = compile_graph(g)
        assert "float m_ct_ptrig;" in code
        assert "ct_ptrig <= 0.0f && ct_t > 0.0f" in code


class TestInterpolatedDelayRead:
    """Verify interpolated delay read code generation."""

    def _make_delay_graph(self, interp: str) -> Graph:
        return Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd")],
            params=[Param(name="tap_pos", min=0.0, max=48000.0, default=100.0)],
            nodes=[
                DelayLine(id="dl", max_samples=48000),
                DelayRead(id="rd", delay="dl", tap="tap_pos", interp=interp),
                DelayWrite(id="dw", delay="dl", value="in1"),
            ],
        )

    def test_none_interp(self) -> None:
        code = compile_graph(self._make_delay_graph("none"))
        assert "rd_pos" in code
        assert "dl_buf[rd_pos]" in code
        # Should NOT have fractional tap
        assert "rd_ftap" not in code

    def test_linear_interp(self) -> None:
        code = compile_graph(self._make_delay_graph("linear"))
        assert "rd_ftap" in code
        assert "rd_itap" in code
        assert "rd_frac" in code
        assert "rd_i0" in code
        assert "rd_i1" in code
        # Linear interpolation formula
        assert "dl_buf[rd_i0]" in code
        assert "dl_buf[rd_i1]" in code

    def test_cubic_interp(self) -> None:
        code = compile_graph(self._make_delay_graph("cubic"))
        assert "rd_ftap" in code
        assert "rd_ym1" in code
        assert "rd_y0" in code
        assert "rd_y1" in code
        assert "rd_y2" in code
        assert "rd_c0" in code
        assert "rd_c1" in code
        assert "rd_c2" in code
        assert "rd_c3" in code


class TestHistoryState:
    """Verify History node state management."""

    def test_history_struct_field(self, onepole_graph: Graph) -> None:
        code = compile_graph(onepole_graph)
        assert "float m_prev;" in code

    def test_history_preloop_load(self, onepole_graph: Graph) -> None:
        code = compile_graph(onepole_graph)
        assert "float prev = self->m_prev;" in code

    def test_history_postloop_save(self, onepole_graph: Graph) -> None:
        code = compile_graph(onepole_graph)
        assert "self->m_prev = prev;" in code

    def test_history_writeback_in_loop(self, onepole_graph: Graph) -> None:
        code = compile_graph(onepole_graph)
        # History write-back: prev = result; (inside loop, after node computations)
        assert "        prev = result;" in code


class TestDelayLine:
    """Verify delay line code generation."""

    def test_delay_struct_fields(self, fbdelay_graph: Graph) -> None:
        code = compile_graph(fbdelay_graph)
        assert "float* m_dline_buf;" in code
        assert "int m_dline_len;" in code
        assert "int m_dline_wr;" in code

    def test_delay_calloc(self, fbdelay_graph: Graph) -> None:
        code = compile_graph(fbdelay_graph)
        assert "calloc(48000, sizeof(float))" in code

    def test_delay_free(self, fbdelay_graph: Graph) -> None:
        code = compile_graph(fbdelay_graph)
        assert "free(self->m_dline_buf);" in code

    def test_delay_write_pointer(self, fbdelay_graph: Graph) -> None:
        code = compile_graph(fbdelay_graph)
        assert "dline_buf[dline_wr]" in code
        assert "dline_wr = (dline_wr + 1) % dline_len;" in code

    def test_delay_read(self, fbdelay_graph: Graph) -> None:
        code = compile_graph(fbdelay_graph)
        assert "dline_wr - (int)(tap)" in code
        assert "dline_buf[delayed_pos]" in code


class TestParamAPI:
    """Verify parameter introspection functions."""

    def test_param_name(self, onepole_graph: Graph) -> None:
        code = compile_graph(onepole_graph)
        assert 'return "coeff";' in code

    def test_param_min_max(self, onepole_graph: Graph) -> None:
        code = compile_graph(onepole_graph)
        assert "return 0.0f;" in code  # min
        assert "return 0.999f;" in code  # max

    def test_set_param(self, onepole_graph: Graph) -> None:
        code = compile_graph(onepole_graph)
        assert "self->p_coeff = value;" in code

    def test_get_param(self, onepole_graph: Graph) -> None:
        code = compile_graph(onepole_graph)
        assert "return self->p_coeff;" in code

    def test_multiple_params(self, fbdelay_graph: Graph) -> None:
        code = compile_graph(fbdelay_graph)
        assert 'return "delay_ms";' in code
        assert 'return "feedback";' in code
        assert 'return "mix";' in code


class TestEdgeCases:
    """Error conditions and edge cases."""

    def test_empty_graph_compiles(self) -> None:
        g = Graph(name="empty")
        code = compile_graph(g)
        assert "struct EmptyState {" in code
        assert "return 0; }" in code

    def test_invalid_graph_raises(self) -> None:
        g = Graph(
            name="bad",
            nodes=[BinOp(id="a", op="add", a="missing", b=0.0)],
            outputs=[AudioOutput(id="out1", source="a")],
        )
        with pytest.raises(ValueError, match="Invalid graph"):
            compile_graph(g)

    def test_invalid_c_identifier_raises(self) -> None:
        g = Graph(
            name="test",
            nodes=[Constant(id="my-node", value=1.0)],
            outputs=[AudioOutput(id="out1", source="my-node")],
        )
        with pytest.raises(ValueError, match="not a valid C identifier"):
            compile_graph(g)

    def test_invalid_param_name_raises(self) -> None:
        g = Graph(
            name="test",
            params=[Param(name="my param")],
            nodes=[Constant(id="c", value=1.0)],
            outputs=[AudioOutput(id="out1", source="c")],
        )
        with pytest.raises(ValueError, match="not a valid C identifier"):
            compile_graph(g)


class TestCompileToFile:
    """Verify compile_graph_to_file writes to disk."""

    def test_writes_file(self, stereo_gain_graph: Graph, tmp_path: Path) -> None:
        out = compile_graph_to_file(stereo_gain_graph, tmp_path / "build")
        assert out.exists()
        assert out.name == "stereo_gain.cpp"
        assert "StereoGainState" in out.read_text()

    def test_creates_directory(self, onepole_graph: Graph, tmp_path: Path) -> None:
        build_dir = tmp_path / "nested" / "build"
        assert not build_dir.exists()
        out = compile_graph_to_file(onepole_graph, build_dir)
        assert build_dir.is_dir()
        assert out == build_dir / "onepole.cpp"

    def test_returns_path(self, fbdelay_graph: Graph, tmp_path: Path) -> None:
        out = compile_graph_to_file(fbdelay_graph, tmp_path)
        assert isinstance(out, Path)
        assert out.parent == tmp_path


class TestBufferNodes:
    """Verify buffer node code generation."""

    def _make_buf_graph(self, *extra_nodes, output_src="br") -> Graph:
        nodes = [Buffer(id="buf", size=1024)]
        nodes.extend(extra_nodes)
        return Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source=output_src)],
            nodes=nodes,
        )

    def test_buffer_struct_fields(self) -> None:
        g = self._make_buf_graph(
            BufRead(id="br", buffer="buf", index=0.0),
        )
        code = compile_graph(g)
        assert "float* m_buf_buf;" in code
        assert "int m_buf_len;" in code

    def test_buffer_calloc(self) -> None:
        g = self._make_buf_graph(
            BufRead(id="br", buffer="buf", index=0.0),
        )
        code = compile_graph(g)
        assert "calloc(1024, sizeof(float))" in code

    def test_buffer_free(self) -> None:
        g = self._make_buf_graph(
            BufRead(id="br", buffer="buf", index=0.0),
        )
        code = compile_graph(g)
        assert "free(self->m_buf_buf);" in code

    def test_bufread_none_interp(self) -> None:
        g = self._make_buf_graph(
            BufRead(id="br", buffer="buf", index=0.0),
        )
        code = compile_graph(g)
        assert "int br_idx = (int)(0.0f);" in code
        assert "if (br_idx < 0) br_idx = 0;" in code
        assert "if (br_idx >= buf_len) br_idx = buf_len - 1;" in code
        assert "float br = buf_buf[br_idx];" in code

    def test_bufread_linear_interp(self) -> None:
        g = self._make_buf_graph(
            BufRead(id="br", buffer="buf", index=0.0, interp="linear"),
        )
        code = compile_graph(g)
        assert "br_fidx" in code
        assert "br_frac" in code
        assert "br_i0" in code
        assert "br_i1" in code
        assert "br_s0" in code
        assert "br_s1" in code
        # Clamped indices
        assert "if (br_i0 < 0) br_i0 = 0;" in code
        assert "if (br_i1 >= buf_len) br_i1 = buf_len - 1;" in code

    def test_bufread_cubic_interp(self) -> None:
        g = self._make_buf_graph(
            BufRead(id="br", buffer="buf", index=0.0, interp="cubic"),
        )
        code = compile_graph(g)
        assert "br_fidx" in code
        assert "br_ym1" in code
        assert "br_y0" in code
        assert "br_y1" in code
        assert "br_y2" in code
        assert "br_c0" in code
        assert "br_c1" in code
        assert "br_c2" in code
        assert "br_c3" in code
        assert "br_im1" in code
        assert "br_i2" in code

    def test_bufwrite_compute(self) -> None:
        g = self._make_buf_graph(
            BufRead(id="br", buffer="buf", index=0.0),
            BufWrite(id="bw", buffer="buf", index=0.0, value=1.0),
        )
        code = compile_graph(g)
        assert "int bw_idx = (int)(0.0f);" in code
        assert "if (bw_idx >= 0 && bw_idx < buf_len)" in code
        assert "buf_buf[bw_idx] = 1.0f;" in code
        # BufWrite is side-effect only -- no output variable
        assert "float bw " not in code
        assert "float bw=" not in code

    def test_bufsize_compute(self) -> None:
        g = self._make_buf_graph(
            BufSize(id="bs", buffer="buf"),
            output_src="bs",
        )
        code = compile_graph(g)
        assert "float bs = (float)self->m_buf_len;" in code


class TestBufferAPI:
    """Verify buffer introspection API functions."""

    def test_num_buffers(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf1", size=1024),
                Buffer(id="buf2", size=2048),
                BufRead(id="br", buffer="buf1", index=0.0),
            ],
        )
        code = compile_graph(g)
        assert "int test_num_buffers(void) { return 2; }" in code

    def test_buffer_name(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="wt", size=1024),
                BufRead(id="br", buffer="wt", index=0.0),
            ],
        )
        code = compile_graph(g)
        assert 'return "wt";' in code

    def test_buffer_size(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="wt", size=1024),
                BufRead(id="br", buffer="wt", index=0.0),
            ],
        )
        code = compile_graph(g)
        assert "return self->m_wt_len;" in code

    def test_get_buffer(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="wt", size=1024),
                BufRead(id="br", buffer="wt", index=0.0),
            ],
        )
        code = compile_graph(g)
        assert "return self->m_wt_buf;" in code

    def test_set_buffer(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="wt", size=1024),
                BufRead(id="br", buffer="wt", index=0.0),
            ],
        )
        code = compile_graph(g)
        assert "dst = self->m_wt_buf; cap = self->m_wt_len;" in code
        assert "int copy_len = len < cap ? len : cap;" in code
        assert "for (int i = 0; i < copy_len; i++) dst[i] = data[i];" in code
        assert "for (int i = copy_len; i < cap; i++) dst[i] = 0.0f;" in code

    def test_no_buffers_api(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Constant(id="c", value=1.0)],
        )
        code = compile_graph(g)
        assert "int test_num_buffers(void) { return 0; }" in code


class TestRateDiv:
    """Verify RateDiv node code generation."""

    def test_struct_fields(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[RateDiv(id="rd", a="in1", divisor=4.0)],
        )
        code = compile_graph(g)
        assert "int m_rd_count;" in code
        assert "float m_rd_held;" in code

    def test_init(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[RateDiv(id="rd", a="in1", divisor=4.0)],
        )
        code = compile_graph(g)
        assert "self->m_rd_count = 0;" in code
        assert "self->m_rd_held = 0.0f;" in code

    def test_load_save(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[RateDiv(id="rd", a="in1", divisor=4.0)],
        )
        code = compile_graph(g)
        assert "int rd_count = self->m_rd_count;" in code
        assert "float rd_held = self->m_rd_held;" in code
        assert "self->m_rd_count = rd_count;" in code
        assert "self->m_rd_held = rd_held;" in code

    def test_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[RateDiv(id="rd", a="in1", divisor=4.0)],
        )
        code = compile_graph(g)
        assert "if (rd_count == 0) rd_held = in1[i];" in code
        assert "rd_count++;" in code
        assert "if (rd_count >= (int)4.0f) rd_count = 0;" in code
        assert "float rd = rd_held;" in code


class TestScale:
    """Verify Scale node code generation."""

    def test_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sc")],
            nodes=[
                Scale(id="sc", a="in1", in_lo=-1.0, in_hi=1.0, out_lo=0.0, out_hi=10.0)
            ],
        )
        code = compile_graph(g)
        assert "sc_in_range" in code
        assert "sc_out_range" in code
        assert "float sc =" in code

    def test_hoisted_when_param_only(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            params=[Param(name="val", default=0.5)],
            nodes=[
                Scale(id="sc", a="val", in_lo=0.0, in_hi=1.0, out_lo=0.0, out_hi=10.0),
                BinOp(id="r", op="mul", a="in1", b="sc"),
            ],
        )
        code = compile_graph(g)
        loop_pos = code.index("for (int i")
        sc_pos = code.index("float sc =")
        assert sc_pos < loop_pos, "param-only Scale should be hoisted"


class TestSmoothParam:
    """Verify SmoothParam node code generation."""

    def test_struct_field(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sp")],
            nodes=[SmoothParam(id="sp", a="in1", coeff=0.99)],
        )
        code = compile_graph(g)
        assert "float m_sp_prev;" in code

    def test_compute(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sp")],
            nodes=[SmoothParam(id="sp", a="in1", coeff=0.99)],
        )
        code = compile_graph(g)
        assert "(1.0f - 0.99f) * in1[i] + 0.99f * sp_prev" in code
        assert "sp_prev = sp;" in code

    def test_never_hoisted(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="sp")],
            params=[Param(name="val", default=0.5)],
            nodes=[SmoothParam(id="sp", a="val", coeff=0.99)],
        )
        code = compile_graph(g)
        loop_pos = code.index("for (int i")
        sp_pos = code.index("float sp =")
        assert sp_pos > loop_pos, "stateful SmoothParam should stay in loop"


class TestPeek:
    """Verify Peek node code generation."""

    def test_struct_field(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="pk")],
            nodes=[Peek(id="pk", a="in1")],
        )
        code = compile_graph(g)
        assert "float m_pk_value;" in code

    def test_passthrough(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="pk")],
            nodes=[Peek(id="pk", a="in1")],
        )
        code = compile_graph(g)
        assert "float pk = in1[i];" in code
        assert "pk_value = pk;" in code

    def test_api_num_peeks(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="pk")],
            nodes=[Peek(id="pk", a="in1")],
        )
        code = compile_graph(g)
        assert "int test_num_peeks(void) { return 1; }" in code

    def test_api_peek_name(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="pk")],
            nodes=[Peek(id="pk", a="in1")],
        )
        code = compile_graph(g)
        assert 'return "pk";' in code

    def test_api_get_peek(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="pk")],
            nodes=[Peek(id="pk", a="in1")],
        )
        code = compile_graph(g)
        assert "return self->m_pk_value;" in code

    def test_no_peeks_api(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Constant(id="c", value=1.0)],
        )
        code = compile_graph(g)
        assert "int test_num_peeks(void) { return 0; }" in code


@pytest.mark.skipif(not shutil.which("g++"), reason="g++ not available")
class TestGccCompilation:
    """Integration: verify generated C++ compiles with g++."""

    def _compile_check(self, graph: Graph) -> None:
        code = compile_graph(graph)
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
            f.write(code)
            f.flush()
            result = subprocess.run(
                ["g++", "-std=c++17", "-c", "-o", "/dev/null", "-x", "c++", f.name],
                capture_output=True,
                text=True,
            )
            Path(f.name).unlink()
        assert result.returncode == 0, f"g++ failed:\n{result.stderr}"

    def test_stereo_gain_compiles(self, stereo_gain_graph: Graph) -> None:
        self._compile_check(stereo_gain_graph)

    def test_onepole_compiles(self, onepole_graph: Graph) -> None:
        self._compile_check(onepole_graph)

    def test_fbdelay_compiles(self, fbdelay_graph: Graph) -> None:
        self._compile_check(fbdelay_graph)

    def test_all_node_types_compile(self) -> None:
        """Graph exercising every node type compiles."""
        g = Graph(
            name="all_nodes",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="clamped")],
            params=[Param(name="freq", min=0.0, max=20000.0, default=440.0)],
            nodes=[
                Constant(id="half", value=0.5),
                BinOp(id="scaled", op="mul", a="in1", b="half"),
                BinOp(id="mn", op="min", a="in1", b="half"),
                BinOp(id="mx", op="max", a="in1", b="half"),
                BinOp(id="md", op="mod", a="in1", b="half"),
                BinOp(id="pw", op="pow", a="in1", b="half"),
                UnaryOp(id="shaped", op="tanh", a="scaled"),
                UnaryOp(id="fl", op="floor", a="in1"),
                UnaryOp(id="cl", op="ceil", a="in1"),
                UnaryOp(id="rn", op="round", a="in1"),
                UnaryOp(id="sg", op="sign", a="in1"),
                UnaryOp(id="at", op="atan", a="in1"),
                UnaryOp(id="asi", op="asin", a="in1"),
                UnaryOp(id="aco", op="acos", a="in1"),
                History(id="prev", input="clamped"),
                BinOp(id="mixed", op="add", a="shaped", b="prev"),
                Clamp(id="clamped", a="mixed"),
                Phasor(id="lfo", freq="freq"),
                Noise(id="noise"),
                DelayLine(id="dl", max_samples=4800),
                DelayRead(id="tap_out", delay="dl", tap="half"),
                DelayRead(id="tap_lin", delay="dl", tap="half", interp="linear"),
                DelayRead(id="tap_cub", delay="dl", tap="half", interp="cubic"),
                DelayWrite(id="dl_wr", delay="dl", value="scaled"),
                Compare(id="cmp", op="gt", a="in1", b=0.0),
                Select(id="sel", cond="cmp", a="in1", b=0.0),
                Wrap(id="wr", a="in1"),
                Fold(id="fo", a="in1"),
                Mix(id="mxn", a="in1", b="half", t=0.5),
                Delta(id="dt", a="in1"),
                Change(id="ch", a="in1"),
                Biquad(id="bq", a="in1", b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0),
                SVF(id="svf", a="in1", freq="freq", q=0.707, mode="lp"),
                OnePole(id="opn", a="in1", coeff=0.5),
                DCBlock(id="dc", a="in1"),
                Allpass(id="ap", a="in1", coeff=0.5),
                SinOsc(id="sosc", freq="freq"),
                TriOsc(id="tosc", freq="freq"),
                SawOsc(id="swosc", freq="freq"),
                PulseOsc(id="posc", freq="freq", width=0.5),
                SampleHold(id="sh", a="in1", trig=0.0),
                Latch(id="la", a="in1", trig=0.0),
                Accum(id="ac", incr=1.0, reset=0.0),
                Counter(id="ct", trig=0.0, max=16.0),
                Buffer(id="buf", size=1024),
                BufRead(id="brd", buffer="buf", index="half"),
                BufRead(id="brl", buffer="buf", index="half", interp="linear"),
                BufRead(id="brc", buffer="buf", index="half", interp="cubic"),
                BufWrite(id="bwr", buffer="buf", index="half", value="in1"),
                BufSize(id="bsz", buffer="buf"),
                RateDiv(id="ratediv", a="in1", divisor=4.0),
                Scale(
                    id="scl", a="in1", in_lo=-1.0, in_hi=1.0, out_lo=0.0, out_hi=10.0
                ),
                SmoothParam(id="smp", a="in1", coeff=0.99),
                Peek(id="peek_n", a="in1"),
            ],
        )
        self._compile_check(g)


class TestLICM:
    """Verify loop-invariant code motion."""

    def test_param_derived_hoisted(self) -> None:
        """A node that depends only on a param is hoisted before the loop."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            params=[Param(name="coeff", default=0.5)],
            nodes=[
                BinOp(id="inv", op="sub", a=1.0, b="coeff"),
                BinOp(id="r", op="mul", a="in1", b="inv"),
            ],
        )
        code = compile_graph(g)
        inv_pos = code.index("float inv =")
        loop_pos = code.index("for (int i")
        assert inv_pos < loop_pos, "param-derived node should be hoisted before loop"

    def test_input_dependent_in_loop(self) -> None:
        """A node referencing an audio input stays inside the loop."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            params=[Param(name="gain", default=1.0)],
            nodes=[
                BinOp(id="r", op="mul", a="in1", b="gain"),
            ],
        )
        code = compile_graph(g)
        r_pos = code.index("float r =")
        loop_pos = code.index("for (int i")
        assert r_pos > loop_pos, "input-dependent node should be inside loop"

    def test_constant_hoisted(self) -> None:
        """A Constant node is hoisted before the loop."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="k", value=42.0),
                BinOp(id="r", op="mul", a="in1", b="k"),
            ],
        )
        code = compile_graph(g)
        k_pos = code.index("float k =")
        loop_pos = code.index("for (int i")
        assert k_pos < loop_pos, "constant should be hoisted before loop"

    def test_chain_hoisted(self) -> None:
        """A chain of param-only nodes are all hoisted before the loop."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            params=[Param(name="freq", default=440.0)],
            nodes=[
                BinOp(id="a", op="div", a="freq", b=44100.0),
                BinOp(id="b", op="mul", a="a", b=6.28),
                BinOp(id="r", op="mul", a="in1", b="b"),
            ],
        )
        code = compile_graph(g)
        loop_pos = code.index("for (int i")
        a_pos = code.index("float a =")
        b_pos = code.index("float b =")
        assert a_pos < loop_pos, "first chain node should be hoisted"
        assert b_pos < loop_pos, "second chain node should be hoisted"

    def test_stateful_never_hoisted(self) -> None:
        """Stateful nodes always stay in the loop, even with literal args."""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="p")],
            nodes=[
                Phasor(id="p", freq=440.0),
            ],
        )
        code = compile_graph(g)
        p_pos = code.index("float p =")
        loop_pos = code.index("for (int i")
        assert p_pos > loop_pos, "stateful node should stay in loop"

    def test_mixed_graph(self) -> None:
        """Some nodes hoisted, others remain in loop."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="result")],
            params=[Param(name="coeff", default=0.5)],
            nodes=[
                BinOp(id="inv_coeff", op="sub", a=1.0, b="coeff"),
                History(id="prev", init=0.0, input="result"),
                BinOp(id="dry", op="mul", a="in1", b="inv_coeff"),
                BinOp(id="wet", op="mul", a="prev", b="coeff"),
                BinOp(id="result", op="add", a="dry", b="wet"),
            ],
        )
        code = compile_graph(g)
        loop_pos = code.index("for (int i")
        # inv_coeff depends only on param -- hoisted
        inv_pos = code.index("float inv_coeff =")
        assert inv_pos < loop_pos
        # dry depends on in1 -- in loop
        dry_pos = code.index("float dry =")
        assert dry_pos > loop_pos

    def test_multiline_wrap_hoisted(self) -> None:
        """A Wrap node (multi-line emission) is correctly hoisted with proper indent."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            params=[Param(name="phase", default=0.5)],
            nodes=[
                Wrap(id="w", a="phase", lo=0.0, hi=1.0),
                BinOp(id="r", op="mul", a="in1", b="w"),
            ],
        )
        code = compile_graph(g)
        loop_pos = code.index("for (int i")
        # All lines of Wrap emission should be before the loop
        assert code.index("w_range") < loop_pos
        assert code.index("w_raw") < loop_pos
        assert code.index("float w =") < loop_pos
        # Hoisted lines should be at 4-space indent (not 8)
        for line in code.splitlines():
            if "w_range" in line and "float" in line:
                assert line.startswith("    ") and not line.startswith("        ")

    def test_multiline_fold_hoisted(self) -> None:
        """A Fold node (multi-line emission with if statement) is correctly hoisted."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            params=[Param(name="val", default=0.5)],
            nodes=[
                Fold(id="f", a="val", lo=0.0, hi=1.0),
                BinOp(id="r", op="mul", a="in1", b="f"),
            ],
        )
        code = compile_graph(g)
        loop_pos = code.index("for (int i")
        assert code.index("f_range") < loop_pos
        assert code.index("f_t") < loop_pos
        assert code.index("float f =") < loop_pos

    def test_sr_not_invariant(self) -> None:
        """Nodes referencing sr (via stateful nodes like SVF) stay in loop."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="f")],
            nodes=[SVF(id="f", a="in1", freq=1000.0, q=0.707, mode="lp")],
        )
        code = compile_graph(g)
        # SVF uses sr internally and is stateful -- stays in loop
        loop_pos = code.index("for (int i")
        f_g_pos = code.index("f_g")
        assert f_g_pos > loop_pos


class TestSIMDHints:
    """Verify SIMD vectorization hints in generated code."""

    def test_restrict_on_io_pointers(self) -> None:
        """I/O pointers use __restrict with correct array unpacking."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
            outputs=[
                AudioOutput(id="out1", source="r1"),
                AudioOutput(id="out2", source="r2"),
            ],
            nodes=[
                BinOp(id="r1", op="mul", a="in1", b=1.0),
                BinOp(id="r2", op="mul", a="in2", b=1.0),
            ],
        )
        code = compile_graph(g)
        assert "float* __restrict in1 = ins[0];" in code
        assert "float* __restrict in2 = ins[1];" in code
        assert "float* __restrict out1 = outs[0];" in code
        assert "float* __restrict out2 = outs[1];" in code

    def test_vectorize_pragma_pure_graph(self) -> None:
        """Vectorization pragma present when only pure nodes exist."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[BinOp(id="r", op="mul", a="in1", b=2.0)],
        )
        code = compile_graph(g)
        assert "#pragma clang loop vectorize(enable)" in code
        assert "#pragma GCC ivdep" in code

    def test_no_pragma_with_stateful(self) -> None:
        """No vectorization pragma when stateful nodes exist."""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="p")],
            nodes=[Phasor(id="p", freq=440.0)],
        )
        code = compile_graph(g)
        assert "#pragma clang loop" not in code
        assert "#pragma GCC ivdep" not in code

    @pytest.mark.skipif(not shutil.which("g++"), reason="g++ not available")
    def test_compiles_with_restrict(self) -> None:
        """Generated code with __restrict compiles successfully."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            params=[Param(name="gain", default=1.0)],
            nodes=[
                BinOp(id="inv", op="sub", a=1.0, b="gain"),
                BinOp(id="r", op="mul", a="in1", b="inv"),
            ],
        )
        code = compile_graph(g)
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
            f.write(code)
            f.flush()
            result = subprocess.run(
                ["g++", "-std=c++17", "-c", "-o", "/dev/null", "-x", "c++", f.name],
                capture_output=True,
                text=True,
            )
            Path(f.name).unlink()
        assert result.returncode == 0, f"g++ failed:\n{result.stderr}"
