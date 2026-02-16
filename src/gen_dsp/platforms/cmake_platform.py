"""
Intermediate base class for CMake-based platform implementations.

Provides shared build(), clean(), get_build_instructions(), and shared cache
resolution that are identical across AU, CLAP, VST3, LV2, SC, and Max.
"""

from pathlib import Path
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.project import ProjectConfig
from gen_dsp.platforms.base import Platform


class CMakePlatform(Platform):
    """Base class for platforms that use CMake as their build system."""

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build project using CMake."""
        return self._build_with_cmake(project_dir, clean, verbose)

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        self._clean_build_dir(project_dir)

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for CMake-based platforms."""
        return ["cmake -B build && cmake --build build"]

    def resolve_shared_cache(
        self, config: Optional[ProjectConfig] = None
    ) -> tuple[str, str]:
        """Resolve shared FetchContent cache settings from config.

        Returns:
            Tuple of (use_shared_cache, cache_dir) where use_shared_cache
            is "ON" or "OFF" and cache_dir is the path string (or empty).
        """
        shared_cache = config is not None and config.shared_cache
        if shared_cache:
            from gen_dsp.core.cache import get_cache_dir

            return "ON", get_cache_dir().as_posix()
        return "OFF", ""
