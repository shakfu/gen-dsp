"""Optimization passes for DSP graphs."""

from __future__ import annotations

import math
from typing import NamedTuple, Union

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

# Types that are stateful and must never be constant-folded.
_STATEFUL_TYPES = (
    History,
    DelayLine,
    DelayRead,
    DelayWrite,
    Phasor,
    Noise,
    Delta,
    Change,
    Biquad,
    SVF,
    OnePole,
    DCBlock,
    Allpass,
    SinOsc,
    TriOsc,
    SawOsc,
    PulseOsc,
    SampleHold,
    Latch,
    Accum,
    Counter,
    Elapsed,
    MulAccum,
    RateDiv,
    SmoothParam,
    Slide,
    ADSR,
    Peek,
    Buffer,
    BufRead,
    BufWrite,
    Splat,
    Cycle,
    Wave,
    Lookup,
)


def _resolve_ref(ref: Union[str, float], constants: dict[str, float]) -> float | None:
    """Resolve a Ref to a float if it is a literal or a known constant node."""
    if isinstance(ref, float):
        return ref
    return constants.get(ref)


_BINOP_EVAL: dict[str, object] = {
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
    "div": lambda a, b: a / b if b != 0.0 else float("inf"),
    "min": lambda a, b: min(a, b),
    "max": lambda a, b: max(a, b),
    "mod": lambda a, b: math.fmod(a, b) if b != 0.0 else 0.0,
    "pow": lambda a, b: a**b,
    "atan2": lambda a, b: math.atan2(a, b),
    "hypot": lambda a, b: math.hypot(a, b),
    "absdiff": lambda a, b: abs(a - b),
    "step": lambda a, b: 1.0 if a >= b else 0.0,
    "and": lambda a, b: 1.0 if (a != 0.0 and b != 0.0) else 0.0,
    "or": lambda a, b: 1.0 if (a != 0.0 or b != 0.0) else 0.0,
    "xor": lambda a, b: 1.0 if ((a != 0.0) != (b != 0.0)) else 0.0,
    "rsub": lambda a, b: b - a,
    "rdiv": lambda a, b: b / a if a != 0.0 else float("inf"),
    "rmod": lambda a, b: math.fmod(b, a) if a != 0.0 else 0.0,
    "gtp": lambda a, b: a if a > b else 0.0,
    "ltp": lambda a, b: a if a < b else 0.0,
    "gtep": lambda a, b: a if a >= b else 0.0,
    "ltep": lambda a, b: a if a <= b else 0.0,
    "eqp": lambda a, b: a if a == b else 0.0,
    "neqp": lambda a, b: a if a != b else 0.0,
    "fastpow": lambda a, b: a**b,
}

