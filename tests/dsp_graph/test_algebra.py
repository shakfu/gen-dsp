"""Tests for FAUST-style block diagram algebra."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
import numpy as np
import pytest

from gen_dsp.dsp_graph import (
    AudioInput,
    AudioOutput,
    BinOp,
    Constant,
    Graph,
    History,
    OnePole,
    Param,
    SinOsc,
    Subgraph,
    compile_graph,
    expand_subgraphs,
    merge,
    parallel,
    series,
    split,
    validate_graph,
)
from gen_dsp.dsp_graph.algebra import _merge_params, _pick_ids
from gen_dsp.dsp_graph.simulate import simulate

# ---------------------------------------------------------------------------
# Reusable graph fixtures
# ---------------------------------------------------------------------------


def _onepole(name: str = "lpf") -> Graph:
    """Mono filter: 1 input, 1 output, 1 param (coeff)."""
    return Graph(
        name=name,
        inputs=[AudioInput(id="in")],
        outputs=[AudioOutput(id="out", source="filt")],
        params=[Param(name="coeff", default=0.5)],
        nodes=[OnePole(id="filt", a="in", coeff="coeff")],
    )


def _gain(name: str = "gain") -> Graph:
    """Mono gain: 1 input, 1 output, 1 param (level)."""
    return Graph(
        name=name,
        inputs=[AudioInput(id="in")],
        outputs=[AudioOutput(id="out", source="mul")],
        params=[Param(name="level", default=0.5, min=0.0, max=1.0)],
        nodes=[BinOp(id="mul", op="mul", a="in", b="level")],
    )


def _stereo_gain(name: str = "stereo_gain") -> Graph:
    """Stereo gain: 2 inputs, 2 outputs, 1 param."""
    return Graph(
        name=name,
        inputs=[AudioInput(id="in_l"), AudioInput(id="in_r")],
        outputs=[
            AudioOutput(id="out_l", source="mul_l"),
            AudioOutput(id="out_r", source="mul_r"),
        ],
        params=[Param(name="level", default=0.5)],
        nodes=[
            BinOp(id="mul_l", op="mul", a="in_l", b="level"),
            BinOp(id="mul_r", op="mul", a="in_r", b="level"),
        ],
    )


def _mono_to_stereo(name: str = "split") -> Graph:
    """1 input -> 2 outputs (identity on both)."""
    return Graph(
        name=name,
        inputs=[AudioInput(id="in")],
        outputs=[
            AudioOutput(id="out_l", source="pass_l"),
            AudioOutput(id="out_r", source="pass_r"),
        ],
        nodes=[
            BinOp(id="pass_l", op="mul", a="in", b=1.0),
            BinOp(id="pass_r", op="mul", a="in", b=1.0),
        ],
    )


def _stereo_to_mono(name: str = "sum") -> Graph:
    """2 inputs -> 1 output (sum)."""
    return Graph(
        name=name,
        inputs=[AudioInput(id="in_l"), AudioInput(id="in_r")],
        outputs=[AudioOutput(id="out", source="add")],
        nodes=[BinOp(id="add", op="add", a="in_l", b="in_r")],
    )


def _generator(name: str = "gen") -> Graph:
    """0 inputs, 1 output, 1 param (freq)."""
    return Graph(
        name=name,
        inputs=[],
        outputs=[AudioOutput(id="out", source="osc")],
        params=[Param(name="freq", default=440.0, min=20.0, max=20000.0)],
        nodes=[SinOsc(id="osc", freq="freq")],
    )


def _passthrough(name: str = "pass") -> Graph:
    """Trivial 1->1 passthrough with no params."""
    return Graph(
        name=name,
        inputs=[AudioInput(id="in")],
        outputs=[AudioOutput(id="out", source="id")],
        nodes=[BinOp(id="id", op="mul", a="in", b=1.0)],
    )


def _adder(name: str = "adder") -> Graph:
    """2-input -> 1-output adder, no params."""
    return Graph(
        name=name,
        inputs=[AudioInput(id="a"), AudioInput(id="b")],
        outputs=[AudioOutput(id="out", source="add")],
        nodes=[BinOp(id="add", op="add", a="a", b="b")],
    )


# ---------------------------------------------------------------------------
# A. Helper tests
# ---------------------------------------------------------------------------


class TestPickIds:
    def test_different_names(self) -> None:
        a = Graph(name="lpf")
        b = Graph(name="hpf")
        assert _pick_ids(a, b) == ("lpf", "hpf")

    def test_same_names(self) -> None:
        a = Graph(name="filt")
        b = Graph(name="filt")
        assert _pick_ids(a, b) == ("filt", "filt2")


class TestMergeParams:
    def test_basic(self) -> None:
        a = _onepole("lpf")
        b = _gain("gain")
        params, a_map, b_map = _merge_params(a, b, "lpf", "gain")
        assert len(params) == 2
        assert params[0].name == "lpf_coeff"
        assert params[1].name == "gain_level"
        assert a_map == {"coeff": "lpf_coeff"}
        assert b_map == {"level": "gain_level"}

    def test_empty_params(self) -> None:
        a = _passthrough()
        b = _passthrough()
        params, a_map, b_map = _merge_params(a, b, "a", "b")
        assert params == []
        assert a_map == {}
        assert b_map == {}

    def test_preserves_ranges(self) -> None:
        a = _gain()
        params, _, _ = _merge_params(a, Graph(name="x"), "gain", "x")
        assert params[0].min == 0.0
        assert params[0].max == 1.0
        assert params[0].default == 0.5


# ---------------------------------------------------------------------------
# B. Series tests
# ---------------------------------------------------------------------------


class TestSeries:
    def test_basic_1to1(self) -> None:
        g = series(_onepole("lpf"), _gain("gain"))
        assert len(g.inputs) == 1
        assert len(g.outputs) == 1
        assert len(g.params) == 2
        assert g.inputs[0].id == "in"
        assert g.outputs[0].id == "out"

    def test_multi_channel(self) -> None:
        g = series(_stereo_gain("a"), _stereo_gain("b"))
        assert len(g.inputs) == 2
        assert len(g.outputs) == 2

    def test_param_namespacing(self) -> None:
        g = series(_onepole("lpf"), _onepole("hpf"))
        param_names = {p.name for p in g.params}
        assert "lpf_coeff" in param_names
        assert "hpf_coeff" in param_names

    def test_expand_and_validate(self) -> None:
        g = series(_onepole("lpf"), _gain("gain"))
        expanded = expand_subgraphs(g)
        errors = validate_graph(expanded)
        assert errors == []
        assert not any(isinstance(n, Subgraph) for n in expanded.nodes)

    def test_compile(self) -> None:
        g = series(_onepole("lpf"), _gain("gain"))
        code = compile_graph(g)
        assert "lpf__filt" in code
        assert "gain__mul" in code

    def test_simulate_step_response(self) -> None:
        """Single onepole with coeff=1.0 should pass through."""
        g = series(_passthrough("a"), _passthrough("b"))
        inp = np.ones(10, dtype=np.float32)
        result = simulate(g, inputs={"in": inp})
        np.testing.assert_allclose(result.outputs["out"], inp, atol=1e-6)

    def test_simulate_double_filter(self) -> None:
        """Two cascaded onepoles with coeff c: y[n] = c*x + (1-c)*y[n-1]."""
        c = 0.3
        g = series(_onepole("lpf1"), _onepole("lpf2"))
        inp = np.ones(20, dtype=np.float32)
        result = simulate(
            g,
            inputs={"in": inp},
            params={"lpf1_coeff": c, "lpf2_coeff": c},
        )
        # Verify against manual double filter
        y1 = np.zeros(20)
        y2 = np.zeros(20)
        for i in range(20):
            y1[i] = c * 1.0 + (1 - c) * (y1[i - 1] if i > 0 else 0.0)
            y2[i] = c * y1[i] + (1 - c) * (y2[i - 1] if i > 0 else 0.0)
        np.testing.assert_allclose(result.outputs["out"], y2, atol=1e-6)

    def test_io_mismatch_error(self) -> None:
        with pytest.raises(ValueError, match="output count"):
            series(_mono_to_stereo(), _onepole())

    def test_zero_param_graphs(self) -> None:
        g = series(_passthrough("a"), _passthrough("b"))
        assert g.params == []
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []

    def test_same_name_graphs(self) -> None:
        a = _onepole("filt")
        b = _onepole("filt")
        g = series(a, b)
        param_names = {p.name for p in g.params}
        assert "filt_coeff" in param_names
        assert "filt2_coeff" in param_names

    def test_nested_series(self) -> None:
        a = _passthrough("a")
        b = _passthrough("b")
        c = _passthrough("c")
        g = series(series(a, b), c)
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []
        # Should compile without error
        code = compile_graph(g)
        assert len(code) > 0

    def test_generator_into_filter(self) -> None:
        """Generator (0 inputs) >> filter (1 input) = generator with 0 inputs."""
        g = series(_generator("gen"), _onepole("lpf"))
        assert len(g.inputs) == 0
        assert len(g.outputs) == 1
        result = simulate(
            g,
            n_samples=10,
            params={"gen_freq": 440.0, "lpf_coeff": 0.5},
        )
        assert result.outputs["out"].shape == (10,)


# ---------------------------------------------------------------------------
# C. Parallel tests
# ---------------------------------------------------------------------------


class TestParallel:
    def test_basic_stacking(self) -> None:
        g = parallel(_onepole("lpf"), _gain("gain"))
        assert len(g.inputs) == 2
        assert len(g.outputs) == 2
        input_ids = {inp.id for inp in g.inputs}
        assert "lpf_in" in input_ids
        assert "gain_in" in input_ids

    def test_io_prefixing(self) -> None:
        g = parallel(_onepole("lpf"), _gain("gain"))
        output_ids = {o.id for o in g.outputs}
        assert "lpf_out" in output_ids
        assert "gain_out" in output_ids

    def test_param_isolation(self) -> None:
        g = parallel(_onepole("lpf"), _gain("gain"))
        param_names = {p.name for p in g.params}
        assert "lpf_coeff" in param_names
        assert "gain_level" in param_names
        assert len(g.params) == 2

    def test_asymmetric_io(self) -> None:
        """Different I/O counts should work fine."""
        a = _onepole("mono")  # 1in/1out
        b = _stereo_gain("stereo")  # 2in/2out
        g = parallel(a, b)
        assert len(g.inputs) == 3
        assert len(g.outputs) == 3

    def test_compile_validate(self) -> None:
        g = parallel(_onepole("lpf"), _gain("gain"))
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []
        code = compile_graph(g)
        assert "lpf__filt" in code
        assert "gain__mul" in code

    def test_simulate_independence(self) -> None:
        g = parallel(_gain("a"), _gain("b"))
        inp_a = np.full(5, 2.0, dtype=np.float32)
        inp_b = np.full(5, 3.0, dtype=np.float32)
        result = simulate(
            g,
            inputs={"a_in": inp_a, "b_in": inp_b},
            params={"a_level": 0.5, "b_level": 0.25},
        )
        np.testing.assert_allclose(result.outputs["a_out"], 1.0, atol=1e-6)
        np.testing.assert_allclose(result.outputs["b_out"], 0.75, atol=1e-6)

    def test_zero_input_generators(self) -> None:
        g = parallel(_generator("gen1"), _generator("gen2"))
        assert len(g.inputs) == 0
        result = simulate(g, n_samples=5)
        assert "gen1_out" in result.outputs
        assert "gen2_out" in result.outputs

    def test_same_name(self) -> None:
        g = parallel(_gain("g"), _gain("g"))
        param_names = {p.name for p in g.params}
        assert "g_level" in param_names
        assert "g2_level" in param_names


# ---------------------------------------------------------------------------
# D. Split tests
# ---------------------------------------------------------------------------


class TestSplit:
    def test_1_to_2(self) -> None:
        """1 output -> 2 inputs."""
        a = _passthrough("src")
        b = _stereo_gain("dst")
        g = split(a, b)
        assert len(g.inputs) == 1
        assert len(g.outputs) == 2

    def test_1_to_4(self) -> None:
        """1 output duplicated to 4 inputs."""
        a = _passthrough("src")
        b = Graph(
            name="quad",
            inputs=[AudioInput(id=f"i{n}") for n in range(4)],
            outputs=[AudioOutput(id="out", source="sum")],
            nodes=[
                BinOp(id="s01", op="add", a="i0", b="i1"),
                BinOp(id="s23", op="add", a="i2", b="i3"),
                BinOp(id="sum", op="add", a="s01", b="s23"),
            ],
        )
        g = split(a, b)
        assert len(g.inputs) == 1
        assert len(g.outputs) == 1

    def test_2_to_4_cyclic(self) -> None:
        """2 outputs -> 4 inputs in cyclic pattern (0,1,0,1)."""
        a = _mono_to_stereo("src")  # 1 in -> 2 out
        b = Graph(
            name="quad",
            inputs=[AudioInput(id=f"i{n}") for n in range(4)],
            outputs=[AudioOutput(id="out", source="sum")],
            nodes=[
                BinOp(id="s01", op="add", a="i0", b="i1"),
                BinOp(id="s23", op="add", a="i2", b="i3"),
                BinOp(id="sum", op="add", a="s01", b="s23"),
            ],
        )
        g = split(a, b)
        assert len(g.inputs) == 1
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []

    def test_compile_validate(self) -> None:
        g = split(_passthrough("src"), _stereo_gain("dst"))
        code = compile_graph(g)
        assert len(code) > 0
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []

    def test_simulate_duplication(self) -> None:
        """Splitting should duplicate the signal."""
        a = _passthrough("src")
        b = _stereo_gain("dst")
        g = split(a, b)
        inp = np.full(5, 2.0, dtype=np.float32)
        result = simulate(
            g,
            inputs={"in": inp},
            params={"dst_level": 1.0},
        )
        np.testing.assert_allclose(result.outputs["out_l"], 2.0, atol=1e-6)
        np.testing.assert_allclose(result.outputs["out_r"], 2.0, atol=1e-6)

    def test_modulo_mismatch_error(self) -> None:
        a = _mono_to_stereo()  # 2 outputs
        b = Graph(
            name="three",
            inputs=[AudioInput(id=f"i{n}") for n in range(3)],
            outputs=[AudioOutput(id="out", source="i0")],
            nodes=[BinOp(id="nop", op="mul", a="i0", b=1.0)],
        )
        with pytest.raises(ValueError, match="not a multiple"):
            split(a, b)

    def test_no_outputs_error(self) -> None:
        a = Graph(name="empty", outputs=[])
        b = _passthrough()
        with pytest.raises(ValueError, match="no outputs"):
            split(a, b)

    def test_1_to_1_degenerates(self) -> None:
        """split with equal I/O should behave like series."""
        a = _passthrough("a")
        b = _gain("b")
        g = split(a, b)
        inp = np.full(5, 3.0, dtype=np.float32)
        result = simulate(g, inputs={"in": inp}, params={"b_level": 0.5})
        np.testing.assert_allclose(result.outputs["out"], 1.5, atol=1e-6)


# ---------------------------------------------------------------------------
# E. Merge tests
# ---------------------------------------------------------------------------


class TestMerge:
    def test_2_to_1_sum(self) -> None:
        a = _mono_to_stereo("src")  # 1 in -> 2 out
        b = _passthrough("dst")  # 1 in -> 1 out
        g = merge(a, b)
        assert len(g.inputs) == 1
        assert len(g.outputs) == 1
        # Should have sum nodes
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []

    def test_4_to_2_sum(self) -> None:
        a = Graph(
            name="quad",
            inputs=[AudioInput(id="in")],
            outputs=[AudioOutput(id=f"o{n}", source=f"g{n}") for n in range(4)],
            nodes=[BinOp(id=f"g{n}", op="mul", a="in", b=1.0) for n in range(4)],
        )
        b = _stereo_gain("dst")
        g = merge(a, b)
        assert len(g.inputs) == 1
        assert len(g.outputs) == 2
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []

    def test_compile_validate(self) -> None:
        a = _mono_to_stereo("src")
        b = _passthrough("dst")
        g = merge(a, b)
        code = compile_graph(g)
        assert len(code) > 0

    def test_simulate_summing(self) -> None:
        """2 outputs merged into 1 should sum them."""
        a = _mono_to_stereo("src")  # duplicates input to 2 outputs
        b = _passthrough("dst")
        g = merge(a, b)
        inp = np.full(5, 3.0, dtype=np.float32)
        result = simulate(g, inputs={"in": inp})
        # Both channels are 3.0, summed = 6.0
        np.testing.assert_allclose(result.outputs["out"], 6.0, atol=1e-6)

    def test_sum_node_naming(self) -> None:
        a = _mono_to_stereo("src")
        b = _passthrough("dst")
        g = merge(a, b)
        node_ids = {n.id for n in g.nodes}
        assert "_sum_0_0" in node_ids

    def test_modulo_mismatch_error(self) -> None:
        a = Graph(
            name="three",
            inputs=[AudioInput(id="in")],
            outputs=[AudioOutput(id=f"o{n}", source=f"g{n}") for n in range(3)],
            nodes=[BinOp(id=f"g{n}", op="mul", a="in", b=1.0) for n in range(3)],
        )
        b = _stereo_gain()  # 2 inputs
        with pytest.raises(ValueError, match="not a multiple"):
            merge(a, b)

    def test_no_inputs_error(self) -> None:
        a = _passthrough()
        b = _generator()
        with pytest.raises(ValueError, match="no inputs"):
            merge(a, b)

    def test_k1_degenerates_to_series(self) -> None:
        """When k=1, merge should behave like series (direct wiring)."""
        a = _passthrough("a")
        b = _gain("b")
        g = merge(a, b)
        # No sum nodes needed for k=1
        binop_nodes = [n for n in g.nodes if isinstance(n, BinOp)]
        assert len(binop_nodes) == 0
        inp = np.full(5, 4.0, dtype=np.float32)
        result = simulate(g, inputs={"in": inp}, params={"b_level": 0.25})
        np.testing.assert_allclose(result.outputs["out"], 1.0, atol=1e-6)


# ---------------------------------------------------------------------------
# F. Operator tests
# ---------------------------------------------------------------------------


class TestOperators:
    def test_rshift_series(self) -> None:
        from gen_dsp.dsp_graph.algebra import series as _series  # noqa: F811

        a = _passthrough("a")
        b = _gain("b")
        g = a >> b
        expected = _series(a, b)
        assert len(g.inputs) == len(expected.inputs)
        assert len(g.outputs) == len(expected.outputs)
        assert len(g.params) == len(expected.params)

    def test_floordiv_parallel(self) -> None:
        from gen_dsp.dsp_graph.algebra import parallel as _par  # noqa: F811

        a = _gain("a")
        b = _gain("b")
        g = a // b
        expected = _par(a, b)
        assert len(g.inputs) == len(expected.inputs)
        assert len(g.outputs) == len(expected.outputs)

    def test_chain_rshift(self) -> None:
        a = _passthrough("a")
        b = _passthrough("b")
        c = _passthrough("c")
        g = a >> b >> c
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []

    def test_mixed_operators(self) -> None:
        """(a // b) >> c where a,b are mono and c is stereo->stereo."""
        a = _gain("a")
        b = _gain("b")
        c = _stereo_gain("c")
        stack = a // b
        g = stack >> c
        assert len(g.inputs) == 2
        assert len(g.outputs) == 2
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []


# ---------------------------------------------------------------------------
# G. Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_multiband_split_parallel(self) -> None:
        """split(mono, parallel(lpf, hpf)) -- multiband structure."""
        mono = _passthrough("src")
        lpf = _onepole("lpf")
        hpf = _onepole("hpf")
        band = parallel(lpf, hpf)
        g = split(mono, band)
        assert len(g.inputs) == 1
        assert len(g.outputs) == 2
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []

    def test_effect_chain(self) -> None:
        """a >> b >> c triple chain."""
        a = _onepole("lpf")
        b = _gain("gain")
        c = _onepole("hpf")
        g = series(series(a, b), c)
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []
        code = compile_graph(g)
        assert len(code) > 0

    def test_additive_synth_merge(self) -> None:
        """parallel(gen, gen) >> merge into mono."""
        # Two generators in parallel
        gen1 = _generator("osc1")
        gen2 = _generator("osc2")
        pair = parallel(gen1, gen2)
        # Merge (sum) into mono adder
        summer = _adder("mix")
        g = merge(pair, summer)
        assert len(g.inputs) == 0  # generators have no inputs
        assert len(g.outputs) == 1
        # Params get double-prefixed: outer subgraph ID + inner prefix
        result = simulate(
            g,
            n_samples=10,
            params={
                "osc1__osc2_osc1_freq": 440.0,
                "osc1__osc2_osc2_freq": 880.0,
            },
        )
        assert result.outputs["out"].shape == (10,)

    def test_simulate_end_to_end(self) -> None:
        """Full pipeline: split -> parallel process -> merge."""
        src = _passthrough("src")
        proc_l = _gain("left")
        proc_r = _gain("right")
        band = parallel(proc_l, proc_r)
        expanded_out = split(src, band)
        # Now merge back to mono via adder
        summer = _adder("mix")
        g = merge(expanded_out, summer)
        # Params are deeply prefixed: outer_id + inner_id + param_name
        param_names = {p.name for p in g.params}
        left_param = next(p for p in param_names if p.endswith("left_level"))
        right_param = next(p for p in param_names if p.endswith("right_level"))
        inp = np.full(10, 2.0, dtype=np.float32)
        result = simulate(
            g,
            inputs={"in": inp},
            params={left_param: 0.5, right_param: 0.25},
        )
        # left = 2.0 * 0.5 = 1.0, right = 2.0 * 0.25 = 0.5, sum = 1.5
        np.testing.assert_allclose(result.outputs["out"], 1.5, atol=1e-6)

    def test_compile_output_structure(self) -> None:
        g = series(_onepole("lpf"), _gain("gain"))
        code = compile_graph(g)
        # Should have perform function and state struct
        assert "perform" in code
        assert "struct" in code.lower() or "State" in code

    def test_all_node_types_through_composition(self) -> None:
        """Verify composition handles graphs with History nodes."""
        fb = Graph(
            name="fb",
            inputs=[AudioInput(id="in")],
            outputs=[AudioOutput(id="out", source="result")],
            params=[Param(name="coeff", default=0.5)],
            nodes=[
                History(id="prev", init=0.0, input="result"),
                BinOp(id="wet", op="mul", a="prev", b="coeff"),
                BinOp(id="inv", op="sub", a=1.0, b="coeff"),
                BinOp(id="dry", op="mul", a="in", b="inv"),
                BinOp(id="result", op="add", a="dry", b="wet"),
            ],
        )
        g = series(fb, _gain("out"))
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []
        code = compile_graph(g)
        # History node should appear prefixed
        assert "fb__prev" in code


# ---------------------------------------------------------------------------
# H. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_params_both_sides(self) -> None:
        g = series(_passthrough("a"), _passthrough("b"))
        assert g.params == []
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []

    def test_single_node_graphs(self) -> None:
        """Graphs with a single node each should compose fine."""
        a = Graph(
            name="const",
            inputs=[AudioInput(id="in")],
            outputs=[AudioOutput(id="out", source="c")],
            nodes=[Constant(id="c", value=42.0)],
        )
        b = _passthrough("pass")
        # constant graph ignores input but has matching I/O count
        g = series(a, b)
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []

    def test_deep_nesting(self) -> None:
        """4+ levels of nesting via repeated series."""
        g = _passthrough("a")
        for i in range(4):
            g = series(g, _passthrough(f"l{i}"))
        expanded = expand_subgraphs(g)
        assert validate_graph(expanded) == []
        code = compile_graph(g)
        assert len(code) > 0

    def test_parallel_then_series(self) -> None:
        """parallel produces prefixed I/O; series should chain correctly."""
        a = _gain("a")
        b = _gain("b")
        c = _stereo_gain("c")
        stack = parallel(a, b)
        g = series(stack, c)
        assert len(g.inputs) == 2
        assert len(g.outputs) == 2
        inp_l = np.full(5, 2.0, dtype=np.float32)
        inp_r = np.full(5, 3.0, dtype=np.float32)
        # Params from parallel(a,b) get prefixed again by series outer ID
        result = simulate(
            g,
            inputs={"a_in": inp_l, "b_in": inp_r},
            params={"a__b_a_level": 1.0, "a__b_b_level": 1.0, "c_level": 0.5},
        )
        np.testing.assert_allclose(result.outputs["out_l"], 1.0, atol=1e-6)
        np.testing.assert_allclose(result.outputs["out_r"], 1.5, atol=1e-6)

    def test_graph_name_composition(self) -> None:
        g = series(_onepole("lpf"), _gain("gain"))
        assert g.name == "lpf__gain"

    def test_sample_rate_propagation(self) -> None:
        a = Graph(
            name="a",
            sample_rate=96000.0,
            inputs=[AudioInput(id="in")],
            outputs=[AudioOutput(id="out", source="x")],
            nodes=[BinOp(id="x", op="mul", a="in", b=1.0)],
        )
        b = _passthrough("b")
        g = series(a, b)
        assert g.sample_rate == 96000.0
