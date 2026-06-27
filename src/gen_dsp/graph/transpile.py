"""Experimental .gdsp -> gen~ (GenExpr codebox) transpiler.

This module re-emits a DSP :class:`~gen_dsp.graph.models.Graph` as gen~ codebox
source (the GenExpr textual language) so a graph can be pasted into a gen~
``codebox`` object in Max/MSP. It serves two purposes:

1. Getting graphs into the Max ecosystem in an editable, version-controllable
   textual form.
2. Differential validation of gen-dsp's own C++ compiler against Cycling '74's
   reference operator implementations.

**Status: experimental.** It is intentionally NOT exported from
``gen_dsp.graph.__init__`` and has no CLI surface yet. Import it directly::

    from gen_dsp.graph.transpile import transpile_to_genexpr

Emission policy (hybrid, native-preferred)
------------------------------------------
Each node is emitted one of two ways:

* **native** -- a gen~ operator whose semantics provably match gen-dsp's C++
  implementation (e.g. ``clamp``, ``wrap``, ``scale``, ``mix``, ``mtof`` is
  spelled out, ``delta``, the comparison ops). Cleanest codebox and a genuine
  cross-implementation check.
* **faithful** -- the exact arithmetic from ``compile/nodes.py`` re-expressed in
  GenExpr (using ``History`` for single-sample state). Used where no native
  operator exists, or where the native operator's internals differ from ours
  (``change``, ``accum``, ``counter``, ``elapsed``). Output should match the C++
  path, so a differential mismatch indicates a real bug.

Coverage is incremental. Unsupported node types raise
:class:`GenExprUnsupportedError` rather than emitting wrong code.
"""

from __future__ import annotations

import re

from gen_dsp.core.identifiers import is_reserved_word
from gen_dsp.errors import GenExtError
from gen_dsp.graph.compile.common import _C_ID_RE
from gen_dsp.graph.compile.nodes import _NAMED_CONSTANT_VALUES
from gen_dsp.graph.models import (
    SVF,
    ADSR,
    Accum,
    Allpass,
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
    Node,
    Noise,
    OnePole,
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
    TriOsc,
    UnaryOp,
    Wave,
    Wrap,
)
from gen_dsp.graph.subgraph import expand_subgraphs
from gen_dsp.graph.toposort import toposort
from gen_dsp.graph.validate import validate_graph


class GenExprUnsupportedError(GenExtError):
    """A graph uses a node type the gen~ transpiler does not yet support."""


# Node ops emitted with a native gen~ operator whose output is nondeterministic
# (or otherwise not reproducible by the Python reference). These DO produce valid
# codeboxes for Max export, but they cannot be checked by the differential
# harness against simulate.py and must be excluded from any such comparison.
NON_DETERMINISTIC_OPS: frozenset[str] = frozenset({"noise"})


# ---------------------------------------------------------------------------
# Identifier safety
# ---------------------------------------------------------------------------

# GenExpr keywords and the operator names this transpiler emits. A graph ID that
# collides with one of these would shadow an operator in the codebox, so we
# reject it up front. ``in<N>`` / ``out<N>`` are handled by a separate regex.
_GENEXPR_RESERVED: frozenset[str] = frozenset(
    {
        # declaration keywords / globals
        "History",
        "Data",
        "Param",
        "Buffer",
        "Delay",
        "samplerate",
        "vectorsize",
        "in",
        "out",
        # buffer / data operators
        "peek",
        "poke",
        "dim",
        "channels",
        "sample",
        "nearest",
        "splat",
        # nondeterministic generators
        "noise",
        "random",
        "rand",
        # math / common operators we emit
        "min",
        "max",
        "mod",
        "pow",
        "atan2",
        "hypot",
        "abs",
        "sqrt",
        "sign",
        "fract",
        "trunc",
        "floor",
        "ceil",
        "round",
        "neg",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "asinh",
        "acosh",
        "atanh",
        "exp",
        "exp2",
        "log",
        "log2",
        "log10",
        "clamp",
        "clip",
        "wrap",
        "fold",
        "scale",
        "mix",
        "step",
        "switch",
        "delta",
        "change",
        "accum",
        "counter",
        "elapsed",
        "and",
        "or",
        "xor",
        "not",
        "bool",
        # comparison ops
        "gt",
        "lt",
        "gte",
        "lte",
        "eq",
        "neq",
        "gtp",
        "ltp",
        "gtep",
        "ltep",
        "eqp",
        "neqp",
        # named constants
        "pi",
        "e",
        "twopi",
        "halfpi",
        "degtorad",
        "radtodeg",
    }
)

_IO_NAME_RE = re.compile(r"^(in|out)\d+$")


# Comparison op -> native gen~ operator name (matches gen-dsp C++ semantics).
_COMPARE_OPS: dict[str, str] = {
    "gt": "gt",
    "lt": "lt",
    "gte": "gte",
    "lte": "lte",
    "eq": "eq",
    "neq": "neq",
}

# UnaryOp ops that are a direct single-argument gen~ function with identical
# semantics to the C library call gen-dsp emits.
_UNARY_DIRECT: dict[str, str] = {
    "sin": "sin",
    "cos": "cos",
    "tanh": "tanh",
    "exp": "exp",
    "log": "log",
    "abs": "abs",
    "sqrt": "sqrt",
    "floor": "floor",
    "ceil": "ceil",
    "round": "round",
    "atan": "atan",
    "asin": "asin",
    "acos": "acos",
    "tan": "tan",
    "sinh": "sinh",
    "cosh": "cosh",
    "asinh": "asinh",
    "acosh": "acosh",
    "atanh": "atanh",
    "exp2": "exp2",
    "log2": "log2",
    "log10": "log10",
    "trunc": "trunc",
}

# UnaryOp ops deferred to a later increment (bit-trick / approximation ops that
# cannot be faithfully expressed in GenExpr yet).
_UNARY_DEFERRED: frozenset[str] = frozenset(
    {"fastsin", "fastcos", "fasttan", "fastexp"}
)

