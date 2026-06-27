"""Experimental Python evaluator for emitted gen~ (GenExpr) codeboxes.

This is the automated half of the differential-test harness for
:mod:`gen_dsp.graph.transpile`. Running a real differential test against
Cycling '74's gen~ requires Max in the loop and cannot run in CI. To get
automated coverage anyway, this module interprets the *emitted* codebox with
gen~ per-sample semantics, so the transpiler's output can be diffed against the
independent reference in :mod:`gen_dsp.graph.simulate`.

What it validates: that the GenExpr the transpiler emits computes the same thing
as the graph it came from. A transcription bug in a faithful node emission
(wrong term, sign, ``History`` timing, interpolation index) makes this evaluator
diverge from ``simulate`` and the differential test fails.

What it does NOT validate: that gen-dsp's operator semantics match Cycling '74's
reference. That remains the manual, Max-in-the-loop step.

Semantics modelled:

* per-sample execution of the codebox body, top to bottom;
* ``History`` is a unit delay -- reads return the previously-stored value
  regardless of textual position; a write schedules the next-sample value;
* ``Data`` is a mutable float32 array; ``peek``/``poke`` are immediate and
  bounds-checked (out-of-range peek returns 0, poke is ignored), ``dim`` returns
  the length; this matches gen~ and ``simulate``;
* ``/`` and ``%`` return 0 on a zero divisor (gen~'s protected division).

**Status: experimental, unexposed.** Imported directly by tests; not part of the
package's public API.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

try:
    import numpy as np
    from numpy.typing import NDArray
except ImportError as exc:  # pragma: no cover - exercised only without numpy
    raise ImportError(
        "numpy is required for the GenExpr evaluator. "
        "Install with: pip install gen-dsp[sim]"
    ) from exc


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------


class Expr:
    """Base class for parsed GenExpr expressions."""


@dataclass
class Num(Expr):
    v: float


@dataclass
class Var(Expr):
    name: str


@dataclass
class Unary(Expr):
    op: str
    e: Expr


@dataclass
class Bin(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class Tern(Expr):
    cond: Expr
    a: Expr
    b: Expr


@dataclass
class Call(Expr):
    name: str
    args: list[Expr]
    cid: int  # unique per call site, used to key stateful operators (delta)


@dataclass
class Assign:
    lhs: str
    expr: Expr
    is_history: bool


@dataclass
class ExprStmt:
    expr: Expr


@dataclass
class Program:
    histories: dict[str, float]
    datas: dict[str, int]
    statements: list[Assign | ExprStmt]
    outputs: list[str]  # out1, out2, ... in order
    n_calls: int
    params: dict[str, float] = field(default_factory=dict)  # name -> default


# ---------------------------------------------------------------------------
# Tokenizer + parser
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
      \s+
    | (?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
    | (?P<id>[A-Za-z_]\w*)
    | (?P<op><=|>=|==|!=|&&|\|\||[-+*/%<>(),?:!])
    """,
    re.VERBOSE,
)

_HISTORY_RE = re.compile(r"^History\s+(\w+)\(\s*(-?[0-9.eE+]+)\s*\);$")
_DATA_RE = re.compile(r"^Data\s+(\w+)\(\s*(\d+)\s*\);$")
_PARAM_RE = re.compile(r"^Param\s+(\w+)\(\s*(-?[0-9.eE+]+)\s*(?:,[^)]*)?\);$")
_ASSIGN_RE = re.compile(r"^(\w+)\s*=(?!=)\s*(.*);$")
_OUT_RE = re.compile(r"^out(\d+)$")


