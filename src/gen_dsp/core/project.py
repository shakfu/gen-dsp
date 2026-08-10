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

from gen_dsp.version import __version__
from gen_dsp.core.parser import ExportInfo
from gen_dsp.errors import ValidationError

# TYPE_CHECKING avoids circular import at runtime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gen_dsp.core.manifest import Manifest
    from gen_dsp.core.midi import MidiMapping
    from gen_dsp.graph.models import Graph
    from gen_dsp.tosc.emit import ToscOptions, ToscResult


@dataclass
class ProjectConfig:
    """Configuration for a new project."""

    # Name for the external (used as lib.name in Makefile)
    name: str

    # Target platform: 'pd', 'max', or any registered platform
    platform: str = "pd"

    # Buffer names (if empty, use auto-detected from export)
    buffers: list[str] = field(default_factory=list)

    # Whether to apply patches automatically
    apply_patches: bool = True

    # Output directory (if None, use current directory)
    output_dir: Optional[Path] = None

    # Use shared FetchContent cache for CMake-based platforms
    shared_cache: bool = True

    # Explicit cache directory override (baked into CMakeLists.txt)
    cache_dir: Optional[Path] = None

    # Board variant for embedded platforms:
    #   Daisy: seed, pod, patch, patch_sm, field, petal, legio, versio
    #   Circle: pi3-i2s, pi4-i2s
    board: Optional[str] = None

    # MIDI-to-CV configuration
    no_midi: bool = False
    midi_gate: Optional[str] = None
    midi_freq: Optional[str] = None
    midi_vel: Optional[str] = None
    midi_freq_unit: str = "hz"
    num_voices: int = 1

    # Signal inputs to remap as parameters.
    # None = don't remap, [] = remap all, ["name", ...] = remap named subset
    inputs_as_params: Optional[list[str]] = None

    # Generate a TouchOSC control surface (requires py2tosc). When the target
    # platform has an OSC path of its own (pd, sc), matching receiver glue is
    # written alongside it.
    tosc: bool = False
    tosc_options: Optional["ToscOptions"] = None

    # Computed MIDI mapping (populated by ProjectGenerator.generate())
    midi_mapping: Optional["MidiMapping"] = None

    def validate(self) -> list[str]:
        """
        Validate the configuration.

        Returns:
            List of validation error messages (empty if valid).
        """
        from gen_dsp.core.identifiers import is_reserved_word
        from gen_dsp.platforms import list_platforms

        errors = []

        # Validate name is a valid C identifier
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", self.name):
            errors.append(
                f"Name '{self.name}' is not a valid C identifier. "
                "Must start with letter/underscore and contain only "
                "alphanumeric characters and underscores."
            )
        elif is_reserved_word(self.name):
            errors.append(
                f"Name '{self.name}' is a C/C++ reserved word and cannot be "
                "used as a plugin name."
            )

        # Validate platform
        valid_platforms = list_platforms()
        if self.platform not in valid_platforms:
            errors.append(
                f"Platform must be one of {valid_platforms}, got '{self.platform}'"
            )

        # Validate buffer count
        if len(self.buffers) > 8:
            errors.append(f"Maximum 8 buffers supported, got {len(self.buffers)}")

        # Validate buffer names
        for buf_name in self.buffers:
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", buf_name):
                errors.append(f"Buffer name '{buf_name}' is not a valid C identifier.")

        # Validate Daisy board name
        if self.board is not None and self.platform == "daisy":
            from gen_dsp.platforms.daisy import DAISY_BOARDS

            if self.board not in DAISY_BOARDS:
                errors.append(
                    f"Unknown Daisy board '{self.board}'. "
                    f"Valid boards: {', '.join(sorted(DAISY_BOARDS))}"
                )

        # Validate Circle board name
        if self.board is not None and self.platform == "circle":
            from gen_dsp.platforms.circle import CIRCLE_BOARDS

            if self.board not in CIRCLE_BOARDS:
                errors.append(
                    f"Unknown Circle board '{self.board}'. "
                    f"Valid boards: {', '.join(sorted(CIRCLE_BOARDS))}"
                )

        return errors

    @staticmethod
    def list_platforms() -> list[str]:
        """Return sorted list of available platform identifiers."""
        from gen_dsp.platforms import list_platforms

        return list_platforms()


