"""
Project generator for gen_ext.

Creates new project structures from gen~ exports using templates.
"""

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Optional

from gen_ext.core.parser import ExportInfo
from gen_ext.errors import ProjectError, ValidationError


@dataclass
class ProjectConfig:
    """Configuration for a new project."""

    # Name for the external (used as lib.name in Makefile)
    name: str

    # Target platform: 'pd', 'max', or 'both'
    platform: str = "pd"

    # Buffer names (if empty, use auto-detected from export)
    buffers: list[str] = field(default_factory=list)

    # Whether to apply patches automatically
    apply_patches: bool = True

    # Output directory (if None, use current directory)
    output_dir: Optional[Path] = None

    def validate(self) -> list[str]:
        """
        Validate the configuration.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []

        # Validate name is a valid C identifier
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", self.name):
            errors.append(
                f"Name '{self.name}' is not a valid C identifier. "
                "Must start with letter/underscore and contain only "
                "alphanumeric characters and underscores."
            )

        # Validate platform
        if self.platform not in ("pd", "max", "both"):
            errors.append(f"Platform must be 'pd', 'max', or 'both', got '{self.platform}'")

        # Validate buffer count
        if len(self.buffers) > 5:
            errors.append(f"Maximum 5 buffers supported, got {len(self.buffers)}")

        # Validate buffer names
        for buf_name in self.buffers:
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", buf_name):
                errors.append(
                    f"Buffer name '{buf_name}' is not a valid C identifier."
                )

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
        self._templates_dir: Optional[Path] = None

    @property
    def templates_dir(self) -> Path:
        """Get the templates directory from the package."""
        if self._templates_dir is None:
            # Import here to avoid circular imports
            from gen_ext.templates import get_templates_dir

            self._templates_dir = get_templates_dir()
        return self._templates_dir

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
        # Validate configuration
        errors = self.config.validate()
        if errors:
            raise ValidationError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))

        # Determine output directory
        if output_dir is None:
            output_dir = self.config.output_dir
        if output_dir is None:
            output_dir = Path.cwd() / self.config.name
        output_dir = Path(output_dir).resolve()

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Determine buffers to use
        buffers = self.config.buffers if self.config.buffers else self.export_info.buffers

        # Generate for each platform
        if self.config.platform in ("pd", "both"):
            self._generate_pd(output_dir, buffers)

        if self.config.platform in ("max", "both"):
            self._generate_max(output_dir, buffers)

        # Copy gen~ export
        self._copy_export(output_dir)

        # Apply patches if requested
        if self.config.apply_patches and self.export_info.has_exp2f_issue:
            from gen_ext.core.patcher import Patcher

            patcher = Patcher(output_dir)
            patcher.apply_exp2f_fix()

        return output_dir

    def _generate_pd(self, output_dir: Path, buffers: list[str]) -> None:
        """Generate PureData project files."""
        pd_templates = self.templates_dir / "pd"
        if not pd_templates.is_dir():
            raise ProjectError(f"PureData templates not found at {pd_templates}")

        # Copy static files
        static_files = [
            "gen_ext.cpp",
            "gen_ext_common.h",
            "_ext.cpp",
            "_ext.h",
            "pd_buffer.h",
        ]

        for filename in static_files:
            src = pd_templates / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Copy pd-lib-builder
        pd_lib_builder_src = pd_templates / "pd-lib-builder"
        pd_lib_builder_dst = output_dir / "pd-lib-builder"
        if pd_lib_builder_src.is_dir():
            if pd_lib_builder_dst.exists():
                shutil.rmtree(pd_lib_builder_dst)
            shutil.copytree(pd_lib_builder_src, pd_lib_builder_dst)

        # Generate Makefile from template
        makefile_template = pd_templates / "Makefile.template"
        if makefile_template.exists():
            self._generate_makefile(makefile_template, output_dir / "Makefile")
        else:
            # Fallback: generate Makefile directly
            self._generate_makefile_direct(output_dir / "Makefile")

        # Generate gen_buffer.h from template
        buffer_template = pd_templates / "gen_buffer.h.template"
        if buffer_template.exists():
            self._generate_buffer_header(buffer_template, output_dir / "gen_buffer.h", buffers)
        else:
            # Fallback: generate gen_buffer.h directly
            self._generate_buffer_header_direct(output_dir / "gen_buffer.h", buffers)

    def _generate_max(self, output_dir: Path, buffers: list[str]) -> None:
        """Generate Max/MSP project files."""
        from gen_ext.platforms.max import MaxPlatform

        platform = MaxPlatform()
        platform.generate_project(
            self.export_info,
            output_dir,
            self.config.name,
            buffers,
        )

    def _copy_export(self, output_dir: Path) -> None:
        """Copy the gen~ export to the project's gen/ directory."""
        gen_dir = output_dir / "gen"

        # Remove existing gen/ if present
        if gen_dir.exists():
            shutil.rmtree(gen_dir)

        # Copy the export
        shutil.copytree(self.export_info.path, gen_dir)

    def _generate_makefile(self, template_path: Path, output_path: Path) -> None:
        """Generate Makefile from template."""
        template_content = template_path.read_text()
        template = Template(template_content)

        content = template.safe_substitute(
            gen_name=self.export_info.name,
            lib_name=self.config.name,
            genext_version=self.GENEXT_VERSION,
        )

        output_path.write_text(content)

    def _generate_makefile_direct(self, output_path: Path) -> None:
        """Generate Makefile directly (fallback)."""
        content = f"""# Makefile for {self.config.name}

# Name of the exported .cpp/.h file from gen~
gen.name = {self.export_info.name}

# Name of the external to generate (do not add ~ suffix)
lib.name = {self.config.name}

genext.version = {self.GENEXT_VERSION}

$(lib.name)~.class.sources = gen_ext.cpp _ext.cpp ./gen/gen_dsp/genlib.cpp
cflags = -I ./gen -I./gen/gen_dsp -DGEN_EXT_VERSION=$(genext.version) -DPD_EXT_NAME=$(lib.name) -DGEN_EXPORTED_NAME=$(gen.name) -DGEN_EXPORTED_HEADER=\\"$(gen.name).h\\" -DGEN_EXPORTED_CPP=\\"$(gen.name).cpp\\"
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

    def _generate_buffer_header(
        self, template_path: Path, output_path: Path, buffers: list[str]
    ) -> None:
        """Generate gen_buffer.h from template."""
        template_content = template_path.read_text()
        template = Template(template_content)

        # Build buffer definitions
        buffer_count = len(buffers)
        buffer_defs = []
        for i, buf_name in enumerate(buffers):
            buffer_defs.append(f"#define WRAPPER_BUFFER_NAME_{i} {buf_name}")

        # Pad with commented-out placeholders
        for i in range(len(buffers), 5):
            buffer_defs.append(f"// #define WRAPPER_BUFFER_NAME_{i} array{i + 1}")

        content = template.safe_substitute(
            buffer_count=buffer_count,
            buffer_definitions="\n".join(buffer_defs),
        )

        output_path.write_text(content)

    def _generate_buffer_header_direct(
        self, output_path: Path, buffers: list[str]
    ) -> None:
        """Generate gen_buffer.h directly (fallback)."""
        buffer_count = len(buffers)

        lines = [
            "// Buffer configuration for gen_ext wrapper",
            "// Auto-generated by gen-ext",
            "",
            f"#define WRAPPER_BUFFER_COUNT {buffer_count}",
            "",
        ]

        for i in range(5):
            if i < len(buffers):
                lines.append(f"#define WRAPPER_BUFFER_NAME_{i} {buffers[i]}")
            else:
                lines.append(f"// #define WRAPPER_BUFFER_NAME_{i} array{i + 1}")

        output_path.write_text("\n".join(lines) + "\n")
