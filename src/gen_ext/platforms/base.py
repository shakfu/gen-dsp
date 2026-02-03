"""
Abstract base class for platform implementations.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from gen_ext.core.parser import ExportInfo
from gen_ext.core.builder import BuildResult


class Platform(ABC):
    """Abstract base class for platform implementations."""

    # Platform identifier
    name: str = "base"

    # File extension for built externals
    extension: str = ""

    @abstractmethod
    def generate_project(
        self,
        export_info: ExportInfo,
        output_dir: Path,
        lib_name: str,
        buffers: list[str],
    ) -> None:
        """
        Generate project files for this platform.

        Args:
            export_info: Parsed gen~ export information.
            output_dir: Directory to generate project in.
            lib_name: Name for the external library.
            buffers: List of buffer names to configure.
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
