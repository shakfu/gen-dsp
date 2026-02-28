"""Optimization passes for DSP graphs."""

from __future__ import annotations

import math
from typing import NamedTuple, Union

from gen_dsp.dsp_graph.models import (
    SVF,
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
    Node,
    Noise,
    OnePole,
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
    RateDiv,
    SmoothParam,
    Peek,
    Buffer,
    BufRead,
    BufWrite,
    BufSize,
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
}

_COMPARE_EVAL: dict[str, object] = {
    "gt": lambda a, b: 1.0 if a > b else 0.0,
    "lt": lambda a, b: 1.0 if a < b else 0.0,
    "gte": lambda a, b: 1.0 if a >= b else 0.0,
    "lte": lambda a, b: 1.0 if a <= b else 0.0,
    "eq": lambda a, b: 1.0 if a == b else 0.0,
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
            fn = _UNARYOP_EVAL[node.op]
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

    return None


def constant_fold(graph: Graph) -> Graph:
    """Replace pure nodes with all-constant inputs by Constant nodes.

    Returns a new Graph (immutable transform). Stateful nodes are never folded.
    """
    from gen_dsp.dsp_graph.toposort import toposort

    sorted_nodes = toposort(graph)
    constants: dict[str, float] = {}
    new_nodes: list[Node] = []

    for node in sorted_nodes:
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

    # Map buffer ID -> BufWrite node IDs that write to it
    buffer_writers: dict[str, list[str]] = {}
    for node in graph.nodes:
        if isinstance(node, BufWrite):
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
        # Follow all string fields
        for field_name, value in node.__dict__.items():
            if field_name in ("id", "op"):
                continue
            if isinstance(value, str) and value in node_ids:
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

    from gen_dsp.dsp_graph.toposort import toposort

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

_NON_REF_FIELDS = frozenset({"id", "op", "interp", "mode"})


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
    return None


def _rewrite_refs(node: Node, rewrite: dict[str, str]) -> Node:
    """Return a copy of *node* with string ref fields remapped through *rewrite*."""
    updates: dict[str, str] = {}
    for field_name, value in node.__dict__.items():
        if field_name in _NON_REF_FIELDS:
            continue
        if isinstance(value, str) and value in rewrite:
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
    from gen_dsp.dsp_graph.toposort import toposort

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
    from gen_dsp.dsp_graph.subgraph import expand_subgraphs

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
