from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
import json

import pytest
from pydantic import ValidationError

from gen_dsp.graph import (
    ADSR,
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
    SmoothParam,
    Smoothstep,
    Splat,
    Subgraph,
    TriOsc,
    UnaryOp,
    Wave,
    Wrap,
)

# ---------------------------------------------------------------------------
# Node construction
# ---------------------------------------------------------------------------


class TestNodeConstruction:
    def test_binop(self) -> None:
        n = BinOp(id="x", op="add", a="in1", b=0.5)
        assert n.id == "x"
        assert n.op == "add"
        assert n.a == "in1"
        assert n.b == 0.5

    def test_binop_min(self) -> None:
        n = BinOp(id="x", op="min", a="in1", b=0.5)
        assert n.op == "min"

    def test_binop_max(self) -> None:
        n = BinOp(id="x", op="max", a="in1", b=0.5)
        assert n.op == "max"

    def test_binop_mod(self) -> None:
        n = BinOp(id="x", op="mod", a="in1", b=2.0)
        assert n.op == "mod"

    def test_binop_pow(self) -> None:
        n = BinOp(id="x", op="pow", a="in1", b=2.0)
        assert n.op == "pow"

    def test_unaryop(self) -> None:
        n = UnaryOp(id="x", op="sin", a="in1")
        assert n.op == "sin"

    def test_unaryop_neg(self) -> None:
        n = UnaryOp(id="x", op="neg", a="in1")
        assert n.op == "neg"

    def test_unaryop_floor(self) -> None:
        n = UnaryOp(id="x", op="floor", a="in1")
        assert n.op == "floor"

    def test_unaryop_ceil(self) -> None:
        n = UnaryOp(id="x", op="ceil", a="in1")
        assert n.op == "ceil"

    def test_unaryop_round(self) -> None:
        n = UnaryOp(id="x", op="round", a="in1")
        assert n.op == "round"

    def test_unaryop_sign(self) -> None:
        n = UnaryOp(id="x", op="sign", a="in1")
        assert n.op == "sign"

    def test_clamp_defaults(self) -> None:
        n = Clamp(id="x", a="in1")
        assert n.lo == 0.0
        assert n.hi == 1.0

    def test_constant(self) -> None:
        n = Constant(id="pi", value=3.14159)
        assert n.op == "constant"
        assert n.value == pytest.approx(3.14159)

    def test_history(self) -> None:
        n = History(id="h", input="result", init=0.0)
        assert n.op == "history"
        assert n.input == "result"

    def test_delay_line(self) -> None:
        n = DelayLine(id="dl", max_samples=96000)
        assert n.max_samples == 96000

    def test_delay_read(self) -> None:
        n = DelayRead(id="dr", delay="dl", tap=100.0)
        assert n.delay == "dl"
        assert n.tap == 100.0
        assert n.interp == "none"

    def test_delay_read_interp(self) -> None:
        n = DelayRead(id="dr", delay="dl", tap=100.0, interp="linear")
        assert n.interp == "linear"
        n2 = DelayRead(id="dr2", delay="dl", tap=100.0, interp="cubic")
        assert n2.interp == "cubic"

    def test_delay_write(self) -> None:
        n = DelayWrite(id="dw", delay="dl", value="input_node")
        assert n.value == "input_node"

    def test_phasor(self) -> None:
        n = Phasor(id="p", freq=440.0)
        assert n.freq == 440.0

    def test_noise(self) -> None:
        n = Noise(id="n")
        assert n.op == "noise"

    def test_compare(self) -> None:
        n = Compare(id="c", op="gt", a="in1", b=0.5)
        assert n.op == "gt"
        assert n.a == "in1"
        assert n.b == 0.5

    def test_compare_all_ops(self) -> None:
        for op in ("gt", "lt", "gte", "lte", "eq"):
            n = Compare(id="c", op=op, a="x", b="y")
            assert n.op == op

    def test_select(self) -> None:
        n = Select(id="s", cond="c", a="x", b="y")
        assert n.op == "select"
        assert n.cond == "c"
        assert n.a == "x"
        assert n.b == "y"

    def test_wrap_defaults(self) -> None:
        n = Wrap(id="w", a="in1")
        assert n.op == "wrap"
        assert n.lo == 0.0
        assert n.hi == 1.0

    def test_wrap_custom(self) -> None:
        n = Wrap(id="w", a="in1", lo=-1.0, hi=1.0)
        assert n.lo == -1.0
        assert n.hi == 1.0

    def test_fold_defaults(self) -> None:
        n = Fold(id="f", a="in1")
        assert n.op == "fold"
        assert n.lo == 0.0
        assert n.hi == 1.0

    def test_mix(self) -> None:
        n = Mix(id="m", a="x", b="y", t=0.5)
        assert n.op == "mix"
        assert n.t == 0.5

    def test_delta(self) -> None:
        n = Delta(id="d", a="in1")
        assert n.op == "delta"
        assert n.a == "in1"

    def test_change(self) -> None:
        n = Change(id="c", a="in1")
        assert n.op == "change"
        assert n.a == "in1"

    def test_unaryop_atan(self) -> None:
        n = UnaryOp(id="x", op="atan", a="in1")
        assert n.op == "atan"

    def test_unaryop_asin(self) -> None:
        n = UnaryOp(id="x", op="asin", a="in1")
        assert n.op == "asin"

    def test_unaryop_acos(self) -> None:
        n = UnaryOp(id="x", op="acos", a="in1")
        assert n.op == "acos"

    def test_biquad(self) -> None:
        n = Biquad(id="bq", a="in1", b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0)
        assert n.op == "biquad"
        assert n.b0 == 1.0

    def test_svf(self) -> None:
        n = SVF(id="f", a="in1", freq=1000.0, q=0.707, mode="lp")
        assert n.op == "svf"
        assert n.mode == "lp"

    def test_onepole_node(self) -> None:
        n = OnePole(id="op", a="in1", coeff=0.5)
        assert n.op == "onepole"
        assert n.coeff == 0.5

    def test_dcblock(self) -> None:
        n = DCBlock(id="dc", a="in1")
        assert n.op == "dcblock"

    def test_allpass(self) -> None:
        n = Allpass(id="ap", a="in1", coeff=0.5)
        assert n.op == "allpass"

    def test_sinosc(self) -> None:
        n = SinOsc(id="s", freq=440.0)
        assert n.op == "sinosc"

    def test_triosc(self) -> None:
        n = TriOsc(id="t", freq=440.0)
        assert n.op == "triosc"

    def test_sawosc(self) -> None:
        n = SawOsc(id="s", freq=440.0)
        assert n.op == "sawosc"

    def test_pulseosc(self) -> None:
        n = PulseOsc(id="p", freq=440.0, width=0.5)
        assert n.op == "pulseosc"
        assert n.width == 0.5

    def test_sample_hold(self) -> None:
        n = SampleHold(id="sh", a="in1", trig="t")
        assert n.op == "sample_hold"

    def test_latch(self) -> None:
        n = Latch(id="l", a="in1", trig="t")
        assert n.op == "latch"

    def test_accum(self) -> None:
        n = Accum(id="ac", incr=1.0, reset=0.0)
        assert n.op == "accum"

    def test_counter(self) -> None:
        n = Counter(id="ct", trig="t", max=16.0)
        assert n.op == "counter"
        assert n.max == 16.0

    def test_buffer(self) -> None:
        n = Buffer(id="buf", size=1024)
        assert n.op == "buffer"
        assert n.size == 1024

    def test_buffer_default_size(self) -> None:
        n = Buffer(id="buf")
        assert n.size == 48000

    def test_buffer_fill_default(self) -> None:
        n = Buffer(id="buf", size=512)
        assert n.fill == "zeros"

    def test_buffer_fill_sine(self) -> None:
        n = Buffer(id="buf", size=512, fill="sine")
        assert n.fill == "sine"
        d = n.model_dump()
        assert d["fill"] == "sine"
        restored = Buffer.model_validate(d)
        assert restored.fill == "sine"

    def test_bufread(self) -> None:
        n = BufRead(id="br", buffer="buf", index=0.0)
        assert n.op == "buf_read"
        assert n.buffer == "buf"
        assert n.index == 0.0
        assert n.interp == "none"

    def test_bufread_interp(self) -> None:
        n = BufRead(id="br", buffer="buf", index=0.0, interp="linear")
        assert n.interp == "linear"
        n2 = BufRead(id="br2", buffer="buf", index=0.0, interp="cubic")
        assert n2.interp == "cubic"

    def test_bufwrite(self) -> None:
        n = BufWrite(id="bw", buffer="buf", index=0.0, value=1.0)
        assert n.op == "buf_write"
        assert n.buffer == "buf"
        assert n.value == 1.0

    def test_bufsize(self) -> None:
        n = BufSize(id="bs", buffer="buf")
        assert n.op == "buf_size"
        assert n.buffer == "buf"

    def test_rate_div(self) -> None:
        n = RateDiv(id="rd", a="in1", divisor=4.0)
        assert n.op == "rate_div"
        assert n.a == "in1"
        assert n.divisor == 4.0

    def test_scale(self) -> None:
        n = Scale(id="sc", a="in1")
        assert n.op == "scale"
        assert n.in_lo == 0.0
        assert n.in_hi == 1.0
        assert n.out_lo == 0.0
        assert n.out_hi == 1.0

    def test_scale_custom(self) -> None:
        n = Scale(id="sc", a="in1", in_lo=-1.0, in_hi=1.0, out_lo=0.0, out_hi=10.0)
        assert n.in_lo == -1.0
        assert n.in_hi == 1.0
        assert n.out_lo == 0.0
        assert n.out_hi == 10.0

    def test_smooth_param(self) -> None:
        n = SmoothParam(id="sp", a="in1", coeff=0.99)
        assert n.op == "smooth"
        assert n.a == "in1"
        assert n.coeff == 0.99

    def test_peek(self) -> None:
        n = Peek(id="pk", a="in1")
        assert n.op == "peek"
        assert n.a == "in1"

    def test_subgraph(self) -> None:
        inner = Graph(
            name="inner",
            inputs=[AudioInput(id="x")],
            outputs=[AudioOutput(id="y", source="pass_node")],
            nodes=[BinOp(id="pass_node", op="mul", a="x", b=1.0)],
        )
        n = Subgraph(id="sg", graph=inner, inputs={"x": "in1"})
        assert n.op == "subgraph"
        assert n.graph.name == "inner"
        assert n.inputs == {"x": "in1"}
        assert n.params == {}
        assert n.output == ""