_UNARYOP_EVAL: dict[str, object] = {
    "sin": math.sin,
    "cos": math.cos,
    "tanh": math.tanh,
    "exp": math.exp,
    "log": lambda x: math.log(x) if x > 0 else float("-inf"),
    "abs": abs,
    "sqrt": lambda x: math.sqrt(x) if x >= 0 else 0.0,
    "neg": lambda x: -x,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
    "sign": lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0),
    "atan": math.atan,
    "asin": lambda x: math.asin(x) if -1 <= x <= 1 else 0.0,
    "acos": lambda x: math.acos(x) if -1 <= x <= 1 else 0.0,
    "tan": math.tan,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "asinh": math.asinh,
    "acosh": lambda x: math.acosh(x) if x >= 1 else 0.0,
    "atanh": lambda x: math.atanh(x) if -1 < x < 1 else 0.0,
    "exp2": lambda x: math.pow(2.0, x),
    "log2": lambda x: math.log2(x) if x > 0 else float("-inf"),
    "log10": lambda x: math.log10(x) if x > 0 else float("-inf"),
    "fract": lambda x: x - math.floor(x),
    "trunc": math.trunc,
    "not": lambda x: 1.0 if x == 0.0 else 0.0,
    "bool": lambda x: 0.0 if x == 0.0 else 1.0,
    "mtof": lambda x: 440.0 * math.pow(2.0, (x - 69.0) / 12.0),
    "ftom": lambda x: 69.0 + 12.0 * math.log2(max(x, 1e-10) / 440.0),
    "atodb": lambda x: 20.0 * math.log10(max(x, 1e-10)),
    "dbtoa": lambda x: math.pow(10.0, x / 20.0),
    "phasewrap": lambda x: x - 2.0 * math.pi * math.floor(x / (2.0 * math.pi) + 0.5),
    "degrees": lambda x: x * (180.0 / math.pi),
    "radians": lambda x: x * (math.pi / 180.0),
    "fixdenorm": lambda x: 0.0 if abs(x) < 1e-18 else x,
    "fixnan": lambda x: 0.0 if math.isnan(x) else x,
    "isdenorm": lambda x: 1.0 if (abs(x) < 1e-18 and x != 0.0) else 0.0,
    "isnan": lambda x: 1.0 if math.isnan(x) else x,
    "fastsin": math.sin,
    "fastcos": math.cos,
    "fasttan": math.tan,
    "fastexp": math.exp,
}

_COMPARE_EVAL: dict[str, object] = {
    "gt": lambda a, b: 1.0 if a > b else 0.0,
    "lt": lambda a, b: 1.0 if a < b else 0.0,
    "gte": lambda a, b: 1.0 if a >= b else 0.0,
    "lte": lambda a, b: 1.0 if a <= b else 0.0,
    "eq": lambda a, b: 1.0 if a == b else 0.0,
    "neq": lambda a, b: 1.0 if a != b else 0.0,
}


