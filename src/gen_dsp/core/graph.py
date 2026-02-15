"""
Graph data model for multi-plugin chain and DAG configurations.

Defines the JSON graph format and validation logic for serial chains
and arbitrary DAGs of gen~ plugins (including built-in mixer nodes).

Typical flow:
    graph.json -> parse_graph() -> GraphConfig
              -> validate_linear_chain() -> errors (if any)     [Phase 1]
              -> extract_chain_order() -> ordered node IDs       [Phase 1]
              -> resolve_chain() -> list[ResolvedChainNode]      [Phase 1]

    Or for DAGs:
              -> validate_dag() -> errors (if any)               [Phase 2]
              -> topological_sort() -> ordered node IDs          [Phase 2]
              -> allocate_edge_buffers() -> EdgeBuffer list       [Phase 2]
              -> resolve_dag() -> list[ResolvedChainNode]        [Phase 2]
"""

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from gen_dsp.core.manifest import Manifest, ParamInfo, manifest_from_export_info
from gen_dsp.core.parser import ExportInfo, GenExportParser
from gen_dsp.errors import ValidationError


@dataclass
class Connection:
    """A directed edge in the plugin graph.

    Attributes:
        src_node: Source node ID (or "audio_in").
        dst_node: Destination node ID (or "audio_out").
        dst_input_index: Optional input index on the destination node.
            None means sequential from 0. Used for mixer input selection
            (e.g. "mix:1" -> dst_input_index=1).
    """

    src_node: str
    dst_node: str
    dst_input_index: Optional[int] = None


@dataclass
class ChainNodeConfig:
    """Configuration for a single node in the chain graph."""

    id: str
    export: Optional[str] = None
    node_type: str = "gen"  # "gen" or "mixer"
    mixer_inputs: int = 0  # only for mixer nodes
    midi_channel: Optional[int] = None
    cc_map: dict[int, str] = field(default_factory=dict)


@dataclass
class GraphConfig:
    """Parsed graph configuration from JSON."""

    nodes: dict[str, ChainNodeConfig]
    connections: list[Connection]


@dataclass
class EdgeBuffer:
    """Buffer allocation for a single edge in the DAG.

    Attributes:
        buffer_id: Unique buffer identifier. Edges from the same source
            share one buffer_id (fan-out = zero-copy).
        src_node: Source node ID.
        dst_node: Destination node ID.
        dst_input_index: Optional input index on the destination.
        num_channels: Channel count (from source output count).
    """

    buffer_id: int
    src_node: str
    dst_node: str
    dst_input_index: Optional[int]
    num_channels: int


@dataclass
class ResolvedChainNode:
    """A chain node with fully resolved export info and manifest."""

    config: ChainNodeConfig
    index: int
    export_info: Optional[ExportInfo]
    manifest: Manifest


