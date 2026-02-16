"""Tests for the graph data model (multi-plugin chain configurations)."""

import json
from pathlib import Path

import pytest

from gen_dsp.core.graph import (
    ChainNodeConfig,
    Connection,
    GraphConfig,
    ResolvedChainNode,
    allocate_edge_buffers,
    parse_graph,
    resolve_dag,
    topological_sort,
    validate_dag,
    validate_linear_chain,
    extract_chain_order,
    resolve_chain,
)
from gen_dsp.errors import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_graph(tmp_path: Path, data: dict) -> Path:
    """Write a graph JSON file and return its path."""
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(data), encoding="utf-8")
    return graph_path


def _simple_graph_data() -> dict:
    """Return a minimal valid linear chain graph."""
    return {
        "nodes": {
            "reverb": {"export": "gigaverb"},
            "delay": {"export": "spectraldelayfb"},
        },
        "connections": [
            ["audio_in", "reverb"],
            ["reverb", "delay"],
            ["delay", "audio_out"],
        ],
    }


def _single_node_graph_data() -> dict:
    """Return a single-node chain graph."""
    return {
        "nodes": {
            "reverb": {"export": "gigaverb"},
        },
        "connections": [
            ["audio_in", "reverb"],
            ["reverb", "audio_out"],
        ],
    }


# ---------------------------------------------------------------------------
# TestGraphParsing
# ---------------------------------------------------------------------------


class TestGraphParsing:
    """Test parse_graph() JSON loading and validation."""

    def test_parse_minimal_graph(self, tmp_path):
        """Parse a minimal valid graph."""
        path = _write_graph(tmp_path, _simple_graph_data())
        graph = parse_graph(path)

        assert len(graph.nodes) == 2
        assert "reverb" in graph.nodes
        assert "delay" in graph.nodes
        assert graph.nodes["reverb"].export == "gigaverb"
        assert graph.nodes["delay"].export == "spectraldelayfb"
        assert len(graph.connections) == 3

    def test_parse_graph_with_midi_channel(self, tmp_path):
        """Parse a graph with explicit MIDI channel assignments."""
        data = _simple_graph_data()
        data["nodes"]["reverb"]["midi_channel"] = 3
        data["nodes"]["delay"]["midi_channel"] = 5

        path = _write_graph(tmp_path, data)
        graph = parse_graph(path)

        assert graph.nodes["reverb"].midi_channel == 3
        assert graph.nodes["delay"].midi_channel == 5

    def test_parse_graph_with_cc_map(self, tmp_path):
        """Parse a graph with explicit CC-to-parameter mappings."""
        data = _simple_graph_data()
        data["nodes"]["reverb"]["cc"] = {"21": "revtime", "22": "damping"}

        path = _write_graph(tmp_path, data)
        graph = parse_graph(path)

        assert graph.nodes["reverb"].cc_map == {21: "revtime", 22: "damping"}

    def test_parse_graph_missing_file(self, tmp_path):
        """Reject missing graph file."""
        with pytest.raises(ValidationError, match="not found"):
            parse_graph(tmp_path / "nonexistent.json")

    def test_parse_graph_invalid_json(self, tmp_path):
        """Reject invalid JSON."""
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("{bad json", encoding="utf-8")
        with pytest.raises(ValidationError, match="Invalid JSON"):
            parse_graph(bad_path)

    def test_parse_graph_not_object(self, tmp_path):
        """Reject non-object JSON."""
        path = _write_graph(tmp_path, [1, 2, 3])
        with pytest.raises(ValidationError, match="must be an object"):
            parse_graph(path)

    def test_parse_graph_missing_nodes(self, tmp_path):
        """Reject graph without 'nodes' key."""
        path = _write_graph(tmp_path, {"connections": []})
        with pytest.raises(ValidationError, match="'nodes'"):
            parse_graph(path)

    def test_parse_graph_missing_connections(self, tmp_path):
        """Reject graph without 'connections' key."""
        path = _write_graph(tmp_path, {"nodes": {}})
        with pytest.raises(ValidationError, match="'connections'"):
            parse_graph(path)

    def test_parse_graph_node_missing_export(self, tmp_path):
        """Reject node without 'export' field."""
        data = {
            "nodes": {"bad_node": {"midi_channel": 1}},
            "connections": [["audio_in", "bad_node"], ["bad_node", "audio_out"]],
        }
        path = _write_graph(tmp_path, data)
        with pytest.raises(ValidationError, match="'export'"):
            parse_graph(path)

    def test_parse_graph_invalid_cc_key(self, tmp_path):
        """Reject non-integer CC key."""
        data = _simple_graph_data()
        data["nodes"]["reverb"]["cc"] = {"abc": "revtime"}
        path = _write_graph(tmp_path, data)
        with pytest.raises(ValidationError, match="CC key"):
            parse_graph(path)

    def test_parse_graph_invalid_midi_channel_type(self, tmp_path):
        """Reject non-integer midi_channel."""
        data = _simple_graph_data()
        data["nodes"]["reverb"]["midi_channel"] = "three"
        path = _write_graph(tmp_path, data)
        with pytest.raises(ValidationError, match="midi_channel"):
            parse_graph(path)

    def test_parse_graph_bad_connection_format(self, tmp_path):
        """Reject connection that is not a [from, to] pair."""
        data = {
            "nodes": {"reverb": {"export": "gigaverb"}},
            "connections": [["audio_in", "reverb", "extra"]],
        }
        path = _write_graph(tmp_path, data)
        with pytest.raises(ValidationError, match="\\[from, to\\] pair"):
            parse_graph(path)

    def test_parse_graph_default_midi_channel_is_none(self, tmp_path):
        """Nodes without midi_channel should default to None (assigned later)."""
        path = _write_graph(tmp_path, _simple_graph_data())
        graph = parse_graph(path)

        assert graph.nodes["reverb"].midi_channel is None
        assert graph.nodes["delay"].midi_channel is None


