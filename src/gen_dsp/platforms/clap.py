"""
CLAP plugin platform implementation.

Generates cross-platform CLAP plugins (.clap files) using CMake and
the CLAP C API (header-only, MIT licensed). CLAP headers are fetched
at configure time via CMake FetchContent -- no vendoring required.
"""

import shutil
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.parser import ExportInfo
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_clap_templates_dir


class ClapPlatform(Platform):
    """CLAP plugin platform implementation using CMake."""

    name = "clap"

    @property
    def extension(self) -> str:
        """Get the file extension for CLAP plugins."""
        return ".clap"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for CLAP."""
        return [
            "mkdir -p build && cd build && cmake .. && cmake --build .",
        ]

    def generate_project(
        self,
        export_info: ExportInfo,
        output_dir: Path,
        lib_name: str,
        buffers: list[str],
    ) -> None:
        """Generate CLAP project files."""
        templates_dir = get_clap_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"CLAP templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "gen_ext_clap.cpp",
            "gen_ext_common_clap.h",
            "_ext_clap.cpp",
            "_ext_clap.h",
            "clap_buffer.h",
        ]

        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Detect plugin type from I/O configuration
        plugin_type = self._detect_plugin_type(export_info.num_inputs)

        # Generate CMakeLists.txt
        self._generate_cmakelists(
            templates_dir / "CMakeLists.txt.template",
            output_dir / "CMakeLists.txt",
            export_info.name,
            lib_name,
            export_info.num_inputs,
            export_info.num_outputs,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            buffers,
            header_comment="Buffer configuration for gen_dsp CLAP wrapper",
        )

        # Create build directory
        (output_dir / "build").mkdir(exist_ok=True)

    def _detect_plugin_type(self, num_inputs: int) -> str:
        """Detect CLAP plugin type from number of inputs.

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
    ) -> None:
        """Generate CMakeLists.txt from template."""
        if not template_path.exists():
            raise ProjectError(
                f"CMakeLists.txt template not found at {template_path}"
            )

        template_content = template_path.read_text()
        template = Template(template_content)
        content = template.safe_substitute(
            gen_name=gen_name,
            lib_name=lib_name,
            genext_version=self.GENEXT_VERSION,
            num_inputs=num_inputs,
            num_outputs=num_outputs,
        )
        output_path.write_text(content)

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build CLAP plugin using CMake."""
        cmakelists = project_dir / "CMakeLists.txt"
        if not cmakelists.exists():
            raise BuildError(f"CMakeLists.txt not found in {project_dir}")

        build_dir = project_dir / "build"

        # Clean if requested
        if clean and build_dir.exists():
            shutil.rmtree(build_dir)

        build_dir.mkdir(exist_ok=True)

        # Configure with CMake
        configure_result = self.run_command(
            ["cmake", ".."], build_dir, verbose=verbose
        )
        if configure_result.returncode != 0:
            return BuildResult(
                success=False,
                platform="clap",
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
            platform="clap",
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
        """Find the built CLAP plugin file."""
        build_dir = project_dir / "build"
        if build_dir.is_dir():
            for f in build_dir.glob("**/*.clap"):
                return f
        return None