def parse_graph(json_path: Path) -> GraphConfig:
    """Parse a chain graph from a JSON file.

    Args:
        json_path: Path to the JSON graph file.

    Returns:
        Parsed GraphConfig.

    Raises:
        ValidationError: If the JSON is malformed or missing required fields.
    """
    if not json_path.is_file():
        raise ValidationError(f"Graph file not found: {json_path}")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValidationError(f"Invalid JSON in graph file: {e}") from e

    if not isinstance(data, dict):
        raise ValidationError("Graph JSON must be an object")

    if "nodes" not in data:
        raise ValidationError("Graph JSON must contain a 'nodes' key")
    if "connections" not in data:
        raise ValidationError("Graph JSON must contain a 'connections' key")

    nodes_data = data["nodes"]
    if not isinstance(nodes_data, dict):
        raise ValidationError("'nodes' must be an object")

    connections_data = data["connections"]
    if not isinstance(connections_data, list):
        raise ValidationError("'connections' must be an array")

    # Parse nodes
    nodes: dict[str, ChainNodeConfig] = {}
    for node_id, node_data in nodes_data.items():
        if not isinstance(node_data, dict):
            raise ValidationError(f"Node '{node_id}' must be an object")

        # Determine node type
        node_type = node_data.get("type", "gen")
        if node_type == "mixer":
            if "inputs" not in node_data:
                raise ValidationError(
                    f"Node '{node_id}': mixer nodes must have an 'inputs' field"
                )
            mixer_inputs = node_data["inputs"]
            if not isinstance(mixer_inputs, int) or mixer_inputs < 1:
                raise ValidationError(
                    f"Node '{node_id}': mixer 'inputs' must be a positive integer"
                )
            export = None
        elif node_type == "gen":
            if "export" not in node_data:
                raise ValidationError(
                    f"Node '{node_id}' must have an 'export' field"
                )
            export = node_data["export"]
            mixer_inputs = 0
        else:
            raise ValidationError(
                f"Node '{node_id}': unknown node type '{node_type}'"
            )

        cc_map: dict[int, str] = {}
        if "cc" in node_data:
            raw_cc = node_data["cc"]
            if not isinstance(raw_cc, dict):
                raise ValidationError(
                    f"Node '{node_id}': 'cc' must be an object mapping CC numbers to param names"
                )
            for cc_str, param_name in raw_cc.items():
                try:
                    cc_num = int(cc_str)
                except ValueError:
                    raise ValidationError(
                        f"Node '{node_id}': CC key '{cc_str}' must be an integer"
                    )
                cc_map[cc_num] = param_name

        midi_channel = node_data.get("midi_channel")
        if midi_channel is not None and not isinstance(midi_channel, int):
            raise ValidationError(
                f"Node '{node_id}': 'midi_channel' must be an integer"
            )

        nodes[node_id] = ChainNodeConfig(
            id=node_id,
            export=export,
            node_type=node_type,
            mixer_inputs=mixer_inputs,
            midi_channel=midi_channel,
            cc_map=cc_map,
        )

    # Parse connections (supports "dst:index" syntax for mixer input selection)
    connections: list[Connection] = []
    for i, conn in enumerate(connections_data):
        if not isinstance(conn, (list, tuple)) or len(conn) != 2:
            raise ValidationError(
                f"Connection {i} must be a [from, to] pair, got: {conn}"
            )
        src = str(conn[0])
        dst_raw = str(conn[1])

        # Parse "dst:index" syntax
        dst_input_index: Optional[int] = None
        if ":" in dst_raw:
            parts = dst_raw.rsplit(":", 1)
            try:
                dst_input_index = int(parts[1])
                dst_raw = parts[0]
            except ValueError:
                raise ValidationError(
                    f"Connection {i}: invalid input index in '{conn[1]}'"
                )

        connections.append(Connection(src, dst_raw, dst_input_index))

    return GraphConfig(nodes=nodes, connections=connections)