# ---------------------------------------------------------------------------
# TestChainValidation
# ---------------------------------------------------------------------------


class TestChainValidation:
    """Test validate_linear_chain() error detection."""

    def test_valid_chain_no_errors(self):
        """A valid linear chain produces no errors."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "b"),
                Connection("b", "audio_out"),
            ],
        )
        assert validate_linear_chain(graph) == []

    def test_missing_audio_in(self):
        """Reject graph without audio_in source."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[Connection("a", "audio_out")],
        )
        errors = validate_linear_chain(graph)
        assert any("audio_in" in e for e in errors)

    def test_missing_audio_out(self):
        """Reject graph without audio_out target."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[Connection("audio_in", "a")],
        )
        errors = validate_linear_chain(graph)
        assert any("audio_out" in e for e in errors)

    def test_fan_out_detected(self):
        """Reject graph with fan-out (one source to multiple targets)."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "b"),
                Connection("a", "audio_out"),
            ],
        )
        errors = validate_linear_chain(graph)
        assert any("Fan-out" in e for e in errors)

    def test_fan_in_detected(self):
        """Reject graph with fan-in (multiple sources to one target)."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("audio_in", "b"),
                Connection("a", "audio_out"),
            ],
        )
        errors = validate_linear_chain(graph)
        assert any("Fan-in" in e or "Fan-out" in e for e in errors)

    def test_unknown_node_reference(self):
        """Reject connection referencing unknown node."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "unknown_node"),
                Connection("unknown_node", "audio_out"),
            ],
        )
        errors = validate_linear_chain(graph)
        assert any("unknown_node" in e for e in errors)

    def test_unconnected_node(self):
        """Reject node that is not referenced in any connection."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "orphan": ChainNodeConfig(id="orphan", export="ex_orphan"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "audio_out"),
            ],
        )
        errors = validate_linear_chain(graph)
        assert any("orphan" in e for e in errors)

    def test_invalid_midi_channel_too_high(self):
        """Reject MIDI channel > 16."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a", midi_channel=17),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "audio_out"),
            ],
        )
        errors = validate_linear_chain(graph)
        assert any("midi_channel" in e for e in errors)

    def test_invalid_midi_channel_zero(self):
        """Reject MIDI channel 0."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a", midi_channel=0),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "audio_out"),
            ],
        )
        errors = validate_linear_chain(graph)
        assert any("midi_channel" in e for e in errors)

    def test_invalid_cc_number(self):
        """Reject CC number > 127."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a", cc_map={128: "param"}),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "audio_out"),
            ],
        )
        errors = validate_linear_chain(graph)
        assert any("CC number" in e for e in errors)

    def test_reserved_name_as_node_id(self):
        """Reject audio_in or audio_out used as node IDs."""
        graph = GraphConfig(
            nodes={
                "audio_in": ChainNodeConfig(id="audio_in", export="ex_a"),
            },
            connections=[
                Connection("audio_in", "audio_out"),
            ],
        )
        errors = validate_linear_chain(graph)
        assert any("reserved" in e for e in errors)