# ---------------------------------------------------------------------------
# Param defaults
# ---------------------------------------------------------------------------


class TestParamDefaults:
    def test_defaults(self) -> None:
        p = Param(name="gain")
        assert p.min == 0.0
        assert p.max == 1.0
        assert p.default == 0.0

    def test_custom_range(self) -> None:
        p = Param(name="freq", min=20.0, max=20000.0, default=440.0)
        assert p.min == 20.0
        assert p.max == 20000.0
        assert p.default == 440.0


# ---------------------------------------------------------------------------
# JSON round-trips
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    def test_graph_json_roundtrip(self, stereo_gain_graph: Graph) -> None:
        json_str = stereo_gain_graph.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == stereo_gain_graph

    def test_graph_dict_roundtrip(self, stereo_gain_graph: Graph) -> None:
        d = stereo_gain_graph.model_dump()
        restored = Graph.model_validate(d)
        assert restored == stereo_gain_graph

    def test_onepole_json_roundtrip(self, onepole_graph: Graph) -> None:
        json_str = onepole_graph.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == onepole_graph

    def test_fbdelay_json_roundtrip(self, fbdelay_graph: Graph) -> None:
        json_str = fbdelay_graph.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == fbdelay_graph

    def test_json_indent(self, stereo_gain_graph: Graph) -> None:
        json_str = stereo_gain_graph.model_dump_json(indent=2)
        parsed = json.loads(json_str)
        assert parsed["name"] == "stereo_gain"
        assert len(parsed["nodes"]) == 2

    def test_new_nodes_json_roundtrip(self) -> None:
        g = Graph(
            name="new_types",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="mx")],
            nodes=[
                Compare(id="cmp", op="gt", a="in1", b=0.0),
                Select(id="sel", cond="cmp", a="in1", b=0.0),
                Wrap(id="wr", a="sel"),
                Fold(id="fo", a="wr"),
                Mix(id="mx", a="fo", b="in1", t=0.5),
                Delta(id="dt", a="in1"),
                Change(id="ch", a="in1"),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g

    def test_v03_nodes_json_roundtrip(self) -> None:
        g = Graph(
            name="v03_types",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="ac")],
            nodes=[
                Biquad(id="bq", a="in1", b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0),
                SVF(id="svf", a="in1", freq=1000.0, q=0.707, mode="lp"),
                OnePole(id="op", a="in1", coeff=0.5),
                DCBlock(id="dc", a="in1"),
                Allpass(id="ap", a="in1", coeff=0.5),
                SinOsc(id="so", freq=440.0),
                TriOsc(id="to", freq=440.0),
                SawOsc(id="sw", freq=440.0),
                PulseOsc(id="po", freq=440.0, width=0.5),
                SampleHold(id="sh", a="in1", trig=0.0),
                Latch(id="la", a="in1", trig=0.0),
                Accum(id="ac", incr=1.0, reset=0.0),
                Counter(id="ct", trig=0.0, max=16.0),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g

    def test_v04_nodes_json_roundtrip(self) -> None:
        g = Graph(
            name="v04_types",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=1024),
                BufRead(id="br", buffer="buf", index=0.0, interp="linear"),
                BufWrite(id="bw", buffer="buf", index=0.0, value=0.0),
                BufSize(id="bs", buffer="buf"),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g

    def test_v06_nodes_json_roundtrip(self) -> None:
        g = Graph(
            name="v06_types",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="pk")],
            nodes=[
                RateDiv(id="rd", a="in1", divisor=4.0),
                Scale(id="sc", a="in1", in_lo=-1.0, in_hi=1.0, out_lo=0.0, out_hi=10.0),
                SmoothParam(id="sp", a="in1", coeff=0.99),
                Peek(id="pk", a="in1"),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g

    def test_subgraph_json_roundtrip(self) -> None:
        inner = Graph(
            name="inner",
            inputs=[AudioInput(id="x")],
            outputs=[AudioOutput(id="y", source="n")],
            params=[Param(name="g", default=0.5)],
            nodes=[BinOp(id="n", op="mul", a="x", b="g")],
        )
        g = Graph(
            name="sg_test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sg")],
            nodes=[
                Subgraph(
                    id="sg",
                    graph=inner,
                    inputs={"x": "in1"},
                    params={"g": 0.8},
                    output="y",
                ),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g
        sg_node = restored.nodes[0]
        assert isinstance(sg_node, Subgraph)
        assert sg_node.graph.name == "inner"
        assert sg_node.inputs == {"x": "in1"}
        assert sg_node.params == {"g": 0.8}
        assert sg_node.output == "y"

    def test_delay_read_interp_roundtrip(self) -> None:
        g = Graph(
            name="interp_test",
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[
                DelayLine(id="dl"),
                DelayRead(id="rd", delay="dl", tap=100.0, interp="cubic"),
                DelayWrite(id="dw", delay="dl", value=0.0),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g
        rd = restored.nodes[1]
        assert isinstance(rd, DelayRead)
        assert rd.interp == "cubic"


# ---------------------------------------------------------------------------
# Discriminated union deserialization
# ---------------------------------------------------------------------------


class TestDiscriminatedUnion:
    def test_mixed_node_types_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {"id": "a", "op": "add", "a": 1.0, "b": 2.0},
                {"id": "s", "op": "sin", "a": "a"},
                {"id": "n", "op": "noise"},
                {"id": "c", "op": "constant", "value": 42.0},
                {"id": "p", "op": "phasor", "freq": 440.0},
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], BinOp)
        assert isinstance(g.nodes[1], UnaryOp)
        assert isinstance(g.nodes[2], Noise)
        assert isinstance(g.nodes[3], Constant)
        assert isinstance(g.nodes[4], Phasor)

    def test_new_ops_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {"id": "cmp", "op": "gt", "a": 1.0, "b": 0.0},
                {"id": "sel", "op": "select", "cond": "cmp", "a": 1.0, "b": 0.0},
                {"id": "wr", "op": "wrap", "a": 1.5},
                {"id": "fo", "op": "fold", "a": 1.5},
                {"id": "mx", "op": "mix", "a": 0.0, "b": 1.0, "t": 0.5},
                {"id": "dt", "op": "delta", "a": 0.0},
                {"id": "ch", "op": "change", "a": 0.0},
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], Compare)
        assert isinstance(g.nodes[1], Select)
        assert isinstance(g.nodes[2], Wrap)
        assert isinstance(g.nodes[3], Fold)
        assert isinstance(g.nodes[4], Mix)
        assert isinstance(g.nodes[5], Delta)
        assert isinstance(g.nodes[6], Change)

    def test_v03_ops_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {
                    "id": "bq",
                    "op": "biquad",
                    "a": 0.0,
                    "b0": 1.0,
                    "b1": 0.0,
                    "b2": 0.0,
                    "a1": 0.0,
                    "a2": 0.0,
                },
                {
                    "id": "svf",
                    "op": "svf",
                    "a": 0.0,
                    "freq": 1000.0,
                    "q": 0.707,
                    "mode": "lp",
                },
                {"id": "op", "op": "onepole", "a": 0.0, "coeff": 0.5},
                {"id": "dc", "op": "dcblock", "a": 0.0},
                {"id": "ap", "op": "allpass", "a": 0.0, "coeff": 0.5},
                {"id": "so", "op": "sinosc", "freq": 440.0},
                {"id": "to", "op": "triosc", "freq": 440.0},
                {"id": "sw", "op": "sawosc", "freq": 440.0},
                {"id": "po", "op": "pulseosc", "freq": 440.0, "width": 0.5},
                {"id": "sh", "op": "sample_hold", "a": 0.0, "trig": 0.0},
                {"id": "la", "op": "latch", "a": 0.0, "trig": 0.0},
                {"id": "ac", "op": "accum", "incr": 1.0, "reset": 0.0},
                {"id": "ct", "op": "counter", "trig": 0.0, "max": 16.0},
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], Biquad)
        assert isinstance(g.nodes[1], SVF)
        assert isinstance(g.nodes[2], OnePole)
        assert isinstance(g.nodes[3], DCBlock)
        assert isinstance(g.nodes[4], Allpass)
        assert isinstance(g.nodes[5], SinOsc)
        assert isinstance(g.nodes[6], TriOsc)
        assert isinstance(g.nodes[7], SawOsc)
        assert isinstance(g.nodes[8], PulseOsc)
        assert isinstance(g.nodes[9], SampleHold)
        assert isinstance(g.nodes[10], Latch)
        assert isinstance(g.nodes[11], Accum)
        assert isinstance(g.nodes[12], Counter)

    def test_v04_ops_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {"id": "buf", "op": "buffer", "size": 1024},
                {"id": "br", "op": "buf_read", "buffer": "buf", "index": 0.0},
                {
                    "id": "bw",
                    "op": "buf_write",
                    "buffer": "buf",
                    "index": 0.0,
                    "value": 0.0,
                },
                {"id": "bs", "op": "buf_size", "buffer": "buf"},
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], Buffer)
        assert isinstance(g.nodes[1], BufRead)
        assert isinstance(g.nodes[2], BufWrite)
        assert isinstance(g.nodes[3], BufSize)

    def test_v06_ops_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {"id": "rd", "op": "rate_div", "a": 0.0, "divisor": 4.0},
                {"id": "sc", "op": "scale", "a": 0.0},
                {"id": "sp", "op": "smooth", "a": 0.0, "coeff": 0.99},
                {"id": "pk", "op": "peek", "a": 0.0},
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], RateDiv)
        assert isinstance(g.nodes[1], Scale)
        assert isinstance(g.nodes[2], SmoothParam)
        assert isinstance(g.nodes[3], Peek)

    def test_invalid_op_rejected(self) -> None:
        raw = {
            "name": "test",
            "nodes": [{"id": "bad", "op": "nonexistent", "a": 1.0}],
        }
        with pytest.raises(ValidationError):
            Graph.model_validate(raw)


