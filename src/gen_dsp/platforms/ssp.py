"""
Percussa SSP platform implementation.

Generates native SSP modules (``.so``) against the Percussa SSP SDK's
``Percussa::SSP::PluginInterface``, without JUCE. The project cross-compiles
with host clang and the Percussa buildroot sysroot through its own
``ssp_toolchain.cmake``; ``-DSSP_HOST_BUILD=ON`` builds for the host instead.

Without JUCE the module loads in Synthor but not in TheTechnobear's rack-style
hosts, which require the JUCE-based ``SSPExtendedApi``.
"""

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from gen_dsp.version import __version__
from gen_dsp.core.manifest import Manifest, build_remap_defines
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import ProjectError
from gen_dsp.platforms.cmake_platform import CMakePlatform
from gen_dsp.templates import get_ssp_templates_dir

if TYPE_CHECKING:
    from gen_dsp.graph.models import Graph

# Copied unchanged into every project (export and graph paths)
_STATIC_FILES = (
    "gen_ext_ssp.cpp",
    "gen_ext_common_ssp.h",
    "ssp_font.h",
    "ssp_toolchain.cmake",
)


def ssp_module_name(lib_name: str) -> str:
    """Derive a 4-character SSP module name from ``lib_name``, e.g. gigaverb -> gvrb.

    Keeps the first character, then prefers unseen consonants and digits, then
    unseen vowels, then repeats; the kept characters stay in reading order. Pads
    with ``x`` when ``lib_name`` has fewer than 4 letters or digits.
    """
    s = re.sub(r"[^A-Za-z0-9]", "", lib_name).lower()
    if not s:
        return "gdsp"
    tiers: tuple[list[int], list[int], list[int]] = ([], [], [])
    seen: set[str] = set()
    for i, c in enumerate(s):
        if c in seen:
            tiers[2].append(i)
        elif i == 0 or c not in "aeiou":
            tiers[0].append(i)
        else:
            tiers[1].append(i)
        seen.add(c)
    keep = sorted((tiers[0] + tiers[1] + tiers[2])[:4])
    return "".join(s[i] for i in keep).ljust(4, "x")


def resolve_ssp_name(config: Optional[ProjectConfig], lib_name: str) -> str:
    """Return the module name: ``config.ssp_name`` if given, else derived from ``lib_name``.

    Synthor lists a module only if its uid spells its 4-character name.
    """
    if config is not None and config.ssp_name:
        return config.ssp_name.lower()
    return ssp_module_name(lib_name)


def write_cmakelists(
    output_dir: Path,
    lib_name: str,
    gen_name: str,
    sources: list[str],
    include_dirs: list[str],
    module_name: str,
    use_shared_cache: str = "OFF",
    cache_dir: str = "",
    remap_defines: str = "",
) -> Path:
    """Render the SSP CMakeLists.txt. Shared by the export and graph paths."""
    path = output_dir / "CMakeLists.txt"
    SspPlatform().render_template(
        get_ssp_templates_dir() / "CMakeLists.txt.template",
        path,
        label="CMakeLists.txt template",
        lib_name=lib_name,
        gen_name=gen_name,
        module_name=module_name,
        gendsp_version=__version__,
        sources="\n".join(f"    {s}" for s in sources),
        include_dirs="\n".join(
            f'    "${{CMAKE_CURRENT_SOURCE_DIR}}/{d}"' for d in include_dirs
        ),
        use_shared_cache=use_shared_cache,
        cache_dir=cache_dir,
        remap_defines=remap_defines,
    )
    return path


class SspPlatform(CMakePlatform):
    """Percussa SSP platform implementation using CMake and a clang cross toolchain."""

    name = "ssp"
    description = "Percussa SSP module"
    build_system = "CMake (clang cross)"

    @property
    def extension(self) -> str:
        """Get the file extension for SSP modules."""
        return ".so"

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate SSP project files."""
        templates_dir = get_ssp_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"SSP templates not found at {templates_dir}")

        self._copy_static_files(output_dir)
        shutil.copy2(templates_dir / "_ext_ssp.cpp", output_dir / "_ext_ssp.cpp")
        shutil.copy2(templates_dir / "ssp_buffer.h", output_dir / "ssp_buffer.h")
        self.generate_ext_header(output_dir, "ssp")
        self.copy_remap_header(output_dir)

        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp SSP wrapper",
        )

        use_shared_cache, cache_dir = self.resolve_shared_cache(config)
        write_cmakelists(
            output_dir,
            lib_name,
            manifest.gen_name,
            sources=[
                "gen_ext_ssp.cpp",
                "_ext_ssp.cpp",
                "gen/gen_dsp/genlib.cpp",
                "gen/gen_dsp/json.c",
                "gen/gen_dsp/json_builder.c",
            ],
            include_dirs=["gen", "gen/gen_dsp"],
            module_name=resolve_ssp_name(config, lib_name),
            use_shared_cache=use_shared_cache,
            cache_dir=cache_dir,
            remap_defines=build_remap_defines(manifest),
        )

        (output_dir / "build").mkdir(exist_ok=True)

    def generate_from_graph(
        self,
        graph: "Graph",
        manifest: Manifest,
        output_dir: Path,
        name: str,
        config: ProjectConfig,
        midi_defines: str,
    ) -> None:
        """Graph path, then re-render CMakeLists.txt: the shared step cannot see ``ssp_name``."""
        super().generate_from_graph(
            graph, manifest, output_dir, name, config, midi_defines
        )
        use_shared_cache, cache_dir = self.resolve_shared_cache(config)
        write_cmakelists(
            output_dir,
            name,
            graph.name,
            sources=["gen_ext_ssp.cpp", "_ext_ssp.cpp"],
            include_dirs=[],
            module_name=resolve_ssp_name(config, name),
            use_shared_cache=use_shared_cache,
            cache_dir=cache_dir,
        )

    def _write_graph_platform_files(
        self,
        graph: "Graph",
        manifest: Manifest,
        output_dir: Path,
        name: str,
        config: ProjectConfig,
    ) -> None:
        """Graph path: copy the font and toolchain the shared template copy skips."""
        self._copy_static_files(output_dir)

    @staticmethod
    def _copy_static_files(output_dir: Path) -> None:
        templates_dir = get_ssp_templates_dir()
        for filename in _STATIC_FILES:
            shutil.copy2(templates_dir / filename, output_dir / filename)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built SSP module."""
        return self.find_output_by_pattern(
            project_dir / "build", "*.so", require_file=True
        )
