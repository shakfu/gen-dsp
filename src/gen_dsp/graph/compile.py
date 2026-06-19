"""C++ code generation from DSP graphs."""

from __future__ import annotations

import math as _math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
    TriOsc,
    UnaryOp,
    Wave,
    Wrap,
)
from gen_dsp.graph.optimize import _STATEFUL_TYPES
from gen_dsp.graph.subgraph import expand_subgraphs
from gen_dsp.graph.toposort import toposort
from gen_dsp.graph.validate import validate_graph

_Writer = Callable[[str], None]

_C_ID_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_BINOP_SYMBOLS: dict[str, str] = {
    "add": "+",
    "sub": "-",
    "mul": "*",
    "div": "/",
}

_BINOP_FUNCS: dict[str, str] = {
    "min": "fminf",
    "max": "fmaxf",
    "mod": "fmodf",
    "pow": "powf",
    "atan2": "atan2f",
    "hypot": "hypotf",
}

_UNARYOP_FUNCS: dict[str, str] = {
    "sin": "sinf",
    "cos": "cosf",
    "tanh": "tanhf",
    "exp": "expf",
    "log": "logf",
    "abs": "fabsf",
    "sqrt": "sqrtf",
    "floor": "floorf",
    "ceil": "ceilf",
    "round": "roundf",
    "atan": "atanf",
    "asin": "asinf",
    "acos": "acosf",
    "tan": "tanf",
    "sinh": "sinhf",
    "cosh": "coshf",
    "asinh": "asinhf",
    "acosh": "acoshf",
    "atanh": "atanhf",
    "exp2": "exp2f",
    "log2": "log2f",
    "log10": "log10f",
    "trunc": "truncf",
}

_COMPARE_SYMBOLS: dict[str, str] = {
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
    "eq": "==",
    "neq": "!=",
}

_NAMED_CONSTANT_VALUES: dict[str, float] = {
    "pi": _math.pi,
    "e": _math.e,
    "twopi": 2.0 * _math.pi,
    "halfpi": _math.pi / 2.0,
    "invpi": 1.0 / _math.pi,
    "degtorad": _math.pi / 180.0,
    "radtodeg": 180.0 / _math.pi,
    "sqrt2": _math.sqrt(2.0),
    "sqrt1_2": _math.sqrt(0.5),
    "ln2": _math.log(2.0),
    "ln10": _math.log(10.0),
    "log2e": _math.log2(_math.e),
    "log10e": _math.log10(_math.e),
    "phi": (1.0 + _math.sqrt(5.0)) / 2.0,
}


def _to_pascal(name: str) -> str:
    """Convert underscore_name to PascalCase."""
    return "".join(part.capitalize() for part in name.split("_"))


def _float_lit(v: float) -> str:
    """Format a float as a C literal with 'f' suffix."""
    s = repr(v)
    if "." not in s and "e" not in s and "E" not in s:
        s += ".0"
    return s + "f"


def _emit_ref(ref: str | float, input_ids: set[str], param_names: set[str]) -> str:
    """Emit a C expression for a Ref value."""
    if isinstance(ref, float):
        return _float_lit(ref)
    if ref in input_ids:
        return ref + "[i]"
    # param names and node IDs are both local C variables
    return ref


def compile_graph(graph: Graph) -> str:
    """Compile a DSP graph to standalone C++ source code.

    Raises ValueError if the graph is invalid or contains IDs that are
    not valid C identifiers.
    """
    graph = expand_subgraphs(graph)
    errors = validate_graph(graph)
    if errors:
        raise ValueError("Invalid graph: " + "; ".join(errors))

    # Validate all IDs are valid C identifiers
    all_ids: list[str] = []
    all_ids.extend(inp.id for inp in graph.inputs)
    all_ids.extend(out.id for out in graph.outputs)
    all_ids.extend(p.name for p in graph.params)
    all_ids.extend(node.id for node in graph.nodes)
    for ident in all_ids:
        if not _C_ID_RE.match(ident):
            raise ValueError(f"ID '{ident}' is not a valid C identifier")

    sorted_nodes = toposort(graph)
    input_ids = {inp.id for inp in graph.inputs}
    param_names = {p.name for p in graph.params}

    name = graph.name
    pascal = _to_pascal(name)
    struct_name = pascal + "State"

    lines: list[str] = []
    w = lines.append

    # -- Includes
    w("#include <cmath>")
    w("#include <cstdlib>")
    w("#include <cstdint>")
    w("#include <cstring>")
    w("")

    # -- Struct
    w(f"struct {struct_name} {{")
    w("    float sr;")
    # Params
    for p in graph.params:
        w(f"    float p_{p.name};")
    # State fields from nodes
    for node in sorted_nodes:
        _emit_state_fields(node, w)
    w("};")
    w("")

    # -- create()
    w(f"{struct_name}* {name}_create(float sr) {{")
    w(f"    {struct_name}* self = ({struct_name}*)calloc(1, sizeof({struct_name}));")
    w("    if (!self) return nullptr;")
    w("    self->sr = sr;")
    for p in graph.params:
        w(f"    self->p_{p.name} = {_float_lit(p.default)};")
    for node in sorted_nodes:
        _emit_state_init(node, w)
    w("    return self;")
    w("}")
    w("")

    # -- destroy()
    w(f"void {name}_destroy({struct_name}* self) {{")
    for node in sorted_nodes:
        if isinstance(node, (DelayLine, Buffer)):
            w(f"    free(self->m_{node.id}_buf);")
    w("    free(self);")
    w("}")
    w("")

    # -- reset()
    _emit_reset(graph, sorted_nodes, name, struct_name, w)
    w("")

    # -- perform()
    _emit_perform(graph, sorted_nodes, input_ids, param_names, name, struct_name, w)
    w("")

    # -- Introspection
    w(f"int {name}_num_inputs(void) {{ return {len(graph.inputs)}; }}")
    w(f"int {name}_num_outputs(void) {{ return {len(graph.outputs)}; }}")
    w(f"int {name}_num_params(void) {{ return {len(graph.params)}; }}")
    w("")

    # -- param_name
    _emit_param_name(graph.params, name, struct_name, w)
    w("")

    # -- param_min / param_max
    _emit_param_minmax(graph.params, name, struct_name, "min", w)
    w("")
    _emit_param_minmax(graph.params, name, struct_name, "max", w)
    w("")

    # -- set_param / get_param
    _emit_param_set(graph.params, name, struct_name, w)
    w("")
    _emit_param_get(graph.params, name, struct_name, w)
    w("")

    # -- Buffer API
    buffer_nodes = [n for n in sorted_nodes if isinstance(n, Buffer)]
    _emit_buffer_api(buffer_nodes, name, struct_name, w)

    # -- Peek API
    peek_nodes = [n for n in sorted_nodes if isinstance(n, Peek)]
    _emit_peek_api(peek_nodes, name, struct_name, w)

    return "\n".join(lines) + "\n"


def compile_graph_to_file(graph: Graph, output_dir: str | Path) -> Path:
    """Compile a DSP graph and write {name}.cpp to output_dir.

    Creates the output directory if it doesn't exist.
    Returns the path to the written file.
    """
    code = compile_graph(graph)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{graph.name}.cpp"
    path.write_text(code)
    return path


# ---------------------------------------------------------------------------
# Struct field emission
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Per-node state emitters
#
# Each stateful node type maps to a _StateEmitter describing its contribution to
# the five state passes: struct fields, create()-time init, reset(), and the
# per-sample load/save of perform() locals. Keeping all five in one place per
# node type means adding a stateful node is a single registry entry instead of
# five coordinated edits across the file.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StateField:
    """One scalar struct member of a stateful node.

    suffix: name suffix appended to the node id ("" for History).
    ctype:  C type of the struct member and its perform-loop local.
    init:   value assigned in create(); a literal, a callable(node) -> literal,
            or None to rely on the calloc-zeroed struct.
    reset:  value assigned in reset(); same forms, None to skip.
    save:   whether the perform-loop local is written back to the struct.
    """

    suffix: str
    ctype: str
    init: str | Callable[[Node], str] | None
    reset: str | Callable[[Node], str] | None
    save: bool = True


def _state_value(v: str | Callable[[Node], str], node: Node) -> str:
    return v(node) if callable(v) else v


