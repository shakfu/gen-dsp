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

v1 scope: Daisy Seed only (2in/2out stereo, no built-in controls).
Parameters retain gen~ defaults. Users modify gen_ext_daisy.cpp to add
ADC reads for knobs/CV.
"""

import os
import shutil
import subprocess
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.parser import ExportInfo
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_daisy_templates_dir


# libDaisy version (latest stable, well-tested)
LIBDAISY_VERSION = "v7.1.0"
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


def ensure_libdaisy(
    libdaisy_dir: Optional[Path] = None, verbose: bool = False
) -> Path:
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
            "git is required to clone libDaisy. "
            "Install git and ensure it is on PATH."
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
            print(
                f"Cloning libDaisy {LIBDAISY_VERSION} from {_LIBDAISY_CLONE_URL} ..."
            )

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


class DaisyPlatform(Platform):
    """Daisy Seed embedded platform implementation using Make."""

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
        export_info: ExportInfo,
        output_dir: Path,
        lib_name: str,
        buffers: list[str],
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate Daisy Seed firmware project files."""
        templates_dir = get_daisy_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"Daisy templates not found at {templates_dir}")

        # Copy static template files
        static_files = [
            "gen_ext_daisy.cpp",
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

        # Resolve default LIBDAISY_DIR for baking into Makefile
        default_libdaisy_dir = str(_get_default_libdaisy_dir())

        # Generate Makefile from template
        self._generate_makefile(
            templates_dir / "Makefile.template",
            output_dir / "Makefile",
            export_info.name,
            lib_name,
            export_info.num_inputs,
            export_info.num_outputs,
            export_info.num_params,
            default_libdaisy_dir,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            buffers,
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

        template_content = template_path.read_text()
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
        output_path.write_text(content)

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
