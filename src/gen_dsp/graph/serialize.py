"""Serialize a Graph to .gdsp DSL source."""

from __future__ import annotations

from typing import Union

from gen_dsp.graph.models import (
    SVF,
    BinOp,
    Buffer,
    BufRead,
    BufSize,
    BufWrite,
    Compare,
    Constant,
    Cycle,
    DelayLine,
    DelayRead,
    DelayWrite,
    GateOut,
    GateRoute,
    Graph,
    History,
    Lookup,
    NamedConstant,
    Node,
    SampleRate,
    Selector,
    Splat,
    UnaryOp,
    Wave,
)
from gen_dsp.graph.toposort import toposort

Ref = Union[str, float]

# BinOp ops that use infix syntax
_INFIX_OPS: dict[str, str] = {
    "add": "+",
    "sub": "-",
    "mul": "*",
    "div": "/",
    "mod": "%",
    "pow": "**",
}

# Compare ops -> infix symbols
_CMP_OPS: dict[str, str] = {
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
    "eq": "==",
    "neq": "!=",
}

# Builtin functions: op -> list of positional field names
_BUILTIN_FIELDS: dict[str, list[str]] = {
    "phasor": ["freq"],
    "sinosc": ["freq"],
    "triosc": ["freq"],
    "sawosc": ["freq"],
    "pulseosc": ["freq", "width"],
    "noise": [],
    "onepole": ["a", "coeff"],
    "dcblock": ["a"],
    "allpass": ["a", "coeff"],
    "biquad": ["a", "b0", "b1", "b2", "a1", "a2"],
    "svf": ["a", "freq", "q"],
    "clamp": ["a", "lo", "hi"],
    "wrap": ["a", "lo", "hi"],
    "fold": ["a", "lo", "hi"],
    "scale": ["a", "in_lo", "in_hi", "out_lo", "out_hi"],
    "smoothstep": ["a", "edge0", "edge1"],
    "mix": ["a", "b", "t"],
    "select": ["cond", "a", "b"],
    "delta": ["a"],
    "change": ["a"],
    "sample_hold": ["a", "trig"],
    "latch": ["a", "trig"],
    "accum": ["incr", "reset"],
    "mulaccum": ["incr", "reset"],
    "counter": ["trig", "max"],
    "elapsed": [],
    "rate_div": ["a", "divisor"],
    "smooth": ["a", "coeff"],
    "slide": ["a", "up", "down"],
    "adsr": ["gate", "attack", "decay", "sustain", "release"],
    "pass": ["a"],
    "peek": ["a"],
    "samplerate": [],
    "cycle": ["buffer", "phase"],
    "wave": ["buffer", "phase"],
    "lookup": ["buffer", "index"],
    "buf_read": ["buffer", "index"],
    "buf_size": ["buffer"],
    "gate_route": ["a", "index"],
    "gate_out": ["gate", "channel"],
    "selector": ["index"],
}


def _format_num(v: float) -> str:
    """Format a float as a clean numeric literal."""
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    s = f"{v:.15g}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
        if "." not in s:
            s += ".0"
    return s


def _format_ref(
    ref: Ref,
    const_map: dict[str, float],
    named_const_map: dict[str, str] | None = None,
) -> str:
    """Format a Ref (str|float) for .gdsp output, inlining constants."""
    if isinstance(ref, (int, float)):
        return _format_num(float(ref))
    if ref in const_map:
        return _format_num(const_map[ref])
    if named_const_map and ref in named_const_map:
        return named_const_map[ref]
    return ref


def graph_to_gdsp(graph: Graph) -> str:
    """Serialize a gen-dsp Graph to .gdsp DSL source.

    Produces a human-readable .gdsp string that, when parsed back with
    ``gen_dsp.graph.dsl.parse()``, yields an equivalent Graph.

    Constant nodes are inlined as numeric literals.  NamedConstant nodes
    are inlined as bare identifiers (``pi``, ``e``, etc.).  History
    feedback writes use the ``<-`` operator.  Processing nodes are
    emitted in topological order.
    """
    lines: list[str] = []
    indent = "    "
    control_set = set(graph.control_nodes)

    # Build constant inlining map
    const_map: dict[str, float] = {}
    named_const_map: dict[str, str] = {}
    for node in graph.nodes:
        if isinstance(node, Constant):
            const_map[node.id] = node.value
        elif isinstance(node, NamedConstant):
            named_const_map[node.id] = node.op

    try:
        topo_order = toposort(graph)
    except Exception:
        topo_order = list(graph.nodes)

    # --- Header ---
    opts: list[str] = []
    if graph.sample_rate != 44100:
        opts.append(f"sr={_format_num(float(graph.sample_rate))}")
    if graph.control_interval != 0:
        opts.append(f"control={graph.control_interval}")
    opt_str = f" ({', '.join(opts)})" if opts else ""
    lines.append(f"graph {graph.name}{opt_str} {{")

    # --- Inputs ---
    if graph.inputs:
        names = ", ".join(inp.id for inp in graph.inputs)
        lines.append(f"{indent}in {names}")

    # --- Params ---
    for p in graph.params:
        lines.append(
            f"{indent}param {p.name} {_format_num(p.min)}..{_format_num(p.max)}"
            f" = {_format_num(p.default)}"
        )

    # --- Memory declarations (buffer, delay, history) ---
    for node in graph.nodes:
        if isinstance(node, Buffer):
            fill_part = f" fill={node.fill}" if node.fill != "zeros" else ""
            lines.append(f"{indent}buffer {node.id} {node.size}{fill_part}")
        elif isinstance(node, DelayLine):
            lines.append(f"{indent}delay {node.id} {node.max_samples}")
        elif isinstance(node, History):
            lines.append(f"{indent}history {node.id} = {_format_num(node.init)}")

    # Blank line before processing
    if (
        graph.inputs
        or graph.params
        or any(isinstance(n, (Buffer, DelayLine, History)) for n in graph.nodes)
    ):
        lines.append("")

    # --- Processing nodes in toposort order ---
    history_writes: list[tuple[str, str]] = []

    for node in topo_order:
        if isinstance(node, Constant):
            continue
        if isinstance(node, (Buffer, DelayLine)):
            continue
        if isinstance(node, History):
            if node.input:
                history_writes.append((node.id, node.input))
            continue

        expr = _node_to_expr(node, const_map, named_const_map)
        if expr is None:
            continue

        control_prefix = "@control " if node.id in control_set else ""

        if isinstance(node, (DelayWrite, BufWrite, Splat)):
            lines.append(f"{indent}{control_prefix}{expr}")
        else:
            lines.append(f"{indent}{control_prefix}{node.id} = {expr}")

    # --- History feedback writes ---
    for hist_id, input_ref in history_writes:
        ref_str = _format_ref(input_ref, const_map, named_const_map)
        lines.append(f"{indent}{hist_id} <- {ref_str}")

    # Blank line before outputs
    if graph.outputs:
        lines.append("")

    # --- Outputs ---
    for out in graph.outputs:
        src = _format_ref(out.source, const_map) if out.source else ""
        lines.append(f"{indent}out {out.id} = {src}")

    lines.append("}")
    return "\n".join(lines) + "\n"