# Named constants with a direct gen~ constant operator; others fall back to a
# numeric literal computed from _NAMED_CONSTANT_VALUES.
_NAMED_DIRECT: frozenset[str] = frozenset(
    {"pi", "e", "twopi", "halfpi", "degtorad", "radtodeg"}
)


def _gen_float_lit(v: float) -> str:
    """Format a float as a GenExpr numeric literal (no ``f`` suffix)."""
    return repr(float(v))


class _Ctx:
    """Accumulates declarations and body statements for one codebox."""

    def __init__(self, input_index: dict[str, int], param_names: set[str]) -> None:
        self.input_index = input_index
        self.param_names = param_names
        self.decls: list[str] = []  # History / Data declarations
        self.body: list[str] = []  # per-sample compute statements
        self.writebacks: list[str] = []  # explicit History store-for-next lines

    def ref(self, r: str | float) -> str:
        """Render a Ref (node id, input id, param name, or literal) in GenExpr."""
        if isinstance(r, bool):  # guard: bool is a subclass of int
            return _gen_float_lit(float(r))
        if isinstance(r, (int, float)):
            return _gen_float_lit(float(r))
        if r in self.input_index:
            return f"in{self.input_index[r]}"
        # param names and node ids are usable as plain variables in GenExpr
        return r

    def emit(self, line: str) -> None:
        self.body.append(line)

    def history(self, name: str, init: float) -> None:
        self.decls.append(f"History {name}({_gen_float_lit(init)});")

    def data(self, name: str, size: int) -> None:
        self.decls.append(f"Data {name}({size});")


# ---------------------------------------------------------------------------
# Per-node emission
# ---------------------------------------------------------------------------


def _emit_binop(node: BinOp, ctx: _Ctx) -> None:
    a, b = ctx.ref(node.a), ctx.ref(node.b)
    nid = node.id
    op = node.op
    if op == "add":
        ctx.emit(f"{nid} = {a} + {b};")
    elif op == "sub":
        ctx.emit(f"{nid} = {a} - {b};")
    elif op == "mul":
        ctx.emit(f"{nid} = {a} * {b};")
    elif op == "div":
        ctx.emit(f"{nid} = {a} / {b};")
    elif op == "min":
        ctx.emit(f"{nid} = min({a}, {b});")
    elif op == "max":
        ctx.emit(f"{nid} = max({a}, {b});")
    elif op == "mod":
        ctx.emit(f"{nid} = {a} % {b};")
    elif op == "pow":
        ctx.emit(f"{nid} = pow({a}, {b});")
    elif op == "atan2":
        ctx.emit(f"{nid} = atan2({a}, {b});")
    elif op == "hypot":
        ctx.emit(f"{nid} = hypot({a}, {b});")
    elif op == "absdiff":
        ctx.emit(f"{nid} = abs({a} - {b});")
    elif op == "step":
        ctx.emit(f"{nid} = step({a}, {b});")
    elif op == "and":
        ctx.emit(f"{nid} = ({a} != 0 && {b} != 0);")
    elif op == "or":
        ctx.emit(f"{nid} = ({a} != 0 || {b} != 0);")
    elif op == "xor":
        ctx.emit(f"{nid} = (({a} != 0) != ({b} != 0));")
    elif op == "rsub":
        ctx.emit(f"{nid} = {b} - {a};")
    elif op == "rdiv":
        ctx.emit(f"{nid} = {b} / {a};")
    elif op == "rmod":
        ctx.emit(f"{nid} = {b} % {a};")
    elif op in ("gtp", "ltp", "gtep", "ltep", "eqp", "neqp"):
        ctx.emit(f"{nid} = {op}({a}, {b});")
    elif op == "fastpow":
        ctx.emit(f"{nid} = exp2({b} * log2({a}));")
    else:  # pragma: no cover - exhaustive over the BinOp literal
        raise GenExprUnsupportedError(f"BinOp '{op}' not supported")


def _emit_unaryop(node: UnaryOp, ctx: _Ctx) -> None:
    a = ctx.ref(node.a)
    nid = node.id
    op = node.op
    if op in _UNARY_DEFERRED:
        raise GenExprUnsupportedError(
            f"UnaryOp '{op}' (approximation/bit-trick op) is not yet supported "
            "by the gen~ transpiler"
        )
    if op in _UNARY_DIRECT:
        ctx.emit(f"{nid} = {_UNARY_DIRECT[op]}({a});")
    elif op == "neg":
        ctx.emit(f"{nid} = -{a};")
    elif op == "sign":
        ctx.emit(f"{nid} = ({a} > 0 ? 1 : ({a} < 0 ? -1 : 0));")
    elif op == "fract":
        ctx.emit(f"{nid} = {a} - floor({a});")
    elif op == "not":
        ctx.emit(f"{nid} = ({a} == 0);")
    elif op == "bool":
        ctx.emit(f"{nid} = ({a} != 0);")
    elif op == "mtof":
        ctx.emit(f"{nid} = 440 * pow(2, ({a} - 69) / 12);")
    elif op == "ftom":
        ctx.emit(f"{nid} = 69 + 12 * log2(max({a}, 1e-10) / 440);")
    elif op == "atodb":
        ctx.emit(f"{nid} = 20 * log10(max({a}, 1e-10));")
    elif op == "dbtoa":
        ctx.emit(f"{nid} = pow(10, {a} / 20);")
    elif op == "phasewrap":
        ctx.emit(f"{nid} = {a} - 6.28318530 * floor({a} * 0.15915494 + 0.5);")
    elif op == "degrees":
        ctx.emit(f"{nid} = {a} * 57.29577951;")
    elif op == "radians":
        ctx.emit(f"{nid} = {a} * 0.01745329;")
    elif op == "mstosamps":
        ctx.emit(f"{nid} = {a} * samplerate / 1000;")
    elif op == "sampstoms":
        ctx.emit(f"{nid} = {a} * 1000 / samplerate;")
    elif op == "t60":
        ctx.emit(f"{nid} = exp(-6.9078 / ({a} * samplerate));")
    elif op == "t60time":
        ctx.emit(f"{nid} = -6.9078 / (log({a}) * samplerate);")
    elif op == "fixdenorm":
        ctx.emit(f"{nid} = (abs({a}) < 1e-18 ? 0 : {a});")
    elif op == "fixnan":
        ctx.emit(f"{nid} = ({a} != {a} ? 0 : {a});")
    elif op == "isdenorm":
        ctx.emit(f"{nid} = ((abs({a}) < 1e-18 && {a} != 0) ? 1 : 0);")
    elif op == "isnan":
        ctx.emit(f"{nid} = ({a} != {a} ? 1 : 0);")
    else:  # pragma: no cover - exhaustive over the UnaryOp literal
        raise GenExprUnsupportedError(f"UnaryOp '{op}' not supported")