class _StateEmitter:
    """Base state emitter; each method returns the lines for one pass."""

    def fields(self, node: Node) -> list[str]:
        return []

    def init(self, node: Node) -> list[str]:
        return []

    def reset(self, node: Node) -> list[str]:
        return []

    def load(self, node: Node) -> list[str]:
        return []

    def save(self, node: Node) -> list[str]:
        return []


class _FieldState(_StateEmitter):
    """State emitter for node types whose state is a list of scalar fields."""

    def __init__(self, *fields: _StateField) -> None:
        self._fields = fields

    def fields(self, node: Node) -> list[str]:
        return [f"    {f.ctype} m_{node.id}{f.suffix};" for f in self._fields]

    def init(self, node: Node) -> list[str]:
        return [
            f"    self->m_{node.id}{f.suffix} = {_state_value(f.init, node)};"
            for f in self._fields
            if f.init is not None
        ]

    def reset(self, node: Node) -> list[str]:
        return [
            f"    self->m_{node.id}{f.suffix} = {_state_value(f.reset, node)};"
            for f in self._fields
            if f.reset is not None
        ]

    def load(self, node: Node) -> list[str]:
        return [
            f"    {f.ctype} {node.id}{f.suffix} = self->m_{node.id}{f.suffix};"
            for f in self._fields
        ]

    def save(self, node: Node) -> list[str]:
        return [
            f"    self->m_{node.id}{f.suffix} = {node.id}{f.suffix};"
            for f in self._fields
            if f.save
        ]


class _DelayLineState(_StateEmitter):
    """A ring buffer: pointer + length + write index (only the index is saved)."""

    def fields(self, node: Node) -> list[str]:
        return [
            f"    float* m_{node.id}_buf;",
            f"    int m_{node.id}_len;",
            f"    int m_{node.id}_wr;",
        ]

    def init(self, node: Node) -> list[str]:
        assert isinstance(node, DelayLine)
        return [
            f"    self->m_{node.id}_len = {node.max_samples};",
            f"    self->m_{node.id}_buf = (float*)calloc({node.max_samples}, sizeof(float));",
            f"    self->m_{node.id}_wr = 0;",
        ]

    def reset(self, node: Node) -> list[str]:
        return [
            f"    memset(self->m_{node.id}_buf, 0, self->m_{node.id}_len * sizeof(float));",
            f"    self->m_{node.id}_wr = 0;",
        ]

    def load(self, node: Node) -> list[str]:
        return [
            f"    float* {node.id}_buf = self->m_{node.id}_buf;",
            f"    int {node.id}_len = self->m_{node.id}_len;",
            f"    int {node.id}_wr = self->m_{node.id}_wr;",
        ]

    def save(self, node: Node) -> list[str]:
        return [f"    self->m_{node.id}_wr = {node.id}_wr;"]


class _BufferState(_StateEmitter):
    """A fixed table: pointer + length, optionally sine-filled; never saved."""

    def fields(self, node: Node) -> list[str]:
        return [f"    float* m_{node.id}_buf;", f"    int m_{node.id}_len;"]

    def init(self, node: Node) -> list[str]:
        assert isinstance(node, Buffer)
        lines = [
            f"    self->m_{node.id}_len = {node.size};",
            f"    self->m_{node.id}_buf = (float*)calloc({node.size}, sizeof(float));",
        ]
        if node.fill == "sine":
            lines.append(f"    for (int _k = 0; _k < {node.size}; _k++)")
            lines.append(
                f"        self->m_{node.id}_buf[_k] = sinf(2.0f * 3.14159265f * (float)_k / (float){node.size});"
            )
        return lines

    def reset(self, node: Node) -> list[str]:
        assert isinstance(node, Buffer)
        if node.fill == "sine":
            return [
                f"    for (int _k = 0; _k < self->m_{node.id}_len; _k++)",
                f"        self->m_{node.id}_buf[_k] = sinf(2.0f * 3.14159265f * (float)_k / (float)self->m_{node.id}_len);",
            ]
        return [
            f"    memset(self->m_{node.id}_buf, 0, self->m_{node.id}_len * sizeof(float));"
        ]

    def load(self, node: Node) -> list[str]:
        return [
            f"    float* {node.id}_buf = self->m_{node.id}_buf;",
            f"    int {node.id}_len = self->m_{node.id}_len;",
        ]


def _history_init_value(node: Node) -> str:
    assert isinstance(node, History)
    return _float_lit(node.init)


# Shared emitters for node types with identical state shapes.
_S_PHASE = _FieldState(_StateField("_phase", "float", None, "0.0f"))
_S_PREV = _FieldState(_StateField("_prev", "float", "0.0f", "0.0f"))
_S_BIQUAD = _FieldState(
    _StateField("_s1", "float", "0.0f", "0.0f"),
    _StateField("_s2", "float", "0.0f", "0.0f"),
)
_S_DCBLOCK = _FieldState(
    _StateField("_xprev", "float", "0.0f", "0.0f"),
    _StateField("_yprev", "float", "0.0f", "0.0f"),
)
_S_SAMPLEHOLD = _FieldState(
    _StateField("_held", "float", "0.0f", "0.0f"),
    _StateField("_ptrig", "float", "0.0f", "0.0f"),
)


# Maps each own-state node type to its emitter. Types that participate in
# stateful semantics but store no state of their own (they reference a
# DelayLine/Buffer) are listed in _STATE_BY_REFERENCE below.
_STATE_EMITTERS: dict[type, _StateEmitter] = {
    History: _FieldState(
        _StateField("", "float", _history_init_value, _history_init_value)
    ),
    DelayLine: _DelayLineState(),
    Buffer: _BufferState(),
    Phasor: _S_PHASE,
    SinOsc: _S_PHASE,
    TriOsc: _S_PHASE,
    SawOsc: _S_PHASE,
    PulseOsc: _S_PHASE,
    Noise: _FieldState(_StateField("_seed", "uint32_t", "123456789u", "123456789u")),
    Delta: _S_PREV,
    Change: _S_PREV,
    OnePole: _S_PREV,
    SmoothParam: _S_PREV,
    Slide: _S_PREV,
    Biquad: _S_BIQUAD,
    SVF: _S_BIQUAD,
    DCBlock: _S_DCBLOCK,
    Allpass: _S_DCBLOCK,
    SampleHold: _S_SAMPLEHOLD,
    Latch: _S_SAMPLEHOLD,
    Accum: _FieldState(_StateField("_sum", "float", None, "0.0f")),
    Counter: _FieldState(
        _StateField("_count", "int", None, "0"),
        _StateField("_ptrig", "float", None, "0.0f"),
    ),
    Elapsed: _FieldState(_StateField("_count", "int", None, "0")),
    MulAccum: _FieldState(_StateField("_prod", "float", "1.0f", "1.0f")),
    RateDiv: _FieldState(
        _StateField("_count", "int", "0", "0"),
        _StateField("_held", "float", "0.0f", "0.0f"),
    ),
    ADSR: _FieldState(
        _StateField("_phase", "int", "0", "0"),
        _StateField("_output", "float", "0.0f", "0.0f"),
        _StateField("_ptrig", "float", "0.0f", "0.0f"),
    ),
    Peek: _FieldState(_StateField("_value", "float", "0.0f", "0.0f")),
}

# Stateful node types that store no state of their own -- they read/write the
# state of a DelayLine or Buffer they reference. Listing them keeps the
# exhaustiveness check below honest without requiring an empty emitter each.
_STATE_BY_REFERENCE: frozenset[type] = frozenset(
    {DelayRead, DelayWrite, BufRead, BufWrite, Splat, Cycle, Wave, Lookup}
)

# Fail loudly at import if a stateful node type has neither an emitter nor an
# explicit by-reference declaration (e.g. a new node type added to the model
# and to _STATEFUL_TYPES but missing its state handling here).
_unhandled_stateful = [
    t
    for t in _STATEFUL_TYPES
    if t not in _STATE_EMITTERS and t not in _STATE_BY_REFERENCE
]
assert not _unhandled_stateful, (
    "state emitter registry out of sync with _STATEFUL_TYPES: "
    f"{_unhandled_stateful} unhandled"
)


def _emit_state_fields(node: Node, w: _Writer) -> None:
    emitter = _STATE_EMITTERS.get(type(node))
    if emitter is not None:
        for line in emitter.fields(node):
            w(line)


