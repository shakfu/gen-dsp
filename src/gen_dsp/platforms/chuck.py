"""
ChucK chugin platform implementation.

Generates ChucK chugins (.chug files) using make and the bundled chugin.h header.
"""

import platform as sys_platform
import shutil
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_chuck_templates_dir


class ChuckPlatform(Platform):
    """ChucK chugin platform implementation using make."""

    name = "chuck"

    @property
    def extension(self) -> str:
        """Get the file extension for chugins."""
        return ".chug"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for ChucK chugin."""
        system = sys_platform.system().lower()
        if system == "darwin":
            return ["make mac"]
        elif system == "linux":
            return ["make linux"]
        return ["make mac"]

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate ChucK chugin project files."""
        templates_dir = get_chuck_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"ChucK templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "gen_ext_chuck.cpp",
            "gen_ext_common_chuck.h",
            "_ext_chuck.cpp",
            "_ext_chuck.h",
            "chuck_buffer.h",
            "makefile.mac",
            "makefile.linux",
        ]

        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Copy chugin.h (bundled header in chuck/include/)
        chugin_include_src = templates_dir / "chuck" / "include"
        chugin_include_dst = output_dir / "chuck" / "include"
        if chugin_include_src.is_dir():
            if chugin_include_dst.exists():
                shutil.rmtree(chugin_include_dst)
            chugin_include_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(chugin_include_src, chugin_include_dst)

        # Generate makefile from template
        self._generate_makefile(
            templates_dir / "makefile.template",
            output_dir / "makefile",
            manifest.gen_name,
            lib_name,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp ChucK chugin wrapper",
        )

    def _capitalize_name(self, name: str) -> str:
        """Capitalize the first letter of a name for ChucK class convention."""
        if not name:
            return name
        return name[0].upper() + name[1:]

    def _generate_makefile(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
    ) -> None:
        """Generate makefile from template."""
        if template_path.exists():
            template_content = template_path.read_text(encoding="utf-8")
            template = Template(template_content)
            content = template.safe_substitute(
                gen_name=gen_name,
                lib_name=self._capitalize_name(lib_name),
                genext_version=self.GENEXT_VERSION,
            )
        else:
            raise ProjectError(f"makefile template not found at {template_path}")

        output_path.write_text(content, encoding="utf-8")

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build ChucK chugin using make."""
        makefile = project_dir / "makefile"
        if not makefile.exists():
            raise BuildError(f"makefile not found in {project_dir}")

        # Clean if requested
        if clean:
            self.run_command(["make", "clean"], project_dir)

        # Detect OS and build accordingly
        system = sys_platform.system().lower()
        if system == "darwin":
            build_target = "mac"
        elif system == "linux":
            build_target = "linux"
        else:
            build_target = "mac"

        # Build using base class run_command
        result = self.run_command(["make", build_target], project_dir, verbose=verbose)

        # Find output file
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=result.returncode == 0,
            platform="chuck",
            output_file=output_file,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        self.run_command(["make", "clean"], project_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built chugin file."""
        for f in project_dir.glob("*.chug"):
            return f
        return None