# ---------------------------------------------------------------------------
# TestChainOrdering
# ---------------------------------------------------------------------------


class TestChainOrdering:
    """Test extract_chain_order() path walking."""

    def test_two_node_chain(self):
        """Walk a simple two-node chain."""
        graph = GraphConfig(
            nodes={
                "reverb": ChainNodeConfig(id="reverb", export="gigaverb"),
                "delay": ChainNodeConfig(id="delay", export="spectraldelayfb"),
            },
            connections=[
                Connection("audio_in", "reverb"),
                Connection("reverb", "delay"),
                Connection("delay", "audio_out"),
            ],
        )
        order = extract_chain_order(graph)
        assert order == ["reverb", "delay"]

    def test_single_node_chain(self):
        """Walk a single-node chain."""
        graph = GraphConfig(
            nodes={
                "reverb": ChainNodeConfig(id="reverb", export="gigaverb"),
            },
            connections=[
                Connection("audio_in", "reverb"),
                Connection("reverb", "audio_out"),
            ],
        )
        order = extract_chain_order(graph)
        assert order == ["reverb"]

    def test_three_node_chain(self):
        """Walk a three-node chain in correct order."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
                "c": ChainNodeConfig(id="c", export="ex_c"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "b"),
                Connection("b", "c"),
                Connection("c", "audio_out"),
            ],
        )
        order = extract_chain_order(graph)
        assert order == ["a", "b", "c"]

    def test_broken_chain_raises(self):
        """Raise if chain does not reach audio_out."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                # Missing: Connection("a", "b") and Connection("b", "audio_out")
            ],
        )
        with pytest.raises(ValidationError, match="audio_out"):
            extract_chain_order(graph)

    def test_no_audio_in_raises(self):
        """Raise if there is no audio_in connection."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[Connection("a", "audio_out")],
        )
        with pytest.raises(ValidationError, match="audio_in"):
            extract_chain_order(graph)

    def test_cycle_detected(self):
        """Raise on cycle in graph."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "b"),
                Connection("b", "a"),  # cycle
            ],
        )
        # validate_linear_chain would catch this as fan-out/fan-in,
        # but extract_chain_order should also detect cycles
        with pytest.raises(ValidationError):
            extract_chain_order(graph)


# ---------------------------------------------------------------------------
# TestChainResolution
# ---------------------------------------------------------------------------