def _emit_state_init(node: Node, w: _Writer) -> None:
    emitter = _STATE_EMITTERS.get(type(node))
    if emitter is not None:
        for line in emitter.init(node):
            w(line)


def _emit_state_reset(node: Node, w: _Writer) -> None:
    emitter = _STATE_EMITTERS.get(type(node))
    if emitter is not None:
        for line in emitter.reset(node):
            w(line)


def _emit_state_load(node: Node, w: _Writer) -> None:
    emitter = _STATE_EMITTERS.get(type(node))
    if emitter is not None:
        for line in emitter.load(node):
            w(line)


def _emit_state_save(node: Node, w: _Writer) -> None:
    emitter = _STATE_EMITTERS.get(type(node))
    if emitter is not None:
        for line in emitter.save(node):
            w(line)


# ---------------------------------------------------------------------------
# reset() -- reinitialize state to creation defaults without reallocating
# ---------------------------------------------------------------------------


def _emit_reset(
    graph: Graph,
    sorted_nodes: list[Node],
    name: str,
    struct_name: str,
    w: _Writer,
) -> None:
    w(f"void {name}_reset({struct_name}* self) {{")
    # Reset params to defaults
    for p in graph.params:
        w(f"    self->p_{p.name} = {_float_lit(p.default)};")
    # Reset node state
    for node in sorted_nodes:
        _emit_state_reset(node, w)
    w("}")


# ---------------------------------------------------------------------------
# perform() body
# ---------------------------------------------------------------------------


_NON_REF_FIELDS = frozenset({"id", "op", "interp", "mode", "count", "channel"})


def _classify_loop_invariance(
    sorted_nodes: list[Node],
    input_ids: set[str],
    param_names: set[str],
) -> set[str]:
    """Return the set of node IDs whose computations are loop-invariant.

    A pure node is loop-invariant if ALL its Ref fields resolve (transitively)
    to params, literal floats, or other invariant nodes -- never to audio inputs
    or stateful nodes.
    """
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
                if value in param_names:
                    continue
                if value in invariant_ids:
                    continue
                is_invariant = False
                break

        if is_invariant:
            invariant_ids.add(node.id)

    return invariant_ids


def _classify_control_rate(
    sorted_nodes: list[Node],
    control_node_ids: set[str],
    invariant_ids: set[str],
) -> set[str]:
    """Return node IDs that should run at control rate.

    Nodes listed in control_node_ids that are already invariant stay hoisted
    (they don't need to be in the control-rate tier).
    """
    return control_node_ids - invariant_ids


def _indent_line(line: str, extra: int) -> str:
    """Add *extra* spaces of indentation to a line."""
    return " " * extra + line


def _emit_perform(
    graph: Graph,
    sorted_nodes: list[Node],
    input_ids: set[str],
    param_names: set[str],
    name: str,
    struct_name: str,
    w: _Writer,
) -> None:
    w(f"void {name}_perform({struct_name}* self, float** ins, float** outs, int n) {{")

    # Unpack I/O pointers with __restrict
    for idx, inp in enumerate(graph.inputs):
        w(f"    float* __restrict {inp.id} = ins[{idx}];")
    for idx, out in enumerate(graph.outputs):
        w(f"    float* __restrict {out.id} = outs[{idx}];")

    # Load params to locals
    for p in graph.params:
        w(f"    float {p.name} = self->p_{p.name};")

    # Load state to locals
    for node in sorted_nodes:
        _emit_state_load(node, w)

    w("    float sr = self->sr;")

    # Classify loop invariance
    invariant_ids = _classify_loop_invariance(sorted_nodes, input_ids, param_names)

    # Emit hoisted (loop-invariant) computations before the loop
    hoisted_history: list[History] = []
    hoisted_dw: list[DelayWrite] = []
    for node in sorted_nodes:
        if node.id in invariant_ids:
            hoisted_lines: list[str] = []
            _emit_node_compute(
                node,
                input_ids,
                param_names,
                hoisted_lines.append,
                hoisted_history,
                hoisted_dw,
            )
            for line in hoisted_lines:
                # Strip 4 leading spaces: 8-space indent -> 4-space indent
                if line.startswith("        "):
                    w(line[4:])
                else:
                    w(line)

    ctrl_interval = graph.control_interval
    ctrl_node_ids = set(graph.control_nodes) if ctrl_interval > 0 else set()
    ctrl_rate_ids = _classify_control_rate(sorted_nodes, ctrl_node_ids, invariant_ids)

    if ctrl_interval > 0 and ctrl_rate_ids:
        _emit_perform_two_tier(
            graph,
            sorted_nodes,
            input_ids,
            param_names,
            invariant_ids,
            ctrl_rate_ids,
            ctrl_interval,
            w,
        )
    else:
        _emit_perform_single(
            graph,
            sorted_nodes,
            input_ids,
            param_names,
            invariant_ids,
            w,
        )

    # Save state back
    for node in sorted_nodes:
        _emit_state_save(node, w)

    w("}")


def _emit_perform_single(
    graph: Graph,
    sorted_nodes: list[Node],
    input_ids: set[str],
    param_names: set[str],
    invariant_ids: set[str],
    w: _Writer,
) -> None:
    """Emit the single-loop perform body (no control-rate tier)."""
    # Vectorization pragma -- only when no stateful nodes exist
    has_stateful = any(isinstance(n, _STATEFUL_TYPES) for n in sorted_nodes)
    if not has_stateful:
        w("#if defined(__clang__)")
        w("    #pragma clang loop vectorize(enable) interleave(enable)")
        w("#elif defined(__GNUC__)")
        w("    #pragma GCC ivdep")
        w("#endif")

    w("    for (int i = 0; i < n; i++) {")

    # Topo-sorted node computations (variant nodes only)
    history_nodes: list[History] = []
    delay_write_nodes: list[DelayWrite] = []
    for node in sorted_nodes:
        if node.id not in invariant_ids:
            _emit_node_compute(
                node, input_ids, param_names, w, history_nodes, delay_write_nodes
            )

    # History write-backs
    for h in history_nodes:
        ref = _emit_ref(h.input, input_ids, param_names)
        w(f"        {h.id} = {ref};")

    # Output assignments
    for out in graph.outputs:
        w(f"        {out.id}[i] = {out.source};")

    w("    }")


def _emit_perform_two_tier(
    graph: Graph,
    sorted_nodes: list[Node],
    input_ids: set[str],
    param_names: set[str],
    invariant_ids: set[str],
    ctrl_rate_ids: set[str],
    ctrl_interval: int,
    w: _Writer,
) -> None:
    """Emit the two-tier (control-rate / audio-rate) perform body."""
    # Outer loop: control blocks
    w(f"    for (int _cb = 0; _cb < n; _cb += {ctrl_interval}) {{")
    w(
        f"        int _block_end = (_cb + {ctrl_interval} < n) ? _cb + {ctrl_interval} : n;"
    )

    # Control-rate nodes (8-space indent = inside outer loop)
    ctrl_history: list[History] = []
    ctrl_dw: list[DelayWrite] = []
    for node in sorted_nodes:
        if node.id in ctrl_rate_ids:
            _emit_node_compute(node, input_ids, param_names, w, ctrl_history, ctrl_dw)

    # Inner loop: audio-rate per-sample
    w("        for (int i = _cb; i < _block_end; i++) {")

    # Audio-rate nodes (12-space indent = inside inner loop)
    audio_history: list[History] = []
    audio_dw: list[DelayWrite] = []
    for node in sorted_nodes:
        if node.id not in invariant_ids and node.id not in ctrl_rate_ids:
            # Collect lines at standard 8-space indent, then add 4 more
            node_lines: list[str] = []
            _emit_node_compute(
                node,
                input_ids,
                param_names,
                node_lines.append,
                audio_history,
                audio_dw,
            )
            for line in node_lines:
                w(_indent_line(line, 4))

    # Audio-rate History write-backs (12-space indent)
    for h in audio_history:
        ref = _emit_ref(h.input, input_ids, param_names)
        w(f"            {h.id} = {ref};")

    # Output assignments (12-space indent)
    for out in graph.outputs:
        w(f"            {out.id}[i] = {out.source};")

    # Close inner loop
    w("        }")

    # Control-rate History write-backs (8-space indent)
    for h in ctrl_history:
        ref = _emit_ref(h.input, input_ids, param_names)
        w(f"        {h.id} = {ref};")

    # Close outer loop
    w("    }")


