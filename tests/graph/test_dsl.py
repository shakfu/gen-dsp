"""Tests for the GDSP DSL parser (tokenizer, parser, compiler)."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")

import pytest

from gen_dsp.graph.dsl import (
    EOF,
    IDENT,
    NEWLINE,
    NUMBER,
    OP,
    STRING,
    ASTAssign,
    ASTBinExpr,
    ASTBufferDecl,
    ASTCall,
    ASTCompose,
    ASTDelayDecl,
    ASTDelayWriteStmt,
    ASTDotAccess,
    ASTFeedbackWrite,
    ASTGraph,
    ASTHistoryDecl,
    ASTIdent,
    ASTInDecl,
    ASTNumber,
    ASTOutDecl,
    ASTParamDecl,
    ASTUnaryExpr,
    GDSPCompileError,
    GDSPSyntaxError,
    Parser,
    parse,
    parse_file,
    parse_multi,
    tokenize,
)
from gen_dsp.graph.models import (
    BinOp,
    Buffer,
    BufRead,
    Cycle,
    DelayLine,
    DelayRead,
    DelayWrite,
    GateOut,
    GateRoute,
    Graph,
    History,
    NamedConstant,
    SampleRate,
    SinOsc,
    Subgraph,
    UnaryOp,
)


# =========================================================================
# Tokenizer tests
# =========================================================================


class TestTokenizer:
    def test_basic_tokens(self):
        tokens = tokenize("graph foo { }")
        types = [(t.type, t.value) for t in tokens if t.type != EOF]
        assert types == [
            (IDENT, "graph"),
            (IDENT, "foo"),
            (OP, "{"),
            (OP, "}"),
        ]

    def test_numbers(self):
        tokens = tokenize("42 3.14 0.5")
        nums = [t.value for t in tokens if t.type == NUMBER]
        assert nums == ["42", "3.14", "0.5"]

    def test_operators(self):
        tokens = tokenize("+ - * / % ** >> // >= <= == != .. <- = ( ) { } , . : ; @")
        ops = [t.value for t in tokens if t.type == OP]
        assert ops == [
            "+",
            "-",
            "*",
            "/",
            "%",
            "**",
            ">>",
            "//",
            ">=",
            "<=",
            "==",
            "!=",
            "..",
            "<-",
            "=",
            "(",
            ")",
            "{",
            "}",
            ",",
            ".",
            ":",
            ";",
            "@",
        ]

    def test_comments_skipped(self):
        tokens = tokenize("a # comment\nb")
        idents = [t.value for t in tokens if t.type == IDENT]
        assert idents == ["a", "b"]

    def test_parallel_not_comment(self):
        """// is the parallel operator, not a comment."""
        tokens = tokenize("a // b")
        types = [(t.type, t.value) for t in tokens if t.type not in (EOF,)]
        assert (OP, "//") in types

    def test_newlines_are_tokens(self):
        tokens = tokenize("a\nb")
        assert any(t.type == NEWLINE for t in tokens)

    def test_string_literal(self):
        tokens = tokenize('"hello.gdsp"')
        strs = [t for t in tokens if t.type == STRING]
        assert len(strs) == 1
        assert strs[0].value == "hello.gdsp"

    def test_unterminated_string(self):
        with pytest.raises(GDSPSyntaxError, match="unterminated string"):
            tokenize('"unterminated')

    def test_unexpected_char(self):
        with pytest.raises(GDSPSyntaxError, match="unexpected character"):
            tokenize("$")

    def test_line_col_tracking(self):
        tokens = tokenize("a\n  b")
        b_tok = [t for t in tokens if t.type == IDENT and t.value == "b"][0]
        assert b_tok.line == 2
        assert b_tok.col == 3

    def test_multiline_with_comments(self):
        src = """
        # first line comment
        graph foo {
            param x 0..1 = 0.5  # inline comment
        }
        """
        tokens = tokenize(src)
        idents = [t.value for t in tokens if t.type == IDENT]
        assert "graph" in idents
        assert "foo" in idents
        assert "param" in idents


# =========================================================================
# Parser tests
# =========================================================================


