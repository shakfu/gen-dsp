"""Tests for LV2 plugin platform implementation."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from tests.helpers import fetchcontent_cmake_args, validate_lv2

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    Lv2Platform,
    get_platform,
)


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

    def test_cmakelists_content(self, gigaverb_export: Path, tmp_project: Path):
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

    def test_cmakelists_num_io(self, gigaverb_export: Path, tmp_project: Path):
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

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
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

    def test_manifest_ttl_content(self, gigaverb_export: Path, tmp_project: Path):
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

    def test_plugin_ttl_ports(self, gigaverb_export: Path, tmp_project: Path):
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

    def test_plugin_ttl_effect_type(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gigaverb (has inputs) is EffectPlugin."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()
        assert export_info.num_inputs > 0

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        ttl = (project_dir / "testverb.ttl").read_text()
        assert "lv2:EffectPlugin" in ttl

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

    def test_cmakelists_shared_cache_on_by_default(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that default generation has shared cache ON."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(ON)" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake

    def test_cmakelists_shared_cache_off(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that --no-shared-cache produces OFF."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2", shared_cache=False)
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(OFF)" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake


class TestLv2BuildIntegration:
    """Integration tests that generate and compile an LV2 plugin.

    Skipped when no cmake/C++ compiler is available.
    """

    @_skip_no_toolchain
    def test_build_lv2_no_buffers(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
        validate_minihost,
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
            ["cmake", "..", *fetchcontent_cmake_args(fetchcontent_cache)],
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

        validate_lv2(lv2_validator, bundle, "gigaverb", 2, 2, 8)

        # Runtime validation via minihost
        validate_minihost(bundle, 2, 2, num_params=8)

    @_skip_no_toolchain
    def test_build_lv2_with_buffers(
        self,
        rampleplayer_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
        validate_minihost,
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
            ["cmake", "..", *fetchcontent_cmake_args(fetchcontent_cache)],
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

        validate_lv2(lv2_validator, lv2_bundles[0], "rampleplayer", 1, 2, 0)

        # Runtime validation via minihost
        validate_minihost(lv2_bundles[0], 1, 2, num_params=0)

    @_skip_no_toolchain
    def test_build_lv2_spectraldelayfb(
        self,
        spectraldelayfb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
        validate_minihost,
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
            ["cmake", "..", *fetchcontent_cmake_args(fetchcontent_cache)],
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

        validate_lv2(lv2_validator, lv2_bundles[0], "spectraldelayfb", 3, 2, 0)

        # Runtime validation via minihost
        validate_minihost(lv2_bundles[0], 3, 2, num_params=0)

    @_skip_no_toolchain
    @_skip_no_toolchain
    def test_build_lv2_polyphony(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
        validate_minihost,
    ):
        """Generate and compile a polyphonic LV2 plugin (NUM_VOICES=4)."""
        import shutil
        from dataclasses import replace
        from gen_dsp.core.manifest import manifest_from_export_info
        from gen_dsp.core.midi import detect_midi_mapping
        from gen_dsp.platforms.base import Platform

        project_dir = tmp_path / "poly_lv2"
        project_dir.mkdir(parents=True, exist_ok=True)
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        # Create manifest but override num_inputs=0 so MIDI detection activates
        manifest = manifest_from_export_info(export_info, [], Platform.GENEXT_VERSION)
        manifest = replace(manifest, num_inputs=0)

        config = ProjectConfig(
            name="polyverb",
            platform="lv2",
            midi_gate="damping",
            midi_freq="roomsize",
            num_voices=4,
        )
        config.midi_mapping = detect_midi_mapping(
            manifest,
            midi_gate=config.midi_gate,
            midi_freq=config.midi_freq,
        )
        config.midi_mapping.num_voices = config.num_voices

        platform = Lv2Platform()
        platform.generate_project(manifest, project_dir, "polyverb", config=config)

        # Copy gen~ export files (normally done by ProjectGenerator)
        shutil.copytree(gigaverb_export, project_dir / "gen")

        build_dir = project_dir / "build"
        env = _build_env()

        # Configure
        result = subprocess.run(
            ["cmake", "..", *fetchcontent_cmake_args(fetchcontent_cache)],
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
        assert bundle.name == "polyverb.lv2"
        # Check bundle contents
        assert (bundle / "manifest.ttl").is_file()
        assert (bundle / "polyverb.ttl").is_file()
        # Check binary exists (name varies by platform)
        binaries = list(bundle.glob("polyverb.*"))
        assert len(binaries) >= 1

        # Verify TTL has MIDI atom port and InstrumentPlugin type
        ttl = (bundle / "polyverb.ttl").read_text()
        assert "lv2:InstrumentPlugin" in ttl
        assert "atom:AtomPort" in ttl
        assert "midi:MidiEvent" in ttl

        # Verify CMakeLists has polyphony defines
        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "NUM_VOICES=4" in cmake
        assert "MIDI_ENABLED=1" in cmake

        # Validator: poly plugin is a generator (0 audio inputs) with MIDI.
        # The C validator checks audio port counts; for a poly generator the
        # expected audio_in is 0.  The atom MIDI port is not an audio port so
        # lilv won't count it.  gigaverb has 8 params.
        validate_lv2(lv2_validator, bundle, "polyverb", 0, 2, 8)

        # Runtime validation via minihost (check_energy=False: generator with no audio input)
        validate_minihost(bundle, 0, 2, num_params=8, check_energy=False)


class TestLv2MidiGeneration:
    """Test MIDI compile definitions and TTL in generated LV2 projects."""

    def test_cmakelists_no_midi_for_effects(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Effects (gigaverb has 2 inputs) should not get MIDI defines."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED" not in cmake
        assert "MIDI_GATE_IDX" not in cmake

        ttl = (project_dir / "testverb.ttl").read_text()
        assert "lv2:EffectPlugin" in ttl
        assert "atom:AtomPort" not in ttl
        assert "midi:MidiEvent" not in ttl

    def test_cmakelists_midi_defines_with_explicit_mapping(self, tmp_path: Path):
        """Explicit --midi-* flags on a generator should produce MIDI defines."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping

        output_dir = tmp_path / "midi_lv2"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_synth",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0,
                    name="gate",
                    has_minmax=True,
                    min=0.0,
                    max=1.0,
                    default=0.0,
                ),
                ParamInfo(
                    index=1,
                    name="freq",
                    has_minmax=True,
                    min=20.0,
                    max=20000.0,
                    default=440.0,
                ),
                ParamInfo(
                    index=2,
                    name="vel",
                    has_minmax=True,
                    min=0.0,
                    max=1.0,
                    default=0.0,
                ),
            ],
        )

        config = ProjectConfig(
            name="testsynth",
            platform="lv2",
            midi_gate="gate",
            midi_freq="freq",
            midi_vel="vel",
        )
        config.midi_mapping = detect_midi_mapping(
            manifest,
            midi_gate=config.midi_gate,
            midi_freq=config.midi_freq,
            midi_vel=config.midi_vel,
        )

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        cmake = (output_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED=1" in cmake
        assert "MIDI_GATE_IDX=0" in cmake
        assert "MIDI_FREQ_IDX=1" in cmake
        assert "MIDI_VEL_IDX=2" in cmake
        assert "MIDI_FREQ_UNIT_HZ=1" in cmake

    def test_ttl_instrument_type_with_midi(self, tmp_path: Path):
        """MIDI-enabled generator should use InstrumentPlugin type in TTL."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping

        output_dir = tmp_path / "midi_lv2_ttl"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_synth",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0,
                    name="gate",
                    has_minmax=True,
                    min=0.0,
                    max=1.0,
                    default=0.0,
                ),
            ],
        )

        config = ProjectConfig(
            name="testsynth",
            platform="lv2",
            midi_gate="gate",
        )
        config.midi_mapping = detect_midi_mapping(
            manifest,
            midi_gate=config.midi_gate,
        )

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        ttl = (output_dir / "testsynth.ttl").read_text()
        assert "lv2:InstrumentPlugin" in ttl
        assert "lv2:GeneratorPlugin" not in ttl

        # Check MIDI atom port is present
        assert "atom:AtomPort" in ttl
        assert "midi:MidiEvent" in ttl
        assert '"midi_in"' in ttl
        assert "urid:map" in ttl
        assert "atom:bufferType atom:Sequence" in ttl

    def test_ttl_generator_without_midi(self, tmp_path: Path):
        """Generator without MIDI mapping should remain GeneratorPlugin."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping

        output_dir = tmp_path / "no_midi_lv2"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_gen",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0,
                    name="volume",
                    has_minmax=True,
                    min=0.0,
                    max=1.0,
                    default=0.5,
                ),
            ],
        )

        config = ProjectConfig(name="testgen", platform="lv2", no_midi=True)
        config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=config.no_midi,
        )

        platform.generate_project(manifest, output_dir, "testgen", config=config)

        ttl = (output_dir / "testgen.ttl").read_text()
        assert "lv2:GeneratorPlugin" in ttl
        assert "lv2:InstrumentPlugin" not in ttl
        assert "atom:AtomPort" not in ttl
        assert "midi:MidiEvent" not in ttl

        cmake = (output_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED" not in cmake

    def test_cmakelists_polyphony_defines(self, tmp_path: Path):
        """NUM_VOICES=8 in CMakeLists when num_voices=8."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping
        from gen_dsp.platforms.lv2 import Lv2Platform

        output_dir = tmp_path / "poly_lv2"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_synth",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0, name="gate", has_minmax=True, min=0.0, max=1.0, default=0.0
                ),
                ParamInfo(
                    index=1,
                    name="freq",
                    has_minmax=True,
                    min=20.0,
                    max=20000.0,
                    default=440.0,
                ),
            ],
        )

        config = ProjectConfig(
            name="testsynth",
            platform="lv2",
            midi_gate="gate",
            midi_freq="freq",
            num_voices=8,
        )

        config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=config.no_midi,
            midi_gate=config.midi_gate,
            midi_freq=config.midi_freq,
            midi_vel=config.midi_vel,
            midi_freq_unit=config.midi_freq_unit,
        )
        config.midi_mapping.num_voices = config.num_voices

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        cmake = (output_dir / "CMakeLists.txt").read_text()
        assert "NUM_VOICES=8" in cmake
        assert "MIDI_ENABLED=1" in cmake

    def test_voice_alloc_header_copied(self, tmp_path: Path):
        """voice_alloc.h is copied when num_voices > 1."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping
        from gen_dsp.platforms.lv2 import Lv2Platform

        output_dir = tmp_path / "poly_header"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_synth",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0, name="gate", has_minmax=True, min=0.0, max=1.0, default=0.0
                ),
            ],
        )

        config = ProjectConfig(
            name="testsynth",
            platform="lv2",
            midi_gate="gate",
            num_voices=4,
        )

        config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=config.no_midi,
            midi_gate=config.midi_gate,
        )
        config.midi_mapping.num_voices = config.num_voices

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        assert (output_dir / "voice_alloc.h").is_file()

    def test_no_voice_alloc_header_mono(self, tmp_path: Path):
        """voice_alloc.h is NOT copied when num_voices=1 (mono)."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping
        from gen_dsp.platforms.lv2 import Lv2Platform

        output_dir = tmp_path / "mono_header"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_synth",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0, name="gate", has_minmax=True, min=0.0, max=1.0, default=0.0
                ),
            ],
        )

        config = ProjectConfig(
            name="testsynth",
            platform="lv2",
            midi_gate="gate",
        )

        config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=config.no_midi,
            midi_gate=config.midi_gate,
        )

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        assert not (output_dir / "voice_alloc.h").exists()
