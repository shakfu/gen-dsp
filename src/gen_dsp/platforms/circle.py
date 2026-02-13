"""
Circle (Raspberry Pi bare metal) platform implementation.

Generates bare-metal firmware projects for Raspberry Pi using the Circle
C++ environment (https://github.com/rsta2/circle). This is a cross-compilation
target producing kernel images (.img) that boot directly on the Pi hardware
with no operating system.

Key differences from other backends:
  - Cross-compilation: arm-none-eabi-gcc (32-bit) or aarch64-none-elf-gcc (64-bit)
  - Custom genlib runtime: genlib_circle.cpp replaces genlib.cpp (heap-based)
  - Make-based build using Circle's Rules.mk
  - Output: kernel*.img for SD card boot
  - Audio via I2S, PWM, HDMI, or USB depending on board variant

Circle SDK acquisition: auto clone + build (git clone --depth 1 --branch <tag>).
Resolution priority (same pattern as Daisy):
  1. CIRCLE_DIR env var          (explicit override)
  2. GEN_DSP_CACHE_DIR env var   (shared cache override)
  3. OS-appropriate gen-dsp cache path (baked into generated Makefile)

Supports Pi Zero through Pi 5 with multiple audio outputs via --board flag.
Board configs use GNU Make 'override' to ensure the project's RASPPI/AARCH/PREFIX
take precedence over the SDK's Config.mk.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gen_dsp.core.graph import GraphConfig, ResolvedChainNode

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_circle_templates_dir


# Circle version (latest stable release)
CIRCLE_VERSION = "Step50.1"


# ---------------------------------------------------------------------------
# Audio device metadata
# ---------------------------------------------------------------------------

# Maps audio_device -> (include header, base class name, device label)
_AUDIO_DEVICE_INFO: dict[str, tuple[str, str, str]] = {
    "i2s": (
        "<circle/sound/i2ssoundbasedevice.h>",
        "CI2SSoundBaseDevice",
        "I2S",
    ),
    "pwm": (
        "<circle/sound/pwmsoundbasedevice.h>",
        "CPWMSoundBaseDevice",
        "PWM",
    ),
    "hdmi": (
        "<circle/sound/hdmisoundbasedevice.h>",
        "CHDMISoundBaseDevice",
        "HDMI",
    ),
    "usb": (
        "<circle/sound/usbsoundbasedevice.h>",
        "CUSBSoundBaseDevice",
        "USB",
    ),
}


def _get_audio_include(audio_device: str) -> str:
    """Return the #include line for a sound device type."""
    header, _, _ = _AUDIO_DEVICE_INFO[audio_device]
    return f"#include {header}"


def _get_audio_base_class(audio_device: str) -> str:
    """Return the Circle sound base class name."""
    _, cls, _ = _AUDIO_DEVICE_INFO[audio_device]
    return cls


def _get_audio_label(audio_device: str) -> str:
    """Return a human-readable label for the audio device."""
    _, _, label = _AUDIO_DEVICE_INFO[audio_device]
    return label


def _get_extra_libs(audio_device: str) -> str:
    """Return additional LIBS entries needed for the audio device."""
    if audio_device == "usb":
        return "$(CIRCLEHOME)/lib/usb/libusb.a"
    return ""


def _get_boot_config(audio_device: str) -> str:
    """Return config.txt content specific to the audio device."""
    if audio_device == "i2s":
        return (
            "# For I2S DAC setup (PCM5102A, PCM5122, UDA1334A, etc.):\n"
            "#   Connect DAC to Pi GPIO header:\n"
            "#     BCK  -> GPIO 18 (pin 12)\n"
            "#     LRCK -> GPIO 19 (pin 35)\n"
            "#     DIN  -> GPIO 21 (pin 40)\n"
            "#     VIN  -> 3.3V (pin 1)\n"
            "#     GND  -> GND (pin 6)\n"
            "\n"
            "# Enable I2S audio overlay\n"
            "dtparam=i2s=on"
        )
    elif audio_device == "pwm":
        return (
            "# PWM audio output through 3.5mm headphone jack\n"
            "# No additional hardware required\n"
            "# Default GPIOs: 12 (left) and 13 (right)"
        )
    elif audio_device == "hdmi":
        return (
            "# HDMI audio output (48kHz stereo)\n"
            "# Connect HDMI to a monitor or audio receiver"
        )
    elif audio_device == "usb":
        return (
            "# USB audio output (Pi 4/5 only)\n# Connect a USB DAC or audio interface"
        )
    return ""


