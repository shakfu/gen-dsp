"""
Project generator for gen_dsp.

Creates new project structures from gen~ exports using templates.
Uses the platform registry for platform-specific project generation.
"""

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from gen_dsp.core.parser import ExportInfo
from gen_dsp.errors import ValidationError


@dataclass
class ProjectConfig:
    """Configuration for a new project."""

    # Name for the external (used as lib.name in Makefile)
    name: str

    # Target platform: 'pd', 'max', 'both', or any registered platform
    platform: str = "pd"

    # Buffer names (if empty, use auto-detected from export)
    buffers: list[str] = field(default_factory=list)

    # Whether to apply patches automatically
    apply_patches: bool = True

    # Output directory (if None, use current directory)
    output_dir: Optional[Path] = None

    # Use shared FetchContent cache for CMake-based platforms (clap, vst3)
    shared_cache: bool = False

    def validate(self) -> list[str]:
        """
        Validate the configuration.

        Returns:
            List of validation error messages (empty if valid).
        """
        from gen_dsp.platforms import list_platforms

        errors = []

        # Validate name is a valid C identifier
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", self.name):
            errors.append(
                f"Name '{self.name}' is not a valid C identifier. "
                "Must start with letter/underscore and contain only "
                "alphanumeric characters and underscores."
            )

        # Validate platform
        valid_platforms = list_platforms() + ["both"]
        if self.platform not in valid_platforms:
            errors.append(
                f"Platform must be one of {valid_platforms}, got '{self.platform}'"
            )

        # Validate buffer count
        if len(self.buffers) > 5:
            errors.append(f"Maximum 5 buffers supported, got {len(self.buffers)}")

        # Validate buffer names
        for buf_name in self.buffers:
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", buf_name):
                errors.append(f"Buffer name '{buf_name}' is not a valid C identifier.")

        return errors


class ProjectGenerator:
    """Generate new project from gen~ export."""

    # Version string for generated projects
    GENEXT_VERSION = "0.8.0"

    def __init__(self, export_info: ExportInfo, config: ProjectConfig):
        """
        Initialize generator with export info and configuration.

        Args:
            export_info: Parsed information from gen~ export.
            config: Configuration for the new project.
        """
        self.export_info = export_info
        self.config = config

    def generate(self, output_dir: Optional[Path] = None) -> Path:
        """
        Generate the project.

        Args:
            output_dir: Output directory. If None, uses config.output_dir
                       or creates a directory named after the project.

        Returns:
            Path to the generated project directory.

        Raises:
            ProjectError: If project cannot be generated.
            ValidationError: If configuration is invalid.
        """
        from gen_dsp.platforms import get_platform, list_platforms

        # Validate configuration
        errors = self.config.validate()
        if errors:
            raise ValidationError(
                "Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        # Determine output directory
        if output_dir is None:
            output_dir = self.config.output_dir
        if output_dir is None:
            output_dir = Path.cwd() / self.config.name
        output_dir = Path(output_dir).resolve()

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Determine buffers to use
        buffers = (
            self.config.buffers if self.config.buffers else self.export_info.buffers
        )

        # Generate for each platform using the registry
        if self.config.platform == "both":
            # Generate for all registered platforms
            for platform_name in list_platforms():
                platform_impl = get_platform(platform_name)
                platform_impl.generate_project(
                    self.export_info,
                    output_dir,
                    self.config.name,
                    buffers,
                    config=self.config,
                )
        else:
            # Generate for specific platform
            platform_impl = get_platform(self.config.platform)
            platform_impl.generate_project(
                self.export_info,
                output_dir,
                self.config.name,
                buffers,
                config=self.config,
            )

        # Copy gen~ export
        self._copy_export(output_dir)

        # Apply patches if requested
        if self.config.apply_patches and self.export_info.has_exp2f_issue:
            from gen_dsp.core.patcher import Patcher

            patcher = Patcher(output_dir)
            patcher.apply_exp2f_fix()

        return output_dir

    def _copy_export(self, output_dir: Path) -> None:
        """Copy the gen~ export to the project's gen/ directory."""
        gen_dir = output_dir / "gen"

        # Remove existing gen/ if present
        if gen_dir.exists():
            shutil.rmtree(gen_dir)

        # Copy the export
        shutil.copytree(self.export_info.path, gen_dir)
