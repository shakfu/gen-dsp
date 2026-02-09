"""
PureData platform implementation.
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
from gen_dsp.templates import get_pd_templates_dir


class PureDataPlatform(Platform):
    """PureData platform implementation using pd-lib-builder."""

    name = "pd"

    @property
    def extension(self) -> str:
        """Get the file extension for the current OS."""
        system = sys_platform.system().lower()
        if system == "darwin":
            return ".pd_darwin"
        elif system == "linux":
            return ".pd_linux"
        elif system == "windows":
            return ".dll"
        return ".pd_linux"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for PureData."""
        return ["make all"]

    def generate_project(
        self,
        export_info: ExportInfo,
        output_dir: Path,
        lib_name: str,
        buffers: list[str],
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate PureData project files."""
        templates_dir = get_pd_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"PureData templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "gen_dsp.cpp",
            "gen_ext_common.h",
            "_ext.cpp",
            "_ext.h",
            "pd_buffer.h",
        ]

        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Copy pd-lib-builder
        pd_lib_builder_src = templates_dir / "pd-lib-builder"
        pd_lib_builder_dst = output_dir / "pd-lib-builder"
        if pd_lib_builder_src.is_dir():
            if pd_lib_builder_dst.exists():
                shutil.rmtree(pd_lib_builder_dst)
            shutil.copytree(pd_lib_builder_src, pd_lib_builder_dst)

        # Generate Makefile
        self._generate_makefile(
            templates_dir / "Makefile.template",
            output_dir / "Makefile",
            export_info.name,
            lib_name,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            buffers,
        )

    def _generate_makefile(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
    ) -> None:
        """Generate Makefile from template."""
        if template_path.exists():
            template_content = template_path.read_text()
            template = Template(template_content)
            content = template.safe_substitute(
                gen_name=gen_name,
                lib_name=lib_name,
                genext_version=self.GENEXT_VERSION,
            )
        else:
            # Fallback: generate directly
            content = f"""# Makefile for {lib_name}

# Name of the exported .cpp/.h file from gen~
gen.name = {gen_name}

# Name of the external to generate (do not add ~ suffix)
lib.name = {lib_name}

gendsp.version = {self.GENEXT_VERSION}

$(lib.name)~.class.sources = gen_dsp.cpp _ext.cpp ./gen/gen_dsp/genlib.cpp
cflags = -I ./gen -I./gen/gen_dsp -DGEN_EXT_VERSION=$(gendsp.version) -DPD_EXT_NAME=$(lib.name) -DGEN_EXPORTED_NAME=$(gen.name) -DGEN_EXPORTED_HEADER=\\"$(gen.name).h\\" -DGEN_EXPORTED_CPP=\\"$(gen.name).cpp\\"
suppress-wunused = yes

define forDarwin
  cflags += -DMSP_ON_CLANG -DGENLIB_USE_FLOAT32 -mmacosx-version-min=10.9
endef

define forLinux
  $(lib.name)~.class.sources += ./gen/gen_dsp/json.c ./gen/gen_dsp/json_builder.c
endef

include ./pd-lib-builder/Makefile.pdlibbuilder
"""

        output_path.write_text(content)

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build PureData external using make."""
        makefile = project_dir / "Makefile"
        if not makefile.exists():
            raise BuildError(f"Makefile not found in {project_dir}")

        # Clean if requested
        if clean:
            self.run_command(["make", "clean"], project_dir)

        # Build using base class run_command
        result = self.run_command(["make", "all"], project_dir, verbose=verbose)

        # Find output file
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=result.returncode == 0,
            platform="pd",
            output_file=output_file,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        self.run_command(["make", "clean"], project_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built PureData external file."""
        # Look for files with the platform extension
        for f in project_dir.glob(f"*{self.extension}"):
            return f

        # Also check for .d_* variants (older naming on macOS)
        system = sys_platform.system().lower()
        if system == "darwin":
            for pattern in ["*.d_fat", "*.d_amd64", "*.d_arm64"]:
                for f in project_dir.glob(pattern):
                    return f

        return None