def _emit_node(node: Node, ctx: _Ctx) -> None:
    nid = node.id

    if isinstance(node, Constant):
        ctx.emit(f"{nid} = {_gen_float_lit(node.value)};")

    elif isinstance(node, Pass):
        ctx.emit(f"{nid} = {ctx.ref(node.a)};")

    elif isinstance(node, SampleRate):
        ctx.emit(f"{nid} = samplerate;")

    elif isinstance(node, NamedConstant):
        if node.op in _NAMED_DIRECT:
            ctx.emit(f"{nid} = {node.op};")
        else:
            ctx.emit(f"{nid} = {_gen_float_lit(_NAMED_CONSTANT_VALUES[node.op])};")

    elif isinstance(node, BinOp):
        _emit_binop(node, ctx)

    elif isinstance(node, UnaryOp):
        _emit_unaryop(node, ctx)

    elif isinstance(node, Compare):
        gen_op = _COMPARE_OPS[node.op]
        ctx.emit(f"{nid} = {gen_op}({ctx.ref(node.a)}, {ctx.ref(node.b)});")

    elif isinstance(node, Select):
        cond, a, b = ctx.ref(node.cond), ctx.ref(node.a), ctx.ref(node.b)
        ctx.emit(f"{nid} = ({cond} > 0 ? {a} : {b});")

    elif isinstance(node, Clamp):
        a, lo, hi = ctx.ref(node.a), ctx.ref(node.lo), ctx.ref(node.hi)
        ctx.emit(f"{nid} = clamp({a}, {lo}, {hi});")

    elif isinstance(node, Wrap):
        a, lo, hi = ctx.ref(node.a), ctx.ref(node.lo), ctx.ref(node.hi)
        ctx.emit(f"{nid} = wrap({a}, {lo}, {hi});")

    elif isinstance(node, Fold):
        a, lo, hi = ctx.ref(node.a), ctx.ref(node.lo), ctx.ref(node.hi)
        ctx.emit(f"{nid} = fold({a}, {lo}, {hi});")

    elif isinstance(node, Scale):
        a = ctx.ref(node.a)
        in_lo, in_hi = ctx.ref(node.in_lo), ctx.ref(node.in_hi)
        out_lo, out_hi = ctx.ref(node.out_lo), ctx.ref(node.out_hi)
        ctx.emit(f"{nid} = scale({a}, {in_lo}, {in_hi}, {out_lo}, {out_hi});")

    elif isinstance(node, Mix):
        a, b, t = ctx.ref(node.a), ctx.ref(node.b), ctx.ref(node.t)
        ctx.emit(f"{nid} = mix({a}, {b}, {t});")

    elif isinstance(node, Smoothstep):
        a = ctx.ref(node.a)
        e0, e1 = ctx.ref(node.edge0), ctx.ref(node.edge1)
        ctx.emit(f"{nid}_t = clamp(({a} - {e0}) / ({e1} - {e0}), 0, 1);")
        ctx.emit(f"{nid} = {nid}_t * {nid}_t * (3 - 2 * {nid}_t);")

    elif isinstance(node, History):
        # Reading the History name yields the previous sample's stored value, so
        # the node itself needs no compute line; only the store-for-next-sample.
        ctx.history(nid, node.init)
        ctx.writebacks.append(f"{nid} = {ctx.ref(node.input)};")

    elif isinstance(node, Delta):
        # gen~ `delta` matches gen-dsp's cur - prev semantics exactly.
        ctx.emit(f"{nid} = delta({ctx.ref(node.a)});")

    elif isinstance(node, Change):
        # gen~ `change` returns the SIGN of the difference; gen-dsp's Change is a
        # did-it-change boolean. Emit faithfully via History.
        a = ctx.ref(node.a)
        ctx.history(f"{nid}_prev", 0.0)
        ctx.emit(f"{nid} = ({a} != {nid}_prev ? 1 : 0);")
        ctx.emit(f"{nid}_prev = {a};")

    elif isinstance(node, Accum):
        incr, reset = ctx.ref(node.incr), ctx.ref(node.reset)
        ctx.history(f"{nid}_sum", 0.0)
        ctx.emit(f"{nid}_s = ({reset} > 0 ? 0 : {nid}_sum);")
        ctx.emit(f"{nid}_s = {nid}_s + {incr};")
        ctx.emit(f"{nid} = {nid}_s;")
        ctx.emit(f"{nid}_sum = {nid}_s;")

    elif isinstance(node, Counter):
        trig, mx = ctx.ref(node.trig), ctx.ref(node.max)
        ctx.history(f"{nid}_count", 0.0)
        ctx.history(f"{nid}_ptrig", 0.0)
        ctx.emit(f"{nid}_t = {trig};")
        ctx.emit(f"{nid}_inc = {nid}_count + 1;")
        ctx.emit(f"{nid}_inc = ({nid}_inc >= trunc({mx}) ? 0 : {nid}_inc);")
        ctx.emit(f"{nid}_rise = ({nid}_ptrig <= 0 && {nid}_t > 0 ? 1 : 0);")
        ctx.emit(f"{nid} = ({nid}_rise > 0 ? {nid}_inc : {nid}_count);")
        ctx.emit(f"{nid}_count = {nid};")
        ctx.emit(f"{nid}_ptrig = {nid}_t;")

    elif isinstance(node, Elapsed):
        ctx.history(f"{nid}_count", 0.0)
        ctx.emit(f"{nid} = {nid}_count;")
        ctx.emit(f"{nid}_count = {nid}_count + 1;")

    # -- Oscillators (faithful: own phase accumulator via History) ----------
    elif isinstance(node, Phasor):
        ctx.history(f"{nid}_phase", 0.0)
        ctx.emit(f"{nid} = {nid}_phase;")
        _emit_phase_step(ctx, nid, ctx.ref(node.freq))

    elif isinstance(node, SinOsc):
        ctx.history(f"{nid}_phase", 0.0)
        ctx.emit(f"{nid} = sin(6.28318530 * {nid}_phase);")
        _emit_phase_step(ctx, nid, ctx.ref(node.freq))

    elif isinstance(node, TriOsc):
        ctx.history(f"{nid}_phase", 0.0)
        ctx.emit(f"{nid} = 4 * abs({nid}_phase - 0.5) - 1;")
        _emit_phase_step(ctx, nid, ctx.ref(node.freq))

    elif isinstance(node, SawOsc):
        ctx.history(f"{nid}_phase", 0.0)
        ctx.emit(f"{nid} = 2 * {nid}_phase - 1;")
        _emit_phase_step(ctx, nid, ctx.ref(node.freq))

    elif isinstance(node, PulseOsc):
        ctx.history(f"{nid}_phase", 0.0)
        ctx.emit(f"{nid} = ({nid}_phase < {ctx.ref(node.width)} ? 1 : -1);")
        _emit_phase_step(ctx, nid, ctx.ref(node.freq))

    elif isinstance(node, Noise):
        # gen~'s native white-noise generator. gen-dsp's Noise is a specific LCG
        # whose exact sequence is not reproducible in GenExpr, and noise() is
        # nondeterministic anyway, so this is emitted for Max export only and is
        # excluded from the differential harness (see NON_DETERMINISTIC_OPS).
        ctx.emit(f"{nid} = noise();")

    # -- Filters ------------------------------------------------------------
    elif isinstance(node, OnePole):
        a, c = ctx.ref(node.a), ctx.ref(node.coeff)
        ctx.history(f"{nid}_prev", 0.0)
        ctx.emit(f"{nid} = {c} * {a} + (1 - {c}) * {nid}_prev;")
        ctx.emit(f"{nid}_prev = {nid};")

    elif isinstance(node, DCBlock):
        a = ctx.ref(node.a)
        ctx.history(f"{nid}_xprev", 0.0)
        ctx.history(f"{nid}_yprev", 0.0)
        ctx.emit(f"{nid}_x = {a};")
        ctx.emit(f"{nid} = {nid}_x - {nid}_xprev + 0.995 * {nid}_yprev;")
        ctx.emit(f"{nid}_xprev = {nid}_x;")
        ctx.emit(f"{nid}_yprev = {nid};")

    elif isinstance(node, Allpass):
        a, c = ctx.ref(node.a), ctx.ref(node.coeff)
        ctx.history(f"{nid}_xprev", 0.0)
        ctx.history(f"{nid}_yprev", 0.0)
        ctx.emit(f"{nid}_x = {a};")
        ctx.emit(f"{nid} = {c} * ({nid}_x - {nid}_yprev) + {nid}_xprev;")
        ctx.emit(f"{nid}_xprev = {nid}_x;")
        ctx.emit(f"{nid}_yprev = {nid};")

    elif isinstance(node, Biquad):
        a = ctx.ref(node.a)
        b0, b1, b2 = ctx.ref(node.b0), ctx.ref(node.b1), ctx.ref(node.b2)
        a1, a2 = ctx.ref(node.a1), ctx.ref(node.a2)
        ctx.history(f"{nid}_s1", 0.0)
        ctx.history(f"{nid}_s2", 0.0)
        ctx.emit(f"{nid}_x = {a};")
        ctx.emit(f"{nid} = {b0} * {nid}_x + {nid}_s1;")
        ctx.emit(f"{nid}_ns1 = {b1} * {nid}_x - {a1} * {nid} + {nid}_s2;")
        ctx.emit(f"{nid}_ns2 = {b2} * {nid}_x - {a2} * {nid};")
        ctx.emit(f"{nid}_s1 = {nid}_ns1;")
        ctx.emit(f"{nid}_s2 = {nid}_ns2;")

    elif isinstance(node, SVF):
        _emit_svf(node, ctx)

    # -- State / timing -----------------------------------------------------
    elif isinstance(node, SampleHold):
        a, t = ctx.ref(node.a), ctx.ref(node.trig)
        ctx.history(f"{nid}_held", 0.0)
        ctx.history(f"{nid}_ptrig", 0.0)
        ctx.emit(f"{nid}_t = {t};")
        ctx.emit(
            f"{nid}_fire = (({nid}_ptrig <= 0 && {nid}_t > 0) || "
            f"({nid}_ptrig > 0 && {nid}_t <= 0) ? 1 : 0);"
        )
        ctx.emit(f"{nid}_h = ({nid}_fire > 0 ? {a} : {nid}_held);")
        ctx.emit(f"{nid} = {nid}_h;")
        ctx.emit(f"{nid}_held = {nid}_h;")
        ctx.emit(f"{nid}_ptrig = {nid}_t;")

    elif isinstance(node, Latch):
        a, t = ctx.ref(node.a), ctx.ref(node.trig)
        ctx.history(f"{nid}_held", 0.0)
        ctx.history(f"{nid}_ptrig", 0.0)
        ctx.emit(f"{nid}_t = {t};")
        ctx.emit(f"{nid}_fire = ({nid}_ptrig <= 0 && {nid}_t > 0 ? 1 : 0);")
        ctx.emit(f"{nid}_h = ({nid}_fire > 0 ? {a} : {nid}_held);")
        ctx.emit(f"{nid} = {nid}_h;")
        ctx.emit(f"{nid}_held = {nid}_h;")
        ctx.emit(f"{nid}_ptrig = {nid}_t;")

    elif isinstance(node, MulAccum):
        incr, reset = ctx.ref(node.incr), ctx.ref(node.reset)
        ctx.history(f"{nid}_prod", 1.0)
        ctx.emit(f"{nid}_p = ({reset} > 0 ? 1 : {nid}_prod);")
        ctx.emit(f"{nid}_p = {nid}_p * {incr};")
        ctx.emit(f"{nid} = {nid}_p;")
        ctx.emit(f"{nid}_prod = {nid}_p;")

    elif isinstance(node, RateDiv):
        a, divisor = ctx.ref(node.a), ctx.ref(node.divisor)
        ctx.history(f"{nid}_count", 0.0)
        ctx.history(f"{nid}_held", 0.0)
        ctx.emit(f"{nid}_h = ({nid}_count == 0 ? {a} : {nid}_held);")
        ctx.emit(f"{nid}_c = {nid}_count + 1;")
        ctx.emit(f"{nid}_c = ({nid}_c >= trunc({divisor}) ? 0 : {nid}_c);")
        ctx.emit(f"{nid} = {nid}_h;")
        ctx.emit(f"{nid}_held = {nid}_h;")
        ctx.emit(f"{nid}_count = {nid}_c;")

    elif isinstance(node, SmoothParam):
        a, c = ctx.ref(node.a), ctx.ref(node.coeff)
        ctx.history(f"{nid}_prev", 0.0)
        ctx.emit(f"{nid} = (1 - {c}) * {a} + {c} * {nid}_prev;")
        ctx.emit(f"{nid}_prev = {nid};")

    elif isinstance(node, Slide):
        a, up, down = ctx.ref(node.a), ctx.ref(node.up), ctx.ref(node.down)
        ctx.history(f"{nid}_prev", 0.0)
        ctx.emit(f"{nid}_x = {a};")
        ctx.emit(f"{nid}_s = ({nid}_x > {nid}_prev ? {up} : {down});")
        ctx.emit(f"{nid}_s = ({nid}_s > 1 ? {nid}_s : 1);")
        ctx.emit(f"{nid} = {nid}_prev + ({nid}_x - {nid}_prev) / {nid}_s;")
        ctx.emit(f"{nid}_prev = {nid};")

    elif isinstance(node, ADSR):
        _emit_adsr(node, ctx)

    elif isinstance(node, Peek):
        # gen-dsp's Peek captures a value for host introspection and passes it
        # through. A codebox has no such introspection, so emit the pass-through.
        ctx.emit(f"{nid} = {ctx.ref(node.a)};")

    # -- Delay lines (ring buffer: Data + History write pointer) ------------
    elif isinstance(node, DelayLine):
        ctx.data(nid, node.max_samples)
        ctx.history(f"{nid}_wr", 0.0)

    elif isinstance(node, DelayRead):
        _emit_delay_read(node, ctx)

    elif isinstance(node, DelayWrite):
        dl, val = node.delay, ctx.ref(node.value)
        ctx.emit(f"poke({dl}, {val}, {dl}_wr);")
        ctx.emit(f"{nid}_wrnext = {dl}_wr + 1;")
        ctx.emit(
            f"{nid}_wrnext = ({nid}_wrnext >= dim({dl}) "
            f"? {nid}_wrnext - dim({dl}) : {nid}_wrnext);"
        )
        ctx.emit(f"{dl}_wr = {nid}_wrnext;")

    # -- Buffers / tables (Data + peek/poke/dim) ----------------------------
    elif isinstance(node, Buffer):
        if node.fill == "sine":
            raise GenExprUnsupportedError(
                "Buffer fill='sine' cannot be statically initialized in a gen~ "
                "codebox; use fill='zeros' and fill at runtime or via the host"
            )
        ctx.data(nid, node.size)

    elif isinstance(node, BufRead):
        _emit_buf_read(node, ctx)

    elif isinstance(node, BufWrite):
        buf, idx, val = node.buffer, ctx.ref(node.index), ctx.ref(node.value)
        ctx.emit(f"{nid}_i = trunc({idx});")
        ctx.emit(f"poke({buf}, {val}, {nid}_i);")

    elif isinstance(node, Splat):
        buf, idx, val = node.buffer, ctx.ref(node.index), ctx.ref(node.value)
        ctx.emit(f"{nid}_i = trunc({idx});")
        ctx.emit(f"poke({buf}, peek({buf}, {nid}_i) + {val}, {nid}_i);")

    elif isinstance(node, BufSize):
        ctx.emit(f"{nid} = dim({node.buffer});")

    elif isinstance(node, Cycle):
        buf, phase = node.buffer, ctx.ref(node.phase)
        ctx.emit(f"{nid}_ph = {phase};")
        ctx.emit(f"{nid}_p = {nid}_ph - floor({nid}_ph);")
        ctx.emit(f"{nid}_n = dim({buf});")
        ctx.emit(f"{nid}_fidx = {nid}_p * {nid}_n;")
        ctx.emit(f"{nid}_t0 = trunc({nid}_fidx);")
        ctx.emit(f"{nid}_i0 = {nid}_t0 - {nid}_n * floor({nid}_t0 / {nid}_n);")
        ctx.emit(f"{nid}_frac = {nid}_fidx - floor({nid}_fidx);")
        ctx.emit(
            f"{nid}_i1 = ({nid}_i0 + 1) - {nid}_n * floor(({nid}_i0 + 1) / {nid}_n);"
        )
        ctx.emit(f"{nid}_y0 = peek({buf}, {nid}_i0);")
        ctx.emit(f"{nid}_y1 = peek({buf}, {nid}_i1);")
        ctx.emit(f"{nid} = {nid}_y0 + {nid}_frac * ({nid}_y1 - {nid}_y0);")

    elif isinstance(node, Wave):
        buf, phase = node.buffer, ctx.ref(node.phase)
        ctx.emit(f"{nid}_n = dim({buf});")
        ctx.emit(f"{nid}_fidx = ({phase} + 1) * 0.5 * ({nid}_n - 1);")
        ctx.emit(f"{nid}_fidx = max(0, min({nid}_fidx, {nid}_n - 1));")
        ctx.emit(f"{nid}_i0 = trunc({nid}_fidx);")
        ctx.emit(f"{nid}_frac = {nid}_fidx - {nid}_i0;")
        ctx.emit(f"{nid}_i1 = min({nid}_i0 + 1, {nid}_n - 1);")
        ctx.emit(f"{nid}_y0 = peek({buf}, {nid}_i0);")
        ctx.emit(f"{nid}_y1 = peek({buf}, {nid}_i1);")
        ctx.emit(f"{nid} = {nid}_y0 + {nid}_frac * ({nid}_y1 - {nid}_y0);")

    elif isinstance(node, Lookup):
        buf, idx = node.buffer, ctx.ref(node.index)
        ctx.emit(f"{nid}_n = dim({buf});")
        ctx.emit(f"{nid}_ci = max(0, min({idx}, 1));")
        ctx.emit(f"{nid}_fidx = {nid}_ci * ({nid}_n - 1);")
        ctx.emit(f"{nid}_i0 = trunc({nid}_fidx);")
        ctx.emit(f"{nid}_frac = {nid}_fidx - {nid}_i0;")
        ctx.emit(f"{nid}_i1 = min({nid}_i0 + 1, {nid}_n - 1);")
        ctx.emit(f"{nid}_y0 = peek({buf}, {nid}_i0);")
        ctx.emit(f"{nid}_y1 = peek({buf}, {nid}_i1);")
        ctx.emit(f"{nid} = {nid}_y0 + {nid}_frac * ({nid}_y1 - {nid}_y0);")

    # -- Routing ------------------------------------------------------------
    elif isinstance(node, GateRoute):
        idx, a = ctx.ref(node.index), ctx.ref(node.a)
        ctx.emit(f"{nid}_idx = trunc({idx});")
        ctx.emit(f"{nid}_idx = max(0, min({nid}_idx, {node.count}));")
        ctx.emit(f"{nid}_val = {a};")

    elif isinstance(node, GateOut):
        g = node.gate
        ctx.emit(f"{nid} = ({g}_idx == {node.channel} ? {g}_val : 0);")

    elif isinstance(node, Selector):
        idx = ctx.ref(node.index)
        n = len(node.inputs)
        ctx.emit(f"{nid}_idx = trunc({idx});")
        ctx.emit(f"{nid}_idx = max(0, min({nid}_idx, {n}));")
        expr = "0"
        for i in range(n, 0, -1):
            expr = f"({nid}_idx == {i} ? {ctx.ref(node.inputs[i - 1])} : {expr})"
        ctx.emit(f"{nid} = {expr};")

    else:
        raise GenExprUnsupportedError(
            f"node type '{type(node).__name__}' (op '{getattr(node, 'op', '?')}') "
            "is not yet supported by the gen~ transpiler"
        )


