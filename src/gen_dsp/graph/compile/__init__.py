"""C++ code generation from DSP graphs."""

from __future__ import annotations

from pathlib import Path

from gen_dsp.core.identifiers import is_reserved_word
from gen_dsp.graph.compile.common import (
    _C_ID_RE,
    _Writer,
    _emit_ref,
    _float_lit,
    _to_pascal,
)
from gen_dsp.graph.compile.nodes import _emit_node_compute
from gen_dsp.graph.compile.state import (
    _emit_state_fields,
    _emit_state_init,
    _emit_state_load,
    _emit_state_reset,
    _emit_state_save,
)
from gen_dsp.graph.models import (
    Buffer,
    DelayLine,
    DelayWrite,
    Graph,
    History,
    Node,
    Param,
    Peek,
)
from gen_dsp.graph.optimize import _STATEFUL_TYPES
from gen_dsp.graph.subgraph import expand_subgraphs
from gen_dsp.graph.toposort import toposort
from gen_dsp.graph.validate import validate_graph


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
        if is_reserved_word(ident):
            raise ValueError(f"ID '{ident}' is a C/C++ reserved word")

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


__all__ = ["compile_graph", "compile_graph_to_file"]
