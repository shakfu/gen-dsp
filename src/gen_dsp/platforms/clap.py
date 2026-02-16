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
from gen_dsp.core.manifest import Manifest
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import ProjectError
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
            "cmake -B build && cmake --build build",
        ]

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
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

        # Resolve shared cache settings
        shared_cache = config is not None and config.shared_cache
        if shared_cache:
            from gen_dsp.core.cache import get_cache_dir

            cache_dir = get_cache_dir().as_posix()
        else:
            cache_dir = ""

        # Generate CMakeLists.txt
        self._generate_cmakelists(
            templates_dir / "CMakeLists.txt.template",
            output_dir / "CMakeLists.txt",
            manifest.gen_name,
            lib_name,
            manifest.num_inputs,
            manifest.num_outputs,
            use_shared_cache="ON" if shared_cache else "OFF",
            cache_dir=cache_dir,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp CLAP wrapper",
        )

        # Create build directory
        (output_dir / "build").mkdir(exist_ok=True)

    def _generate_cmakelists(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
        num_inputs: int,
        num_outputs: int,
        use_shared_cache: str = "OFF",
        cache_dir: str = "",
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
            use_shared_cache=use_shared_cache,
            cache_dir=cache_dir,
        )
        output_path.write_text(content, encoding="utf-8")

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build CLAP plugin using CMake."""
        return self._build_with_cmake(project_dir, clean, verbose)

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        self._clean_build_dir(project_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built CLAP plugin file."""
        build_dir = project_dir / "build"
        if build_dir.is_dir():
            for f in build_dir.glob("**/*.clap"):
                return f
        return None