def _emit_phase_step(ctx: _Ctx, nid: str, freq: str) -> None:
    """Advance a phase History by freq/samplerate with a single wrap."""
    ctx.emit(f"{nid}_p = {nid}_phase + {freq} / samplerate;")
    ctx.emit(f"{nid}_p = ({nid}_p >= 1 ? {nid}_p - 1 : {nid}_p);")
    ctx.emit(f"{nid}_phase = {nid}_p;")


def _emit_svf(node: SVF, ctx: _Ctx) -> None:
    nid = node.id
    a, freq, q = ctx.ref(node.a), ctx.ref(node.freq), ctx.ref(node.q)
    ctx.history(f"{nid}_s1", 0.0)
    ctx.history(f"{nid}_s2", 0.0)
    ctx.emit(f"{nid}_x = {a};")
    ctx.emit(f"{nid}_g = tan(3.14159265 * {freq} / samplerate);")
    ctx.emit(f"{nid}_k = 1 / {q};")
    ctx.emit(f"{nid}_a1 = 1 / (1 + {nid}_g * ({nid}_g + {nid}_k));")
    ctx.emit(f"{nid}_a2 = {nid}_g * {nid}_a1;")
    ctx.emit(f"{nid}_a3 = {nid}_g * {nid}_a2;")
    ctx.emit(f"{nid}_v3 = {nid}_x - {nid}_s2;")
    ctx.emit(f"{nid}_v1 = {nid}_a1 * {nid}_s1 + {nid}_a2 * {nid}_v3;")
    ctx.emit(f"{nid}_v2 = {nid}_s2 + {nid}_a2 * {nid}_s1 + {nid}_a3 * {nid}_v3;")
    ctx.emit(f"{nid}_ns1 = 2 * {nid}_v1 - {nid}_s1;")
    ctx.emit(f"{nid}_ns2 = 2 * {nid}_v2 - {nid}_s2;")
    ctx.emit(f"{nid}_s1 = {nid}_ns1;")
    ctx.emit(f"{nid}_s2 = {nid}_ns2;")
    if node.mode == "lp":
        ctx.emit(f"{nid} = {nid}_v2;")
    elif node.mode == "hp":
        ctx.emit(f"{nid} = {nid}_x - {nid}_k * {nid}_v1 - {nid}_v2;")
    elif node.mode == "bp":
        ctx.emit(f"{nid} = {nid}_v1;")
    else:  # notch
        ctx.emit(f"{nid} = {nid}_x - {nid}_k * {nid}_v1;")