class TestChainResolution:
    """Test resolve_chain() with real fixture exports."""

    def test_resolve_single_node(self, gigaverb_export):
        """Resolve a single-node chain with gigaverb fixture."""
        graph = GraphConfig(
            nodes={
                "reverb": ChainNodeConfig(id="reverb", export="gigaverb"),
            },
            connections=[
                Connection("audio_in", "reverb"),
                Connection("reverb", "audio_out"),
            ],
        )
        export_dirs = {"gigaverb": gigaverb_export}
        chain = resolve_chain(graph, export_dirs, "0.8.0")

        assert len(chain) == 1
        assert chain[0].config.id == "reverb"
        assert chain[0].index == 0
        assert chain[0].manifest.num_inputs == 2
        assert chain[0].manifest.num_outputs == 2
        assert chain[0].config.midi_channel == 1  # auto-assigned

    def test_resolve_two_node_chain(self, gigaverb_export, spectraldelayfb_export):
        """Resolve a two-node chain with different fixtures."""
        graph = GraphConfig(
            nodes={
                "reverb": ChainNodeConfig(id="reverb", export="gigaverb"),
                "delay": ChainNodeConfig(id="delay", export="spectraldelayfb"),
            },
            connections=[
                Connection("audio_in", "reverb"),
                Connection("reverb", "delay"),
                Connection("delay", "audio_out"),
            ],
        )
        export_dirs = {
            "gigaverb": gigaverb_export,
            "spectraldelayfb": spectraldelayfb_export,
        }
        chain = resolve_chain(graph, export_dirs, "0.8.0")

        assert len(chain) == 2
        assert chain[0].config.id == "reverb"
        assert chain[0].index == 0
        assert chain[0].config.midi_channel == 1
        assert chain[1].config.id == "delay"
        assert chain[1].index == 1
        assert chain[1].config.midi_channel == 2

    def test_resolve_preserves_explicit_midi_channel(self, gigaverb_export):
        """Explicit MIDI channels are preserved, not overwritten by defaults."""
        graph = GraphConfig(
            nodes={
                "reverb": ChainNodeConfig(
                    id="reverb", export="gigaverb", midi_channel=5
                ),
            },
            connections=[
                Connection("audio_in", "reverb"),
                Connection("reverb", "audio_out"),
            ],
        )
        export_dirs = {"gigaverb": gigaverb_export}
        chain = resolve_chain(graph, export_dirs, "0.8.0")

        assert chain[0].config.midi_channel == 5

    def test_resolve_missing_export(self, gigaverb_export):
        """Raise if an export name is not in export_dirs."""
        graph = GraphConfig(
            nodes={
                "reverb": ChainNodeConfig(id="reverb", export="nonexistent"),
            },
            connections=[
                Connection("audio_in", "reverb"),
                Connection("reverb", "audio_out"),
            ],
        )
        export_dirs = {"gigaverb": gigaverb_export}
        with pytest.raises(ValidationError, match="nonexistent"):
            resolve_chain(graph, export_dirs, "0.8.0")

    def test_resolve_bad_export_path(self, tmp_path):
        """Raise if export path does not contain a valid gen~ export."""
        graph = GraphConfig(
            nodes={
                "bad": ChainNodeConfig(id="bad", export="empty"),
            },
            connections=[
                Connection("audio_in", "bad"),
                Connection("bad", "audio_out"),
            ],
        )
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        export_dirs = {"empty": empty_dir}
        with pytest.raises(ValidationError, match="failed to parse"):
            resolve_chain(graph, export_dirs, "0.8.0")


# ---------------------------------------------------------------------------
# Phase 2: DAG tests
# ---------------------------------------------------------------------------


def _diamond_dag_data() -> dict:
    """Return a diamond DAG: audio_in -> reverb + delay -> mix -> audio_out."""
    return {
        "nodes": {
            "reverb": {"export": "gigaverb"},
            "delay": {"export": "spectraldelayfb"},
            "mix": {"type": "mixer", "inputs": 2},
        },
        "connections": [
            ["audio_in", "reverb"],
            ["audio_in", "delay"],
            ["reverb", "mix:0"],
            ["delay", "mix:1"],
            ["mix", "audio_out"],
        ],
    }


def _diamond_graph() -> GraphConfig:
    """Construct a diamond DAG GraphConfig directly."""
    return GraphConfig(
        nodes={
            "reverb": ChainNodeConfig(id="reverb", export="gigaverb", node_type="gen"),
            "delay": ChainNodeConfig(
                id="delay", export="spectraldelayfb", node_type="gen"
            ),
            "mix": ChainNodeConfig(id="mix", node_type="mixer", mixer_inputs=2),
        },
        connections=[
            Connection("audio_in", "reverb"),
            Connection("audio_in", "delay"),
            Connection("reverb", "mix", dst_input_index=0),
            Connection("delay", "mix", dst_input_index=1),
            Connection("mix", "audio_out"),
        ],
    )


class TestConnectionParsing:
    """Test Connection dataclass and :index parsing."""

    def test_parse_connection_without_index(self, tmp_path):
        """Simple connection without input index."""
        data = _simple_graph_data()
        path = _write_graph(tmp_path, data)
        graph = parse_graph(path)
        for c in graph.connections:
            assert c.dst_input_index is None

    def test_parse_connection_with_index(self, tmp_path):
        """Connection with :index syntax parses dst_input_index."""
        data = _diamond_dag_data()
        path = _write_graph(tmp_path, data)
        graph = parse_graph(path)
        indexed = [c for c in graph.connections if c.dst_input_index is not None]
        assert len(indexed) == 2
        indices = sorted(c.dst_input_index for c in indexed)
        assert indices == [0, 1]

    def test_parse_connection_invalid_index(self, tmp_path):
        """Invalid :index syntax raises ValidationError."""
        data = {
            "nodes": {"a": {"export": "gigaverb"}},
            "connections": [["audio_in", "a:abc"]],
        }
        path = _write_graph(tmp_path, data)
        with pytest.raises(ValidationError, match="invalid input index"):
            parse_graph(path)

    def test_connection_backward_compat(self, tmp_path):
        """Linear chain connections still work (no :index)."""
        data = _simple_graph_data()
        path = _write_graph(tmp_path, data)
        graph = parse_graph(path)
        assert len(graph.connections) == 3
        assert graph.connections[0].src_node == "audio_in"
        assert graph.connections[0].dst_node == "reverb"


