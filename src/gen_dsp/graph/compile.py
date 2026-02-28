"""C++ code generation from DSP graphs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from gen_dsp.graph.models import (
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
}

_COMPARE_SYMBOLS: dict[str, str] = {
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
    "eq": "==",
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


def _emit_state_fields(node: Node, w: _Writer) -> None:
    if isinstance(node, History):
        w(f"    float m_{node.id};")
    elif isinstance(node, DelayLine):
        w(f"    float* m_{node.id}_buf;")
        w(f"    int m_{node.id}_len;")
        w(f"    int m_{node.id}_wr;")
    elif isinstance(node, Phasor):
        w(f"    float m_{node.id}_phase;")
    elif isinstance(node, Noise):
        w(f"    uint32_t m_{node.id}_seed;")
    elif isinstance(node, (Delta, Change)):
        w(f"    float m_{node.id}_prev;")
    elif isinstance(node, Biquad):
        w(f"    float m_{node.id}_s1;")
        w(f"    float m_{node.id}_s2;")
    elif isinstance(node, SVF):
        w(f"    float m_{node.id}_s1;")
        w(f"    float m_{node.id}_s2;")
    elif isinstance(node, OnePole):
        w(f"    float m_{node.id}_prev;")
    elif isinstance(node, DCBlock):
        w(f"    float m_{node.id}_xprev;")
        w(f"    float m_{node.id}_yprev;")
    elif isinstance(node, Allpass):
        w(f"    float m_{node.id}_xprev;")
        w(f"    float m_{node.id}_yprev;")
    elif isinstance(node, (SinOsc, TriOsc, SawOsc, PulseOsc)):
        w(f"    float m_{node.id}_phase;")
    elif isinstance(node, (SampleHold, Latch)):
        w(f"    float m_{node.id}_held;")
        w(f"    float m_{node.id}_ptrig;")
    elif isinstance(node, Accum):
        w(f"    float m_{node.id}_sum;")
    elif isinstance(node, Counter):
        w(f"    int m_{node.id}_count;")
        w(f"    float m_{node.id}_ptrig;")
    elif isinstance(node, RateDiv):
        w(f"    int m_{node.id}_count;")
        w(f"    float m_{node.id}_held;")
    elif isinstance(node, SmoothParam):
        w(f"    float m_{node.id}_prev;")
    elif isinstance(node, Peek):
        w(f"    float m_{node.id}_value;")
    elif isinstance(node, Buffer):
        w(f"    float* m_{node.id}_buf;")
        w(f"    int m_{node.id}_len;")


# ---------------------------------------------------------------------------
# State initialization
# ---------------------------------------------------------------------------


def _emit_state_init(node: Node, w: _Writer) -> None:
    if isinstance(node, History):
        w(f"    self->m_{node.id} = {_float_lit(node.init)};")
    elif isinstance(node, DelayLine):
        w(f"    self->m_{node.id}_len = {node.max_samples};")
        w(
            f"    self->m_{node.id}_buf = (float*)calloc({node.max_samples}, sizeof(float));"
        )
        w(f"    self->m_{node.id}_wr = 0;")
    elif isinstance(node, Noise):
        w(f"    self->m_{node.id}_seed = 123456789u;")
    elif isinstance(node, (Delta, Change)):
        w(f"    self->m_{node.id}_prev = 0.0f;")
    elif isinstance(node, Biquad):
        w(f"    self->m_{node.id}_s1 = 0.0f;")
        w(f"    self->m_{node.id}_s2 = 0.0f;")
    elif isinstance(node, SVF):
        w(f"    self->m_{node.id}_s1 = 0.0f;")
        w(f"    self->m_{node.id}_s2 = 0.0f;")
    elif isinstance(node, OnePole):
        w(f"    self->m_{node.id}_prev = 0.0f;")
    elif isinstance(node, DCBlock):
        w(f"    self->m_{node.id}_xprev = 0.0f;")
        w(f"    self->m_{node.id}_yprev = 0.0f;")
    elif isinstance(node, Allpass):
        w(f"    self->m_{node.id}_xprev = 0.0f;")
        w(f"    self->m_{node.id}_yprev = 0.0f;")
    elif isinstance(node, (SampleHold, Latch)):
        w(f"    self->m_{node.id}_held = 0.0f;")
        w(f"    self->m_{node.id}_ptrig = 0.0f;")
    elif isinstance(node, RateDiv):
        w(f"    self->m_{node.id}_count = 0;")
        w(f"    self->m_{node.id}_held = 0.0f;")
    elif isinstance(node, SmoothParam):
        w(f"    self->m_{node.id}_prev = 0.0f;")
    elif isinstance(node, Peek):
        w(f"    self->m_{node.id}_value = 0.0f;")
    elif isinstance(node, Buffer):
        w(f"    self->m_{node.id}_len = {node.size};")
        w(f"    self->m_{node.id}_buf = (float*)calloc({node.size}, sizeof(float));")


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


def _emit_state_reset(node: Node, w: _Writer) -> None:
    if isinstance(node, History):
        w(f"    self->m_{node.id} = {_float_lit(node.init)};")
    elif isinstance(node, DelayLine):
        w(
            f"    memset(self->m_{node.id}_buf, 0, self->m_{node.id}_len * sizeof(float));"
        )
        w(f"    self->m_{node.id}_wr = 0;")
    elif isinstance(node, (Phasor, SinOsc, TriOsc, SawOsc, PulseOsc)):
        w(f"    self->m_{node.id}_phase = 0.0f;")
    elif isinstance(node, Noise):
        w(f"    self->m_{node.id}_seed = 123456789u;")
    elif isinstance(node, (Delta, Change)):
        w(f"    self->m_{node.id}_prev = 0.0f;")
    elif isinstance(node, (Biquad, SVF)):
        w(f"    self->m_{node.id}_s1 = 0.0f;")
        w(f"    self->m_{node.id}_s2 = 0.0f;")
    elif isinstance(node, OnePole):
        w(f"    self->m_{node.id}_prev = 0.0f;")
    elif isinstance(node, (DCBlock, Allpass)):
        w(f"    self->m_{node.id}_xprev = 0.0f;")
        w(f"    self->m_{node.id}_yprev = 0.0f;")
    elif isinstance(node, (SampleHold, Latch)):
        w(f"    self->m_{node.id}_held = 0.0f;")
        w(f"    self->m_{node.id}_ptrig = 0.0f;")
    elif isinstance(node, Accum):
        w(f"    self->m_{node.id}_sum = 0.0f;")
    elif isinstance(node, Counter):
        w(f"    self->m_{node.id}_count = 0;")
        w(f"    self->m_{node.id}_ptrig = 0.0f;")
    elif isinstance(node, RateDiv):
        w(f"    self->m_{node.id}_count = 0;")
        w(f"    self->m_{node.id}_held = 0.0f;")
    elif isinstance(node, SmoothParam):
        w(f"    self->m_{node.id}_prev = 0.0f;")
    elif isinstance(node, Peek):
        w(f"    self->m_{node.id}_value = 0.0f;")
    elif isinstance(node, Buffer):
        w(
            f"    memset(self->m_{node.id}_buf, 0, self->m_{node.id}_len * sizeof(float));"
        )


# ---------------------------------------------------------------------------
# perform() body
# ---------------------------------------------------------------------------


_NON_REF_FIELDS = frozenset({"id", "op", "interp", "mode"})


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


def _emit_state_load(node: Node, w: _Writer) -> None:
    if isinstance(node, History):
        w(f"    float {node.id} = self->m_{node.id};")
    elif isinstance(node, DelayLine):
        w(f"    float* {node.id}_buf = self->m_{node.id}_buf;")
        w(f"    int {node.id}_len = self->m_{node.id}_len;")
        w(f"    int {node.id}_wr = self->m_{node.id}_wr;")
    elif isinstance(node, Phasor):
        w(f"    float {node.id}_phase = self->m_{node.id}_phase;")
    elif isinstance(node, Noise):
        w(f"    uint32_t {node.id}_seed = self->m_{node.id}_seed;")
    elif isinstance(node, (Delta, Change)):
        w(f"    float {node.id}_prev = self->m_{node.id}_prev;")
    elif isinstance(node, Biquad):
        w(f"    float {node.id}_s1 = self->m_{node.id}_s1;")
        w(f"    float {node.id}_s2 = self->m_{node.id}_s2;")
    elif isinstance(node, SVF):
        w(f"    float {node.id}_s1 = self->m_{node.id}_s1;")
        w(f"    float {node.id}_s2 = self->m_{node.id}_s2;")
    elif isinstance(node, OnePole):
        w(f"    float {node.id}_prev = self->m_{node.id}_prev;")
    elif isinstance(node, DCBlock):
        w(f"    float {node.id}_xprev = self->m_{node.id}_xprev;")
        w(f"    float {node.id}_yprev = self->m_{node.id}_yprev;")
    elif isinstance(node, Allpass):
        w(f"    float {node.id}_xprev = self->m_{node.id}_xprev;")
        w(f"    float {node.id}_yprev = self->m_{node.id}_yprev;")
    elif isinstance(node, (SinOsc, TriOsc, SawOsc, PulseOsc)):
        w(f"    float {node.id}_phase = self->m_{node.id}_phase;")
    elif isinstance(node, (SampleHold, Latch)):
        w(f"    float {node.id}_held = self->m_{node.id}_held;")
        w(f"    float {node.id}_ptrig = self->m_{node.id}_ptrig;")
    elif isinstance(node, Accum):
        w(f"    float {node.id}_sum = self->m_{node.id}_sum;")
    elif isinstance(node, Counter):
        w(f"    int {node.id}_count = self->m_{node.id}_count;")
        w(f"    float {node.id}_ptrig = self->m_{node.id}_ptrig;")
    elif isinstance(node, RateDiv):
        w(f"    int {node.id}_count = self->m_{node.id}_count;")
        w(f"    float {node.id}_held = self->m_{node.id}_held;")
    elif isinstance(node, SmoothParam):
        w(f"    float {node.id}_prev = self->m_{node.id}_prev;")
    elif isinstance(node, Peek):
        w(f"    float {node.id}_value = self->m_{node.id}_value;")
    elif isinstance(node, Buffer):
        w(f"    float* {node.id}_buf = self->m_{node.id}_buf;")
        w(f"    int {node.id}_len = self->m_{node.id}_len;")


def _emit_state_save(node: Node, w: _Writer) -> None:
    if isinstance(node, History):
        w(f"    self->m_{node.id} = {node.id};")
    elif isinstance(node, DelayLine):
        w(f"    self->m_{node.id}_wr = {node.id}_wr;")
    elif isinstance(node, Phasor):
        w(f"    self->m_{node.id}_phase = {node.id}_phase;")
    elif isinstance(node, Noise):
        w(f"    self->m_{node.id}_seed = {node.id}_seed;")
    elif isinstance(node, (Delta, Change)):
        w(f"    self->m_{node.id}_prev = {node.id}_prev;")
    elif isinstance(node, Biquad):
        w(f"    self->m_{node.id}_s1 = {node.id}_s1;")
        w(f"    self->m_{node.id}_s2 = {node.id}_s2;")
    elif isinstance(node, SVF):
        w(f"    self->m_{node.id}_s1 = {node.id}_s1;")
        w(f"    self->m_{node.id}_s2 = {node.id}_s2;")
    elif isinstance(node, OnePole):
        w(f"    self->m_{node.id}_prev = {node.id}_prev;")
    elif isinstance(node, DCBlock):
        w(f"    self->m_{node.id}_xprev = {node.id}_xprev;")
        w(f"    self->m_{node.id}_yprev = {node.id}_yprev;")
    elif isinstance(node, Allpass):
        w(f"    self->m_{node.id}_xprev = {node.id}_xprev;")
        w(f"    self->m_{node.id}_yprev = {node.id}_yprev;")
    elif isinstance(node, (SinOsc, TriOsc, SawOsc, PulseOsc)):
        w(f"    self->m_{node.id}_phase = {node.id}_phase;")
    elif isinstance(node, (SampleHold, Latch)):
        w(f"    self->m_{node.id}_held = {node.id}_held;")
        w(f"    self->m_{node.id}_ptrig = {node.id}_ptrig;")
    elif isinstance(node, Accum):
        w(f"    self->m_{node.id}_sum = {node.id}_sum;")
    elif isinstance(node, Counter):
        w(f"    self->m_{node.id}_count = {node.id}_count;")
        w(f"    self->m_{node.id}_ptrig = {node.id}_ptrig;")
    elif isinstance(node, RateDiv):
        w(f"    self->m_{node.id}_count = {node.id}_count;")
        w(f"    self->m_{node.id}_held = {node.id}_held;")
    elif isinstance(node, SmoothParam):
        w(f"    self->m_{node.id}_prev = {node.id}_prev;")
    elif isinstance(node, Peek):
        w(f"    self->m_{node.id}_value = {node.id}_value;")


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

    elif isinstance(node, BufSize):
        w(f"        float {node.id} = (float)self->m_{node.buffer}_len;")

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

    elif isinstance(node, Peek):
        nid = node.id
        a = ref(node.a)
        w(f"        float {nid} = {a};")
        w(f"        {nid}_value = {nid};")


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