# ---------------------------------------------------------------------------
# Graph structure
# ---------------------------------------------------------------------------


class TestGraphStructure:
    def test_empty_graph(self) -> None:
        g = Graph(name="empty")
        assert g.nodes == []
        assert g.inputs == []
        assert g.outputs == []
        assert g.params == []
        assert g.sample_rate == 44100.0

    def test_graph_with_all_node_types(self) -> None:
        g = Graph(
            name="all_types",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="clamped")],
            nodes=[
                BinOp(id="sum", op="add", a="in1", b=1.0),
                UnaryOp(id="sine", op="sin", a="sum"),
                Clamp(id="clamped", a="sine"),
                Constant(id="k", value=2.0),
                History(id="h", input="clamped"),
                DelayLine(id="dl"),
                DelayRead(id="dr", delay="dl", tap=100.0),
                DelayWrite(id="dw", delay="dl", value="in1"),
                Phasor(id="p", freq=440.0),
                Noise(id="n"),
                Compare(id="cmp", op="gt", a="in1", b=0.0),
                Select(id="sel", cond="cmp", a="in1", b=0.0),
                Wrap(id="wr", a="in1"),
                Fold(id="fo", a="in1"),
                Mix(id="mx", a="in1", b=0.0, t=0.5),
                Delta(id="dt", a="in1"),
                Change(id="ch", a="in1"),
                Biquad(id="bq", a="in1", b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0),
                SVF(id="svf", a="in1", freq=1000.0, q=0.707, mode="lp"),
                OnePole(id="op", a="in1", coeff=0.5),
                DCBlock(id="dc", a="in1"),
                Allpass(id="ap", a="in1", coeff=0.5),
                SinOsc(id="so", freq=440.0),
                TriOsc(id="to", freq=440.0),
                SawOsc(id="sw", freq=440.0),
                PulseOsc(id="po", freq=440.0, width=0.5),
                SampleHold(id="sh", a="in1", trig=0.0),
                Latch(id="la", a="in1", trig=0.0),
                Accum(id="ac", incr=1.0, reset=0.0),
                Counter(id="ct", trig=0.0, max=16.0),
                Buffer(id="buf", size=1024),
                BufRead(id="br", buffer="buf", index=0.0),
                BufWrite(id="bw", buffer="buf", index=0.0, value=0.0),
                BufSize(id="bs", buffer="buf"),
                RateDiv(id="rd", a="in1", divisor=4.0),
                Scale(id="sc", a="in1"),
                SmoothParam(id="sp", a="in1", coeff=0.99),
                Peek(id="pk", a="in1"),
                Pass(id="ps", a="in1"),
                NamedConstant(id="nc", op="pi"),
                Smoothstep(id="ss", a="in1", edge0=0.0, edge1=1.0),
                Subgraph(
                    id="sg",
                    graph=Graph(
                        name="inner",
                        inputs=[AudioInput(id="x")],
                        outputs=[AudioOutput(id="y", source="pass")],
                        nodes=[BinOp(id="pass", op="mul", a="x", b=1.0)],
                    ),
                    inputs={"x": "in1"},
                ),
                GateRoute(id="gr", a="in1", index=1.0, count=3),
                GateOut(id="go1", gate="gr", channel=1),
                Selector(id="mux", index=1.0, inputs=["in1", 0.0]),
                Slide(id="sl", a="in1", up=10.0, down=20.0),
                SampleRate(id="srn"),
                Elapsed(id="el"),
                MulAccum(id="ma", incr=1.0, reset=0.0),
                Cycle(id="cy", buffer="buf", phase=0.0),
                Wave(id="wv", buffer="buf", phase=0.0),
                Lookup(id="lu", buffer="buf", index=0.5),
                Splat(id="sp2", buffer="buf", index=0.0, value=0.0),
                ADSR(
                    id="adsr1",
                    gate="in1",
                    attack=10.0,
                    decay=100.0,
                    sustain=0.7,
                    release=200.0,
                ),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert len(restored.nodes) == 54


# ---------------------------------------------------------------------------
# New ops and node types (v0.2)
# ---------------------------------------------------------------------------


class TestNewOps:
    """Construction tests for new UnaryOp, BinOp, Compare ops and new node types."""

    @pytest.mark.parametrize(
        "op",
        [
            "tan",
            "sinh",
            "cosh",
            "asinh",
            "acosh",
            "atanh",
            "exp2",
            "log2",
            "log10",
            "fract",
            "trunc",
            "not",
            "bool",
        ],
    )
    def test_new_unary_ops(self, op: str) -> None:
        n = UnaryOp(id="x", op=op, a="in1")
        assert n.op == op

    @pytest.mark.parametrize(
        "op", ["atan2", "hypot", "absdiff", "step", "and", "or", "xor"]
    )
    def test_new_binop_ops(self, op: str) -> None:
        n = BinOp(id="x", op=op, a="in1", b="in2")
        assert n.op == op

    def test_compare_neq(self) -> None:
        n = Compare(id="c", op="neq", a="x", b="y")
        assert n.op == "neq"

    def test_pass_node(self) -> None:
        n = Pass(id="p", a="in1")
        assert n.op == "pass"
        assert n.a == "in1"

    def test_named_constant(self) -> None:
        n = NamedConstant(id="pi_val", op="pi")
        assert n.op == "pi"

    @pytest.mark.parametrize(
        "op",
        [
            "pi",
            "e",
            "twopi",
            "halfpi",
            "invpi",
            "degtorad",
            "radtodeg",
            "sqrt2",
            "sqrt1_2",
            "ln2",
            "ln10",
            "log2e",
            "log10e",
            "phi",
        ],
    )
    def test_named_constant_all_ops(self, op: str) -> None:
        n = NamedConstant(id="k", op=op)
        assert n.op == op

    def test_smoothstep(self) -> None:
        n = Smoothstep(id="ss", a="in1", edge0=0.0, edge1=1.0)
        assert n.op == "smoothstep"
        assert n.edge0 == 0.0
        assert n.edge1 == 1.0

    def test_new_nodes_json_roundtrip(self) -> None:
        g = Graph(
            name="new_v2_types",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="ps")],
            nodes=[
                Pass(id="ps", a="in1"),
                NamedConstant(id="pi_val", op="pi"),
                Smoothstep(id="ss", a="in1", edge0=0.0, edge1=1.0),
                BinOp(id="hy", op="hypot", a="in1", b=1.0),
                UnaryOp(id="tn", op="tan", a="in1"),
                Compare(id="neq_c", op="neq", a="in1", b=0.0),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g

    def test_new_ops_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {"id": "ps", "op": "pass", "a": 1.0},
                {"id": "nc", "op": "pi"},
                {"id": "ss", "op": "smoothstep", "a": 0.5, "edge0": 0.0, "edge1": 1.0},
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], Pass)
        assert isinstance(g.nodes[1], NamedConstant)
        assert isinstance(g.nodes[2], Smoothstep)


