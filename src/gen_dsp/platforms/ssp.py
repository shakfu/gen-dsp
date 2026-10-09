"""
Percussa SSP platform implementation.

Generates SSP modules (``.so``) in one of two formats:

- ``native``: implements the Percussa SDK's ``Percussa::SSP::PluginInterface``
  directly, without JUCE. Loads in Synthor but not in TheTechnobear's
  rack-style hosts, which require the JUCE-based ``SSPExtendedApi``.
- ``juce``: builds on the SSP plugin framework (``plugins/common`` of
  shakfu/ssp) and TheTechnobear's JUCE fork, as the SSP's own modules are.
  Exports ``SSPExtendedApi`` too, so rack-style hosts load it.

Both cross-compile with host clang and the Percussa buildroot sysroot through
``ssp_toolchain.cmake``; ``-DSSP_HOST_BUILD=ON`` builds for the host instead.
"""

import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest, build_remap_defines
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import ProjectError
from gen_dsp.platforms.cmake_platform import CMakePlatform
from gen_dsp.templates import get_ssp_templates_dir
from gen_dsp.version import __version__

if TYPE_CHECKING:
    from gen_dsp.graph.models import Graph

# Copied unchanged into every project (export and graph paths)
_STATIC_FILES = (
    "gen_ext_ssp.cpp",
    "gen_ext_common_ssp.h",
    "ssp_font.h",
    "ssp_toolchain.cmake",
    "ssp_exports.map",
    "_ext_ssp_buffers.h",
)


# JUCE format, ad hoc dev tree: shakfu/ssp supplies plugins/common; its juce
# submodule is TheTechnobear's fork at the commit below.
_FRAMEWORK_COMMIT = "bc73d70d28ca9546d8bb09369846c24c83e14006"
_FRAMEWORK_SHA256 = "8ece06d802d0d89eb13b1a26f4a3a90af195c4943ff968b97609f802fc14ee99"
_JUCE_COMMIT = "ed1da021a045632a8f4dca65056f93b31ef3834f"
_JUCE_SHA256 = "5c2ea7181f666069afe71889fd7a2771bad75f796afc50630e9d62eed9620205"