def _emit_node_compute(
    node: Node,
    input_ids: set[str],
    param_names: set[str],
    w: _Writer,
    history_nodes: list[History],
    delay_write_nodes: list[DelayWrite],
) -> None:
    def ref(r: str | float) -> str:
        return _emit_ref(r, input_ids, param_names)

    if isinstance(node, BinOp):
        if node.op in _BINOP_FUNCS:
            func = _BINOP_FUNCS[node.op]
            w(f"        float {node.id} = {func}({ref(node.a)}, {ref(node.b)});")
        elif node.op == "absdiff":
            w(f"        float {node.id} = fabsf({ref(node.a)} - {ref(node.b)});")
        elif node.op == "step":
            w(
                f"        float {node.id} = ({ref(node.a)} >= {ref(node.b)}) ? 1.0f : 0.0f;"
            )
        elif node.op == "and":
            w(
                f"        float {node.id} = (float)({ref(node.a)} != 0.0f && {ref(node.b)} != 0.0f);"
            )
        elif node.op == "or":
            w(
                f"        float {node.id} = (float)({ref(node.a)} != 0.0f || {ref(node.b)} != 0.0f);"
            )
        elif node.op == "xor":
            w(
                f"        float {node.id} = (float)(({ref(node.a)} != 0.0f) != ({ref(node.b)} != 0.0f));"
            )
        elif node.op == "rsub":
            w(f"        float {node.id} = {ref(node.b)} - {ref(node.a)};")
        elif node.op == "rdiv":
            w(f"        float {node.id} = {ref(node.b)} / {ref(node.a)};")
        elif node.op == "rmod":
            w(f"        float {node.id} = fmodf({ref(node.b)}, {ref(node.a)});")
        elif node.op == "gtp":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} > {b}) ? {a} : 0.0f;")
        elif node.op == "ltp":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} < {b}) ? {a} : 0.0f;")
        elif node.op == "gtep":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} >= {b}) ? {a} : 0.0f;")
        elif node.op == "ltep":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} <= {b}) ? {a} : 0.0f;")
        elif node.op == "eqp":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} == {b}) ? {a} : 0.0f;")
        elif node.op == "neqp":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} != {b}) ? {a} : 0.0f;")
        elif node.op == "fastpow":
            w(f"        float {node.id} = exp2f({ref(node.b)} * log2f({ref(node.a)}));")
        else:
            sym = _BINOP_SYMBOLS[node.op]
            w(f"        float {node.id} = {ref(node.a)} {sym} {ref(node.b)};")

    elif isinstance(node, UnaryOp):
        if node.op == "neg":
            w(f"        float {node.id} = -{ref(node.a)};")
        elif node.op == "sign":
            a = ref(node.a)
            w(
                f"        float {node.id} = ({a} > 0.0f ? 1.0f : ({a} < 0.0f ? -1.0f : 0.0f));"
            )
        elif node.op == "fract":
            a = ref(node.a)
            w(f"        float {node.id} = {a} - floorf({a});")
        elif node.op == "not":
            w(f"        float {node.id} = (float)({ref(node.a)} == 0.0f);")
        elif node.op == "bool":
            w(f"        float {node.id} = (float)({ref(node.a)} != 0.0f);")
        elif node.op == "mtof":
            a = ref(node.a)
            w(f"        float {node.id} = 440.0f * powf(2.0f, ({a} - 69.0f) / 12.0f);")
        elif node.op == "ftom":
            a = ref(node.a)
            w(
                f"        float {node.id} = 69.0f + 12.0f * log2f(fmaxf({a}, 1e-10f) / 440.0f);"
            )
        elif node.op == "atodb":
            a = ref(node.a)
            w(f"        float {node.id} = 20.0f * log10f(fmaxf({a}, 1e-10f));")
        elif node.op == "dbtoa":
            a = ref(node.a)
            w(f"        float {node.id} = powf(10.0f, {a} / 20.0f);")
        elif node.op == "phasewrap":
            a = ref(node.a)
            w(
                f"        float {node.id} = {a} - 6.28318530f * floorf({a} * 0.15915494f + 0.5f);"
            )
        elif node.op == "degrees":
            w(f"        float {node.id} = {ref(node.a)} * 57.29577951f;")
        elif node.op == "radians":
            w(f"        float {node.id} = {ref(node.a)} * 0.01745329f;")
        elif node.op == "mstosamps":
            w(f"        float {node.id} = {ref(node.a)} * sr / 1000.0f;")
        elif node.op == "sampstoms":
            w(f"        float {node.id} = {ref(node.a)} * 1000.0f / sr;")
        elif node.op == "t60":
            a = ref(node.a)
            w(f"        float {node.id} = expf(-6.9078f / ({a} * sr));")
        elif node.op == "t60time":
            a = ref(node.a)
            w(f"        float {node.id} = -6.9078f / (logf({a}) * sr);")
        elif node.op == "fixdenorm":
            a = ref(node.a)
            w(f"        float {node.id} = (fabsf({a}) < 1e-18f) ? 0.0f : {a};")
        elif node.op == "fixnan":
            a = ref(node.a)
            w(f"        float {node.id} = ({a} != {a}) ? 0.0f : {a};")
        elif node.op == "isdenorm":
            a = ref(node.a)
            w(
                f"        float {node.id} = (fabsf({a}) < 1e-18f && {a} != 0.0f) ? 1.0f : 0.0f;"
            )
        elif node.op == "isnan":
            a = ref(node.a)
            w(f"        float {node.id} = ({a} != {a}) ? 1.0f : 0.0f;")
        elif node.op == "fastsin":
            a = ref(node.a)
            # Bhaskara I approximation: 16x(pi-x) / (5pi^2 - 4x(pi-x))
            # First wrap to [0, pi] via abs(phasewrap)
            w(
                f"        float {node.id}_x = {a} - 6.28318530f * floorf({a} * 0.15915494f + 0.5f);"
            )
            w(f"        float {node.id}_sign = ({node.id}_x < 0.0f) ? -1.0f : 1.0f;")
            w(f"        float {node.id}_ax = fabsf({node.id}_x);")
            w(f"        float {node.id}_pma = 3.14159265f - {node.id}_ax;")
            w(
                f"        float {node.id} = {node.id}_sign * 16.0f * {node.id}_ax * {node.id}_pma / (49.3480220f - 4.0f * {node.id}_ax * {node.id}_pma);"
            )
        elif node.op == "fastcos":
            a = ref(node.a)
            # fastcos(x) = fastsin(x + pi/2)
            w(f"        float {node.id}_sh = {a} + 1.57079633f;")
            w(
                f"        float {node.id}_x = {node.id}_sh - 6.28318530f * floorf({node.id}_sh * 0.15915494f + 0.5f);"
            )
            w(f"        float {node.id}_sign = ({node.id}_x < 0.0f) ? -1.0f : 1.0f;")
            w(f"        float {node.id}_ax = fabsf({node.id}_x);")
            w(f"        float {node.id}_pma = 3.14159265f - {node.id}_ax;")
            w(
                f"        float {node.id} = {node.id}_sign * 16.0f * {node.id}_ax * {node.id}_pma / (49.3480220f - 4.0f * {node.id}_ax * {node.id}_pma);"
            )
        elif node.op == "fasttan":
            a = ref(node.a)
            w(f"        float {node.id} = sinf({a}) / cosf({a});")
        elif node.op == "fastexp":
            a = ref(node.a)
            # Schraudolph's method
            w(f"        union {{ float f; int32_t i; }} {node.id}_u;")
            w(f"        {node.id}_u.i = (int32_t)(12102203.0f * {a} + 1065353216.0f);")
            w(f"        float {node.id} = {node.id}_u.f;")
        else:
            func = _UNARYOP_FUNCS[node.op]
            w(f"        float {node.id} = {func}({ref(node.a)});")

    elif isinstance(node, Clamp):
        a, lo, hi = ref(node.a), ref(node.lo), ref(node.hi)
        w(f"        float {node.id} = fminf(fmaxf({a}, {lo}), {hi});")

    elif isinstance(node, Constant):
        w(f"        float {node.id} = {_float_lit(node.value)};")

    elif isinstance(node, History):
        # Value already loaded pre-loop; track for write-back
        history_nodes.append(node)

    elif isinstance(node, DelayLine):
        # State-only node, no per-sample computation
        pass

    elif isinstance(node, DelayRead):
        dl = node.delay
        tap = ref(node.tap)
        if node.interp == "none":
            w(
                f"        int {node.id}_pos = "
                f"(({dl}_wr - (int)({tap})) % {dl}_len + {dl}_len) % {dl}_len;"
            )
            w(f"        float {node.id} = {dl}_buf[{node.id}_pos];")
        elif node.interp == "linear":
            nid = node.id
            _emit_interp_linear(nid, dl, tap, w)
        elif node.interp == "cubic":
            nid = node.id
            _emit_interp_cubic(nid, dl, tap, w)

    elif isinstance(node, DelayWrite):
        delay_write_nodes.append(node)
        val = ref(node.value)
        w(f"        {node.delay}_buf[{node.delay}_wr] = {val};")
        w(f"        {node.delay}_wr = ({node.delay}_wr + 1) % {node.delay}_len;")

    elif isinstance(node, Phasor):
        freq = ref(node.freq)
        w(f"        float {node.id} = {node.id}_phase;")
        w(f"        {node.id}_phase += {freq} / sr;")
        w(f"        if ({node.id}_phase >= 1.0f) {node.id}_phase -= 1.0f;")

    elif isinstance(node, Noise):
        w(f"        {node.id}_seed = {node.id}_seed * 1664525u + 1013904223u;")
        w(f"        float {node.id} = (float)(int32_t){node.id}_seed / 2147483648.0f;")

    elif isinstance(node, Compare):
        sym = _COMPARE_SYMBOLS[node.op]
        w(f"        float {node.id} = (float)({ref(node.a)} {sym} {ref(node.b)});")

    elif isinstance(node, Select):
        w(
            f"        float {node.id} = {ref(node.cond)} > 0.0f ? {ref(node.a)} : {ref(node.b)};"
        )

    elif isinstance(node, Wrap):
        nid = node.id
        a, lo, hi = ref(node.a), ref(node.lo), ref(node.hi)
        w(f"        float {nid}_range = {hi} - {lo};")
        w(f"        float {nid}_raw = fmodf({a} - {lo}, {nid}_range);")
        raw_expr = f"{nid}_raw < 0.0f ? {nid}_raw + {nid}_range : {nid}_raw"
        w(f"        float {nid} = {lo} + ({raw_expr});")

    elif isinstance(node, Fold):
        nid = node.id
        a, lo, hi = ref(node.a), ref(node.lo), ref(node.hi)
        w(f"        float {nid}_range = {hi} - {lo};")
        w(f"        float {nid}_t = fmodf({a} - {lo}, 2.0f * {nid}_range);")
        w(f"        if ({nid}_t < 0.0f) {nid}_t += 2.0f * {nid}_range;")
        lo_branch = f"{lo} + {nid}_t"
        hi_branch = f"{hi} - ({nid}_t - {nid}_range)"
        w(f"        float {nid} = {nid}_t <= {nid}_range ? {lo_branch} : {hi_branch};")

    elif isinstance(node, Mix):
        a_r, b_r, t_r = ref(node.a), ref(node.b), ref(node.t)
        w(f"        float {node.id} = {a_r} + ({b_r} - {a_r}) * {t_r};")

    elif isinstance(node, Delta):
        nid = node.id
        a = ref(node.a)
        w(f"        float {nid}_cur = {a};")
        w(f"        float {nid} = {nid}_cur - {nid}_prev;")
        w(f"        {nid}_prev = {nid}_cur;")

    elif isinstance(node, Change):
        nid = node.id
        a = ref(node.a)
        w(f"        float {nid}_cur = {a};")
        w(f"        float {nid} = ({nid}_cur != {nid}_prev) ? 1.0f : 0.0f;")
        w(f"        {nid}_prev = {nid}_cur;")

    elif isinstance(node, Biquad):
        nid = node.id
        a = ref(node.a)
        b0 = ref(node.b0)
        b1 = ref(node.b1)
        b2 = ref(node.b2)
        a1 = ref(node.a1)
        a2 = ref(node.a2)
        w(f"        float {nid}_in = {a};")
        w(f"        float {nid} = {b0} * {nid}_in + {nid}_s1;")
        w(f"        {nid}_s1 = {b1} * {nid}_in - {a1} * {nid} + {nid}_s2;")
        w(f"        {nid}_s2 = {b2} * {nid}_in - {a2} * {nid};")

    elif isinstance(node, SVF):
        nid = node.id
        a = ref(node.a)
        freq = ref(node.freq)
        q = ref(node.q)
        w(f"        float {nid}_g = tanf(3.14159265f * {freq} / sr);")
        w(f"        float {nid}_k = 1.0f / {q};")
        w(f"        float {nid}_a1 = 1.0f / (1.0f + {nid}_g * ({nid}_g + {nid}_k));")
        w(f"        float {nid}_a2 = {nid}_g * {nid}_a1;")
        w(f"        float {nid}_a3 = {nid}_g * {nid}_a2;")
        w(f"        float {nid}_v3 = {a} - {nid}_s2;")
        w(f"        float {nid}_v1 = {nid}_a1 * {nid}_s1 + {nid}_a2 * {nid}_v3;")
        w(
            f"        float {nid}_v2 = {nid}_s2 + {nid}_a2 * {nid}_s1 + {nid}_a3 * {nid}_v3;"
        )
        w(f"        {nid}_s1 = 2.0f * {nid}_v1 - {nid}_s1;")
        w(f"        {nid}_s2 = 2.0f * {nid}_v2 - {nid}_s2;")
        if node.mode == "lp":
            w(f"        float {nid} = {nid}_v2;")
        elif node.mode == "hp":
            w(f"        float {nid} = {a} - {nid}_k * {nid}_v1 - {nid}_v2;")
        elif node.mode == "bp":
            w(f"        float {nid} = {nid}_v1;")
        elif node.mode == "notch":
            w(f"        float {nid} = {a} - {nid}_k * {nid}_v1;")

    elif isinstance(node, OnePole):
        nid = node.id
        a = ref(node.a)
        c = ref(node.coeff)
        w(f"        float {nid} = {c} * {a} + (1.0f - {c}) * {nid}_prev;")
        w(f"        {nid}_prev = {nid};")

    elif isinstance(node, DCBlock):
        nid = node.id
        a = ref(node.a)
        w(f"        float {nid}_x = {a};")
        w(f"        float {nid} = {nid}_x - {nid}_xprev + 0.995f * {nid}_yprev;")
        w(f"        {nid}_xprev = {nid}_x;")
        w(f"        {nid}_yprev = {nid};")

    elif isinstance(node, Allpass):
        nid = node.id
        a = ref(node.a)
        c = ref(node.coeff)
        w(f"        float {nid}_x = {a};")
        w(f"        float {nid} = {c} * ({nid}_x - {nid}_yprev) + {nid}_xprev;")
        w(f"        {nid}_xprev = {nid}_x;")
        w(f"        {nid}_yprev = {nid};")

    elif isinstance(node, SinOsc):
        nid = node.id
        freq = ref(node.freq)
        w(f"        float {nid} = sinf(6.28318530f * {nid}_phase);")
        w(f"        {nid}_phase += {freq} / sr;")
        w(f"        if ({nid}_phase >= 1.0f) {nid}_phase -= 1.0f;")

    elif isinstance(node, TriOsc):
        nid = node.id
        freq = ref(node.freq)
        w(f"        float {nid} = 4.0f * fabsf({nid}_phase - 0.5f) - 1.0f;")
        w(f"        {nid}_phase += {freq} / sr;")
        w(f"        if ({nid}_phase >= 1.0f) {nid}_phase -= 1.0f;")

    elif isinstance(node, SawOsc):
        nid = node.id
        freq = ref(node.freq)
        w(f"        float {nid} = 2.0f * {nid}_phase - 1.0f;")
        w(f"        {nid}_phase += {freq} / sr;")
        w(f"        if ({nid}_phase >= 1.0f) {nid}_phase -= 1.0f;")

    elif isinstance(node, PulseOsc):
        nid = node.id
        freq = ref(node.freq)
        width = ref(node.width)
        w(f"        float {nid} = {nid}_phase < {width} ? 1.0f : -1.0f;")
        w(f"        {nid}_phase += {freq} / sr;")
        w(f"        if ({nid}_phase >= 1.0f) {nid}_phase -= 1.0f;")

    elif isinstance(node, SampleHold):
        nid = node.id
        a = ref(node.a)
        t = ref(node.trig)
        w(f"        float {nid}_t = {t};")
        w(
            f"        if (({nid}_ptrig <= 0.0f && {nid}_t > 0.0f) ||"
            f" ({nid}_ptrig > 0.0f && {nid}_t <= 0.0f))"
        )
        w(f"            {nid}_held = {a};")
        w(f"        {nid}_ptrig = {nid}_t;")
        w(f"        float {nid} = {nid}_held;")

    elif isinstance(node, Latch):
        nid = node.id
        a = ref(node.a)
        t = ref(node.trig)
        w(f"        float {nid}_t = {t};")
        w(f"        if ({nid}_ptrig <= 0.0f && {nid}_t > 0.0f)")
        w(f"            {nid}_held = {a};")
        w(f"        {nid}_ptrig = {nid}_t;")
        w(f"        float {nid} = {nid}_held;")

    elif isinstance(node, Accum):
        nid = node.id
        incr = ref(node.incr)
        reset = ref(node.reset)
        w(f"        if ({reset} > 0.0f) {nid}_sum = 0.0f;")
        w(f"        {nid}_sum += {incr};")
        w(f"        float {nid} = {nid}_sum;")

    elif isinstance(node, Counter):
        nid = node.id
        t = ref(node.trig)
        mx = ref(node.max)
        w(f"        float {nid}_t = {t};")
        w(f"        if ({nid}_ptrig <= 0.0f && {nid}_t > 0.0f) {{")
        w(f"            {nid}_count++;")
        w(f"            if ({nid}_count >= (int){mx}) {nid}_count = 0;")
        w("        }")
        w(f"        {nid}_ptrig = {nid}_t;")
        w(f"        float {nid} = (float){nid}_count;")

    elif isinstance(node, Elapsed):
        nid = node.id
        w(f"        float {nid} = (float){nid}_count;")
        w(f"        {nid}_count++;")

    elif isinstance(node, MulAccum):
        nid = node.id
        incr = ref(node.incr)
        reset = ref(node.reset)
        w(f"        if ({reset} > 0.0f) {nid}_prod = 1.0f;")
        w(f"        {nid}_prod *= {incr};")
        w(f"        float {nid} = {nid}_prod;")

    elif isinstance(node, Buffer):
        # State-only node, no per-sample computation
        pass

    elif isinstance(node, BufRead):
        nid = node.id
        buf = node.buffer
        idx = ref(node.index)
        if node.interp == "none":
            w(f"        int {nid}_idx = (int)({idx});")
            w(f"        if ({nid}_idx < 0) {nid}_idx = 0;")
            w(f"        if ({nid}_idx >= {buf}_len) {nid}_idx = {buf}_len - 1;")
            w(f"        float {nid} = {buf}_buf[{nid}_idx];")
        elif node.interp == "linear":
            _emit_buf_interp_linear(nid, buf, idx, w)
        elif node.interp == "cubic":
            _emit_buf_interp_cubic(nid, buf, idx, w)

    elif isinstance(node, BufWrite):
        nid = node.id
        buf = node.buffer
        idx = ref(node.index)
        val = ref(node.value)
        w(f"        int {nid}_idx = (int)({idx});")
        w(f"        if ({nid}_idx >= 0 && {nid}_idx < {buf}_len)")
        w(f"            {buf}_buf[{nid}_idx] = {val};")

    elif isinstance(node, Splat):
        nid = node.id
        buf = node.buffer
        idx = ref(node.index)
        val = ref(node.value)
        w(f"        int {nid}_idx = (int)({idx});")
        w(f"        if ({nid}_idx >= 0 && {nid}_idx < {buf}_len)")
        w(f"            {buf}_buf[{nid}_idx] += {val};")

    elif isinstance(node, BufSize):
        w(f"        float {node.id} = (float)self->m_{node.buffer}_len;")

    elif isinstance(node, Cycle):
        nid = node.id
        buf = node.buffer
        phase = ref(node.phase)
        # phase [0,1) wraps, linear interpolation
        w(f"        float {nid}_p = {phase} - floorf({phase});")
        w(f"        float {nid}_fidx = {nid}_p * (float){buf}_len;")
        w(f"        int {nid}_i0 = (int){nid}_fidx;")
        w(f"        float {nid}_frac = {nid}_fidx - (float){nid}_i0;")
        w(f"        int {nid}_i1 = ({nid}_i0 + 1) % {buf}_len;")
        w(f"        {nid}_i0 = {nid}_i0 % {buf}_len;")
        w(
            f"        float {nid} = {buf}_buf[{nid}_i0] + {nid}_frac * ({buf}_buf[{nid}_i1] - {buf}_buf[{nid}_i0]);"
        )

    elif isinstance(node, Wave):
        nid = node.id
        buf = node.buffer
        phase = ref(node.phase)
        # phase [-1,1] maps to [0, len), clamped
        w(f"        float {nid}_norm = ({phase} + 1.0f) * 0.5f;")
        w(f"        float {nid}_fidx = {nid}_norm * (float)({buf}_len - 1);")
        w(f"        if ({nid}_fidx < 0.0f) {nid}_fidx = 0.0f;")
        w(
            f"        if ({nid}_fidx > (float)({buf}_len - 1)) {nid}_fidx = (float)({buf}_len - 1);"
        )
        w(f"        int {nid}_i0 = (int){nid}_fidx;")
        w(f"        float {nid}_frac = {nid}_fidx - (float){nid}_i0;")
        w(f"        int {nid}_i1 = {nid}_i0 + 1;")
        w(f"        if ({nid}_i1 >= {buf}_len) {nid}_i1 = {buf}_len - 1;")
        w(
            f"        float {nid} = {buf}_buf[{nid}_i0] + {nid}_frac * ({buf}_buf[{nid}_i1] - {buf}_buf[{nid}_i0]);"
        )

    elif isinstance(node, Lookup):
        nid = node.id
        buf = node.buffer
        idx = ref(node.index)
        # index [0,1] clamped, linear interpolation
        w(f"        float {nid}_ci = {idx};")
        w(f"        if ({nid}_ci < 0.0f) {nid}_ci = 0.0f;")
        w(f"        if ({nid}_ci > 1.0f) {nid}_ci = 1.0f;")
        w(f"        float {nid}_fidx = {nid}_ci * (float)({buf}_len - 1);")
        w(f"        int {nid}_i0 = (int){nid}_fidx;")
        w(f"        float {nid}_frac = {nid}_fidx - (float){nid}_i0;")
        w(f"        int {nid}_i1 = {nid}_i0 + 1;")
        w(f"        if ({nid}_i1 >= {buf}_len) {nid}_i1 = {buf}_len - 1;")
        w(
            f"        float {nid} = {buf}_buf[{nid}_i0] + {nid}_frac * ({buf}_buf[{nid}_i1] - {buf}_buf[{nid}_i0]);"
        )

    elif isinstance(node, RateDiv):
        nid = node.id
        a = ref(node.a)
        divisor = ref(node.divisor)
        w(f"        if ({nid}_count == 0) {nid}_held = {a};")
        w(f"        {nid}_count++;")
        w(f"        if ({nid}_count >= (int){divisor}) {nid}_count = 0;")
        w(f"        float {nid} = {nid}_held;")

    elif isinstance(node, Scale):
        nid = node.id
        a = ref(node.a)
        in_lo = ref(node.in_lo)
        in_hi = ref(node.in_hi)
        out_lo = ref(node.out_lo)
        out_hi = ref(node.out_hi)
        w(f"        float {nid}_in_range = {in_hi} - {in_lo};")
        w(f"        float {nid}_out_range = {out_hi} - {out_lo};")
        w(
            f"        float {nid} = {out_lo} + ({a} - {in_lo}) / {nid}_in_range * {nid}_out_range;"
        )

    elif isinstance(node, SmoothParam):
        nid = node.id
        a = ref(node.a)
        c = ref(node.coeff)
        w(f"        float {nid} = (1.0f - {c}) * {a} + {c} * {nid}_prev;")
        w(f"        {nid}_prev = {nid};")

    elif isinstance(node, Slide):
        nid = node.id
        a = ref(node.a)
        up = ref(node.up)
        down = ref(node.down)
        w(f"        float {nid}_x = {a};")
        w(f"        float {nid}_s = ({nid}_x > {nid}_prev) ? {up} : {down};")
        w(
            f"        float {nid} = {nid}_prev + ({nid}_x - {nid}_prev) / (({nid}_s > 1.0f) ? {nid}_s : 1.0f);"
        )
        w(f"        {nid}_prev = {nid};")

    elif isinstance(node, ADSR):
        nid = node.id
        gate = ref(node.gate)
        attack = ref(node.attack)
        decay = ref(node.decay)
        sustain = ref(node.sustain)
        release = ref(node.release)
        w(f"        {{ // ADSR {nid}")
        w(f"            float {nid}_gate = {gate};")
        w(f"            float {nid}_sus = {sustain};")
        # Edge detection: gate on
        w(f"            if ({nid}_gate > 0.0f && {nid}_ptrig <= 0.0f) {nid}_phase = 1;")
        # Edge detection: gate off
        w(f"            if ({nid}_gate <= 0.0f && {nid}_ptrig > 0.0f) {nid}_phase = 4;")
        w(f"            {nid}_ptrig = {nid}_gate;")
        # Attack phase
        w(f"            if ({nid}_phase == 1) {{")
        w(f"                float {nid}_a_ms = {attack};")
        w(
            f"                float {nid}_a_samps = fmaxf({nid}_a_ms * sr * 0.001f, 1.0f);"
        )
        w(f"                {nid}_output += 1.0f / {nid}_a_samps;")
        w(
            f"                if ({nid}_output >= 1.0f) {{ {nid}_output = 1.0f; {nid}_phase = 2; }}"
        )
        w("            }")
        # Decay phase
        w(f"            if ({nid}_phase == 2) {{")
        w(f"                float {nid}_d_ms = {decay};")
        w(
            f"                float {nid}_d_samps = fmaxf({nid}_d_ms * sr * 0.001f, 1.0f);"
        )
        w(f"                {nid}_output -= (1.0f - {nid}_sus) / {nid}_d_samps;")
        w(
            f"                if ({nid}_output <= {nid}_sus) {{ {nid}_output = {nid}_sus; {nid}_phase = 3; }}"
        )
        w("            }")
        # Sustain phase
        w(f"            if ({nid}_phase == 3) {nid}_output = {nid}_sus;")
        # Release phase
        w(f"            if ({nid}_phase == 4) {{")
        w(f"                float {nid}_r_ms = {release};")
        w(
            f"                float {nid}_r_samps = fmaxf({nid}_r_ms * sr * 0.001f, 1.0f);"
        )
        w(f"                {nid}_output -= 1.0f / {nid}_r_samps;")
        w(
            f"                if ({nid}_output <= 0.0f) {{ {nid}_output = 0.0f; {nid}_phase = 0; }}"
        )
        w("            }")
        w("        }")
        w(f"        float {nid} = {nid}_output;")

    elif isinstance(node, Peek):
        nid = node.id
        a = ref(node.a)
        w(f"        float {nid} = {a};")
        w(f"        {nid}_value = {nid};")

    elif isinstance(node, Pass):
        w(f"        float {node.id} = {ref(node.a)};")

    elif isinstance(node, NamedConstant):
        w(f"        float {node.id} = {_float_lit(_NAMED_CONSTANT_VALUES[node.op])};")

    elif isinstance(node, SampleRate):
        # `sr` is already declared at perform-function scope (from self->sr),
        # so only emit an alias when the node uses a different id.
        if node.id != "sr":
            w(f"        float {node.id} = sr;")

    elif isinstance(node, Smoothstep):
        nid = node.id
        a = ref(node.a)
        e0 = ref(node.edge0)
        e1 = ref(node.edge1)
        w(
            f"        float {nid}_t = fminf(fmaxf(({a} - {e0}) / ({e1} - {e0}), 0.0f), 1.0f);"
        )
        w(f"        float {nid} = {nid}_t * {nid}_t * (3.0f - 2.0f * {nid}_t);")

    elif isinstance(node, GateRoute):
        nid = node.id
        idx = ref(node.index)
        a = ref(node.a)
        w(f"        int {nid}_idx = (int)({idx});")
        w(f"        if ({nid}_idx < 0) {nid}_idx = 0;")
        w(f"        if ({nid}_idx > {node.count}) {nid}_idx = {node.count};")
        w(f"        float {nid}_val = {a};")

    elif isinstance(node, GateOut):
        nid = node.id
        gate = node.gate
        w(f"        float {nid} = ({gate}_idx == {node.channel}) ? {gate}_val : 0.0f;")

    elif isinstance(node, Selector):
        nid = node.id
        idx = ref(node.index)
        n = len(node.inputs)
        w(f"        int {nid}_idx = (int)({idx});")
        w(f"        if ({nid}_idx < 0) {nid}_idx = 0;")
        w(f"        if ({nid}_idx > {n}) {nid}_idx = {n};")
        # Build cascading ternary
        expr = "0.0f"
        for i in range(n, 0, -1):
            input_ref = ref(node.inputs[i - 1])
            expr = f"{nid}_idx == {i} ? {input_ref} : {expr}"
        w(f"        float {nid} = {expr};")