def validate_linear_chain(graph: GraphConfig) -> list[str]:
    """Validate that a graph represents a linear chain.

    Checks for:
    - audio_in and audio_out endpoints present in connections
    - No duplicate node IDs (handled at parse time)
    - No fan-out (node appears as source in multiple connections)
    - No fan-in (node appears as target in multiple connections)
    - No cycles
    - All nodes referenced in connections exist
    - MIDI channel values in valid range (1-16)
    - CC numbers in valid range (0-127)

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []

    # Check audio_in / audio_out in connections
    sources = [c.src_node for c in graph.connections]
    targets = [c.dst_node for c in graph.connections]

    if "audio_in" not in sources:
        errors.append("Connections must include 'audio_in' as a source")
    if "audio_out" not in targets:
        errors.append("Connections must include 'audio_out' as a target")

    # Reserved names must not appear as node IDs
    reserved = {"audio_in", "audio_out"}
    for name in reserved:
        if name in graph.nodes:
            errors.append(
                f"'{name}' is a reserved name and cannot be used as a node ID"
            )

    # Reject mixer nodes in linear chains
    for node_id, node in graph.nodes.items():
        if node.node_type == "mixer":
            errors.append(
                f"Node '{node_id}': mixer nodes are not allowed in linear chains"
            )

    # Check for fan-out (same source in multiple connections)
    source_counts: dict[str, int] = {}
    for c in graph.connections:
        source_counts[c.src_node] = source_counts.get(c.src_node, 0) + 1
    for src, count in source_counts.items():
        if count > 1:
            errors.append(f"Fan-out detected: '{src}' connects to {count} targets")

    # Check for fan-in (same target in multiple connections)
    target_counts: dict[str, int] = {}
    for c in graph.connections:
        target_counts[c.dst_node] = target_counts.get(c.dst_node, 0) + 1
    for tgt, count in target_counts.items():
        if count > 1:
            errors.append(f"Fan-in detected: '{tgt}' receives from {count} sources")

    # Check all non-reserved references exist in nodes
    all_refs = set(sources) | set(targets)
    for ref in all_refs:
        if ref not in reserved and ref not in graph.nodes:
            errors.append(f"Connection references unknown node '{ref}'")

    # Check all nodes are referenced in connections
    for node_id in graph.nodes:
        if node_id not in all_refs:
            errors.append(f"Node '{node_id}' is not connected in the graph")

    # Validate MIDI channels (1-16)
    for node_id, node in graph.nodes.items():
        if node.midi_channel is not None:
            if not (1 <= node.midi_channel <= 16):
                errors.append(
                    f"Node '{node_id}': midi_channel must be 1-16, got {node.midi_channel}"
                )

    # Validate CC numbers (0-127)
    for node_id, node in graph.nodes.items():
        for cc_num in node.cc_map:
            if not (0 <= cc_num <= 127):
                errors.append(
                    f"Node '{node_id}': CC number must be 0-127, got {cc_num}"
                )

    return errors


def extract_chain_order(graph: GraphConfig) -> list[str]:
    """Walk connections from audio_in to audio_out, returning ordered node IDs.

    Args:
        graph: A validated linear chain graph.

    Returns:
        Ordered list of node IDs from first to last in the chain.

    Raises:
        ValidationError: If the chain is broken or non-linear.
    """
    # Build adjacency: source -> target
    adjacency: dict[str, str] = {}
    for c in graph.connections:
        if c.src_node in adjacency:
            raise ValidationError(f"Fan-out at '{c.src_node}': non-linear graph")
        adjacency[c.src_node] = c.dst_node

    if "audio_in" not in adjacency:
        raise ValidationError("No connection from 'audio_in'")

    order: list[str] = []
    current = adjacency.get("audio_in")

    visited: set[str] = set()
    while current and current != "audio_out":
        if current in visited:
            raise ValidationError(f"Cycle detected at '{current}'")
        if current not in graph.nodes:
            raise ValidationError(f"Connection references unknown node '{current}'")
        visited.add(current)
        order.append(current)
        current = adjacency.get(current)

    if current != "audio_out":
        raise ValidationError("Chain does not reach 'audio_out'")

    return order


def resolve_chain(
    graph: GraphConfig,
    export_dirs: dict[str, Path],
    version: str,
) -> list[ResolvedChainNode]:
    """Resolve a chain graph into fully parsed nodes with manifests.

    Args:
        graph: Validated graph config.
        export_dirs: Mapping of export name -> path to gen~ export directory.
        version: Version string for manifests.

    Returns:
        List of ResolvedChainNode in chain order.

    Raises:
        ValidationError: If exports cannot be found or parsed.
    """
    order = extract_chain_order(graph)

    resolved: list[ResolvedChainNode] = []
    for i, node_id in enumerate(order):
        node_config = graph.nodes[node_id]

        # Assign default MIDI channel if not specified
        if node_config.midi_channel is None:
            node_config.midi_channel = i + 1

        export_name = node_config.export
        if export_name not in export_dirs:
            raise ValidationError(
                f"Node '{node_id}': export '{export_name}' not found. "
                f"Available exports: {sorted(export_dirs.keys())}"
            )

        export_path = export_dirs[export_name]
        try:
            parser = GenExportParser(export_path)
            export_info = parser.parse()
        except Exception as e:
            raise ValidationError(
                f"Node '{node_id}': failed to parse export '{export_name}': {e}"
            ) from e

        manifest = manifest_from_export_info(export_info, [], version)

        resolved.append(
            ResolvedChainNode(
                config=node_config,
                index=i,
                export_info=export_info,
                manifest=manifest,
            )
        )

    return resolved


# ---------------------------------------------------------------------------
# Phase 2: DAG validation, topological sort, buffer allocation, resolution
# ---------------------------------------------------------------------------

_RESERVED_NAMES = {"audio_in", "audio_out"}


def validate_dag(graph: GraphConfig) -> list[str]:
    """Validate that a graph represents a valid DAG (possibly non-linear).

    Checks:
    1. audio_in/audio_out present in connections
    2. Reserved names not used as node IDs
    3. All referenced nodes exist
    4. All nodes connected
    5. Cycle detection via DFS
    6. Connectivity: all nodes reachable from audio_in and reverse-reachable
       from audio_out
    7. Mixer input count matches incoming connection count
    8. MIDI channel/CC validation

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []

    sources = [c.src_node for c in graph.connections]
    targets = [c.dst_node for c in graph.connections]

    # 1. audio_in / audio_out in connections
    if "audio_in" not in sources:
        errors.append("Connections must include 'audio_in' as a source")
    if "audio_out" not in targets:
        errors.append("Connections must include 'audio_out' as a target")

    # 2. Reserved names not used as node IDs
    for name in _RESERVED_NAMES:
        if name in graph.nodes:
            errors.append(
                f"'{name}' is a reserved name and cannot be used as a node ID"
            )

    # 3. All referenced nodes exist
    all_refs = set(sources) | set(targets)
    for ref in all_refs:
        if ref not in _RESERVED_NAMES and ref not in graph.nodes:
            errors.append(f"Connection references unknown node '{ref}'")

    # 4. All nodes connected
    for node_id in graph.nodes:
        if node_id not in all_refs:
            errors.append(f"Node '{node_id}' is not connected in the graph")

    # 5. Cycle detection via DFS
    # Build adjacency list: node -> set of successors
    adj: dict[str, set[str]] = {}
    for c in graph.connections:
        adj.setdefault(c.src_node, set()).add(c.dst_node)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    all_graph_nodes = set(graph.nodes.keys()) | _RESERVED_NAMES
    for n in all_graph_nodes:
        color[n] = WHITE

    def _dfs_cycle(u: str) -> bool:
        color[u] = GRAY
        for v in adj.get(u, set()):
            if color.get(v, WHITE) == GRAY:
                return True  # back edge = cycle
            if color.get(v, WHITE) == WHITE and _dfs_cycle(v):
                return True
        color[u] = BLACK
        return False

    if _dfs_cycle("audio_in"):
        errors.append("Cycle detected in graph")

    # 6. Connectivity: forward from audio_in, backward to audio_out
    # Forward reachability
    forward_reachable: set[str] = set()
    queue: deque[str] = deque(["audio_in"])
    while queue:
        node = queue.popleft()
        if node in forward_reachable:
            continue
        forward_reachable.add(node)
        for v in adj.get(node, set()):
            queue.append(v)

    # Reverse adjacency
    rev_adj: dict[str, set[str]] = {}
    for c in graph.connections:
        rev_adj.setdefault(c.dst_node, set()).add(c.src_node)

    backward_reachable: set[str] = set()
    queue = deque(["audio_out"])
    while queue:
        node = queue.popleft()
        if node in backward_reachable:
            continue
        backward_reachable.add(node)
        for v in rev_adj.get(node, set()):
            queue.append(v)

    for node_id in graph.nodes:
        if node_id not in forward_reachable:
            errors.append(f"Node '{node_id}' is not reachable from audio_in")
        if node_id not in backward_reachable:
            errors.append(f"Node '{node_id}' cannot reach audio_out")

    # 7. Mixer input count matches incoming connections
    for nid, ncfg in graph.nodes.items():
        if ncfg.node_type == "mixer":
            incoming = sum(
                1 for c in graph.connections if c.dst_node == nid
            )
            if incoming != ncfg.mixer_inputs:
                errors.append(
                    f"Node '{nid}': mixer expects {ncfg.mixer_inputs} inputs "
                    f"but has {incoming} incoming connections"
                )

    # 8. MIDI channel/CC validation (shared with linear)
    for nid, ncfg in graph.nodes.items():
        if ncfg.midi_channel is not None:
            if not (1 <= ncfg.midi_channel <= 16):
                errors.append(
                    f"Node '{nid}': midi_channel must be 1-16, "
                    f"got {ncfg.midi_channel}"
                )
        for cc_num in ncfg.cc_map:
            if not (0 <= cc_num <= 127):
                errors.append(
                    f"Node '{nid}': CC number must be 0-127, got {cc_num}"
                )

    return errors


