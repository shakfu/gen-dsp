"""
LV2 plugin platform implementation.

Generates cross-platform LV2 plugins (.lv2 bundle directories) using CMake
and the LV2 C API (header-only, ISC licensed). LV2 headers are fetched
at configure time via CMake FetchContent.

LV2 bundles contain:
  - manifest.ttl  (plugin discovery metadata)
  - <name>.ttl    (port definitions: control + audio)
  - <name>.so/.dylib (shared library)
"""

import re
import shutil
import sys
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.manifest import Manifest, ParamInfo
from gen_dsp.core.midi import build_midi_defines
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import ProjectError
from gen_dsp.platforms.base import PluginCategory
from gen_dsp.platforms.cmake_platform import CMakePlatform
from gen_dsp.templates import get_lv2_templates_dir


class Lv2Platform(CMakePlatform):
    """LV2 plugin platform implementation using CMake."""

    name = "lv2"
    LV2_URI_BASE = "http://gen-dsp.com/plugins"

    _LV2_TYPE_MAP = {
        PluginCategory.EFFECT: "lv2:Plugin ,\n      lv2:EffectPlugin",
        PluginCategory.GENERATOR: "lv2:Plugin ,\n      lv2:GeneratorPlugin",
    }

    LV2_TYPE_INSTRUMENT = "lv2:Plugin ,\n      lv2:InstrumentPlugin"

    @property
    def extension(self) -> str:
        """Get the extension for LV2 bundles."""
        return ".lv2"

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate LV2 project files."""
        templates_dir = get_lv2_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"LV2 templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "gen_ext_lv2.cpp",
            "gen_ext_common_lv2.h",
            "_ext_lv2.cpp",
            "lv2_buffer.h",
        ]
        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        self.generate_ext_header(output_dir, "lv2")
        self.copy_voice_alloc_header(output_dir, config)

        # Build MIDI compile definitions
        midi_mapping = config.midi_mapping if config else None
        midi_enabled = midi_mapping is not None and midi_mapping.enabled
        midi_defines = build_midi_defines(midi_mapping)

        # Generate TTL files
        plugin_uri = f"{self.LV2_URI_BASE}/{lib_name}"
        self._generate_manifest_ttl(output_dir, lib_name, plugin_uri)
        self._generate_plugin_ttl(
            output_dir,
            lib_name,
            plugin_uri,
            manifest.num_inputs,
            manifest.num_outputs,
            manifest.num_params,
            manifest.params,
            midi_enabled=midi_enabled,
        )

        # Resolve shared cache settings
        use_shared_cache, cache_dir = self.resolve_shared_cache(config)

        # Generate CMakeLists.txt
        self._generate_cmakelists(
            templates_dir / "CMakeLists.txt.template",
            output_dir / "CMakeLists.txt",
            manifest.gen_name,
            lib_name,
            manifest.num_inputs,
            manifest.num_outputs,
            manifest.num_params,
            use_shared_cache=use_shared_cache,
            cache_dir=cache_dir,
            midi_defines=midi_defines,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp LV2 wrapper",
        )

        # Create build directory
        (output_dir / "build").mkdir(exist_ok=True)

    def _generate_manifest_ttl(
        self,
        output_dir: Path,
        lib_name: str,
        plugin_uri: str,
    ) -> None:
        """Generate manifest.ttl for LV2 plugin discovery."""
        if sys.platform == "darwin":
            binary_ext = "dylib"
        elif sys.platform == "win32":
            binary_ext = "dll"
        else:
            binary_ext = "so"

        content = (
            "@prefix lv2:  <http://lv2plug.in/ns/lv2core#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "\n"
            f"<{plugin_uri}>\n"
            "    a lv2:Plugin ;\n"
            f"    lv2:binary <{lib_name}.{binary_ext}> ;\n"
            f"    rdfs:seeAlso <{lib_name}.ttl> .\n"
        )
        (output_dir / "manifest.ttl").write_text(content, encoding="utf-8")

    def _generate_plugin_ttl(
        self,
        output_dir: Path,
        lib_name: str,
        plugin_uri: str,
        num_inputs: int,
        num_outputs: int,
        num_params: int,
        params: list[ParamInfo],
        midi_enabled: bool = False,
    ) -> None:
        """Generate <plugin>.ttl with full port descriptions.

        Port layout matches the C++ code:
          indices 0..num_params-1   = ControlPort InputPort
          indices num_params..+nin  = AudioPort InputPort
          indices above..+nout      = AudioPort OutputPort
          (if MIDI) last index      = AtomPort InputPort (MIDI events)
        """
        # Plugin type
        if midi_enabled:
            plugin_type = self.LV2_TYPE_INSTRUMENT
        else:
            category = PluginCategory.from_num_inputs(num_inputs)
            plugin_type = self._LV2_TYPE_MAP[category]

        prefixes = [
            "@prefix doap:  <http://usefulinc.com/ns/doap#> .",
            "@prefix lv2:   <http://lv2plug.in/ns/lv2core#> .",
            "@prefix state: <http://lv2plug.in/ns/ext/state#> .",
            "@prefix urid:  <http://lv2plug.in/ns/ext/urid#> .",
        ]
        if midi_enabled:
            prefixes.append("@prefix atom: <http://lv2plug.in/ns/ext/atom#> .")
            prefixes.append("@prefix midi: <http://lv2plug.in/ns/ext/midi#> .")

        lines = prefixes + [
            "",
            f"<{plugin_uri}>",
            f"    a {plugin_type} ;",
            f'    doap:name "{lib_name}" ;',
            "    doap:license <http://opensource.org/licenses/isc> ;",
            "    lv2:optionalFeature lv2:hardRTCapable ;",
            "    lv2:extensionData state:interface ;",
        ]

        if midi_enabled:
            lines.append("    lv2:requiredFeature urid:map ;")

        total_ports = num_params + num_inputs + num_outputs
        if midi_enabled:
            total_ports += 1  # atom port for MIDI
        port_index = 0

        # Control input ports (parameters)
        for i in range(num_params):
            # Use parsed param info if available, else generic
            if i < len(params):
                p = params[i]
                symbol = self._sanitize_symbol(p.name)
                pname = p.name
                pmin = p.min
                pmax = p.max
                pdefault = p.default
            else:
                symbol = f"param_{i}"
                pname = f"Parameter {i}"
                pmin = 0.0
                pmax = 1.0
                pdefault = 0.0

            is_last = port_index == total_ports - 1
            terminator = " ." if is_last else " ;"

            lines.append("    lv2:port [")
            lines.append("        a lv2:InputPort , lv2:ControlPort ;")
            lines.append(f"        lv2:index {port_index} ;")
            lines.append(f'        lv2:symbol "{symbol}" ;')
            lines.append(f'        lv2:name "{pname}" ;')
            lines.append(f"        lv2:default {pdefault} ;")
            lines.append(f"        lv2:minimum {pmin} ;")
            lines.append(f"        lv2:maximum {pmax}")
            lines.append(f"    ]{terminator}")
            port_index += 1

        # Audio input ports
        for i in range(num_inputs):
            is_last = port_index == total_ports - 1
            terminator = " ." if is_last else " ;"

            lines.append("    lv2:port [")
            lines.append("        a lv2:InputPort , lv2:AudioPort ;")
            lines.append(f"        lv2:index {port_index} ;")
            lines.append(f'        lv2:symbol "in{i}" ;')
            lines.append(f'        lv2:name "Input {i}"')
            lines.append(f"    ]{terminator}")
            port_index += 1

        # Audio output ports
        for i in range(num_outputs):
            is_last = port_index == total_ports - 1
            terminator = " ." if is_last else " ;"

            lines.append("    lv2:port [")
            lines.append("        a lv2:OutputPort , lv2:AudioPort ;")
            lines.append(f"        lv2:index {port_index} ;")
            lines.append(f'        lv2:symbol "out{i}" ;')
            lines.append(f'        lv2:name "Output {i}"')
            lines.append(f"    ]{terminator}")
            port_index += 1

        # MIDI atom input port (appended at the end)
        if midi_enabled:
            lines.append("    lv2:port [")
            lines.append("        a lv2:InputPort , atom:AtomPort ;")
            lines.append(f"        lv2:index {port_index} ;")
            lines.append('        lv2:symbol "midi_in" ;')
            lines.append('        lv2:name "MIDI In" ;')
            lines.append("        atom:bufferType atom:Sequence ;")
            lines.append("        atom:supports midi:MidiEvent")
            lines.append("    ] .")
            port_index += 1

        content = "\n".join(lines) + "\n"
        (output_dir / f"{lib_name}.ttl").write_text(content, encoding="utf-8")

    @staticmethod
    def _sanitize_symbol(name: str) -> str:
        """Ensure a parameter name is a valid LV2 symbol (C identifier)."""
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        if sanitized and sanitized[0].isdigit():
            sanitized = "_" + sanitized
        return sanitized or "param"

    def _generate_cmakelists(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
        num_inputs: int,
        num_outputs: int,
        num_params: int,
        use_shared_cache: str = "OFF",
        cache_dir: str = "",
        midi_defines: str = "",
    ) -> None:
        """Generate CMakeLists.txt from template."""
        if not template_path.exists():
            raise ProjectError(f"CMakeLists.txt template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)
        content = template.safe_substitute(
            gen_name=gen_name,
            lib_name=lib_name,
            genext_version=self.GENEXT_VERSION,
            num_inputs=num_inputs,
            num_outputs=num_outputs,
            num_params=num_params,
            use_shared_cache=use_shared_cache,
            cache_dir=cache_dir,
            midi_defines=midi_defines,
        )
        output_path.write_text(content, encoding="utf-8")

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built LV2 bundle directory."""
        build_dir = project_dir / "build"
        if build_dir.is_dir():
            for f in build_dir.glob("**/*.lv2"):
                if f.is_dir():
                    return f
        return None