# ---------------------------------------------------------------------------
# Interpolation helpers
# ---------------------------------------------------------------------------


def _wrap_idx(expr: str, dl: str) -> str:
    """Wrap a delay index expression with positive modulo."""
    return f"(({expr}) % {dl}_len + {dl}_len) % {dl}_len"


def _emit_interp_linear(nid: str, dl: str, tap: str, w: _Writer) -> None:
    w(f"        float {nid}_ftap = {tap};")
    w(f"        int {nid}_itap = (int){nid}_ftap;")
    w(f"        float {nid}_frac = {nid}_ftap - (float){nid}_itap;")
    i0 = _wrap_idx(f"{dl}_wr - {nid}_itap", dl)
    i1 = _wrap_idx(f"{dl}_wr - {nid}_itap - 1", dl)
    w(f"        int {nid}_i0 = {i0};")
    w(f"        int {nid}_i1 = {i1};")
    s0 = f"{dl}_buf[{nid}_i0]"
    s1 = f"{dl}_buf[{nid}_i1]"
    w(f"        float {nid} = {s0} + {nid}_frac * ({s1} - {s0});")


def _emit_interp_cubic(nid: str, dl: str, tap: str, w: _Writer) -> None:
    w(f"        float {nid}_ftap = {tap};")
    w(f"        int {nid}_itap = (int){nid}_ftap;")
    w(f"        float {nid}_frac = {nid}_ftap - (float){nid}_itap;")
    i0 = _wrap_idx(f"{dl}_wr - {nid}_itap", dl)
    w(f"        int {nid}_i0 = {i0};")
    w(f"        int {nid}_im1 = ({nid}_i0 + 1) % {dl}_len;")
    i1 = _wrap_idx(f"{dl}_wr - {nid}_itap - 1", dl)
    i2 = _wrap_idx(f"{dl}_wr - {nid}_itap - 2", dl)
    w(f"        int {nid}_i1 = {i1};")
    w(f"        int {nid}_i2 = {i2};")
    w(f"        float {nid}_ym1 = {dl}_buf[{nid}_im1];")
    w(f"        float {nid}_y0 = {dl}_buf[{nid}_i0];")
    w(f"        float {nid}_y1 = {dl}_buf[{nid}_i1];")
    w(f"        float {nid}_y2 = {dl}_buf[{nid}_i2];")
    w(f"        float {nid}_c0 = {nid}_y0;")
    w(f"        float {nid}_c1 = 0.5f * ({nid}_y1 - {nid}_ym1);")
    c2a = f"{nid}_ym1 - 2.5f * {nid}_y0"
    c2b = f"2.0f * {nid}_y1 - 0.5f * {nid}_y2"
    w(f"        float {nid}_c2 = {c2a} + {c2b};")
    c3a = f"0.5f * ({nid}_y2 - {nid}_ym1)"
    c3b = f"1.5f * ({nid}_y0 - {nid}_y1)"
    w(f"        float {nid}_c3 = {c3a} + {c3b};")
    horner = f"(({nid}_c3 * {nid}_frac + {nid}_c2) * {nid}_frac + {nid}_c1) * {nid}_frac + {nid}_c0"
    w(f"        float {nid} = {horner};")


