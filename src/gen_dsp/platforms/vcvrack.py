"""
VCV Rack module platform implementation.

Generates VCV Rack plugins using the Rack SDK's Makefile-based build system.
The plugin's Makefile includes $(RACK_DIR)/plugin.mk which provides compilation
rules, platform detection, and linking.

The Rack SDK is automatically downloaded and cached -- same model as the CMake
backends that use FetchContent. Priority for RACK_DIR resolution:
  1. RACK_DIR environment variable (explicit override)
  2. GEN_DSP_CACHE_DIR environment variable + /rack-sdk/Rack-SDK
  3. OS-appropriate gen-dsp cache path (baked into generated Makefile)

Processing: gen~'s perform() is called with n=1 per sample (VCV Rack calls
process() once per sample). This is zero-latency and cleanest.

Output artifacts:
  - plugin.dylib (macOS), plugin.so (Linux), plugin.dll (Windows)
  - plugin.json   (VCV Rack module manifest)
  - res/<name>.svg (panel SVG)
"""

import json
import os
import platform as sys_platform
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_vcvrack_templates_dir


# Rack SDK version and download URLs
RACK_SDK_VERSION = "2.6.1"
_RACK_SDK_BASE_URL = "https://vcvrack.com/downloads"
_RACK_SDK_URLS = {
    "darwin_arm64": f"{_RACK_SDK_BASE_URL}/Rack-SDK-{RACK_SDK_VERSION}-mac-arm64.zip",
    "darwin_x86_64": f"{_RACK_SDK_BASE_URL}/Rack-SDK-{RACK_SDK_VERSION}-mac-x64.zip",
    "linux_x86_64": f"{_RACK_SDK_BASE_URL}/Rack-SDK-{RACK_SDK_VERSION}-lin-x64.zip",
    "win32_x86_64": f"{_RACK_SDK_BASE_URL}/Rack-SDK-{RACK_SDK_VERSION}-win-x64.zip",
}

# Subdirectory name inside the gen-dsp cache
_RACK_SDK_CACHE_SUBDIR = "rack-sdk-src"
# Name of the directory inside the extracted zip
_RACK_SDK_DIR_NAME = "Rack-SDK"


def _get_rack_sdk_url() -> str:
    """Return the download URL for the current platform/architecture."""
    system = sys.platform  # darwin, linux, win32
    machine = sys_platform.machine()  # arm64, x86_64, AMD64

    # Normalise architecture
    arch = machine.lower()
    if arch in ("amd64", "x86_64"):
        arch = "x86_64"
    elif arch in ("arm64", "aarch64"):
        arch = "arm64"

    key = f"{system}_{arch}"
    if key not in _RACK_SDK_URLS:
        raise BuildError(
            f"No Rack SDK download available for {system}/{machine}. "
            f"Available: {', '.join(sorted(_RACK_SDK_URLS.keys()))}"
        )
    return _RACK_SDK_URLS[key]


def _get_default_rack_sdk_dir() -> Path:
    """Return the default cached Rack SDK path (OS-appropriate)."""
    from gen_dsp.core.cache import get_cache_dir

    return get_cache_dir() / _RACK_SDK_CACHE_SUBDIR / _RACK_SDK_DIR_NAME


def _resolve_rack_dir() -> Path:
    """Resolve RACK_DIR using the priority chain.

    1. RACK_DIR env var
    2. GEN_DSP_CACHE_DIR env var + rack-sdk-src/Rack-SDK
    3. OS-appropriate gen-dsp cache path
    """
    env_rack = os.environ.get("RACK_DIR")
    if env_rack:
        return Path(env_rack)

    env_cache = os.environ.get("GEN_DSP_CACHE_DIR")
    if env_cache:
        return Path(env_cache) / _RACK_SDK_CACHE_SUBDIR / _RACK_SDK_DIR_NAME

    return _get_default_rack_sdk_dir()


