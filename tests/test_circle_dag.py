"""Tests for Circle DAG (Phase 2) project generation."""

import json
from pathlib import Path


from gen_dsp.core.graph import (
    ChainNodeConfig,
    Connection,
    EdgeBuffer,
    GraphConfig,
    ResolvedChainNode,
    allocate_edge_buffers,
    parse_graph,
    resolve_dag,
    validate_dag,
    validate_linear_chain,
)
from gen_dsp.core.manifest import Manifest, ParamInfo
from gen_dsp.core.parser import ExportInfo
from gen_dsp.core.project import ProjectConfig
from gen_dsp.platforms.circle import (
    CirclePlatform,
    _build_dag_buffer_decls,
    _build_dag_buffer_init,
    _build_dag_create,
    _build_dag_destroy,
    _build_dag_includes,
    _build_dag_io_defines,
    _build_dag_midi_dispatch,
    _build_dag_mixer_gain_decls,
    _build_dag_per_node_flags,
    _build_dag_perform,
    _build_dag_set_param,
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
    node_type: str = "gen",
    mixer_inputs: int = 0,
) -> ResolvedChainNode:
    """Create a ResolvedChainNode for testing without real export files."""
    config = ChainNodeConfig(
        id=node_id,
        export=export_name if node_type == "gen" else None,
        node_type=node_type,
        mixer_inputs=mixer_inputs,
        midi_channel=midi_channel if midi_channel is not None else index + 1,
        cc_map=cc_map or {},
    )
    if node_type == "gen":
        export_info = ExportInfo(
            name=f"gen_{export_name}",
            path=Path(f"/fake/{export_name}"),
            num_inputs=num_inputs,
            num_outputs=num_outputs,
            num_params=num_params,
        )
    else:
        export_info = None
    manifest = Manifest(
        gen_name=f"gen_{export_name}" if node_type == "gen" else f"mixer_{node_id}",
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


def _diamond_dag_nodes() -> list[ResolvedChainNode]:
    """Diamond DAG: reverb + delay -> mix."""
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
        _make_resolved_node(
            "mix",
            "mix",
            2,
            2,
            2,
            2,
            params=[
                ParamInfo(0, "gain_0", True, 0.0, 2.0, 1.0),
                ParamInfo(1, "gain_1", True, 0.0, 2.0, 1.0),
            ],
            node_type="mixer",
            mixer_inputs=2,
        ),
    ]


def _diamond_graph() -> GraphConfig:
    """Graph matching _diamond_dag_nodes()."""
    return GraphConfig(
        nodes={
            "reverb": ChainNodeConfig(id="reverb", export="gigaverb", midi_channel=1),
            "delay": ChainNodeConfig(
                id="delay", export="spectraldelayfb", midi_channel=2
            ),
            "mix": ChainNodeConfig(
                id="mix", node_type="mixer", mixer_inputs=2, midi_channel=3
            ),
        },
        connections=[
            Connection("audio_in", "reverb"),
            Connection("audio_in", "delay"),
            Connection("reverb", "mix", dst_input_index=0),
            Connection("delay", "mix", dst_input_index=1),
            Connection("mix", "audio_out"),
        ],
    )


def _diamond_edge_buffers() -> tuple[list[EdgeBuffer], int]:
    """Edge buffers for the diamond DAG."""
    edges = [
        EdgeBuffer(
            buffer_id=-1,
            src_node="audio_in",
            dst_node="reverb",
            dst_input_index=None,
            num_channels=2,
        ),
        EdgeBuffer(
            buffer_id=-1,
            src_node="audio_in",
            dst_node="delay",
            dst_input_index=None,
            num_channels=2,
        ),
        EdgeBuffer(
            buffer_id=0,
            src_node="reverb",
            dst_node="mix",
            dst_input_index=0,
            num_channels=2,
        ),
        EdgeBuffer(
            buffer_id=1,
            src_node="delay",
            dst_node="mix",
            dst_input_index=1,
            num_channels=2,
        ),
        EdgeBuffer(
            buffer_id=2,
            src_node="mix",
            dst_node="audio_out",
            dst_input_index=None,
            num_channels=2,
        ),
    ]
    return edges, 3


