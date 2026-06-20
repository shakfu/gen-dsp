"""C++ code-generation helpers for Circle multi-plugin DAGs."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gen_dsp.core.graph import EdgeBuffer, GraphConfig, ResolvedChainNode


# ---------------------------------------------------------------------------
# DAG code generation helpers (Phase 2)
# ---------------------------------------------------------------------------


def _build_dag_buffer_decls(num_buffers: int, max_channels: int) -> str:
    """Build DAG buffer storage and pointer array declarations."""
    lines = []
    lines.append(f"#define DAG_NUM_BUFFERS    {num_buffers}")
    lines.append(f"#define DAG_MAX_CHANNELS   {max_channels}")
    lines.append("")
    for i in range(num_buffers):
        lines.append(
            f"    float m_DagBufStorage_{i}[DAG_MAX_CHANNELS][CIRCLE_CHUNK_SIZE];"
        )
    lines.append("")
    for i in range(num_buffers):
        lines.append(f"    float* m_pDagBuf_{i}[DAG_MAX_CHANNELS];")
    return "\n".join(lines)


def _build_dag_buffer_init(num_buffers: int) -> str:
    """Build pointer array initialization for constructor."""
    lines = []
    for i in range(num_buffers):
        lines.append("        for (int ch = 0; ch < DAG_MAX_CHANNELS; ch++) {")
        lines.append(f"            m_pDagBuf_{i}[ch] = m_DagBufStorage_{i}[ch];")
        lines.append("        }")
    return "\n".join(lines)


def _build_dag_mixer_gain_decls(dag_nodes: "list[ResolvedChainNode]") -> str:
    """Build mixer gain member variable declarations."""
    lines = []
    for node in dag_nodes:
        if node.config.node_type == "mixer":
            for p in node.manifest.params:
                lines.append(f"    float m_{node.config.id}_{p.name} = 1.0f;")
    return "\n".join(lines)


def _build_dag_includes(dag_nodes: "list[ResolvedChainNode]") -> str:
    """Build #include lines for gen~ node wrapper headers (skip mixers)."""
    lines = []
    for node in dag_nodes:
        if node.config.node_type == "gen":
            lines.append(f'#include "_ext_circle_{node.index}.h"')
    return "\n".join(lines)


def _build_dag_io_defines(dag_nodes: "list[ResolvedChainNode]") -> str:
    """Build per-node I/O count #defines (skip mixers)."""
    lines = []
    for node in dag_nodes:
        if node.config.node_type == "gen":
            prefix = f"NODE_{node.index}"
            lines.append(f"#define {prefix}_NUM_INPUTS  {node.manifest.num_inputs}")
            lines.append(f"#define {prefix}_NUM_OUTPUTS {node.manifest.num_outputs}")
    return "\n".join(lines)


def _build_dag_create(dag_nodes: "list[ResolvedChainNode]") -> str:
    """Build gen state creation calls (gen~ nodes only; mixer slots are null)."""
    lines = []
    for node in dag_nodes:
        if node.config.node_type == "gen":
            ns = f"{node.config.id}_circle"
            lines.append(
                f"        m_genState[{node.index}] = "
                f"{ns}::wrapper_create("
                f"(float)CIRCLE_SAMPLE_RATE, (long)CIRCLE_CHUNK_SIZE);"
            )
            lines.append(f"        if (!m_genState[{node.index}]) return FALSE;")
        else:
            lines.append(
                f"        m_genState[{node.index}] = nullptr;  "
                f"// {node.config.id} (mixer)"
            )
    return "\n".join(lines)


def _build_dag_destroy(dag_nodes: "list[ResolvedChainNode]") -> str:
    """Build gen state destruction calls (gen~ nodes only)."""
    lines = []
    for node in dag_nodes:
        if node.config.node_type == "gen":
            ns = f"{node.config.id}_circle"
            lines.append(f"        if (m_genState[{node.index}]) {{")
            lines.append(
                f"            {ns}::wrapper_destroy(m_genState[{node.index}]);"
            )
            lines.append(f"            m_genState[{node.index}] = nullptr;")
            lines.append("        }")
    return "\n".join(lines)


