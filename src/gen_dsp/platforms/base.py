"""
Abstract base class for platform implementations.

Provides common functionality shared across all platforms.
"""

import re
import subprocess
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Optional

import shutil

from gen_dsp.version import __version__
from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError

if TYPE_CHECKING:
    from gen_dsp.graph.models import Graph


def substitute_strict(template: Template, /, *, label: str, **mapping: object) -> str:
    """Substitute ``$`` placeholders, erroring on undefined or malformed tokens.

    Unlike ``Template.safe_substitute``, an unprovided ``$placeholder`` raises a
    ``ProjectError`` -- catching template-variable typos at generation time
    rather than letting them through into broken build files. Any literal ``$``
    in a template must therefore be written ``$$`` (e.g. make/CMake variables).
    ``label`` identifies the template in error messages.
    """
    try:
        return template.substitute(mapping)
    except KeyError as exc:
        provided = ", ".join(sorted(mapping)) or "none"
        raise ProjectError(
            f"{label}: undefined template variable '${exc.args[0]}' "
            f"(provided: {provided})"
        ) from exc
    except ValueError as exc:
        raise ProjectError(
            f"{label}: malformed '$' token ({exc}); write a literal '$' as '$$'"
        ) from exc


class PluginCategory(Enum):
    """Plugin category based on I/O configuration.

    EFFECT: has audio inputs (processes existing audio)
    GENERATOR: no audio inputs (synthesizes audio)
    """

    EFFECT = "effect"
    GENERATOR = "generator"

    @staticmethod
    def from_num_inputs(num_inputs: int) -> "PluginCategory":
        """Detect category from number of audio inputs."""
        return PluginCategory.EFFECT if num_inputs > 0 else PluginCategory.GENERATOR


