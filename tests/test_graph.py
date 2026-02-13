"""Tests for the graph data model (multi-plugin chain configurations)."""

import json
from pathlib import Path

import pytest

from gen_dsp.core.graph import (
    ChainNodeConfig,
    GraphConfig,
    parse_graph,
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
                ("audio_in", "a"),
                ("a", "b"),
                ("b", "audio_out"),
            ],
        )
        assert validate_linear_chain(graph) == []

    def test_missing_audio_in(self):
        """Reject graph without audio_in source."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[("a", "audio_out")],
        )
        errors = validate_linear_chain(graph)
        assert any("audio_in" in e for e in errors)

    def test_missing_audio_out(self):
        """Reject graph without audio_out target."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[("audio_in", "a")],
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
                ("audio_in", "a"),
                ("a", "b"),
                ("a", "audio_out"),
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
                ("audio_in", "a"),
                ("audio_in", "b"),
                ("a", "audio_out"),
            ],
        )
        errors = validate_linear_chain(graph)
        assert any("Fan-in" in e or "Fan-out" in e for e in errors)

    def test_unknown_node_reference(self):
        """Reject connection referencing unknown node."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[
                ("audio_in", "a"),
                ("a", "unknown_node"),
                ("unknown_node", "audio_out"),
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
                ("audio_in", "a"),
                ("a", "audio_out"),
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
                ("audio_in", "a"),
                ("a", "audio_out"),
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
                ("audio_in", "a"),
                ("a", "audio_out"),
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
                ("audio_in", "a"),
                ("a", "audio_out"),
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
                ("audio_in", "audio_out"),
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
                ("audio_in", "reverb"),
                ("reverb", "delay"),
                ("delay", "audio_out"),
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
                ("audio_in", "reverb"),
                ("reverb", "audio_out"),
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
                ("audio_in", "a"),
                ("a", "b"),
                ("b", "c"),
                ("c", "audio_out"),
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
                ("audio_in", "a"),
                # Missing: ("a", "b") and ("b", "audio_out")
            ],
        )
        with pytest.raises(ValidationError, match="audio_out"):
            extract_chain_order(graph)

    def test_no_audio_in_raises(self):
        """Raise if there is no audio_in connection."""
        graph = GraphConfig(
            nodes={"a": ChainNodeConfig(id="a", export="ex_a")},
            connections=[("a", "audio_out")],
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
                ("audio_in", "a"),
                ("a", "b"),
                ("b", "a"),  # cycle
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
                ("audio_in", "reverb"),
                ("reverb", "audio_out"),
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
                ("audio_in", "reverb"),
                ("reverb", "delay"),
                ("delay", "audio_out"),
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
                ("audio_in", "reverb"),
                ("reverb", "audio_out"),
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
                ("audio_in", "reverb"),
                ("reverb", "audio_out"),
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
                ("audio_in", "bad"),
                ("bad", "audio_out"),
            ],
        )
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        export_dirs = {"empty": empty_dir}
        with pytest.raises(ValidationError, match="failed to parse"):
            resolve_chain(graph, export_dirs, "0.8.0")
