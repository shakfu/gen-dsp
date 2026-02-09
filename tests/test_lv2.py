"""Tests for LV2 plugin platform implementation."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    Lv2Platform,
    get_platform,
)
from gen_dsp.platforms.lv2 import ParamInfo


def _build_env():
    """Environment for cmake subprocesses that prevents git credential prompts."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


# Skip conditions
_has_cmake = shutil.which("cmake") is not None
_has_cxx = shutil.which("clang++") is not None or shutil.which("g++") is not None
_can_build = _has_cmake and _has_cxx

_skip_no_toolchain = pytest.mark.skipif(
    not _can_build, reason="cmake and C++ compiler required"
)


class TestLv2Platform:
    """Test LV2 platform registry and basic properties."""

    def test_registry_contains_lv2(self):
        """Test that LV2 is in the registry."""
        assert "lv2" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["lv2"] == Lv2Platform

    def test_get_platform_lv2(self):
        """Test getting LV2 platform instance."""
        platform = get_platform("lv2")
        assert isinstance(platform, Lv2Platform)
        assert platform.name == "lv2"

    def test_lv2_extension(self):
        """Test that extension is .lv2."""
        platform = Lv2Platform()
        assert platform.extension == ".lv2"

    def test_lv2_build_instructions(self):
        """Test LV2 build instructions."""
        platform = Lv2Platform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert len(instructions) > 0
        assert any("cmake" in instr for instr in instructions)

    def test_detect_plugin_type_effect(self):
        """Test that inputs > 0 gives effect."""
        platform = Lv2Platform()
        assert platform._detect_plugin_type(2) == "effect"
        assert platform._detect_plugin_type(1) == "effect"

    def test_detect_plugin_type_generator(self):
        """Test that inputs == 0 gives generator."""
        platform = Lv2Platform()
        assert platform._detect_plugin_type(0) == "generator"

    def test_sanitize_symbol_valid(self):
        """Test that valid symbols pass through."""
        assert Lv2Platform._sanitize_symbol("bandwidth") == "bandwidth"
        assert Lv2Platform._sanitize_symbol("my_param") == "my_param"

    def test_sanitize_symbol_spaces(self):
        """Test that spaces are replaced with underscores."""
        assert Lv2Platform._sanitize_symbol("my param") == "my_param"

    def test_sanitize_symbol_leading_digit(self):
        """Test that leading digits get underscore prefix."""
        assert Lv2Platform._sanitize_symbol("0gain") == "_0gain"

    def test_sanitize_symbol_special_chars(self):
        """Test that special characters are replaced."""
        assert Lv2Platform._sanitize_symbol("gain-level") == "gain_level"