# ---------------------------------------------------------------------------
# Gate / Selector routing nodes
# ---------------------------------------------------------------------------


class TestRoutingNodes:
    def test_gate_route(self) -> None:
        n = GateRoute(id="gr", a="in1", index=1.0, count=3)
        assert n.op == "gate_route"
        assert n.a == "in1"
        assert n.index == 1.0
        assert n.count == 3

    def test_gate_out(self) -> None:
        n = GateOut(id="go", gate="gr", channel=2)
        assert n.op == "gate_out"
        assert n.gate == "gr"
        assert n.channel == 2

    def test_selector(self) -> None:
        n = Selector(id="sel", index=1.0, inputs=["a", "b", "c"])
        assert n.op == "selector"
        assert n.index == 1.0
        assert n.inputs == ["a", "b", "c"]

    def test_selector_with_literal_inputs(self) -> None:
        n = Selector(id="sel", index=2.0, inputs=["a", 0.5, "c"])
        assert n.inputs == ["a", 0.5, "c"]

    def test_gate_selector_json_roundtrip(self) -> None:
        g = Graph(
            name="routing",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out1", source="go1"),
                AudioOutput(id="out2", source="mux"),
            ],
            nodes=[
                GateRoute(id="gr", a="in1", index=1.0, count=2),
                GateOut(id="go1", gate="gr", channel=1),
                GateOut(id="go2", gate="gr", channel=2),
                Selector(id="mux", index=1.0, inputs=["go1", "go2"]),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g

    def test_gate_selector_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {"id": "gr", "op": "gate_route", "a": 1.0, "index": 1.0, "count": 3},
                {"id": "go", "op": "gate_out", "gate": "gr", "channel": 1},
                {"id": "sel", "op": "selector", "index": 1.0, "inputs": [1.0, 2.0]},
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], GateRoute)
        assert isinstance(g.nodes[1], GateOut)
        assert isinstance(g.nodes[2], Selector)


