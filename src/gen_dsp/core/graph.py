"""
Graph data model for multi-plugin chain configurations.

Defines the JSON graph format and validation logic for serial chains
of gen~ plugins. Phase 1 supports only linear chains (no fan-out,
fan-in, or cycles).

Typical flow:
    graph.json -> parse_graph() -> GraphConfig
              -> validate_linear_chain() -> errors (if any)
              -> extract_chain_order() -> ordered node IDs
              -> resolve_chain() -> list[ResolvedChainNode]
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from gen_dsp.core.manifest import Manifest, manifest_from_export_info
from gen_dsp.core.parser import ExportInfo, GenExportParser
from gen_dsp.errors import ValidationError


@dataclass
class ChainNodeConfig:
    """Configuration for a single node in the chain graph."""

    id: str
    export: str
    midi_channel: Optional[int] = None
    cc_map: dict[int, str] = field(default_factory=dict)


@dataclass
class GraphConfig:
    """Parsed graph configuration from JSON."""

    nodes: dict[str, ChainNodeConfig]
    connections: list[tuple[str, str]]


@dataclass
class ResolvedChainNode:
    """A chain node with fully resolved export info and manifest."""

    config: ChainNodeConfig
    index: int
    export_info: ExportInfo
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

        if "export" not in node_data:
            raise ValidationError(f"Node '{node_id}' must have an 'export' field")

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
            export=node_data["export"],
            midi_channel=midi_channel,
            cc_map=cc_map,
        )

    # Parse connections
    connections: list[tuple[str, str]] = []
    for i, conn in enumerate(connections_data):
        if not isinstance(conn, (list, tuple)) or len(conn) != 2:
            raise ValidationError(
                f"Connection {i} must be a [from, to] pair, got: {conn}"
            )
        connections.append((str(conn[0]), str(conn[1])))

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
    sources = [c[0] for c in graph.connections]
    targets = [c[1] for c in graph.connections]

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

    # Check for fan-out (same source in multiple connections)
    source_counts: dict[str, int] = {}
    for src, _ in graph.connections:
        source_counts[src] = source_counts.get(src, 0) + 1
    for src, count in source_counts.items():
        if count > 1:
            errors.append(f"Fan-out detected: '{src}' connects to {count} targets")

    # Check for fan-in (same target in multiple connections)
    target_counts: dict[str, int] = {}
    for _, tgt in graph.connections:
        target_counts[tgt] = target_counts.get(tgt, 0) + 1
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
    for src, tgt in graph.connections:
        if src in adjacency:
            raise ValidationError(f"Fan-out at '{src}': non-linear graph")
        adjacency[src] = tgt

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