# ---------------------------------------------------------------------------
# Buffer interpolation helpers
# ---------------------------------------------------------------------------


def _clamp_buf_idx(nid: str, suffix: str, buf: str, w: _Writer) -> None:
    """Emit clamping for a buffer index variable to [0, buf_len-1]."""
    var = f"{nid}_{suffix}"
    w(f"        if ({var} < 0) {var} = 0;")
    w(f"        if ({var} >= {buf}_len) {var} = {buf}_len - 1;")


def _emit_buf_interp_linear(nid: str, buf: str, idx: str, w: _Writer) -> None:
    w(f"        float {nid}_fidx = {idx};")
    w(f"        int {nid}_i0 = (int){nid}_fidx;")
    w(f"        float {nid}_frac = {nid}_fidx - (float){nid}_i0;")
    w(f"        int {nid}_i1 = {nid}_i0 + 1;")
    _clamp_buf_idx(nid, "i0", buf, w)
    _clamp_buf_idx(nid, "i1", buf, w)
    w(f"        float {nid}_s0 = {buf}_buf[{nid}_i0];")
    w(f"        float {nid}_s1 = {buf}_buf[{nid}_i1];")
    w(f"        float {nid} = {nid}_s0 + {nid}_frac * ({nid}_s1 - {nid}_s0);")