# ---------------------------------------------------------------------------
# Slide, SampleRate, convert ops
# ---------------------------------------------------------------------------


class TestSlideAndSampleRate:
    def test_slide_construction(self) -> None:
        n = Slide(id="sl", a="in1", up=10.0, down=20.0)
        assert n.op == "slide"
        assert n.a == "in1"
        assert n.up == 10.0
        assert n.down == 20.0

    def test_samplerate_construction(self) -> None:
        n = SampleRate(id="sr_node")
        assert n.op == "samplerate"

    @pytest.mark.parametrize("op", ["mtof", "ftom", "atodb", "dbtoa"])
    def test_convert_unary_ops(self, op: str) -> None:
        n = UnaryOp(id="x", op=op, a="in1")
        assert n.op == op

    def test_slide_samplerate_json_roundtrip(self) -> None:
        g = Graph(
            name="slide_sr",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sl")],
            nodes=[
                SampleRate(id="sr_node"),
                Slide(id="sl", a="in1", up=10.0, down=20.0),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g

    def test_slide_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {"id": "sl", "op": "slide", "a": 1.0, "up": 10.0, "down": 20.0},
                {"id": "sr", "op": "samplerate"},
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], Slide)
        assert isinstance(g.nodes[1], SampleRate)


# ---------------------------------------------------------------------------
# Elapsed, MulAccum, phasewrap, Buffer variants
# ---------------------------------------------------------------------------


