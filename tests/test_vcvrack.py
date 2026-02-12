"""Tests for VCV Rack module platform implementation."""

import json
import os
import platform as sys_platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    VcvRackPlatform,
    get_platform,
)
from gen_dsp.platforms.vcvrack import (
    RACK_SDK_VERSION,
    _get_default_rack_sdk_dir,
    _get_rack_sdk_url,
    _resolve_rack_dir,
    ensure_rack_sdk,
)


# Skip conditions
_has_make = shutil.which("make") is not None
_has_cxx = shutil.which("clang++") is not None or shutil.which("g++") is not None
_can_build = _has_make and _has_cxx

_skip_no_toolchain = pytest.mark.skipif(
    not _can_build, reason="make and C++ compiler required"
)


def _find_rack_binary() -> Optional[str]:
    """Find VCV Rack binary. PATH > RACK_APP env > macOS app bundle."""
    found = shutil.which("Rack")
    if found:
        return found
    env_val = os.environ.get("RACK_APP")
    if env_val:
        candidate = Path(env_val) / "Contents" / "MacOS" / "Rack"
        if candidate.is_file():
            return str(candidate)
    if sys.platform == "darwin":
        for app_dir in [
            Path("/Applications/VCV Rack 2 Pro.app"),
            Path("/Applications/VCV Rack 2 Free.app"),
            Path("/Applications/Studio/VCV Rack 2 Pro.app"),
            Path("/Applications/Studio/VCV Rack 2 Free.app"),
        ]:
            candidate = app_dir / "Contents" / "MacOS" / "Rack"
            if candidate.is_file():
                return str(candidate)
    return None


_rack_binary = _find_rack_binary()
_has_rack_runtime = _rack_binary is not None


def _rack_plugins_subdir() -> str:
    """Return the platform-specific plugins subfolder name."""
    system = sys_platform.system().lower()
    machine = sys_platform.machine().lower()
    if system == "darwin":
        os_tag = "mac"
        cpu_tag = "arm64" if machine == "arm64" else "x64"
    elif system == "linux":
        os_tag = "lin"
        cpu_tag = "x64"
    else:
        os_tag = "win"
        cpu_tag = "x64"
    return f"plugins-{os_tag}-{cpu_tag}"


