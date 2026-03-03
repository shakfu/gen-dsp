"""Tests for Graph -> .gdsp serialization (graph_to_gdsp)."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")

from gen_dsp.graph.dsl import parse
from gen_dsp.graph.models import (
    AudioInput,
    AudioOutput,
    BinOp,
    Constant,
    Graph,
    History,
    NamedConstant,
    Param,
    Phasor,
)
from gen_dsp.graph.serialize import graph_to_gdsp


class TestGraphToGdsp:
    def test_phasor_roundtrip(self):
        g = Graph(
            name="phasor_test",
            inputs=[],
            outputs=[AudioOutput(id="out1", source="ph")],
            params=[Param(name="freq", min=1.0, max=20000.0, default=440.0)],
            nodes=[Phasor(id="ph", freq="freq")],
        )
        source = graph_to_gdsp(g)
        g2 = parse(source)
        assert g2.name == "phasor_test"
        phasor_nodes = [n for n in g2.nodes if n.op == "phasor"]
        assert len(phasor_nodes) == 1
        assert len(g2.outputs) == 1

    def test_stereo_gain_infix_ops(self):
        g = Graph(
            name="stereo_gain",
            inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
            outputs=[
                AudioOutput(id="out1", source="scaled1"),
                AudioOutput(id="out2", source="scaled2"),
            ],
            params=[Param(name="gain", min=0.0, max=2.0, default=1.0)],
            nodes=[
                BinOp(id="scaled1", op="mul", a="in1", b="gain"),
                BinOp(id="scaled2", op="mul", a="in2", b="gain"),
            ],
        )
        source = graph_to_gdsp(g)
        assert "*" in source
        g2 = parse(source)
        assert g2.name == "stereo_gain"
        assert len(g2.inputs) == 2
        assert len(g2.outputs) == 2
        mul_nodes = [n for n in g2.nodes if n.op == "mul"]
        assert len(mul_nodes) == 2

    def test_history_feedback(self):
        g = Graph(
            name="onepole_test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="result")],
            params=[Param(name="coeff", min=0.0, max=0.999, default=0.5)],
            nodes=[
                BinOp(id="inv_coeff", op="sub", a=1.0, b="coeff"),
                BinOp(id="dry", op="mul", a="in1", b="inv_coeff"),
                History(id="prev", init=0.0, input="result"),
                BinOp(id="wet", op="mul", a="prev", b="coeff"),
                BinOp(id="result", op="add", a="dry", b="wet"),
            ],
        )
        source = graph_to_gdsp(g)
        assert "history prev" in source
        assert "prev <- result" in source
        g2 = parse(source)
        assert g2.name == "onepole_test"
        hist = [n for n in g2.nodes if n.op == "history"]
        assert len(hist) == 1
        assert hist[0].input == "result"

    def test_constants_inlined(self):
        g = Graph(
            name="const_test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="scaled")],
            params=[],
            nodes=[
                Constant(id="c1", value=3.14),
                BinOp(id="scaled", op="mul", a="in1", b="c1"),
            ],
        )
        source = graph_to_gdsp(g)
        assert "c1 =" not in source
        assert "3.14" in source
        g2 = parse(source)
        assert g2.name == "const_test"

    def test_named_constants(self):
        g = Graph(
            name="named_const_test",
            inputs=[],
            outputs=[AudioOutput(id="out1", source="result")],
            params=[],
            nodes=[
                NamedConstant(id="my_pi", op="pi"),
                BinOp(id="result", op="mul", a="my_pi", b=2.0),
            ],
        )
        source = graph_to_gdsp(g)
        assert "my_pi = pi" in source
        g2 = parse(source)
        assert any(n.op == "pi" for n in g2.nodes)

    def test_param_declaration(self):
        g = Graph(
            name="param_test",
            inputs=[],
            outputs=[AudioOutput(id="out1", source="gain")],
            params=[Param(name="gain", min=0.0, max=2.0, default=1.0)],
            nodes=[],
        )
        source = graph_to_gdsp(g)
        assert "param gain 0..2 = 1" in source
        g2 = parse(source)
        p = g2.params[0]
        assert p.name == "gain"
        assert p.min == 0.0
        assert p.max == 2.0
        assert p.default == 1.0

    def test_sample_rate_option(self):
        g = Graph(
            name="sr_test",
            sample_rate=48000,
            inputs=[],
            outputs=[AudioOutput(id="out1", source="ph")],
            params=[Param(name="freq", min=1.0, max=20000.0, default=440.0)],
            nodes=[Phasor(id="ph", freq="freq")],
        )
        source = graph_to_gdsp(g)
        assert "sr=48000" in source
        g2 = parse(source)
        assert g2.sample_rate == 48000.0

    def test_control_interval_option(self):
        from gen_dsp.graph.models import SmoothParam

        g = Graph(
            name="ctrl_test",
            control_interval=64,
            control_nodes=["sf"],
            inputs=[],
            outputs=[AudioOutput(id="out1", source="sf")],
            params=[Param(name="freq", min=20.0, max=20000.0, default=440.0)],
            nodes=[SmoothParam(id="sf", a="freq", coeff=0.999)],
        )
        source = graph_to_gdsp(g)
        assert "control=64" in source
        assert "@control sf" in source

    def test_delay_line_roundtrip(self):
        """Delay declarations and delay_read/delay_write serialize correctly."""
        source = graph_to_gdsp(
            parse("""
            graph dly_test {
                in input
                out output = tap
                delay dl 48000
                delay_write dl (input)
                tap = delay_read dl (1000)
            }
            """)
        )
        assert "delay dl 48000" in source
        assert "delay_write dl" in source
        assert "delay_read dl" in source
        g2 = parse(source)
        assert g2.name == "dly_test"

    def test_buffer_roundtrip(self):
        """Buffer declarations and buf_read serialize correctly."""
        source = graph_to_gdsp(
            parse("""
            graph buf_test {
                out output = val
                param freq 1..20000 = 440
                buffer wt 1024
                phase = phasor(freq)
                idx = phase * buf_size(wt)
                val = buf_read(wt, idx, interp=linear)
            }
            """)
        )
        assert "buffer wt 1024" in source
        assert "buf_read(wt" in source
        assert "interp=linear" in source
        g2 = parse(source)
        assert g2.name == "buf_test"
