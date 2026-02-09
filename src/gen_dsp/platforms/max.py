"""
Max/MSP platform implementation.

Generates Max/MSP externals using CMake and the max-sdk-base submodule.
"""

import platform as sys_platform
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
from gen_dsp.templates import get_max_templates_dir


class MaxPlatform(Platform):
    """Max/MSP platform implementation using CMake and max-sdk-base."""

    name = "max"

    # max-sdk-base git repository
    MAX_SDK_REPO = "https://github.com/Cycling74/max-sdk-base.git"

    @property
    def extension(self) -> str:
        """Get the file extension for the current OS."""
        system = sys_platform.system().lower()
        if system == "darwin":
            return ".mxo"
        elif system == "windows":
            return ".mxe64"
        return ".mxl"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for Max/MSP."""
        return [
            "git clone --depth 1 https://github.com/Cycling74/max-sdk-base.git",
            "mkdir -p build && cd build && cmake .. && cmake --build .",
        ]

    def generate_project(
        self,
        export_info: ExportInfo,
        output_dir: Path,
        lib_name: str,
        buffers: list[str],
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate Max/MSP project files."""
        templates_dir = get_max_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"Max/MSP templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "gen_ext_max.cpp",
            "gen_ext_common_max.h",
            "_ext_max.cpp",
            "_ext_max.h",
            "gen_buffer_max.h",
        ]

        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Generate CMakeLists.txt
        self._generate_cmakelists(
            templates_dir / "CMakeLists.txt.template",
            output_dir / "CMakeLists.txt",
            export_info.name,
            lib_name,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            buffers,
            header_comment="Buffer configuration for gen_dsp Max/MSP wrapper",
        )

        # Create build directory
        (output_dir / "build").mkdir(exist_ok=True)

        # Create externals output directory
        (output_dir / "externals").mkdir(exist_ok=True)

    def _generate_cmakelists(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
    ) -> None:
        """Generate CMakeLists.txt from template."""
        if template_path.exists():
            template_content = template_path.read_text()
            template = Template(template_content)
            content = template.safe_substitute(
                gen_name=gen_name,
                lib_name=lib_name,
                genext_version=self.GENEXT_VERSION,
            )
        else:
            raise ProjectError(f"CMakeLists.txt template not found at {template_path}")

        output_path.write_text(content)

    def setup_sdk(self, project_dir: Path) -> bool:
        """
        Set up the max-sdk-base submodule.

        Returns True if SDK is ready, False if setup failed.
        """
        sdk_dir = project_dir / "max-sdk-base"

        if sdk_dir.exists() and (sdk_dir / "script" / "max-pretarget.cmake").exists():
            return True

        # Clone max-sdk-base
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", self.MAX_SDK_REPO, str(sdk_dir)],
                capture_output=True,
                text=True,
                cwd=project_dir,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build Max/MSP external using CMake."""
        cmakelists = project_dir / "CMakeLists.txt"
        if not cmakelists.exists():
            raise BuildError(f"CMakeLists.txt not found in {project_dir}")

        # Ensure max-sdk-base is available
        if not self.setup_sdk(project_dir):
            raise BuildError(
                "Failed to set up max-sdk-base. Please ensure git is installed and run:\n"
                f"  cd {project_dir}\n"
                f"  git clone {self.MAX_SDK_REPO}"
            )

        build_dir = project_dir / "build"

        # Clean if requested
        if clean and build_dir.exists():
            shutil.rmtree(build_dir)

        build_dir.mkdir(exist_ok=True)

        # Configure with CMake using base class run_command
        configure_result = self.run_command(["cmake", ".."], build_dir, verbose=verbose)
        if configure_result.returncode != 0:
            return BuildResult(
                success=False,
                platform="max",
                output_file=None,
                stdout=configure_result.stdout,
                stderr=configure_result.stderr,
                return_code=configure_result.returncode,
            )

        # Build using base class run_command
        build_result = self.run_command(
            ["cmake", "--build", "."], build_dir, verbose=verbose
        )

        # Find output file
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=build_result.returncode == 0,
            platform="max",
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
        """Find the built Max external file."""
        # Check externals directory (where max-posttarget.cmake puts output)
        externals_dir = project_dir / "externals"
        if externals_dir.is_dir():
            # Look for .mxo bundles (macOS) or .mxe64 (Windows)
            for pattern in ["*.mxo", "*.mxe64", "*.mxl*"]:
                for f in externals_dir.glob(pattern):
                    return f

        # Also check build directory
        build_dir = project_dir / "build"
        if build_dir.is_dir():
            for pattern in ["**/*.mxo", "**/*.mxe64", "**/*.mxl*"]:
                for f in build_dir.glob(pattern):
                    return f

        return None
