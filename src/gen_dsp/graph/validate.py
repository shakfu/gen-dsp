from __future__ import annotations

from collections import defaultdict

from gen_dsp.graph._deps import build_forward_deps
from gen_dsp.graph.models import (
    Buffer,
    BufRead,
    BufSize,
    BufWrite,
    Cycle,
    DelayLine,
    DelayRead,
    DelayWrite,
    GateOut,
    GateRoute,
    Graph,
    History,
    Lookup,
    Splat,
    Subgraph,
    Wave,
)
from gen_dsp.graph.optimize import _STATEFUL_TYPES


class GraphValidationError(str):
    """A structured validation error that behaves as a plain string.

    Subclasses ``str`` so all existing call sites (``== []``, ``in``,
    ``"; ".join(errors)``, ``print(f"error: {err}")``) work unchanged.

    Attributes
    ----------
    kind : str
        Machine-readable error category.  Stable values:

        ``"duplicate_id"``
            Two nodes share the same ID.
        ``"id_collision"``
            A node ID equals an audio input ID or param name.
        ``"dangling_ref"``
            A field references an ID that does not exist.
        ``"bad_output_source"``
            ``AudioOutput.source`` does not reference a node.
        ``"missing_delay_line"``
            ``DelayRead``/``DelayWrite`` references a non-existent ``DelayLine``.
        ``"missing_buffer"``
            A buffer consumer (``BufRead``, ``BufWrite``, ``BufSize``, ``Splat``,
            ``Cycle``, ``Wave``, ``Lookup``) references a non-existent ``Buffer``.
        ``"missing_gate_route"``
            ``GateOut.gate`` references a non-existent ``GateRoute``.
        ``"gate_channel_range"``
            ``GateOut.channel`` is outside ``[1, gate_route.count]``.
        ``"invalid_control_node"``
            An ID in ``Graph.control_nodes`` is not a node ID.
        ``"control_audio_dep"``
            A control-rate node depends on an audio input.
        ``"control_rate_dep"``
            A control-rate node depends on an audio-rate node.
        ``"cycle"``
            Graph contains a pure cycle (not through ``History`` or delay feedback).
        ``"expansion_error"``
            ``expand_subgraphs()`` raised a ``ValueError`` (malformed ``Subgraph``).
        ``"unmapped_param"`` *(warning)*
            A subgraph param uses its default because it was not mapped at the
            call site.  Only emitted when ``warn_unmapped_params=True``.

    node_id : str | None
        ID of the offending node, if applicable.
    field_name : str | None
        Name of the offending field, if applicable.
    severity : str
        ``"error"`` or ``"warning"``.
    """

    kind: str
    node_id: str | None
    field_name: str | None
    severity: str  # "error" | "warning"

    def __new__(
        cls,
        kind: str,
        message: str,
        *,
        node_id: str | None = None,
        field_name: str | None = None,
        severity: str = "error",
    ) -> GraphValidationError:
        return super().__new__(cls, message)

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        node_id: str | None = None,
        field_name: str | None = None,
        severity: str = "error",
    ) -> None:
        self.kind = kind
        self.node_id = node_id
        self.field_name = field_name
        self.severity = severity


def _collect_refs(node: object) -> list[str]:
    """Return all string references from a node's input fields (excluding 'id' and 'op')."""
    refs: list[str] = []
    for field_name, value in node.__dict__.items():
        if field_name in ("id", "op"):
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    refs.append(item)
        elif isinstance(value, str):
            refs.append(value)
    return refs


def _check_unmapped_params(
    nodes: list[object],
    prefix: str,
    warnings: list[GraphValidationError],
) -> None:
    """Recursively check for unmapped subgraph params, emitting warnings."""
    for node in nodes:
        if not isinstance(node, Subgraph):
            continue
        inner_param_names = {p.name for p in node.graph.params}
        mapped = set(node.params.keys())
        unmapped = inner_param_names - mapped
        sg_id = prefix + node.id if prefix else node.id
        for pname in sorted(unmapped):
            default = next(p.default for p in node.graph.params if p.name == pname)
            warnings.append(
                GraphValidationError(
                    "unmapped_param",
                    f"Subgraph '{sg_id}': param '{pname}' not mapped, using default {default}",
                    node_id=sg_id,
                    field_name=pname,
                    severity="warning",
                )
            )
        # Recurse into nested subgraphs
        inner_prefix = (prefix + node.id + "__") if prefix else (node.id + "__")
        _check_unmapped_params(list(node.graph.nodes), inner_prefix, warnings)