def topological_sort(graph: GraphConfig) -> list[str]:
    """Return a topological ordering of node IDs using Kahn's algorithm.

    Excludes audio_in and audio_out from the result.

    Args:
        graph: A validated DAG graph.

    Returns:
        Ordered list of node IDs in valid execution order.

    Raises:
        ValidationError: If a cycle is detected.
    """
    # Build in-degree map for non-reserved nodes
    in_degree: dict[str, int] = {nid: 0 for nid in graph.nodes}
    adj: dict[str, list[str]] = {nid: [] for nid in graph.nodes}

    for c in graph.connections:
        src = c.src_node
        dst = c.dst_node
        if dst in _RESERVED_NAMES:
            continue
        if src not in _RESERVED_NAMES:
            adj[src].append(dst)
        # Count all incoming edges (including from audio_in)
        in_degree[dst] = in_degree.get(dst, 0) + 1

    # Seed queue with nodes whose only inputs come from audio_in
    # (i.e. in-degree from non-reserved sources is zero after removing audio_in edges)
    # Actually, we count ALL incoming edges including audio_in, then seed with 0-degree
    queue: deque[str] = deque()
    for nid in graph.nodes:
        # Count edges from audio_in separately
        audio_in_edges = sum(
            1 for c in graph.connections
            if c.src_node == "audio_in" and c.dst_node == nid
        )
        # In-degree from non-audio_in sources
        real_in = in_degree[nid] - audio_in_edges
        if real_in == 0:
            queue.append(nid)

    result: list[str] = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for successor in adj[node]:
            in_degree[successor] -= 1
            # Check if all non-audio_in predecessors are processed
            audio_in_edges = sum(
                1 for c in graph.connections
                if c.src_node == "audio_in" and c.dst_node == successor
            )
            remaining = in_degree[successor] - audio_in_edges
            if remaining == 0:
                queue.append(successor)

    if len(result) != len(graph.nodes):
        raise ValidationError(
            "Cycle detected in graph during topological sort"
        )

    return result