class TestBatch2Ops:
    def test_elapsed_construction(self) -> None:
        n = Elapsed(id="el")
        assert n.op == "elapsed"

    def test_mulaccum_construction(self) -> None:
        n = MulAccum(id="ma", incr=2.0, reset=0.0)
        assert n.op == "mulaccum"
        assert n.incr == 2.0
        assert n.reset == 0.0

    def test_phasewrap_unary(self) -> None:
        n = UnaryOp(id="pw", op="phasewrap", a="in1")
        assert n.op == "phasewrap"

    def test_cycle_construction(self) -> None:
        n = Cycle(id="cy", buffer="buf", phase=0.5)
        assert n.op == "cycle"
        assert n.buffer == "buf"
        assert n.phase == 0.5

    def test_wave_construction(self) -> None:
        n = Wave(id="wv", buffer="buf", phase=0.0)
        assert n.op == "wave"
        assert n.buffer == "buf"
        assert n.phase == 0.0

    def test_lookup_construction(self) -> None:
        n = Lookup(id="lu", buffer="buf", index=0.5)
        assert n.op == "lookup"
        assert n.buffer == "buf"
        assert n.index == 0.5

    def test_batch2_json_roundtrip(self) -> None:
        g = Graph(
            name="batch2_types",
            outputs=[AudioOutput(id="out1", source="el")],
            nodes=[
                Buffer(id="buf", size=1024),
                Elapsed(id="el"),
                MulAccum(id="ma", incr=1.0, reset=0.0),
                Cycle(id="cy", buffer="buf", phase=0.0),
                Wave(id="wv", buffer="buf", phase=0.0),
                Lookup(id="lu", buffer="buf", index=0.5),
                UnaryOp(id="pw", op="phasewrap", a=1.0),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g

    def test_batch2_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {"id": "el", "op": "elapsed"},
                {"id": "ma", "op": "mulaccum", "incr": 1.0, "reset": 0.0},
                {"id": "cy", "op": "cycle", "buffer": "buf", "phase": 0.0},
                {"id": "wv", "op": "wave", "buffer": "buf", "phase": 0.0},
                {"id": "lu", "op": "lookup", "buffer": "buf", "index": 0.5},
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], Elapsed)
        assert isinstance(g.nodes[1], MulAccum)
        assert isinstance(g.nodes[2], Cycle)
        assert isinstance(g.nodes[3], Wave)
        assert isinstance(g.nodes[4], Lookup)


