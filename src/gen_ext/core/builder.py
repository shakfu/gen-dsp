"""
Build orchestration for gen_ext projects.

Invokes the appropriate build system for each platform:
- PureData: make via pd-lib-builder
- Max/MSP: CMake (future)
"""

import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gen_ext.errors import BuildError


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
    """Build gen_ext projects."""

    def __init__(self, project_dir: Path | str):
        """
        Initialize builder with project directory.

        Args:
            project_dir: Path to the gen_ext project directory.
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
            target_platform: 'pd' or 'max'.
            clean: If True, clean before building.
            verbose: If True, print build output in real-time.

        Returns:
            BuildResult with build status and output file path.

        Raises:
            BuildError: If build fails and cannot be recovered.
        """
        if target_platform == "pd":
            return self._build_pd(clean=clean, verbose=verbose)
        elif target_platform == "max":
            return self._build_max(clean=clean, verbose=verbose)
        else:
            raise BuildError(f"Unknown platform: {target_platform}")

    def clean(self, target_platform: str = "pd") -> None:
        """
        Clean build artifacts.

        Args:
            target_platform: 'pd' or 'max'.
        """
        if target_platform == "pd":
            self._run_make(["clean"])
        elif target_platform == "max":
            # CMake clean (future)
            build_dir = self.project_dir / "build"
            if build_dir.exists():
                import shutil

                shutil.rmtree(build_dir)

    def _build_pd(self, clean: bool = False, verbose: bool = False) -> BuildResult:
        """Build PureData external using make."""
        # Check for Makefile
        makefile = self.project_dir / "Makefile"
        if not makefile.exists():
            raise BuildError(f"Makefile not found in {self.project_dir}")

        # Clean if requested
        if clean:
            self._run_make(["clean"])

        # Build
        result = self._run_make(["all"], verbose=verbose)

        # Find output file
        output_file = self._find_pd_output()

        return BuildResult(
            success=result.returncode == 0,
            platform="pd",
            output_file=output_file,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def _build_max(self, clean: bool = False, verbose: bool = False) -> BuildResult:
        """Build Max/MSP external using CMake."""
        from gen_ext.platforms.max import MaxPlatform

        platform = MaxPlatform()
        return platform.build(self.project_dir, clean=clean, verbose=verbose)

    def _run_make(
        self, args: list[str], verbose: bool = False
    ) -> subprocess.CompletedProcess:
        """
        Run make with the given arguments.

        Args:
            args: Arguments to pass to make.
            verbose: If True, print output in real-time.

        Returns:
            CompletedProcess result.
        """
        cmd = ["make"] + args

        if verbose:
            # Run with output streaming
            process = subprocess.Popen(
                cmd,
                cwd=self.project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            output_lines = []
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
                cwd=self.project_dir,
                capture_output=True,
                text=True,
            )

    def _find_pd_output(self) -> Optional[Path]:
        """Find the built PureData external file."""
        # Determine expected extension based on platform
        system = platform.system().lower()
        if system == "darwin":
            ext = ".pd_darwin"
        elif system == "linux":
            ext = ".pd_linux"
        elif system == "windows":
            ext = ".dll"
        else:
            ext = ".pd_linux"  # Default

        # Look for files with the extension
        for f in self.project_dir.glob(f"*{ext}"):
            return f

        # Also check for .d_* variants (older naming)
        if system == "darwin":
            for f in self.project_dir.glob("*.d_fat"):
                return f
            for f in self.project_dir.glob("*.d_amd64"):
                return f
            for f in self.project_dir.glob("*.d_arm64"):
                return f

        return None

    def get_lib_name(self) -> Optional[str]:
        """
        Get the lib.name from the project Makefile.

        Returns:
            The lib.name value or None if not found.
        """
        makefile = self.project_dir / "Makefile"
        if not makefile.exists():
            return None

        content = makefile.read_text()
        import re

        match = re.search(r"lib\.name\s*=\s*(\S+)", content)
        if match:
            return match.group(1)

        return None