class ProjectGenerator:
    """Generate new project from gen~ export or graph."""

    def __init__(self, export_info: ExportInfo, config: ProjectConfig):
        """
        Initialize generator with export info and configuration.

        Args:
            export_info: Parsed information from gen~ export.
            config: Configuration for the new project.
        """
        self.export_info: Optional[ExportInfo] = export_info
        self.config = config
        self._graph: Optional[Graph] = None
        self._manifest: Optional[Manifest] = None
        # Populated by generate() when config.tosc is set, so callers can
        # report exactly which files were written -- or, in tosc_skipped, why
        # no surface was.
        self.tosc_result: Optional["ToscResult"] = None
        self.tosc_skipped: Optional[str] = None

    @classmethod
    def from_graph(cls, graph: "Graph", config: ProjectConfig) -> "ProjectGenerator":
        """Create a ProjectGenerator from a graph Graph object.

        Args:
            graph: A ``gen_dsp.graph.models.Graph`` instance.
            config: Project configuration.

        Returns:
            A ProjectGenerator configured for the graph path.
        """
        from gen_dsp.graph.adapter import generate_manifest_obj

        # Create instance without ExportInfo
        instance = cls.__new__(cls)
        instance.export_info = None
        instance.config = config
        instance._graph = graph
        instance._manifest = generate_manifest_obj(graph)
        instance.tosc_result = None
        instance.tosc_skipped = None
        return instance

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

        if self._graph is not None:
            return self._generate_from_graph(output_dir)
        else:
            return self._generate_from_export(output_dir)

    def _generate_from_export(self, output_dir: Path) -> Path:
        """Generate project from gen~ export (original path)."""
        assert self.export_info is not None
        from gen_dsp.core.manifest import manifest_from_export_info
        from gen_dsp.platforms import get_platform

        # Determine buffers to use
        buffers = (
            self.config.buffers if self.config.buffers else self.export_info.buffers
        )

        # Build manifest
        manifest = manifest_from_export_info(self.export_info, buffers, __version__)

        # Apply input-to-parameter remapping if requested
        if self.config.inputs_as_params is not None:
            from gen_dsp.core.manifest import apply_inputs_as_params

            remap_names = (
                self.config.inputs_as_params if self.config.inputs_as_params else None
            )
            manifest = apply_inputs_as_params(
                manifest, self.export_info.input_names, remap_names
            )

        # Compute MIDI mapping (used by platforms that support MIDI)
        from gen_dsp.core.midi import detect_midi_mapping

        self.config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=self.config.no_midi,
            midi_gate=self.config.midi_gate,
            midi_freq=self.config.midi_freq,
            midi_vel=self.config.midi_vel,
            midi_freq_unit=self.config.midi_freq_unit,
        )
        # Set polyphony voice count on the mapping
        if self.config.midi_mapping.enabled and self.config.num_voices > 1:
            self.config.midi_mapping.num_voices = self.config.num_voices

        # Generate for the target platform using the registry
        platform_impl = get_platform(self.config.platform)
        platform_impl.generate_project(
            manifest,
            output_dir,
            self.config.name,
            config=self.config,
        )

        # Write manifest.json to project root
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(manifest.to_json(), encoding="utf-8")
        self._write_project_marker(output_dir)

        # Copy gen~ export
        self._copy_export(output_dir)

        # Apply patches if requested
        if self.config.apply_patches and self.export_info.has_exp2f_issue:
            from gen_dsp.core.patcher import Patcher

            patcher = Patcher(output_dir)
            patcher.apply_exp2f_fix()

        # Last, so that a TouchOSC failure cannot leave the project itself
        # half-written.
        self._write_tosc(manifest, output_dir)

        return output_dir

    def _generate_from_graph(self, output_dir: Path) -> Path:
        """Generate project from a graph Graph.

        Delegates all platform-specific work to the target platform's
        ``generate_from_graph`` method, keeping this layer free of any
        per-platform branching or graph imports.
        """
        from gen_dsp.core.midi import build_midi_defines, detect_midi_mapping
        from gen_dsp.platforms import get_platform

        assert self._graph is not None
        assert self._manifest is not None
        graph = self._graph
        manifest = self._manifest

        # Compute the MIDI mapping (shared, front-end-agnostic infrastructure).
        self.config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=self.config.no_midi,
            midi_gate=self.config.midi_gate,
            midi_freq=self.config.midi_freq,
            midi_vel=self.config.midi_vel,
            midi_freq_unit=self.config.midi_freq_unit,
        )
        if self.config.midi_mapping.enabled and self.config.num_voices > 1:
            self.config.midi_mapping.num_voices = self.config.num_voices
        midi_defines = build_midi_defines(self.config.midi_mapping)

        # Generate the project for the target platform.
        platform_impl = get_platform(self.config.platform)
        platform_impl.generate_from_graph(
            graph,
            manifest,
            output_dir,
            self.config.name,
            self.config,
            midi_defines,
        )

        # Write manifest.json to project root.
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(manifest.to_json(), encoding="utf-8")
        self._write_project_marker(output_dir)
        self._write_tosc(manifest, output_dir)

        return output_dir

    def _write_tosc(self, manifest: "Manifest", output_dir: Path) -> None:
        """Write the TouchOSC surface and receiver glue, if requested.

        The two ways this can fail are not equally serious. A missing py2tosc
        means ``--tosc`` cannot be honoured at all, which is a configuration
        problem the user has to fix, so it is raised as a project error. A
        plugin with no parameters simply has nothing to put on a surface --
        the project around it is perfectly good, so the reason is recorded in
        ``tosc_skipped`` for the caller to report and generation continues.
        """
        if not self.config.tosc:
            return

        from gen_dsp.errors import ProjectError, ValidationError
        from gen_dsp.tosc.emit import emit

        try:
            self.tosc_result = emit(
                manifest,
                output_dir,
                self.config.name,
                platform=self.config.platform,
                options=self.config.tosc_options,
            )
        except ImportError as e:
            raise ProjectError(str(e)) from e
        except ValidationError as e:
            self.tosc_skipped = str(e)

    def _write_project_marker(self, output_dir: Path) -> None:
        """Write ``.gen-dsp.json`` recording the target platform and name.

        Lets ``gen-dsp build`` auto-detect the platform of an existing project
        without an explicit ``-p``, and ``gen-dsp tosc`` recover the name the
        project was generated under (which is the user's ``-n``, not the gen~
        export's internal ``gen_name``). Kept separate from ``manifest.json``
        (the front-end-agnostic IR) because both are output concerns, not part
        of the manifest.
        """
        import json

        marker: dict[str, str] = {
            "tool": "gen-dsp",
            "version": __version__,
            "platform": self.config.platform,
            "name": self.config.name,
        }
        if self.config.board is not None:
            marker["board"] = self.config.board
        (output_dir / ".gen-dsp.json").write_text(
            json.dumps(marker, indent=2) + "\n", encoding="utf-8"
        )

    def _copy_export(self, output_dir: Path) -> None:
        """Copy the gen~ export to the project's gen/ directory."""
        assert self.export_info is not None
        gen_dir = output_dir / "gen"

        # Remove existing gen/ if present
        if gen_dir.exists():
            shutil.rmtree(gen_dir)

        # Copy the export
        shutil.copytree(self.export_info.path, gen_dir)