def _node_to_expr(
    node: Node,
    const_map: dict[str, float],
    named_const_map: dict[str, str] | None = None,
) -> str | None:
    """Convert a single node to its .gdsp expression string."""

    def ref(v: Ref) -> str:
        return _format_ref(v, const_map, named_const_map)

    op = node.op

    # BinOp with infix operators
    if isinstance(node, BinOp) and op in _INFIX_OPS:
        return f"{ref(node.a)} {_INFIX_OPS[op]} {ref(node.b)}"

    # BinOp with function-call operators (min, max, atan2, etc.)
    if isinstance(node, BinOp):
        return f"{op}({ref(node.a)}, {ref(node.b)})"

    # Compare
    if isinstance(node, Compare):
        return f"{ref(node.a)} {_CMP_OPS[op]} {ref(node.b)}"

    # UnaryOp
    if isinstance(node, UnaryOp):
        return f"{op}({ref(node.a)})"

    # NamedConstant
    if isinstance(node, NamedConstant):
        return op

    # SampleRate
    if isinstance(node, SampleRate):
        return "samplerate()"

    # DelayWrite: special statement syntax
    if isinstance(node, DelayWrite):
        return f"delay_write {node.delay} ({ref(node.value)})"

    # DelayRead: special syntax
    if isinstance(node, DelayRead):
        interp_part = f", interp={node.interp}" if node.interp != "none" else ""
        return f"delay_read {node.delay} ({ref(node.tap)}{interp_part})"

    # BufWrite: function-call statement
    if isinstance(node, BufWrite):
        return f"buf_write({node.buffer}, {ref(node.index)}, {ref(node.value)})"

    # Splat: function-call statement
    if isinstance(node, Splat):
        return f"splat({node.buffer}, {ref(node.index)}, {ref(node.value)})"

    # BufRead: function call with optional interp kwarg
    if isinstance(node, BufRead):
        interp_part = f", interp={node.interp}" if node.interp != "none" else ""
        return f"buf_read({node.buffer}, {ref(node.index)}{interp_part})"

    # BufSize
    if isinstance(node, BufSize):
        return f"buf_size({node.buffer})"

    # Cycle / Wave / Lookup
    if isinstance(node, Cycle):
        return f"cycle({node.buffer}, {ref(node.phase)})"
    if isinstance(node, Wave):
        return f"wave({node.buffer}, {ref(node.phase)})"
    if isinstance(node, Lookup):
        return f"lookup({node.buffer}, {ref(node.index)})"

    # SVF: optional mode kwarg (omit if default 'lp')
    if isinstance(node, SVF):
        mode_part = f", mode={node.mode}" if node.mode != "lp" else ""
        return f"svf({ref(node.a)}, {ref(node.freq)}, {ref(node.q)}{mode_part})"

    # Selector: variable-length inputs
    if isinstance(node, Selector):
        inputs_str = ", ".join(ref(i) for i in node.inputs)
        return f"selector({ref(node.index)}, {inputs_str})"

    # GateRoute
    if isinstance(node, GateRoute):
        return f"gate_route({ref(node.a)}, {ref(node.index)}, {node.count})"

    # GateOut
    if isinstance(node, GateOut):
        return f"gate_out({node.gate}, {node.channel})"

    # Fallback: use builtin field registry
    if op in _BUILTIN_FIELDS:
        fields = _BUILTIN_FIELDS[op]
        args: list[str] = []
        for fname in fields:
            val = getattr(node, fname, None)
            if val is None:
                continue
            if isinstance(val, (str, int, float)):
                args.append(ref(val) if isinstance(val, (str, float)) else str(val))
            elif isinstance(val, list):
                args.extend(ref(item) for item in val)
        return f"{op}({', '.join(args)})"

    # Last resort: generic op(field1, field2, ...)
    fields_data = {k: v for k, v in node.__dict__.items() if k not in ("id", "op")}
    args_list = []
    for v in fields_data.values():
        if isinstance(v, (str, float)):
            args_list.append(ref(v))
        elif isinstance(v, int):
            args_list.append(str(v))
        elif isinstance(v, list):
            args_list.extend(ref(item) for item in v if isinstance(item, (str, float)))
    return f"{op}({', '.join(args_list)})"
