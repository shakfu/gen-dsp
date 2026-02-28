from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
from gen_dsp.graph import (
    SVF,
    AudioInput,
    AudioOutput,
    BinOp,
    Buffer,
    BufRead,
    BufSize,
    BufWrite,
    DelayLine,
    DelayRead,
    DelayWrite,
    Graph,
    GraphValidationError,
    History,
    OnePole,
    Param,
    Subgraph,
    validate_graph,
)

# ---------------------------------------------------------------------------
# Valid graphs
# ---------------------------------------------------------------------------


class TestValidGraphs:
    def test_stereo_gain_valid(self, stereo_gain_graph: Graph) -> None:
        assert validate_graph(stereo_gain_graph) == []

    def test_onepole_valid(self, onepole_graph: Graph) -> None:
        assert validate_graph(onepole_graph) == []

    def test_fbdelay_valid(self, fbdelay_graph: Graph) -> None:
        assert validate_graph(fbdelay_graph) == []

    def test_empty_graph_valid(self) -> None:
        g = Graph(name="empty")
        assert validate_graph(g) == []


# ---------------------------------------------------------------------------
# Duplicate IDs
# ---------------------------------------------------------------------------


class TestDuplicateIds:
    def test_duplicate_node_id(self) -> None:
        g = Graph(
            name="test",
            nodes=[
                BinOp(id="x", op="add", a=1.0, b=2.0),
                BinOp(id="x", op="mul", a=3.0, b=4.0),
            ],
        )
        errors = validate_graph(g)
        assert any("Duplicate node ID" in e for e in errors)

    def test_node_id_collides_with_input(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            nodes=[BinOp(id="in1", op="add", a=1.0, b=2.0)],
        )
        errors = validate_graph(g)
        assert any("collides with audio input" in e for e in errors)

    def test_node_id_collides_with_param(self) -> None:
        g = Graph(
            name="test",
            params=[Param(name="gain")],
            nodes=[BinOp(id="gain", op="add", a=1.0, b=2.0)],
        )
        errors = validate_graph(g)
        assert any("collides with param" in e for e in errors)


# ---------------------------------------------------------------------------
# Dangling references
# ---------------------------------------------------------------------------


class TestDanglingReferences:
    def test_node_references_unknown_id(self) -> None:
        g = Graph(
            name="test",
            nodes=[BinOp(id="x", op="add", a="nonexistent", b=1.0)],
        )
        errors = validate_graph(g)
        assert any("unknown ID 'nonexistent'" in e for e in errors)

    def test_output_references_unknown_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="nonexistent")],
        )
        errors = validate_graph(g)
        assert any("does not reference a node" in e for e in errors)

    def test_literal_float_not_flagged(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="x")],
            nodes=[BinOp(id="x", op="add", a=1.0, b=2.0)],
        )
        assert validate_graph(g) == []


# ---------------------------------------------------------------------------
# Delay consistency
# ---------------------------------------------------------------------------


class TestDelayConsistency:
    def test_delay_read_references_nonexistent_line(self) -> None:
        g = Graph(
            name="test",
            nodes=[DelayRead(id="dr", delay="missing", tap=100.0)],
        )
        errors = validate_graph(g)
        assert any("non-existent delay line 'missing'" in e for e in errors)

    def test_delay_write_references_nonexistent_line(self) -> None:
        g = Graph(
            name="test",
            nodes=[DelayWrite(id="dw", delay="missing", value=1.0)],
        )
        errors = validate_graph(g)
        assert any("non-existent delay line 'missing'" in e for e in errors)

    def test_valid_delay_references(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="dr")],
            nodes=[
                DelayLine(id="dl"),
                DelayRead(id="dr", delay="dl", tap=100.0),
                DelayWrite(id="dw", delay="dl", value=1.0),
            ],
        )
        assert validate_graph(g) == []


# ---------------------------------------------------------------------------
# Buffer consistency
# ---------------------------------------------------------------------------