class TestMixerNodeParsing:
    """Test mixer node parsing and validation."""

    def test_parse_mixer_node(self, tmp_path):
        """Mixer node has correct type and inputs."""
        data = _diamond_dag_data()
        path = _write_graph(tmp_path, data)
        graph = parse_graph(path)
        mix = graph.nodes["mix"]
        assert mix.node_type == "mixer"
        assert mix.mixer_inputs == 2
        assert mix.export is None

    def test_mixer_node_missing_inputs(self, tmp_path):
        """Mixer node without 'inputs' field raises error."""
        data = {
            "nodes": {"mix": {"type": "mixer"}},
            "connections": [["audio_in", "mix"], ["mix", "audio_out"]],
        }
        path = _write_graph(tmp_path, data)
        with pytest.raises(ValidationError, match="inputs"):
            parse_graph(path)

    def test_mixer_node_invalid_inputs(self, tmp_path):
        """Mixer node with non-positive 'inputs' raises error."""
        data = {
            "nodes": {"mix": {"type": "mixer", "inputs": 0}},
            "connections": [["audio_in", "mix"], ["mix", "audio_out"]],
        }
        path = _write_graph(tmp_path, data)
        with pytest.raises(ValidationError, match="positive integer"):
            parse_graph(path)

    def test_unknown_node_type(self, tmp_path):
        """Unknown node type raises error."""
        data = {
            "nodes": {"a": {"type": "splitter"}},
            "connections": [["audio_in", "a"], ["a", "audio_out"]],
        }
        path = _write_graph(tmp_path, data)
        with pytest.raises(ValidationError, match="unknown node type"):
            parse_graph(path)

    def test_linear_validation_rejects_mixer(self):
        """validate_linear_chain rejects mixer nodes."""
        graph = _diamond_graph()
        errors = validate_linear_chain(graph)
        assert any("mixer" in e for e in errors)


