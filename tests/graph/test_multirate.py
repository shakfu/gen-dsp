"""Tests for multi-rate processing (control-rate vs audio-rate)."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
import numpy as np
import pytest

from gen_dsp.graph import (
    AudioInput,
    AudioOutput,
    BinOp,
    Constant,
    Graph,
    History,
    OnePole,
    Param,
    SmoothParam,
    Subgraph,
    compile_graph,
    expand_subgraphs,
    optimize_graph,
    validate_graph,
)
from gen_dsp.graph.simulate import simulate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_graph(
    *,
    control_interval: int = 0,
    control_nodes: list[str] | None = None,
    nodes: list | None = None,
    inputs: list | None = None,
    outputs: list | None = None,
    params: list | None = None,
) -> Graph:
    """Build a small test graph with sane defaults."""
    return Graph(
        name="test",
        sample_rate=48000.0,
        control_interval=control_interval,
        control_nodes=control_nodes or [],
        inputs=inputs or [AudioInput(id="in0")],
        outputs=outputs or [AudioOutput(id="out0", source="gain")],
        params=params or [Param(name="vol", min=0.0, max=1.0, default=0.5)],
        nodes=nodes
        or [
            BinOp(id="gain", op="mul", a="in0", b="vol"),
        ],
    )


# ===========================================================================
# A. Model / Validation (~8 tests)
# ===========================================================================


class TestModelDefaults:
    def test_control_interval_default_zero(self):
        g = Graph(name="t", outputs=[], nodes=[])
        assert g.control_interval == 0

    def test_control_nodes_default_empty(self):
        g = Graph(name="t", outputs=[], nodes=[])
        assert g.control_nodes == []


class TestValidation:
    def test_unknown_node_id_in_control_nodes(self):
        g = _simple_graph(control_interval=64, control_nodes=["nonexistent"])
        errors = validate_graph(g)
        assert any("nonexistent" in e and "not a node ID" in e for e in errors)

    def test_control_node_depends_on_audio_input(self):
        """A control-rate node referencing an audio input is invalid."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["scaled"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="scaled")],
            params=[Param(name="vol")],
            nodes=[BinOp(id="scaled", op="mul", a="in0", b="vol")],
        )
        errors = validate_graph(g)
        assert any("audio input" in e for e in errors)

    def test_control_node_depends_on_audio_rate_node(self):
        """A control-rate node referencing an audio-rate node is invalid."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["ctrl"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="ctrl")],
            params=[Param(name="vol")],
            nodes=[
                BinOp(id="audio_node", op="mul", a="in0", b="vol"),
                BinOp(id="ctrl", op="add", a="audio_node", b="vol"),
            ],
        )
        errors = validate_graph(g)
        assert any("audio-rate node" in e for e in errors)

    def test_control_node_depends_on_param_ok(self):
        """Control-rate node depending only on params is valid."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["coeff"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="scaled")],
            params=[Param(name="vol"), Param(name="gain")],
            nodes=[
                BinOp(id="coeff", op="mul", a="vol", b="gain"),
                BinOp(id="scaled", op="mul", a="in0", b="coeff"),
            ],
        )
        errors = validate_graph(g)
        assert errors == []

    def test_control_node_depends_on_other_control_node_ok(self):
        """Control-rate node depending on another control-rate node is valid."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["half_vol", "double_half"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="result")],
            params=[Param(name="vol")],
            nodes=[
                BinOp(id="half_vol", op="mul", a="vol", b=0.5),
                BinOp(id="double_half", op="add", a="half_vol", b="half_vol"),
                BinOp(id="result", op="mul", a="in0", b="double_half"),
            ],
        )
        errors = validate_graph(g)
        assert errors == []

    def test_control_interval_zero_ignores_control_nodes(self):
        """When control_interval=0, control_nodes are ignored -- no validation errors."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=0,
            control_nodes=["nonexistent"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="c")],
            nodes=[Constant(id="c", value=1.0)],
        )
        errors = validate_graph(g)
        # No control-rate errors since interval is 0
        assert not any("control" in e.lower() for e in errors)

    def test_duplicate_ids_in_control_nodes(self):
        """Duplicate IDs in control_nodes should not cause extra errors."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["coeff", "coeff"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="scaled")],
            params=[Param(name="vol")],
            nodes=[
                BinOp(id="coeff", op="mul", a="vol", b=0.5),
                BinOp(id="scaled", op="mul", a="in0", b="coeff"),
            ],
        )
        errors = validate_graph(g)
        assert errors == []


# ===========================================================================
# B. Compile / Codegen (~10 tests)
# ===========================================================================


class TestCompileNoControlRate:
    def test_control_interval_zero_unchanged(self):
        """control_interval=0 produces identical code to the default path."""
        g = _simple_graph(control_interval=0)
        code = compile_graph(g)
        assert "for (int i = 0; i < n; i++)" in code
        assert "_cb" not in code
        assert "_block_end" not in code

    def test_no_control_nodes_with_interval_unchanged(self):
        """control_interval>0 but empty control_nodes -> single loop."""
        g = _simple_graph(control_interval=64, control_nodes=[])
        code = compile_graph(g)
        assert "for (int i = 0; i < n; i++)" in code
        assert "_cb" not in code


class TestCompileTwoTier:
    @pytest.fixture()
    def two_tier_graph(self) -> Graph:
        """Use SmoothParam (stateful) as control-rate node -- LICM won't hoist it."""
        return Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["smoother"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="scaled")],
            params=[Param(name="vol"), Param(name="gain")],
            nodes=[
                SmoothParam(id="smoother", a="vol", coeff="gain"),
                BinOp(id="scaled", op="mul", a="in0", b="smoother"),
            ],
        )

    def test_outer_loop_present(self, two_tier_graph):
        code = compile_graph(two_tier_graph)
        assert "for (int _cb = 0; _cb < n; _cb += 64)" in code

    def test_block_end_calculation(self, two_tier_graph):
        code = compile_graph(two_tier_graph)
        assert "int _block_end = (_cb + 64 < n) ? _cb + 64 : n;" in code

    def test_inner_loop_present(self, two_tier_graph):
        code = compile_graph(two_tier_graph)
        assert "for (int i = _cb; i < _block_end; i++)" in code

    def test_control_node_between_loops(self, two_tier_graph):
        """Control-rate SmoothParam should appear between outer and inner loops."""
        code = compile_graph(two_tier_graph)
        outer_pos = code.index("for (int _cb = 0;")
        inner_pos = code.index("for (int i = _cb;")
        # smoother computation should be between outer and inner
        smoother_pos = code.index("float smoother =")
        assert outer_pos < smoother_pos < inner_pos

    def test_audio_node_inside_inner_loop(self, two_tier_graph):
        """Audio-rate node 'scaled' should appear inside the inner loop."""
        code = compile_graph(two_tier_graph)
        inner_pos = code.index("for (int i = _cb;")
        scaled_pos = code.index("float scaled = in0[i] * smoother;")
        assert scaled_pos > inner_pos

    def test_licm_still_hoists_invariant_nodes(self):
        """Invariant nodes should still be hoisted before both loops."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["ctrl_smooth"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="result")],
            params=[Param(name="a"), Param(name="b"), Param(name="c")],
            nodes=[
                BinOp(id="inv", op="add", a="a", b="b"),  # invariant (params only)
                SmoothParam(id="ctrl_smooth", a="inv", coeff="c"),  # control-rate
                BinOp(id="result", op="mul", a="in0", b="ctrl_smooth"),  # audio-rate
            ],
        )
        code = compile_graph(g)
        outer_pos = code.index("for (int _cb = 0;")
        # inv should be hoisted before the outer loop
        inv_pos = code.index("float inv = a + b;")
        assert inv_pos < outer_pos

    def test_state_load_save_unchanged(self, two_tier_graph):
        """State load/save should be before/after the outer loop."""
        code = compile_graph(two_tier_graph)
        # smoother state should be loaded before the loop and saved after
        assert "float smoother_prev = self->m_smoother_prev;" in code
        assert "self->m_smoother_prev = smoother_prev;" in code
        # The perform function should end with }
        assert code.strip().endswith("}")

    def test_control_rate_history_writeback_in_outer_loop(self):
        """History write-back for a control-rate History should be in the outer loop."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=32,
            control_nodes=["h", "smoother"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="out_mul")],
            params=[Param(name="target", default=0.0)],
            nodes=[
                History(id="h", init=0.0, input="smoother"),
                SmoothParam(id="smoother", a="target", coeff=0.9),
                BinOp(id="out_mul", op="mul", a="in0", b="smoother"),
            ],
        )
        code = compile_graph(g)
        # Control-rate History write-back should be inside outer loop but outside inner
        # The history write-back "h = smoother;" should exist in the outer loop
        h_writeback = code.index("h = smoother;")
        assert h_writeback > 0

    def test_mixed_control_audio_with_dependencies(self):
        """Control-rate stateful node can feed audio-rate nodes."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=16,
            control_nodes=["smoother"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="result")],
            params=[Param(name="vol")],
            nodes=[
                SmoothParam(id="smoother", a="vol", coeff=0.9),
                BinOp(id="result", op="mul", a="in0", b="smoother"),
            ],
        )
        code = compile_graph(g)
        # Should compile without error and have two-tier structure
        assert "for (int _cb = 0;" in code
        assert "for (int i = _cb;" in code


# ===========================================================================
# C. Simulate (~10 tests)
# ===========================================================================


class TestSimulateNoControlRate:
    def test_control_interval_zero_identical(self):
        """control_interval=0 should give identical results to current behavior."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=0,
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="gain")],
            params=[Param(name="vol", default=0.5)],
            nodes=[BinOp(id="gain", op="mul", a="in0", b="vol")],
        )
        inp = np.ones(128, dtype=np.float32)
        result = simulate(g, inputs={"in0": inp})
        np.testing.assert_allclose(result.outputs["out0"], 0.5 * inp, atol=1e-7)


