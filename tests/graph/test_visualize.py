from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
import shutil
from unittest.mock import patch

import pytest

from gen_dsp.graph import (
    SVF,
    Accum,
    Allpass,
    AudioInput,
    AudioOutput,
    Biquad,
    Buffer,
    BufRead,
    BufSize,
    BufWrite,
    Change,
    Compare,
    Constant,
    Counter,
    DCBlock,
    Delta,
    Fold,
    Graph,
    Latch,
    Mix,
    OnePole,
    Peek,
    PulseOsc,
    RateDiv,
    SampleHold,
    SawOsc,
    Scale,
    Select,
    SinOsc,
    SmoothParam,
    TriOsc,
    Wrap,
    graph_to_dot,
    graph_to_dot_file,
)


class TestGraphToDot:
    def test_header(self, stereo_gain_graph: Graph) -> None:
        dot = graph_to_dot(stereo_gain_graph)
        assert 'digraph "stereo_gain"' in dot
        assert "rankdir=LR" in dot
        assert "fontname" in dot

    def test_input_nodes(self, stereo_gain_graph: Graph) -> None:
        dot = graph_to_dot(stereo_gain_graph)
        assert '"in1"' in dot
        assert '"in2"' in dot
        assert "#d4edda" in dot  # green fill
        assert "rounded" in dot

    def test_output_nodes(self, stereo_gain_graph: Graph) -> None:
        dot = graph_to_dot(stereo_gain_graph)
        assert '"out1"' in dot
        assert '"out2"' in dot
        assert "#f8d7da" in dot  # red fill

    def test_param_node(self, stereo_gain_graph: Graph) -> None:
        dot = graph_to_dot(stereo_gain_graph)
        assert '"gain"' in dot
        assert "ellipse" in dot
        assert "#cce5ff" in dot  # blue fill
        assert "[0.0, 2.0]" in dot
        assert "default=1.0" in dot

    def test_forward_edges(self, stereo_gain_graph: Graph) -> None:
        dot = graph_to_dot(stereo_gain_graph)
        assert '"in1" -> "scaled1"' in dot
        assert '"gain" -> "scaled1"' in dot
        assert '"in2" -> "scaled2"' in dot
        assert '"gain" -> "scaled2"' in dot

    def test_output_edges(self, stereo_gain_graph: Graph) -> None:
        dot = graph_to_dot(stereo_gain_graph)
        assert '"scaled1" -> "out1"' in dot
        assert '"scaled2" -> "out2"' in dot

    def test_no_dashed_in_stereo_gain(self, stereo_gain_graph: Graph) -> None:
        dot = graph_to_dot(stereo_gain_graph)
        assert "dashed" not in dot

    def test_feedback_edge_dashed(self, onepole_graph: Graph) -> None:
        dot = graph_to_dot(onepole_graph)
        # History.input = "result" is a feedback edge
        assert '"result" -> "prev" [style=dashed label="z^-1"]' in dot

    def test_history_node_label(self, onepole_graph: Graph) -> None:
        dot = graph_to_dot(onepole_graph)
        assert "z^-1" in dot
        assert "#fde0c8" in dot  # orange fill

    def test_binop_label(self, stereo_gain_graph: Graph) -> None:
        dot = graph_to_dot(stereo_gain_graph)
        assert "mul" in dot

    def test_constant_node(self) -> None:
        graph = Graph(
            name="const_test",
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Constant(id="c", value=3.14)],
        )
        dot = graph_to_dot(graph)
        assert "3.14" in dot
        assert "#e9ecef" in dot  # gray fill

    def test_delay_nodes(self, fbdelay_graph: Graph) -> None:
        dot = graph_to_dot(fbdelay_graph)
        assert "delay[48000]" in dot
        assert "box3d" in dot
        assert "read" in dot
        assert "write" in dot

    def test_compare_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Compare(id="c", op="gt", a="in1", b=0.0)],
        )
        dot = graph_to_dot(g)
        assert "diamond" in dot
        assert "#fff3cd" in dot
        assert "gt" in dot

    def test_select_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="s")],
            nodes=[
                Compare(id="c", op="gt", a="in1", b=0.0),
                Select(id="s", cond="c", a="in1", b=0.0),
            ],
        )
        dot = graph_to_dot(g)
        # Select should be diamond
        assert "shape=diamond" in dot

    def test_wrap_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="w")],
            nodes=[Wrap(id="w", a="in1")],
        )
        dot = graph_to_dot(g)
        assert "wrap" in dot
        assert "#fff3cd" in dot

    def test_fold_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="f")],
            nodes=[Fold(id="f", a="in1")],
        )
        dot = graph_to_dot(g)
        assert "fold" in dot
        assert "#fff3cd" in dot

    def test_mix_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="m")],
            nodes=[Mix(id="m", a="in1", b=0.0, t=0.5)],
        )
        dot = graph_to_dot(g)
        assert "mix" in dot
        assert "#fff3cd" in dot

    def test_delta_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="d")],
            nodes=[Delta(id="d", a="in1")],
        )
        dot = graph_to_dot(g)
        assert "delta" in dot
        assert "#fde0c8" in dot  # orange (stateful)

    def test_change_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[Change(id="c", a="in1")],
        )
        dot = graph_to_dot(g)
        assert "change" in dot
        assert "#fde0c8" in dot  # orange (stateful)

    def test_biquad_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="bq")],
            nodes=[Biquad(id="bq", a="in1", b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0)],
        )
        dot = graph_to_dot(g)
        assert "biquad" in dot
        assert "#fde0c8" in dot

    def test_svf_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="f")],
            nodes=[SVF(id="f", a="in1", freq=1000.0, q=0.707, mode="lp")],
        )
        dot = graph_to_dot(g)
        assert "svf(lp)" in dot
        assert "#fde0c8" in dot

    def test_onepole_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="op")],
            nodes=[OnePole(id="op", a="in1", coeff=0.5)],
        )
        dot = graph_to_dot(g)
        assert "onepole" in dot
        assert "#fde0c8" in dot

    def test_dcblock_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="dc")],
            nodes=[DCBlock(id="dc", a="in1")],
        )
        dot = graph_to_dot(g)
        assert "dcblock" in dot
        assert "#fde0c8" in dot

    def test_allpass_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="ap")],
            nodes=[Allpass(id="ap", a="in1", coeff=0.5)],
        )
        dot = graph_to_dot(g)
        assert "allpass" in dot
        assert "#fde0c8" in dot

    def test_sinosc_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="s")],
            nodes=[SinOsc(id="s", freq=440.0)],
        )
        dot = graph_to_dot(g)
        assert "sinosc" in dot
        assert "#e2d5f1" in dot

    def test_triosc_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="t")],
            nodes=[TriOsc(id="t", freq=440.0)],
        )
        dot = graph_to_dot(g)
        assert "triosc" in dot
        assert "#e2d5f1" in dot

    def test_sawosc_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="s")],
            nodes=[SawOsc(id="s", freq=440.0)],
        )
        dot = graph_to_dot(g)
        assert "sawosc" in dot
        assert "#e2d5f1" in dot

    def test_pulseosc_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="p")],
            nodes=[PulseOsc(id="p", freq=440.0, width=0.5)],
        )
        dot = graph_to_dot(g)
        assert "pulseosc" in dot
        assert "#e2d5f1" in dot

    def test_sample_hold_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sh")],
            nodes=[SampleHold(id="sh", a="in1", trig=0.0)],
        )
        dot = graph_to_dot(g)
        assert "sample_hold" in dot
        assert "#fde0c8" in dot

    def test_latch_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="la")],
            nodes=[Latch(id="la", a="in1", trig=0.0)],
        )
        dot = graph_to_dot(g)
        assert "latch" in dot
        assert "#fde0c8" in dot

    def test_accum_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="ac")],
            nodes=[Accum(id="ac", incr=1.0, reset=0.0)],
        )
        dot = graph_to_dot(g)
        assert "accum" in dot
        assert "#fde0c8" in dot

    def test_counter_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="ct")],
            nodes=[Counter(id="ct", trig=0.0, max=16.0)],
        )
        dot = graph_to_dot(g)
        assert "counter" in dot
        assert "#fde0c8" in dot

    def test_buffer_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=1024),
                BufRead(id="br", buffer="buf", index=0.0),
            ],
        )
        dot = graph_to_dot(g)
        assert "buffer[1024]" in dot
        assert "box3d" in dot
        assert "#fde0c8" in dot

    def test_bufread_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=1024),
                BufRead(id="br", buffer="buf", index=0.0),
            ],
        )
        dot = graph_to_dot(g)
        assert "buf_read" in dot
        assert "#fde0c8" in dot

    def test_bufwrite_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=1024),
                BufRead(id="br", buffer="buf", index=0.0),
                BufWrite(id="bw", buffer="buf", index=0.0, value=0.0),
            ],
        )
        dot = graph_to_dot(g)
        assert "buf_write" in dot
        assert "#fde0c8" in dot

    def test_bufsize_node(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="bs")],
            nodes=[
                Buffer(id="buf", size=1024),
                BufSize(id="bs", buffer="buf"),
            ],
        )
        dot = graph_to_dot(g)
        assert "buf_size" in dot
        assert "#fde0c8" in dot

    def test_all_fixtures_valid_dot(
        self,
        stereo_gain_graph: Graph,
        onepole_graph: Graph,
        fbdelay_graph: Graph,
    ) -> None:
        for g in [stereo_gain_graph, onepole_graph, fbdelay_graph]:
            dot = graph_to_dot(g)
            assert dot.startswith("digraph")
            assert dot.strip().endswith("}")

    def test_rate_div_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[RateDiv(id="rd", a="in1", divisor=4.0)],
        )
        dot = graph_to_dot(g)
        assert "rate_div" in dot
        assert "#fde0c8" in dot  # orange (stateful)

    def test_scale_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sc")],
            nodes=[Scale(id="sc", a="in1")],
        )
        dot = graph_to_dot(g)
        assert "scale" in dot
        assert "#fff3cd" in dot  # yellow (pure)

    def test_smooth_param_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="sp")],
            nodes=[SmoothParam(id="sp", a="in1", coeff=0.99)],
        )
        dot = graph_to_dot(g)
        assert "smooth" in dot
        assert "#fde0c8" in dot  # orange (stateful)

    def test_peek_node(self) -> None:
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="pk")],
            nodes=[Peek(id="pk", a="in1")],
        )
        dot = graph_to_dot(g)
        assert "peek" in dot
        assert "#d4edda" in dot  # green (debug)

    def test_empty_graph(self) -> None:
        graph = Graph(name="empty")
        dot = graph_to_dot(graph)
        assert 'digraph "empty"' in dot
        assert dot.strip().endswith("}")