class TestParser:
    def _parse_graph(self, src: str) -> ASTGraph:
        tokens = tokenize(src)
        parser = Parser(tokens)
        graphs = parser.parse_file()
        assert len(graphs) == 1
        return graphs[0]

    def test_empty_graph(self):
        g = self._parse_graph("graph empty { }")
        assert g.name == "empty"
        assert g.body == []

    def test_graph_options(self):
        g = self._parse_graph("graph test (sr=48000, control=64) { }")
        assert g.options == {"sr": 48000.0, "control": 64.0}

    def test_in_decl(self):
        g = self._parse_graph("graph t { in a, b, c }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTInDecl)
        assert stmt.ids == ["a", "b", "c"]

    def test_out_decl(self):
        g = self._parse_graph("graph t { out output = x }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTOutDecl)
        assert stmt.name == "output"
        assert isinstance(stmt.source, ASTIdent)

    def test_param_decl(self):
        g = self._parse_graph("graph t { param freq 20..20000 = 440 }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTParamDecl)
        assert stmt.name == "freq"
        assert stmt.min_val == 20.0
        assert stmt.max_val == 20000.0
        assert stmt.default == 440.0
        assert not stmt.control

    def test_param_control(self):
        g = self._parse_graph("graph t { @control param freq 20..20000 = 440 }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTParamDecl)
        assert stmt.control

    def test_buffer_decl(self):
        g = self._parse_graph("graph t { buffer tbl 512 fill=sine }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTBufferDecl)
        assert stmt.name == "tbl"
        assert stmt.size == 512
        assert stmt.fill == "sine"

    def test_delay_decl(self):
        g = self._parse_graph("graph t { delay dly 96000 }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTDelayDecl)
        assert stmt.name == "dly"
        assert stmt.max_samples == 96000

    def test_history_decl(self):
        g = self._parse_graph("graph t { history fb = 0.5 }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTHistoryDecl)
        assert stmt.name == "fb"
        assert stmt.init == 0.5

    def test_feedback_write(self):
        g = self._parse_graph("graph t { history fb = 0.0\nfb <- y }")
        stmt = g.body[1]
        assert isinstance(stmt, ASTFeedbackWrite)
        assert stmt.name == "fb"

    def test_delay_write(self):
        g = self._parse_graph("graph t { delay_write dly (x) }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTDelayWriteStmt)
        assert stmt.delay == "dly"

    def test_assignment(self):
        g = self._parse_graph("graph t { y = x * 0.5 }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTAssign)
        assert stmt.targets == ["y"]
        assert isinstance(stmt.value, ASTBinExpr)
        assert stmt.value.op == "mul"

    def test_destructuring(self):
        g = self._parse_graph("graph t { a, b, c = gate_route(x, i, 3) }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTAssign)
        assert stmt.targets == ["a", "b", "c"]

    def test_control_assignment(self):
        g = self._parse_graph("graph t { @control y = smooth(x, 0.99) }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTAssign)
        assert stmt.control

    def test_expression_precedence(self):
        """a + b * c should parse as a + (b * c)."""
        g = self._parse_graph("graph t { y = a + b * c }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTAssign)
        expr = stmt.value
        assert isinstance(expr, ASTBinExpr)
        assert expr.op == "add"
        assert isinstance(expr.right, ASTBinExpr)
        assert expr.right.op == "mul"

    def test_power_right_assoc(self):
        """a ** b ** c should parse as a ** (b ** c)."""
        g = self._parse_graph("graph t { y = a ** b ** c }")
        stmt = g.body[0]
        expr = stmt.value
        assert isinstance(expr, ASTBinExpr)
        assert expr.op == "pow"
        assert isinstance(expr.right, ASTBinExpr)
        assert expr.right.op == "pow"

    def test_unary_neg(self):
        g = self._parse_graph("graph t { y = -x }")
        stmt = g.body[0]
        expr = stmt.value
        assert isinstance(expr, ASTUnaryExpr)
        assert expr.op == "neg"

    def test_constant_negation_fold(self):
        """Unary minus on number literal should fold to negative number."""
        g = self._parse_graph("graph t { y = -3.14 }")
        stmt = g.body[0]
        expr = stmt.value
        assert isinstance(expr, ASTNumber)
        assert expr.value == -3.14

    def test_dot_access(self):
        g = self._parse_graph("graph t { y = sub.output }")
        stmt = g.body[0]
        expr = stmt.value
        assert isinstance(expr, ASTDotAccess)
        assert isinstance(expr.obj, ASTIdent)
        assert expr.field_name == "output"

    def test_function_call(self):
        g = self._parse_graph("graph t { y = sin(x) }")
        stmt = g.body[0]
        expr = stmt.value
        assert isinstance(expr, ASTCall)
        assert expr.name == "sin"
        assert len(expr.args) == 1

    def test_keyword_args(self):
        g = self._parse_graph("graph t { y = svf(x, 1000, 0.7, mode=lp) }")
        stmt = g.body[0]
        expr = stmt.value
        assert isinstance(expr, ASTCall)
        # 3 positional + 1 keyword
        assert len(expr.args) == 4
        assert expr.args[3].name == "mode"

    def test_composition_operators(self):
        g = self._parse_graph("graph t { y = a(x=1) >> b(x=2) }")
        stmt = g.body[0]
        expr = stmt.value
        assert isinstance(expr, ASTCompose)
        assert expr.op == ">>"

    def test_parallel_operator(self):
        g = self._parse_graph("graph t { y = a() // b() }")
        stmt = g.body[0]
        expr = stmt.value
        assert isinstance(expr, ASTCompose)
        assert expr.op == "//"

    def test_delay_read_expr(self):
        g = self._parse_graph("graph t { tap = delay_read dly (100) }")
        stmt = g.body[0]
        assert isinstance(stmt, ASTAssign)
        expr = stmt.value
        assert isinstance(expr, ASTCall)
        assert expr.name == "delay_read"
        # First arg is injected delay name
        assert len(expr.args) == 2

    def test_semicolon_separator(self):
        g = self._parse_graph("graph t { in x; out o = x }")
        assert len(g.body) == 2

    def test_multi_graph(self):
        src = "graph a { } graph b { }"
        tokens = tokenize(src)
        parser = Parser(tokens)
        graphs = parser.parse_file()
        assert len(graphs) == 2
        assert graphs[0].name == "a"
        assert graphs[1].name == "b"


# =========================================================================
# Compiler tests
# =========================================================================


class TestCompiler:
    def test_minimal_gain(self):
        graph = parse("""
        graph gain {
            in input
            out output = scaled
            param g 0..1 = 0.5
            scaled = input * g
        }
        """)
        assert graph.name == "gain"
        assert len(graph.inputs) == 1
        assert graph.inputs[0].id == "input"
        assert len(graph.outputs) == 1
        assert graph.outputs[0].id == "output"
        assert graph.outputs[0].source == "scaled"
        assert len(graph.params) == 1
        assert graph.params[0].name == "g"
        assert graph.params[0].default == 0.5
        # Should have a mul node
        mul_nodes = [n for n in graph.nodes if isinstance(n, BinOp) and n.op == "mul"]
        assert len(mul_nodes) == 1
        assert mul_nodes[0].id == "scaled"

    def test_generator_no_inputs(self):
        graph = parse("""
        graph osc {
            out output = s
            param freq 20..20000 = 440
            s = sinosc(freq)
        }
        """)
        assert len(graph.inputs) == 0
        assert len(graph.outputs) == 1
        sin_nodes = [n for n in graph.nodes if isinstance(n, SinOsc)]
        assert len(sin_nodes) == 1

    def test_history_feedback(self):
        graph = parse("""
        graph lpf {
            in input
            out output = y
            param coeff 0..1 = 0.5
            history fb = 0.0
            y = input + fb * coeff
            fb <- y
        }
        """)
        hist_nodes = [n for n in graph.nodes if isinstance(n, History)]
        assert len(hist_nodes) == 1
        assert hist_nodes[0].id == "fb"
        assert hist_nodes[0].input != "__pending__"

    def test_delay_line(self):
        graph = parse("""
        graph dly {
            in input
            out output = tap
            delay dl 48000
            delay_write dl (input)
            tap = delay_read dl (1000)
        }
        """)
        dl_nodes = [n for n in graph.nodes if isinstance(n, DelayLine)]
        assert len(dl_nodes) == 1
        dw_nodes = [n for n in graph.nodes if isinstance(n, DelayWrite)]
        assert len(dw_nodes) == 1
        dr_nodes = [n for n in graph.nodes if isinstance(n, DelayRead)]
        assert len(dr_nodes) == 1
        assert dr_nodes[0].delay == "dl"

    def test_delay_read_with_interp(self):
        graph = parse("""
        graph dly {
            in input
            out output = tap
            delay dl 48000
            delay_write dl (input)
            tap = delay_read dl (1000, interp=linear)
        }
        """)
        dr = [n for n in graph.nodes if isinstance(n, DelayRead)][0]
        assert dr.interp == "linear"

    def test_buffer_cycle(self):
        graph = parse("""
        graph wt {
            out output = val
            param freq 20..20000 = 440
            buffer tbl 512 fill=sine
            phase = phasor(freq)
            val = cycle(tbl, phase)
        }
        """)
        buf = [n for n in graph.nodes if isinstance(n, Buffer)]
        assert len(buf) == 1
        assert buf[0].fill == "sine"
        cyc = [n for n in graph.nodes if isinstance(n, Cycle)]
        assert len(cyc) == 1
        assert cyc[0].buffer == "tbl"

    def test_control_rate(self):
        graph = parse("""
        graph synth (control=64) {
            out output = osc
            @control param freq 20..20000 = 440
            @control sf = smooth(freq, 0.999)
            osc = sinosc(sf)
        }
        """)
        assert graph.control_interval == 64
        # @control on param is a no-op (params aren't nodes)
        assert "freq" not in graph.control_nodes
        # @control on assignment adds the node ID
        assert "sf" in graph.control_nodes

    def test_destructuring_gate_route(self):
        graph = parse("""
        graph router {
            in input
            out out1 = a
            out out2 = b
            param route 0..2 = 1
            a, b = gate_route(input, route, 2)
        }
        """)
        gr_nodes = [n for n in graph.nodes if isinstance(n, GateRoute)]
        assert len(gr_nodes) == 1
        go_nodes = [n for n in graph.nodes if isinstance(n, GateOut)]
        assert len(go_nodes) == 2
        assert go_nodes[0].id == "a"
        assert go_nodes[0].channel == 1
        assert go_nodes[1].id == "b"
        assert go_nodes[1].channel == 2

    def test_named_constants(self):
        graph = parse("""
        graph t {
            out output = y
            y = pi
        }
        """)
        nc = [n for n in graph.nodes if isinstance(n, NamedConstant)]
        assert len(nc) == 1
        assert nc[0].op == "pi"

    def test_implicit_sr(self):
        graph = parse("""
        graph t (sr=48000) {
            out output = y
            param freq 20..20000 = 440
            y = freq / sr
        }
        """)
        assert graph.sample_rate == 48000.0
        sr_nodes = [n for n in graph.nodes if isinstance(n, SampleRate)]
        assert len(sr_nodes) == 1
        assert sr_nodes[0].id == "sr"

    def test_comparison_operators(self):
        graph = parse("""
        graph t {
            in x
            out output = cmp
            cmp = x > 0.5
        }
        """)
        from gen_dsp.graph.models import Compare

        cmp = [n for n in graph.nodes if isinstance(n, Compare)]
        assert len(cmp) == 1
        assert cmp[0].op == "gt"

    def test_param_default_clamping(self):
        graph = parse("""
        graph t {
            out output = x
            param x 0..1 = 5.0
        }
        """)
        assert graph.params[0].default == 1.0

    def test_negative_param_default(self):
        graph = parse("""
        graph t {
            out output = x
            param x -10..10 = -5
        }
        """)
        assert graph.params[0].min == -10.0
        assert graph.params[0].default == -5.0

    def test_multi_graph_subgraph(self):
        graphs = parse_multi("""
        graph lpf {
            in input
            out output = filtered
            param coeff 0..1 = 0.3
            filtered = onepole(input, coeff)
        }

        graph main {
            in x
            out output = y
            y = lpf(input=x, coeff=0.5)
        }
        """)
        assert "lpf" in graphs
        assert "main" in graphs
        main = graphs["main"]
        sg = [n for n in main.nodes if isinstance(n, Subgraph)]
        assert len(sg) == 1
        assert sg[0].graph.name == "lpf"

    def test_parse_returns_last_graph(self):
        graph = parse("""
        graph helper { out o = x; param x 0..1 = 0 }
        graph main { out o = y; y = helper(x=0.5) }
        """)
        assert graph.name == "main"

    def test_dot_access_subgraph(self):
        graph = parse("""
        graph stereo {
            in in_l, in_r
            out left = in_l
            out right = in_r
        }

        graph main {
            in a, b
            out out_l = stereo.left
            out out_r = stereo.right
            stereo = stereo(in_l=a, in_r=b)
        }
        """)
        assert graph.outputs[0].source == "stereo.left"
        assert graph.outputs[1].source == "stereo.right"

    def test_unary_ops(self):
        graph = parse("""
        graph t {
            in x
            out output = y
            y = abs(x)
        }
        """)
        uo = [n for n in graph.nodes if isinstance(n, UnaryOp)]
        assert len(uo) == 1
        assert uo[0].op == "abs"

    def test_binary_op_functions(self):
        graph = parse("""
        graph t {
            in a
            in b
            out output = y
            y = max(a, b)
        }
        """)
        bo = [n for n in graph.nodes if isinstance(n, BinOp)]
        assert len(bo) == 1
        assert bo[0].op == "max"

    def test_complex_expression(self):
        """Test a compound expression with multiple operators."""
        graph = parse("""
        graph t {
            in x
            out output = y
            y = (x + 1.0) * 0.5 - 0.25
        }
        """)
        # Should produce add, mul, sub nodes
        adds = [n for n in graph.nodes if isinstance(n, BinOp) and n.op == "add"]
        muls = [n for n in graph.nodes if isinstance(n, BinOp) and n.op == "mul"]
        subs = [n for n in graph.nodes if isinstance(n, BinOp) and n.op == "sub"]
        assert len(adds) >= 1
        assert len(muls) >= 1
        assert len(subs) >= 1

    def test_inline_composition_series(self):
        graph = parse("""
        graph lpf {
            in input
            out output = filtered
            param coeff 0..1 = 0.3
            filtered = onepole(input, coeff)
        }
        graph hpf {
            in input
            out output = filtered
            param coeff 0..1 = 0.7
            filtered = input - onepole(input, coeff)
        }
        graph main {
            in input
            out output = processed
            processed = lpf(coeff=0.2) >> hpf(coeff=0.8)
        }
        """)
        assert graph.name == "main"
        # Should contain a Subgraph wrapping the composed result
        sg = [n for n in graph.nodes if isinstance(n, Subgraph)]
        assert len(sg) >= 1

    def test_buf_read_with_interp(self):
        graph = parse("""
        graph t {
            in x
            out output = val
            buffer tbl 512
            val = buf_read(tbl, x, interp=linear)
        }
        """)
        br = [n for n in graph.nodes if isinstance(n, BufRead)]
        assert len(br) == 1
        assert br[0].interp == "linear"


# =========================================================================
# Error tests
# =========================================================================


class TestErrors:
    def test_syntax_error_unexpected_token(self):
        with pytest.raises(GDSPSyntaxError):
            parse("not_a_graph { }")

    def test_syntax_error_missing_brace(self):
        with pytest.raises(GDSPSyntaxError):
            parse("graph t {")

    def test_compile_error_undefined_function(self):
        with pytest.raises(GDSPCompileError, match="undefined function"):
            parse("""
            graph t {
                out o = y
                y = nonexistent_func(1)
            }
            """)

    def test_compile_error_feedback_undeclared(self):
        with pytest.raises(GDSPCompileError, match="undeclared history"):
            parse("""
            graph t {
                out o = x
                param x 0..1 = 0.5
                fb <- x
            }
            """)

    def test_compile_error_destructuring_count_mismatch(self):
        with pytest.raises(GDSPCompileError, match="targets but count"):
            parse("""
            graph t {
                in x
                out o = a
                param idx 0..3 = 1
                a, b = gate_route(x, idx, 3)
            }
            """)

    def test_compile_error_import_not_supported(self):
        with pytest.raises(GDSPCompileError, match="external imports"):
            parse("""
            graph t {
                in x
                out o = y
                y = import "file.gdsp":thing(input=x)
            }
            """)

    def test_error_has_line_info(self):
        try:
            parse("graph t {\n  $invalid\n}")
        except GDSPSyntaxError as e:
            assert e.line == 2

    def test_empty_source(self):
        with pytest.raises(GDSPSyntaxError, match="no graph definitions"):
            parse("")

    def test_compile_error_recursive_graph_name(self):
        """Graph name shadowing a builtin should raise, not infinite-recurse."""
        with pytest.raises(GDSPCompileError, match="recursive graph reference"):
            parse("""
            graph phasor {
                out output = ph
                param freq 1..20000 = 440
                ph = phasor(freq)
            }
            """)

    def test_compile_error_self_referencing_graph(self):
        """A graph calling itself by name should raise a compile error."""
        with pytest.raises(GDSPCompileError, match="recursive graph reference"):
            parse("""
            graph my_filter {
                in x
                out output = y
                y = my_filter(x=x)
            }
            """)


# =========================================================================
# Round-trip: parse -> validate
# =========================================================================


class TestRoundTrip:
    def test_gain_validates(self):
        from gen_dsp.graph.validate import validate_graph

        graph = parse("""
        graph gain {
            in input
            out output = scaled
            param g 0..1 = 0.5
            scaled = input * g
        }
        """)
        errors = validate_graph(graph)
        assert errors == [], f"Validation errors: {errors}"

    def test_osc_validates(self):
        from gen_dsp.graph.validate import validate_graph

        graph = parse("""
        graph osc {
            out output = s
            param freq 20..20000 = 440
            s = sinosc(freq)
        }
        """)
        errors = validate_graph(graph)
        assert errors == [], f"Validation errors: {errors}"

    def test_feedback_delay_validates(self):
        from gen_dsp.graph.validate import validate_graph

        graph = parse("""
        graph fbdelay (sr=48000) {
            in input
            out output = wet_mix

            param time    1..2000   = 500
            param feedback 0..0.99  = 0.6
            param tone     0..1     = 0.3
            param mix      0..1     = 0.5

            delay dly 96000

            time_samps = mstosamps(time)
            tap = delay_read dly (time_samps, interp=linear)
            fb_filtered = onepole(tap, tone)
            delay_write dly (input + fb_filtered * feedback)

            dry = input * (1 - mix)
            wet = tap * mix
            wet_mix = dry + wet
        }
        """)
        errors = validate_graph(graph)
        assert errors == [], f"Validation errors: {errors}"

    def test_fm_synth_example_validates(self):
        """Test the FM synth example from the spec."""
        from gen_dsp.graph.validate import validate_graph

        graph = parse("""
        graph fm_synth (sr=44100) {
            out output = result

            param freq  20..20000 = 440
            param depth 0..1000   = 200
            param gate  0..1      = 0

            buffer sine_tbl 512 fill=sine

            mod_phase = phasor(freq * 2.0)
            mod       = sin(mod_phase) * depth
            phase     = phasor(freq) + mod / sr
            carrier   = cycle(sine_tbl, phase)
            env       = adsr(gate, 10, 100, 0.7, 200)
            result    = carrier * env
        }
        """)
        errors = validate_graph(graph)
        assert errors == [], f"Validation errors: {errors}"


# =========================================================================
# parse_file tests
# =========================================================================


class TestParseFile:
    def test_parse_file_single(self, tmp_path):
        f = tmp_path / "test.gdsp"
        f.write_text("""
        graph gain {
            in input
            out output = scaled
            param g 0..1 = 0.5
            scaled = input * g
        }
        """)
        graph = parse_file(f)
        assert isinstance(graph, Graph)
        assert graph.name == "gain"

    def test_parse_file_multi(self, tmp_path):
        f = tmp_path / "multi.gdsp"
        f.write_text("""
        graph a { out o = x; param x 0..1 = 0 }
        graph b { out o = y; param y 0..1 = 0 }
        """)
        result = parse_file(f, multi=True)
        assert isinstance(result, dict)
        assert "a" in result
        assert "b" in result


# =========================================================================
# Full spec examples
# =========================================================================


class TestSpecExamples:
    def test_signal_router(self):
        graph = parse("""
        graph router {
            in input
            out out1 = clean
            out out2 = distorted
            out out3 = filtered

            param route 0..3 = 1

            a, b, c = gate_route(input, route, 3)

            clean     = a
            distorted = tanh(b * 3.0)
            filtered  = onepole(c, 0.2)
        }
        """)
        assert len(graph.inputs) == 1
        assert len(graph.outputs) == 3
        assert len(graph.params) == 1

    def test_poly_synth_with_subgraph(self):
        graph = parse("""
        graph voice {
            in gate_in
            out output = out_signal
            param freq 20..20000 = 440
            param attack 1..5000 = 10
            param release 1..5000 = 200
            env = adsr(gate_in, attack, 50, 0.8, release)
            osc = sawosc(freq)
            out_signal = osc * env
        }

        graph poly_synth {
            out output = mixed
            param freq1 20..20000 = 440
            param freq2 20..20000 = 550
            param gate  0..1      = 0
            v1 = voice(gate_in=gate, freq=freq1)
            v2 = voice(gate_in=gate, freq=freq2)
            mixed = (v1 + v2) * 0.5
        }
        """)
        assert graph.name == "poly_synth"
        sg = [n for n in graph.nodes if isinstance(n, Subgraph)]
        assert len(sg) == 2

    def test_history_onepole(self):
        """Test history-based one-pole filter pattern."""
        graph = parse("""
        graph manual_onepole {
            in input
            out output = y
            param coeff 0..0.999 = 0.5
            history fb = 0.0
            y = input * (1 - coeff) + fb * coeff
            fb <- y
        }
        """)
        hist = [n for n in graph.nodes if isinstance(n, History)]
        assert len(hist) == 1
        assert hist[0].id == "fb"
        # input should be set (not __pending__)
        assert hist[0].input != "__pending__"