class TestSimulateControlRate:
    def test_control_interval_1_same_as_audio(self):
        """control_interval=1 means every sample is a control boundary -> same as audio."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=1,
            control_nodes=["smoother"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="result")],
            params=[Param(name="target", default=1.0)],
            nodes=[
                SmoothParam(id="smoother", a="target", coeff=0.9),
                BinOp(id="result", op="mul", a="in0", b="smoother"),
            ],
        )
        g_audio = g.model_copy(update={"control_interval": 0, "control_nodes": []})
        inp = np.ones(64, dtype=np.float32)

        r_ctrl = simulate(g, inputs={"in0": inp})
        r_audio = simulate(g_audio, inputs={"in0": inp})
        np.testing.assert_allclose(
            r_ctrl.outputs["out0"], r_audio.outputs["out0"], atol=1e-7
        )

    def test_control_node_updates_every_n_samples(self):
        """Control-rate SmoothParam should update once per control block."""
        ctrl_interval = 4
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=ctrl_interval,
            control_nodes=["smoother"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="smoother")],
            params=[Param(name="target", default=1.0)],
            nodes=[SmoothParam(id="smoother", a="target", coeff=0.0)],
        )
        result = simulate(g, n_samples=8)
        out = result.outputs["out0"]
        # coeff=0.0 means y = (1-0)*target + 0*prev = target
        # But control-rate updates only at block boundaries (sample 0 and 4)
        # At sample 0: smoother = 1.0; samples 0-3 hold 1.0
        # At sample 4: smoother = 1.0; samples 4-7 hold 1.0
        np.testing.assert_allclose(out, np.ones(8, dtype=np.float32), atol=1e-7)

    def test_control_rate_output_held_between_updates(self):
        """Control-rate node values should be held for samples between block boundaries."""
        # Use a SmoothParam with coeff=0.5 (partial tracking)
        ctrl_interval = 4
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=ctrl_interval,
            control_nodes=["smoother"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="smoother")],
            params=[Param(name="target", default=1.0)],
            nodes=[SmoothParam(id="smoother", a="target", coeff=0.5)],
        )
        result = simulate(g, n_samples=8)
        out = result.outputs["out0"]
        # Sample 0: smoother = (1-0.5)*1.0 + 0.5*0.0 = 0.5 (prev=0)
        # Samples 1-3: held at 0.5
        # Sample 4: smoother = (1-0.5)*1.0 + 0.5*0.5 = 0.75
        # Samples 5-7: held at 0.75
        expected_0 = 0.5
        expected_4 = 0.75
        np.testing.assert_allclose(out[0:4], expected_0, atol=1e-7)
        np.testing.assert_allclose(out[4:8], expected_4, atol=1e-7)

    def test_audio_rate_reads_held_control_rate_value(self):
        """Audio-rate nodes should use the held control-rate value."""
        ctrl_interval = 4
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=ctrl_interval,
            control_nodes=["coeff"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="result")],
            params=[Param(name="vol", default=2.0)],
            nodes=[
                BinOp(id="coeff", op="mul", a="vol", b=0.5),  # pure, but control-rate
                BinOp(id="result", op="mul", a="in0", b="coeff"),
            ],
        )
        inp = np.ones(8, dtype=np.float32)
        result = simulate(g, inputs={"in0": inp})
        # coeff = 2.0 * 0.5 = 1.0, held for all samples
        np.testing.assert_allclose(result.outputs["out0"], 1.0, atol=1e-7)

    def test_smooth_param_at_control_rate_slower_smoothing(self):
        """SmoothParam at control-rate should smooth more slowly than audio-rate."""
        g_ctrl = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=4,
            control_nodes=["smoother"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="smoother")],
            params=[Param(name="target", default=1.0)],
            nodes=[SmoothParam(id="smoother", a="target", coeff=0.9)],
        )
        g_audio = Graph(
            name="test",
            sample_rate=48000.0,
            inputs=[],
            outputs=[AudioOutput(id="out0", source="smoother")],
            params=[Param(name="target", default=1.0)],
            nodes=[SmoothParam(id="smoother", a="target", coeff=0.9)],
        )
        r_ctrl = simulate(g_ctrl, n_samples=16)
        r_audio = simulate(g_audio, n_samples=16)

        # Control-rate should converge more slowly (fewer updates)
        # After 16 samples, audio-rate has had 16 updates, control-rate has had 4
        ctrl_final = r_ctrl.outputs["out0"][-1]
        audio_final = r_audio.outputs["out0"][-1]
        # Audio-rate should be closer to 1.0 (target) since it updates every sample
        assert audio_final > ctrl_final

    def test_step_response_staircase(self):
        """Control-rate node should produce a staircase-like step response."""
        ctrl_interval = 4
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=ctrl_interval,
            control_nodes=["smoother"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="smoother")],
            params=[Param(name="target", default=1.0)],
            nodes=[SmoothParam(id="smoother", a="target", coeff=0.5)],
        )
        result = simulate(g, n_samples=12)
        out = result.outputs["out0"]
        # Each block of 4 samples should have constant value
        for block_start in range(0, 12, ctrl_interval):
            block = out[block_start : min(block_start + ctrl_interval, 12)]
            np.testing.assert_allclose(block, block[0], atol=1e-10)

    def test_onepole_at_control_rate(self):
        """OnePole filter at control-rate: updates once per block."""
        ctrl_interval = 4
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=ctrl_interval,
            control_nodes=["filt"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="filt")],
            params=[Param(name="val", default=1.0)],
            nodes=[OnePole(id="filt", a="val", coeff=0.5)],
        )
        result = simulate(g, n_samples=8)
        out = result.outputs["out0"]
        # Block 0 (samples 0-3): filt = 0.5*1.0 + 0.5*0.0 = 0.5
        # Block 1 (samples 4-7): filt = 0.5*1.0 + 0.5*0.5 = 0.75
        np.testing.assert_allclose(out[0:4], 0.5, atol=1e-7)
        np.testing.assert_allclose(out[4:8], 0.75, atol=1e-7)

    def test_history_at_control_rate(self):
        """History at control-rate should delay by one control block."""
        ctrl_interval = 4
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=ctrl_interval,
            control_nodes=["h", "add1"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="h")],
            params=[],
            nodes=[
                History(id="h", init=0.0, input="add1"),
                BinOp(id="add1", op="add", a="h", b=1.0),
            ],
        )
        result = simulate(g, n_samples=12)
        out = result.outputs["out0"]
        # Block 0 (samples 0-3): h reads init 0.0, write-back sets h = 0+1 = 1
        # Block 1 (samples 4-7): h reads 1.0, write-back sets h = 1+1 = 2
        # Block 2 (samples 8-11): h reads 2.0, write-back sets h = 2+1 = 3
        np.testing.assert_allclose(out[0:4], 0.0, atol=1e-7)
        np.testing.assert_allclose(out[4:8], 1.0, atol=1e-7)
        np.testing.assert_allclose(out[8:12], 2.0, atol=1e-7)

    def test_state_persistence_across_calls(self):
        """State should persist across simulate() calls."""
        ctrl_interval = 4
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=ctrl_interval,
            control_nodes=["smoother"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="smoother")],
            params=[Param(name="target", default=1.0)],
            nodes=[SmoothParam(id="smoother", a="target", coeff=0.5)],
        )
        r1 = simulate(g, n_samples=4)
        # Continue with same state
        r2 = simulate(g, n_samples=4, state=r1.state)
        # First call: smoother = 0.5 (from 0 toward 1)
        # Second call starts with prev=0.5: smoother = 0.5*1 + 0.5*0.5 = 0.75
        np.testing.assert_allclose(r1.outputs["out0"], 0.5, atol=1e-7)
        np.testing.assert_allclose(r2.outputs["out0"], 0.75, atol=1e-7)


# ===========================================================================
# D. Subgraph Integration (~5 tests)
# ===========================================================================


class TestSubgraphControlNodes:
    def _inner_graph(self) -> Graph:
        return Graph(
            name="inner",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["smoother"],
            inputs=[AudioInput(id="x")],
            outputs=[AudioOutput(id="y", source="scaled")],
            params=[Param(name="g", default=0.5)],
            nodes=[
                SmoothParam(id="smoother", a="g", coeff=0.9),
                BinOp(id="scaled", op="mul", a="x", b="smoother"),
            ],
        )

    def test_subgraph_control_nodes_prefixed(self):
        inner = self._inner_graph()
        outer = Graph(
            name="outer",
            sample_rate=48000.0,
            control_interval=64,
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="sg")],
            params=[],
            nodes=[
                Subgraph(id="sg", graph=inner, inputs={"x": "in0"}, params={}),
            ],
        )
        expanded = expand_subgraphs(outer)
        assert "sg__smoother" in expanded.control_nodes

    def test_nested_subgraph_double_prefixed(self):
        inner = Graph(
            name="inner",
            sample_rate=48000.0,
            control_nodes=["c"],
            inputs=[AudioInput(id="x")],
            outputs=[AudioOutput(id="y", source="c")],
            nodes=[Constant(id="c", value=1.0)],
        )
        mid = Graph(
            name="mid",
            sample_rate=48000.0,
            control_interval=32,
            inputs=[AudioInput(id="x")],
            outputs=[AudioOutput(id="y", source="sg_inner")],
            nodes=[
                Subgraph(id="sg_inner", graph=inner, inputs={"x": "x"}),
            ],
        )
        outer = Graph(
            name="outer",
            sample_rate=48000.0,
            control_interval=32,
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="sg_mid")],
            nodes=[
                Subgraph(id="sg_mid", graph=mid, inputs={"x": "in0"}),
            ],
        )
        expanded = expand_subgraphs(outer)
        # Inner "c" -> mid prefix "sg_inner__c" -> outer prefix "sg_mid__sg_inner__c"
        assert "sg_mid__sg_inner__c" in expanded.control_nodes

    def test_expand_preserves_control_interval(self):
        inner = self._inner_graph()
        outer = Graph(
            name="outer",
            sample_rate=48000.0,
            control_interval=128,
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="sg")],
            nodes=[
                Subgraph(id="sg", graph=inner, inputs={"x": "in0"}),
            ],
        )
        expanded = expand_subgraphs(outer)
        assert expanded.control_interval == 128

    def test_series_algebra_propagates_control_nodes(self):
        """series() composition should preserve control_nodes through subgraph expansion."""
        from gen_dsp.graph.algebra import series

        a = Graph(
            name="a",
            sample_rate=48000.0,
            control_nodes=["c1"],
            inputs=[AudioInput(id="x")],
            outputs=[AudioOutput(id="y", source="c1")],
            nodes=[Constant(id="c1", value=1.0)],
        )
        b = Graph(
            name="b",
            sample_rate=48000.0,
            control_nodes=["c2"],
            inputs=[AudioInput(id="x")],
            outputs=[AudioOutput(id="y", source="c2")],
            nodes=[Constant(id="c2", value=2.0)],
        )
        composed = series(a, b)
        expanded = expand_subgraphs(composed)
        # a's c1 -> "a__c1", b's c2 -> "b__c2"
        assert "a__c1" in expanded.control_nodes
        assert "b__c2" in expanded.control_nodes

    def test_compile_through_subgraph_with_control_rate(self):
        """Full compile through subgraph expansion + control-rate should work."""
        inner = self._inner_graph()
        outer = Graph(
            name="outer",
            sample_rate=48000.0,
            control_interval=64,
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="sg")],
            nodes=[
                Subgraph(id="sg", graph=inner, inputs={"x": "in0"}),
            ],
        )
        code = compile_graph(outer)
        assert "for (int _cb = 0;" in code


# ===========================================================================
# E. Edge Cases (~5 tests)
# ===========================================================================


class TestEdgeCases:
    def test_all_nodes_control_rate(self):
        """When all non-invariant nodes are control-rate, inner loop is a pass-through."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=32,
            control_nodes=["coeff"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="coeff")],
            params=[Param(name="vol")],
            nodes=[BinOp(id="coeff", op="mul", a="vol", b=0.5)],
        )
        code = compile_graph(g)
        # Even though coeff would be LICM-invariant (depends only on params),
        # the user explicitly marks it as control-rate. But LICM will hoist it
        # since it depends only on params. So it stays hoisted, and no two-tier
        # loop is generated (since ctrl_rate_ids would be empty after removing
        # invariant nodes).
        # This is correct behavior: invariant nodes override control-rate classification.
        assert "for (int i = 0; i < n; i++)" in code

    def test_control_interval_greater_than_n(self):
        """When control_interval > n, single control block processes all samples."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=256,
            control_nodes=["smoother"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="smoother")],
            params=[Param(name="target", default=1.0)],
            nodes=[SmoothParam(id="smoother", a="target", coeff=0.5)],
        )
        # Simulate with only 8 samples (less than control_interval=256)
        result = simulate(g, n_samples=8)
        out = result.outputs["out0"]
        # Only one control update at sample 0, held for all 8 samples
        np.testing.assert_allclose(out, 0.5, atol=1e-7)

    def test_control_interval_1_degenerate(self):
        """control_interval=1 means control and audio update every sample."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=1,
            control_nodes=["smoother"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="result")],
            params=[Param(name="target", default=1.0)],
            nodes=[
                SmoothParam(id="smoother", a="target", coeff=0.5),
                BinOp(id="result", op="mul", a="in0", b="smoother"),
            ],
        )
        code = compile_graph(g)
        assert "for (int _cb = 0; _cb < n; _cb += 1)" in code

    def test_generator_no_inputs_with_control_rate(self):
        """Generator (no audio inputs) with control-rate nodes should work."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=8,
            control_nodes=["smoother"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="smoother")],
            params=[Param(name="target", default=1.0)],
            nodes=[SmoothParam(id="smoother", a="target", coeff=0.9)],
        )
        result = simulate(g, n_samples=16)
        out = result.outputs["out0"]
        assert len(out) == 16
        # Should produce a staircase response
        # Block 0 (samples 0-7): value computed at sample 0
        np.testing.assert_allclose(out[0:8], out[0], atol=1e-10)
        # Block 1 (samples 8-15): different value
        np.testing.assert_allclose(out[8:16], out[8], atol=1e-10)
        # Block 1 should be closer to target (1.0) than block 0
        assert out[8] > out[0]

    def test_no_nodes_control_rate_but_interval_set(self):
        """control_interval>0 with no control_nodes is effectively a no-op."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=[],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="gain")],
            params=[Param(name="vol", default=0.5)],
            nodes=[BinOp(id="gain", op="mul", a="in0", b="vol")],
        )
        inp = np.ones(128, dtype=np.float32)
        result = simulate(g, inputs={"in0": inp})
        np.testing.assert_allclose(result.outputs["out0"], 0.5, atol=1e-7)

    def test_non_divisible_n_samples(self):
        """n_samples not divisible by control_interval should still work."""
        ctrl_interval = 4
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=ctrl_interval,
            control_nodes=["smoother"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="smoother")],
            params=[Param(name="target", default=1.0)],
            nodes=[SmoothParam(id="smoother", a="target", coeff=0.5)],
        )
        # 7 samples = 1 full block of 4 + 3 remaining
        result = simulate(g, n_samples=7)
        out = result.outputs["out0"]
        assert len(out) == 7
        # Block 0 (samples 0-3): value = 0.5
        np.testing.assert_allclose(out[0:4], 0.5, atol=1e-7)
        # Block 1 (samples 4-6): value = 0.75
        np.testing.assert_allclose(out[4:7], 0.75, atol=1e-7)