def _tokenize(s: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(s):
        m = _TOKEN_RE.match(s, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot tokenize GenExpr near: {s[pos:pos + 20]!r}")
        pos = m.end()
        if m.lastgroup is not None:
            tokens.append(m.group())
    return tokens


class _Parser:
    """Recursive-descent / precedence-climbing parser for the GenExpr subset."""

    def __init__(self, tokens: list[str], call_counter: list[int]) -> None:
        self._t = tokens
        self._i = 0
        self._call_counter = call_counter  # single-element mutable counter

    def _peek(self) -> str | None:
        return self._t[self._i] if self._i < len(self._t) else None

    def _next(self) -> str:
        tok = self._t[self._i]
        self._i += 1
        return tok

    def _expect(self, tok: str) -> None:
        got = self._peek()
        if got != tok:
            raise ValueError(f"expected {tok!r}, got {got!r}")
        self._i += 1

    def parse(self) -> Expr:
        e = self._ternary()
        if self._i != len(self._t):
            raise ValueError(f"trailing tokens: {self._t[self._i:]}")
        return e

    def _ternary(self) -> Expr:
        cond = self._or()
        if self._peek() == "?":
            self._next()
            a = self._ternary()
            self._expect(":")
            b = self._ternary()
            return Tern(cond, a, b)
        return cond

    def _binary_level(
        self, ops: set[str], lower: Callable[[], Expr]
    ) -> Expr:
        left = lower()
        while self._peek() in ops:
            op = self._next()
            right = lower()
            left = Bin(op, left, right)
        return left

    def _or(self) -> Expr:
        return self._binary_level({"||"}, self._and)

    def _and(self) -> Expr:
        return self._binary_level({"&&"}, self._equality)

    def _equality(self) -> Expr:
        return self._binary_level({"==", "!="}, self._relational)

    def _relational(self) -> Expr:
        return self._binary_level({"<", ">", "<=", ">="}, self._additive)

    def _additive(self) -> Expr:
        return self._binary_level({"+", "-"}, self._multiplicative)

    def _multiplicative(self) -> Expr:
        return self._binary_level({"*", "/", "%"}, self._unary)

    def _unary(self) -> Expr:
        tok = self._peek()
        if tok == "-":
            self._next()
            return Unary("-", self._unary())
        if tok == "!":
            self._next()
            return Unary("!", self._unary())
        return self._primary()

    def _primary(self) -> Expr:
        tok = self._peek()
        if tok is None:
            raise ValueError("unexpected end of expression")
        if tok == "(":
            self._next()
            e = self._ternary()
            self._expect(")")
            return e
        if tok[0].isdigit() or tok[0] == ".":
            # numeric literal
            self._next()
            return Num(float(tok))
        if tok[0].isalpha() or tok[0] == "_":
            self._next()
            if self._peek() == "(":
                self._next()
                args: list[Expr] = []
                if self._peek() != ")":
                    args.append(self._ternary())
                    while self._peek() == ",":
                        self._next()
                        args.append(self._ternary())
                self._expect(")")
                cid = self._call_counter[0]
                self._call_counter[0] += 1
                return Call(tok, args, cid)
            return Var(tok)
        raise ValueError(f"unexpected token {tok!r}")


def parse_genexpr(code: str) -> Program:
    """Parse an emitted GenExpr codebox into a runnable :class:`Program`."""
    histories: dict[str, float] = {}
    datas: dict[str, int] = {}
    params: dict[str, float] = {}
    statements: list[Assign | ExprStmt] = []
    outputs: list[str] = []
    call_counter = [0]

    for raw in code.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        pm = _PARAM_RE.match(line)
        if pm:
            params[pm.group(1)] = float(pm.group(2))
            continue
        hm = _HISTORY_RE.match(line)
        if hm:
            histories[hm.group(1)] = float(hm.group(2))
            continue
        dm = _DATA_RE.match(line)
        if dm:
            datas[dm.group(1)] = int(dm.group(2))
            continue
        am = _ASSIGN_RE.match(line)
        if am:
            lhs, rhs = am.group(1), am.group(2)
            expr = _Parser(_tokenize(rhs), call_counter).parse()
            statements.append(Assign(lhs, expr, lhs in histories))
            om = _OUT_RE.match(lhs)
            if om and lhs not in outputs:
                outputs.append(lhs)
            continue
        if not line.endswith(";"):
            raise ValueError(f"unterminated GenExpr statement: {line!r}")
        expr = _Parser(_tokenize(line[:-1]), call_counter).parse()
        statements.append(ExprStmt(expr))

    outputs.sort(key=lambda name: int(_OUT_RE.match(name).group(1)))  # type: ignore[union-attr]
    return Program(histories, datas, statements, outputs, call_counter[0], params)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass
class _EvalCtx:
    env: dict[str, float]
    data: dict[str, NDArray[np.float32]]
    call_state: dict[int, float]


def _data_name(e: Expr) -> str:
    if not isinstance(e, Var):
        raise ValueError("buffer operator expects a Data name as first argument")
    return e.name


def _peek(arr: NDArray[np.float32], idx: float) -> float:
    i = int(idx)
    if 0 <= i < len(arr):
        return float(arr[i])
    return 0.0


def _poke(arr: NDArray[np.float32], val: float, idx: float) -> None:
    i = int(idx)
    if 0 <= i < len(arr):
        arr[i] = np.float32(val)


# Pure scalar functions, mirroring simulate.py / gen~ operator semantics.
_UNARY_FUNCS: dict[str, Callable[[float], float]] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "asinh": math.asinh,
    "acosh": math.acosh,
    "atanh": math.atanh,
    "exp": math.exp,
    "exp2": lambda x: math.pow(2.0, x),
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "sqrt": math.sqrt,
    "abs": abs,
    "floor": lambda x: float(math.floor(x)),
    "ceil": lambda x: float(math.ceil(x)),
    "round": lambda x: float(round(x)),
    "trunc": lambda x: float(math.trunc(x)),
    "sign": lambda x: 1.0 if x > 0.0 else (-1.0 if x < 0.0 else 0.0),
    "fract": lambda x: x - math.floor(x),
}


def _eval(e: Expr, ctx: _EvalCtx) -> float:
    if isinstance(e, Num):
        return e.v
    if isinstance(e, Var):
        if e.name in ctx.env:
            return ctx.env[e.name]
        raise KeyError(f"undefined variable: {e.name!r}")
    if isinstance(e, Unary):
        v = _eval(e.e, ctx)
        if e.op == "-":
            return -v
        return 1.0 if v == 0.0 else 0.0  # "!"
    if isinstance(e, Tern):
        return _eval(e.a, ctx) if _eval(e.cond, ctx) != 0.0 else _eval(e.b, ctx)
    if isinstance(e, Bin):
        return _eval_bin(e, ctx)
    if isinstance(e, Call):
        return _eval_call(e, ctx)
    raise TypeError(f"unknown expr: {e!r}")


def _eval_bin(e: Bin, ctx: _EvalCtx) -> float:
    op = e.op
    a = _eval(e.left, ctx)
    b = _eval(e.right, ctx)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return a / b if b != 0.0 else 0.0
    if op == "%":
        return math.fmod(a, b) if b != 0.0 else 0.0
    if op == "<":
        return 1.0 if a < b else 0.0
    if op == ">":
        return 1.0 if a > b else 0.0
    if op == "<=":
        return 1.0 if a <= b else 0.0
    if op == ">=":
        return 1.0 if a >= b else 0.0
    if op == "==":
        return 1.0 if a == b else 0.0
    if op == "!=":
        return 1.0 if a != b else 0.0
    if op == "&&":
        return 1.0 if (a != 0.0 and b != 0.0) else 0.0
    if op == "||":
        return 1.0 if (a != 0.0 or b != 0.0) else 0.0
    raise ValueError(f"unknown binary op: {op!r}")


def _eval_call(e: Call, ctx: _EvalCtx) -> float:
    name = e.name
    # Buffer / data operators: first arg is a Data name, not a value.
    if name == "dim":
        return float(len(ctx.data[_data_name(e.args[0])]))
    if name == "peek":
        return _peek(ctx.data[_data_name(e.args[0])], _eval(e.args[1], ctx))
    if name == "poke":
        _poke(
            ctx.data[_data_name(e.args[0])],
            _eval(e.args[1], ctx),
            _eval(e.args[2], ctx),
        )
        return 0.0
    # Nondeterministic generator: cannot be reproduced or differentially tested.
    if name == "noise":
        raise ValueError(
            "noise() is nondeterministic and cannot be evaluated by the "
            "differential harness; exclude Noise nodes from comparison"
        )
    # Stateful native operator (call-site keyed).
    if name == "delta":
        x = _eval(e.args[0], ctx)
        prev = ctx.call_state.get(e.cid, 0.0)
        ctx.call_state[e.cid] = x
        return x - prev
    args = [_eval(a, ctx) for a in e.args]
    if name in _UNARY_FUNCS and len(args) == 1:
        return float(_UNARY_FUNCS[name](args[0]))
    return _eval_named(name, args)


def _eval_named(name: str, a: list[float]) -> float:
    if name == "min":
        return min(a[0], a[1])
    if name == "max":
        return max(a[0], a[1])
    if name == "pow":
        return math.pow(a[0], a[1])
    if name == "atan2":
        return math.atan2(a[0], a[1])
    if name == "hypot":
        return math.hypot(a[0], a[1])
    if name == "step":
        return 1.0 if a[0] >= a[1] else 0.0
    if name == "clamp":
        return min(max(a[0], a[1]), a[2])
    if name == "wrap":
        rng = a[2] - a[1]
        raw = math.fmod(a[0] - a[1], rng)
        if raw < 0.0:
            raw += rng
        return a[1] + raw
    if name == "fold":
        rng = a[2] - a[1]
        t = math.fmod(a[0] - a[1], 2.0 * rng)
        if t < 0.0:
            t += 2.0 * rng
        return a[1] + t if t <= rng else a[2] - (t - rng)
    if name == "scale":
        in_range = a[2] - a[1]
        return a[3] + (a[0] - a[1]) / in_range * (a[4] - a[3]) if in_range != 0.0 else a[3]
    if name == "mix":
        return a[0] + (a[1] - a[0]) * a[2]
    if name in ("gt", "lt", "gte", "lte", "eq", "neq"):
        return _eval_compare(name, a[0], a[1])
    if name in ("gtp", "ltp", "gtep", "ltep", "eqp", "neqp"):
        return _eval_compare_pass(name, a[0], a[1])
    raise ValueError(f"unknown function: {name!r}")


def _eval_compare(name: str, a: float, b: float) -> float:
    table = {
        "gt": a > b,
        "lt": a < b,
        "gte": a >= b,
        "lte": a <= b,
        "eq": a == b,
        "neq": a != b,
    }
    return 1.0 if table[name] else 0.0


def _eval_compare_pass(name: str, a: float, b: float) -> float:
    table = {
        "gtp": a > b,
        "ltp": a < b,
        "gtep": a >= b,
        "ltep": a <= b,
        "eqp": a == b,
        "neqp": a != b,
    }
    return a if table[name] else 0.0


def run_genexpr(
    program: Program,
    inputs: dict[str, NDArray[np.float32]] | None,
    sr: float,
    n_samples: int,
    data_init: dict[str, NDArray[np.float32]] | None = None,
    params: dict[str, float] | None = None,
) -> dict[str, NDArray[np.float32]]:
    """Execute a parsed GenExpr program and return its output arrays.

    Args:
        program: Parsed codebox.
        inputs: Maps ``in1``/``in2``/... to float32 arrays of length n_samples.
        sr: Sample rate (the ``samplerate`` operator).
        n_samples: Number of samples to run.
        data_init: Optional initial contents for ``Data`` arrays, keyed by name
            (truncated / zero-padded to the declared size).
        params: Optional ``Param`` overrides (name -> value); defaults to each
            param's declared default.
    """
    inputs = inputs or {}
    param_vals = dict(program.params)
    if params:
        param_vals.update(params)
    data: dict[str, NDArray[np.float32]] = {}
    for name, size in program.datas.items():
        arr = np.zeros(size, dtype=np.float32)
        if data_init and name in data_init:
            src = data_init[name]
            copy = min(len(src), size)
            arr[:copy] = src[:copy]
        data[name] = arr

    history_store: dict[str, float] = dict(program.histories)
    call_state: dict[int, float] = {}
    out_arrays = {
        name: np.zeros(n_samples, dtype=np.float32) for name in program.outputs
    }

    for i in range(n_samples):
        env: dict[str, float] = {"samplerate": sr}
        env.update(param_vals)
        for in_name, arr in inputs.items():
            env[in_name] = float(arr[i])
        for hname, hval in history_store.items():
            env[hname] = hval

        ctx = _EvalCtx(env, data, call_state)
        pending: dict[str, float] = {}
        for stmt in program.statements:
            if isinstance(stmt, ExprStmt):
                _eval(stmt.expr, ctx)
                continue
            val = _eval(stmt.expr, ctx)
            if stmt.is_history:
                pending[stmt.lhs] = val  # store for next sample, read stays old
            else:
                env[stmt.lhs] = val

        for name in program.outputs:
            out_arrays[name][i] = np.float32(env[name])
        history_store.update(pending)

    return out_arrays


def eval_genexpr(
    code: str,
    inputs: dict[str, NDArray[np.float32]] | None,
    sr: float,
    n_samples: int,
    data_init: dict[str, NDArray[np.float32]] | None = None,
) -> dict[str, NDArray[np.float32]]:
    """Parse and run a GenExpr codebox in one call."""
    return run_genexpr(parse_genexpr(code), inputs, sr, n_samples, data_init)


__all__ = ["parse_genexpr", "run_genexpr", "eval_genexpr", "Program"]
