"""
AudioUnit (AUv2) platform implementation.

Generates macOS AudioUnit v2 plugins (.component bundles) using CMake and
the raw AUv2 C API (AudioComponentPlugInInterface). No external SDK is
required -- only system frameworks (AudioToolbox, CoreFoundation, CoreAudio).
"""

import platform as sys_platform
import shutil
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.parser import ExportInfo
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_au_templates_dir


class AudioUnitPlatform(Platform):
    """AudioUnit v2 platform implementation using CMake."""

    name = "au"

    # Default manufacturer code for gen-dsp generated AUs
    AU_MANUFACTURER = "gdsp"

    @property
    def extension(self) -> str:
        """Get the file extension for AudioUnit plugins."""
        return ".component"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for AudioUnit."""
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
        """Generate AudioUnit project files."""
        templates_dir = get_au_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"AudioUnit templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "gen_ext_au.cpp",
            "gen_ext_common_au.h",
            "_ext_au.cpp",
            "_ext_au.h",
            "au_buffer.h",
        ]

        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Detect AU type from I/O configuration
        au_type = self._detect_au_type(export_info.num_inputs)
        au_subtype = self._generate_subtype(lib_name)

        # Generate CMakeLists.txt
        self._generate_cmakelists(
            templates_dir / "CMakeLists.txt.template",
            output_dir / "CMakeLists.txt",
            export_info.name,
            lib_name,
            export_info.num_inputs,
            export_info.num_outputs,
        )

        # Generate Info.plist
        self._generate_info_plist(
            templates_dir / "Info.plist.template",
            output_dir / "Info.plist",
            lib_name,
            au_type,
            au_subtype,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            buffers,
            header_comment="Buffer configuration for gen_dsp AudioUnit wrapper",
        )

        # Create build directory
        (output_dir / "build").mkdir(exist_ok=True)

    def _detect_au_type(self, num_inputs: int) -> str:
        """Detect AU component type from number of inputs.

        Returns 'aufx' (effect) if inputs > 0, 'augn' (generator) if inputs == 0.
        """
        return "aufx" if num_inputs > 0 else "augn"

    def _generate_subtype(self, lib_name: str) -> str:
        """Generate a 4-char AU subtype code from the library name.

        Takes first 4 characters lowercased, padded with 'x' if shorter.
        """
        code = lib_name.lower()[:4]
        return code.ljust(4, "x")

    def _generate_cmakelists(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
        num_inputs: int,
        num_outputs: int,
    ) -> None:
        """Generate CMakeLists.txt from template."""
        if not template_path.exists():
            raise ProjectError(f"CMakeLists.txt template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)
        content = template.safe_substitute(
            gen_name=gen_name,
            lib_name=lib_name,
            genext_version=self.GENEXT_VERSION,
            num_inputs=num_inputs,
            num_outputs=num_outputs,
        )
        output_path.write_text(content, encoding="utf-8")

    def _generate_info_plist(
        self,
        template_path: Path,
        output_path: Path,
        lib_name: str,
        au_type: str,
        au_subtype: str,
    ) -> None:
        """Generate Info.plist from template."""
        if not template_path.exists():
            raise ProjectError(f"Info.plist template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)
        content = template.safe_substitute(
            lib_name=lib_name,
            genext_version=self.GENEXT_VERSION,
            au_type=au_type,
            au_subtype=au_subtype,
            au_manufacturer=self.AU_MANUFACTURER,
        )
        output_path.write_text(content, encoding="utf-8")

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build AudioUnit using CMake."""
        if sys_platform.system() != "Darwin":
            raise BuildError("AudioUnit plugins can only be built on macOS")

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
                platform="au",
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
            platform="au",
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
        """Find the built AudioUnit .component bundle."""
        build_dir = project_dir / "build"
        if build_dir.is_dir():
            for f in build_dir.glob("**/*.component"):
                return f
        return None
