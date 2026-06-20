"""Circle (bare-metal Raspberry Pi) platform implementation."""

import shutil
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Optional

from gen_dsp.version import __version__
from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest, build_remap_defines_make
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_circle_templates_dir

from gen_dsp.platforms.circle.boards import (
    CIRCLE_BOARDS,
    CircleBoardConfig,
    _get_audio_base_class,
    _get_audio_include,
    _get_audio_label,
    _get_boot_config,
    _get_extra_libs,
)
from gen_dsp.platforms.circle.sdk import (
    CIRCLE_VERSION,
    _CIRCLE_CACHE_SUBDIR,
    _CIRCLE_CLONE_URL,
    _CIRCLE_DIR_NAME,
    _get_default_circle_dir,
    _resolve_circle_dir,
    ensure_circle,
)
from gen_dsp.platforms.circle.chain import (
    _build_chain_create,
    _build_chain_destroy,
    _build_chain_includes,
    _build_chain_io_defines,
    _build_chain_midi_dispatch,
    _build_chain_per_node_flags,
    _build_chain_perform,
    _build_chain_set_param,
)
from gen_dsp.platforms.circle.dag import (
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

if TYPE_CHECKING:
    from gen_dsp.core.graph import EdgeBuffer, GraphConfig, ResolvedChainNode
    from gen_dsp.graph.models import Graph


class CirclePlatform(Platform):
    """Circle bare metal Raspberry Pi platform implementation using Make."""

    name = "circle"

    @property
    def extension(self) -> str:
        """Get the extension for Circle kernel images."""
        return ".img"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for Circle."""
        return ["make"]

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate Circle bare metal project files."""
        templates_dir = get_circle_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"Circle templates not found at {templates_dir}")

        # Resolve board config
        board_key = "pi3-i2s"
        if config is not None and config.board is not None:
            board_key = config.board
        if board_key not in CIRCLE_BOARDS:
            raise ProjectError(
                f"Unknown Circle board '{board_key}'. "
                f"Valid boards: {', '.join(sorted(CIRCLE_BOARDS))}"
            )
        board = CIRCLE_BOARDS[board_key]

        # Copy static template files (board-agnostic)
        static_files = [
            "gen_ext_common_circle.h",
            "_ext_circle.cpp",
            "circle_buffer.h",
            "genlib_circle.h",
            "genlib_circle.cpp",
            "cmath",  # shim: Circle's -nostdinc++ strips C++ headers
        ]
        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        self.generate_ext_header(output_dir, "circle")
        self.copy_remap_header(output_dir)

        # Select template based on audio device type
        if board.audio_device == "usb":
            template_name = "gen_ext_circle_usb.cpp.template"
        else:
            template_name = "gen_ext_circle.cpp.template"

        # Generate gen_ext_circle.cpp from template (board-specific)
        self._generate_ext_circle(
            templates_dir / template_name,
            output_dir / "gen_ext_circle.cpp",
            board,
            manifest.num_inputs,
            manifest.num_outputs,
        )

        # Resolve default CIRCLE_DIR for baking into Makefile
        default_circle_dir = str(_get_default_circle_dir())

        # Build input remap compile definitions (both CFLAGS and CPPFLAGS)
        remap_defines = build_remap_defines_make(manifest, ["CFLAGS", "CPPFLAGS"])

        # Generate Makefile from template
        self._generate_makefile(
            templates_dir / "Makefile.template",
            output_dir / "Makefile",
            manifest.gen_name,
            lib_name,
            manifest.num_inputs,
            manifest.num_outputs,
            manifest.num_params,
            default_circle_dir,
            board,
            remap_defines=remap_defines,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp Circle wrapper",
        )

        # Generate config.txt for Pi boot partition
        self._generate_config_txt(
            templates_dir / "config.txt.template",
            output_dir / "config.txt",
            board,
        )

    def _generate_makefile(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
        num_inputs: int,
        num_outputs: int,
        num_params: int,
        default_circle_dir: str,
        board: CircleBoardConfig,
        remap_defines: str = "",
    ) -> None:
        """Generate Makefile from template."""
        self.render_template(
            template_path,
            output_path,
            label="Makefile template",
            gen_name=gen_name,
            lib_name=lib_name,
            gendsp_version=__version__,
            num_inputs=num_inputs,
            num_outputs=num_outputs,
            num_params=num_params,
            default_circle_dir=default_circle_dir,
            rasppi=board.rasppi,
            aarch=board.aarch,
            prefix=board.prefix,
            extra_libs=_get_extra_libs(board.audio_device),
            remap_defines=remap_defines,
        )

    def _generate_ext_circle(
        self,
        template_path: Path,
        output_path: Path,
        board: CircleBoardConfig,
        num_inputs: int,
        num_outputs: int,
    ) -> None:
        """Generate gen_ext_circle.cpp from template with board-specific values."""
        if not template_path.exists():
            raise ProjectError(
                f"gen_ext_circle.cpp template not found at {template_path}"
            )

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)

        content = template.safe_substitute(
            board_key=board.key,
            rasppi=board.rasppi,
            kernel_img=board.kernel_img,
            num_inputs=num_inputs,
            num_outputs=num_outputs,
            audio_include=_get_audio_include(board.audio_device),
            audio_base_class=_get_audio_base_class(board.audio_device),
            audio_label=_get_audio_label(board.audio_device),
        )
        output_path.write_text(content, encoding="utf-8")

    def _generate_config_txt(
        self,
        template_path: Path,
        output_path: Path,
        board: CircleBoardConfig,
    ) -> None:
        """Generate config.txt for Raspberry Pi boot partition."""
        self.render_template(
            template_path,
            output_path,
            label="config.txt template",
            rasppi=board.rasppi,
            audio_boot_config=_get_boot_config(board.audio_device),
        )

    def _write_graph_platform_files(
        self,
        graph: "Graph",
        manifest: Manifest,
        output_dir: Path,
        name: str,
        config: ProjectConfig,
    ) -> None:
        """Graph path: generate the board-specific gen_ext_circle.cpp and config.txt."""
        board_key = config.board if config.board is not None else "pi3-i2s"
        circle_board = CIRCLE_BOARDS[board_key]
        audio_include = _get_audio_include(circle_board.audio_device)
        audio_base_class = _get_audio_base_class(circle_board.audio_device)
        audio_label = _get_audio_label(circle_board.audio_device)

        gen_ext_circle = f"""\
// gen_ext_circle.cpp - Circle bare metal wrapper for graph compiled code
// Board: {board_key} (Raspberry Pi {circle_board.rasppi})
// Audio: {audio_label} output
// This file includes ONLY Circle headers - graph code is isolated in _ext_circle.cpp

#include <circle/actled.h>
#include <circle/koptions.h>
#include <circle/devicenameservice.h>
#include <circle/exceptionhandler.h>
#include <circle/interrupt.h>
#include <circle/logger.h>
#include <circle/startup.h>
#include <circle/timer.h>
#include <circle/types.h>
{audio_include}

#include "gen_ext_common_circle.h"
#include "_ext_circle.h"

using namespace WRAPPER_NAMESPACE;

#define CIRCLE_SAMPLE_RATE     48000
#define CIRCLE_CHUNK_SIZE      256
#define CIRCLE_AUDIO_CHANNELS  2

#define CIRCLE_NUM_INPUTS  {manifest.num_inputs}
#define CIRCLE_NUM_OUTPUTS {manifest.num_outputs}

class CGenDSPSoundDevice : public {audio_base_class}
{{
public:
    CGenDSPSoundDevice(CInterruptSystem* pInterrupt)
        : {audio_base_class}(pInterrupt, CIRCLE_SAMPLE_RATE, CIRCLE_CHUNK_SIZE),
          m_genState(nullptr)
    {{
        for (int i = 0; i < CIRCLE_NUM_INPUTS || i < 1; i++) {{
            m_pInputBuffers[i] = m_InputStorage[i];
        }}
        for (int i = 0; i < CIRCLE_NUM_OUTPUTS || i < 1; i++) {{
            m_pOutputBuffers[i] = m_OutputStorage[i];
        }}
    }}

    ~CGenDSPSoundDevice(void)
    {{
        if (m_genState) {{
            wrapper_destroy(m_genState);
            m_genState = nullptr;
        }}
    }}

    boolean Initialize(void)
    {{
        m_genState = wrapper_create((float)CIRCLE_SAMPLE_RATE, (long)CIRCLE_CHUNK_SIZE);
        if (!m_genState) {{
            return FALSE;
        }}
        return Start();
    }}

protected:
    unsigned GetChunk(u32* pBuffer, unsigned nChunkSize) override
    {{
        if (!m_genState) {{
            for (unsigned i = 0; i < nChunkSize; i++) {{
                pBuffer[i] = 0;
            }}
            return nChunkSize;
        }}

        unsigned nFrames = nChunkSize / CIRCLE_AUDIO_CHANNELS;

#if CIRCLE_NUM_INPUTS > 0
        for (int ch = 0; ch < CIRCLE_NUM_INPUTS; ch++) {{
            for (unsigned i = 0; i < nFrames; i++) {{
                m_InputStorage[ch][i] = 0.0f;
            }}
        }}
#endif

        wrapper_perform(
            m_genState,
#if CIRCLE_NUM_INPUTS > 0
            m_pInputBuffers,
#else
            nullptr,
#endif
            CIRCLE_NUM_INPUTS,
            m_pOutputBuffers,
            CIRCLE_NUM_OUTPUTS,
            (long)nFrames
        );

        int nRangeMin = GetRangeMin();
        int nRangeMax = GetRangeMax();

        for (unsigned i = 0; i < nFrames; i++) {{
            for (int ch = 0; ch < CIRCLE_AUDIO_CHANNELS; ch++) {{
                float sample = 0.0f;
                if (ch < CIRCLE_NUM_OUTPUTS) {{
                    sample = m_pOutputBuffers[ch][i];
                }}
                if (sample > 1.0f) sample = 1.0f;
                if (sample < -1.0f) sample = -1.0f;
                int nSample = (int)((sample + 1.0f) / 2.0f
                    * (nRangeMax - nRangeMin) + nRangeMin);
                pBuffer[i * CIRCLE_AUDIO_CHANNELS + ch] = (u32)nSample;
            }}
        }}

        return nChunkSize;
    }}

private:
    GenState* m_genState;
    float m_InputStorage[CIRCLE_NUM_INPUTS > 0 ? CIRCLE_NUM_INPUTS : 1][CIRCLE_CHUNK_SIZE];
    float m_OutputStorage[CIRCLE_NUM_OUTPUTS > 0 ? CIRCLE_NUM_OUTPUTS : 1][CIRCLE_CHUNK_SIZE];
    float* m_pInputBuffers[CIRCLE_NUM_INPUTS > 0 ? CIRCLE_NUM_INPUTS : 1];
    float* m_pOutputBuffers[CIRCLE_NUM_OUTPUTS > 0 ? CIRCLE_NUM_OUTPUTS : 1];
}};

class CKernel
{{
public:
    CKernel(void)
        : m_Timer(&m_Interrupt),
          m_Logger(m_Options.GetLogLevel(), &m_Timer),
          m_pSound(nullptr)
    {{
    }}

    ~CKernel(void)
    {{
        delete m_pSound;
    }}

    boolean Initialize(void)
    {{
        if (!m_Interrupt.Initialize()) {{
            return FALSE;
        }}
        if (!m_Timer.Initialize()) {{
            return FALSE;
        }}
        if (!m_Logger.Initialize(nullptr)) {{
            return FALSE;
        }}

        m_pSound = new CGenDSPSoundDevice(&m_Interrupt);
        if (!m_pSound->Initialize()) {{
            m_Logger.Write("gen-dsp", LogError, "Failed to initialize {audio_label} sound device");
            return FALSE;
        }}

        m_Logger.Write("gen-dsp", LogNotice,
            "gen-dsp Circle audio started: %uHz, %u frames/chunk, {audio_label} output",
            CIRCLE_SAMPLE_RATE, CIRCLE_CHUNK_SIZE);

        return TRUE;
    }}

    void Run(void)
    {{
        for (;;) {{
        }}
    }}

private:
    CActLED             m_ActLED;
    CKernelOptions      m_Options;
    CDeviceNameService  m_DeviceNameService;
    CExceptionHandler   m_ExceptionHandler;
    CInterruptSystem    m_Interrupt;
    CTimer              m_Timer;
    CLogger             m_Logger;
    CGenDSPSoundDevice* m_pSound;
}};

int main(void)
{{
    CKernel Kernel;
    if (!Kernel.Initialize()) {{
        halt();
        return EXIT_HALT;
    }}
    Kernel.Run();
    halt();
    return EXIT_HALT;
}}
"""
        (output_dir / "gen_ext_circle.cpp").write_text(gen_ext_circle)

        config_template_path = get_circle_templates_dir() / "config.txt.template"
        if config_template_path.is_file():
            config_content = config_template_path.read_text(encoding="utf-8")
            config_txt = Template(config_content).safe_substitute(
                audio_boot_config=_get_boot_config(circle_board.audio_device),
            )
            (output_dir / "config.txt").write_text(config_txt, encoding="utf-8")

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build Circle firmware using make.

        Automatically clones and builds Circle if not already cached.
        """
        makefile = project_dir / "Makefile"
        if not makefile.exists():
            raise BuildError(f"Makefile not found in {project_dir}")

        # Ensure Circle is available (clones and builds if needed)
        circle_dir = _resolve_circle_dir()
        circle_dir = ensure_circle(circle_dir, verbose=verbose)

        # Clean if requested
        if clean:
            self.run_command(["make", "clean", f"CIRCLEHOME={circle_dir}"], project_dir)

        # Build with explicit CIRCLEHOME
        result = self.run_command(
            ["make", f"CIRCLEHOME={circle_dir}"], project_dir, verbose=verbose
        )

        # Find output file
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=result.returncode == 0,
            platform="circle",
            output_file=output_file,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        circle_dir = _resolve_circle_dir()
        if (circle_dir / "Rules.mk").is_file():
            self.run_command(["make", "clean", f"CIRCLEHOME={circle_dir}"], project_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built Circle kernel image."""
        return self.find_output_by_pattern(project_dir, "kernel*.img")

    # ------------------------------------------------------------------
    # Chain mode (multi-plugin serial chain)
    # ------------------------------------------------------------------

    def generate_chain_project(
        self,
        chain: "list[ResolvedChainNode]",
        graph: "GraphConfig",
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate Circle chain project with multiple gen~ plugins.

        Args:
            chain: List of ResolvedChainNode (from graph.resolve_chain).
            graph: The original GraphConfig (for MIDI mapping).
            output_dir: Output directory.
            lib_name: Project name.
            config: Optional project config (for board selection).
        """

        templates_dir = get_circle_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"Circle templates not found at {templates_dir}")

        # Resolve board config
        board_key = "pi3-i2s"
        if config is not None and config.board is not None:
            board_key = config.board
        if board_key not in CIRCLE_BOARDS:
            raise ProjectError(
                f"Unknown Circle board '{board_key}'. "
                f"Valid boards: {', '.join(sorted(CIRCLE_BOARDS))}"
            )
        board = CIRCLE_BOARDS[board_key]

        # Copy static template files shared with chain mode
        static_files = [
            "gen_ext_common_circle.h",
            "_ext_circle_impl.cpp",
            "_ext_circle_impl.h",
            "circle_buffer.h",
            "genlib_circle.h",
            "genlib_circle.cpp",
            "cmath",
        ]
        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Compute chain metrics
        max_channels = max(
            max(n.manifest.num_inputs, n.manifest.num_outputs, 1) for n in chain
        )

        # Generate per-node wrapper shims
        self._generate_per_node_wrappers(chain, output_dir)

        # Generate gen_buffer.h (no buffers in chain Phase 1)
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            [],
            header_comment="Buffer configuration for gen_dsp Circle chain wrapper",
        )

        # Generate chain kernel (gen_ext_circle.cpp)
        self._generate_chain_kernel(
            templates_dir, output_dir, chain, graph, board, max_channels, lib_name
        )

        # Generate chain Makefile
        default_circle_dir = str(_get_default_circle_dir())
        self._generate_chain_makefile(
            templates_dir, output_dir, chain, lib_name, default_circle_dir, board
        )

        # Generate config.txt
        self._generate_config_txt(
            templates_dir / "config.txt.template",
            output_dir / "config.txt",
            board,
        )

    def _generate_per_node_wrappers(
        self,
        chain: "list[ResolvedChainNode]",
        output_dir: Path,
    ) -> None:
        """Generate thin _ext_circle_N.cpp/h shims for each chain node.

        Each shim defines macros (CIRCLE_EXT_NAME, GEN_EXPORTED_NAME, etc.)
        then #includes the shared _ext_circle_impl.cpp/h.
        """
        for node in chain:
            assert node.export_info is not None
            idx = node.index
            node_id = node.config.id
            gen_name = node.export_info.name

            # Generate _ext_circle_N.h
            h_content = (
                f"// _ext_circle_{idx}.h - Chain node {idx}: {node_id}\n"
                f"// Auto-generated wrapper header for {gen_name}\n"
                f"\n"
                f"#undef CIRCLE_EXT_NAME\n"
                f"#define CIRCLE_EXT_NAME {node_id}\n"
                f"\n"
                f'#include "_ext_circle_impl.h"\n'
            )
            (output_dir / f"_ext_circle_{idx}.h").write_text(
                h_content, encoding="utf-8"
            )

            # Generate _ext_circle_N.cpp
            cpp_content = (
                f"// _ext_circle_{idx}.cpp - Chain node {idx}: {node_id}\n"
                f"// Auto-generated wrapper for {gen_name}\n"
                f"\n"
                f"#undef CIRCLE_EXT_NAME\n"
                f"#define CIRCLE_EXT_NAME {node_id}\n"
                f"#undef GEN_EXPORTED_NAME\n"
                f"#define GEN_EXPORTED_NAME {gen_name}\n"
                f"#undef GEN_EXPORTED_HEADER\n"
                f'#define GEN_EXPORTED_HEADER "{gen_name}.h"\n'
                f"#undef GEN_EXPORTED_CPP\n"
                f'#define GEN_EXPORTED_CPP "{gen_name}.cpp"\n'
                f"\n"
                f'#include "_ext_circle_impl.cpp"\n'
            )
            (output_dir / f"_ext_circle_{idx}.cpp").write_text(
                cpp_content, encoding="utf-8"
            )

    def _generate_chain_kernel(
        self,
        templates_dir: Path,
        output_dir: Path,
        chain: "list[ResolvedChainNode]",
        graph: "GraphConfig",
        board: CircleBoardConfig,
        max_channels: int,
        lib_name: str,
    ) -> None:
        """Generate gen_ext_circle.cpp from chain template."""
        if board.audio_device == "usb":
            template_name = "gen_ext_circle_chain_usb.cpp.template"
        else:
            template_name = "gen_ext_circle_chain.cpp.template"

        template_path = templates_dir / template_name
        if not template_path.exists():
            raise ProjectError(f"Chain template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)

        last_node = chain[-1]
        # Determine which scratch buffer holds the final output
        # Even-indexed nodes write to B, odd-indexed nodes write to A
        if (len(chain) - 1) % 2 == 0:
            final_output_ptr = "m_pScratchB"
        else:
            final_output_ptr = "m_pScratchA"

        content = template.safe_substitute(
            board_key=board.key,
            rasppi=board.rasppi,
            kernel_img=board.kernel_img,
            num_nodes=len(chain),
            max_channels=max_channels,
            audio_include=_get_audio_include(board.audio_device),
            audio_base_class=_get_audio_base_class(board.audio_device),
            audio_label=_get_audio_label(board.audio_device),
            chain_includes=_build_chain_includes(chain),
            chain_io_defines=_build_chain_io_defines(chain),
            chain_create_calls=_build_chain_create(chain),
            chain_destroy_calls=_build_chain_destroy(chain),
            chain_set_param_calls=_build_chain_set_param(chain),
            chain_perform_block=_build_chain_perform(chain, max_channels),
            chain_midi_dispatch=_build_chain_midi_dispatch(chain, graph),
            chain_last_num_outputs=last_node.manifest.num_outputs,
            chain_final_output_ptr=final_output_ptr,
        )
        (output_dir / "gen_ext_circle.cpp").write_text(content, encoding="utf-8")

    def _generate_chain_makefile(
        self,
        templates_dir: Path,
        output_dir: Path,
        chain: "list[ResolvedChainNode]",
        lib_name: str,
        default_circle_dir: str,
        board: CircleBoardConfig,
    ) -> None:
        """Generate Makefile from chain template."""
        template_path = templates_dir / "Makefile_chain.template"
        if not template_path.exists():
            raise ProjectError(f"Chain Makefile template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)

        # Build per-node .o list
        ext_objs = " ".join(f"_ext_circle_{n.index}.o" for n in chain)

        # Extra libs: for chain mode, USB is always linked (for MIDI).
        # But if audio is also USB, we don't duplicate.
        extra_libs = _get_extra_libs(board.audio_device)

        content = template.safe_substitute(
            lib_name=lib_name,
            gendsp_version=__version__,
            num_nodes=len(chain),
            default_circle_dir=default_circle_dir,
            rasppi=board.rasppi,
            aarch=board.aarch,
            prefix=board.prefix,
            chain_ext_objs=ext_objs,
            extra_libs=extra_libs,
            chain_per_node_flags=_build_chain_per_node_flags(chain),
        )
        (output_dir / "Makefile").write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # DAG mode (Phase 2: arbitrary DAG topology)
    # ------------------------------------------------------------------

    def generate_dag_project(
        self,
        dag_nodes: "list[ResolvedChainNode]",
        graph: "GraphConfig",
        edge_buffers: "list[EdgeBuffer]",
        num_buffers: int,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate Circle DAG project with arbitrary topology.

        Args:
            dag_nodes: List of ResolvedChainNode in topological order.
            graph: The original GraphConfig.
            edge_buffers: Buffer allocations from allocate_edge_buffers().
            num_buffers: Total number of allocated intermediate buffers.
            output_dir: Output directory.
            lib_name: Project name.
            config: Optional project config (for board selection).
        """
        templates_dir = get_circle_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"Circle templates not found at {templates_dir}")

        # Resolve board config
        board_key = "pi3-i2s"
        if config is not None and config.board is not None:
            board_key = config.board
        if board_key not in CIRCLE_BOARDS:
            raise ProjectError(
                f"Unknown Circle board '{board_key}'. "
                f"Valid boards: {', '.join(sorted(CIRCLE_BOARDS))}"
            )
        board = CIRCLE_BOARDS[board_key]

        # Copy static template files (same as chain)
        static_files = [
            "gen_ext_common_circle.h",
            "_ext_circle_impl.cpp",
            "_ext_circle_impl.h",
            "circle_buffer.h",
            "genlib_circle.h",
            "genlib_circle.cpp",
            "cmath",
        ]
        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Compute max channels across all nodes
        max_channels = max(
            max(n.manifest.num_inputs, n.manifest.num_outputs, 1) for n in dag_nodes
        )

        # Generate per-node wrapper shims (gen~ nodes only)
        gen_nodes = [n for n in dag_nodes if n.config.node_type == "gen"]
        self._generate_per_node_wrappers(gen_nodes, output_dir)

        # Generate gen_buffer.h
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            [],
            header_comment="Buffer configuration for gen_dsp Circle DAG wrapper",
        )

        # Generate DAG kernel (gen_ext_circle.cpp)
        self._generate_dag_kernel(
            templates_dir,
            output_dir,
            dag_nodes,
            graph,
            edge_buffers,
            num_buffers,
            board,
            max_channels,
            lib_name,
        )

        # Generate DAG Makefile (reuses chain Makefile template)
        default_circle_dir = str(_get_default_circle_dir())
        self._generate_dag_makefile(
            templates_dir,
            output_dir,
            dag_nodes,
            lib_name,
            default_circle_dir,
            board,
        )

        # Generate config.txt
        self._generate_config_txt(
            templates_dir / "config.txt.template",
            output_dir / "config.txt",
            board,
        )

    def _generate_dag_kernel(
        self,
        templates_dir: Path,
        output_dir: Path,
        dag_nodes: "list[ResolvedChainNode]",
        graph: "GraphConfig",
        edge_buffers: "list[EdgeBuffer]",
        num_buffers: int,
        board: CircleBoardConfig,
        max_channels: int,
        lib_name: str,
    ) -> None:
        """Generate gen_ext_circle.cpp from DAG template."""
        if board.audio_device == "usb":
            template_name = "gen_ext_circle_dag_usb.cpp.template"
        else:
            template_name = "gen_ext_circle_dag.cpp.template"

        template_path = templates_dir / template_name
        if not template_path.exists():
            raise ProjectError(f"DAG template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)

        # Find the last node that feeds audio_out
        last_node = dag_nodes[-1]
        for c in graph.connections:
            if c.dst_node == "audio_out":
                for n in dag_nodes:
                    if n.config.id == c.src_node:
                        last_node = n
                        break

        # Find the buffer that feeds audio_out
        out_edges = [e for e in edge_buffers if e.dst_node == "audio_out"]
        if out_edges and out_edges[0].buffer_id >= 0:
            final_output_ptr = f"m_pDagBuf_{out_edges[0].buffer_id}"
        else:
            # Fallback: use the last allocated buffer
            final_output_ptr = (
                f"m_pDagBuf_{num_buffers - 1}" if num_buffers > 0 else "m_pHwInput"
            )

        # Build clear-buffers code
        clear_lines = []
        for i in range(num_buffers):
            for ch in range(max_channels):
                clear_lines.append(f"            m_DagBufStorage_{i}[{ch}][i] = 0.0f;")
        dag_clear_buffers = "\n".join(clear_lines)

        content = template.safe_substitute(
            board_key=board.key,
            rasppi=board.rasppi,
            kernel_img=board.kernel_img,
            num_nodes=len(dag_nodes),
            num_buffers=num_buffers,
            audio_include=_get_audio_include(board.audio_device),
            audio_base_class=_get_audio_base_class(board.audio_device),
            audio_label=_get_audio_label(board.audio_device),
            dag_includes=_build_dag_includes(dag_nodes),
            dag_io_defines=_build_dag_io_defines(dag_nodes),
            dag_buffer_decls=_build_dag_buffer_decls(num_buffers, max_channels),
            dag_buffer_init=_build_dag_buffer_init(num_buffers),
            dag_mixer_gain_decls=_build_dag_mixer_gain_decls(dag_nodes),
            dag_create_calls=_build_dag_create(dag_nodes),
            dag_destroy_calls=_build_dag_destroy(dag_nodes),
            dag_set_param_calls=_build_dag_set_param(dag_nodes),
            dag_perform_block=_build_dag_perform(
                dag_nodes, edge_buffers, graph, max_channels
            ),
            dag_clear_buffers=dag_clear_buffers,
            dag_midi_dispatch=_build_dag_midi_dispatch(dag_nodes, graph),
            dag_last_num_outputs=last_node.manifest.num_outputs,
            dag_final_output_ptr=final_output_ptr,
        )
        (output_dir / "gen_ext_circle.cpp").write_text(content, encoding="utf-8")

    def _generate_dag_makefile(
        self,
        templates_dir: Path,
        output_dir: Path,
        dag_nodes: "list[ResolvedChainNode]",
        lib_name: str,
        default_circle_dir: str,
        board: CircleBoardConfig,
    ) -> None:
        """Generate Makefile for DAG project (reuses chain Makefile template)."""
        template_path = templates_dir / "Makefile_chain.template"
        if not template_path.exists():
            raise ProjectError(f"Chain Makefile template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)

        # Build per-node .o list (gen~ nodes only)
        gen_nodes = [n for n in dag_nodes if n.config.node_type == "gen"]
        ext_objs = " ".join(f"_ext_circle_{n.index}.o" for n in gen_nodes)

        extra_libs = _get_extra_libs(board.audio_device)

        content = template.safe_substitute(
            lib_name=lib_name,
            gendsp_version=__version__,
            num_nodes=len(dag_nodes),
            default_circle_dir=default_circle_dir,
            rasppi=board.rasppi,
            aarch=board.aarch,
            prefix=board.prefix,
            chain_ext_objs=ext_objs,
            extra_libs=extra_libs,
            chain_per_node_flags=_build_dag_per_node_flags(dag_nodes),
        )
        (output_dir / "Makefile").write_text(content, encoding="utf-8")


__all__ = [
    "CirclePlatform",
    "CIRCLE_BOARDS",
    "CIRCLE_VERSION",
    "CircleBoardConfig",
    "_CIRCLE_CACHE_SUBDIR",
    "_CIRCLE_CLONE_URL",
    "_CIRCLE_DIR_NAME",
    "_build_chain_create",
    "_build_chain_destroy",
    "_build_chain_includes",
    "_build_chain_io_defines",
    "_build_chain_midi_dispatch",
    "_build_chain_per_node_flags",
    "_build_chain_perform",
    "_build_chain_set_param",
    "_build_dag_buffer_decls",
    "_build_dag_buffer_init",
    "_build_dag_create",
    "_build_dag_destroy",
    "_build_dag_includes",
    "_build_dag_io_defines",
    "_build_dag_midi_dispatch",
    "_build_dag_mixer_gain_decls",
    "_build_dag_per_node_flags",
    "_build_dag_perform",
    "_build_dag_set_param",
    "_get_audio_base_class",
    "_get_audio_include",
    "_get_audio_label",
    "_get_boot_config",
    "_get_default_circle_dir",
    "_get_extra_libs",
    "_resolve_circle_dir",
    "ensure_circle",
]