class TestGraphToDotFile:
    def test_writes_dot_file(self, tmp_path: object, stereo_gain_graph: Graph) -> None:
        with patch("gen_dsp.graph.visualize.shutil.which", return_value=None):
            result = graph_to_dot_file(stereo_gain_graph, str(tmp_path))
        assert result.exists()
        assert result.name == "stereo_gain.dot"
        content = result.read_text()
        assert 'digraph "stereo_gain"' in content

    def test_creates_output_dir(self, tmp_path: object, onepole_graph: Graph) -> None:
        out_dir = tmp_path / "sub" / "dir"  # type: ignore[operator]
        with patch("gen_dsp.graph.visualize.shutil.which", return_value=None):
            result = graph_to_dot_file(onepole_graph, str(out_dir))
        assert result.exists()
        assert result.parent == out_dir

    def test_pdf_conversion_when_dot_available(
        self, tmp_path: object, stereo_gain_graph: Graph
    ) -> None:
        dot_bin = shutil.which("dot")
        if dot_bin is None:
            pytest.skip("dot binary not on PATH")
        result = graph_to_dot_file(stereo_gain_graph, str(tmp_path))
        pdf_path = result.with_suffix(".pdf")
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

    def test_no_pdf_when_dot_missing(
        self, tmp_path: object, stereo_gain_graph: Graph
    ) -> None:
        with patch("gen_dsp.graph.visualize.shutil.which", return_value=None):
            result = graph_to_dot_file(stereo_gain_graph, str(tmp_path))
        pdf_path = result.with_suffix(".pdf")
        assert not pdf_path.exists()