def _try_fold(node: Node, constants: dict[str, float]) -> float | None:
    """Try to evaluate a node with all-constant inputs. Returns value or None."""
    if isinstance(node, _STATEFUL_TYPES):
        return None

    if isinstance(node, Constant):
        return node.value

    if isinstance(node, BinOp):
        a = _resolve_ref(node.a, constants)
        b = _resolve_ref(node.b, constants)
        if a is not None and b is not None:
            fn = _BINOP_EVAL[node.op]
            return float(fn(a, b))  # type: ignore[operator]
        return None

    if isinstance(node, UnaryOp):
        a = _resolve_ref(node.a, constants)
        if a is not None:
            fn = _UNARYOP_EVAL.get(node.op)
            if fn is None:
                return None  # sr-dependent ops cannot be folded
            return float(fn(a))  # type: ignore[operator]
        return None

    if isinstance(node, Compare):
        a = _resolve_ref(node.a, constants)
        b = _resolve_ref(node.b, constants)
        if a is not None and b is not None:
            fn = _COMPARE_EVAL[node.op]
            return float(fn(a, b))  # type: ignore[operator]
        return None

    if isinstance(node, Select):
        c = _resolve_ref(node.cond, constants)
        a = _resolve_ref(node.a, constants)
        b = _resolve_ref(node.b, constants)
        if c is not None and a is not None and b is not None:
            return a if c > 0.0 else b
        return None

    if isinstance(node, Clamp):
        a = _resolve_ref(node.a, constants)
        lo = _resolve_ref(node.lo, constants)
        hi = _resolve_ref(node.hi, constants)
        if a is not None and lo is not None and hi is not None:
            return min(max(a, lo), hi)
        return None

    if isinstance(node, Wrap):
        a = _resolve_ref(node.a, constants)
        lo = _resolve_ref(node.lo, constants)
        hi = _resolve_ref(node.hi, constants)
        if a is not None and lo is not None and hi is not None:
            r = hi - lo
            if r == 0.0:
                return lo
            raw = math.fmod(a - lo, r)
            return lo + (raw + r if raw < 0.0 else raw)
        return None

    if isinstance(node, Fold):
        a = _resolve_ref(node.a, constants)
        lo = _resolve_ref(node.lo, constants)
        hi = _resolve_ref(node.hi, constants)
        if a is not None and lo is not None and hi is not None:
            r = hi - lo
            if r == 0.0:
                return lo
            t = math.fmod(a - lo, 2.0 * r)
            if t < 0.0:
                t += 2.0 * r
            return lo + t if t <= r else hi - (t - r)
        return None

    if isinstance(node, Mix):
        a = _resolve_ref(node.a, constants)
        b = _resolve_ref(node.b, constants)
        mix_t = _resolve_ref(node.t, constants)
        if a is not None and b is not None and mix_t is not None:
            return a + (b - a) * mix_t
        return None

    if isinstance(node, Scale):
        a = _resolve_ref(node.a, constants)
        in_lo = _resolve_ref(node.in_lo, constants)
        in_hi = _resolve_ref(node.in_hi, constants)
        out_lo = _resolve_ref(node.out_lo, constants)
        out_hi = _resolve_ref(node.out_hi, constants)
        if (
            a is not None
            and in_lo is not None
            and in_hi is not None
            and out_lo is not None
            and out_hi is not None
        ):
            in_range = in_hi - in_lo
            if in_range == 0.0:
                return out_lo
            return out_lo + (a - in_lo) / in_range * (out_hi - out_lo)
        return None

    if isinstance(node, Pass):
        a = _resolve_ref(node.a, constants)
        if a is not None:
            return a
        return None

    if isinstance(node, SampleRate):
        return None  # runtime value, not constant-foldable

    if isinstance(node, NamedConstant):
        from gen_dsp.graph.compile import _NAMED_CONSTANT_VALUES

        return _NAMED_CONSTANT_VALUES[node.op]

    if isinstance(node, Smoothstep):
        a = _resolve_ref(node.a, constants)
        e0 = _resolve_ref(node.edge0, constants)
        e1 = _resolve_ref(node.edge1, constants)
        if a is not None and e0 is not None and e1 is not None:
            rng = e1 - e0
            if rng == 0.0:
                return 0.0
            t = min(max((a - e0) / rng, 0.0), 1.0)
            return t * t * (3.0 - 2.0 * t)
        return None

    if isinstance(node, GateRoute):
        # Multi-output container -- cannot fold to single constant
        return None

    if isinstance(node, GateOut):
        # Could fold if gate's index and value are known, but GateRoute
        # can't fold, so GateOut won't have constant gate refs in practice.
        return None

    if isinstance(node, Selector):
        idx = _resolve_ref(node.index, constants)
        if idx is None:
            return None
        resolved = [_resolve_ref(inp, constants) for inp in node.inputs]
        if any(v is None for v in resolved):
            return None
        n = len(node.inputs)
        i = int(idx)
        i = max(0, min(i, n))
        return resolved[i - 1] if i > 0 else 0.0

    return None


def constant_fold(graph: Graph) -> Graph:
    """Replace pure nodes with all-constant inputs by Constant nodes.

    Returns a new Graph (immutable transform). Stateful nodes are never folded.
    """
    from gen_dsp.graph.toposort import toposort

    sorted_nodes = toposort(graph)
    constants: dict[str, float] = {}
    new_nodes: list[Node] = []

    # Pre-resolve BufSize nodes to constants (buffer sizes are static integers).
    buf_sizes: dict[str, int] = {
        node.id: node.size for node in sorted_nodes if isinstance(node, Buffer)
    }
    bufsize_values: dict[str, float] = {}
    for node in sorted_nodes:
        if isinstance(node, BufSize) and node.buffer in buf_sizes:
            bufsize_values[node.id] = float(buf_sizes[node.buffer])

    for node in sorted_nodes:
        # Replace BufSize with pre-resolved constant.
        if node.id in bufsize_values:
            bs_val = bufsize_values[node.id]
            constants[node.id] = bs_val
            new_nodes.append(Constant(id=node.id, value=bs_val))
            continue
        val = _try_fold(node, constants)
        if val is not None and not isinstance(node, Constant):
            constants[node.id] = val
            new_nodes.append(Constant(id=node.id, value=val))
        else:
            if isinstance(node, Constant):
                constants[node.id] = node.value
            new_nodes.append(node)

    return graph.model_copy(update={"nodes": new_nodes})