# ---------------------------------------------------------------------------
# Board configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CircleBoardConfig:
    """Hardware configuration for a specific Circle board variant."""

    key: str  # "pi3-i2s", "pi4-pwm", etc.
    rasppi: int  # RASPPI value: 1, 3, 4, or 5
    aarch: int  # 32 or 64 (bit width)
    prefix: str  # Compiler prefix
    kernel_img: str  # Output kernel image filename
    audio_device: str  # "i2s", "pwm", "hdmi", or "usb"


CIRCLE_BOARDS: dict[str, CircleBoardConfig] = {
    # --- Pi Zero (original / W) - 32-bit, single core ---
    "pi0-pwm": CircleBoardConfig(
        key="pi0-pwm",
        rasppi=1,
        aarch=32,
        prefix="arm-none-eabi-",
        kernel_img="kernel.img",
        audio_device="pwm",
    ),
    "pi0-i2s": CircleBoardConfig(
        key="pi0-i2s",
        rasppi=1,
        aarch=32,
        prefix="arm-none-eabi-",
        kernel_img="kernel.img",
        audio_device="i2s",
    ),
    # --- Pi Zero 2 W - same SoC as Pi 3 ---
    "pi0w2-i2s": CircleBoardConfig(
        key="pi0w2-i2s",
        rasppi=3,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8.img",
        audio_device="i2s",
    ),
    "pi0w2-pwm": CircleBoardConfig(
        key="pi0w2-pwm",
        rasppi=3,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8.img",
        audio_device="pwm",
    ),
    # --- Pi 3 / 3B+ ---
    "pi3-i2s": CircleBoardConfig(
        key="pi3-i2s",
        rasppi=3,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8.img",
        audio_device="i2s",
    ),
    "pi3-pwm": CircleBoardConfig(
        key="pi3-pwm",
        rasppi=3,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8.img",
        audio_device="pwm",
    ),
    "pi3-hdmi": CircleBoardConfig(
        key="pi3-hdmi",
        rasppi=3,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8.img",
        audio_device="hdmi",
    ),
    # --- Pi 4 / 400 ---
    "pi4-i2s": CircleBoardConfig(
        key="pi4-i2s",
        rasppi=4,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8-rpi4.img",
        audio_device="i2s",
    ),
    "pi4-pwm": CircleBoardConfig(
        key="pi4-pwm",
        rasppi=4,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8-rpi4.img",
        audio_device="pwm",
    ),
    "pi4-usb": CircleBoardConfig(
        key="pi4-usb",
        rasppi=4,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8-rpi4.img",
        audio_device="usb",
    ),
    "pi4-hdmi": CircleBoardConfig(
        key="pi4-hdmi",
        rasppi=4,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel8-rpi4.img",
        audio_device="hdmi",
    ),
    # --- Pi 5 (64-bit only) ---
    "pi5-i2s": CircleBoardConfig(
        key="pi5-i2s",
        rasppi=5,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel_2712.img",
        audio_device="i2s",
    ),
    "pi5-usb": CircleBoardConfig(
        key="pi5-usb",
        rasppi=5,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel_2712.img",
        audio_device="usb",
    ),
    "pi5-hdmi": CircleBoardConfig(
        key="pi5-hdmi",
        rasppi=5,
        aarch=64,
        prefix="aarch64-none-elf-",
        kernel_img="kernel_2712.img",
        audio_device="hdmi",
    ),
}

_CIRCLE_CLONE_URL = "https://github.com/rsta2/circle.git"

# Subdirectory name inside the gen-dsp cache
_CIRCLE_CACHE_SUBDIR = "circle-src"
_CIRCLE_DIR_NAME = "circle"


def _get_default_circle_dir() -> Path:
    """Return the default cached Circle path (OS-appropriate)."""
    from gen_dsp.core.cache import get_cache_dir

    return get_cache_dir() / _CIRCLE_CACHE_SUBDIR / _CIRCLE_DIR_NAME


def _resolve_circle_dir() -> Path:
    """Resolve CIRCLE_DIR using the priority chain.

    1. CIRCLE_DIR env var
    2. GEN_DSP_CACHE_DIR env var + circle-src/circle
    3. OS-appropriate gen-dsp cache path
    """
    env_circle = os.environ.get("CIRCLE_DIR")
    if env_circle:
        return Path(env_circle)

    env_cache = os.environ.get("GEN_DSP_CACHE_DIR")
    if env_cache:
        return Path(env_cache) / _CIRCLE_CACHE_SUBDIR / _CIRCLE_DIR_NAME

    return _get_default_circle_dir()