# ---------------------------------------------------------------------------
# Batch 3: reverse ops, "p" comparisons, angle/sample convert, DSP safety,
#           fast approx, splat
# ---------------------------------------------------------------------------


class TestBatch3Ops:
    @pytest.mark.parametrize(
        "op",
        [
            "rsub",
            "rdiv",
            "rmod",
            "gtp",
            "ltp",
            "gtep",
            "ltep",
            "eqp",
            "neqp",
            "fastpow",
        ],
    )
    def test_new_binop_ops(self, op: str) -> None:
        n = BinOp(id="x", op=op, a="in1", b="in2")
        assert n.op == op

    @pytest.mark.parametrize(
        "op",
        [
            "degrees",
            "radians",
            "mstosamps",
            "sampstoms",
            "t60",
            "t60time",
            "fixdenorm",
            "fixnan",
            "isdenorm",
            "isnan",
            "fastsin",
            "fastcos",
            "fasttan",
            "fastexp",
        ],
    )
    def test_new_unary_ops(self, op: str) -> None:
        n = UnaryOp(id="x", op=op, a="in1")
        assert n.op == op

    def test_splat_construction(self) -> None:
        n = Splat(id="sp", buffer="buf", index=0.0, value=1.0)
        assert n.op == "splat"
        assert n.buffer == "buf"
        assert n.index == 0.0
        assert n.value == 1.0

    def test_batch3_json_roundtrip(self) -> None:
        g = Graph(
            name="batch3_types",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rsb")],
            nodes=[
                Buffer(id="buf", size=1024),
                BinOp(id="rsb", op="rsub", a="in1", b=1.0),
                BinOp(id="gtp_n", op="gtp", a="in1", b=0.0),
                UnaryOp(id="deg", op="degrees", a="in1"),
                UnaryOp(id="ms2s", op="mstosamps", a="in1"),
                UnaryOp(id="fd", op="fixdenorm", a="in1"),
                UnaryOp(id="fs", op="fastsin", a="in1"),
                Splat(id="sp", buffer="buf", index=0.0, value="in1"),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g

    def test_splat_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {
                    "id": "sp",
                    "op": "splat",
                    "buffer": "buf",
                    "index": 0.0,
                    "value": 1.0,
                },
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], Splat)