def _build_dag_set_param(dag_nodes: "list[ResolvedChainNode]") -> str:
    """Build SetParam dispatch for gen~ and mixer nodes."""
    lines = []
    for node in dag_nodes:
        lines.append(f"        if (nodeIndex == {node.index}) {{")
        if node.config.node_type == "gen":
            ns = f"{node.config.id}_circle"
            lines.append(
                f"            {ns}::wrapper_set_param("
                f"m_genState[{node.index}], paramIndex, value);"
            )
        else:
            # Mixer: dispatch by paramIndex to gain members
            for p in node.manifest.params:
                lines.append(f"            if (paramIndex == {p.index}) {{")
                lines.append(f"                m_{node.config.id}_{p.name} = value;")
                lines.append("            }")
        lines.append("        }")
    return "\n".join(lines)


def _build_dag_perform(
    dag_nodes: "list[ResolvedChainNode]",
    edge_buffers: "list[EdgeBuffer]",
    graph: "GraphConfig",
    max_channels: int,
) -> str:
    """Build the toposort-ordered perform block for GetChunk().

    gen~ nodes call wrapper_perform with correct edge buffers.
    Mixer nodes emit inline weighted-sum loops.
    """
    lines = []

    for node in dag_nodes:
        nid = node.config.id
        n_in = node.manifest.num_inputs
        n_out = node.manifest.num_outputs

        # Find incoming edges for this node
        incoming = [e for e in edge_buffers if e.dst_node == nid]
        # Find outgoing edges for this node
        outgoing = [e for e in edge_buffers if e.src_node == nid]

        if node.config.node_type == "gen":
            ns = f"{nid}_circle"

            # Determine input buffer
            if incoming and incoming[0].buffer_id == -1:
                # Reads from hardware input (audio_in)
                in_buf = "m_pHwInput"
                in_note = "hw input"
            elif incoming:
                in_buf = f"m_pDagBuf_{incoming[0].buffer_id}"
                in_note = f"buf {incoming[0].buffer_id}"
            else:
                in_buf = "nullptr"
                in_note = "none"

            # Determine output buffer
            if outgoing:
                out_buf = f"m_pDagBuf_{outgoing[0].buffer_id}"
                out_note = f"buf {outgoing[0].buffer_id}"
            else:
                out_buf = "nullptr"
                out_note = "none"

            lines.append(
                f"        // Node {node.index}: {nid} "
                f"({n_in}in/{n_out}out, "
                f"in={in_note}, out={out_note})"
            )

            # Zero-pad missing input channels
            if incoming and incoming[0].buffer_id != -1:
                src_ch = incoming[0].num_channels
                if src_ch < n_in:
                    lines.append(
                        f"        // Zero-pad: source has {src_ch} ch, "
                        f"node expects {n_in}"
                    )
                    for ch in range(src_ch, n_in):
                        lines.append(
                            f"        for (unsigned z = 0; z < nFrames; z++) "
                            f"{in_buf}[{ch}][z] = 0.0f;"
                        )

            lines.append(f"        {ns}::wrapper_perform(")
            lines.append(f"            m_genState[{node.index}],")
            if n_in > 0:
                lines.append(f"            {in_buf}, {n_in},")
            else:
                lines.append("            nullptr, 0,")
            lines.append(f"            {out_buf}, {n_out},")
            lines.append("            (long)nFrames);")
            lines.append("")

        elif node.config.node_type == "mixer":
            # Inline weighted sum
            lines.append(
                f"        // Node {node.index}: {nid} (mixer, {len(incoming)} inputs)"
            )

            # Determine output buffer
            if outgoing:
                out_buf = f"m_pDagBuf_{outgoing[0].buffer_id}"
            else:
                out_buf = "nullptr"

            lines.append(f"        for (int ch = 0; ch < {n_out}; ch++) {{")
            lines.append("            for (unsigned s = 0; s < nFrames; s++) {")

            # Build weighted sum expression
            terms = []
            for edge in incoming:
                idx = edge.dst_input_index if edge.dst_input_index is not None else 0
                gain_var = f"m_{nid}_gain_{idx}"
                if edge.buffer_id == -1:
                    src_buf = "m_pHwInput"
                else:
                    src_buf = f"m_pDagBuf_{edge.buffer_id}"
                terms.append(f"{src_buf}[ch][s] * {gain_var}")

            if terms:
                sum_expr = " + ".join(terms)
                lines.append(f"                {out_buf}[ch][s] = {sum_expr};")
            else:
                lines.append(f"                {out_buf}[ch][s] = 0.0f;")

            lines.append("            }")
            lines.append("        }")
            lines.append("")

    return "\n".join(lines)


