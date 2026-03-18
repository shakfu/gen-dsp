"""
Audio Unit v3 (AUv3) platform implementation.

Generates macOS AUv3 plugins as App Extensions (.appex) inside a host
application (.app). Uses cmake -G Xcode to produce the nested bundle
structure required by PluginKit for system-wide AU discovery.

Requires: macOS, Xcode (for the Xcode CMake generator), CMake >= 3.19.
"""

import platform as sys_platform
import shutil
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest, build_remap_defines
from gen_dsp.core.midi import build_midi_defines
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform, PluginCategory
from gen_dsp.templates import get_auv3_templates_dir


class Auv3Platform(Platform):
    """Audio Unit v3 platform using CMake Xcode generator."""

    name = "auv3"

    AU_MANUFACTURER = "Gdsp"

    _AU_TYPE_MAP = {
        PluginCategory.EFFECT: "aufx",
        PluginCategory.GENERATOR: "augn",
    }
    AU_TYPE_MUSIC_DEVICE = "aumu"

    _AU_TAG_MAP = {
        PluginCategory.EFFECT: "Effects",
        PluginCategory.GENERATOR: "Synthesizer",
    }

    @property
    def extension(self) -> str:
        return ".app"

    def get_build_instructions(self) -> list[str]:
        return [
            "cmake -G Xcode -B build",
            "cmake --build build --config Release",
        ]

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        templates_dir = get_auv3_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"AUv3 templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "gen_ext_auv3.mm",
            "_ext_auv3.cpp",
            "gen_ext_common_auv3.h",
            "auv3_buffer.h",
        ]
        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        self.generate_ext_header(output_dir, "auv3")
        self.copy_remap_header(output_dir)
        self.copy_voice_alloc_header(output_dir, config)

        # Detect AU type
        category = PluginCategory.from_num_inputs(manifest.num_inputs)
        au_type = self._AU_TYPE_MAP[category]
        au_tag = self._AU_TAG_MAP[category]
        au_subtype = self._generate_subtype(lib_name)

        midi_mapping = config.midi_mapping if config else None
        midi_defines = build_midi_defines(midi_mapping)
        remap_defines = build_remap_defines(manifest)

        if midi_mapping and midi_mapping.enabled:
            au_type = self.AU_TYPE_MUSIC_DEVICE
            au_tag = "Synthesizer"

        # Generate CMakeLists.txt
        self._render_template(
            templates_dir / "CMakeLists.txt.template",
            output_dir / "CMakeLists.txt",
            lib_name=lib_name,
            gen_name=manifest.gen_name,
            genext_version=self.GENEXT_VERSION,
            num_inputs=str(manifest.num_inputs),
            num_outputs=str(manifest.num_outputs),
            midi_defines=midi_defines,
            remap_defines=remap_defines,
        )

        # Generate Info plists
        plist_vars = dict(
            lib_name=lib_name,
            genext_version=self.GENEXT_VERSION,
            au_type=au_type,
            au_subtype=au_subtype,
            au_manufacturer=self.AU_MANUFACTURER,
            au_version=str(self._version_to_int(self.GENEXT_VERSION)),
            au_tag=au_tag,
        )
        self._render_template(
            templates_dir / "Info-AUv3.plist.template",
            output_dir / "Info-AUv3.plist",
            **plist_vars,
        )
        self._render_template(
            templates_dir / "Info-App.plist.template",
            output_dir / "Info-App.plist",
            **plist_vars,
        )

        # Generate gen_buffer.h
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp AUv3 wrapper",
        )

        (output_dir / "build").mkdir(exist_ok=True)

    def _generate_subtype(self, lib_name: str) -> str:
        code = lib_name.lower()[:4]
        return code.ljust(4, "x")

    @staticmethod
    def _version_to_int(version_str: str) -> int:
        parts = version_str.split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major << 16) | (minor << 8) | patch

    def _render_template(
        self, template_path: Path, output_path: Path, **subs: str
    ) -> None:
        if not template_path.exists():
            raise ProjectError(f"Template not found at {template_path}")
        content = Template(
            template_path.read_text(encoding="utf-8")
        ).safe_substitute(**subs)
        output_path.write_text(content, encoding="utf-8")

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        if sys_platform.system() != "Darwin":
            raise BuildError("AUv3 plugins can only be built on macOS")

        build_dir = project_dir / "build"

        if clean and build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(exist_ok=True)

        # Configure with Xcode generator
        configure = self.run_command(
            ["cmake", "-G", "Xcode", ".."], build_dir, verbose=verbose
        )
        if configure.returncode != 0:
            return BuildResult(
                success=False, platform=self.name, output_file=None,
                stdout=configure.stdout, stderr=configure.stderr,
                return_code=configure.returncode,
            )

        # Build
        result = self.run_command(
            ["cmake", "--build", ".", "--config", "Release"],
            build_dir, verbose=verbose,
        )
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=result.returncode == 0, platform=self.name,
            output_file=output_file, stdout=result.stdout,
            stderr=result.stderr, return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        build_dir = project_dir / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        build_dir = project_dir / "build"
        if build_dir.is_dir():
            # The host .app contains the .appex
            for f in build_dir.glob("**/*-Host.app"):
                return f
        return None