def eliminate_dead_nodes(graph: Graph) -> Graph:
    """Remove nodes not reachable from any output.

    Walks backward from output sources, following ALL string fields
    (including feedback edges).  When a DelayRead is reachable, the
    DelayWrite nodes that feed the same delay line are also treated
    as reachable (side-effecting nodes).

    Returns a new Graph with dead nodes removed.
    """
    node_ids = {node.id for node in graph.nodes}
    node_map = {node.id: node for node in graph.nodes}

    # Map delay-line ID -> DelayWrite node IDs that write to it
    delay_writers: dict[str, list[str]] = {}
    for node in graph.nodes:
        if isinstance(node, DelayWrite):
            delay_writers.setdefault(node.delay, []).append(node.id)

    # Map buffer ID -> BufWrite/Splat node IDs that write to it
    buffer_writers: dict[str, list[str]] = {}
    for node in graph.nodes:
        if isinstance(node, (BufWrite, Splat)):
            buffer_writers.setdefault(node.buffer, []).append(node.id)

    # Seed with output sources
    reachable: set[str] = set()
    worklist: list[str] = [
        out.source for out in graph.outputs if out.source in node_ids
    ]

    while worklist:
        nid = worklist.pop()
        if nid in reachable:
            continue
        reachable.add(nid)
        if nid not in node_map:
            continue
        node = node_map[nid]
        # Follow all string fields (and list items)
        for field_name, value in node.__dict__.items():
            if field_name in ("id", "op"):
                continue
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item in node_ids:
                        worklist.append(item)
            elif isinstance(value, str) and value in node_ids:
                worklist.append(value)
        # If this is a DelayRead, also mark the corresponding writers
        if isinstance(node, DelayRead):
            for writer_id in delay_writers.get(node.delay, []):
                worklist.append(writer_id)
        # If this is a BufRead or BufSize, also mark the corresponding writers
        if isinstance(node, (BufRead, BufSize)):
            for writer_id in buffer_writers.get(node.buffer, []):
                worklist.append(writer_id)

    new_nodes = [node for node in graph.nodes if node.id in reachable]
    return graph.model_copy(update={"nodes": new_nodes})