def _build_dag_midi_dispatch(
    dag_nodes: "list[ResolvedChainNode]",
    graph: "GraphConfig",
) -> str:
    """Build MIDI CC dispatch for DAG nodes (gen~ and mixer)."""
    lines = []
    for node in dag_nodes:
        midi_ch = node.config.midi_channel
        if midi_ch is None:
            midi_ch = node.index + 1
        n_params = node.manifest.num_params

        lines.append(f"    // Node {node.index}: {node.config.id} (MIDI ch {midi_ch})")
        lines.append(f"    if (channel == {midi_ch}) {{")

        if node.config.cc_map:
            # Explicit CC mapping
            for cc_num, param_name in sorted(node.config.cc_map.items()):
                param_idx = None
                for p in node.manifest.params:
                    if p.name == param_name:
                        param_idx = p.index
                        break
                if param_idx is not None:
                    if node.config.node_type == "gen":
                        ns = f"{node.config.id}_circle"
                        lines.append(f"        if (cc == {cc_num}) {{")
                        lines.append(
                            f"            float min = {ns}::wrapper_param_min("
                            f"s_pSoundDevice->m_genState[{node.index}], "
                            f"{param_idx});"
                        )
                        lines.append(
                            f"            float max = {ns}::wrapper_param_max("
                            f"s_pSoundDevice->m_genState[{node.index}], "
                            f"{param_idx});"
                        )
                        lines.append(
                            f"            s_pSoundDevice->SetParam("
                            f"{node.index}, {param_idx}, "
                            f"min + normalized * (max - min));"
                        )
                        lines.append("        }")
                    else:
                        # Mixer: scale to [min, max]
                        p_obj = node.manifest.params[param_idx]
                        lines.append(f"        if (cc == {cc_num}) {{")
                        lines.append(
                            f"            s_pSoundDevice->SetParam("
                            f"{node.index}, {param_idx}, "
                            f"{p_obj.min}f + normalized * "
                            f"{p_obj.max - p_obj.min}f);"
                        )
                        lines.append("        }")
        else:
            # CC-by-param-index
            if n_params > 0:
                if node.config.node_type == "gen":
                    lines.append(f"        if (cc < {n_params}) {{")
                    lines.append(
                        f"            s_pSoundDevice->SetParam("
                        f"{node.index}, (int)cc, normalized);"
                    )
                    lines.append("        }")
                else:
                    # Mixer: scale normalized to [0, 2]
                    lines.append(f"        if (cc < {n_params}) {{")
                    lines.append(
                        f"            s_pSoundDevice->SetParam("
                        f"{node.index}, (int)cc, normalized * 2.0f);"
                    )
                    lines.append("        }")

        lines.append("    }")
    return "\n".join(lines)


def _build_dag_per_node_flags(dag_nodes: "list[ResolvedChainNode]") -> str:
    """Build per-node CPPFLAGS with include paths (gen~ nodes only)."""
    lines = []
    for node in dag_nodes:
        if node.config.node_type != "gen":
            continue
        assert node.export_info is not None
        idx = node.index
        gen_name = node.export_info.name
        node_id = node.config.id
        export_dir = f"gen_{node.config.export}"

        lines.append(
            f"_ext_circle_{idx}.o: CPPFLAGS += "
            f"-I./{export_dir} -I./{export_dir}/gen_dsp "
            f"-DCIRCLE_EXT_NAME={node_id} "
            f"-DGEN_EXPORTED_NAME={gen_name} "
            f'-DGEN_EXPORTED_HEADER=\\"{gen_name}.h\\" '
            f'-DGEN_EXPORTED_CPP=\\"{gen_name}.cpp\\"'
        )
    return "\n".join(lines)
