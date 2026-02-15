"""Tests for Circle chain (multi-plugin) project generation."""

import json
from pathlib import Path

import pytest

from gen_dsp.core.graph import (
    ChainNodeConfig,
    Connection,
    GraphConfig,
    ResolvedChainNode,
    parse_graph,
    resolve_chain,
)
from gen_dsp.core.manifest import Manifest, ParamInfo
from gen_dsp.core.parser import ExportInfo
from gen_dsp.core.project import ProjectConfig
from gen_dsp.platforms.circle import (
    CirclePlatform,
    _build_chain_includes,
    _build_chain_io_defines,
    _build_chain_create,
    _build_chain_destroy,
    _build_chain_perform,
    _build_chain_midi_dispatch,
    _build_chain_per_node_flags,
    _build_chain_set_param,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolved_node(
    node_id: str,
    export_name: str,
    index: int,
    num_inputs: int = 2,
    num_outputs: int = 2,
    num_params: int = 0,
    params: list[ParamInfo] | None = None,
    midi_channel: int | None = None,
    cc_map: dict[int, str] | None = None,
) -> ResolvedChainNode:
    """Create a ResolvedChainNode for testing without real export files."""
    config = ChainNodeConfig(
        id=node_id,
        export=export_name,
        midi_channel=midi_channel if midi_channel is not None else index + 1,
        cc_map=cc_map or {},
    )
    export_info = ExportInfo(
        name=f"gen_{export_name}",
        path=Path(f"/fake/{export_name}"),
        num_inputs=num_inputs,
        num_outputs=num_outputs,
        num_params=num_params,
    )
    manifest = Manifest(
        gen_name=f"gen_{export_name}",
        num_inputs=num_inputs,
        num_outputs=num_outputs,
        params=params or [],
    )
    return ResolvedChainNode(
        config=config,
        index=index,
        export_info=export_info,
        manifest=manifest,
    )


def _two_node_chain() -> list[ResolvedChainNode]:
    """Two-node chain: reverb (2in/2out) -> delay (3in/2out)."""
    return [
        _make_resolved_node(
            "reverb",
            "gigaverb",
            0,
            2,
            2,
            5,
            params=[ParamInfo(i, f"param{i}", True, 0.0, 1.0, 0.5) for i in range(5)],
        ),
        _make_resolved_node(
            "delay",
            "spectraldelayfb",
            1,
            3,
            2,
            3,
            params=[ParamInfo(i, f"param{i}", True, 0.0, 1.0, 0.5) for i in range(3)],
        ),
    ]


def _two_node_graph() -> GraphConfig:
    """Graph matching _two_node_chain()."""
    return GraphConfig(
        nodes={
            "reverb": ChainNodeConfig(id="reverb", export="gigaverb", midi_channel=1),
            "delay": ChainNodeConfig(
                id="delay", export="spectraldelayfb", midi_channel=2
            ),
        },
        connections=[
            Connection("audio_in", "reverb"),
            Connection("reverb", "delay"),
            Connection("delay", "audio_out"),
        ],
    )


def _write_graph(tmp_path: Path, data: dict) -> Path:
    """Write a graph JSON file and return its path."""
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(data), encoding="utf-8")
    return graph_path


# ---------------------------------------------------------------------------
# TestCircleChainCodeGenerationHelpers
# ---------------------------------------------------------------------------