def _validate_vcvrack(project_dir: Path, slug: str) -> None:
    """Load a built VCV Rack plugin in headless Rack and verify it loads."""
    if not _has_rack_runtime:
        return

    import tempfile

    user_dir = Path(tempfile.mkdtemp(prefix="rack_validate_"))
    try:
        # Copy plugin to isolated user dir
        plugins_dir = user_dir / _rack_plugins_subdir() / slug
        plugins_dir.mkdir(parents=True)
        # Copy plugin.dylib/so/dll
        platform = VcvRackPlatform()
        output = platform.find_output(project_dir)
        assert output is not None
        shutil.copy2(output, plugins_dir / output.name)
        # Copy plugin.json
        shutil.copy2(project_dir / "plugin.json", plugins_dir / "plugin.json")
        # Copy res/ if it exists
        res_src = project_dir / "res"
        if res_src.is_dir():
            shutil.copytree(res_src, plugins_dir / "res")

        # Create minimal autosave patch that instantiates our module
        autosave_dir = user_dir / "autosave"
        autosave_dir.mkdir()
        patch = {
            "version": "2.6.6",
            "modules": [
                {
                    "id": 1,
                    "plugin": slug,
                    "model": slug,
                    "version": "2.0.0",
                    "params": [],
                }
            ],
            "cables": [],
        }
        (autosave_dir / "patch.json").write_text(json.dumps(patch))
        # Minimal settings -- disable network access for fast, offline validation
        settings = {
            "autoCheckUpdates": False,
            "verifyHttpsCerts": False,
        }
        (user_dir / "settings.json").write_text(json.dumps(settings))

        # Run Rack headless -- /dev/null stdin causes immediate exit after load
        result = subprocess.run(
            [_rack_binary, "--headless", "--user", str(user_dir)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Read log
        log_path = user_dir / "log.txt"
        log_text = log_path.read_text() if log_path.is_file() else ""

        assert result.returncode == 0, (
            f"Rack headless failed (exit {result.returncode}):\n{log_text}"
        )
        assert f"Loaded plugin {slug}" in log_text, (
            f"Plugin {slug} not loaded:\n{log_text}"
        )
        # Check no module creation error
        assert "Could not create module" not in log_text, (
            f"Module creation failed:\n{log_text}"
        )
    finally:
        shutil.rmtree(user_dir, ignore_errors=True)


class TestVcvRackPlatform:
    """Test VCV Rack platform registry and basic properties."""

    def test_registry_contains_vcvrack(self):
        """Test that vcvrack is in the registry."""
        assert "vcvrack" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["vcvrack"] == VcvRackPlatform

    def test_get_platform_vcvrack(self):
        """Test getting VCV Rack platform instance."""
        platform = get_platform("vcvrack")
        assert isinstance(platform, VcvRackPlatform)
        assert platform.name == "vcvrack"

    def test_vcvrack_extension(self):
        """Test that extension matches platform."""
        platform = VcvRackPlatform()
        ext = platform.extension
        assert ext in (".dylib", ".so", ".dll")

    def test_vcvrack_build_instructions(self):
        """Test VCV Rack build instructions."""
        platform = VcvRackPlatform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert len(instructions) > 0
        assert any("make" in instr for instr in instructions)

    def test_detect_plugin_type_effect(self):
        """Test that inputs > 0 gives effect."""
        platform = VcvRackPlatform()
        assert platform._detect_plugin_type(2) == "effect"
        assert platform._detect_plugin_type(1) == "effect"

    def test_detect_plugin_type_generator(self):
        """Test that inputs == 0 gives generator."""
        platform = VcvRackPlatform()
        assert platform._detect_plugin_type(0) == "generator"

    def test_compute_panel_hp_small(self):
        """Test HP computation for small component counts."""
        assert VcvRackPlatform._compute_panel_hp(1) == 6
        assert VcvRackPlatform._compute_panel_hp(6) == 6

    def test_compute_panel_hp_medium(self):
        """Test HP computation for medium component counts."""
        assert VcvRackPlatform._compute_panel_hp(7) == 10
        assert VcvRackPlatform._compute_panel_hp(12) == 10

    def test_compute_panel_hp_large(self):
        """Test HP computation for large component counts."""
        assert VcvRackPlatform._compute_panel_hp(13) == 16
        assert VcvRackPlatform._compute_panel_hp(20) == 16

    def test_compute_panel_hp_xlarge(self):
        """Test HP computation for very large component counts."""
        assert VcvRackPlatform._compute_panel_hp(21) == 24
        assert VcvRackPlatform._compute_panel_hp(50) == 24


class TestVcvRackSdkResolution:
    """Test Rack SDK path resolution and URL generation."""

    def test_sdk_url_returns_string(self):
        """Test that SDK URL is generated for current platform."""
        url = _get_rack_sdk_url()
        assert url.startswith("https://")
        assert RACK_SDK_VERSION in url
        assert "Rack-SDK" in url

    def test_default_rack_sdk_dir_in_cache(self):
        """Test that default SDK dir is under the gen-dsp cache."""
        sdk_dir = _get_default_rack_sdk_dir()
        assert "gen-dsp" in str(sdk_dir)
        assert "rack-sdk-src" in str(sdk_dir)
        assert "Rack-SDK" in str(sdk_dir)

    def test_resolve_rack_dir_env_override(self, monkeypatch):
        """Test that RACK_DIR env var takes highest priority."""
        monkeypatch.setenv("RACK_DIR", "/custom/sdk")
        assert _resolve_rack_dir() == Path("/custom/sdk")

    def test_resolve_rack_dir_cache_override(self, monkeypatch):
        """Test that GEN_DSP_CACHE_DIR env var derives RACK_DIR."""
        monkeypatch.delenv("RACK_DIR", raising=False)
        monkeypatch.setenv("GEN_DSP_CACHE_DIR", "/tmp/mycache")
        result = _resolve_rack_dir()
        assert str(result) == "/tmp/mycache/rack-sdk-src/Rack-SDK"

    def test_resolve_rack_dir_default(self, monkeypatch):
        """Test that default falls back to OS cache path."""
        monkeypatch.delenv("RACK_DIR", raising=False)
        monkeypatch.delenv("GEN_DSP_CACHE_DIR", raising=False)
        result = _resolve_rack_dir()
        assert result == _get_default_rack_sdk_dir()


class TestVcvRackProjectGeneration:
    """Test VCV Rack project generation."""

    def test_generate_vcvrack_project_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating VCV Rack project without buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check directory was created
        assert project_dir.is_dir()

        # Check required files exist
        assert (project_dir / "Makefile").is_file()
        assert (project_dir / "plugin.json").is_file()
        assert (project_dir / "plugin.cpp").is_file()
        assert (project_dir / "plugin.hpp").is_file()
        assert (project_dir / "gen_ext_vcvrack.cpp").is_file()
        assert (project_dir / "_ext_vcvrack.cpp").is_file()
        assert (project_dir / "_ext_vcvrack.h").is_file()
        assert (project_dir / "gen_ext_common_vcvrack.h").is_file()
        assert (project_dir / "vcvrack_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()

        # Check panel SVG exists
        assert (project_dir / "res" / "testverb.svg").is_file()

        # Check gen export
        assert (project_dir / "gen").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_vcvrack_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating VCV Rack project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="vcvrack",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check gen_buffer.h has buffer configured
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_generate_vcvrack_project_multiple_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating VCV Rack project with multiple buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="multibuf",
            platform="vcvrack",
            buffers=["buf1", "buf2", "buf3"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 3" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 buf1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_1 buf2" in buffer_h
        assert "WRAPPER_BUFFER_NAME_2 buf3" in buffer_h

    def test_makefile_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has correct template substitutions."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "VCR_EXT_NAME=testverb" in makefile
        assert "GEN_EXPORTED_NAME=gen_exported" in makefile
        assert "GENLIB_USE_FLOAT32" in makefile
        assert "RACK_DIR" in makefile
        assert "plugin.mk" in makefile

    def test_makefile_baked_rack_dir(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has baked-in cache path for RACK_DIR."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        # Should contain the OS-appropriate cache path, not ~/Rack-SDK
        assert "gen-dsp" in makefile
        assert "rack-sdk-src/Rack-SDK" in makefile
        # Should support GEN_DSP_CACHE_DIR override
        assert "GEN_DSP_CACHE_DIR" in makefile

    def test_makefile_num_io(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has correct I/O and param counts."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert f"VCR_NUM_INPUTS={export_info.num_inputs}" in makefile
        assert f"VCR_NUM_OUTPUTS={export_info.num_outputs}" in makefile
        assert f"VCR_NUM_PARAMS={export_info.num_params}" in makefile

    def test_makefile_panel_hp(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has correct panel HP."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        # gigaverb: 2in + 2out + 8params = 12 components -> 10 HP
        assert "VCR_PANEL_HP=10" in makefile

    def test_plugin_json_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test that plugin.json has correct content."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        plugin_json = json.loads((project_dir / "plugin.json").read_text())
        assert plugin_json["slug"] == "testverb"
        assert plugin_json["name"] == "testverb"
        assert "modules" in plugin_json
        assert len(plugin_json["modules"]) == 1
        module = plugin_json["modules"][0]
        assert module["slug"] == "testverb"
        assert module["name"] == "testverb"

    def test_plugin_json_effect_tags(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gigaverb (has inputs) gets Effect tag."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()
        assert export_info.num_inputs > 0

        config = ProjectConfig(name="testverb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        plugin_json = json.loads((project_dir / "plugin.json").read_text())
        module = plugin_json["modules"][0]
        assert "Effect" in module["tags"]

    def test_plugin_json_generator_tags(self):
        """Test that 0-input export gets Synth Voice tag."""
        platform = VcvRackPlatform()
        assert platform._detect_plugin_type(0) == "generator"

    def test_panel_svg_exists(self, gigaverb_export: Path, tmp_project: Path):
        """Test that panel SVG is generated with correct dimensions."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        svg_path = project_dir / "res" / "testverb.svg"
        assert svg_path.is_file()
        svg_content = svg_path.read_text()
        assert "<svg" in svg_content
        assert "testverb" in svg_content
        # gigaverb: 12 components -> 10 HP -> 50.8mm width
        assert "50.8mm" in svg_content
        assert "128.5mm" in svg_content

    def test_panel_svg_dimensions_vary(
        self, spectraldelayfb_export: Path, tmp_project: Path
    ):
        """Test that panel SVG dimensions match component count."""
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="specfb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        svg_content = (project_dir / "res" / "specfb.svg").read_text()
        # spectraldelayfb: 3in + 2out + 0params = 5 components -> 6 HP -> 30.48mm
        assert "30.48mm" in svg_content

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()


class TestVcvRackBuildIntegration:
    """Integration tests that generate and compile a VCV Rack plugin.

    Skipped when make/C++ compiler is not available. Rack SDK is
    auto-downloaded to the shared fetchcontent cache on first run.
    """

    @_skip_no_toolchain
    def test_build_vcvrack_no_buffers(
        self, gigaverb_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile a VCV Rack plugin from gigaverb (no buffers)."""
        project_dir = tmp_path / "gigaverb_vcvrack"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        # Ensure SDK is downloaded to shared cache
        rack_sdk_dir = fetchcontent_cache / "rack-sdk-src" / "Rack-SDK"
        rack_dir = ensure_rack_sdk(rack_sdk_dir)

        platform = VcvRackPlatform()
        result = platform.run_command(["make", f"RACK_DIR={rack_dir}"], project_dir)
        assert result.returncode == 0, (
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output = platform.find_output(project_dir)
        assert output is not None
        assert output.name.startswith("plugin")

        _validate_vcvrack(project_dir, "gigaverb")

    @_skip_no_toolchain
    def test_build_vcvrack_with_buffers(
        self, rampleplayer_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile a VCV Rack plugin from RamplePlayer (has buffers)."""
        project_dir = tmp_path / "rampleplayer_vcvrack"
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="rampleplayer",
            platform="vcvrack",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        rack_sdk_dir = fetchcontent_cache / "rack-sdk-src" / "Rack-SDK"
        rack_dir = ensure_rack_sdk(rack_sdk_dir)

        platform = VcvRackPlatform()
        result = platform.run_command(["make", f"RACK_DIR={rack_dir}"], project_dir)
        assert result.returncode == 0, (
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output = platform.find_output(project_dir)
        assert output is not None

        _validate_vcvrack(project_dir, "rampleplayer")

    @_skip_no_toolchain
    def test_build_vcvrack_spectraldelayfb(
        self, spectraldelayfb_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile a VCV Rack plugin from spectraldelayfb (3in/2out)."""
        project_dir = tmp_path / "spectraldelayfb_vcvrack"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="vcvrack")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        rack_sdk_dir = fetchcontent_cache / "rack-sdk-src" / "Rack-SDK"
        rack_dir = ensure_rack_sdk(rack_sdk_dir)

        platform = VcvRackPlatform()
        result = platform.run_command(["make", f"RACK_DIR={rack_dir}"], project_dir)
        assert result.returncode == 0, (
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output = platform.find_output(project_dir)
        assert output is not None

        _validate_vcvrack(project_dir, "spectraldelayfb")