def _emit_adsr(node: ADSR, ctx: _Ctx) -> None:
    """Mirror simulate.py's sequential-cascade ADSR using temps + History."""
    nid = node.id
    gate = ctx.ref(node.gate)
    attack, decay = ctx.ref(node.attack), ctx.ref(node.decay)
    sustain, release = ctx.ref(node.sustain), ctx.ref(node.release)
    ctx.history(f"{nid}_phase", 0.0)
    ctx.history(f"{nid}_output", 0.0)
    ctx.history(f"{nid}_ptrig", 0.0)
    ctx.emit(f"{nid}_g = {gate};")
    ctx.emit(f"{nid}_ph = ({nid}_g > 0 && {nid}_ptrig <= 0 ? 1 : {nid}_phase);")
    ctx.emit(f"{nid}_ph = ({nid}_g <= 0 && {nid}_ptrig > 0 ? 4 : {nid}_ph);")
    ctx.emit(f"{nid}_out = {nid}_output;")
    # attack
    ctx.emit(f"{nid}_asamps = max({attack} * samplerate * 0.001, 1);")
    ctx.emit(f"{nid}_out = ({nid}_ph == 1 ? {nid}_out + 1 / {nid}_asamps : {nid}_out);")
    ctx.emit(f"{nid}_hit1 = ({nid}_ph == 1 && {nid}_out >= 1 ? 1 : 0);")
    ctx.emit(f"{nid}_out = ({nid}_hit1 > 0 ? 1 : {nid}_out);")
    ctx.emit(f"{nid}_ph = ({nid}_hit1 > 0 ? 2 : {nid}_ph);")
    # decay
    ctx.emit(f"{nid}_dsamps = max({decay} * samplerate * 0.001, 1);")
    ctx.emit(
        f"{nid}_out = ({nid}_ph == 2 ? {nid}_out - (1 - {sustain}) / "
        f"{nid}_dsamps : {nid}_out);"
    )
    ctx.emit(f"{nid}_hit2 = ({nid}_ph == 2 && {nid}_out <= {sustain} ? 1 : 0);")
    ctx.emit(f"{nid}_out = ({nid}_hit2 > 0 ? {sustain} : {nid}_out);")
    ctx.emit(f"{nid}_ph = ({nid}_hit2 > 0 ? 3 : {nid}_ph);")
    # sustain
    ctx.emit(f"{nid}_out = ({nid}_ph == 3 ? {sustain} : {nid}_out);")
    # release
    ctx.emit(f"{nid}_rsamps = max({release} * samplerate * 0.001, 1);")
    ctx.emit(f"{nid}_out = ({nid}_ph == 4 ? {nid}_out - 1 / {nid}_rsamps : {nid}_out);")
    ctx.emit(f"{nid}_hit0 = ({nid}_ph == 4 && {nid}_out <= 0 ? 1 : 0);")
    ctx.emit(f"{nid}_out = ({nid}_hit0 > 0 ? 0 : {nid}_out);")
    ctx.emit(f"{nid}_ph = ({nid}_hit0 > 0 ? 0 : {nid}_ph);")
    # commit
    ctx.emit(f"{nid} = {nid}_out;")
    ctx.emit(f"{nid}_phase = {nid}_ph;")
    ctx.emit(f"{nid}_output = {nid}_out;")
    ctx.emit(f"{nid}_ptrig = {nid}_g;")