# ---------------------------------------------------------------------------
# TestDAGCodeGenerationHelpers
# ---------------------------------------------------------------------------


class TestDAGCodeGenerationHelpers:
    """Test the DAG code generation helper functions."""

    def test_dag_buffer_decls(self):
        """Test buffer storage and pointer array declarations."""
        result = _build_dag_buffer_decls(3, 2)
        assert "DAG_NUM_BUFFERS    3" in result
        assert "DAG_MAX_CHANNELS   2" in result
        assert "m_DagBufStorage_0" in result
        assert "m_DagBufStorage_1" in result
        assert "m_DagBufStorage_2" in result
        assert "m_pDagBuf_0" in result
        assert "m_pDagBuf_2" in result

    def test_dag_buffer_init(self):
        """Test pointer array initialization code."""
        result = _build_dag_buffer_init(2)
        assert "m_pDagBuf_0[ch] = m_DagBufStorage_0[ch]" in result
        assert "m_pDagBuf_1[ch] = m_DagBufStorage_1[ch]" in result

    def test_dag_mixer_gain_decls(self):
        """Test mixer gain member variable declarations."""
        nodes = _diamond_dag_nodes()
        result = _build_dag_mixer_gain_decls(nodes)
        assert "m_mix_gain_0" in result
        assert "m_mix_gain_1" in result
        # Should not include gain vars for gen~ nodes
        assert "m_reverb" not in result

    def test_dag_includes_skip_mixer(self):
        """Test that mixer nodes are excluded from #include lines."""
        nodes = _diamond_dag_nodes()
        result = _build_dag_includes(nodes)
        assert '#include "_ext_circle_0.h"' in result
        assert '#include "_ext_circle_1.h"' in result
        # Mixer (index 2) should NOT have an include
        assert "_ext_circle_2" not in result

    def test_dag_io_defines_skip_mixer(self):
        """Test that mixer nodes are excluded from I/O defines."""
        nodes = _diamond_dag_nodes()
        result = _build_dag_io_defines(nodes)
        assert "NODE_0_NUM_INPUTS" in result
        assert "NODE_1_NUM_INPUTS" in result
        assert "NODE_2" not in result

    def test_dag_create_skip_mixer(self):
        """Test that mixer slots are null, gen~ nodes get wrapper_create."""
        nodes = _diamond_dag_nodes()
        result = _build_dag_create(nodes)
        assert "reverb_circle::wrapper_create" in result
        assert "delay_circle::wrapper_create" in result
        assert "nullptr" in result  # mixer slot
        assert "mixer" in result.lower()

    def test_dag_destroy_skip_mixer(self):
        """Test that only gen~ nodes get wrapper_destroy."""
        nodes = _diamond_dag_nodes()
        result = _build_dag_destroy(nodes)
        assert "reverb_circle::wrapper_destroy" in result
        assert "delay_circle::wrapper_destroy" in result
        assert "mix_circle" not in result

    def test_dag_set_param_gen(self):
        """Test SetParam dispatch for gen~ nodes."""
        nodes = _diamond_dag_nodes()
        result = _build_dag_set_param(nodes)
        assert "nodeIndex == 0" in result
        assert "reverb_circle::wrapper_set_param" in result

    def test_dag_set_param_mixer(self):
        """Test SetParam dispatch for mixer nodes (sets gain members)."""
        nodes = _diamond_dag_nodes()
        result = _build_dag_set_param(nodes)
        assert "nodeIndex == 2" in result
        assert "m_mix_gain_0" in result
        assert "m_mix_gain_1" in result

    def test_dag_perform_fan_out(self):
        """Test that fan-out edges from same source read same buffer."""
        nodes = _diamond_dag_nodes()
        edges, _ = _diamond_edge_buffers()
        graph = _diamond_graph()
        result = _build_dag_perform(nodes, edges, graph, max_channels=3)

        # Both reverb and delay read from hw input (buffer_id=-1)
        assert "m_pHwInput" in result
        # Reverb writes to buf 0
        assert "m_pDagBuf_0" in result
        # Delay writes to buf 1
        assert "m_pDagBuf_1" in result

    def test_dag_perform_mixer_inline(self):
        """Test that mixer generates inline weighted sum code."""
        nodes = _diamond_dag_nodes()
        edges, _ = _diamond_edge_buffers()
        graph = _diamond_graph()
        result = _build_dag_perform(nodes, edges, graph, max_channels=3)

        # Mixer should have weighted sum with gain variables
        assert "m_mix_gain_0" in result
        assert "m_mix_gain_1" in result
        # Mixer reads from buf 0 and buf 1
        assert "m_pDagBuf_0[ch][s]" in result
        assert "m_pDagBuf_1[ch][s]" in result

    def test_dag_midi_dispatch(self):
        """Test MIDI dispatch for both gen~ and mixer nodes."""
        nodes = _diamond_dag_nodes()
        graph = _diamond_graph()
        result = _build_dag_midi_dispatch(nodes, graph)
        # Channel-per-node dispatch
        assert "channel == 1" in result
        assert "channel == 2" in result
        assert "channel == 3" in result

    def test_dag_per_node_flags_skip_mixer(self):
        """Test per-node Makefile flags exclude mixer nodes."""
        nodes = _diamond_dag_nodes()
        result = _build_dag_per_node_flags(nodes)
        assert "_ext_circle_0.o: CPPFLAGS +=" in result
        assert "_ext_circle_1.o: CPPFLAGS +=" in result
        assert "_ext_circle_2" not in result


