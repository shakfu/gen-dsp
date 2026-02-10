"""
VST3 plugin platform implementation.

Generates cross-platform VST3 plugins (.vst3 bundles) using CMake and
the Steinberg VST3 SDK. The SDK is fetched at configure time via CMake
FetchContent -- no vendoring required.
"""

import hashlib
import struct
import shutil
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.parser import ExportInfo
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_vst3_templates_dir


class Vst3Platform(Platform):
    """VST3 plugin platform implementation using CMake."""

    name = "vst3"

    @property
    def extension(self) -> str:
        """Get the file extension for VST3 plugins."""
        return ".vst3"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for VST3."""
        return [
            "cmake -B build && cmake --build build",
        ]

    def generate_project(
        self,
        export_info: ExportInfo,
        output_dir: Path,
        lib_name: str,
        buffers: list[str],
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate VST3 project files."""
        templates_dir = get_vst3_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"VST3 templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "gen_ext_vst3.cpp",
            "gen_ext_common_vst3.h",
            "_ext_vst3.cpp",
            "_ext_vst3.h",
            "vst3_buffer.h",
        ]

        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Generate FUID from lib_name
        fuid = self._generate_fuid(lib_name)

        # Resolve shared cache settings
        shared_cache = config is not None and config.shared_cache
        if shared_cache:
            from gen_dsp.core.cache import get_cache_dir

            cache_dir = str(get_cache_dir())
        else:
            cache_dir = ""

        # Generate CMakeLists.txt
        self._generate_cmakelists(
            templates_dir / "CMakeLists.txt.template",
            output_dir / "CMakeLists.txt",
            export_info.name,
            lib_name,
            export_info.num_inputs,
            export_info.num_outputs,
            fuid,
            use_shared_cache="ON" if shared_cache else "OFF",
            cache_dir=cache_dir,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            buffers,
            header_comment="Buffer configuration for gen_dsp VST3 wrapper",
        )

        # Create build directory
        (output_dir / "build").mkdir(exist_ok=True)

    def _generate_fuid(self, lib_name: str) -> tuple[int, int, int, int]:
        """Generate a deterministic 128-bit FUID from the library name.

        Uses MD5 of 'com.gen-dsp.vst3.<lib_name>' split into 4 x uint32.
        Returns tuple of 4 integers.
        """
        digest = hashlib.md5(f"com.gen-dsp.vst3.{lib_name}".encode()).digest()
        return struct.unpack(">IIII", digest)

    def _detect_plugin_type(self, num_inputs: int) -> str:
        """Detect VST3 plugin type from number of inputs.

        Returns 'effect' if inputs > 0, 'instrument' if inputs == 0.
        """
        return "effect" if num_inputs > 0 else "instrument"

    def _generate_cmakelists(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
        num_inputs: int,
        num_outputs: int,
        fuid: tuple[int, int, int, int],
        use_shared_cache: str = "OFF",
        cache_dir: str = "",
    ) -> None:
        """Generate CMakeLists.txt from template."""
        if not template_path.exists():
            raise ProjectError(f"CMakeLists.txt template not found at {template_path}")

        template_content = template_path.read_text()
        template = Template(template_content)
        content = template.safe_substitute(
            gen_name=gen_name,
            lib_name=lib_name,
            genext_version=self.GENEXT_VERSION,
            num_inputs=num_inputs,
            num_outputs=num_outputs,
            fuid_0=f"0x{fuid[0]:08X}",
            fuid_1=f"0x{fuid[1]:08X}",
            fuid_2=f"0x{fuid[2]:08X}",
            fuid_3=f"0x{fuid[3]:08X}",
            use_shared_cache=use_shared_cache,
            cache_dir=cache_dir,
        )
        output_path.write_text(content)

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build VST3 plugin using CMake."""
        cmakelists = project_dir / "CMakeLists.txt"
        if not cmakelists.exists():
            raise BuildError(f"CMakeLists.txt not found in {project_dir}")

        build_dir = project_dir / "build"

        # Clean if requested
        if clean and build_dir.exists():
            shutil.rmtree(build_dir)

        build_dir.mkdir(exist_ok=True)

        # Configure with CMake
        configure_result = self.run_command(["cmake", ".."], build_dir, verbose=verbose)
        if configure_result.returncode != 0:
            return BuildResult(
                success=False,
                platform="vst3",
                output_file=None,
                stdout=configure_result.stdout,
                stderr=configure_result.stderr,
                return_code=configure_result.returncode,
            )

        # Build
        build_result = self.run_command(
            ["cmake", "--build", "."], build_dir, verbose=verbose
        )

        # Find output file
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=build_result.returncode == 0,
            platform="vst3",
            output_file=output_file,
            stdout=build_result.stdout,
            stderr=build_result.stderr,
            return_code=build_result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        build_dir = project_dir / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built VST3 plugin bundle."""
        build_dir = project_dir / "build"
        if build_dir.is_dir():
            for f in build_dir.glob("**/*.vst3"):
                if f.is_dir():
                    return f
        return None