def _emit_delay_read(node: DelayRead, ctx: _Ctx) -> None:
    """Faithful ring-buffer tap read mirroring simulate.py."""
    nid, dl = node.id, node.delay
    tap = ctx.ref(node.tap)
    ctx.emit(f"{nid}_n = dim({dl});")
    if node.interp == "none":
        ctx.emit(f"{nid}_b = {dl}_wr - trunc({tap});")
        ctx.emit(f"{nid}_pos = {nid}_b - {nid}_n * floor({nid}_b / {nid}_n);")
        ctx.emit(f"{nid} = peek({dl}, {nid}_pos);")
        return
    ctx.emit(f"{nid}_tap = {tap};")
    ctx.emit(f"{nid}_itap = trunc({nid}_tap);")
    ctx.emit(f"{nid}_frac = {nid}_tap - {nid}_itap;")
    ctx.emit(f"{nid}_b0 = {dl}_wr - {nid}_itap;")
    ctx.emit(f"{nid}_i0 = {nid}_b0 - {nid}_n * floor({nid}_b0 / {nid}_n);")
    ctx.emit(f"{nid}_b1 = {dl}_wr - {nid}_itap - 1;")
    ctx.emit(f"{nid}_i1 = {nid}_b1 - {nid}_n * floor({nid}_b1 / {nid}_n);")
    if node.interp == "linear":
        ctx.emit(f"{nid}_s0 = peek({dl}, {nid}_i0);")
        ctx.emit(f"{nid}_s1 = peek({dl}, {nid}_i1);")
        ctx.emit(f"{nid} = {nid}_s0 + {nid}_frac * ({nid}_s1 - {nid}_s0);")
        return
    # cubic
    ctx.emit(f"{nid}_im1 = ({nid}_i0 + 1) - {nid}_n * floor(({nid}_i0 + 1) / {nid}_n);")
    ctx.emit(f"{nid}_b2 = {dl}_wr - {nid}_itap - 2;")
    ctx.emit(f"{nid}_i2 = {nid}_b2 - {nid}_n * floor({nid}_b2 / {nid}_n);")
    ctx.emit(f"{nid}_ym1 = peek({dl}, {nid}_im1);")
    ctx.emit(f"{nid}_y0 = peek({dl}, {nid}_i0);")
    ctx.emit(f"{nid}_y1 = peek({dl}, {nid}_i1);")
    ctx.emit(f"{nid}_y2 = peek({dl}, {nid}_i2);")
    _emit_cubic_horner(ctx, nid)