def promote_control_rate(graph: Graph) -> Graph:
    """Promote audio-rate pure nodes to control-rate when all deps are control/invariant.

    A non-stateful node is promoted if it is not already control-rate or
    loop-invariant, and every string Ref field resolves to a param, literal
    float, invariant node, or (existing or already-promoted) control-rate node.

    Returns a new Graph with additional entries in ``control_nodes``.
    No-op when ``control_interval <= 0`` or ``control_nodes`` is empty.
    """
    if graph.control_interval <= 0 or not graph.control_nodes:
        return graph

    from gen_dsp.graph.toposort import toposort

    sorted_nodes = toposort(graph)
    input_ids = {inp.id for inp in graph.inputs}
    param_names = {p.name for p in graph.params}

    # Compute invariant set (mirrors compile.py _classify_loop_invariance).
    invariant_ids: set[str] = set()
    for node in sorted_nodes:
        if isinstance(node, _STATEFUL_TYPES):
            continue
        is_invariant = True
        for field_name, value in node.__dict__.items():
            if field_name in _NON_REF_FIELDS:
                continue
            if isinstance(value, float):
                continue
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, float):
                        continue
                    if isinstance(item, str):
                        if item in input_ids:
                            is_invariant = False
                            break
                        if item in param_names or item in invariant_ids:
                            continue
                        is_invariant = False
                        break
                if not is_invariant:
                    break
                continue
            if isinstance(value, str):
                if value in input_ids:
                    is_invariant = False
                    break
                if value in param_names or value in invariant_ids:
                    continue
                is_invariant = False
                break
        if is_invariant:
            invariant_ids.add(node.id)

    # Walk topo-sorted nodes and promote eligible ones.
    control_set = set(graph.control_nodes)
    promoted: list[str] = []
    for node in sorted_nodes:
        if isinstance(node, _STATEFUL_TYPES):
            continue
        if node.id in control_set or node.id in invariant_ids:
            continue
        is_promotable = True
        for field_name, value in node.__dict__.items():
            if field_name in _NON_REF_FIELDS:
                continue
            if isinstance(value, float):
                continue
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, float):
                        continue
                    if isinstance(item, str):
                        if (
                            item in param_names
                            or item in invariant_ids
                            or item in control_set
                        ):
                            continue
                        is_promotable = False
                        break
                if not is_promotable:
                    break
                continue
            if isinstance(value, str):
                if (
                    value in param_names
                    or value in invariant_ids
                    or value in control_set
                ):
                    continue
                is_promotable = False
                break
        if is_promotable:
            promoted.append(node.id)
            control_set.add(node.id)  # enable transitive promotion

    if not promoted:
        return graph
    return graph.model_copy(update={"control_nodes": graph.control_nodes + promoted})


_COMMUTATIVE_OPS = frozenset({"add", "mul", "min", "max"})

_NON_REF_FIELDS = frozenset({"id", "op", "interp", "mode", "count", "channel"})


def _operand_key(ref: Union[str, float]) -> tuple[int, Union[str, float]]:
    """Sort key for commutative operand canonicalization."""
    if isinstance(ref, float):
        return (0, ref)
    return (1, ref)


def _cse_key(
    node: Node, rewrite: dict[str, str]
) -> tuple[Union[str, float], ...] | None:
    """Compute a hashable expression key for a pure node, or None if not eligible.

    Ref fields are resolved through *rewrite* first so that transitive CSE works.
    """
    if isinstance(node, _STATEFUL_TYPES):
        return None

    def r(v: Union[str, float]) -> Union[str, float]:
        if isinstance(v, str):
            return rewrite.get(v, v)
        return v

    if isinstance(node, BinOp):
        a, b = r(node.a), r(node.b)
        if node.op in _COMMUTATIVE_OPS:
            a, b = sorted([a, b], key=_operand_key)
        return ("binop", node.op, a, b)
    if isinstance(node, UnaryOp):
        return ("unaryop", node.op, r(node.a))
    if isinstance(node, Constant):
        return ("constant", node.value)
    if isinstance(node, Compare):
        return ("compare", node.op, r(node.a), r(node.b))
    if isinstance(node, Select):
        return ("select", r(node.cond), r(node.a), r(node.b))
    if isinstance(node, Clamp):
        return ("clamp", r(node.a), r(node.lo), r(node.hi))
    if isinstance(node, Wrap):
        return ("wrap", r(node.a), r(node.lo), r(node.hi))
    if isinstance(node, Fold):
        return ("fold", r(node.a), r(node.lo), r(node.hi))
    if isinstance(node, Mix):
        return ("mix", r(node.a), r(node.b), r(node.t))
    if isinstance(node, Scale):
        return (
            "scale",
            r(node.a),
            r(node.in_lo),
            r(node.in_hi),
            r(node.out_lo),
            r(node.out_hi),
        )
    if isinstance(node, Pass):
        return ("pass", r(node.a))
    if isinstance(node, SampleRate):
        return ("samplerate",)
    if isinstance(node, NamedConstant):
        return ("namedconstant", node.op)
    if isinstance(node, Smoothstep):
        return ("smoothstep", r(node.a), r(node.edge0), r(node.edge1))
    if isinstance(node, GateRoute):
        return ("gate_route", r(node.a), r(node.index), node.count)
    if isinstance(node, GateOut):
        return ("gate_out", node.gate, node.channel)
    if isinstance(node, Selector):
        return ("selector", r(node.index), *tuple(r(inp) for inp in node.inputs))
    return None