def allocate_edge_buffers(
    graph: GraphConfig,
    resolved_nodes: dict[str, ResolvedChainNode],
    topo_order: list[str],
) -> tuple[list[EdgeBuffer], int]:
    """Allocate intermediate buffers for DAG edges.

    Fan-out edges from the same source share one buffer_id (zero-copy,
    since gen~ does not mutate input buffers). Edges from audio_in use
    the hardware input buffer (buffer_id = -1, not allocated).

    Args:
        graph: Validated DAG graph config.
        resolved_nodes: Mapping of node_id -> ResolvedChainNode.
        topo_order: Topological ordering of node IDs.

    Returns:
        Tuple of (list of EdgeBuffer, total number of allocated buffers).
    """
    # Assign buffer IDs per source node (fan-out sharing)
    source_buffer: dict[str, int] = {}
    next_buffer_id = 0

    edge_buffers: list[EdgeBuffer] = []

    for c in graph.connections:
        if c.dst_node == "audio_out":
            # audio_out edges: the last node writes directly to the output
            # We still track them but they use the source's buffer
            pass

        if c.src_node == "audio_in":
            # audio_in edges use hardware input buffer (no allocation)
            num_channels = 2  # hardware stereo input
            edge_buffers.append(
                EdgeBuffer(
                    buffer_id=-1,
                    src_node=c.src_node,
                    dst_node=c.dst_node,
                    dst_input_index=c.dst_input_index,
                    num_channels=num_channels,
                )
            )
            continue

        # Allocate or reuse buffer for this source
        if c.src_node not in source_buffer:
            source_buffer[c.src_node] = next_buffer_id
            next_buffer_id += 1

        buf_id = source_buffer[c.src_node]

        # Channel count from source's output count
        src_node = resolved_nodes[c.src_node]
        num_channels = src_node.manifest.num_outputs

        edge_buffers.append(
            EdgeBuffer(
                buffer_id=buf_id,
                src_node=c.src_node,
                dst_node=c.dst_node,
                dst_input_index=c.dst_input_index,
                num_channels=num_channels,
            )
        )

    return edge_buffers, next_buffer_id