# ---------------------------------------------------------------------------
# ADSR envelope node
# ---------------------------------------------------------------------------


class TestADSR:
    def test_adsr_construction(self) -> None:
        n = ADSR(
            id="env", gate="g", attack=10.0, decay=100.0, sustain=0.7, release=200.0
        )
        assert n.op == "adsr"
        assert n.gate == "g"
        assert n.attack == 10.0
        assert n.decay == 100.0
        assert n.sustain == 0.7
        assert n.release == 200.0

    def test_adsr_with_refs(self) -> None:
        n = ADSR(
            id="env",
            gate="gate_param",
            attack="atk",
            decay="dec",
            sustain="sus",
            release="rel",
        )
        assert n.gate == "gate_param"
        assert n.attack == "atk"

    def test_adsr_json_roundtrip(self) -> None:
        g = Graph(
            name="adsr_test",
            outputs=[AudioOutput(id="out1", source="env")],
            params=[Param(name="gate")],
            nodes=[
                ADSR(
                    id="env",
                    gate="gate",
                    attack=10.0,
                    decay=100.0,
                    sustain=0.7,
                    release=200.0,
                ),
            ],
        )
        json_str = g.model_dump_json()
        restored = Graph.model_validate_json(json_str)
        assert restored == g

    def test_adsr_from_json(self) -> None:
        raw = {
            "name": "test",
            "nodes": [
                {
                    "id": "env",
                    "op": "adsr",
                    "gate": 1.0,
                    "attack": 10.0,
                    "decay": 100.0,
                    "sustain": 0.7,
                    "release": 200.0,
                },
            ],
        }
        g = Graph.model_validate(raw)
        assert isinstance(g.nodes[0], ADSR)
        assert g.nodes[0].sustain == 0.7
