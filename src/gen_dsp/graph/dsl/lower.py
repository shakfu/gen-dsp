"""AST-to-Graph lowering (the GDSP compiler)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from gen_dsp.graph.algebra import parallel as _algebra_parallel
from gen_dsp.graph.algebra import series as _algebra_series
from gen_dsp.graph.dsl.lexer import GDSPCompileError
from gen_dsp.graph.dsl.parser import (
    ASTArg,
    ASTAssign,
    ASTBinExpr,
    ASTBufWriteStmt,
    ASTBufferDecl,
    ASTCall,
    ASTCompose,
    ASTDelayDecl,
    ASTDelayWriteStmt,
    ASTDotAccess,
    ASTExpr,
    ASTFeedbackWrite,
    ASTGraph,
    ASTHistoryDecl,
    ASTIdent,
    ASTImportAssign,
    ASTInDecl,
    ASTNumber,
    ASTOutDecl,
    ASTParamDecl,
    ASTStmt,
    ASTUnaryExpr,
)
from gen_dsp.graph.models import (
    SVF,
    ADSR,
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
    NamedConstant,
    Node,
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
    Smoothstep,
    SmoothParam,
    Splat,
    Subgraph,
    TriOsc,
    UnaryOp,
    Wave,
    Wrap,
)


# ---------------------------------------------------------------------------
# Compiler (AST -> Graph)
# ---------------------------------------------------------------------------

# Named constants that can appear as bare identifiers
_NAMED_CONSTANTS = {
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
}


# Unary ops (DSL name -> UnaryOp.op)
_UNARY_OPS = {
    "sin",
    "cos",
    "tan",
    "tanh",
    "sinh",
    "cosh",
    "asin",
    "acos",
    "atan",
    "asinh",
    "acosh",
    "atanh",
    "exp",
    "exp2",
    "log",
    "log2",
    "log10",
    "abs",
    "sqrt",
    "neg",
    "sign",
    "floor",
    "ceil",
    "round",
    "trunc",
    "fract",
    "not",
    "bool",
    "mtof",
    "ftom",
    "atodb",
    "dbtoa",
    "phasewrap",
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
}


# Binary ops via function call (DSL name -> BinOp.op)
_BINOP_FUNCS = {
    "min",
    "max",
    "atan2",
    "hypot",
    "absdiff",
    "step",
    "and",
    "or",
    "xor",
    "fastpow",
}


# Builtin registry: name -> (ModelClass, positional_field_names, fixed_kwargs)
_BUILTINS: dict[str, tuple[type, list[str], dict[str, str]]] = {
    "phasor": (Phasor, ["freq"], {}),
    "sinosc": (SinOsc, ["freq"], {}),
    "triosc": (TriOsc, ["freq"], {}),
    "sawosc": (SawOsc, ["freq"], {}),
    "pulseosc": (PulseOsc, ["freq", "width"], {}),
    "noise": (Noise, [], {}),
    "onepole": (OnePole, ["a", "coeff"], {}),
    "svf": (SVF, ["a", "freq", "q"], {}),
    "biquad": (Biquad, ["a", "b0", "b1", "b2", "a1", "a2"], {}),
    "dcblock": (DCBlock, ["a"], {}),
    "allpass": (Allpass, ["a", "coeff"], {}),
    "clamp": (Clamp, ["a", "lo", "hi"], {}),
    "wrap": (Wrap, ["a", "lo", "hi"], {}),
    "fold": (Fold, ["a", "lo", "hi"], {}),
    "scale": (Scale, ["a", "in_lo", "in_hi", "out_lo", "out_hi"], {}),
    "mix": (Mix, ["a", "b", "t"], {}),
    "smoothstep": (Smoothstep, ["a", "edge0", "edge1"], {}),
    "smooth": (SmoothParam, ["a", "coeff"], {}),
    "slide": (Slide, ["a", "up", "down"], {}),
    "adsr": (ADSR, ["gate", "attack", "decay", "sustain", "release"], {}),
    "select": (Select, ["cond", "a", "b"], {}),
    "delta": (Delta, ["a"], {}),
    "change": (Change, ["a"], {}),
    "sample_hold": (SampleHold, ["a", "trig"], {}),
    "latch": (Latch, ["a", "trig"], {}),
    "accum": (Accum, ["incr", "reset"], {}),
    "counter": (Counter, ["trig", "max"], {}),
    "elapsed": (Elapsed, [], {}),
    "rate_div": (RateDiv, ["a", "divisor"], {}),
    "pass": (Pass, ["a"], {}),
    "peek": (Peek, ["a"], {}),
    "samplerate": (SampleRate, [], {}),
    "cycle": (Cycle, ["buffer", "phase"], {}),
    "wave": (Wave, ["buffer", "phase"], {}),
    "lookup": (Lookup, ["buffer", "index"], {}),
    "buf_read": (BufRead, ["buffer", "index"], {}),
    "buf_size": (BufSize, ["buffer"], {}),
}


# Fields that take string buffer/delay references (not Ref)
_STR_REF_FIELDS = {"buffer", "delay", "gate"}


@dataclass
class _IDCounter:
    """Auto-incrementing ID generator."""

    counters: dict[str, int] = field(default_factory=dict)

    def next(self, prefix: str) -> str:
        n = self.counters.get(prefix, 0)
        self.counters[prefix] = n + 1
        return f"_{prefix}_{n}"


class Compiler:
    """Compiles a list of ASTGraph into Graph objects."""

    def __init__(self, ast_graphs: list[ASTGraph], filename: str = "<string>"):
        self.ast_graphs = ast_graphs
        self.filename = filename
        # Collect all graph names for deferred resolution
        self.graph_names: set[str] = {g.name for g in ast_graphs}
        self.compiled: dict[str, Graph] = {}
        # Track graphs currently being compiled to detect recursive calls
        self._compiling: set[str] = set()

    def compile_all(self) -> dict[str, Graph]:
        for ast_g in self.ast_graphs:
            self.compiled[ast_g.name] = self._compile_graph(ast_g)
        return self.compiled

    def _compile_graph(self, ast_g: ASTGraph) -> Graph:
        if ast_g.name in self._compiling:
            raise GDSPCompileError(
                f"recursive graph reference: '{ast_g.name}' cannot call itself",
                line=ast_g.line,
                filename=self.filename,
            )
        self._compiling.add(ast_g.name)
        try:
            return self._compile_graph_inner(ast_g)
        finally:
            self._compiling.discard(ast_g.name)

    def _compile_graph_inner(self, ast_g: ASTGraph) -> Graph:
        ctx = _GraphCtx(
            name=ast_g.name,
            options=ast_g.options,
            compiler=self,
            filename=self.filename,
        )

        # Implicit sr
        if "sr" in ast_g.options:
            ctx.nodes.append(SampleRate(id="sr"))
            ctx.defined_ids.add("sr")

        for stmt in ast_g.body:
            ctx.compile_stmt(stmt)

        sample_rate = float(ast_g.options.get("sr", 44100.0))
        control_interval = int(ast_g.options.get("control", 0))

        return Graph(
            name=ast_g.name,
            sample_rate=sample_rate,
            control_interval=control_interval,
            control_nodes=ctx.control_nodes,
            inputs=ctx.inputs,
            outputs=ctx.outputs,
            params=ctx.params,
            nodes=ctx.nodes,
        )


@dataclass
class _GraphCtx:
    """Compilation context for a single graph."""

    name: str
    options: dict[str, Union[str, float]]
    compiler: Compiler
    filename: str

    inputs: list[AudioInput] = field(default_factory=list)
    outputs: list[AudioOutput] = field(default_factory=list)
    params: list[Param] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    control_nodes: list[str] = field(default_factory=list)
    defined_ids: set[str] = field(default_factory=set)
    id_counter: _IDCounter = field(default_factory=_IDCounter)
    # Track history declarations for feedback write resolution
    histories: dict[str, int] = field(default_factory=dict)  # name -> node index

    def _err(self, msg: str, line: int = 0, col: int = 0) -> GDSPCompileError:
        return GDSPCompileError(msg, line=line, col=col, filename=self.filename)

    def _auto_id(self, prefix: str) -> str:
        return self.id_counter.next(prefix)

    def _add_node(self, node: Node) -> None:
        self.nodes.append(node)
        if hasattr(node, "id"):
            self.defined_ids.add(node.id)

    def compile_stmt(self, stmt: ASTStmt) -> None:
        if isinstance(stmt, ASTInDecl):
            for name in stmt.ids:
                self.inputs.append(AudioInput(id=name))
                self.defined_ids.add(name)

        elif isinstance(stmt, ASTOutDecl):
            source_ref = self._compile_expr(stmt.source)
            if isinstance(source_ref, (int, float)):
                # Wrap literal in a constant node
                cid = self._auto_id("const")
                self._add_node(Constant(id=cid, value=float(source_ref)))
                source_ref = cid
            self.outputs.append(AudioOutput(id=stmt.name, source=str(source_ref)))

        elif isinstance(stmt, ASTParamDecl):
            self.params.append(
                Param(
                    name=stmt.name,
                    min=stmt.min_val,
                    max=stmt.max_val,
                    default=max(stmt.min_val, min(stmt.max_val, stmt.default)),
                )
            )
            self.defined_ids.add(stmt.name)

        elif isinstance(stmt, ASTBufferDecl):
            self._add_node(
                Buffer(id=stmt.name, size=stmt.size, fill=stmt.fill)  # type: ignore[arg-type]
            )

        elif isinstance(stmt, ASTDelayDecl):
            self._add_node(DelayLine(id=stmt.name, max_samples=stmt.max_samples))

        elif isinstance(stmt, ASTHistoryDecl):
            # Add placeholder History node (input filled by feedback write)
            idx = len(self.nodes)
            self._add_node(History(id=stmt.name, init=stmt.init, input="__pending__"))
            self.histories[stmt.name] = idx

        elif isinstance(stmt, ASTFeedbackWrite):
            value_ref = self._compile_expr(stmt.value)
            if stmt.name not in self.histories:
                raise self._err(
                    f"feedback write to undeclared history '{stmt.name}'",
                    stmt.line,
                )
            idx = self.histories[stmt.name]
            old = self.nodes[idx]
            assert isinstance(old, History)
            self.nodes[idx] = History(
                id=old.id, init=old.init, input=str(self._ref_to_str(value_ref))
            )

        elif isinstance(stmt, ASTDelayWriteStmt):
            value_ref = self._compile_expr(stmt.value)
            dw_id = self._auto_id("dw")
            self._add_node(
                DelayWrite(
                    id=dw_id,
                    delay=stmt.delay,
                    value=self._to_ref(value_ref),
                )
            )

        elif isinstance(stmt, ASTBufWriteStmt):
            index_ref = self._compile_expr(stmt.index)
            value_ref = self._compile_expr(stmt.value)
            bw_id = self._auto_id("bw")
            cls = BufWrite if stmt.op == "buf_write" else Splat
            self._add_node(
                cls(
                    id=bw_id,
                    buffer=stmt.buffer,
                    index=self._to_ref(index_ref),
                    value=self._to_ref(value_ref),
                )
            )

        elif isinstance(stmt, ASTAssign):
            self._compile_assign(stmt)

        elif isinstance(stmt, ASTImportAssign):
            # The DSL grammar reserves `name = import "..."`, but cross-file
            # imports are intentionally not supported (no resolver/cycle
            # detection). Compose graphs via the Python API instead.
            raise self._err(
                "external imports are not supported; compose graphs via the "
                "Python API (algebra.series/parallel) instead",
                stmt.line,
            )

        else:
            raise self._err(
                f"unknown statement type: {type(stmt).__name__}",
                getattr(stmt, "line", 0),
                getattr(stmt, "col", 0),
            )

    def _compile_assign(self, stmt: ASTAssign) -> None:
        targets = stmt.targets

        # Check for gate_route destructuring
        if len(targets) > 1:
            if not isinstance(stmt.value, ASTCall):
                raise self._err(
                    "destructuring assignment requires a function call",
                    stmt.line,
                )
            if stmt.value.name != "gate_route":
                raise self._err(
                    f"destructuring only supported for gate_route, got '{stmt.value.name}'",
                    stmt.line,
                )
            self._compile_gate_route_destructure(targets, stmt.value, stmt)
            return

        target = targets[0]
        value_ref = self._compile_expr(stmt.value, target_id=target)
        # If the expression already produced a node with the target ID, we're done.
        if isinstance(value_ref, str) and value_ref == target:
            pass
        else:
            # Need to alias: create a Pass node or rename
            # Check if the last added node can be renamed
            if isinstance(value_ref, (int, float)):
                self._add_node(Constant(id=target, value=float(value_ref)))
            elif isinstance(value_ref, str) and value_ref != target:
                # If the expression was a simple reference, create a Pass node
                # But if it was the ID of a node we just created, try to rename
                if self._try_rename_last_node(value_ref, target):
                    pass
                else:
                    self._add_node(Pass(id=target, a=value_ref))

        if stmt.control:
            self.control_nodes.append(target)

    def _try_rename_last_node(self, old_id: str, new_id: str) -> bool:
        """Try to rename the last added node from old_id to new_id."""
        if not self.nodes:
            return False
        last = self.nodes[-1]
        if hasattr(last, "id") and last.id == old_id:
            # Reconstruct with new id
            data = last.model_dump()
            data["id"] = new_id
            self.defined_ids.discard(old_id)
            self.nodes[-1] = type(last)(**data)
            self.defined_ids.add(new_id)
            return True
        return False

    def _compile_gate_route_destructure(
        self,
        targets: list[str],
        call: ASTCall,
        stmt: ASTAssign,
    ) -> None:
        # Resolve args
        pos_args, kw_args = self._split_args(call.args)
        if len(pos_args) < 3:
            raise self._err(
                "gate_route requires 3 positional args: signal, index, count",
                stmt.line,
            )
        signal_ref = self._compile_expr(pos_args[0])
        index_ref = self._compile_expr(pos_args[1])
        count_expr = pos_args[2]
        if not isinstance(count_expr, ASTNumber):
            raise self._err("gate_route count must be a literal integer", stmt.line)
        count = int(count_expr.value)

        if len(targets) != count:
            raise self._err(
                f"gate_route destructuring: {len(targets)} targets but count={count}",
                stmt.line,
            )

        gate_id = self._auto_id("gate")
        self._add_node(
            GateRoute(
                id=gate_id,
                a=self._to_ref(signal_ref),
                index=self._to_ref(index_ref),
                count=count,
            )
        )

        for i, t in enumerate(targets):
            self._add_node(GateOut(id=t, gate=gate_id, channel=i + 1))

    def _compile_expr(self, expr: ASTExpr, target_id: str | None = None) -> str | float:
        """Compile an expression, returning a Ref (node ID or float literal).

        If target_id is provided, the outermost node gets that ID instead of
        an auto-generated one.
        """
        if isinstance(expr, ASTNumber):
            return expr.value

        if isinstance(expr, ASTIdent):
            name = expr.name
            # Named constants
            if name in _NAMED_CONSTANTS:
                nid = target_id or self._auto_id(name)
                self._add_node(NamedConstant(id=nid, op=name))  # type: ignore[arg-type]
                return nid
            # Otherwise it's a reference to an existing name
            return name

        if isinstance(expr, ASTBinExpr):
            left = self._compile_expr(expr.left)
            right = self._compile_expr(expr.right)
            nid = target_id or self._auto_id(expr.op)

            # Comparison ops -> Compare
            if expr.op in ("gt", "lt", "gte", "lte", "eq", "neq"):
                self._add_node(
                    Compare(
                        id=nid,
                        op=expr.op,  # type: ignore[arg-type]
                        a=self._to_ref(left),
                        b=self._to_ref(right),
                    )
                )
            else:
                self._add_node(
                    BinOp(
                        id=nid,
                        op=expr.op,  # type: ignore[arg-type]
                        a=self._to_ref(left),
                        b=self._to_ref(right),
                    )
                )
            return nid

        if isinstance(expr, ASTUnaryExpr):
            operand = self._compile_expr(expr.operand)
            nid = target_id or self._auto_id(expr.op)
            self._add_node(
                UnaryOp(
                    id=nid,
                    op=expr.op,  # type: ignore[arg-type]
                    a=self._to_ref(operand),
                )
            )
            return nid

        if isinstance(expr, ASTCall):
            return self._compile_call(expr, target_id)

        if isinstance(expr, ASTDotAccess):
            obj_ref = self._compile_expr(expr.obj)
            # Dot access on subgraph output: "subgraph_id.output_name"
            return f"{obj_ref}.{expr.field_name}"

        if isinstance(expr, ASTCompose):
            return self._compile_compose(expr, target_id)

        raise self._err(
            f"unknown expression type: {type(expr).__name__}",
            getattr(expr, "line", 0),
            getattr(expr, "col", 0),
        )

    def _compile_call(self, call: ASTCall, target_id: str | None = None) -> str | float:
        name = call.name
        line, col = call.line, call.col
        pos_args, kw_args = self._split_args(call.args)

        # Deferred resolution: check graph names first
        if name in self.compiler.graph_names:
            return self._compile_subgraph_call(
                name, pos_args, kw_args, target_id, line, col
            )

        # Unary ops
        if name in _UNARY_OPS:
            if len(pos_args) != 1:
                raise self._err(
                    f"'{name}' expects 1 argument, got {len(pos_args)}", line, col
                )
            a_ref = self._compile_expr(pos_args[0])
            nid = target_id or self._auto_id(name)
            self._add_node(
                UnaryOp(id=nid, op=name, a=self._to_ref(a_ref))  # type: ignore[arg-type]
            )
            return nid

        # Binary ops via function call
        if name in _BINOP_FUNCS:
            if len(pos_args) != 2:
                raise self._err(
                    f"'{name}' expects 2 arguments, got {len(pos_args)}", line, col
                )
            a_ref = self._compile_expr(pos_args[0])
            b_ref = self._compile_expr(pos_args[1])
            nid = target_id or self._auto_id(name)
            self._add_node(
                BinOp(
                    id=nid,
                    op=name,  # type: ignore[arg-type]
                    a=self._to_ref(a_ref),
                    b=self._to_ref(b_ref),
                )
            )
            return nid

        # gate_route (non-destructuring, standalone)
        if name == "gate_route":
            return self._compile_gate_route_call(
                pos_args, kw_args, target_id, line, col
            )

        # gate_out
        if name == "gate_out":
            if len(pos_args) != 2:
                raise self._err(
                    "gate_out expects 2 args: gate_node, channel", line, col
                )
            gate_ref = self._compile_expr(pos_args[0])
            ch_expr = pos_args[1]
            if not isinstance(ch_expr, ASTNumber):
                raise self._err("gate_out channel must be a literal integer", line, col)
            nid = target_id or self._auto_id("gate_out")
            self._add_node(
                GateOut(
                    id=nid,
                    gate=str(self._ref_to_str(gate_ref)),
                    channel=int(ch_expr.value),
                )
            )
            return nid

        # selector (variadic)
        if name == "selector":
            return self._compile_selector(pos_args, kw_args, target_id, line, col)

        # delay_read (special syntax already parsed with delay name injected)
        if name == "delay_read":
            return self._compile_delay_read(pos_args, kw_args, target_id, line, col)

        # Builtins registry
        if name in _BUILTINS:
            return self._compile_builtin(name, pos_args, kw_args, target_id)

        raise self._err(f"undefined function '{name}'", line, col)

    def _compile_subgraph_call(
        self,
        graph_name: str,
        pos_args: list[ASTExpr],
        kw_args: dict[str, ASTExpr],
        target_id: str | None = None,
        line: int = 0,
        col: int = 0,
    ) -> str:
        # Compile the referenced graph if not already done
        if graph_name not in self.compiler.compiled:
            # Find the AST and compile it
            ast_g = next(g for g in self.compiler.ast_graphs if g.name == graph_name)
            self.compiler.compiled[graph_name] = self.compiler._compile_graph(ast_g)
        sub_graph = self.compiler.compiled[graph_name]

        nid = target_id or self._auto_id(graph_name)

        # Map keyword args to inputs and params
        input_names = {inp.id for inp in sub_graph.inputs}
        param_names = {p.name for p in sub_graph.params}

        inputs_map: dict[str, str | float] = {}
        params_map: dict[str, str | float] = {}

        for k, v_expr in kw_args.items():
            v_ref = self._compile_expr(v_expr)
            if k in input_names:
                inputs_map[k] = self._to_ref(v_ref)
            elif k in param_names:
                params_map[k] = self._to_ref(v_ref)
            else:
                raise self._err(
                    f"subgraph '{graph_name}' has no input or param '{k}'", line, col
                )

        # Determine output (first output by default)
        output = sub_graph.outputs[0].id if sub_graph.outputs else ""

        self._add_node(
            Subgraph(
                id=nid,
                graph=sub_graph,
                inputs=inputs_map,
                params=params_map,
                output=output,
            )
        )
        return nid

    def _compile_gate_route_call(
        self,
        pos_args: list[ASTExpr],
        kw_args: dict[str, ASTExpr],
        target_id: str | None = None,
        line: int = 0,
        col: int = 0,
    ) -> str:
        if len(pos_args) < 3:
            raise self._err(
                "gate_route requires 3 positional args: signal, index, count", line, col
            )
        signal_ref = self._compile_expr(pos_args[0])
        index_ref = self._compile_expr(pos_args[1])
        count_expr = pos_args[2]
        if not isinstance(count_expr, ASTNumber):
            raise self._err("gate_route count must be a literal integer", line, col)
        nid = target_id or self._auto_id("gate")
        self._add_node(
            GateRoute(
                id=nid,
                a=self._to_ref(signal_ref),
                index=self._to_ref(index_ref),
                count=int(count_expr.value),
            )
        )
        return nid

    def _compile_selector(
        self,
        pos_args: list[ASTExpr],
        kw_args: dict[str, ASTExpr],
        target_id: str | None = None,
        line: int = 0,
        col: int = 0,
    ) -> str:
        if len(pos_args) < 2:
            raise self._err(
                "selector requires at least 2 args: index + inputs", line, col
            )

        # First arg is index, rest are inputs
        index_ref = self._compile_expr(pos_args[0])
        input_refs = [self._to_ref(self._compile_expr(a)) for a in pos_args[1:]]

        # Check for 'index' keyword arg
        if "index" in kw_args:
            index_ref = self._compile_expr(kw_args["index"])

        nid = target_id or self._auto_id("sel")
        self._add_node(
            Selector(
                id=nid,
                index=self._to_ref(index_ref),
                inputs=input_refs,
            )
        )
        return nid

    def _compile_delay_read(
        self,
        pos_args: list[ASTExpr],
        kw_args: dict[str, ASTExpr],
        target_id: str | None = None,
        line: int = 0,
        col: int = 0,
    ) -> str:
        # pos_args[0] is the delay name (injected by parser as ASTIdent)
        if len(pos_args) < 2:
            raise self._err(
                "delay_read requires delay name and tap position", line, col
            )
        delay_name_expr = pos_args[0]
        if not isinstance(delay_name_expr, ASTIdent):
            raise self._err("delay_read first arg must be delay line name", line, col)
        delay_name = delay_name_expr.name

        tap_ref = self._compile_expr(pos_args[1])

        interp = "none"
        if "interp" in kw_args:
            interp_expr = kw_args["interp"]
            if isinstance(interp_expr, ASTIdent):
                interp = interp_expr.name
            else:
                raise self._err("delay_read interp must be an identifier", line, col)

        nid = target_id or self._auto_id("dr")
        self._add_node(
            DelayRead(
                id=nid,
                delay=delay_name,
                tap=self._to_ref(tap_ref),
                interp=interp,  # type: ignore[arg-type]
            )
        )
        return nid

    def _compile_builtin(
        self,
        name: str,
        pos_args: list[ASTExpr],
        kw_args: dict[str, ASTExpr],
        target_id: str | None = None,
    ) -> str:
        cls, field_names, fixed_kw = _BUILTINS[name]
        nid = target_id or self._auto_id(name)

        kwargs: dict[str, object] = {"id": nid}
        kwargs.update(fixed_kw)

        # Map positional args
        for i, field_name in enumerate(field_names):
            if i < len(pos_args):
                val = self._compile_expr(pos_args[i])
                if field_name in _STR_REF_FIELDS:
                    kwargs[field_name] = str(self._ref_to_str(val))
                else:
                    kwargs[field_name] = self._to_ref(val)

        # Map keyword args
        for k, v_expr in kw_args.items():
            val = self._compile_expr(v_expr)
            if k in _STR_REF_FIELDS:
                kwargs[k] = str(self._ref_to_str(val))
            elif k == "interp" or k == "mode":
                # String-valued keyword
                if isinstance(v_expr, ASTIdent):
                    kwargs[k] = v_expr.name
                else:
                    kwargs[k] = str(self._ref_to_str(val))
            else:
                kwargs[k] = self._to_ref(val)

        self._add_node(cls(**kwargs))
        return nid

    def _compile_compose(self, expr: ASTCompose, target_id: str | None = None) -> str:
        """Compile >> (series) or // (parallel) composition."""
        left_graph = self._expr_to_graph(expr.left)
        right_graph = self._expr_to_graph(expr.right)

        if expr.op == ">>":
            result = _algebra_series(left_graph, right_graph)
        else:
            result = _algebra_parallel(left_graph, right_graph)

        nid = target_id or self._auto_id("comp")

        # Wrap result graph as a subgraph node
        # Wire outer inputs from calling graph namespace
        inputs_map: dict[str, str | float] = {}
        for inp in result.inputs:
            inputs_map[inp.id] = inp.id

        params_map: dict[str, str | float] = {}
        for p in result.params:
            params_map[p.name] = p.name

        output = result.outputs[0].id if result.outputs else ""

        self._add_node(
            Subgraph(
                id=nid,
                graph=result,
                inputs=inputs_map,
                params=params_map,
                output=output,
            )
        )
        return nid

    def _expr_to_graph(self, expr: ASTExpr) -> Graph:
        """Convert an expression to a Graph for composition.

        Handles: graph function calls (partially applied) and nested compositions.
        """
        if isinstance(expr, ASTCall):
            name = expr.name
            if name in self.compiler.graph_names:
                # Compile the graph
                if name not in self.compiler.compiled:
                    ast_g = next(g for g in self.compiler.ast_graphs if g.name == name)
                    self.compiler.compiled[name] = self.compiler._compile_graph(ast_g)
                sub_graph = self.compiler.compiled[name]

                # Apply keyword args as param overrides
                _, kw_args = self._split_args(expr.args)
                # For composition, we return the graph itself with param defaults
                # overridden. The algebra functions handle the wiring.
                if kw_args:
                    # Create a modified graph with adjusted param defaults
                    new_params = []
                    for p in sub_graph.params:
                        if p.name in kw_args:
                            kw_expr = kw_args[p.name]
                            val = self._compile_expr(kw_expr)
                            if isinstance(val, (int, float)):
                                new_params.append(
                                    Param(
                                        name=p.name,
                                        min=p.min,
                                        max=p.max,
                                        default=float(val),
                                    )
                                )
                            else:
                                new_params.append(p)
                        else:
                            new_params.append(p)
                    return Graph(
                        name=sub_graph.name,
                        sample_rate=sub_graph.sample_rate,
                        control_interval=sub_graph.control_interval,
                        control_nodes=sub_graph.control_nodes,
                        inputs=sub_graph.inputs,
                        outputs=sub_graph.outputs,
                        params=new_params,
                        nodes=sub_graph.nodes,
                    )
                return sub_graph
            raise self._err(
                f"'{name}' is not a graph (cannot compose)", expr.line, expr.col
            )

        if isinstance(expr, ASTCompose):
            left_graph = self._expr_to_graph(expr.left)
            right_graph = self._expr_to_graph(expr.right)
            if expr.op == ">>":
                return _algebra_series(left_graph, right_graph)
            return _algebra_parallel(left_graph, right_graph)

        if isinstance(expr, ASTIdent):
            name = expr.name
            if name in self.compiler.graph_names:
                if name not in self.compiler.compiled:
                    ast_g = next(g for g in self.compiler.ast_graphs if g.name == name)
                    self.compiler.compiled[name] = self.compiler._compile_graph(ast_g)
                return self.compiler.compiled[name]
            raise self._err(
                f"'{name}' is not a graph (cannot compose)", expr.line, expr.col
            )

        raise self._err(
            f"cannot use {type(expr).__name__} in composition expression",
            getattr(expr, "line", 0),
            getattr(expr, "col", 0),
        )

    def _split_args(
        self, args: list[ASTArg]
    ) -> tuple[list[ASTExpr], dict[str, ASTExpr]]:
        """Split argument list into positional and keyword args."""
        pos: list[ASTExpr] = []
        kw: dict[str, ASTExpr] = {}
        for arg in args:
            if arg.name is not None:
                kw[arg.name] = arg.value
            else:
                pos.append(arg.value)
        return pos, kw

    def _to_ref(self, val: str | float) -> str | float:
        """Convert compiler result to a Ref value."""
        return val

    def _ref_to_str(self, val: str | float) -> str:
        """Convert a ref to string (for fields that need str, not Ref)."""
        if isinstance(val, str):
            return val
        return str(val)