def ensure_circle(circle_dir: Optional[Path] = None, verbose: bool = False) -> Path:
    """Ensure Circle SDK is available, cloning and building if necessary.

    Args:
        circle_dir: Explicit path. If None, resolves via priority chain.
        verbose: Print progress messages.

    Returns:
        Path to the Circle directory (containing Rules.mk).

    Raises:
        BuildError: If clone or build fails, or if git/toolchain
                    is not available.
    """
    if circle_dir is None:
        circle_dir = _resolve_circle_dir()

    # Already present and built?
    if (circle_dir / "Rules.mk").is_file() and (
        circle_dir / "lib" / "libcircle.a"
    ).is_file():
        return circle_dir

    # Check prerequisites
    if not shutil.which("git"):
        raise BuildError(
            "git is required to clone Circle. Install git and ensure it is on PATH."
        )

    if not shutil.which("aarch64-none-elf-gcc"):
        raise BuildError(
            "aarch64-none-elf-gcc is required to build Circle SDK. "
            "Download the AArch64 bare-metal toolchain from:\n"
            "  https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads\n"
            "Select the 'aarch64-none-elf' variant for your host OS, extract it,\n"
            "and add its bin/ directory to your PATH."
        )

    # Clone if not present
    if not (circle_dir / "Rules.mk").is_file():
        cache_parent = circle_dir.parent
        cache_parent.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f"Cloning Circle {CIRCLE_VERSION} from {_CIRCLE_CLONE_URL} ...")

        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    CIRCLE_VERSION,
                    _CIRCLE_CLONE_URL,
                    str(circle_dir),
                ],
                check=True,
                capture_output=not verbose,
                text=True,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except subprocess.CalledProcessError as e:
            raise BuildError(f"Failed to clone Circle: {e}") from e

    # Configure and build Circle libraries if not already built
    if not (circle_dir / "lib" / "libcircle.a").is_file():
        if verbose:
            print("Configuring Circle ...")

        # Run ./configure to generate Config.mk
        # Use Pi 3 / AArch64 as the default SDK build target.
        # The per-project Makefile uses 'override' directives to set
        # the correct RASPPI/AARCH/PREFIX for the actual target board.
        try:
            subprocess.run(
                ["./configure", "-r", "3", "-p", "aarch64-none-elf-"],
                cwd=circle_dir,
                check=True,
                capture_output=not verbose,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            raise BuildError(f"Failed to configure Circle: {e}\n{stderr}") from e

        if verbose:
            print("Building Circle libraries ...")

        try:
            subprocess.run(
                ["./makeall", "clean"],
                cwd=circle_dir,
                check=True,
                capture_output=not verbose,
                text=True,
            )
        except subprocess.CalledProcessError:
            pass  # clean may fail on first build

        try:
            subprocess.run(
                ["./makeall"],
                cwd=circle_dir,
                check=True,
                capture_output=not verbose,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            raise BuildError(f"Failed to build Circle: {e}\n{stderr}") from e

    # Verify
    if not (circle_dir / "lib" / "libcircle.a").is_file():
        raise BuildError(
            f"Circle build completed but libcircle.a not found at "
            f"{circle_dir / 'lib' / 'libcircle.a'}"
        )

    return circle_dir


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
            "_ext_circle.h",
            "circle_buffer.h",
            "genlib_circle.h",
            "genlib_circle.cpp",
            "cmath",  # shim: Circle's -nostdinc++ strips C++ headers
        ]
        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

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
    ) -> None:
        """Generate Makefile from template."""
        if not template_path.exists():
            raise ProjectError(f"Makefile template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)
        content = template.safe_substitute(
            gen_name=gen_name,
            lib_name=lib_name,
            genext_version=self.GENEXT_VERSION,
            num_inputs=num_inputs,
            num_outputs=num_outputs,
            num_params=num_params,
            default_circle_dir=default_circle_dir,
            rasppi=board.rasppi,
            aarch=board.aarch,
            prefix=board.prefix,
            extra_libs=_get_extra_libs(board.audio_device),
        )
        output_path.write_text(content, encoding="utf-8")

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
        if not template_path.exists():
            raise ProjectError(f"config.txt template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)
        content = template.safe_substitute(
            rasppi=board.rasppi,
            audio_boot_config=_get_boot_config(board.audio_device),
        )
        output_path.write_text(content, encoding="utf-8")

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
        for candidate in project_dir.glob("kernel*.img"):
            return candidate
        return None

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
            genext_version=self.GENEXT_VERSION,
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
