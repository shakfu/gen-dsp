"""
Daisy (Electrosmith) embedded platform implementation.

Generates firmware projects for the Daisy Seed (STM32H750-based embedded
audio platform). This is gen-dsp's first cross-compilation target: it requires
arm-none-eabi-gcc and produces firmware binaries (.bin), not shared libraries.

Key differences from other backends:
  - Cross-compilation: arm-none-eabi-gcc instead of host compiler
  - Custom genlib runtime: genlib_daisy.cpp replaces genlib.cpp (bump allocator)
  - Make-based build using libDaisy's core/Makefile (ARM toolchain rules)
  - Output: firmware .bin for DFU flashing

libDaisy acquisition: auto clone + build (git clone --recurse-submodules).
Resolution priority (same pattern as VCV Rack):
  1. LIBDAISY_DIR env var       (explicit override)
  2. GEN_DSP_CACHE_DIR env var  (shared cache override)
  3. OS-appropriate gen-dsp cache path (baked into generated Makefile)

Supports 8 board variants (seed, pod, patch, patch_sm, field, petal,
legio, versio) via --board CLI flag. Knob-to-parameter automap generates
code that reads hardware knobs and scales to gen~ parameter ranges.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_daisy_templates_dir


# libDaisy version (latest stable, well-tested)
LIBDAISY_VERSION = "v7.1.0"


# ---------------------------------------------------------------------------
# Board configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DaisyBoardConfig:
    """Hardware configuration for a specific Daisy board variant."""

    key: str  # "seed", "pod", etc.
    header: str  # "daisy_seed.h"
    hw_class: str  # "DaisySeed"
    hw_channels: int  # 2 or 4
    knob_exprs: tuple[str, ...]  # C++ expressions returning 0-1 per knob
    extra_using: str  # "" or "using namespace daisy::patch_sm;"


DAISY_BOARDS: dict[str, DaisyBoardConfig] = {
    "seed": DaisyBoardConfig(
        key="seed",
        header="daisy_seed.h",
        hw_class="DaisySeed",
        hw_channels=2,
        knob_exprs=(),
        extra_using="",
    ),
    "pod": DaisyBoardConfig(
        key="pod",
        header="daisy_pod.h",
        hw_class="DaisyPod",
        hw_channels=2,
        knob_exprs=(
            "hw.knob1.Value()",
            "hw.knob2.Value()",
        ),
        extra_using="",
    ),
    "patch": DaisyBoardConfig(
        key="patch",
        header="daisy_patch.h",
        hw_class="DaisyPatch",
        hw_channels=4,
        knob_exprs=(
            "hw.GetKnobValue(DaisyPatch::CTRL_1)",
            "hw.GetKnobValue(DaisyPatch::CTRL_2)",
            "hw.GetKnobValue(DaisyPatch::CTRL_3)",
            "hw.GetKnobValue(DaisyPatch::CTRL_4)",
        ),
        extra_using="",
    ),
    "patch_sm": DaisyBoardConfig(
        key="patch_sm",
        header="daisy_patch_sm.h",
        hw_class="DaisyPatchSM",
        hw_channels=2,
        knob_exprs=(
            "hw.GetAdcValue(CV_1)",
            "hw.GetAdcValue(CV_2)",
            "hw.GetAdcValue(CV_3)",
            "hw.GetAdcValue(CV_4)",
        ),
        extra_using="using namespace daisy::patch_sm;",
    ),
    "field": DaisyBoardConfig(
        key="field",
        header="daisy_field.h",
        hw_class="DaisyField",
        hw_channels=2,
        knob_exprs=(
            "hw.GetKnobValue(DaisyField::KNOB_1)",
            "hw.GetKnobValue(DaisyField::KNOB_2)",
            "hw.GetKnobValue(DaisyField::KNOB_3)",
            "hw.GetKnobValue(DaisyField::KNOB_4)",
            "hw.GetKnobValue(DaisyField::KNOB_5)",
            "hw.GetKnobValue(DaisyField::KNOB_6)",
            "hw.GetKnobValue(DaisyField::KNOB_7)",
            "hw.GetKnobValue(DaisyField::KNOB_8)",
        ),
        extra_using="",
    ),
    "petal": DaisyBoardConfig(
        key="petal",
        header="daisy_petal.h",
        hw_class="DaisyPetal",
        hw_channels=2,
        knob_exprs=(
            "hw.GetKnobValue(DaisyPetal::KNOB_1)",
            "hw.GetKnobValue(DaisyPetal::KNOB_2)",
            "hw.GetKnobValue(DaisyPetal::KNOB_3)",
            "hw.GetKnobValue(DaisyPetal::KNOB_4)",
            "hw.GetKnobValue(DaisyPetal::KNOB_5)",
            "hw.GetKnobValue(DaisyPetal::KNOB_6)",
        ),
        extra_using="",
    ),
    "legio": DaisyBoardConfig(
        key="legio",
        header="daisy_legio.h",
        hw_class="DaisyLegio",
        hw_channels=2,
        knob_exprs=(
            "hw.GetKnobValue(DaisyLegio::CONTROL_KNOB_TOP)",
            "hw.GetKnobValue(DaisyLegio::CONTROL_KNOB_BOTTOM)",
        ),
        extra_using="",
    ),
    "versio": DaisyBoardConfig(
        key="versio",
        header="daisy_versio.h",
        hw_class="DaisyVersio",
        hw_channels=2,
        knob_exprs=(
            "hw.GetKnobValue(0)",
            "hw.GetKnobValue(1)",
            "hw.GetKnobValue(2)",
            "hw.GetKnobValue(3)",
            "hw.GetKnobValue(4)",
            "hw.GetKnobValue(5)",
            "hw.GetKnobValue(6)",
        ),
        extra_using="",
    ),
}
_LIBDAISY_CLONE_URL = "https://github.com/electro-smith/libDaisy.git"

# Subdirectory name inside the gen-dsp cache
_LIBDAISY_CACHE_SUBDIR = "libdaisy-src"
_LIBDAISY_DIR_NAME = "libDaisy"


def _get_default_libdaisy_dir() -> Path:
    """Return the default cached libDaisy path (OS-appropriate)."""
    from gen_dsp.core.cache import get_cache_dir

    return get_cache_dir() / _LIBDAISY_CACHE_SUBDIR / _LIBDAISY_DIR_NAME


def _resolve_libdaisy_dir() -> Path:
    """Resolve LIBDAISY_DIR using the priority chain.

    1. LIBDAISY_DIR env var
    2. GEN_DSP_CACHE_DIR env var + libdaisy-src/libDaisy
    3. OS-appropriate gen-dsp cache path
    """
    env_libdaisy = os.environ.get("LIBDAISY_DIR")
    if env_libdaisy:
        return Path(env_libdaisy)

    env_cache = os.environ.get("GEN_DSP_CACHE_DIR")
    if env_cache:
        return Path(env_cache) / _LIBDAISY_CACHE_SUBDIR / _LIBDAISY_DIR_NAME

    return _get_default_libdaisy_dir()


def ensure_libdaisy(libdaisy_dir: Optional[Path] = None, verbose: bool = False) -> Path:
    """Ensure libDaisy is available, cloning and building if necessary.

    Args:
        libdaisy_dir: Explicit path. If None, resolves via priority chain.
        verbose: Print progress messages.

    Returns:
        Path to the libDaisy directory (containing core/Makefile).

    Raises:
        BuildError: If clone or build fails, or if git/arm-none-eabi-gcc
                    is not available.
    """
    if libdaisy_dir is None:
        libdaisy_dir = _resolve_libdaisy_dir()

    # Already present and built?
    if (libdaisy_dir / "core" / "Makefile").is_file() and (
        libdaisy_dir / "build" / "libdaisy.a"
    ).is_file():
        return libdaisy_dir

    # Check prerequisites
    if not shutil.which("git"):
        raise BuildError(
            "git is required to clone libDaisy. Install git and ensure it is on PATH."
        )

    if not shutil.which("arm-none-eabi-gcc"):
        raise BuildError(
            "arm-none-eabi-gcc is required to build for Daisy. "
            "Install the ARM GCC toolchain and ensure it is on PATH."
        )

    # Clone if not present
    if not (libdaisy_dir / "core" / "Makefile").is_file():
        cache_parent = libdaisy_dir.parent
        cache_parent.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f"Cloning libDaisy {LIBDAISY_VERSION} from {_LIBDAISY_CLONE_URL} ...")

        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--recurse-submodules",
                    "--depth",
                    "1",
                    "--branch",
                    LIBDAISY_VERSION,
                    _LIBDAISY_CLONE_URL,
                    str(libdaisy_dir),
                ],
                check=True,
                capture_output=not verbose,
                text=True,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except subprocess.CalledProcessError as e:
            raise BuildError(f"Failed to clone libDaisy: {e}") from e

    # Build libdaisy.a if not already built
    if not (libdaisy_dir / "build" / "libdaisy.a").is_file():
        if verbose:
            print("Building libDaisy ...")

        try:
            subprocess.run(
                ["make", "-j"],
                cwd=libdaisy_dir,
                check=True,
                capture_output=not verbose,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise BuildError(f"Failed to build libDaisy: {e}") from e

    # Verify
    if not (libdaisy_dir / "build" / "libdaisy.a").is_file():
        raise BuildError(
            f"libDaisy build completed but libdaisy.a not found at "
            f"{libdaisy_dir / 'build' / 'libdaisy.a'}"
        )

    return libdaisy_dir


def _generate_main_loop_body(board: DaisyBoardConfig, num_params: int) -> str:
    """Generate C++ code for the main loop body.

    For boards with knobs: reads knobs, scales to parameter range, sets params.
    For seed or 0 params: comment-only placeholder.

    Returns indented code (8 spaces) suitable for insertion into the for(;;) block.
    """
    num_knobs = len(board.knob_exprs)
    mapped = min(num_knobs, num_params)

    if mapped == 0:
        lines = [
            "        // No hardware knobs on this board (or no gen~ params).",
            "        // Add user code here: read ADCs, update parameters, etc.",
        ]
        return "\n".join(lines)

    lines = []
    lines.append("        hw.ProcessAllControls();")
    lines.append("        if (genState) {")
    lines.append(f"            // Automap: {mapped} knob(s) -> first {mapped} param(s)")
    for i in range(mapped):
        knob_expr = board.knob_exprs[i]
        lines.append("            {")
        lines.append(f"                float knob = {knob_expr};")
        lines.append(f"                float lo = wrapper_param_min(genState, {i});")
        lines.append(f"                float hi = wrapper_param_max(genState, {i});")
        lines.append(
            f"                wrapper_set_param(genState, {i}, lo + knob * (hi - lo));"
        )
        lines.append("            }")
    lines.append("        }")

    return "\n".join(lines)


class DaisyPlatform(Platform):
    """Daisy embedded platform implementation using Make."""

    name = "daisy"

    @property
    def extension(self) -> str:
        """Get the extension for Daisy firmware binaries."""
        return ".bin"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for Daisy."""
        return ["make"]

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate Daisy firmware project files."""
        templates_dir = get_daisy_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"Daisy templates not found at {templates_dir}")

        # Resolve board config
        board_key = "seed"
        if config is not None and config.board is not None:
            board_key = config.board
        if board_key not in DAISY_BOARDS:
            raise ProjectError(
                f"Unknown Daisy board '{board_key}'. "
                f"Valid boards: {', '.join(sorted(DAISY_BOARDS))}"
            )
        board = DAISY_BOARDS[board_key]

        # Copy static template files (board-agnostic)
        static_files = [
            "gen_ext_common_daisy.h",
            "_ext_daisy.cpp",
            "_ext_daisy.h",
            "daisy_buffer.h",
            "genlib_daisy.h",
            "genlib_daisy.cpp",
        ]
        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Generate gen_ext_daisy.cpp from template (board-specific)
        self._generate_ext_daisy(
            templates_dir / "gen_ext_daisy.cpp.template",
            output_dir / "gen_ext_daisy.cpp",
            board,
            manifest.num_params,
        )

        # Resolve default LIBDAISY_DIR for baking into Makefile
        default_libdaisy_dir = str(_get_default_libdaisy_dir())

        # Generate Makefile from template
        self._generate_makefile(
            templates_dir / "Makefile.template",
            output_dir / "Makefile",
            manifest.gen_name,
            lib_name,
            manifest.num_inputs,
            manifest.num_outputs,
            manifest.num_params,
            default_libdaisy_dir,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp Daisy wrapper",
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
        default_libdaisy_dir: str,
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
            default_libdaisy_dir=default_libdaisy_dir,
        )
        output_path.write_text(content, encoding="utf-8")

    def _generate_ext_daisy(
        self,
        template_path: Path,
        output_path: Path,
        board: DaisyBoardConfig,
        num_params: int,
    ) -> None:
        """Generate gen_ext_daisy.cpp from template with board-specific values."""
        if not template_path.exists():
            raise ProjectError(
                f"gen_ext_daisy.cpp template not found at {template_path}"
            )

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)

        # Build extra_using line (empty string or full line with newline prefix)
        extra_using = ""
        if board.extra_using:
            extra_using = "\n" + board.extra_using

        main_loop_body = _generate_main_loop_body(board, num_params)

        content = template.safe_substitute(
            board_key=board.key,
            board_header=board.header,
            board_class=board.hw_class,
            hw_channels=board.hw_channels,
            extra_using=extra_using,
            main_loop_body=main_loop_body,
        )
        output_path.write_text(content, encoding="utf-8")

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build Daisy firmware using make.

        Automatically clones and builds libDaisy if not already cached.
        """
        makefile = project_dir / "Makefile"
        if not makefile.exists():
            raise BuildError(f"Makefile not found in {project_dir}")

        # Ensure libDaisy is available (clones and builds if needed)
        libdaisy_dir = _resolve_libdaisy_dir()
        libdaisy_dir = ensure_libdaisy(libdaisy_dir, verbose=verbose)

        # Clean if requested
        if clean:
            self.run_command(
                ["make", "clean", f"LIBDAISY_DIR={libdaisy_dir}"], project_dir
            )

        # Build with explicit LIBDAISY_DIR
        result = self.run_command(
            ["make", f"LIBDAISY_DIR={libdaisy_dir}"], project_dir, verbose=verbose
        )

        # Find output file
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=result.returncode == 0,
            platform="daisy",
            output_file=output_file,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        libdaisy_dir = _resolve_libdaisy_dir()
        if (libdaisy_dir / "core" / "Makefile").is_file():
            self.run_command(
                ["make", "clean", f"LIBDAISY_DIR={libdaisy_dir}"], project_dir
            )

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built Daisy firmware binary."""
        build_dir = project_dir / "build"
        if build_dir.is_dir():
            for candidate in build_dir.glob("*.bin"):
                return candidate
        return None
