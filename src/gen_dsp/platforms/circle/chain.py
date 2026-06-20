"""C++ code-generation helpers for Circle multi-plugin chains."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gen_dsp.core.graph import GraphConfig, ResolvedChainNode


# ---------------------------------------------------------------------------
# Chain code generation helpers
# ---------------------------------------------------------------------------


def _build_chain_includes(chain: "list[ResolvedChainNode]") -> str:
    """Build #include lines for per-node wrapper headers."""
    lines = []
    for node in chain:
        lines.append(f'#include "_ext_circle_{node.index}.h"')
    return "\n".join(lines)


def _build_chain_io_defines(chain: "list[ResolvedChainNode]") -> str:
    """Build per-node I/O count #defines."""
    lines = []
    for node in chain:
        prefix = f"NODE_{node.index}"
        lines.append(f"#define {prefix}_NUM_INPUTS  {node.manifest.num_inputs}")
        lines.append(f"#define {prefix}_NUM_OUTPUTS {node.manifest.num_outputs}")
    return "\n".join(lines)


def _build_chain_create(chain: "list[ResolvedChainNode]") -> str:
    """Build gen state creation calls for Initialize()."""
    lines = []
    for node in chain:
        ns = f"{node.config.id}_circle"
        lines.append(
            f"        m_genState[{node.index}] = "
            f"{ns}::wrapper_create((float)CIRCLE_SAMPLE_RATE, (long)CIRCLE_CHUNK_SIZE);"
        )
        lines.append(f"        if (!m_genState[{node.index}]) return FALSE;")
    return "\n".join(lines)


def _build_chain_destroy(chain: "list[ResolvedChainNode]") -> str:
    """Build gen state destruction calls for destructor."""
    lines = []
    for node in chain:
        ns = f"{node.config.id}_circle"
        lines.append(f"        if (m_genState[{node.index}]) {{")
        lines.append(f"            {ns}::wrapper_destroy(m_genState[{node.index}]);")
        lines.append(f"            m_genState[{node.index}] = nullptr;")
        lines.append("        }")
    return "\n".join(lines)


def _build_chain_set_param(chain: "list[ResolvedChainNode]") -> str:
    """Build SetParam dispatch for per-node parameter setting."""
    lines = []
    for node in chain:
        ns = f"{node.config.id}_circle"
        lines.append(f"        if (nodeIndex == {node.index}) {{")
        lines.append(
            f"            {ns}::wrapper_set_param(m_genState[{node.index}], paramIndex, value);"
        )
        lines.append("        }")
    return "\n".join(lines)


def _build_chain_perform(chain: "list[ResolvedChainNode]", max_channels: int) -> str:
    """Build the ping-pong perform block for GetChunk().

    Node 0 reads from scratchA, writes to scratchB.
    Node 1 reads from scratchB, writes to scratchA.
    And so on, alternating.
    """
    lines = []
    for node in chain:
        idx = node.index
        ns = f"{node.config.id}_circle"
        n_in = node.manifest.num_inputs
        n_out = node.manifest.num_outputs

        if idx % 2 == 0:
            in_buf = "m_pScratchA"
            out_buf = "m_pScratchB"
        else:
            in_buf = "m_pScratchB"
            out_buf = "m_pScratchA"

        lines.append(f"        // Node {idx}: {node.config.id} ({n_in}in/{n_out}out)")
        lines.append(f"        {ns}::wrapper_perform(")
        lines.append(f"            m_genState[{idx}],")
        if n_in > 0:
            lines.append(f"            {in_buf}, {n_in},")
        else:
            lines.append("            nullptr, 0,")
        lines.append(f"            {out_buf}, {n_out},")
        lines.append("            (long)nFrames);")
        lines.append("")
    return "\n".join(lines)


def _build_chain_midi_dispatch(
    chain: "list[ResolvedChainNode]", graph: "GraphConfig"
) -> str:
    """Build MIDI CC dispatch code.

    For each node, generates an if-block matching its MIDI channel.
    Within that block, maps CC numbers to parameter indices.
    If cc_map is explicit, use it. Otherwise, CC-by-param-index
    (CC 0 -> param 0, CC 1 -> param 1, etc.).
    """
    lines = []
    for node in chain:
        midi_ch = node.config.midi_channel
        if midi_ch is None:
            midi_ch = node.index + 1
        ns = f"{node.config.id}_circle"
        n_params = node.manifest.num_params

        lines.append(f"    // Node {node.index}: {node.config.id} (MIDI ch {midi_ch})")
        lines.append(f"    if (channel == {midi_ch}) {{")

        if node.config.cc_map:
            # Explicit CC mapping
            for cc_num, param_name in sorted(node.config.cc_map.items()):
                # Find param index by name
                param_idx = None
                for p in node.manifest.params:
                    if p.name == param_name:
                        param_idx = p.index
                        break
                if param_idx is not None:
                    lines.append(f"        if (cc == {cc_num}) {{")
                    lines.append(
                        f"            // {param_name}: scale normalized to [min, max]"
                    )
                    lines.append(
                        f"            float min = {ns}::wrapper_param_min("
                        f"s_pSoundDevice->m_genState[{node.index}], {param_idx});"
                    )
                    lines.append(
                        f"            float max = {ns}::wrapper_param_max("
                        f"s_pSoundDevice->m_genState[{node.index}], {param_idx});"
                    )
                    lines.append(
                        f"            s_pSoundDevice->SetParam({node.index}, "
                        f"{param_idx}, min + normalized * (max - min));"
                    )
                    lines.append("        }")
        else:
            # CC-by-param-index: CC N -> param N
            if n_params > 0:
                lines.append(f"        if (cc < {n_params}) {{")
                lines.append(
                    f"            s_pSoundDevice->SetParam({node.index}, "
                    f"(int)cc, normalized);"
                )
                lines.append("        }")

        lines.append("    }")
    return "\n".join(lines)


def _build_chain_per_node_flags(chain: "list[ResolvedChainNode]") -> str:
    """Build per-node CPPFLAGS with include paths and defines."""
    lines = []
    for node in chain:
        idx = node.index
        assert node.export_info is not None
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