def resolve_dag(
    graph: GraphConfig,
    export_dirs: dict[str, Path],
    version: str,
) -> list[ResolvedChainNode]:
    """Resolve a DAG graph into fully parsed nodes with manifests.

    For gen~ nodes: parses export, creates manifest (same as resolve_chain).
    For mixer nodes: constructs a synthetic Manifest with gain_N parameters.

    Args:
        graph: Validated DAG graph config.
        export_dirs: Mapping of export name -> path to gen~ export directory.
        version: Version string for manifests.

    Returns:
        List of ResolvedChainNode in topological order.

    Raises:
        ValidationError: If exports cannot be found or parsed.
    """
    topo_order = topological_sort(graph)

    resolved: list[ResolvedChainNode] = []
    for i, node_id in enumerate(topo_order):
        node_config = graph.nodes[node_id]

        # Assign default MIDI channel if not specified
        if node_config.midi_channel is None:
            node_config.midi_channel = i + 1

        if node_config.node_type == "mixer":
            # Synthetic manifest for mixer node
            # Determine actual incoming connections
            incoming = [
                c for c in graph.connections if c.dst_node == node_id
            ]
            n_inputs = len(incoming)

            # Mixer output channels = max channel count of inputs
            max_ch = 2  # default stereo
            # We'll refine this after all gen nodes are resolved
            # For now use the declared mixer_inputs
            params = [
                ParamInfo(
                    index=j,
                    name=f"gain_{j}",
                    has_minmax=True,
                    min=0.0,
                    max=2.0,
                    default=1.0,
                )
                for j in range(n_inputs)
            ]
            manifest = Manifest(
                gen_name=f"mixer_{node_id}",
                num_inputs=n_inputs,
                num_outputs=max_ch,
                params=params,
            )
            resolved.append(
                ResolvedChainNode(
                    config=node_config,
                    index=i,
                    export_info=None,
                    manifest=manifest,
                )
            )
        else:
            # gen~ node
            export_name = node_config.export
            if export_name not in export_dirs:
                raise ValidationError(
                    f"Node '{node_id}': export '{export_name}' not found. "
                    f"Available exports: {sorted(export_dirs.keys())}"
                )

            export_path = export_dirs[export_name]
            try:
                parser = GenExportParser(export_path)
                export_info = parser.parse()
            except Exception as e:
                raise ValidationError(
                    f"Node '{node_id}': failed to parse export "
                    f"'{export_name}': {e}"
                ) from e

            manifest = manifest_from_export_info(export_info, [], version)
            resolved.append(
                ResolvedChainNode(
                    config=node_config,
                    index=i,
                    export_info=export_info,
                    manifest=manifest,
                )
            )

    # Second pass: refine mixer output channels based on resolved input channels
    resolved_map = {n.config.id: n for n in resolved}
    for node in resolved:
        if node.config.node_type == "mixer":
            incoming = [
                c for c in graph.connections if c.dst_node == node.config.id
            ]
            max_ch = 0
            for c in incoming:
                if c.src_node == "audio_in":
                    max_ch = max(max_ch, 2)  # hardware stereo
                elif c.src_node in resolved_map:
                    max_ch = max(
                        max_ch, resolved_map[c.src_node].manifest.num_outputs
                    )
            if max_ch > 0:
                node.manifest.num_outputs = max_ch

    return resolved