class TestValidateDAG:
    """Test validate_dag() error detection."""

    def test_valid_diamond_dag(self):
        """A valid diamond DAG produces no errors."""
        graph = _diamond_graph()
        assert validate_dag(graph) == []

    def test_dag_missing_audio_in(self):
        """Reject DAG without audio_in."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[Connection("a", "audio_out")],
        )
        errors = validate_dag(graph)
        assert any("audio_in" in e for e in errors)

    def test_dag_missing_audio_out(self):
        """Reject DAG without audio_out."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[Connection("audio_in", "a")],
        )
        errors = validate_dag(graph)
        assert any("audio_out" in e for e in errors)

    def test_dag_cycle_detected(self):
        """Reject DAG with cycle."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "b"),
                Connection("b", "a"),
                Connection("b", "audio_out"),
            ],
        )
        errors = validate_dag(graph)
        assert any("Cycle" in e for e in errors)

    def test_dag_disconnected_node(self):
        """Reject node not connected in graph."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "orphan": ChainNodeConfig(id="orphan", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "audio_out"),
            ],
        )
        errors = validate_dag(graph)
        assert any("orphan" in e for e in errors)

    def test_dag_unreachable_from_audio_in(self):
        """Reject node not reachable from audio_in."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "audio_out"),
                Connection("b", "audio_out"),
            ],
        )
        errors = validate_dag(graph)
        assert any("not reachable from audio_in" in e for e in errors)

    def test_dag_cannot_reach_audio_out(self):
        """Reject node that cannot reach audio_out."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("audio_in", "b"),
                Connection("a", "audio_out"),
            ],
        )
        errors = validate_dag(graph)
        assert any("cannot reach audio_out" in e for e in errors)

    def test_dag_mixer_input_count_mismatch(self):
        """Reject mixer with wrong incoming connection count."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "mix": ChainNodeConfig(id="mix", node_type="mixer", mixer_inputs=3),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "mix"),
                Connection("mix", "audio_out"),
            ],
        )
        errors = validate_dag(graph)
        assert any("expects 3 inputs but has 1" in e for e in errors)

    def test_dag_reserved_name(self):
        """Reject reserved names as node IDs."""
        graph = GraphConfig(
            nodes={
                "audio_in": ChainNodeConfig(id="audio_in", export="ex_a"),
            },
            connections=[Connection("audio_in", "audio_out")],
        )
        errors = validate_dag(graph)
        assert any("reserved" in e for e in errors)

    def test_dag_invalid_midi_channel(self):
        """Reject invalid MIDI channel."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a", midi_channel=17),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "audio_out"),
            ],
        )
        errors = validate_dag(graph)
        assert any("midi_channel" in e for e in errors)

    def test_valid_linear_dag(self):
        """A linear graph also passes DAG validation."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "b"),
                Connection("b", "audio_out"),
            ],
        )
        assert validate_dag(graph) == []


class TestTopologicalSort:
    """Test topological_sort() ordering."""

    def test_diamond_dag(self):
        """Diamond DAG: reverb and delay before mix."""
        graph = _diamond_graph()
        order = topological_sort(graph)
        assert len(order) == 3
        assert order.index("mix") > order.index("reverb")
        assert order.index("mix") > order.index("delay")

    def test_fan_out_dag(self):
        """Fan-out: single source feeds two targets, both before final."""
        graph = GraphConfig(
            nodes={
                "src": ChainNodeConfig(id="src", export="ex_a"),
                "a": ChainNodeConfig(id="a", export="ex_b"),
                "b": ChainNodeConfig(id="b", export="ex_c"),
                "mix": ChainNodeConfig(id="mix", node_type="mixer", mixer_inputs=2),
            },
            connections=[
                Connection("audio_in", "src"),
                Connection("src", "a"),
                Connection("src", "b"),
                Connection("a", "mix", dst_input_index=0),
                Connection("b", "mix", dst_input_index=1),
                Connection("mix", "audio_out"),
            ],
        )
        order = topological_sort(graph)
        assert order.index("src") < order.index("a")
        assert order.index("src") < order.index("b")
        assert order.index("a") < order.index("mix")
        assert order.index("b") < order.index("mix")

    def test_single_node(self):
        """Single node returns just that node."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "audio_out"),
            ],
        )
        assert topological_sort(graph) == ["a"]

    def test_linear_chain(self):
        """Linear chain returns correct order."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
                "c": ChainNodeConfig(id="c", export="ex_c"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "b"),
                Connection("b", "c"),
                Connection("c", "audio_out"),
            ],
        )
        assert topological_sort(graph) == ["a", "b", "c"]


class TestAllocateEdgeBuffers:
    """Test allocate_edge_buffers() buffer assignment."""

    def _make_resolved_map(
        self,
        nodes: dict[str, tuple[int, int]],
    ) -> dict[str, ResolvedChainNode]:
        """Create a minimal resolved node map for buffer allocation tests."""
        from gen_dsp.core.manifest import Manifest
        from gen_dsp.core.parser import ExportInfo

        result = {}
        for i, (nid, (n_in, n_out)) in enumerate(nodes.items()):
            config = ChainNodeConfig(id=nid, export=f"ex_{nid}")
            info = ExportInfo(
                name=f"gen_{nid}",
                path=Path(f"/fake/{nid}"),
                num_inputs=n_in,
                num_outputs=n_out,
            )
            manifest = Manifest(
                gen_name=f"gen_{nid}",
                num_inputs=n_in,
                num_outputs=n_out,
            )
            result[nid] = ResolvedChainNode(
                config=config, index=i, export_info=info, manifest=manifest
            )
        return result

    def test_fan_out_shares_buffer(self):
        """Fan-out edges from same source share one buffer_id."""
        graph = GraphConfig(
            nodes={
                "src": ChainNodeConfig(id="src", export="ex_a"),
                "a": ChainNodeConfig(id="a", export="ex_b"),
                "b": ChainNodeConfig(id="b", export="ex_c"),
            },
            connections=[
                Connection("audio_in", "src"),
                Connection("src", "a"),
                Connection("src", "b"),
                Connection("a", "audio_out"),
                Connection("b", "audio_out"),
            ],
        )
        resolved = self._make_resolved_map({"src": (2, 2), "a": (2, 2), "b": (2, 2)})
        topo = ["src", "a", "b"]
        edges, total = allocate_edge_buffers(graph, resolved, topo)

        # Edges from src should share the same buffer_id
        src_edges = [e for e in edges if e.src_node == "src"]
        assert len(src_edges) == 2
        assert src_edges[0].buffer_id == src_edges[1].buffer_id

    def test_audio_in_edges_not_allocated(self):
        """Edges from audio_in have buffer_id = -1."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "audio_out"),
            ],
        )
        resolved = self._make_resolved_map({"a": (2, 2)})
        edges, total = allocate_edge_buffers(graph, resolved, ["a"])

        audio_in_edges = [e for e in edges if e.src_node == "audio_in"]
        assert len(audio_in_edges) == 1
        assert audio_in_edges[0].buffer_id == -1

    def test_buffer_count(self):
        """Total buffer count matches unique source allocations."""
        graph = _diamond_graph()
        resolved = self._make_resolved_map(
            {
                "reverb": (2, 2),
                "delay": (3, 2),
                "mix": (2, 2),
            }
        )
        topo = ["reverb", "delay", "mix"]
        edges, total = allocate_edge_buffers(graph, resolved, topo)

        # Sources needing buffers: reverb, delay, mix = 3 allocated buffers
        assert total == 3

    def test_channel_count_from_source(self):
        """Edge channel count comes from source node's output count."""
        graph = GraphConfig(
            nodes={
                "a": ChainNodeConfig(id="a", export="ex_a"),
                "b": ChainNodeConfig(id="b", export="ex_b"),
            },
            connections=[
                Connection("audio_in", "a"),
                Connection("a", "b"),
                Connection("b", "audio_out"),
            ],
        )
        resolved = self._make_resolved_map({"a": (2, 3), "b": (3, 2)})
        edges, _ = allocate_edge_buffers(graph, resolved, ["a", "b"])
        a_to_b = [e for e in edges if e.src_node == "a" and e.dst_node == "b"]
        assert len(a_to_b) == 1
        assert a_to_b[0].num_channels == 3  # a outputs 3 channels


