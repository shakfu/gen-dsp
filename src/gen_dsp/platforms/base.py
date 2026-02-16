"""
Abstract base class for platform implementations.

Provides common functionality shared across all platforms.
"""

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from string import Template
from typing import Optional

import shutil

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError


class Platform(ABC):
    """Abstract base class for platform implementations."""

    # Platform identifier (e.g., 'pd', 'max')
    name: str = "base"

    @property
    @abstractmethod
    def extension(self) -> str:
        """File extension for built externals (e.g. '.pd_darwin', '.clap')."""
        ...

    # Version string for generated projects
    GENEXT_VERSION = "0.8.0"

    @abstractmethod
    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """
        Generate project files for this platform.

        Args:
            manifest: Front-end-agnostic manifest with I/O, params, buffers.
            output_dir: Directory to generate project in.
            lib_name: Name for the external library.
            config: Optional ProjectConfig for platform-specific options.
        """
        pass

    @abstractmethod
    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """
        Build the project for this platform.

        Args:
            project_dir: Path to the project directory.
            clean: If True, clean before building.
            verbose: If True, print build output.

        Returns:
            BuildResult with build status and output file.
        """
        pass

    @abstractmethod
    def clean(self, project_dir: Path) -> None:
        """
        Clean build artifacts for this platform.

        Args:
            project_dir: Path to the project directory.
        """
        pass

    @abstractmethod
    def find_output(self, project_dir: Path) -> Optional[Path]:
        """
        Find the built external file.

        Args:
            project_dir: Path to the project directory.

        Returns:
            Path to the built external or None if not found.
        """
        pass

    def get_build_instructions(self) -> list[str]:
        """
        Get build instructions for this platform.

        Returns:
            List of command strings to show the user.
        """
        return [f"# Build instructions for {self.name} not available"]

    # -------------------------------------------------------------------------
    # Common utility methods shared by all platforms
    # -------------------------------------------------------------------------

    def _build_with_cmake(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build a project using CMake (configure + build).

        Shared by all CMake-based platforms (AU, CLAP, VST3, LV2, SC, Max).
        """
        cmakelists = project_dir / "CMakeLists.txt"
        if not cmakelists.exists():
            raise BuildError(f"CMakeLists.txt not found in {project_dir}")

        build_dir = project_dir / "build"

        if clean and build_dir.exists():
            shutil.rmtree(build_dir)

        build_dir.mkdir(exist_ok=True)

        configure_result = self.run_command(["cmake", ".."], build_dir, verbose=verbose)
        if configure_result.returncode != 0:
            return BuildResult(
                success=False,
                platform=self.name,
                output_file=None,
                stdout=configure_result.stdout,
                stderr=configure_result.stderr,
                return_code=configure_result.returncode,
            )

        build_result = self.run_command(
            ["cmake", "--build", "."], build_dir, verbose=verbose
        )

        output_file = self.find_output(project_dir)

        return BuildResult(
            success=build_result.returncode == 0,
            platform=self.name,
            output_file=output_file,
            stdout=build_result.stdout,
            stderr=build_result.stderr,
            return_code=build_result.returncode,
        )

    def _clean_build_dir(self, project_dir: Path) -> None:
        """Remove the build/ subdirectory. Shared by all CMake-based platforms."""
        build_dir = project_dir / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir)

    def generate_buffer_header(
        self,
        template_path: Path,
        output_path: Path,
        buffers: list[str],
        header_comment: str = "Buffer configuration for gen_dsp wrapper",
    ) -> None:
        """
        Generate gen_buffer.h from template.

        This is a common operation across all platforms with identical logic.

        Args:
            template_path: Path to the template file.
            output_path: Path to write the generated header.
            buffers: List of buffer names.
            header_comment: Comment to include in fallback generation.
        """
        buffer_count = len(buffers)

        # Build buffer definitions
        buffer_defs = []
        for i, buf_name in enumerate(buffers):
            buffer_defs.append(f"#define WRAPPER_BUFFER_NAME_{i} {buf_name}")

        # Pad with commented-out placeholders
        for i in range(len(buffers), 5):
            buffer_defs.append(f"// #define WRAPPER_BUFFER_NAME_{i} array{i + 1}")

        if template_path.exists():
            template_content = template_path.read_text(encoding="utf-8")
            template = Template(template_content)
            content = template.safe_substitute(
                buffer_count=buffer_count,
                buffer_definitions="\n".join(buffer_defs),
            )
        else:
            # Fallback: generate directly
            lines = [
                f"// {header_comment}",
                "// Auto-generated by gen-dsp",
                "",
                f"#define WRAPPER_BUFFER_COUNT {buffer_count}",
                "",
            ]
            lines.extend(buffer_defs)
            content = "\n".join(lines) + "\n"

        output_path.write_text(content, encoding="utf-8")

    def run_command(
        self,
        cmd: list[str],
        cwd: Path,
        verbose: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """
        Run a subprocess command with optional output streaming.

        This provides a consistent way to run build commands across platforms.

        Args:
            cmd: Command and arguments to run.
            cwd: Working directory for the command.
            verbose: If True, stream output in real-time.

        Returns:
            CompletedProcess with captured output.
        """
        if verbose:
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            output_lines = []
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="")
                output_lines.append(line)

            process.wait()

            return subprocess.CompletedProcess(
                args=cmd,
                returncode=process.returncode,
                stdout="".join(output_lines),
                stderr="",
            )
        else:
            return subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
            )