def _emit_buf_interp_cubic(nid: str, buf: str, idx: str, w: _Writer) -> None:
    w(f"        float {nid}_fidx = {idx};")
    w(f"        int {nid}_i0 = (int){nid}_fidx;")
    w(f"        float {nid}_frac = {nid}_fidx - (float){nid}_i0;")
    w(f"        int {nid}_im1 = {nid}_i0 - 1;")
    w(f"        int {nid}_i1 = {nid}_i0 + 1;")
    w(f"        int {nid}_i2 = {nid}_i0 + 2;")
    _clamp_buf_idx(nid, "im1", buf, w)
    _clamp_buf_idx(nid, "i0", buf, w)
    _clamp_buf_idx(nid, "i1", buf, w)
    _clamp_buf_idx(nid, "i2", buf, w)
    w(f"        float {nid}_ym1 = {buf}_buf[{nid}_im1];")
    w(f"        float {nid}_y0 = {buf}_buf[{nid}_i0];")
    w(f"        float {nid}_y1 = {buf}_buf[{nid}_i1];")
    w(f"        float {nid}_y2 = {buf}_buf[{nid}_i2];")
    w(f"        float {nid}_c0 = {nid}_y0;")
    w(f"        float {nid}_c1 = 0.5f * ({nid}_y1 - {nid}_ym1);")
    c2a = f"{nid}_ym1 - 2.5f * {nid}_y0"
    c2b = f"2.0f * {nid}_y1 - 0.5f * {nid}_y2"
    w(f"        float {nid}_c2 = {c2a} + {c2b};")
    c3a = f"0.5f * ({nid}_y2 - {nid}_ym1)"
    c3b = f"1.5f * ({nid}_y0 - {nid}_y1)"
    w(f"        float {nid}_c3 = {c3a} + {c3b};")
    horner = f"(({nid}_c3 * {nid}_frac + {nid}_c2) * {nid}_frac + {nid}_c1) * {nid}_frac + {nid}_c0"
    w(f"        float {nid} = {horner};")