class TestResolveDAG:
    """Test resolve_dag() with real fixtures."""

    def test_resolve_diamond_dag(self, gigaverb_export, spectraldelayfb_export):
        """Resolve a diamond DAG with mixer node."""
        graph = _diamond_graph()
        export_dirs = {
            "gigaverb": gigaverb_export,
            "spectraldelayfb": spectraldelayfb_export,
        }
        resolved = resolve_dag(graph, export_dirs, "0.8.0")

        assert len(resolved) == 3
        node_ids = [n.config.id for n in resolved]
        # mix must come after reverb and delay
        assert node_ids.index("mix") > node_ids.index("reverb")
        assert node_ids.index("mix") > node_ids.index("delay")

        # Mixer node has synthetic manifest
        mix_node = [n for n in resolved if n.config.id == "mix"][0]
        assert mix_node.export_info is None
        assert mix_node.manifest.num_params == 2
        assert mix_node.manifest.params[0].name == "gain_0"
        assert mix_node.manifest.params[1].name == "gain_1"

    def test_resolve_dag_assigns_midi_channels(
        self, gigaverb_export, spectraldelayfb_export
    ):
        """Default MIDI channels are auto-assigned by topological order."""
        graph = _diamond_graph()
        export_dirs = {
            "gigaverb": gigaverb_export,
            "spectraldelayfb": spectraldelayfb_export,
        }
        resolved = resolve_dag(graph, export_dirs, "0.8.0")
        channels = [n.config.midi_channel for n in resolved]
        assert channels == [1, 2, 3]

    def test_resolve_dag_mixer_output_channels(
        self, gigaverb_export, spectraldelayfb_export
    ):
        """Mixer output channels = max of input channel counts."""
        graph = _diamond_graph()
        export_dirs = {
            "gigaverb": gigaverb_export,
            "spectraldelayfb": spectraldelayfb_export,
        }
        resolved = resolve_dag(graph, export_dirs, "0.8.0")
        mix_node = [n for n in resolved if n.config.id == "mix"][0]
        # gigaverb outputs 2, spectraldelayfb outputs 2
        assert mix_node.manifest.num_outputs == 2

    def test_resolve_dag_missing_export(self, gigaverb_export):
        """Raise if export is not found."""
        graph = _diamond_graph()
        export_dirs = {"gigaverb": gigaverb_export}
        with pytest.raises(ValidationError, match="spectraldelayfb"):
            resolve_dag(graph, export_dirs, "0.8.0")