def ensure_rack_sdk(rack_dir: Optional[Path] = None, verbose: bool = False) -> Path:
    """Ensure the Rack SDK is available, downloading if necessary.

    Args:
        rack_dir: Explicit SDK path. If None, resolves via priority chain.
        verbose: Print progress messages.

    Returns:
        Path to the Rack SDK directory (containing plugin.mk).

    Raises:
        BuildError: If download fails or SDK is invalid.
    """
    if rack_dir is None:
        rack_dir = _resolve_rack_dir()

    # Already present?
    if (rack_dir / "plugin.mk").is_file():
        return rack_dir

    # Download and extract
    url = _get_rack_sdk_url()
    cache_parent = rack_dir.parent  # .../rack-sdk-src/
    cache_parent.mkdir(parents=True, exist_ok=True)

    zip_path = cache_parent / f"Rack-SDK-{RACK_SDK_VERSION}.zip"

    if not zip_path.is_file():
        if verbose:
            print(f"Downloading Rack SDK {RACK_SDK_VERSION} from {url} ...")
        try:
            urllib.request.urlretrieve(url, zip_path)
        except Exception as e:
            zip_path.unlink(missing_ok=True)
            raise BuildError(f"Failed to download Rack SDK: {e}") from e

    # Extract
    if verbose:
        print(f"Extracting Rack SDK to {cache_parent} ...")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(cache_parent)
    except Exception as e:
        raise BuildError(f"Failed to extract Rack SDK: {e}") from e

    # Verify
    if not (rack_dir / "plugin.mk").is_file():
        raise BuildError(
            f"Rack SDK extraction succeeded but plugin.mk not found at {rack_dir}. "
            f"Contents: {list(cache_parent.iterdir())}"
        )

    return rack_dir