def _emit_buf_read(node: BufRead, ctx: _Ctx) -> None:
    """Faithful table read with optional interpolation mirroring simulate.py."""
    nid, buf = node.id, node.buffer
    idx = ctx.ref(node.index)
    ctx.emit(f"{nid}_dm = dim({buf}) - 1;")
    if node.interp == "none":
        ctx.emit(f"{nid}_i = trunc({idx});")
        ctx.emit(f"{nid}_i = max(0, min({nid}_i, {nid}_dm));")
        ctx.emit(f"{nid} = peek({buf}, {nid}_i);")
        return
    ctx.emit(f"{nid}_fi = {idx};")
    ctx.emit(f"{nid}_i0 = trunc({nid}_fi);")
    ctx.emit(f"{nid}_frac = {nid}_fi - {nid}_i0;")
    if node.interp == "linear":
        ctx.emit(f"{nid}_c0 = max(0, min({nid}_i0, {nid}_dm));")
        ctx.emit(f"{nid}_c1 = max(0, min({nid}_i0 + 1, {nid}_dm));")
        ctx.emit(f"{nid}_s0 = peek({buf}, {nid}_c0);")
        ctx.emit(f"{nid}_s1 = peek({buf}, {nid}_c1);")
        ctx.emit(f"{nid} = {nid}_s0 + {nid}_frac * ({nid}_s1 - {nid}_s0);")
        return
    # cubic
    ctx.emit(f"{nid}_im1 = max(0, min({nid}_i0 - 1, {nid}_dm));")
    ctx.emit(f"{nid}_c0i = max(0, min({nid}_i0, {nid}_dm));")
    ctx.emit(f"{nid}_i1 = max(0, min({nid}_i0 + 1, {nid}_dm));")
    ctx.emit(f"{nid}_i2 = max(0, min({nid}_i0 + 2, {nid}_dm));")
    ctx.emit(f"{nid}_ym1 = peek({buf}, {nid}_im1);")
    ctx.emit(f"{nid}_y0 = peek({buf}, {nid}_c0i);")
    ctx.emit(f"{nid}_y1 = peek({buf}, {nid}_i1);")
    ctx.emit(f"{nid}_y2 = peek({buf}, {nid}_i2);")
    _emit_cubic_horner(ctx, nid)


