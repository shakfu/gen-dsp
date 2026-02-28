"""Subgraph expansion -- inline Subgraph nodes into flat graphs."""

from __future__ import annotations

from gen_dsp.dsp_graph.models import Graph, Node, Subgraph

_NON_REF_FIELDS = frozenset({"id", "op", "interp", "mode", "output"})


def expand_subgraphs(graph: Graph) -> Graph:
    """Recursively expand all Subgraph nodes into a flat graph.

    Returns the graph unchanged if it contains no Subgraph nodes.
    Raises ValueError on invalid subgraph wiring.
    """
    if not any(isinstance(n, Subgraph) for n in graph.nodes):
        return graph

    out_nodes: list[Node] = []
    # Maps subgraph ID (and compound IDs) to the expanded output node ID
    output_map: dict[str, str] = {}
    # Collect prefixed control_nodes from inner subgraphs
    new_control_nodes: list[str] = list(graph.control_nodes)

    # Parent namespace sets for collision detection
    parent_param_names = {p.name for p in graph.params}
    parent_input_ids = {inp.id for inp in graph.inputs}

    for node in graph.nodes:
        if isinstance(node, Subgraph):
            pre_count = len(out_nodes)
            _expand_one(node, out_nodes, output_map)
            # Check for namespace collisions with parent params/inputs
            for new_node in out_nodes[pre_count:]:
                if new_node.id in parent_param_names:
                    raise ValueError(
                        f"Subgraph '{node.id}': expanded node '{new_node.id}' "
                        f"collides with parent param"
                    )
                if new_node.id in parent_input_ids:
                    raise ValueError(
                        f"Subgraph '{node.id}': expanded node '{new_node.id}' "
                        f"collides with parent input"
                    )
            # Propagate inner graph's control_nodes with prefix
            inner = expand_subgraphs(node.graph)
            prefix = node.id + "__"
            for cn_id in inner.control_nodes:
                new_control_nodes.append(prefix + cn_id)
        else:
            out_nodes.append(node)

    # Rewrite parent-level refs that point to subgraph IDs
    out_nodes = [_rewrite_refs(n, output_map) for n in out_nodes]

    new_outputs = []
    for out in graph.outputs:
        source = output_map.get(out.source, out.source)
        if source != out.source:
            new_outputs.append(out.model_copy(update={"source": source}))
        else:
            new_outputs.append(out)

    updates: dict[str, object] = {"nodes": out_nodes, "outputs": new_outputs}
    if new_control_nodes != list(graph.control_nodes):
        updates["control_nodes"] = new_control_nodes
    return graph.model_copy(update=updates)


def _expand_one(
    sg: Subgraph,
    out_nodes: list[Node],
    output_map: dict[str, str],
) -> None:
    """Expand a single Subgraph node, appending results to out_nodes."""
    inner = sg.graph

    # Recurse first (handles nested subgraphs)
    inner = expand_subgraphs(inner)

    if not inner.outputs:
        raise ValueError(f"Subgraph '{sg.id}': inner graph has no outputs")

    # Validate output selector
    inner_output_ids = {o.id for o in inner.outputs}
    if sg.output and sg.output not in inner_output_ids:
        raise ValueError(
            f"Subgraph '{sg.id}': output '{sg.output}' not found "
            f"in inner graph (available: {sorted(inner_output_ids)})"
        )

    # Validate input mappings
    inner_input_ids = {inp.id for inp in inner.inputs}
    for key in sg.inputs:
        if key not in inner_input_ids:
            raise ValueError(
                f"Subgraph '{sg.id}': input key '{key}' not found "
                f"in inner graph (available: {sorted(inner_input_ids)})"
            )
    for iid in inner_input_ids:
        if iid not in sg.inputs:
            raise ValueError(f"Subgraph '{sg.id}': missing input mapping for '{iid}'")

    # Validate param mappings
    inner_param_names = {p.name for p in inner.params}
    for key in sg.params:
        if key not in inner_param_names:
            raise ValueError(
                f"Subgraph '{sg.id}': param key '{key}' not found "
                f"in inner graph (available: {sorted(inner_param_names)})"
            )

    # Build defaults for unmapped params
    param_defaults = {p.name: p.default for p in inner.params}

    prefix = sg.id + "__"
    inner_node_ids = {n.id for n in inner.nodes}

    # Build rewrite map: inner ID -> replacement
    rewrite_map: dict[str, str | float] = {}
    # Inner node IDs -> prefixed
    for nid in inner_node_ids:
        rewrite_map[nid] = prefix + nid
    # Inner input IDs -> parent ref
    for iid, ref in sg.inputs.items():
        rewrite_map[iid] = ref
    # Inner param names -> parent ref or default float
    for pname in inner_param_names:
        if pname in sg.params:
            rewrite_map[pname] = sg.params[pname]
        else:
            rewrite_map[pname] = param_defaults[pname]

    # Clone + rewrite each inner node
    for node in inner.nodes:
        new_node = _rewrite_node(node, prefix, rewrite_map)
        out_nodes.append(new_node)

    # Build output_map entries
    # Selected output (or first)
    selected = sg.output if sg.output else inner.outputs[0].id
    for out in inner.outputs:
        prefixed_source = prefix + out.source
        if out.id == selected:
            output_map[sg.id] = prefixed_source
        # Compound ID for all outputs
        output_map[sg.id + "__" + out.id] = prefixed_source


def _rewrite_node(
    node: Node,
    prefix: str,
    rewrite_map: dict[str, str | float],
) -> Node:
    """Clone a node with prefixed ID and rewritten ref fields."""
    updates: dict[str, object] = {"id": prefix + node.id}
    for field_name, value in node.__dict__.items():
        if field_name in _NON_REF_FIELDS:
            continue
        if isinstance(value, str) and value in rewrite_map:
            updates[field_name] = rewrite_map[value]
        elif isinstance(value, float):
            continue
        elif isinstance(value, int):
            continue
    return node.model_copy(update=updates)


def _rewrite_refs(node: Node, output_map: dict[str, str]) -> Node:
    """Rewrite parent-level refs pointing to subgraph IDs."""
    updates: dict[str, object] = {}
    for field_name, value in node.__dict__.items():
        if field_name in _NON_REF_FIELDS:
            continue
        if isinstance(value, str) and value in output_map:
            updates[field_name] = output_map[value]
    if not updates:
        return node
    return node.model_copy(update=updates)