class Platform(ABC):
    """Abstract base class for platform implementations."""

    # Platform identifier (e.g., 'pd', 'max')
    name: str = "base"

    # One-line human-readable description (shown by ``gen-dsp list -v``).
    description: str = ""

    # Build system of generated projects, e.g. "CMake", "Make" (shown by
    # ``gen-dsp list -v``).
    build_system: str = ""

    @property
    @abstractmethod
    def extension(self) -> str:
        """File extension for built externals (e.g. '.pd_darwin', '.clap')."""

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

    @abstractmethod
    def clean(self, project_dir: Path) -> None:
        """
        Clean build artifacts for this platform.

        Args:
            project_dir: Path to the project directory.
        """

    @abstractmethod
    def find_output(self, project_dir: Path) -> Optional[Path]:
        """
        Find the built external file.

        Args:
            project_dir: Path to the project directory.

        Returns:
            Path to the built external or None if not found.
        """

    def get_build_instructions(self) -> list[str]:
        """
        Get build instructions for this platform.

        Returns:
            List of command strings to show the user.
        """
        return [f"# Build instructions for {self.name} not available"]

    def list_boards(self) -> list[str]:
        """Return the valid ``--board`` variants for this platform.

        Empty for platforms with no board concept. Embedded platforms (Daisy,
        Circle) override this with their hardware variant keys.
        """
        return []

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

    def copy_voice_alloc_header(
        self, output_dir: Path, config: Optional[ProjectConfig] = None
    ) -> None:
        """Copy voice_alloc.h to output_dir when polyphony is enabled (NUM_VOICES > 1).

        Only copies when the config has a MIDI mapping with num_voices > 1.
        """
        if config is None or config.midi_mapping is None:
            return
        if config.midi_mapping.num_voices <= 1:
            return

        from gen_dsp.templates import get_templates_dir

        src = get_templates_dir("shared") / "voice_alloc.h"
        if src.exists():
            shutil.copy2(src, output_dir / "voice_alloc.h")

    def copy_remap_header(self, output_dir: Path) -> None:
        """Copy gen_remap_inputs.h to output_dir.

        This header is always included by _ext_*.cpp bridges but compiles to
        nothing unless REMAP_INPUT_COUNT is defined, so it is safe to copy
        unconditionally.
        """
        from gen_dsp.templates import get_templates_dir

        src = get_templates_dir("shared") / "gen_remap_inputs.h"
        if src.exists():
            shutil.copy2(src, output_dir / "gen_remap_inputs.h")

    def generate_ext_header(self, output_dir: Path, platform_key: str) -> None:
        """Generate the standard _ext_{platform}.h header from shared template.

        Used by platforms with the identical wrapper interface (all except
        PD, Max, and ChucK which have genuinely different headers).
        """
        from gen_dsp.templates import get_templates_dir

        shared_template = get_templates_dir("shared") / "gen_ext_h.template"
        template = Template(shared_template.read_text(encoding="utf-8"))
        content = substitute_strict(
            template,
            label=f"_ext_{platform_key}.h template",
            platform_upper=platform_key.upper(),
            platform_lower=platform_key,
        )
        (output_dir / f"_ext_{platform_key}.h").write_text(content, encoding="utf-8")

    # -------------------------------------------------------------------------
    # Graph frontend path
    # -------------------------------------------------------------------------

    def generate_from_graph(
        self,
        graph: "Graph",
        manifest: Manifest,
        output_dir: Path,
        name: str,
        config: ProjectConfig,
        midi_defines: str,
    ) -> None:
        """Generate a project from a graph Graph (graph frontend path).

        Provides the orchestration common to every platform: compile the graph
        to C++, emit the platform adapter, copy template files, and write the
        build file. Platform-specific extras (Info.plist, TTL metadata, board
        wrappers, etc.) are produced by the ``_write_graph_platform_files`` hook,
        which each platform overrides as needed. This keeps all knowledge of a
        platform inside its own module, mirroring the export path's
        ``generate_project``.
        """
        from gen_dsp.graph.adapter import (
            _copy_platform_templates,
            _generate_buffer_header,
            generate_adapter_cpp,
            generate_graph_build_file,
        )
        from gen_dsp.graph.compile import compile_graph

        platform = config.platform

        # 1. Compile graph to C++
        (output_dir / f"{graph.name}.cpp").write_text(compile_graph(graph))

        # 2. Generate adapter _ext_{platform}.cpp
        (output_dir / f"_ext_{platform}.cpp").write_text(
            generate_adapter_cpp(graph, platform)
        )

        # 3. Copy platform template files (gen_ext_{platform}.cpp, etc.)
        _copy_platform_templates(output_dir, platform)

        # 4. Generate _ext_{platform}.h if not already provided by the templates
        if not (output_dir / f"_ext_{platform}.h").is_file():
            self.generate_ext_header(output_dir, platform)

        # 5. Generate gen_buffer.h (graph manages its own buffers)
        _generate_buffer_header(output_dir)

        # 6. Copy voice_alloc.h when polyphony is enabled
        self.copy_voice_alloc_header(output_dir, config)

        # 7. Copy platform-specific buffer header if one exists
        import gen_dsp.templates as templates

        getter = getattr(templates, f"get_{platform}_templates_dir", None)
        if getter is not None:
            buf_header = getter() / f"{platform}_buffer.h"
            if buf_header.is_file():
                shutil.copy2(buf_header, output_dir / f"{platform}_buffer.h")

        # 8. Platform-specific extra files (plists, TTL, board wrappers, ...)
        self._write_graph_platform_files(graph, manifest, output_dir, name, config)

        # 9. Generate the simplified build file (no genlib sources)
        generate_graph_build_file(
            output_dir=output_dir,
            platform=platform,
            lib_name=name,
            gen_name=graph.name,
            num_inputs=manifest.num_inputs,
            num_outputs=manifest.num_outputs,
            num_params=manifest.num_params,
            gendsp_version=__version__,
            shared_cache=config.shared_cache,
            midi_defines=midi_defines,
        )

    def _write_graph_platform_files(
        self,
        graph: "Graph",
        manifest: Manifest,
        output_dir: Path,
        name: str,
        config: ProjectConfig,
    ) -> None:
        """Write platform-specific files for the graph path.

        Default implementation writes nothing. Platforms that need extra files
        (e.g. Info.plist, TTL metadata, a board-specific wrapper) override this.
        """
        return None

    # -------------------------------------------------------------------------
    # Shared generation helpers
    # -------------------------------------------------------------------------

    def render_template(
        self,
        template_path: Path,
        output_path: Path,
        *,
        label: str = "Template",
        **substitutions: object,
    ) -> None:
        """Render a ``string.Template`` file to ``output_path``.

        Shared by all platforms in place of per-module reimplementations.
        Substitution values may be any type (``safe_substitute`` stringifies
        them). ``label`` is used only in the not-found error message (e.g. pass
        ``"CMakeLists.txt template"`` to preserve a platform-specific message).
        """
        if not template_path.exists():
            raise ProjectError(f"{label} not found at {template_path}")
        content = substitute_strict(
            Template(template_path.read_text(encoding="utf-8")),
            label=label,
            **substitutions,
        )
        output_path.write_text(content, encoding="utf-8")

    def find_output_by_pattern(
        self,
        base_dir: Path,
        *patterns: str,
        require_dir: bool = False,
        require_file: bool = False,
    ) -> Optional[Path]:
        """Return the first entry under ``base_dir`` matching any glob pattern.

        Patterns are tried in order. ``require_dir``/``require_file`` filter the
        match type. Returns None if ``base_dir`` is not a directory or nothing
        matches. Shared by platforms whose ``find_output`` is a simple glob.
        """
        if not base_dir.is_dir():
            return None
        for pattern in patterns:
            for match in base_dir.glob(pattern):
                if require_dir and not match.is_dir():
                    continue
                if require_file and not match.is_file():
                    continue
                return match
        return None

    @staticmethod
    def capitalize_first(name: str) -> str:
        """Capitalize the first letter of a name (for class-name conventions)."""
        if not name:
            return name
        return name[0].upper() + name[1:]

    @staticmethod
    def sanitize_c_identifier(name: str) -> str:
        """Coerce a name into a valid C identifier.

        Replaces non-alphanumeric characters with underscores and prefixes a
        leading digit with an underscore; falls back to ``"param"`` if empty.
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        if sanitized and sanitized[0].isdigit():
            sanitized = "_" + sanitized
        return sanitized or "param"

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
        for i in range(len(buffers), 8):
            buffer_defs.append(f"// #define WRAPPER_BUFFER_NAME_{i} array{i + 1}")

        if template_path.exists():
            template_content = template_path.read_text(encoding="utf-8")
            content = substitute_strict(
                Template(template_content),
                label="buffer header template",
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
                check=False,
            )