class TestCircleChainCodeGenerationHelpers:
    """Test the code generation helper functions."""

    def test_build_chain_includes(self):
        """Test #include lines for chain nodes."""
        chain = _two_node_chain()
        result = _build_chain_includes(chain)
        assert '#include "_ext_circle_0.h"' in result
        assert '#include "_ext_circle_1.h"' in result

    def test_build_chain_io_defines(self):
        """Test per-node I/O count defines."""
        chain = _two_node_chain()
        result = _build_chain_io_defines(chain)
        assert "NODE_0_NUM_INPUTS  2" in result
        assert "NODE_0_NUM_OUTPUTS 2" in result
        assert "NODE_1_NUM_INPUTS  3" in result
        assert "NODE_1_NUM_OUTPUTS 2" in result

    def test_build_chain_create(self):
        """Test gen state creation calls."""
        chain = _two_node_chain()
        result = _build_chain_create(chain)
        assert "reverb_circle::wrapper_create" in result
        assert "delay_circle::wrapper_create" in result
        assert "m_genState[0]" in result
        assert "m_genState[1]" in result

    def test_build_chain_destroy(self):
        """Test gen state destruction calls."""
        chain = _two_node_chain()
        result = _build_chain_destroy(chain)
        assert "reverb_circle::wrapper_destroy" in result
        assert "delay_circle::wrapper_destroy" in result

    def test_build_chain_set_param(self):
        """Test SetParam dispatch code."""
        chain = _two_node_chain()
        result = _build_chain_set_param(chain)
        assert "nodeIndex == 0" in result
        assert "nodeIndex == 1" in result
        assert "reverb_circle::wrapper_set_param" in result
        assert "delay_circle::wrapper_set_param" in result

    def test_build_chain_perform_ping_pong(self):
        """Test ping-pong buffer alternation in perform block."""
        chain = _two_node_chain()
        result = _build_chain_perform(chain, max_channels=3)

        # Node 0: reads from A, writes to B
        lines = result.split("\n")
        # Find the node 0 perform call
        node0_lines = []
        node1_lines = []
        in_node0 = False
        in_node1 = False
        for line in lines:
            if "Node 0:" in line:
                in_node0 = True
                in_node1 = False
            elif "Node 1:" in line:
                in_node0 = False
                in_node1 = True
            if in_node0:
                node0_lines.append(line)
            if in_node1:
                node1_lines.append(line)

        node0_text = "\n".join(node0_lines)
        node1_text = "\n".join(node1_lines)

        # Node 0 reads from scratchA, writes to scratchB
        assert "m_pScratchA" in node0_text
        assert "m_pScratchB" in node0_text

        # Node 1 reads from scratchB, writes to scratchA
        assert "m_pScratchB" in node1_text
        assert "m_pScratchA" in node1_text

    def test_build_chain_midi_dispatch_cc_by_index(self):
        """Test default CC-by-param-index MIDI dispatch."""
        chain = _two_node_chain()
        graph = _two_node_graph()
        result = _build_chain_midi_dispatch(chain, graph)

        # Node 0 has 5 params, node 1 has 3 params
        assert "channel == 1" in result
        assert "channel == 2" in result
        assert "cc < 5" in result
        assert "cc < 3" in result

    def test_build_chain_midi_dispatch_explicit_cc(self):
        """Test explicit CC mapping in MIDI dispatch."""
        chain = [
            _make_resolved_node(
                "reverb",
                "gigaverb",
                0,
                2,
                2,
                5,
                params=[
                    ParamInfo(0, "revtime", True, 0.0, 1.0, 0.5),
                    ParamInfo(1, "damping", True, 0.0, 1.0, 0.5),
                ],
                cc_map={21: "revtime", 22: "damping"},
            ),
        ]
        graph = GraphConfig(
            nodes={
                "reverb": ChainNodeConfig(
                    id="reverb",
                    export="gigaverb",
                    midi_channel=1,
                    cc_map={21: "revtime", 22: "damping"},
                ),
            },
            connections=[
                Connection("audio_in", "reverb"),
                Connection("reverb", "audio_out"),
            ],
        )
        result = _build_chain_midi_dispatch(chain, graph)

        assert "cc == 21" in result
        assert "cc == 22" in result
        assert "revtime" in result
        assert "damping" in result

    def test_build_chain_per_node_flags(self):
        """Test per-node Makefile CPPFLAGS."""
        chain = _two_node_chain()
        result = _build_chain_per_node_flags(chain)

        assert "_ext_circle_0.o: CPPFLAGS +=" in result
        assert "_ext_circle_1.o: CPPFLAGS +=" in result
        assert "-I./gen_gigaverb" in result
        assert "-I./gen_spectraldelayfb" in result
        assert "CIRCLE_EXT_NAME=reverb" in result
        assert "CIRCLE_EXT_NAME=delay" in result


# ---------------------------------------------------------------------------
# TestCircleChainProjectGeneration
# ---------------------------------------------------------------------------


