"""Tests for optimization passes."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
import pytest

from gen_dsp.graph import (
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
    OptimizeStats,
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
    constant_fold,
    eliminate_cse,
    eliminate_dead_nodes,
    optimize_graph,
    promote_control_rate,
)

# ---------------------------------------------------------------------------
# Constant folding
# ---------------------------------------------------------------------------


class TestConstantFold:
    def test_binop_div_folded(self) -> None:
        """44100.0 / 1000.0 -> Constant(44.1)"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="sr", value=44100.0),
                Constant(id="k", value=1000.0),
                BinOp(id="r", op="div", a="sr", b="k"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(44.1)

    def test_chain_folds(self) -> None:
        """Chain of constants collapses: (2 + 3) * 4 -> 20"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="result")],
            nodes=[
                Constant(id="a", value=2.0),
                Constant(id="b", value=3.0),
                BinOp(id="sum", op="add", a="a", b="b"),
                Constant(id="c", value=4.0),
                BinOp(id="result", op="mul", a="sum", b="c"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["result"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(20.0)

    def test_non_constant_input_preserved(self) -> None:
        """Nodes with non-constant inputs are not folded."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="k", value=2.0),
                BinOp(id="r", op="mul", a="in1", b="k"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, BinOp)

    def test_stateful_never_folded(self) -> None:
        """Stateful nodes are never constant-folded."""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="p")],
            nodes=[
                Phasor(id="p", freq=440.0),
                Noise(id="n"),
                History(id="h", input="p"),
                Delta(id="d", a=0.0),
                Change(id="c", a=0.0),
            ],
        )
        folded = constant_fold(g)
        types = {n.id: type(n).__name__ for n in folded.nodes}
        assert types["p"] == "Phasor"
        assert types["n"] == "Noise"
        assert types["h"] == "History"
        assert types["d"] == "Delta"
        assert types["c"] == "Change"

    def test_unaryop_folded(self) -> None:
        """sin(0.0) -> 0.0"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="zero", value=0.0),
                UnaryOp(id="r", op="sin", a="zero"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(0.0)

    def test_compare_folded(self) -> None:
        """5.0 > 3.0 -> 1.0"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="a", value=5.0),
                Constant(id="b", value=3.0),
                Compare(id="r", op="gt", a="a", b="b"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(1.0)

    def test_select_folded(self) -> None:
        """select(1.0, 10.0, 20.0) -> 10.0"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="cond", value=1.0),
                Constant(id="a", value=10.0),
                Constant(id="b", value=20.0),
                Select(id="r", cond="cond", a="a", b="b"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(10.0)

    def test_clamp_folded(self) -> None:
        """clamp(5.0, 0.0, 1.0) -> 1.0"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="v", value=5.0),
                Clamp(id="r", a="v"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(1.0)

    def test_mix_folded(self) -> None:
        """mix(0.0, 10.0, 0.5) -> 5.0"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="a", value=0.0),
                Constant(id="b", value=10.0),
                Constant(id="t", value=0.5),
                Mix(id="r", a="a", b="b", t="t"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(5.0)

    def test_wrap_folded(self) -> None:
        """wrap(1.5, 0, 1) -> 0.5"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="v", value=1.5),
                Wrap(id="r", a="v"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(0.5)

    def test_fold_folded(self) -> None:
        """fold(1.7, 0, 1) -> 0.3"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="v", value=1.7),
                Fold(id="r", a="v"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(0.3)

    def test_v03_stateful_never_folded(self) -> None:
        """All v0.3 stateful nodes are never constant-folded."""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="bq")],
            nodes=[
                Biquad(id="bq", a=0.0, b0=1.0, b1=0.0, b2=0.0, a1=0.0, a2=0.0),
                SVF(id="svf", a=0.0, freq=1000.0, q=0.707, mode="lp"),
                OnePole(id="op", a=0.0, coeff=0.5),
                DCBlock(id="dc", a=0.0),
                Allpass(id="ap", a=0.0, coeff=0.5),
                SinOsc(id="so", freq=440.0),
                TriOsc(id="to", freq=440.0),
                SawOsc(id="sw", freq=440.0),
                PulseOsc(id="po", freq=440.0, width=0.5),
                SampleHold(id="sh", a=0.0, trig=0.0),
                Latch(id="la", a=0.0, trig=0.0),
                Accum(id="ac", incr=1.0, reset=0.0),
                Counter(id="ct", trig=0.0, max=16.0),
            ],
        )
        folded = constant_fold(g)
        types = {n.id: type(n).__name__ for n in folded.nodes}
        assert types["bq"] == "Biquad"
        assert types["svf"] == "SVF"
        assert types["op"] == "OnePole"
        assert types["dc"] == "DCBlock"
        assert types["ap"] == "Allpass"
        assert types["so"] == "SinOsc"
        assert types["to"] == "TriOsc"
        assert types["sw"] == "SawOsc"
        assert types["po"] == "PulseOsc"
        assert types["sh"] == "SampleHold"
        assert types["la"] == "Latch"
        assert types["ac"] == "Accum"
        assert types["ct"] == "Counter"

    def test_inverse_trig_folded(self) -> None:
        """atan(1.0) -> Constant(pi/4)"""
        import math

        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="one", value=1.0),
                UnaryOp(id="r", op="atan", a="one"),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(math.pi / 4)

    def test_literal_ref_folded(self) -> None:
        """BinOp with literal float refs folds: 2.0 + 3.0 -> 5.0"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                BinOp(id="r", op="add", a=2.0, b=3.0),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(5.0)

    def test_extended_binops_fold(self) -> None:
        """min, max, mod, pow fold correctly."""
        for op, a, b, expected in [
            ("min", 3.0, 5.0, 3.0),
            ("max", 3.0, 5.0, 5.0),
            ("mod", 7.0, 3.0, 1.0),
            ("pow", 2.0, 3.0, 8.0),
        ]:
            g = Graph(
                name="test",
                outputs=[AudioOutput(id="out1", source="r")],
                nodes=[BinOp(id="r", op=op, a=a, b=b)],
            )
            folded = constant_fold(g)
            r = {n.id: n for n in folded.nodes}["r"]
            assert isinstance(r, Constant), f"{op} not folded"
            assert r.value == pytest.approx(expected), f"{op}: {r.value} != {expected}"


# ---------------------------------------------------------------------------
# Dead node elimination
# ---------------------------------------------------------------------------


class TestDeadNodeElimination:
    def test_unreachable_removed(self) -> None:
        """Nodes not reachable from outputs are removed."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="used")],
            nodes=[
                Constant(id="used", value=1.0),
                Constant(id="dead", value=999.0),
            ],
        )
        result = eliminate_dead_nodes(g)
        ids = {n.id for n in result.nodes}
        assert "used" in ids
        assert "dead" not in ids

    def test_reachable_preserved(self) -> None:
        """All nodes in the dependency chain are preserved."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="k", value=2.0),
                BinOp(id="r", op="mul", a="in1", b="k"),
            ],
        )
        result = eliminate_dead_nodes(g)
        ids = {n.id for n in result.nodes}
        assert ids == {"k", "r"}

    def test_feedback_edges_preserve_nodes(self) -> None:
        """Nodes reachable only through feedback edges are still preserved."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="result")],
            nodes=[
                History(id="prev", input="result", init=0.0),
                BinOp(id="result", op="add", a="in1", b="prev"),
            ],
        )
        result = eliminate_dead_nodes(g)
        ids = {n.id for n in result.nodes}
        # History references "result" via feedback, and "result" uses "prev"
        assert ids == {"prev", "result"}

    def test_delay_chain_preserved(self) -> None:
        """Delay line, read, and write are all preserved when output uses read."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[
                DelayLine(id="dl"),
                DelayRead(id="rd", delay="dl", tap=100.0),
                DelayWrite(id="dw", delay="dl", value="in1"),
                Constant(id="dead", value=0.0),
            ],
        )
        result = eliminate_dead_nodes(g)
        ids = {n.id for n in result.nodes}
        assert "dl" in ids
        assert "rd" in ids
        # dw writes to the same delay line that rd reads -- side effect preserved
        assert "dw" in ids
        assert "dead" not in ids

    def test_delay_write_deps_preserved(self) -> None:
        """DelayWrite's input dependencies are also preserved."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[
                DelayLine(id="dl"),
                DelayRead(id="rd", delay="dl", tap=100.0),
                BinOp(id="scaled", op="mul", a="in1", b=0.5),
                DelayWrite(id="dw", delay="dl", value="scaled"),
            ],
        )
        result = eliminate_dead_nodes(g)
        ids = {n.id for n in result.nodes}
        # scaled is only reachable through dw, which is kept as a side effect
        assert ids == {"dl", "rd", "scaled", "dw"}

    def test_unreferenced_delay_write_removed(self) -> None:
        """DelayWrite to a line with no reachable reader IS dead."""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[
                Constant(id="c", value=1.0),
                DelayLine(id="dl"),
                DelayWrite(id="dw", delay="dl", value=0.0),
            ],
        )
        result = eliminate_dead_nodes(g)
        ids = {n.id for n in result.nodes}
        assert "c" in ids
        assert "dw" not in ids
        assert "dl" not in ids


# ---------------------------------------------------------------------------
# Combined optimization
# ---------------------------------------------------------------------------


class TestOptimizeGraph:
    def test_fold_then_eliminate(self) -> None:
        """Constant folding + dead elimination applied together."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Constant(id="sr", value=44100.0),
                Constant(id="k", value=1000.0),
                BinOp(id="ratio", op="div", a="sr", b="k"),
                BinOp(id="r", op="mul", a="in1", b="ratio"),
                Constant(id="dead", value=999.0),
            ],
        )
        result, stats = optimize_graph(g)
        ids = {n.id for n in result.nodes}
        # ratio should be folded into a constant
        r_ratio = {n.id: n for n in result.nodes}.get("ratio")
        assert isinstance(r_ratio, Constant)
        assert r_ratio.value == pytest.approx(44.1)
        # dead should be eliminated
        assert "dead" not in ids
        # sr and k are now dead too (ratio is a constant, doesn't reference them)
        assert "sr" not in ids
        assert "k" not in ids
        # stats: 1 fold (ratio), 0 CSE, 3 dead (sr, k, dead)
        assert stats.constants_folded == 1
        assert stats.cse_merges == 0
        assert stats.dead_nodes_removed == 3

    def test_empty_graph(self) -> None:
        g = Graph(name="empty")
        result, stats = optimize_graph(g)
        assert result.nodes == []
        assert stats == OptimizeStats(0, 0, 0, 0)

    def test_v04_buffer_stateful_never_folded(self) -> None:
        """All v0.4 buffer-related stateful nodes are never constant-folded."""
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
        folded = constant_fold(g)
        types = {n.id: type(n).__name__ for n in folded.nodes}
        assert types["buf"] == "Buffer"
        assert types["br"] == "BufRead"
        assert types["bw"] == "BufWrite"
        assert types["bs"] == "BufSize"

    def test_buffer_dead_node_elimination_preserved(self) -> None:
        """BufWrite kept alive when BufRead on same buffer is reachable."""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="br")],
            nodes=[
                Buffer(id="buf", size=1024),
                BufRead(id="br", buffer="buf", index=0.0),
                BufWrite(id="bw", buffer="buf", index=0.0, value=0.0),
                Constant(id="dead", value=999.0),
            ],
        )
        result = eliminate_dead_nodes(g)
        ids = {n.id for n in result.nodes}
        assert "buf" in ids
        assert "br" in ids
        assert "bw" in ids
        assert "dead" not in ids

    def test_buffer_dead_node_elimination_removed(self) -> None:
        """BufWrite removed when no BufRead/BufSize on same buffer is reachable."""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[
                Constant(id="c", value=1.0),
                Buffer(id="buf", size=1024),
                BufWrite(id="bw", buffer="buf", index=0.0, value=0.0),
            ],
        )
        result = eliminate_dead_nodes(g)
        ids = {n.id for n in result.nodes}
        assert "c" in ids
        assert "bw" not in ids
        assert "buf" not in ids

    def test_bufsize_keeps_writers_alive(self) -> None:
        """BufSize also keeps BufWrite alive on the same buffer."""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="bs")],
            nodes=[
                Buffer(id="buf", size=1024),
                BufSize(id="bs", buffer="buf"),
                BufWrite(id="bw", buffer="buf", index=0.0, value=0.0),
            ],
        )
        result = eliminate_dead_nodes(g)
        ids = {n.id for n in result.nodes}
        assert "bs" in ids
        assert "bw" in ids

    def test_param_preserves_nodes(self) -> None:
        """Nodes depending on params are not folded."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            params=[Param(name="gain")],
            nodes=[
                BinOp(id="r", op="mul", a="in1", b="gain"),
            ],
        )
        result, _stats = optimize_graph(g)
        r = {n.id: n for n in result.nodes}["r"]
        assert isinstance(r, BinOp)


# ---------------------------------------------------------------------------
# Common Subexpression Elimination
# ---------------------------------------------------------------------------


class TestCSE:
    def test_identical_binops_collapsed(self) -> None:
        """Two identical BinOp(add, x, 1.0) -> one remains."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out1", source="a"),
                AudioOutput(id="out2", source="b"),
            ],
            nodes=[
                BinOp(id="a", op="add", a="in1", b=1.0),
                BinOp(id="b", op="add", a="in1", b=1.0),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert "a" in ids
        assert "b" not in ids
        # out2 should now reference "a"
        out2 = {o.id: o for o in result.outputs}["out2"]
        assert out2.source == "a"

    def test_commutative_detected(self) -> None:
        """add(a, b) == add(b, a) for commutative ops."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
            outputs=[
                AudioOutput(id="out1", source="a"),
                AudioOutput(id="out2", source="b"),
            ],
            nodes=[
                BinOp(id="a", op="add", a="in1", b="in2"),
                BinOp(id="b", op="add", a="in2", b="in1"),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert len(ids) == 1

    def test_noncommutative_preserved(self) -> None:
        """sub(a, b) != sub(b, a) for non-commutative ops."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
            outputs=[
                AudioOutput(id="out1", source="a"),
                AudioOutput(id="out2", source="b"),
            ],
            nodes=[
                BinOp(id="a", op="sub", a="in1", b="in2"),
                BinOp(id="b", op="sub", a="in2", b="in1"),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert len(ids) == 2

    def test_stateful_never_cse(self) -> None:
        """Two identical Phasors remain distinct (stateful)."""
        g = Graph(
            name="test",
            outputs=[
                AudioOutput(id="out1", source="a"),
                AudioOutput(id="out2", source="b"),
            ],
            nodes=[
                Phasor(id="a", freq=440.0),
                Phasor(id="b", freq=440.0),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert ids == {"a", "b"}

    def test_transitive_rewrite(self) -> None:
        """B refs A, A is dup of A' -> B refs A'."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="c")],
            nodes=[
                BinOp(id="a1", op="add", a="in1", b=1.0),
                BinOp(id="a2", op="add", a="in1", b=1.0),
                # c references a2, which is a duplicate of a1
                BinOp(id="c", op="mul", a="a2", b=2.0),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert "a2" not in ids
        c = {n.id: n for n in result.nodes}["c"]
        assert isinstance(c, BinOp)
        assert c.a == "a1"

    def test_constants_merged(self) -> None:
        """Two Constant(value=3.14) -> one."""
        g = Graph(
            name="test",
            outputs=[
                AudioOutput(id="out1", source="a"),
                AudioOutput(id="out2", source="b"),
            ],
            nodes=[
                Constant(id="a", value=3.14),
                Constant(id="b", value=3.14),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert len(ids) == 1

    def test_multifield_nodes(self) -> None:
        """Identical Clamp and Mix nodes are merged."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out1", source="c1"),
                AudioOutput(id="out2", source="c2"),
                AudioOutput(id="out3", source="m1"),
                AudioOutput(id="out4", source="m2"),
            ],
            nodes=[
                Clamp(id="c1", a="in1", lo=0.0, hi=1.0),
                Clamp(id="c2", a="in1", lo=0.0, hi=1.0),
                Mix(id="m1", a="in1", b=1.0, t=0.5),
                Mix(id="m2", a="in1", b=1.0, t=0.5),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert "c2" not in ids
        assert "m2" not in ids

    def test_unaryop_cse(self) -> None:
        """Identical UnaryOp nodes are merged."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out1", source="a"),
                AudioOutput(id="out2", source="b"),
            ],
            nodes=[
                UnaryOp(id="a", op="sin", a="in1"),
                UnaryOp(id="b", op="sin", a="in1"),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert len(ids) == 1

    def test_compare_cse(self) -> None:
        """Identical Compare nodes are merged."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out1", source="a"),
                AudioOutput(id="out2", source="b"),
            ],
            nodes=[
                Compare(id="a", op="gt", a="in1", b=0.0),
                Compare(id="b", op="gt", a="in1", b=0.0),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert len(ids) == 1

    def test_select_cse(self) -> None:
        """Identical Select nodes are merged."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out1", source="s1"),
                AudioOutput(id="out2", source="s2"),
            ],
            nodes=[
                Compare(id="cmp", op="gt", a="in1", b=0.0),
                Select(id="s1", cond="cmp", a="in1", b=0.0),
                Select(id="s2", cond="cmp", a="in1", b=0.0),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert "s2" not in ids

    def test_wrap_fold_cse(self) -> None:
        """Identical Wrap and Fold nodes are merged."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out1", source="w1"),
                AudioOutput(id="out2", source="w2"),
                AudioOutput(id="out3", source="f1"),
                AudioOutput(id="out4", source="f2"),
            ],
            nodes=[
                Wrap(id="w1", a="in1", lo=0.0, hi=1.0),
                Wrap(id="w2", a="in1", lo=0.0, hi=1.0),
                Fold(id="f1", a="in1", lo=0.0, hi=1.0),
                Fold(id="f2", a="in1", lo=0.0, hi=1.0),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert "w2" not in ids
        assert "f2" not in ids

    def test_different_values_not_merged(self) -> None:
        """Constants with different values remain separate."""
        g = Graph(
            name="test",
            outputs=[
                AudioOutput(id="out1", source="a"),
                AudioOutput(id="out2", source="b"),
            ],
            nodes=[
                Constant(id="a", value=3.14),
                Constant(id="b", value=2.71),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert ids == {"a", "b"}

    def test_different_ops_not_merged(self) -> None:
        """BinOps with different ops but same operands remain separate."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out1", source="a"),
                AudioOutput(id="out2", source="b"),
            ],
            nodes=[
                BinOp(id="a", op="add", a="in1", b=1.0),
                BinOp(id="b", op="sub", a="in1", b=1.0),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert ids == {"a", "b"}

    def test_stateful_node_refs_rewritten(self) -> None:
        """A History node referencing a CSE'd node gets its ref rewritten."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="result")],
            nodes=[
                BinOp(id="a1", op="add", a="in1", b=1.0),
                BinOp(id="a2", op="add", a="in1", b=1.0),
                History(id="prev", init=0.0, input="a2"),
                BinOp(id="result", op="add", a="a1", b="prev"),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert "a2" not in ids
        h = {n.id: n for n in result.nodes}["prev"]
        assert isinstance(h, History)
        assert h.input == "a1"

    def test_cse_in_optimize_graph(self) -> None:
        """End-to-end: CSE runs as part of optimize_graph()."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out1", source="a"),
                AudioOutput(id="out2", source="b"),
            ],
            params=[Param(name="gain")],
            nodes=[
                BinOp(id="a", op="mul", a="in1", b="gain"),
                BinOp(id="b", op="mul", a="in1", b="gain"),
            ],
        )
        result, stats = optimize_graph(g)
        ids = {n.id for n in result.nodes}
        # One of a/b should be eliminated
        assert len(ids) == 1
        assert stats.cse_merges == 1

    def test_cse_orphaned_deps_eliminated(self) -> None:
        """Second dead-node pass removes nodes orphaned by CSE.

        Graph: helper1 feeds dup1, helper2 feeds dup2.
        dup1 and dup2 are identical (both read in1 * 2.0).
        CSE removes dup2 and rewires result to dup1.
        First dead-node pass runs before CSE, so helper2 was live.
        After CSE, helper2 is only referenced by the now-removed dup2.
        The second dead-node pass catches helper2.
        """
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="result")],
            nodes=[
                # helper1 and helper2 both compute in1 * 2.0
                BinOp(id="helper1", op="mul", a="in1", b=2.0),
                BinOp(id="helper2", op="mul", a="in1", b=2.0),
                # dup1 uses helper1, dup2 uses helper2 -- but both
                # resolve to the same CSE key after helper2 -> helper1 rewrite
                UnaryOp(id="dup1", op="abs", a="helper1"),
                UnaryOp(id="dup2", op="abs", a="helper2"),
                # result only uses dup2, which CSE rewrites to dup1
                BinOp(id="result", op="add", a="dup2", b=1.0),
            ],
        )
        result, stats = optimize_graph(g)
        ids = {n.id for n in result.nodes}
        # CSE merges helper2->helper1 and dup2->dup1
        assert "helper2" not in ids, (
            "helper2 should be eliminated by second dead-node pass"
        )
        assert "dup2" not in ids, "dup2 should be eliminated by CSE"
        # Core chain preserved
        assert "helper1" in ids
        assert "dup1" in ids
        assert "result" in ids
        assert stats.cse_merges == 2  # helper2->helper1, dup2->dup1

    def test_scale_cse(self) -> None:
        """Identical Scale nodes are merged."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[
                AudioOutput(id="out1", source="s1"),
                AudioOutput(id="out2", source="s2"),
            ],
            nodes=[
                Scale(id="s1", a="in1", in_lo=0.0, in_hi=1.0, out_lo=0.0, out_hi=10.0),
                Scale(id="s2", a="in1", in_lo=0.0, in_hi=1.0, out_lo=0.0, out_hi=10.0),
            ],
        )
        result = eliminate_cse(g)
        ids = {n.id for n in result.nodes}
        assert len(ids) == 1


# ---------------------------------------------------------------------------
# Scale constant folding
# ---------------------------------------------------------------------------


class TestScaleFold:
    def test_scale_folded(self) -> None:
        """scale(0.5, 0, 1, 0, 10) -> 5.0"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Scale(id="r", a=0.5, in_lo=0.0, in_hi=1.0, out_lo=0.0, out_hi=10.0),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(5.0)

    def test_scale_degenerate_range(self) -> None:
        """scale with in_lo == in_hi -> out_lo"""
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[
                Scale(id="r", a=0.5, in_lo=1.0, in_hi=1.0, out_lo=5.0, out_hi=10.0),
            ],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Constant)
        assert r.value == pytest.approx(5.0)

    def test_scale_non_constant_preserved(self) -> None:
        """Scale with non-constant input is not folded."""
        g = Graph(
            name="test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="r")],
            nodes=[Scale(id="r", a="in1")],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["r"]
        assert isinstance(r, Scale)


# ---------------------------------------------------------------------------
# New stateful types never folded
# ---------------------------------------------------------------------------


class TestNewStatefulNeverFolded:
    def test_rate_div_never_folded(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="rd")],
            nodes=[RateDiv(id="rd", a=0.0, divisor=4.0)],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["rd"]
        assert isinstance(r, RateDiv)

    def test_smooth_param_never_folded(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="sp")],
            nodes=[SmoothParam(id="sp", a=0.0, coeff=0.99)],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["sp"]
        assert isinstance(r, SmoothParam)

    def test_peek_never_folded(self) -> None:
        g = Graph(
            name="test",
            outputs=[AudioOutput(id="out1", source="pk")],
            nodes=[Peek(id="pk", a=0.0)],
        )
        folded = constant_fold(g)
        r = {n.id: n for n in folded.nodes}["pk"]
        assert isinstance(r, Peek)


# ---------------------------------------------------------------------------
# Control-rate promotion
# ---------------------------------------------------------------------------


class TestPromoteControlRate:
    def test_basic_promotion(self) -> None:
        """Pure node depending on a control-rate node is promoted."""
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
        result = promote_control_rate(g)
        assert "inv_vol" in result.control_nodes
        # result depends on audio input, should NOT be promoted
        assert "result" not in result.control_nodes

    def test_transitive_promotion(self) -> None:
        """Chain of promotable nodes: A->B->C all promoted."""
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
                BinOp(id="step1", op="sub", a=1.0, b="smoother"),
                UnaryOp(id="step2", op="abs", a="step1"),
                BinOp(id="result", op="mul", a="in0", b="step2"),
            ],
        )
        result = promote_control_rate(g)
        assert "step1" in result.control_nodes
        assert "step2" in result.control_nodes
        assert "result" not in result.control_nodes

    def test_stateful_never_promoted(self) -> None:
        """Stateful nodes are never promoted even if deps are control-rate."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["ctrl_const"],
            inputs=[],
            outputs=[AudioOutput(id="out0", source="osc")],
            params=[Param(name="freq")],
            nodes=[
                BinOp(id="ctrl_const", op="mul", a="freq", b=0.5),
                Phasor(id="osc", freq="ctrl_const"),
            ],
        )
        result = promote_control_rate(g)
        assert "osc" not in result.control_nodes

    def test_invariant_not_promoted(self) -> None:
        """Invariant nodes stay in LICM tier, not downgraded to control-rate."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["smoother"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="result")],
            params=[Param(name="a"), Param(name="b")],
            nodes=[
                SmoothParam(id="smoother", a="a", coeff=0.9),
                BinOp(id="inv", op="add", a="a", b="b"),  # depends only on params
                BinOp(id="result", op="mul", a="in0", b="inv"),
            ],
        )
        result = promote_control_rate(g)
        # inv depends only on params -> invariant, should NOT be promoted
        assert "inv" not in result.control_nodes

    def test_noop_when_control_interval_zero(self) -> None:
        """No promotion when control_interval=0."""
        g = Graph(
            name="test",
            control_interval=0,
            control_nodes=[],
            outputs=[AudioOutput(id="out0", source="x")],
            nodes=[BinOp(id="x", op="add", a=1.0, b=2.0)],
        )
        result = promote_control_rate(g)
        assert result.control_nodes == []

    def test_noop_when_control_nodes_empty(self) -> None:
        """No promotion when control_nodes is empty (even with interval>0)."""
        g = Graph(
            name="test",
            control_interval=64,
            control_nodes=[],
            outputs=[AudioOutput(id="out0", source="x")],
            nodes=[BinOp(id="x", op="add", a=1.0, b=2.0)],
        )
        result = promote_control_rate(g)
        assert result.control_nodes == []

    def test_depends_on_invariant_and_control(self) -> None:
        """Node depending on both invariant and control-rate is still promotable."""
        g = Graph(
            name="test",
            sample_rate=48000.0,
            control_interval=64,
            control_nodes=["smoother"],
            inputs=[AudioInput(id="in0")],
            outputs=[AudioOutput(id="out0", source="result")],
            params=[Param(name="vol"), Param(name="scale")],
            nodes=[
                SmoothParam(id="smoother", a="vol", coeff=0.9),
                # mix_node depends on param (invariant dep) and smoother (control-rate)
                BinOp(id="mix_node", op="mul", a="scale", b="smoother"),
                BinOp(id="result", op="mul", a="in0", b="mix_node"),
            ],
        )
        result = promote_control_rate(g)
        assert "mix_node" in result.control_nodes

    def test_stats_via_optimize_graph(self) -> None:
        """optimize_graph reports promoted count in stats."""
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
        _, stats = optimize_graph(g)
        assert stats.control_rate_promoted == 1
