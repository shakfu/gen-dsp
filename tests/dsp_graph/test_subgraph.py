"""Tests for subgraph expansion."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
import pytest

from gen_dsp.dsp_graph import (
    AudioInput,
    AudioOutput,
    BinOp,
    Graph,
    History,
    OnePole,
    Param,
    Subgraph,
    compile_graph,
    expand_subgraphs,
    optimize_graph,
    validate_graph,
)


def _onepole_graph() -> Graph:
    """Simple onepole inner graph: 1 input, 1 output, 1 param."""
    return Graph(
        name="inner_lpf",
        inputs=[AudioInput(id="sig")],
        outputs=[AudioOutput(id="filtered", source="lpf")],
        params=[Param(name="coeff", default=0.5)],
        nodes=[
            OnePole(id="lpf", a="sig", coeff="coeff"),
        ],
    )


def _two_output_graph() -> Graph:
    """Inner graph with 2 outputs."""
    return Graph(
        name="inner_split",
        inputs=[AudioInput(id="sig")],
        outputs=[
            AudioOutput(id="lo", source="low"),
            AudioOutput(id="hi", source="high"),
        ],
        params=[Param(name="coeff", default=0.3)],
        nodes=[
            OnePole(id="low", a="sig", coeff="coeff"),
            BinOp(id="high", op="sub", a="sig", b="low"),
        ],
    )


# ---------------------------------------------------------------------------
# Basic expansion
# ---------------------------------------------------------------------------


class TestBasicExpansion:
    def test_single_output_subgraph(self) -> None:
        inner = _onepole_graph()
        graph = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            nodes=[
                Subgraph(id="filt", graph=inner, inputs={"sig": "in1"}),
            ],
        )
        expanded = expand_subgraphs(graph)

        # No Subgraph nodes remain
        assert not any(isinstance(n, Subgraph) for n in expanded.nodes)

        # Prefixed inner node
        ids = {n.id for n in expanded.nodes}
        assert "filt__lpf" in ids

        # Output rewired to prefixed node
        assert expanded.outputs[0].source == "filt__lpf"

    def test_multi_output_subgraph(self) -> None:
        inner = _two_output_graph()
        graph = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out_lo", source="split"),
                AudioOutput(id="out_hi", source="split__hi"),
            ],
            nodes=[
                Subgraph(id="split", graph=inner, inputs={"sig": "in1"}),
            ],
        )
        expanded = expand_subgraphs(graph)

        # Default output (first = "lo") maps to split__low
        assert expanded.outputs[0].source == "split__low"
        # Compound ID "split__hi" maps to split__high
        assert expanded.outputs[1].source == "split__high"

    def test_nested_subgraph(self) -> None:
        inner = _onepole_graph()
        mid = Graph(
            name="mid",
            inputs=[AudioInput(id="x")],
            outputs=[AudioOutput(id="y", source="sub")],
            nodes=[
                Subgraph(id="sub", graph=inner, inputs={"sig": "x"}),
            ],
        )
        graph = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="outer")],
            nodes=[
                Subgraph(id="outer", graph=mid, inputs={"x": "in1"}),
            ],
        )
        expanded = expand_subgraphs(graph)

        # Double-prefixed: outer__sub__lpf
        ids = {n.id for n in expanded.nodes}
        assert "outer__sub__lpf" in ids
        assert expanded.outputs[0].source == "outer__sub__lpf"

    def test_multiple_instances(self) -> None:
        inner = _onepole_graph()
        graph = Graph(
            name="test",
            inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
            outputs=[
                AudioOutput(id="out1", source="filt_a"),
                AudioOutput(id="out2", source="filt_b"),
            ],
            nodes=[
                Subgraph(id="filt_a", graph=inner, inputs={"sig": "in1"}),
                Subgraph(id="filt_b", graph=inner, inputs={"sig": "in2"}),
            ],
        )
        expanded = expand_subgraphs(graph)

        ids = {n.id for n in expanded.nodes}
        assert "filt_a__lpf" in ids
        assert "filt_b__lpf" in ids
        # Independent nodes
        assert len(ids) == 2

    def test_unmapped_params_use_defaults(self) -> None:
        inner = _onepole_graph()
        graph = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            nodes=[
                Subgraph(id="filt", graph=inner, inputs={"sig": "in1"}),
                # coeff param not mapped -- should use default 0.5
            ],
        )
        expanded = expand_subgraphs(graph)
        lpf = next(n for n in expanded.nodes if n.id == "filt__lpf")
        assert isinstance(lpf, OnePole)
        # coeff should be the default float value
        assert lpf.coeff == 0.5

    def test_mapped_params(self) -> None:
        inner = _onepole_graph()
        graph = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            params=[Param(name="my_coeff", default=0.7)],
            nodes=[
                Subgraph(
                    id="filt",
                    graph=inner,
                    inputs={"sig": "in1"},
                    params={"coeff": "my_coeff"},
                ),
            ],
        )
        expanded = expand_subgraphs(graph)
        lpf = next(n for n in expanded.nodes if n.id == "filt__lpf")
        assert isinstance(lpf, OnePole)
        assert lpf.coeff == "my_coeff"

    def test_no_subgraphs_passthrough(self) -> None:
        graph = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="g")],
            nodes=[BinOp(id="g", op="mul", a="in1", b=0.5)],
        )
        result = expand_subgraphs(graph)
        assert result is graph  # same object, no copy

    def test_output_selector(self) -> None:
        inner = _two_output_graph()
        graph = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="split")],
            nodes=[
                Subgraph(
                    id="split",
                    graph=inner,
                    inputs={"sig": "in1"},
                    output="hi",
                ),
            ],
        )
        expanded = expand_subgraphs(graph)
        # "hi" output selected, source is inner "high" node
        assert expanded.outputs[0].source == "split__high"


# ---------------------------------------------------------------------------
# Integration with pipeline
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    def test_expand_then_compile(self) -> None:
        inner = _onepole_graph()
        graph = Graph(
            name="test_expand",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            params=[Param(name="c", default=0.5)],
            nodes=[
                Subgraph(
                    id="filt",
                    graph=inner,
                    inputs={"sig": "in1"},
                    params={"coeff": "c"},
                ),
            ],
        )
        expanded = expand_subgraphs(graph)
        code = compile_graph(expanded)
        assert "filt__lpf" in code
        assert "test_expand_perform" in code

    def test_compile_auto_expands(self) -> None:
        inner = _onepole_graph()
        graph = Graph(
            name="test_auto",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            params=[Param(name="c", default=0.5)],
            nodes=[
                Subgraph(
                    id="filt",
                    graph=inner,
                    inputs={"sig": "in1"},
                    params={"coeff": "c"},
                ),
            ],
        )
        # compile_graph should handle expansion transparently
        code = compile_graph(graph)
        assert "filt__lpf" in code

    def test_validate_auto_expands(self) -> None:
        inner = _onepole_graph()
        graph = Graph(
            name="test_val",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            nodes=[
                Subgraph(id="filt", graph=inner, inputs={"sig": "in1"}),
            ],
        )
        errors = validate_graph(graph)
        assert errors == []

    def test_validate_catches_expansion_error(self) -> None:
        inner = _onepole_graph()
        graph = Graph(
            name="test_val_err",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            nodes=[
                # Missing required input mapping
                Subgraph(id="filt", graph=inner, inputs={}),
            ],
        )
        errors = validate_graph(graph)
        assert len(errors) == 1
        assert "missing input mapping" in errors[0].lower()

    def test_optimize_auto_expands(self) -> None:
        inner = _onepole_graph()
        graph = Graph(
            name="test_opt",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            nodes=[
                Subgraph(id="filt", graph=inner, inputs={"sig": "in1"}),
            ],
        )
        optimized, _stats = optimize_graph(graph)
        assert not any(isinstance(n, Subgraph) for n in optimized.nodes)


# ---------------------------------------------------------------------------
# Stateful subgraph
# ---------------------------------------------------------------------------


class TestStatefulSubgraph:
    def test_stateful_subgraph(self) -> None:
        """History inside subgraph -- state fields get prefixed names."""
        inner = Graph(
            name="inner_fb",
            inputs=[AudioInput(id="sig")],
            outputs=[AudioOutput(id="y", source="result")],
            params=[Param(name="coeff", default=0.5)],
            nodes=[
                History(id="prev", init=0.0, input="result"),
                BinOp(id="wet", op="mul", a="prev", b="coeff"),
                BinOp(id="inv", op="sub", a=1.0, b="coeff"),
                BinOp(id="dry", op="mul", a="sig", b="inv"),
                BinOp(id="result", op="add", a="dry", b="wet"),
            ],
        )
        graph = Graph(
            name="test_state",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="filt")],
            params=[Param(name="c", default=0.5)],
            nodes=[
                Subgraph(
                    id="filt",
                    graph=inner,
                    inputs={"sig": "in1"},
                    params={"coeff": "c"},
                ),
            ],
        )
        code = compile_graph(graph)
        # History state field should be prefixed
        assert "m_filt__prev" in code
        # Prefixed node IDs in compute
        assert "filt__result" in code


# ---------------------------------------------------------------------------
# Subgraph references between parent nodes
# ---------------------------------------------------------------------------


class TestSubgraphRefs:
    def test_parent_node_refs_subgraph_output(self) -> None:
        """A parent-level node references a subgraph output by its ID."""
        inner = _onepole_graph()
        graph = Graph(
            name="test_ref",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="scaled")],
            params=[Param(name="c", default=0.5)],
            nodes=[
                Subgraph(
                    id="filt",
                    graph=inner,
                    inputs={"sig": "in1"},
                    params={"coeff": "c"},
                ),
                BinOp(id="scaled", op="mul", a="filt", b=0.5),
            ],
        )
        expanded = expand_subgraphs(graph)
        scaled = next(n for n in expanded.nodes if n.id == "scaled")
        assert isinstance(scaled, BinOp)
        # "filt" should be rewritten to "filt__lpf"
        assert scaled.a == "filt__lpf"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestSubgraphErrors:
    def test_missing_input_mapping(self) -> None:
        inner = _onepole_graph()
        with pytest.raises(ValueError, match="missing input mapping"):
            expand_subgraphs(
                Graph(
                    name="t",
                    outputs=[AudioOutput(id="o", source="sg")],
                    nodes=[Subgraph(id="sg", graph=inner, inputs={})],
                )
            )

    def test_unknown_input_key(self) -> None:
        inner = _onepole_graph()
        with pytest.raises(ValueError, match="input key 'bogus' not found"):
            expand_subgraphs(
                Graph(
                    name="t",
                    outputs=[AudioOutput(id="o", source="sg")],
                    nodes=[
                        Subgraph(
                            id="sg",
                            graph=inner,
                            inputs={"sig": 0.0, "bogus": 0.0},
                        )
                    ],
                )
            )

    def test_unknown_param_key(self) -> None:
        inner = _onepole_graph()
        with pytest.raises(ValueError, match="param key 'bogus' not found"):
            expand_subgraphs(
                Graph(
                    name="t",
                    outputs=[AudioOutput(id="o", source="sg")],
                    nodes=[
                        Subgraph(
                            id="sg",
                            graph=inner,
                            inputs={"sig": 0.0},
                            params={"bogus": 0.5},
                        )
                    ],
                )
            )

    def test_invalid_output_selector(self) -> None:
        inner = _onepole_graph()
        with pytest.raises(ValueError, match="output 'nope' not found"):
            expand_subgraphs(
                Graph(
                    name="t",
                    outputs=[AudioOutput(id="o", source="sg")],
                    nodes=[
                        Subgraph(
                            id="sg",
                            graph=inner,
                            inputs={"sig": 0.0},
                            output="nope",
                        )
                    ],
                )
            )

    def test_no_outputs_error(self) -> None:
        inner = Graph(name="empty", inputs=[AudioInput(id="x")])
        with pytest.raises(ValueError, match="no outputs"):
            expand_subgraphs(
                Graph(
                    name="t",
                    outputs=[AudioOutput(id="o", source="sg")],
                    nodes=[Subgraph(id="sg", graph=inner, inputs={"x": 0.0})],
                )
            )


# ---------------------------------------------------------------------------
# Param namespace collision detection
# ---------------------------------------------------------------------------


class TestParamNamespaceCollision:
    def test_collision_with_parent_param(self) -> None:
        """Expanded node ID collides with a parent param name."""
        inner = Graph(
            name="inner",
            inputs=[AudioInput(id="sig")],
            outputs=[AudioOutput(id="y", source="lpf")],
            nodes=[OnePole(id="lpf", a="sig", coeff=0.5)],
        )
        # Subgraph id="my" + inner node "lpf" -> "my__lpf"
        # Parent param named "my__lpf" -> collision
        with pytest.raises(ValueError, match="collides with parent param"):
            expand_subgraphs(
                Graph(
                    name="t",
                    inputs=[AudioInput(id="in1")],
                    outputs=[AudioOutput(id="o", source="my")],
                    params=[Param(name="my__lpf", default=0.0)],
                    nodes=[Subgraph(id="my", graph=inner, inputs={"sig": "in1"})],
                )
            )

    def test_collision_with_parent_input(self) -> None:
        """Expanded node ID collides with a parent audio input ID."""
        inner = Graph(
            name="inner",
            inputs=[AudioInput(id="sig")],
            outputs=[AudioOutput(id="y", source="lpf")],
            nodes=[OnePole(id="lpf", a="sig", coeff=0.5)],
        )
        with pytest.raises(ValueError, match="collides with parent input"):
            expand_subgraphs(
                Graph(
                    name="t",
                    inputs=[AudioInput(id="my__lpf")],
                    outputs=[AudioOutput(id="o", source="my")],
                    nodes=[Subgraph(id="my", graph=inner, inputs={"sig": "my__lpf"})],
                )
            )

    def test_no_collision_normal_case(self) -> None:
        """Normal expansion should not trigger collision errors."""
        inner = Graph(
            name="inner",
            inputs=[AudioInput(id="sig")],
            outputs=[AudioOutput(id="y", source="lpf")],
            nodes=[OnePole(id="lpf", a="sig", coeff=0.5)],
        )
        graph = Graph(
            name="t",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="o", source="sub")],
            params=[Param(name="gain", default=1.0)],
            nodes=[Subgraph(id="sub", graph=inner, inputs={"sig": "in1"})],
        )
        expanded = expand_subgraphs(graph)
        assert "sub__lpf" in {n.id for n in expanded.nodes}