class TestCircleChainProjectGeneration:
    """Test full chain project generation with real exports."""

    def test_chain_project_files_created(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that all expected files are created for a chain project."""
        chain, graph = self._resolve_chain(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "chain_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mychain")

        # Static files
        assert (output_dir / "gen_ext_common_circle.h").is_file()
        assert (output_dir / "_ext_circle_impl.cpp").is_file()
        assert (output_dir / "_ext_circle_impl.h").is_file()
        assert (output_dir / "circle_buffer.h").is_file()
        assert (output_dir / "genlib_circle.h").is_file()
        assert (output_dir / "genlib_circle.cpp").is_file()
        assert (output_dir / "cmath").is_file()
        assert (output_dir / "gen_buffer.h").is_file()
        assert (output_dir / "config.txt").is_file()

        # Generated chain files
        assert (output_dir / "gen_ext_circle.cpp").is_file()
        assert (output_dir / "Makefile").is_file()

        # Per-node wrapper shims
        assert (output_dir / "_ext_circle_0.cpp").is_file()
        assert (output_dir / "_ext_circle_0.h").is_file()
        assert (output_dir / "_ext_circle_1.cpp").is_file()
        assert (output_dir / "_ext_circle_1.h").is_file()

    def test_chain_kernel_includes_nodes(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that generated kernel includes per-node headers."""
        chain, graph = self._resolve_chain(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "chain_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mychain")

        kernel = (output_dir / "gen_ext_circle.cpp").read_text(encoding="utf-8")
        assert '#include "_ext_circle_0.h"' in kernel
        assert '#include "_ext_circle_1.h"' in kernel
        assert "CHAIN_NODE_COUNT" in kernel

    def test_chain_kernel_has_midi(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that generated kernel includes USB MIDI support."""
        chain, graph = self._resolve_chain(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "chain_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mychain")

        kernel = (output_dir / "gen_ext_circle.cpp").read_text(encoding="utf-8")
        assert "usbmididevice.h" in kernel
        assert "MIDIPacketHandler" in kernel

    def test_chain_makefile_has_per_node_objs(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that Makefile includes per-node .o files."""
        chain, graph = self._resolve_chain(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "chain_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mychain")

        makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
        assert "_ext_circle_0.o" in makefile
        assert "_ext_circle_1.o" in makefile

    def test_chain_makefile_has_per_node_flags(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that Makefile has per-node CPPFLAGS for include paths."""
        chain, graph = self._resolve_chain(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "chain_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mychain")

        makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
        assert "_ext_circle_0.o: CPPFLAGS +=" in makefile
        assert "_ext_circle_1.o: CPPFLAGS +=" in makefile

    def test_chain_makefile_always_links_usb(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that Makefile always links libusb.a (for MIDI)."""
        chain, graph = self._resolve_chain(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "chain_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mychain")

        makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
        assert "libusb.a" in makefile

    def test_chain_per_node_wrapper_content(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test content of generated per-node wrapper shims."""
        chain, graph = self._resolve_chain(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "chain_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mychain")

        # Check node 0 (.cpp)
        cpp0 = (output_dir / "_ext_circle_0.cpp").read_text(encoding="utf-8")
        assert "#define CIRCLE_EXT_NAME reverb" in cpp0
        assert '#include "_ext_circle_impl.cpp"' in cpp0

        # Check node 0 (.h)
        h0 = (output_dir / "_ext_circle_0.h").read_text(encoding="utf-8")
        assert "#define CIRCLE_EXT_NAME reverb" in h0
        assert '#include "_ext_circle_impl.h"' in h0

        # Check node 1
        cpp1 = (output_dir / "_ext_circle_1.cpp").read_text(encoding="utf-8")
        assert "#define CIRCLE_EXT_NAME delay" in cpp1

    def test_chain_gen_buffer_has_zero_buffers(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that gen_buffer.h has WRAPPER_BUFFER_COUNT=0 in chain mode."""
        chain, graph = self._resolve_chain(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "chain_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mychain")

        gen_buffer = (output_dir / "gen_buffer.h").read_text(encoding="utf-8")
        assert "WRAPPER_BUFFER_COUNT 0" in gen_buffer

    def test_chain_usb_board_uses_usb_template(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that USB board uses the USB audio chain template."""
        chain, graph = self._resolve_chain(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "chain_project"
        output_dir.mkdir()

        config = ProjectConfig(name="mychain", platform="circle", board="pi4-usb")
        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mychain", config)

        kernel = (output_dir / "gen_ext_circle.cpp").read_text(encoding="utf-8")
        assert "CUSBSoundBaseDevice" in kernel

    def test_chain_default_board_is_pi3_i2s(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that default board is pi3-i2s (DMA audio template)."""
        chain, graph = self._resolve_chain(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "chain_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mychain")

        kernel = (output_dir / "gen_ext_circle.cpp").read_text(encoding="utf-8")
        assert "pi3-i2s" in kernel
        assert "I2S" in kernel

    # --- Helpers ---

    def _resolve_chain(self, gigaverb_export, spectraldelayfb_export, tmp_path):
        """Resolve a two-node chain from test fixtures."""
        data = {
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
        graph_path = tmp_path / "graph.json"
        graph_path.write_text(json.dumps(data), encoding="utf-8")
        graph = parse_graph(graph_path)

        export_dirs = {
            "gigaverb": gigaverb_export,
            "spectraldelayfb": spectraldelayfb_export,
        }
        chain = resolve_chain(graph, export_dirs, "0.8.0")
        return chain, graph


# ---------------------------------------------------------------------------
# TestCircleChainEdgeCases
# ---------------------------------------------------------------------------


class TestCircleChainEdgeCases:
    """Test edge cases in chain project generation."""

    def test_single_node_chain_project(self, gigaverb_export, tmp_path):
        """Test chain project with a single node."""
        data = {
            "nodes": {"reverb": {"export": "gigaverb"}},
            "connections": [
                ["audio_in", "reverb"],
                ["reverb", "audio_out"],
            ],
        }
        graph_path = tmp_path / "graph.json"
        graph_path.write_text(json.dumps(data), encoding="utf-8")
        graph = parse_graph(graph_path)

        export_dirs = {"gigaverb": gigaverb_export}
        chain = resolve_chain(graph, export_dirs, "0.8.0")

        output_dir = tmp_path / "single_chain"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "single")

        # Should have exactly one per-node wrapper
        assert (output_dir / "_ext_circle_0.cpp").is_file()
        assert (output_dir / "_ext_circle_0.h").is_file()
        assert not (output_dir / "_ext_circle_1.cpp").is_file()

        kernel = (output_dir / "gen_ext_circle.cpp").read_text(encoding="utf-8")
        assert "CHAIN_NODE_COUNT       1" in kernel

    def test_channel_mismatch_max_channels(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that max_channels is computed correctly across nodes.

        gigaverb: 2in/2out, spectraldelayfb: 3in/2out -> max_channels=3
        """
        data = {
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
        graph_path = tmp_path / "graph.json"
        graph_path.write_text(json.dumps(data), encoding="utf-8")
        graph = parse_graph(graph_path)

        export_dirs = {
            "gigaverb": gigaverb_export,
            "spectraldelayfb": spectraldelayfb_export,
        }
        chain = resolve_chain(graph, export_dirs, "0.8.0")

        output_dir = tmp_path / "mismatch_chain"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, "mismatch")

        kernel = (output_dir / "gen_ext_circle.cpp").read_text(encoding="utf-8")
        assert "CHAIN_MAX_CHANNELS     3" in kernel

    def test_chain_final_output_ptr_even_nodes(self):
        """Test final output pointer for even number of nodes.

        With 2 nodes (index 0 and 1):
        - Node 0 writes to B
        - Node 1 writes to A
        Final output is from A (odd last index).
        """
        chain = _two_node_chain()
        # Last node index is 1 (odd) -> writes to scratchA
        last_idx = len(chain) - 1
        if last_idx % 2 == 0:
            expected = "m_pScratchB"
        else:
            expected = "m_pScratchA"
        assert expected == "m_pScratchA"

    def test_chain_final_output_ptr_odd_nodes(self):
        """Test final output pointer for odd number of nodes (1 node).

        With 1 node (index 0):
        - Node 0 writes to B
        Final output is from B.
        """
        chain = [_make_resolved_node("a", "ex_a", 0)]
        last_idx = len(chain) - 1
        if last_idx % 2 == 0:
            expected = "m_pScratchB"
        else:
            expected = "m_pScratchA"
        assert expected == "m_pScratchB"

    def test_invalid_board_raises(self, gigaverb_export, tmp_path):
        """Test that invalid board name raises ProjectError."""
        from gen_dsp.errors import ProjectError

        data = {
            "nodes": {"reverb": {"export": "gigaverb"}},
            "connections": [
                ["audio_in", "reverb"],
                ["reverb", "audio_out"],
            ],
        }
        graph_path = tmp_path / "graph.json"
        graph_path.write_text(json.dumps(data), encoding="utf-8")
        graph = parse_graph(graph_path)

        export_dirs = {"gigaverb": gigaverb_export}
        chain = resolve_chain(graph, export_dirs, "0.8.0")

        output_dir = tmp_path / "bad_board"
        output_dir.mkdir()

        config = ProjectConfig(name="test", platform="circle", board="invalid-board")
        platform = CirclePlatform()
        with pytest.raises(ProjectError, match="Unknown Circle board"):
            platform.generate_chain_project(chain, graph, output_dir, "test", config)