class VcvRackPlatform(Platform):
    """VCV Rack module platform implementation using Make."""

    name = "vcvrack"

    @property
    def extension(self) -> str:
        """Get the extension for VCV Rack plugins."""
        if sys.platform == "darwin":
            return ".dylib"
        elif sys.platform == "win32":
            return ".dll"
        return ".so"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for VCV Rack."""
        return ["make"]

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate VCV Rack module project files."""
        templates_dir = get_vcvrack_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"VCV Rack templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "gen_ext_vcvrack.cpp",
            "gen_ext_common_vcvrack.h",
            "_ext_vcvrack.cpp",
            "_ext_vcvrack.h",
            "vcvrack_buffer.h",
            "plugin.cpp",
            "plugin.hpp",
        ]
        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Compute panel HP
        total_components = (
            manifest.num_params + manifest.num_inputs + manifest.num_outputs
        )
        panel_hp = self._compute_panel_hp(total_components)

        # Resolve default RACK_DIR for baking into Makefile
        default_rack_dir = str(_get_default_rack_sdk_dir())

        # Generate Makefile from template
        self._generate_makefile(
            templates_dir / "Makefile.template",
            output_dir / "Makefile",
            manifest.gen_name,
            lib_name,
            manifest.num_inputs,
            manifest.num_outputs,
            manifest.num_params,
            panel_hp,
            default_rack_dir,
        )

        # Generate plugin.json manifest
        self._generate_plugin_json(
            output_dir,
            lib_name,
            manifest.num_inputs,
        )

        # Generate panel SVG
        res_dir = output_dir / "res"
        res_dir.mkdir(exist_ok=True)
        self._generate_panel_svg(
            res_dir / f"{lib_name}.svg",
            lib_name,
            panel_hp,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp VCV Rack wrapper",
        )

    def _detect_plugin_type(self, num_inputs: int) -> str:
        """Detect module type from number of inputs.

        Returns 'effect' if inputs > 0, 'generator' if inputs == 0.
        """
        return "effect" if num_inputs > 0 else "generator"

    @staticmethod
    def _compute_panel_hp(total_components: int) -> int:
        """Compute panel width in HP from total component count.

        HP (Horizontal Pitch) is the standard Eurorack width unit (1 HP = 5.08mm).
        """
        if total_components <= 6:
            return 6
        elif total_components <= 12:
            return 10
        elif total_components <= 20:
            return 16
        return 24

    def _generate_makefile(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
        num_inputs: int,
        num_outputs: int,
        num_params: int,
        panel_hp: int,
        default_rack_dir: str,
    ) -> None:
        """Generate Makefile from template."""
        if not template_path.exists():
            raise ProjectError(f"Makefile template not found at {template_path}")

        template_content = template_path.read_text(encoding="utf-8")
        template = Template(template_content)
        content = template.safe_substitute(
            gen_name=gen_name,
            lib_name=lib_name,
            genext_version=self.GENEXT_VERSION,
            num_inputs=num_inputs,
            num_outputs=num_outputs,
            num_params=num_params,
            panel_hp=panel_hp,
            default_rack_dir=default_rack_dir,
        )
        output_path.write_text(content, encoding="utf-8")

    def _generate_plugin_json(
        self,
        output_dir: Path,
        lib_name: str,
        num_inputs: int,
    ) -> None:
        """Generate plugin.json manifest for VCV Rack."""
        plugin_type = self._detect_plugin_type(num_inputs)
        if plugin_type == "effect":
            tags = ["Effect"]
        else:
            tags = ["Synth Voice"]

        manifest = {
            "slug": lib_name,
            "name": lib_name,
            "version": "2.0.0",
            "license": "MIT",
            "brand": "gen-dsp",
            "author": "gen-dsp",
            "authorUrl": "https://github.com/shakfu/gen-dsp",
            "pluginUrl": "",
            "manualUrl": "",
            "sourceUrl": "",
            "modules": [
                {
                    "slug": lib_name,
                    "name": lib_name,
                    "description": f"gen~ {lib_name} module",
                    "tags": tags,
                }
            ],
        }

        content = json.dumps(manifest, indent=2) + "\n"
        (output_dir / "plugin.json").write_text(content, encoding="utf-8")

    def _generate_panel_svg(
        self,
        output_path: Path,
        lib_name: str,
        panel_hp: int,
    ) -> None:
        """Generate a minimal dark panel SVG sized to the given HP."""
        # 1 HP = 5.08mm; standard Eurorack height = 128.5mm
        width_mm = panel_hp * 5.08
        height_mm = 128.5

        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width_mm}mm" height="{height_mm}mm" '
            f'viewBox="0 0 {width_mm} {height_mm}">\n'
            f'  <rect width="{width_mm}" height="{height_mm}" fill="#2a2a2a"/>\n'
            f'  <text x="{width_mm / 2}" y="12" '
            f'font-family="sans-serif" font-size="6" fill="#cccccc" '
            f'text-anchor="middle">{lib_name}</text>\n'
            f"</svg>\n"
        )
        output_path.write_text(svg)

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build VCV Rack plugin using make.

        Automatically downloads the Rack SDK if not already cached.
        """
        makefile = project_dir / "Makefile"
        if not makefile.exists():
            raise BuildError(f"Makefile not found in {project_dir}")

        # Ensure Rack SDK is available (downloads if needed)
        rack_dir = _resolve_rack_dir()
        rack_dir = ensure_rack_sdk(rack_dir, verbose=verbose)

        # Clean if requested
        if clean:
            self.run_command(["make", "clean", f"RACK_DIR={rack_dir}"], project_dir)

        # Build with explicit RACK_DIR
        result = self.run_command(
            ["make", f"RACK_DIR={rack_dir}"], project_dir, verbose=verbose
        )

        # Find output file
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=result.returncode == 0,
            platform="vcvrack",
            output_file=output_file,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        rack_dir = _resolve_rack_dir()
        if (rack_dir / "plugin.mk").is_file():
            self.run_command(["make", "clean", f"RACK_DIR={rack_dir}"], project_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built VCV Rack plugin file."""
        for ext in [".dylib", ".so", ".dll"]:
            candidate = project_dir / f"plugin{ext}"
            if candidate.is_file():
                return candidate
        return None
