"""
Csound opcode plugin platform implementation.

Generates Csound opcode plugins (.so/.dylib) that register as custom opcodes
via the csdl.h C API. Audio inputs map to a-rate args, parameters to k-rate
args, and audio outputs to a-rate outputs.
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
from gen_dsp.templates import get_csound_templates_dir


def _build_type_strings(
    num_inputs: int, num_outputs: int, num_params: int
) -> tuple[str, str]:
    """Build Csound OENTRY type strings from I/O counts.

    Returns:
        (outypes, intypes) -- e.g. ("aa", "aakkkk") for 2in/2out/4params.
    """
    outypes = "a" * num_outputs if num_outputs > 0 else "a"
    intypes = "a" * num_inputs + "k" * num_params
    if not intypes:
        intypes = ""
    return outypes, intypes


class CsoundPlatform(Platform):
    """Csound opcode plugin platform using make."""

    name = "csound"

    @property
    def extension(self) -> str:
        """Get the file extension for the built plugin."""
        system = sys_platform.system().lower()
        if system == "darwin":
            return ".dylib"
        return ".so"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for Csound opcode."""
        return ["make all"]

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate Csound opcode project files."""
        templates_dir = get_csound_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(
                f"Csound templates not found at {templates_dir}"
            )

        # Copy static files
        static_files = [
            "gen_ext_csound.cpp",
            "_ext_csound.cpp",
            "gen_ext_common_csound.h",
            "csound_buffer.h",
        ]

        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Generate _ext_csound.h via shared template
        self.generate_ext_header(output_dir, "csound")
        self.copy_remap_header(output_dir)

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp Csound opcode wrapper",
        )

        # Build OENTRY type strings
        outypes, intypes = _build_type_strings(
            manifest.num_inputs, manifest.num_outputs, len(manifest.params)
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
            num_inputs=str(manifest.num_inputs),
            num_outputs=str(manifest.num_outputs),
            num_params=str(len(manifest.params)),
            outypes=outypes,
            intypes=intypes,
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
        """Build Csound opcode plugin using make."""
        makefile = project_dir / "Makefile"
        if not makefile.exists():
            raise BuildError(f"Makefile not found in {project_dir}")

        if clean:
            self.run_command(["make", "clean"], project_dir)

        result = self.run_command(["make", "all"], project_dir, verbose=verbose)
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=result.returncode == 0,
            platform="csound",
            output_file=output_file,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        self.run_command(["make", "clean"], project_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built opcode plugin."""
        for ext in (".dylib", ".so"):
            for f in project_dir.glob(f"lib*{ext}"):
                return f
        return None