def validate_graph(
    graph: Graph, *, warn_unmapped_params: bool = False
) -> list[GraphValidationError]:
    """Validate a DSP graph and return a list of errors (empty = valid).

    When *warn_unmapped_params* is ``True``, warnings for subgraph params
    that silently fall back to defaults are appended after all errors.
    """
    from gen_dsp.graph.subgraph import expand_subgraphs

    # Collect unmapped-param warnings *before* expansion (needs Subgraph nodes)
    warnings: list[GraphValidationError] = []
    if warn_unmapped_params:
        _check_unmapped_params(list(graph.nodes), "", warnings)

    try:
        graph = expand_subgraphs(graph)
    except ValueError as e:
        return [GraphValidationError("expansion_error", str(e))]

    errors: list[GraphValidationError] = []

    # Build ID sets
    node_ids: dict[str, int] = {}
    input_ids = {inp.id for inp in graph.inputs}
    param_names = {p.name for p in graph.params}
    all_sources = input_ids | param_names  # valid non-node sources

    # 1. Unique IDs -- no duplicate node IDs, no collision with inputs/params
    for node in graph.nodes:
        nid = node.id
        if nid in node_ids:
            errors.append(
                GraphValidationError(
                    "duplicate_id", f"Duplicate node ID: '{nid}'", node_id=nid
                )
            )
        node_ids[nid] = 0  # just tracking existence

        if nid in input_ids:
            errors.append(
                GraphValidationError(
                    "id_collision",
                    f"Node ID '{nid}' collides with audio input ID",
                    node_id=nid,
                )
            )
        if nid in param_names:
            errors.append(
                GraphValidationError(
                    "id_collision",
                    f"Node ID '{nid}' collides with param name",
                    node_id=nid,
                )
            )

    all_ids = set(node_ids) | all_sources

    # String fields that are enum selectors, not node references
    _NON_REF_FIELDS = {
        "id",
        "op",
        "interp",
        "mode",
        "output",
        "count",
        "channel",
        "fill",
    }

    # 2. Reference resolution -- every str input resolves to a known ID
    for node in graph.nodes:
        for field_name, value in node.__dict__.items():
            if field_name in _NON_REF_FIELDS:
                continue
            if isinstance(value, list):
                for idx, item in enumerate(value):
                    if isinstance(item, str) and item not in all_ids:
                        nid = node.id
                        errors.append(
                            GraphValidationError(
                                "dangling_ref",
                                f"Node '{nid}' field '{field_name}[{idx}]' references unknown ID '{item}'",
                                node_id=nid,
                                field_name=field_name,
                            )
                        )
            elif isinstance(value, str):
                if value not in all_ids:
                    nid = node.id
                    errors.append(
                        GraphValidationError(
                            "dangling_ref",
                            f"Node '{nid}' field '{field_name}' references unknown ID '{value}'",
                            node_id=nid,
                            field_name=field_name,
                        )
                    )

    # 3. Output resolution -- every output source resolves to a node ID
    for out in graph.outputs:
        if out.source not in node_ids:
            errors.append(
                GraphValidationError(
                    "bad_output_source",
                    f"Output '{out.id}' source '{out.source}' does not reference a node",
                    node_id=out.id,
                    field_name="source",
                )
            )

    # 4. Delay consistency -- DelayRead/DelayWrite must reference a DelayLine
    delay_line_ids = {node.id for node in graph.nodes if isinstance(node, DelayLine)}
    for node in graph.nodes:
        if isinstance(node, DelayRead) and node.delay not in delay_line_ids:
            errors.append(
                GraphValidationError(
                    "missing_delay_line",
                    f"DelayRead '{node.id}' references non-existent delay line '{node.delay}'",
                    node_id=node.id,
                    field_name="delay",
                )
            )
        if isinstance(node, DelayWrite) and node.delay not in delay_line_ids:
            errors.append(
                GraphValidationError(
                    "missing_delay_line",
                    f"DelayWrite '{node.id}' references non-existent delay line '{node.delay}'",
                    node_id=node.id,
                    field_name="delay",
                )
            )

    # 4b. Buffer consistency -- BufRead/BufWrite/BufSize must reference a Buffer
    buffer_ids = {node.id for node in graph.nodes if isinstance(node, Buffer)}
    for node in graph.nodes:
        if isinstance(node, BufRead) and node.buffer not in buffer_ids:
            errors.append(
                GraphValidationError(
                    "missing_buffer",
                    f"BufRead '{node.id}' references non-existent buffer '{node.buffer}'",
                    node_id=node.id,
                    field_name="buffer",
                )
            )
        if isinstance(node, BufWrite) and node.buffer not in buffer_ids:
            errors.append(
                GraphValidationError(
                    "missing_buffer",
                    f"BufWrite '{node.id}' references non-existent buffer '{node.buffer}'",
                    node_id=node.id,
                    field_name="buffer",
                )
            )
        if isinstance(node, Splat) and node.buffer not in buffer_ids:
            errors.append(
                GraphValidationError(
                    "missing_buffer",
                    f"Splat '{node.id}' references non-existent buffer '{node.buffer}'",
                    node_id=node.id,
                    field_name="buffer",
                )
            )
        if isinstance(node, BufSize) and node.buffer not in buffer_ids:
            errors.append(
                GraphValidationError(
                    "missing_buffer",
                    f"BufSize '{node.id}' references non-existent buffer '{node.buffer}'",
                    node_id=node.id,
                    field_name="buffer",
                )
            )
        if isinstance(node, Cycle) and node.buffer not in buffer_ids:
            errors.append(
                GraphValidationError(
                    "missing_buffer",
                    f"Cycle '{node.id}' references non-existent buffer '{node.buffer}'",
                    node_id=node.id,
                    field_name="buffer",
                )
            )
        if isinstance(node, Wave) and node.buffer not in buffer_ids:
            errors.append(
                GraphValidationError(
                    "missing_buffer",
                    f"Wave '{node.id}' references non-existent buffer '{node.buffer}'",
                    node_id=node.id,
                    field_name="buffer",
                )
            )
        if isinstance(node, Lookup) and node.buffer not in buffer_ids:
            errors.append(
                GraphValidationError(
                    "missing_buffer",
                    f"Lookup '{node.id}' references non-existent buffer '{node.buffer}'",
                    node_id=node.id,
                    field_name="buffer",
                )
            )

    # 4c. Gate consistency -- GateOut must reference a GateRoute, channel in range
    gate_route_map = {
        node.id: node for node in graph.nodes if isinstance(node, GateRoute)
    }
    for node in graph.nodes:
        if isinstance(node, GateOut):
            if node.gate not in gate_route_map:
                errors.append(
                    GraphValidationError(
                        "missing_gate_route",
                        f"GateOut '{node.id}' references non-existent gate route '{node.gate}'",
                        node_id=node.id,
                        field_name="gate",
                    )
                )
            else:
                gate_route = gate_route_map[node.gate]
                if node.channel < 1 or node.channel > gate_route.count:
                    errors.append(
                        GraphValidationError(
                            "gate_channel_range",
                            f"GateOut '{node.id}' channel {node.channel} out of range [1, {gate_route.count}]",
                            node_id=node.id,
                            field_name="channel",
                        )
                    )

    # 5. Control-rate consistency
    if graph.control_interval > 0 and graph.control_nodes:
        ctrl_set = set(graph.control_nodes)
        node_id_set = set(node_ids)

        for cid in graph.control_nodes:
            if cid not in node_id_set:
                errors.append(
                    GraphValidationError(
                        "invalid_control_node",
                        f"control_nodes: '{cid}' is not a node ID",
                        node_id=cid,
                    )
                )

        # Compute invariant node IDs: pure nodes depending only on
        # params/literals/other invariant nodes.  These are LICM-hoistable and
        # safe for control-rate nodes to reference.
        invariant_ids: set[str] = set()
        node_by_id = {n.id: n for n in graph.nodes}
        for node in graph.nodes:
            if isinstance(node, _STATEFUL_TYPES):
                continue
            is_inv = True
            for fn, val in node.__dict__.items():
                if fn in _NON_REF_FIELDS:
                    continue
                if isinstance(val, float):
                    continue
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, float):
                            continue
                        if isinstance(item, str):
                            if item in param_names or item in invariant_ids:
                                continue
                            is_inv = False
                            break
                    if not is_inv:
                        break
                    continue
                if isinstance(val, str):
                    if val in param_names or val in invariant_ids:
                        continue
                    is_inv = False
                    break
            if is_inv:
                invariant_ids.add(node.id)

        # Allowed deps for a control-rate node: params, other ctrl nodes, invariant nodes
        allowed = ctrl_set | param_names | invariant_ids
        for cid in graph.control_nodes:
            if cid not in node_by_id:
                continue
            node = node_by_id[cid]
            if isinstance(node, History):
                continue
            for field_name, value in node.__dict__.items():
                if field_name in _NON_REF_FIELDS:
                    continue
                str_refs: list[str] = []
                if isinstance(value, list):
                    str_refs = [v for v in value if isinstance(v, str)]
                elif isinstance(value, str):
                    str_refs = [value]
                else:
                    continue
                for ref_val in str_refs:
                    if ref_val in input_ids:
                        errors.append(
                            GraphValidationError(
                                "control_audio_dep",
                                f"Control-rate node '{cid}' depends on audio input '{ref_val}'",
                                node_id=cid,
                                field_name=field_name,
                            )
                        )
                    elif ref_val in node_id_set and ref_val not in allowed:
                        errors.append(
                            GraphValidationError(
                                "control_rate_dep",
                                f"Control-rate node '{cid}' depends on audio-rate node '{ref_val}'",
                                node_id=cid,
                                field_name=field_name,
                            )
                        )

    # 6. No pure cycles -- topo sort on non-feedback edges must succeed
    deps = build_forward_deps(graph)

    # Kahn's algorithm
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    reverse: dict[str, list[str]] = defaultdict(list)
    for nid, dep_set in deps.items():
        for dep in dep_set:
            if dep in in_degree:
                in_degree[nid] += 1
                reverse[dep].append(nid)

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for dependent in reverse[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if visited < len(node_ids):
        cycle_nodes = [nid for nid, deg in in_degree.items() if deg > 0]
        errors.append(
            GraphValidationError(
                "cycle",
                f"Graph contains a cycle through nodes: {', '.join(sorted(cycle_nodes))}",
            )
        )

    # Append warnings after errors
    errors.extend(warnings)

    return errors