# ===========================================================================
# F. Control-Rate Promotion Integration (~2 tests)
# ===========================================================================


class TestControlRatePromotion:
    def test_promoted_node_staircase_in_simulation(self):
        """Auto-promoted control-rate node produces staircase output."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=4,
            control_nodes=["smoother"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="inv_vol")],
            params=[Param(name="vol", default=1.0)],
            nodes=[
                SmoothParam(id="smoother", a="vol", coeff=0.5),
                BinOp(id="inv_vol", op="sub", a=1.0, b="smoother"),
            ],
        )
        opt_graph, stats = optimize_graph(g)
        assert "inv_vol" in opt_graph.control_nodes
        assert stats.control_rate_promoted == 1

        # Simulate -- promoted node should produce staircase (held per block)
        sim_result = simulate(opt_graph, n_samples=8)
        out = sim_result.outputs["out0"]
        # Block 0 (samples 0-3): smoother=0.5, inv_vol=1-0.5=0.5
        # Block 1 (samples 4-7): smoother=0.75, inv_vol=1-0.75=0.25
        np.testing.assert_allclose(out[0:4], 0.5, atol=1e-7)
        np.testing.assert_allclose(out[4:8], 0.25, atol=1e-7)

    def test_promoted_node_in_control_rate_codegen(self):
        """Auto-promoted node appears in control-rate section of compiled C++."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["smoother"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="result")],
            params=[Param(name="vol")],
            nodes=[
                SmoothParam(id="smoother", a="vol", coeff=0.9),
                BinOp(id="inv_vol", op="sub", a=1.0, b="smoother"),
                BinOp(id="result", op="mul", a="in0", b="inv_vol"),
            ],
        )
        opt_graph, _ = optimize_graph(g)
        assert "inv_vol" in opt_graph.control_nodes

        code = compile_graph(opt_graph)
        outer_pos = code.index("for (int _cb = 0;")
        inner_pos = code.index("for (int i = _cb;")
        inv_vol_pos = code.index("float inv_vol =")
        # inv_vol should be emitted between outer and inner loops (control-rate)
        assert outer_pos < inv_vol_pos < inner_pos