# ---------------------------------------------------------------------------
# Param introspection
# ---------------------------------------------------------------------------


def _emit_param_name(
    params: list[Param], name: str, struct_name: str, w: _Writer
) -> None:
    w(f"const char* {name}_param_name(int index) {{")
    w("    switch (index) {")
    for idx, p in enumerate(params):
        w(f'    case {idx}: return "{p.name}";')
    w('    default: return "";')
    w("    }")
    w("}")


def _emit_param_minmax(
    params: list[Param], name: str, struct_name: str, which: str, w: _Writer
) -> None:
    w(f"float {name}_param_{which}(int index) {{")
    w("    switch (index) {")
    for idx, p in enumerate(params):
        val = p.min if which == "min" else p.max
        w(f"    case {idx}: return {_float_lit(val)};")
    w("    default: return 0.0f;")
    w("    }")
    w("}")


def _emit_param_set(
    params: list[Param], name: str, struct_name: str, w: _Writer
) -> None:
    w(f"void {name}_set_param({struct_name}* self, int index, float value) {{")
    w("    switch (index) {")
    for idx, p in enumerate(params):
        w(f"    case {idx}: self->p_{p.name} = value; break;")
    w("    default: break;")
    w("    }")
    w("}")


def _emit_param_get(
    params: list[Param], name: str, struct_name: str, w: _Writer
) -> None:
    w(f"float {name}_get_param({struct_name}* self, int index) {{")
    w("    switch (index) {")
    for idx, p in enumerate(params):
        w(f"    case {idx}: return self->p_{p.name};")
    w("    default: return 0.0f;")
    w("    }")
    w("}")


# ---------------------------------------------------------------------------
# Buffer introspection API
# ---------------------------------------------------------------------------


def _emit_buffer_api(
    buffer_nodes: list[Buffer], name: str, struct_name: str, w: _Writer
) -> None:
    count = len(buffer_nodes)

    # num_buffers
    w(f"int {name}_num_buffers(void) {{ return {count}; }}")
    w("")

    # buffer_name
    w(f"const char* {name}_buffer_name(int index) {{")
    w("    switch (index) {")
    for idx, buf in enumerate(buffer_nodes):
        w(f'    case {idx}: return "{buf.id}";')
    w('    default: return "";')
    w("    }")
    w("}")
    w("")

    # buffer_size
    w(f"int {name}_buffer_size({struct_name}* self, int index) {{")
    w("    switch (index) {")
    for idx, buf in enumerate(buffer_nodes):
        w(f"    case {idx}: return self->m_{buf.id}_len;")
    w("    default: return 0;")
    w("    }")
    w("}")
    w("")

    # get_buffer
    w(f"float* {name}_get_buffer({struct_name}* self, int index) {{")
    w("    switch (index) {")
    for idx, buf in enumerate(buffer_nodes):
        w(f"    case {idx}: return self->m_{buf.id}_buf;")
    w("    default: return nullptr;")
    w("    }")
    w("}")
    w("")

    # set_buffer
    w(
        f"void {name}_set_buffer({struct_name}* self, int index, const float* data, int len) {{"
    )
    w("    float* dst = nullptr;")
    w("    int cap = 0;")
    w("    switch (index) {")
    for idx, buf in enumerate(buffer_nodes):
        w(
            f"    case {idx}: dst = self->m_{buf.id}_buf; cap = self->m_{buf.id}_len; break;"
        )
    w("    default: return;")
    w("    }")
    w("    int copy_len = len < cap ? len : cap;")
    w("    for (int i = 0; i < copy_len; i++) dst[i] = data[i];")
    w("    for (int i = copy_len; i < cap; i++) dst[i] = 0.0f;")
    w("}")


# ---------------------------------------------------------------------------
# Peek introspection API
# ---------------------------------------------------------------------------


def _emit_peek_api(
    peek_nodes: list[Peek], name: str, struct_name: str, w: _Writer
) -> None:
    count = len(peek_nodes)

    # num_peeks
    w("")
    w(f"int {name}_num_peeks(void) {{ return {count}; }}")
    w("")

    # peek_name
    w(f"const char* {name}_peek_name(int index) {{")
    w("    switch (index) {")
    for idx, pk in enumerate(peek_nodes):
        w(f'    case {idx}: return "{pk.id}";')
    w('    default: return "";')
    w("    }")
    w("}")
    w("")

    # get_peek
    w(f"float {name}_get_peek({struct_name}* self, int index) {{")
    w("    switch (index) {")
    for idx, pk in enumerate(peek_nodes):
        w(f"    case {idx}: return self->m_{pk.id}_value;")
    w("    default: return 0.0f;")
    w("    }")
    w("}")