def _rewrite_refs(node: Node, rewrite: dict[str, str]) -> Node:
    """Return a copy of *node* with string ref fields remapped through *rewrite*."""
    updates: dict[str, object] = {}
    for field_name, value in node.__dict__.items():
        if field_name in _NON_REF_FIELDS:
            continue
        if isinstance(value, list):
            new_list = [rewrite.get(v, v) if isinstance(v, str) else v for v in value]
            if new_list != value:
                updates[field_name] = new_list
        elif isinstance(value, str) and value in rewrite:
            updates[field_name] = rewrite[value]
    if not updates:
        return node
    return node.model_copy(update=updates)


def eliminate_cse(graph: Graph) -> Graph:
    """Eliminate common subexpressions from the graph.

    Two pure nodes with identical (type, op, resolved ref fields) are
    duplicates -- the later one is removed and all references rewritten
    to point to the earlier (canonical) one.
    """
    from gen_dsp.graph.toposort import toposort

    sorted_nodes = toposort(graph)
    rewrite: dict[str, str] = {}
    seen: dict[tuple[Union[str, float], ...], str] = {}

    for node in sorted_nodes:
        key = _cse_key(node, rewrite)
        if key is not None and key in seen:
            rewrite[node.id] = seen[key]
        elif key is not None:
            seen[key] = node.id

    if not rewrite:
        return graph

    new_nodes = []
    for node in graph.nodes:
        if node.id in rewrite:
            continue
        new_nodes.append(_rewrite_refs(node, rewrite))

    new_outputs = []
    for out in graph.outputs:
        source = rewrite.get(out.source, out.source)
        if source != out.source:
            new_outputs.append(out.model_copy(update={"source": source}))
        else:
            new_outputs.append(out)

    return graph.model_copy(update={"nodes": new_nodes, "outputs": new_outputs})


class OptimizeStats(NamedTuple):
    """Statistics from a single optimize_graph() run."""

    constants_folded: int
    cse_merges: int
    dead_nodes_removed: int
    control_rate_promoted: int = 0


class OptimizeResult(NamedTuple):
    """Result of optimize_graph(): the optimized graph and pass statistics."""

    graph: Graph
    stats: OptimizeStats


def optimize_graph(graph: Graph) -> OptimizeResult:
    """Apply all optimization passes: constant folding, CSE, then dead node elimination.

    Returns an ``OptimizeResult(graph, stats)`` named tuple.
    """
    from gen_dsp.graph.subgraph import expand_subgraphs

    graph = expand_subgraphs(graph)

    result = constant_fold(graph)
    orig_types = {n.id: type(n) for n in graph.nodes}
    constants_folded = sum(
        1
        for n in result.nodes
        if isinstance(n, Constant) and orig_types.get(n.id) is not Constant
    )

    before_cse = len(result.nodes)
    result = eliminate_cse(result)
    cse_merges = before_cse - len(result.nodes)

    after_cse = len(result.nodes)
    result = eliminate_dead_nodes(result)
    # CSE can orphan nodes that only the removed duplicates referenced.
    # A second dead-node pass catches these.
    result = eliminate_dead_nodes(result)
    dead_nodes_removed = after_cse - len(result.nodes)

    before_ctrl = len(result.control_nodes)
    result = promote_control_rate(result)
    control_rate_promoted = len(result.control_nodes) - before_ctrl

    stats = OptimizeStats(
        constants_folded=constants_folded,
        cse_merges=cse_merges,
        dead_nodes_removed=dead_nodes_removed,
        control_rate_promoted=control_rate_promoted,
    )
    return OptimizeResult(graph=result, stats=stats)
