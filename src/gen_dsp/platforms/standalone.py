"""
Standalone audio application platform implementation.

Generates standalone audio executables using miniaudio (single-header,
public domain, zero-dependency audio library). The generated application
processes audio from the system's default input to the default output,
with parameters configurable via command-line arguments.
"""

import platform as sys_platform
import shutil
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest, build_remap_defines_make
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_standalone_templates_dir


class StandalonePlatform(Platform):
    """Standalone audio application platform using miniaudio."""

    name = "standalone"

    @property
    def extension(self) -> str:
        """Get the file extension for the built executable."""
        system = sys_platform.system().lower()
        if system == "windows":
            return ".exe"
        return ""

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for standalone application."""
        return ["make all"]

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate standalone project files."""
        templates_dir = get_standalone_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(
                f"Standalone templates not found at {templates_dir}"
            )

        # Copy static files
        static_files = [
            "gen_ext_standalone.cpp",
            "_ext_standalone.cpp",
            "gen_ext_common_standalone.h",
            "standalone_buffer.h",
        ]

        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Generate _ext_standalone.h via shared template
        self.generate_ext_header(output_dir, "standalone")
        self.copy_remap_header(output_dir)

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp standalone wrapper",
        )

        # Build input remap compile definitions
        remap_defines = build_remap_defines_make(manifest, "CFLAGS")

        # Generate Makefile from template
        self._generate_from_template(
            templates_dir / "Makefile.template",
            output_dir / "Makefile",
            lib_name=lib_name,
            gen_name=manifest.gen_name,
            genext_version=self.GENEXT_VERSION,
            remap_defines=remap_defines,
        )

    def _generate_from_template(
        self,
        template_path: Path,
        output_path: Path,
        **substitutions: str,
    ) -> None:
        """Render a template file with the given substitutions."""
        if not template_path.exists():
            raise ProjectError(f"Template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)
        content = template.safe_substitute(**substitutions)
        output_path.write_text(content, encoding="utf-8")

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build standalone executable using make."""
        makefile = project_dir / "Makefile"
        if not makefile.exists():
            raise BuildError(f"Makefile not found in {project_dir}")

        if clean:
            self.run_command(["make", "clean"], project_dir)

        result = self.run_command(["make", "all"], project_dir, verbose=verbose)
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=result.returncode == 0,
            platform="standalone",
            output_file=output_file,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        self.run_command(["make", "clean"], project_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built executable.

        The executable name matches the lib_name from the Makefile.
        We look for any executable file in the project root.
        """
        # Read LIB_NAME from Makefile
        makefile = project_dir / "Makefile"
        if makefile.exists():
            for line in makefile.read_text().splitlines():
                if line.startswith("LIB_NAME"):
                    lib_name = line.split("=", 1)[1].strip()
                    exe = project_dir / lib_name
                    if exe.is_file():
                        return exe
                    # Windows
                    exe_win = project_dir / (lib_name + ".exe")
                    if exe_win.is_file():
                        return exe_win
                    break
        return None