def _emit_cubic_horner(ctx: _Ctx, nid: str) -> None:
    """Emit the shared 4-point cubic interpolation tail (uses ym1,y0,y1,y2,frac)."""
    ctx.emit(f"{nid}_c0v = {nid}_y0;")
    ctx.emit(f"{nid}_c1v = 0.5 * ({nid}_y1 - {nid}_ym1);")
    ctx.emit(f"{nid}_c2v = {nid}_ym1 - 2.5 * {nid}_y0 + 2 * {nid}_y1 - 0.5 * {nid}_y2;")
    ctx.emit(f"{nid}_c3v = 0.5 * ({nid}_y2 - {nid}_ym1) + 1.5 * ({nid}_y0 - {nid}_y1);")
    ctx.emit(
        f"{nid} = (({nid}_c3v * {nid}_frac + {nid}_c2v) * {nid}_frac + {nid}_c1v) "
        f"* {nid}_frac + {nid}_c0v;"
    )


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def _check_identifier(ident: str, kind: str) -> None:
    if not _C_ID_RE.match(ident):
        raise ValueError(f"{kind} '{ident}' is not a valid identifier")
    if is_reserved_word(ident):
        raise ValueError(f"{kind} '{ident}' is a C/C++ reserved word")
    if ident in _GENEXPR_RESERVED or _IO_NAME_RE.match(ident):
        raise ValueError(
            f"{kind} '{ident}' collides with a GenExpr reserved word/operator; "
            "rename it"
        )


def transpile_to_genexpr(graph: Graph) -> str:
    """Transpile a DSP graph to gen~ codebox (GenExpr) source.

    Subgraphs are expanded first, then the graph is validated. Raises
    :class:`ValueError` for invalid graphs or colliding identifiers, and
    :class:`GenExprUnsupportedError` for node types not yet handled.
    """
    graph = expand_subgraphs(graph)
    errors = validate_graph(graph)
    if errors:
        raise ValueError("Invalid graph: " + "; ".join(errors))

    # Only node ids and param names become GenExpr identifiers in the emitted
    # codebox, so only they need the reserved-word/operator collision guard.
    # Input/output ids are remapped positionally to in<N>/out<N> and are never
    # emitted verbatim, so they are exempt (e.g. an output id "out1" is fine).
    for p in graph.params:
        _check_identifier(p.name, "param")
    for node in graph.nodes:
        _check_identifier(node.id, "node")

    sorted_nodes = toposort(graph)
    input_index = {inp.id: i + 1 for i, inp in enumerate(graph.inputs)}
    param_names = {p.name for p in graph.params}

    ctx = _Ctx(input_index, param_names)
    for node in sorted_nodes:
        _emit_node(node, ctx)

    # -- Assemble
    lines: list[str] = []
    lines.append("// Generated by gen-dsp (experimental .gdsp -> gen~ transpiler)")
    lines.append(f"// Graph: {graph.name}")
    lines.append(
        f"// {len(graph.inputs)} in, {len(graph.outputs)} out, "
        f"{len(graph.params)} param(s)"
    )
    lines.append("")

    for p in graph.params:
        default = max(p.min, min(p.default, p.max))
        lines.append(
            f"Param {p.name}({_gen_float_lit(default)}, "
            f"min={_gen_float_lit(p.min)}, max={_gen_float_lit(p.max)});"
        )
    if graph.params:
        lines.append("")

    if ctx.decls:
        lines.extend(ctx.decls)
        lines.append("")

    lines.extend(ctx.body)

    if ctx.writebacks:
        lines.append("")
        lines.append("// history feedback (store for next sample)")
        lines.extend(ctx.writebacks)

    lines.append("")
    lines.append("// outputs")
    for i, out in enumerate(graph.outputs):
        lines.append(f"out{i + 1} = {ctx.ref(out.source)};")

    return "\n".join(lines) + "\n"


__all__ = [
    "transpile_to_genexpr",
    "GenExprUnsupportedError",
    "NON_DETERMINISTIC_OPS",
]