# Copied into every JUCE-format project, from templates/ssp/juce
_JUCE_FILES = (
    "PluginProcessor.h",
    "PluginProcessor.cpp",
    "SSPApi.cpp",
    "ssp_exports.map",
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


def resolve_ssp_name(config: ProjectConfig | None, lib_name: str) -> str:
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


def write_juce_cmakelists(
    output_dir: Path,
    lib_name: str,
    gen_name: str,
    sources: list[str],
    include_dirs: list[str],
    module_name: str,
    dev_dir: Path | None = None,
    use_shared_cache: str = "OFF",
    cache_dir: str = "",
    remap_defines: str = "",
) -> Path:
    """Render the JUCE-format SSP CMakeLists.txt. Shared by the export and graph paths."""
    path = output_dir / "CMakeLists.txt"
    version = re.match(r"\d+(\.\d+){0,2}", __version__)
    SspPlatform().render_template(
        get_ssp_templates_dir() / "juce" / "CMakeLists.txt.template",
        path,
        label="JUCE CMakeLists.txt template",
        lib_name=lib_name,
        gen_name=gen_name,
        module_name=module_name,
        gendsp_version=__version__,
        project_version=version.group(0) if version else "0.0.0",
        dev_dir=dev_dir.as_posix() if dev_dir else "",
        framework_commit=_FRAMEWORK_COMMIT,
        framework_sha256=_FRAMEWORK_SHA256,
        juce_commit=_JUCE_COMMIT,
        juce_sha256=_JUCE_SHA256,
        sources="\n".join(f'    "${{CMAKE_CURRENT_SOURCE_DIR}}/{s}"' for s in sources),
        include_dirs="\n".join(
            f'    "${{CMAKE_CURRENT_SOURCE_DIR}}/{d}"' for d in include_dirs
        ),
        use_shared_cache=use_shared_cache,
        cache_dir=cache_dir,
        remap_defines=remap_defines,
    )
    return path


def write_buffer_names(output_dir: Path, buffers: list[str]) -> Path:
    """Write ssp_buffer_names.h, which _ext_ssp.cpp includes around the exported code."""
    lines = [
        "// ssp_buffer_names.h - generated by gen-dsp; no include guard: included twice",
        "// Renames each buffer the exported gen~ code names to its instance's view.",
        "#ifndef SSP_BUFFER_NAMES_END",
        *(f"#define {name} SSP_BUFFER({k})" for k, name in enumerate(buffers)),
        "#else",
        *(f"#undef {name}" for name in buffers),
        "#undef SSP_BUFFER_NAMES_END",
        "#endif",
    ]
    path = output_dir / "ssp_buffer_names.h"
    path.write_text("\n".join(lines) + "\n")
    return path


def _is_juce(config: ProjectConfig | None) -> bool:
    return config is not None and config.ssp_format == "juce"


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
        config: ProjectConfig | None = None,
    ) -> None:
        """Generate SSP project files."""
        templates_dir = get_ssp_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"SSP templates not found at {templates_dir}")

        self._copy_static_files(output_dir, config)
        shutil.copy2(templates_dir / "_ext_ssp.cpp", output_dir / "_ext_ssp.cpp")
        shutil.copy2(templates_dir / "ssp_buffer.h", output_dir / "ssp_buffer.h")
        write_buffer_names(output_dir, manifest.buffers)
        self.generate_ext_header(output_dir, "ssp")
        self.copy_remap_header(output_dir)

        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp SSP wrapper",
        )

        self._write_cmakelists(
            output_dir,
            lib_name,
            manifest.gen_name,
            config,
            sources=[
                "_ext_ssp.cpp",
                "gen/gen_dsp/genlib.cpp",
                "gen/gen_dsp/json.c",
                "gen/gen_dsp/json_builder.c",
            ],
            include_dirs=["gen", "gen/gen_dsp"],
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
        if _is_juce(config):
            # the shared step copies the native module source
            (output_dir / "gen_ext_ssp.cpp").unlink(missing_ok=True)
        self._write_cmakelists(
            output_dir,
            name,
            graph.name,
            config,
            sources=["_ext_ssp.cpp"],
            include_dirs=[],
        )

    def _write_cmakelists(
        self,
        output_dir: Path,
        lib_name: str,
        gen_name: str,
        config: ProjectConfig | None,
        sources: list[str],
        include_dirs: list[str],
        remap_defines: str = "",
    ) -> None:
        use_shared_cache, cache_dir = self.resolve_shared_cache(config)
        module_name = resolve_ssp_name(config, lib_name)
        if _is_juce(config):
            assert config is not None
            write_juce_cmakelists(
                output_dir,
                lib_name,
                gen_name,
                sources=["PluginProcessor.cpp", *sources],
                include_dirs=include_dirs,
                module_name=module_name,
                dev_dir=config.ssp_dev_dir,
                use_shared_cache=use_shared_cache,
                cache_dir=cache_dir,
                remap_defines=remap_defines,
            )
        else:
            write_cmakelists(
                output_dir,
                lib_name,
                gen_name,
                sources=["gen_ext_ssp.cpp", *sources],
                include_dirs=include_dirs,
                module_name=module_name,
                use_shared_cache=use_shared_cache,
                cache_dir=cache_dir,
                remap_defines=remap_defines,
            )

    def _write_graph_platform_files(
        self,
        graph: "Graph",
        manifest: Manifest,
        output_dir: Path,
        name: str,
        config: ProjectConfig,
    ) -> None:
        """Graph path: copy the files the shared template copy skips."""
        self._copy_static_files(output_dir, config)

    @staticmethod
    def _copy_static_files(output_dir: Path, config: ProjectConfig | None) -> None:
        templates_dir = get_ssp_templates_dir()
        if _is_juce(config):
            for filename in (
                "gen_ext_common_ssp.h",
                "ssp_toolchain.cmake",
                "_ext_ssp_buffers.h",
            ):
                shutil.copy2(templates_dir / filename, output_dir / filename)
            for filename in _JUCE_FILES:
                shutil.copy2(templates_dir / "juce" / filename, output_dir / filename)
        else:
            for filename in _STATIC_FILES:
                shutil.copy2(templates_dir / filename, output_dir / filename)

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build with CMake, one job per CPU: the JUCE format compiles JUCE too."""
        return self._build_with_cmake(
            project_dir,
            clean,
            verbose,
            build_args=["--parallel", str(os.cpu_count() or 1)],
        )

    def find_output(self, project_dir: Path) -> Path | None:
        """Find the built SSP module."""
        return self.find_output_by_pattern(
            project_dir / "build", "*.so", require_file=True
        )