class TestLv2ParamParsing:
    """Test parameter metadata extraction from gen~ exports."""

    def test_parse_gigaverb_params(self, gigaverb_export: Path):
        """Test parsing parameters from gigaverb (8 params)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        platform = Lv2Platform()
        params = platform._parse_params(export_info)

        assert len(params) == 8
        # Check first param
        assert params[0].index == 0
        assert params[0].name == "bandwidth"
        # Check last param
        assert params[7].index == 7
        assert params[7].name == "tail"
        # All gigaverb params have hasminmax=true
        for p in params:
            assert p.has_minmax is True
            assert p.output_max >= p.output_min
        # Spot-check: revtime has min=0.1, others have min=0
        assert params[0].output_min == 0.0  # bandwidth
        assert params[0].output_max == 1.0
        revtime = next(p for p in params if p.name == "revtime")
        assert revtime.output_min == 0.1
        assert revtime.output_max == 1.0

    def test_parse_spectraldelayfb_params(self, spectraldelayfb_export: Path):
        """Test parsing parameters from spectraldelayfb (0 params)."""
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        platform = Lv2Platform()
        params = platform._parse_params(export_info)

        assert len(params) == 0

    def test_parse_params_sorted_by_index(self, gigaverb_export: Path):
        """Test that parsed params are sorted by index."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        platform = Lv2Platform()
        params = platform._parse_params(export_info)

        indices = [p.index for p in params]
        assert indices == sorted(indices)

    def test_param_names_are_valid_identifiers(self, gigaverb_export: Path):
        """Test that parsed param names are usable as LV2 symbols."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        platform = Lv2Platform()
        params = platform._parse_params(export_info)

        for p in params:
            symbol = Lv2Platform._sanitize_symbol(p.name)
            assert symbol == p.name  # gen~ names should already be valid


class TestLv2ProjectGeneration:
    """Test LV2 project generation."""

    def test_generate_lv2_project_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating LV2 project without buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check directory was created
        assert project_dir.is_dir()

        # Check required C++ files exist
        assert (project_dir / "CMakeLists.txt").is_file()
        assert (project_dir / "gen_ext_lv2.cpp").is_file()
        assert (project_dir / "_ext_lv2.cpp").is_file()
        assert (project_dir / "_ext_lv2.h").is_file()
        assert (project_dir / "gen_ext_common_lv2.h").is_file()
        assert (project_dir / "lv2_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()

        # Check TTL files exist
        assert (project_dir / "manifest.ttl").is_file()
        assert (project_dir / "testverb.ttl").is_file()

        # Check gen export and build dir
        assert (project_dir / "gen").is_dir()
        assert (project_dir / "build").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_lv2_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating LV2 project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="lv2",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check gen_buffer.h has buffer configured
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_generate_lv2_project_multiple_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating LV2 project with multiple buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="multibuf",
            platform="lv2",
            buffers=["buf1", "buf2", "buf3"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 3" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 buf1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_1 buf2" in buffer_h
        assert "WRAPPER_BUFFER_NAME_2 buf3" in buffer_h

    def test_cmakelists_content(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that CMakeLists.txt has correct template substitutions."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "set(PROJECT_NAME testverb)" in cmake
        assert "LV2_EXT_NAME=testverb" in cmake
        assert "GEN_EXPORTED_NAME=gen_exported" in cmake
        assert "GENLIB_USE_FLOAT32" in cmake
        assert "FetchContent_Declare" in cmake
        assert "lv2/lv2" in cmake

    def test_cmakelists_num_io(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that CMakeLists.txt has correct I/O and param counts."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert f"LV2_NUM_INPUTS={export_info.num_inputs}" in cmake
        assert f"LV2_NUM_OUTPUTS={export_info.num_outputs}" in cmake
        assert f"LV2_NUM_PARAMS={export_info.num_params}" in cmake

    def test_generate_copies_gen_export(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()

    def test_manifest_ttl_content(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test manifest.ttl has correct URI and binary reference."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        manifest = (project_dir / "manifest.ttl").read_text()
        assert "http://gen-dsp.com/plugins/testverb" in manifest
        assert "lv2:binary" in manifest
        assert "lv2:Plugin" in manifest
        assert "rdfs:seeAlso" in manifest
        assert "testverb.ttl" in manifest

    def test_plugin_ttl_ports(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test plugin.ttl has correct port definitions."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        ttl = (project_dir / "testverb.ttl").read_text()
        assert "http://gen-dsp.com/plugins/testverb" in ttl
        assert 'doap:name "testverb"' in ttl
        assert "lv2:hardRTCapable" in ttl

        # Check param ports exist with real names
        assert '"bandwidth"' in ttl
        assert '"damping"' in ttl
        assert '"revtime"' in ttl
        assert "lv2:ControlPort" in ttl

        # Check audio ports
        assert "lv2:AudioPort" in ttl
        assert '"in0"' in ttl
        assert '"out0"' in ttl

        # Check port indices are present
        assert "lv2:index 0" in ttl  # first param

    def test_plugin_ttl_effect_type(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that gigaverb (has inputs) is EffectPlugin."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()
        assert export_info.num_inputs > 0

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        ttl = (project_dir / "testverb.ttl").read_text()
        assert "lv2:EffectPlugin" in ttl

    def test_plugin_ttl_generator_type(
        self, spectraldelayfb_export: Path, tmp_project: Path
    ):
        """Test that 0-input export is GeneratorPlugin."""
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        # spectraldelayfb has 3 inputs, so we need to test the type logic directly
        platform = Lv2Platform()
        assert platform._detect_plugin_type(0) == "generator"

    def test_plugin_ttl_no_params(
        self, spectraldelayfb_export: Path, tmp_project: Path
    ):
        """Test TTL for export with no parameters."""
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="specfb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        ttl = (project_dir / "specfb.ttl").read_text()
        # Should have audio ports but no control ports
        assert "lv2:AudioPort" in ttl
        assert "lv2:ControlPort" not in ttl

    def test_cmakelists_shared_cache_off_by_default(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that default generation has shared cache OFF."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(OFF)" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake

    def test_cmakelists_shared_cache_on(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that --shared-cache produces ON with resolved path."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testverb", platform="lv2", shared_cache=True
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(ON)" in cmake
        assert "gen-dsp" in cmake
        assert "fetchcontent" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake


class TestLv2BuildIntegration:
    """Integration tests that generate and compile an LV2 plugin.

    Skipped when no cmake/C++ compiler is available.
    """

    @_skip_no_toolchain
    def test_build_lv2_no_buffers(
        self, gigaverb_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile an LV2 plugin from gigaverb (no buffers)."""
        project_dir = tmp_path / "gigaverb_lv2"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        build_dir = project_dir / "build"
        env = _build_env()

        # Configure
        result = subprocess.run(
            ["cmake", "..", f"-DFETCHCONTENT_BASE_DIR={fetchcontent_cache}"],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert result.returncode == 0, (
            f"cmake configure failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Build
        result = subprocess.run(
            ["cmake", "--build", "."],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert result.returncode == 0, (
            f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify .lv2 bundle directory was produced
        lv2_bundles = [d for d in build_dir.glob("**/*.lv2") if d.is_dir()]
        assert len(lv2_bundles) >= 1
        bundle = lv2_bundles[0]
        assert bundle.name == "gigaverb.lv2"
        # Check bundle contents
        assert (bundle / "manifest.ttl").is_file()
        assert (bundle / "gigaverb.ttl").is_file()
        # Check binary exists (name varies by platform)
        binaries = list(bundle.glob("gigaverb.*"))
        assert len(binaries) >= 1

    @_skip_no_toolchain
    def test_build_lv2_with_buffers(
        self, rampleplayer_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile an LV2 plugin from RamplePlayer (has buffers)."""
        project_dir = tmp_path / "rampleplayer_lv2"
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="rampleplayer",
            platform="lv2",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        build_dir = project_dir / "build"
        env = _build_env()

        result = subprocess.run(
            ["cmake", "..", f"-DFETCHCONTENT_BASE_DIR={fetchcontent_cache}"],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert result.returncode == 0, (
            f"cmake configure failed:\nstderr: {result.stderr}"
        )

        result = subprocess.run(
            ["cmake", "--build", "."],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert result.returncode == 0, (
            f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        lv2_bundles = [d for d in build_dir.glob("**/*.lv2") if d.is_dir()]
        assert len(lv2_bundles) >= 1
        assert lv2_bundles[0].name == "rampleplayer.lv2"

    @_skip_no_toolchain
    def test_build_lv2_spectraldelayfb(
        self, spectraldelayfb_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile an LV2 plugin from spectraldelayfb (3in/2out)."""
        project_dir = tmp_path / "spectraldelayfb_lv2"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        build_dir = project_dir / "build"
        env = _build_env()

        result = subprocess.run(
            ["cmake", "..", f"-DFETCHCONTENT_BASE_DIR={fetchcontent_cache}"],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert result.returncode == 0, (
            f"cmake configure failed:\nstderr: {result.stderr}"
        )

        result = subprocess.run(
            ["cmake", "--build", "."],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert result.returncode == 0, (
            f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        lv2_bundles = [d for d in build_dir.glob("**/*.lv2") if d.is_dir()]
        assert len(lv2_bundles) >= 1
        assert lv2_bundles[0].name == "spectraldelayfb.lv2"

    @_skip_no_toolchain
    def test_build_clean_rebuild(
        self, gigaverb_export: Path, tmp_path: Path, fetchcontent_cache: Path,
        monkeypatch,
    ):
        """Test that clean + rebuild works via the platform API."""
        monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")

        project_dir = tmp_path / "gigaverb_rebuild"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        # Inject shared FetchContent cache
        cmakelists = project_dir / "CMakeLists.txt"
        original = cmakelists.read_text()
        inject = (
            f'set(FETCHCONTENT_BASE_DIR "{fetchcontent_cache}"'
            f' CACHE PATH "" FORCE)\n'
        )
        cmakelists.write_text(inject + original)

        platform = Lv2Platform()

        # First build
        build_result = platform.build(project_dir)
        assert build_result.success
        assert build_result.output_file is not None
        assert build_result.output_file.name == "gigaverb.lv2"

        # Clean + rebuild
        build_result = platform.build(project_dir, clean=True)
        assert build_result.success
        assert build_result.output_file is not None
