"""
Web Audio (AudioWorklet + WASM) platform implementation.

Generates Web Audio projects that compile C++ to WASM via Emscripten,
with an AudioWorkletProcessor wrapper for real-time browser audio.
"""

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from gen_dsp.version import __version__
from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest, build_remap_defines_make
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_webaudio_templates_dir

if TYPE_CHECKING:
    from gen_dsp.graph.models import Graph


class WebAudioPlatform(Platform):
    """Web Audio platform implementation using Emscripten (emcc)."""

    name = "webaudio"
    description = "Web Audio (WASM / AudioWorklet)"
    build_system = "Make (emcc)"

    @property
    def extension(self) -> str:
        """Get the file extension for WASM output."""
        return ".wasm"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for Web Audio WASM module."""
        return ["make all"]

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate Web Audio project files."""
        templates_dir = get_webaudio_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"Web Audio templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "_ext_webaudio.cpp",
            "gen_ext_common_webaudio.h",
            "webaudio_buffer.h",
        ]

        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Generate _ext_webaudio.h via shared template
        self.generate_ext_header(output_dir, "webaudio")
        self.copy_remap_header(output_dir)

        # Generate gen_ext_webaudio.cpp from template
        self.render_template(
            templates_dir / "gen_ext_webaudio.cpp.template",
            output_dir / "gen_ext_webaudio.cpp",
            lib_name=lib_name,
            gen_name=manifest.gen_name,
            gendsp_version=__version__,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp Web Audio wrapper",
        )

        # Build input remap compile definitions
        remap_defines = build_remap_defines_make(manifest, "CFLAGS")

        # Generate Makefile from template
        export_name = self._make_export_name(lib_name)
        self.render_template(
            templates_dir / "Makefile.template",
            output_dir / "Makefile",
            lib_name=lib_name,
            gen_name=manifest.gen_name,
            gendsp_version=__version__,
            export_name=export_name,
            remap_defines=remap_defines,
        )

        # Generate _processor.js from template (concatenated with Emscripten
        # glue at build time to produce the final processor.js)
        param_descriptors, processor_class, num_outputs_array = (
            self._build_processor_vars(manifest, lib_name)
        )
        export_name = self._make_export_name(lib_name)
        self._generate_processor_js(
            templates_dir / "processor.js.template",
            output_dir / "_processor.js",
            manifest,
            lib_name,
        )

        # Generate index.html demo page
        self.render_template(
            templates_dir / "index.html.template",
            output_dir / "index.html",
            lib_name=lib_name,
            num_inputs=str(manifest.num_inputs),
            num_outputs=str(manifest.num_outputs),
            num_params=str(len(manifest.params)),
            param_descriptors=json.dumps(param_descriptors, indent=4),
            num_outputs_array=num_outputs_array,
        )

    @staticmethod
    def _make_export_name(lib_name: str) -> str:
        """Build the Emscripten EXPORT_NAME from lib_name.

        E.g. ``"gigaverb"`` -> ``"createGigaverbModule"``.
        """
        capitalized = lib_name[0].upper() + lib_name[1:] if lib_name else lib_name
        return f"create{capitalized}Module"

    @staticmethod
    def _build_processor_vars(
        manifest: Manifest, lib_name: str
    ) -> tuple[list[dict[str, object]], str, str]:
        """Build shared template variables for processor.js and index.html.

        Returns:
            (param_descriptors, processor_class, num_outputs_array)
        """
        param_descriptors: list[dict[str, object]] = []
        for param in manifest.params:
            default = param.default
            if default is not None:
                default = max(param.min, min(param.max, default))
            else:
                default = param.min
            desc: dict[str, object] = {
                "name": param.name,
                "defaultValue": default,
                "minValue": param.min,
                "maxValue": param.max,
                "automationRate": "k-rate",
                "_index": param.index,
            }
            param_descriptors.append(desc)

        processor_class = "".join(
            part.capitalize() for part in lib_name.replace("-", "_").split("_")
        )
        processor_class += "Processor"

        num_outputs_array = ", ".join(["1"] * manifest.num_outputs)
        if manifest.num_outputs == 0:
            num_outputs_array = "1"

        return param_descriptors, processor_class, num_outputs_array

    def _generate_processor_js(
        self,
        template_path: Path,
        output_path: Path,
        manifest: Manifest,
        lib_name: str,
    ) -> None:
        """Generate the AudioWorkletProcessor JavaScript file."""
        param_descriptors, processor_class, num_outputs_array = (
            self._build_processor_vars(manifest, lib_name)
        )
        export_name = self._make_export_name(lib_name)
        self.render_template(
            template_path,
            output_path,
            label="processor.js template",
            lib_name=lib_name,
            gendsp_version=__version__,
            export_name=export_name,
            processor_name=lib_name,
            processor_class=processor_class,
            param_descriptors=json.dumps(param_descriptors, indent=4),
            num_inputs=manifest.num_inputs,
            num_outputs=manifest.num_outputs,
            num_outputs_array=num_outputs_array,
        )

    def _write_graph_platform_files(
        self,
        graph: "Graph",
        manifest: Manifest,
        output_dir: Path,
        name: str,
        config: ProjectConfig,
    ) -> None:
        """Graph path: generate the Emscripten bridge, processor.js, and demo page."""
        tmpl_dir = get_webaudio_templates_dir()

        self.render_template(
            tmpl_dir / "gen_ext_webaudio.cpp.template",
            output_dir / "gen_ext_webaudio.cpp",
            lib_name=name,
            gen_name=graph.name,
            gendsp_version=__version__,
        )

        self._generate_processor_js(
            tmpl_dir / "processor.js.template",
            output_dir / "_processor.js",
            manifest,
            name,
        )

        param_descriptors, _processor_class, num_outputs_array = (
            self._build_processor_vars(manifest, name)
        )
        self.render_template(
            tmpl_dir / "index.html.template",
            output_dir / "index.html",
            lib_name=name,
            num_inputs=str(manifest.num_inputs),
            num_outputs=str(manifest.num_outputs),
            num_params=str(len(manifest.params)),
            param_descriptors=json.dumps(param_descriptors, indent=4),
            num_outputs_array=num_outputs_array,
        )

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build Web Audio WASM module using make (emcc)."""
        makefile = project_dir / "Makefile"
        if not makefile.exists():
            raise BuildError(f"Makefile not found in {project_dir}")

        if clean:
            self.run_command(["make", "clean"], project_dir)

        result = self.run_command(["make", "all"], project_dir, verbose=verbose)
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=result.returncode == 0,
            platform="webaudio",
            output_file=output_file,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        self.run_command(["make", "clean"], project_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built WASM file."""
        return self.find_output_by_pattern(project_dir / "build", "*.wasm")