# ---------------------------------------------------------------------------
# TestDAGProjectGeneration
# ---------------------------------------------------------------------------


class TestDAGProjectGeneration:
    """Test full DAG project generation."""

    def test_dag_project_files_created(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that all expected files are created for a DAG project."""
        dag_nodes, graph, edge_buffers, num_buffers = self._resolve_dag(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "dag_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_dag_project(
            dag_nodes, graph, edge_buffers, num_buffers, output_dir, "mydag"
        )

        # Static files
        assert (output_dir / "gen_ext_common_circle.h").is_file()
        assert (output_dir / "_ext_circle_impl.cpp").is_file()
        assert (output_dir / "_ext_circle_impl.h").is_file()
        assert (output_dir / "genlib_circle.h").is_file()
        assert (output_dir / "genlib_circle.cpp").is_file()

        # Generated files
        assert (output_dir / "gen_ext_circle.cpp").is_file()
        assert (output_dir / "Makefile").is_file()
        assert (output_dir / "config.txt").is_file()
        assert (output_dir / "gen_buffer.h").is_file()

        # Per-node wrappers (gen~ nodes only, not mixer)
        assert (output_dir / "_ext_circle_0.cpp").is_file()
        assert (output_dir / "_ext_circle_0.h").is_file()
        assert (output_dir / "_ext_circle_1.cpp").is_file()
        assert (output_dir / "_ext_circle_1.h").is_file()
        # Mixer (index 2) should NOT have wrapper files
        assert not (output_dir / "_ext_circle_2.cpp").is_file()
        assert not (output_dir / "_ext_circle_2.h").is_file()

    def test_dag_kernel_has_dag_markers(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that DAG kernel has DAG-specific content."""
        dag_nodes, graph, edge_buffers, num_buffers = self._resolve_dag(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "dag_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_dag_project(
            dag_nodes, graph, edge_buffers, num_buffers, output_dir, "mydag"
        )

        kernel = (output_dir / "gen_ext_circle.cpp").read_text(encoding="utf-8")
        assert "DAG_NODE_COUNT" in kernel
        assert "m_pDagBuf_" in kernel
        assert "m_pHwInput" in kernel
        assert "MIDIPacketHandler" in kernel

    def test_dag_makefile_excludes_mixer(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that Makefile only includes gen~ node .o files."""
        dag_nodes, graph, edge_buffers, num_buffers = self._resolve_dag(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "dag_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_dag_project(
            dag_nodes, graph, edge_buffers, num_buffers, output_dir, "mydag"
        )

        makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
        assert "_ext_circle_0.o" in makefile
        assert "_ext_circle_1.o" in makefile
        # Mixer index should not appear in OBJS
        assert "_ext_circle_2.o" not in makefile

    def test_dag_kernel_has_mixer_gains(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that kernel includes mixer gain member variables."""
        dag_nodes, graph, edge_buffers, num_buffers = self._resolve_dag(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "dag_project"
        output_dir.mkdir()

        platform = CirclePlatform()
        platform.generate_dag_project(
            dag_nodes, graph, edge_buffers, num_buffers, output_dir, "mydag"
        )

        kernel = (output_dir / "gen_ext_circle.cpp").read_text(encoding="utf-8")
        assert "m_mix_gain_0" in kernel
        assert "m_mix_gain_1" in kernel

    def test_dag_usb_board_uses_usb_template(
        self, gigaverb_export, spectraldelayfb_export, tmp_path
    ):
        """Test that USB board uses the USB DAG template."""
        dag_nodes, graph, edge_buffers, num_buffers = self._resolve_dag(
            gigaverb_export, spectraldelayfb_export, tmp_path
        )

        output_dir = tmp_path / "dag_project"
        output_dir.mkdir()

        config = ProjectConfig(name="mydag", platform="circle", board="pi4-usb")
        platform = CirclePlatform()
        platform.generate_dag_project(
            dag_nodes, graph, edge_buffers, num_buffers, output_dir, "mydag", config
        )

        kernel = (output_dir / "gen_ext_circle.cpp").read_text(encoding="utf-8")
        assert "CUSBSoundBaseDevice" in kernel

    # --- Helpers ---

    def _resolve_dag(self, gigaverb_export, spectraldelayfb_export, tmp_path):
        """Resolve a diamond DAG from test fixtures."""
        data = {
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
        graph_path = tmp_path / "graph.json"
        graph_path.write_text(json.dumps(data), encoding="utf-8")
        graph = parse_graph(graph_path)

        export_dirs = {
            "gigaverb": gigaverb_export,
            "spectraldelayfb": spectraldelayfb_export,
        }
        dag_nodes = resolve_dag(graph, export_dirs, "0.8.0")

        resolved_map = {n.config.id: n for n in dag_nodes}
        topo_order = [n.config.id for n in dag_nodes]
        edge_buffers, num_buffers = allocate_edge_buffers(
            graph, resolved_map, topo_order
        )

        return dag_nodes, graph, edge_buffers, num_buffers


# ---------------------------------------------------------------------------
# TestLinearGraphStillUsesPhase1
# ---------------------------------------------------------------------------


class TestLinearGraphStillUsesPhase1:
    """Verify backward compatibility: linear graphs use Phase 1 chain path."""

    def test_linear_graph_passes_linear_validation(self, tmp_path):
        """A linear graph passes validate_linear_chain."""
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

        assert validate_linear_chain(graph) == []

    def test_diamond_graph_fails_linear_validation(self, tmp_path):
        """A diamond DAG fails validate_linear_chain (fan-out + fan-in)."""
        data = {
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
        graph_path = tmp_path / "graph.json"
        graph_path.write_text(json.dumps(data), encoding="utf-8")
        graph = parse_graph(graph_path)

        errors = validate_linear_chain(graph)
        assert len(errors) > 0

    def test_diamond_graph_passes_dag_validation(self, tmp_path):
        """A diamond DAG passes validate_dag."""
        data = {
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
        graph_path = tmp_path / "graph.json"
        graph_path.write_text(json.dumps(data), encoding="utf-8")
        graph = parse_graph(graph_path)

        assert validate_dag(graph) == []