class TestBufferConsistency:
    def test_bufread_references_nonexistent_buffer(self) -> None:
        g = Graph(
            name="test",
            nodes=[BufRead(id="br", buffer="missing", index=0.0)],
        )
        errors = validate_graph(g)
        assert any("non-existent buffer 'missing'" in e for e in errors)

    def test_bufwrite_references_nonexistent_buffer(self) -> None:
        g = Graph(
            name="test",
            nodes=[BufWrite(id="bw", buffer="missing", index=0.0, value=0.0)],
        )
        errors = validate_graph(g)
        assert any("non-existent buffer 'missing'" in e for e in errors)

    def test_bufsize_references_nonexistent_buffer(self) -> None:
        g = Graph(
            name="test",
            nodes=[BufSize(id="bs", buffer="missing")],
        )
        errors = validate_graph(g)
        assert any("non-existent buffer 'missing'" in e for e in errors)

    def test_valid_buffer_references(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=1024),
                BufRead(id="br", buffer="buf", index=0.0),
                BufWrite(id="bw", buffer="buf", index=0.0, value=0.0),
                BufSize(id="bs", buffer="buf"),
            ],
        )
        assert validate_graph(g) == []


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_pure_cycle_detected(self) -> None:
        """add -> mul -> add with no history should be flagged."""
        g = Graph(
            name="test",
            nodes=[
                BinOp(id="a", op="add", a="b", b=1.0),
                BinOp(id="b", op="mul", a="a", b=2.0),
            ],
        )
        errors = validate_graph(g)
        assert any("cycle" in e.lower() for e in errors)

    def test_cycle_through_history_allowed(self) -> None:
        """result -> History -> result is a valid feedback loop."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="result")],
            nodes=[
                History(id="prev", input="result", init=0.0),
                BinOp(id="result", op="add", a="in1", b="prev"),
            ],
        )
        assert validate_graph(g) == []

    def test_cycle_through_delay_allowed(self) -> None:
        """Delay read/write loop is valid feedback."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="delayed")],
            nodes=[
                DelayLine(id="dl"),
                DelayRead(id="delayed", delay="dl", tap=100.0),
                BinOp(id="fb", op="mul", a="delayed", b=0.5),
                BinOp(id="sum", op="add", a="in1", b="fb"),
                DelayWrite(id="dw", delay="dl", value="sum"),
            ],
        )
        assert validate_graph(g) == []

    def test_svf_mode_not_flagged_as_ref(self) -> None:
        """SVF 'mode' field should not be treated as a dangling reference."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="f")],
            nodes=[SVF(id="f", a="in1", freq=1000.0, q=0.707, mode="lp")],
        )
        assert validate_graph(g) == []

    def test_three_node_cycle(self) -> None:
        """a -> b -> c -> a without feedback."""
        g = Graph(
            name="test",
            nodes=[
                BinOp(id="a", op="add", a="c", b=1.0),
                BinOp(id="b", op="mul", a="a", b=1.0),
                BinOp(id="c", op="sub", a="b", b=1.0),
            ],
        )
        errors = validate_graph(g)
        assert any("cycle" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Structured errors
# ---------------------------------------------------------------------------


class TestStructuredErrors:
    def test_error_has_kind_and_node_id(self) -> None:
        g = Graph(
            name="test",
            nodes=[
                BinOp(id="x", op="add", a=1.0, b=2.0),
                BinOp(id="x", op="mul", a=3.0, b=4.0),
            ],
        )
        errors = validate_graph(g)
        err = next(e for e in errors if "Duplicate" in e)
        assert isinstance(err, GraphValidationError)
        assert err.kind == "duplicate_id"
        assert err.node_id == "x"
        assert err.severity == "error"

    def test_dangling_ref_has_field_name(self) -> None:
        g = Graph(
            name="test",
            nodes=[BinOp(id="x", op="add", a="missing", b=1.0)],
        )
        errors = validate_graph(g)
        err = next(e for e in errors if "unknown ID" in e)
        assert err.kind == "dangling_ref"
        assert err.node_id == "x"
        assert err.field_name == "a"

    def test_bad_output_source(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="gone")],
        )
        errors = validate_graph(g)
        err = next(e for e in errors if "does not reference" in e)
        assert err.kind == "bad_output_source"
        assert err.node_id == "out1"
        assert err.field_name == "source"

    def test_missing_delay_line(self) -> None:
        g = Graph(
            name="test",
            nodes=[DelayRead(id="dr", delay="nope", tap=10.0)],
        )
        errors = validate_graph(g)
        err = next(e for e in errors if "delay line" in e)
        assert err.kind == "missing_delay_line"
        assert err.node_id == "dr"
        assert err.field_name == "delay"

    def test_cycle_error_kind(self) -> None:
        g = Graph(
            name="test",
            nodes=[
                BinOp(id="a", op="add", a="b", b=1.0),
                BinOp(id="b", op="mul", a="a", b=1.0),
            ],
        )
        errors = validate_graph(g)
        err = next(e for e in errors if "cycle" in e.lower())
        assert err.kind == "cycle"
        assert err.node_id is None

    def test_backward_compat_str_ops(self) -> None:
        """GraphValidationError should work with str operations seamlessly."""
        g = Graph(
            name="test",
            nodes=[BinOp(id="x", op="add", a="missing", b=1.0)],
        )
        errors = validate_graph(g)
        assert errors != []
        # join works
        joined = "; ".join(errors)
        assert "unknown ID" in joined
        # f-string works
        msg = f"error: {errors[0]}"
        assert "error:" in msg
        # 'in' works
        assert any("unknown ID" in e for e in errors)


# ---------------------------------------------------------------------------
# Unmapped param warnings
# ---------------------------------------------------------------------------


def _onepole_inner() -> Graph:
    return Graph(
        name="inner_lpf",
        inputs=[AudioInput(id="sig")],
        outputs=[AudioOutput(id="filtered", source="lpf")],
        params=[Param(name="coeff", default=0.5)],
        nodes=[OnePole(id="lpf", a="sig", coeff="coeff")],
    )


class TestUnmappedParamWarnings:
    def test_no_warnings_by_default(self) -> None:
        inner = _onepole_inner()
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            nodes=[Subgraph(id="filt", graph=inner, inputs={"sig": "in1"})],
        )
        errors = validate_graph(g)
        assert errors == []

    def test_warnings_when_opted_in(self) -> None:
        inner = _onepole_inner()
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            nodes=[Subgraph(id="filt", graph=inner, inputs={"sig": "in1"})],
        )
        errors = validate_graph(g, warn_unmapped_params=True)
        warnings = [e for e in errors if e.severity == "warning"]
        assert len(warnings) == 1
        assert warnings[0].kind == "unmapped_param"
        assert "coeff" in warnings[0]
        assert "0.5" in warnings[0]
        assert warnings[0].node_id == "filt"
        assert warnings[0].field_name == "coeff"

    def test_no_warning_when_mapped(self) -> None:
        inner = _onepole_inner()
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            params=[Param(name="c", default=0.5)],
            nodes=[
                Subgraph(
                    id="filt",
                    graph=inner,
                    inputs={"sig": "in1"},
                    params={"coeff": "c"},
                )
            ],
        )
        errors = validate_graph(g, warn_unmapped_params=True)
        assert errors == []

    def test_nested_subgraph_warnings(self) -> None:
        inner = _onepole_inner()
        mid = Graph(
            name="mid",
            inputs=[AudioInput(id="x")],
            outputs=[AudioOutput(id="y", source="sub")],
            params=[Param(name="mid_p", default=0.1)],
            nodes=[Subgraph(id="sub", graph=inner, inputs={"sig": "x"})],
        )
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="outer")],
            nodes=[Subgraph(id="outer", graph=mid, inputs={"x": "in1"})],
        )
        errors = validate_graph(g, warn_unmapped_params=True)
        warnings = [e for e in errors if e.severity == "warning"]
        # outer: mid_p unmapped, outer__sub: coeff unmapped
        assert len(warnings) == 2
        kinds = {w.node_id for w in warnings}
        assert "outer" in kinds
        assert "outer__sub" in kinds

    def test_errors_before_warnings(self) -> None:
        """Errors should appear before warnings in the list."""
        inner = _onepole_inner()
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            # Dangling ref will cause an error (the graph is otherwise valid
            # after expansion, but add a broken node)
            nodes=[
                Subgraph(id="filt", graph=inner, inputs={"sig": "in1"}),
                BinOp(id="broken", op="add", a="nonexistent", b=1.0),
            ],
        )
        errors = validate_graph(g, warn_unmapped_params=True)
        err_indices = [i for i, e in enumerate(errors) if e.severity == "error"]
        warn_indices = [i for i, e in enumerate(errors) if e.severity == "warning"]
        assert err_indices and warn_indices
        assert max(err_indices) < min(warn_indices)
