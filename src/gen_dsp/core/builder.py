"""
Build orchestration for gen_dsp projects.

Uses the platform registry to dynamically select the appropriate
build system for each platform.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gen_dsp.errors import BuildError


@dataclass
class BuildResult:
    """Result of a build operation."""

    success: bool
    platform: str
    output_file: Optional[Path]
    stdout: str
    stderr: str
    return_code: int

    def __repr__(self) -> str:
        status = "success" if self.success else "failed"
        output = f" -> {self.output_file}" if self.output_file else ""
        return f"BuildResult({self.platform}: {status}{output})"


class Builder:
    """Build gen_dsp projects."""

    def __init__(self, project_dir: Path | str):
        """
        Initialize builder with project directory.

        Args:
            project_dir: Path to the gen_dsp project directory.
        """
        self.project_dir = Path(project_dir).resolve()

        if not self.project_dir.is_dir():
            raise BuildError(f"Project directory not found: {self.project_dir}")

    def build(
        self,
        target_platform: str = "pd",
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """
        Build the project for the specified platform.

        Args:
            target_platform: Platform name (e.g., 'pd', 'max').
            clean: If True, clean before building.
            verbose: If True, print build output in real-time.

        Returns:
            BuildResult with build status and output file path.

        Raises:
            BuildError: If build fails and cannot be recovered.
            ValueError: If platform is not recognized.
        """
        from gen_dsp.platforms import get_platform

        try:
            platform_impl = get_platform(target_platform)
        except ValueError as e:
            raise BuildError(str(e)) from e

        return platform_impl.build(self.project_dir, clean=clean, verbose=verbose)

    def clean(self, target_platform: str = "pd") -> None:
        """
        Clean build artifacts.

        Args:
            target_platform: Platform name (e.g., 'pd', 'max').
        """
        from gen_dsp.platforms import get_platform

        try:
            platform_impl = get_platform(target_platform)
        except ValueError as e:
            raise BuildError(str(e)) from e

        platform_impl.clean(self.project_dir)

    def get_lib_name(self) -> Optional[str]:
        """
        Get the lib.name from the project Makefile.

        Returns:
            The lib.name value or None if not found.
        """
        makefile = self.project_dir / "Makefile"
        if not makefile.exists():
            return None

        content = makefile.read_text(encoding="utf-8")

        match = re.search(r"lib\.name\s*=\s*(\S+)", content)
        if match:
            return match.group(1)

        return None
