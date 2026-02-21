"""Tests for AudioUnit (AUv2) platform implementation."""

import platform as sys_platform
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    AudioUnitPlatform,
    get_platform,
)

# Skip conditions
_is_macos = sys_platform.system() == "Darwin"
_has_cmake = shutil.which("cmake") is not None
_has_cxx = shutil.which("clang++") is not None or shutil.which("g++") is not None
_can_build = _is_macos and _has_cmake and _has_cxx

_skip_not_macos = pytest.mark.skipif(not _is_macos, reason="AudioUnit is macOS-only")
_skip_no_toolchain = pytest.mark.skipif(
    not _can_build, reason="macOS with cmake and C++ compiler required"
)

_has_auval = shutil.which("auval") is not None
_AU_COMPONENTS_DIR = Path.home() / "Library" / "Audio" / "Plug-Ins" / "Components"


def _validate_au(component_path: Path, lib_name: str) -> None:
    """Validate a built .component bundle with Apple's auval tool.

    Copies the component into ~/Library/Audio/Plug-Ins/Components/ so
    CoreAudio can discover it, runs auval -v, then cleans up.
    """
    if not _has_auval:
        return

    subtype = lib_name.lower()[:4].ljust(4, "x")
    dest = _AU_COMPONENTS_DIR / component_path.name

    try:
        _AU_COMPONENTS_DIR.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(component_path, dest)

        # Re-sign in place so CoreAudio accepts the bundle
        sign_result = subprocess.run(
            ["codesign", "-f", "-s", "-", str(dest)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert sign_result.returncode == 0, (
            f"codesign failed:\nstdout: {sign_result.stdout}\nstderr: {sign_result.stderr}"
        )

        # Give CoreAudio time to discover the component.  Retry once with
        # a longer sleep if the first attempt fails -- under heavy load the
        # initial scan can take longer than 10 seconds.
        result = None
        for wait in (10, 15):
            time.sleep(wait)
            result = subprocess.run(
                ["auval", "-v", "aufx", subtype, "Gdsp"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                break
        assert result is not None and result.returncode == 0, (
            f"auval validation failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    finally:
        if dest.exists():
            shutil.rmtree(dest)


def _validate_au_with_minihost(
    validate_fn,
    component_path: Path,
    lib_name: str,
    num_inputs: int,
    num_outputs: int,
    num_params: int = 0,
    send_midi: bool = False,
    check_energy: bool = True,
) -> None:
    """Install AU component and validate with minihost.

    Copies the component into ~/Library/Audio/Plug-Ins/Components/ so
    CoreAudio can discover it, runs minihost validation, then cleans up.

    ``validate_fn`` is the ``validate_minihost`` fixture callable.
    """
    try:
        import minihost  # noqa: F401
    except ImportError:
        return

    dest = _AU_COMPONENTS_DIR / component_path.name

    try:
        _AU_COMPONENTS_DIR.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(component_path, dest)

        # Re-sign so CoreAudio accepts the bundle
        subprocess.run(
            ["codesign", "-f", "-s", "-", str(dest)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Give CoreAudio time to discover the component
        time.sleep(10)

        validate_fn(
            dest,
            num_inputs,
            num_outputs,
            num_params=num_params,
            send_midi=send_midi,
            check_energy=check_energy,
        )
    finally:
        if dest.exists():
            shutil.rmtree(dest)


class TestAudioUnitPlatform:
    """Test AudioUnit platform registry and basic properties."""

    def test_registry_contains_au(self):
        """Test that AU is in the registry."""
        assert "au" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["au"] == AudioUnitPlatform

    def test_get_platform_au(self):
        """Test getting AudioUnit platform instance."""
        platform = get_platform("au")
        assert isinstance(platform, AudioUnitPlatform)
        assert platform.name == "au"

    def test_au_extension(self):
        """Test that extension is .component."""
        platform = AudioUnitPlatform()
        assert platform.extension == ".component"

    def test_au_build_instructions(self):
        """Test AudioUnit build instructions."""
        platform = AudioUnitPlatform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert len(instructions) > 0
        assert any("cmake" in instr for instr in instructions)

    def test_detect_au_type_effect(self):
        """Test that inputs > 0 gives aufx (effect)."""
        from gen_dsp.platforms.base import PluginCategory

        assert PluginCategory.from_num_inputs(2) == PluginCategory.EFFECT
        assert PluginCategory.from_num_inputs(1) == PluginCategory.EFFECT
        assert AudioUnitPlatform._AU_TYPE_MAP[PluginCategory.EFFECT] == "aufx"

    def test_detect_au_type_generator(self):
        """Test that inputs == 0 gives augn (generator)."""
        from gen_dsp.platforms.base import PluginCategory

        assert PluginCategory.from_num_inputs(0) == PluginCategory.GENERATOR
        assert AudioUnitPlatform._AU_TYPE_MAP[PluginCategory.GENERATOR] == "augn"

    def test_generate_subtype_normal(self):
        """Test subtype generation for normal names."""
        platform = AudioUnitPlatform()
        assert platform._generate_subtype("gigaverb") == "giga"
        assert platform._generate_subtype("testeffect") == "test"

    def test_generate_subtype_short_name(self):
        """Test subtype generation pads short names with 'x'."""
        platform = AudioUnitPlatform()
        assert platform._generate_subtype("fx") == "fxxx"
        assert platform._generate_subtype("a") == "axxx"

    def test_generate_subtype_exact_four(self):
        """Test subtype generation with exactly 4 chars."""
        platform = AudioUnitPlatform()
        assert platform._generate_subtype("verb") == "verb"

    def test_generate_subtype_uppercase(self):
        """Test subtype generation lowercases input."""
        platform = AudioUnitPlatform()
        assert platform._generate_subtype("MyEffect") == "myef"


class TestAudioUnitProjectGeneration:
    """Test AudioUnit project generation."""

    def test_generate_au_project_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating AudioUnit project without buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="au")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check directory was created
        assert project_dir.is_dir()

        # Check required files exist
        assert (project_dir / "CMakeLists.txt").is_file()
        assert (project_dir / "Info.plist").is_file()
        assert (project_dir / "gen_ext_au.cpp").is_file()
        assert (project_dir / "_ext_au.cpp").is_file()
        assert (project_dir / "_ext_au.h").is_file()
        assert (project_dir / "gen_ext_common_au.h").is_file()
        assert (project_dir / "au_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()
        assert (project_dir / "gen").is_dir()
        assert (project_dir / "build").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_au_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating AudioUnit project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="au",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check gen_buffer.h has buffer configured
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_generate_au_project_multiple_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating AudioUnit project with multiple buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="multibuf",
            platform="au",
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

        config = ProjectConfig(name="testverb", platform="au")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "set(PROJECT_NAME testverb)" in cmake
        assert "AU_EXT_NAME=testverb" in cmake
        assert "GEN_EXPORTED_NAME=gen_exported" in cmake
        assert "GENLIB_USE_FLOAT32" in cmake
        assert "AudioToolbox" in cmake
        assert "CoreFoundation" in cmake
        assert '.component"' in cmake

    def test_info_plist_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Info.plist has correct AU metadata."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="au")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        plist = (project_dir / "Info.plist").read_text()
        assert "<string>aufx</string>" in plist  # effect (has inputs)
        assert "<string>test</string>" in plist  # subtype: first 4 chars of "testverb"
        assert "<string>Gdsp</string>" in plist  # manufacturer
        assert "<string>AUGenFactory</string>" in plist  # factory function
        assert "<string>testverb</string>" in plist  # bundle name

    def test_aufx_type_for_effects(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gigaverb (has inputs) generates aufx type."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()
        assert export_info.num_inputs > 0

        config = ProjectConfig(name="testverb", platform="au")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        plist = (project_dir / "Info.plist").read_text()
        assert "<string>aufx</string>" in plist

    def test_augn_type_for_generators(self, gigaverb_export: Path, tmp_project: Path):
        """Test that 0 inputs generates augn type (using mock)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        # Mock 0 inputs to test generator type
        original_inputs = export_info.num_inputs
        export_info.num_inputs = 0

        config = ProjectConfig(name="testgen", platform="au")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        plist = (project_dir / "Info.plist").read_text()
        assert "<string>augn</string>" in plist

        # Restore
        export_info.num_inputs = original_inputs

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="au")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()

    def test_cmakelists_num_io(self, gigaverb_export: Path, tmp_project: Path):
        """Test that CMakeLists.txt has correct I/O counts."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="au")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert f"AU_NUM_INPUTS={export_info.num_inputs}" in cmake
        assert f"AU_NUM_OUTPUTS={export_info.num_outputs}" in cmake


class TestAudioUnitBuildIntegration:
    """Integration tests that generate and compile an AudioUnit.

    Skipped when not on macOS or no cmake/C++ compiler is available.
    """

    @_skip_no_toolchain
    def test_build_au_no_buffers(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        validate_minihost,
    ):
        """Generate and compile an AudioUnit from gigaverb (no buffers)."""
        project_dir = tmp_path / "gigaverb_au"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="au")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        build_dir = project_dir / "build"

        # Configure
        result = subprocess.run(
            ["cmake", ".."],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=60,
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
        )
        assert result.returncode == 0, (
            f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify .component bundle was produced
        component_files = list(build_dir.glob("**/*.component"))
        assert len(component_files) >= 1
        assert component_files[0].name == "gigaverb.component"

        _validate_au(component_files[0], "gigaverb")

        # Runtime validation via minihost
        _validate_au_with_minihost(
            validate_minihost,
            component_files[0],
            "gigaverb",
            2,
            2,
            num_params=8,
        )

    @_skip_no_toolchain
    def test_build_au_with_buffers(
        self,
        rampleplayer_export: Path,
        tmp_path: Path,
        validate_minihost,
    ):
        """Generate and compile an AudioUnit from RamplePlayer (has buffers)."""
        project_dir = tmp_path / "rampleplayer_au"
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="rampleplayer",
            platform="au",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        build_dir = project_dir / "build"

        result = subprocess.run(
            ["cmake", ".."],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=60,
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
        )
        assert result.returncode == 0, (
            f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        component_files = list(build_dir.glob("**/*.component"))
        assert len(component_files) >= 1
        assert component_files[0].name == "rampleplayer.component"

        _validate_au(component_files[0], "rampleplayer")

        # Runtime validation via minihost
        _validate_au_with_minihost(
            validate_minihost,
            component_files[0],
            "rampleplayer",
            1,
            2,
            num_params=0,
        )

    @_skip_no_toolchain
    def test_build_au_spectraldelayfb(
        self,
        spectraldelayfb_export: Path,
        tmp_path: Path,
    ):
        """Generate and compile an AudioUnit from spectraldelayfb (3in/2out, no buffers)."""
        project_dir = tmp_path / "spectraldelayfb_au"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="au")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        build_dir = project_dir / "build"

        result = subprocess.run(
            ["cmake", ".."],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=60,
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
        )
        assert result.returncode == 0, (
            f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        component_files = list(build_dir.glob("**/*.component"))
        assert len(component_files) >= 1
        assert component_files[0].name == "spectraldelayfb.component"

        # Verify it detected as effect (3 inputs > 0)
        plist = (project_dir / "Info.plist").read_text()
        assert "<string>aufx</string>" in plist

        _validate_au(component_files[0], "spectraldelayfb")

        # NOTE: minihost validation skipped for spectraldelayfb AU --
        # 3in/2out is a non-standard channel count that causes a segfault
        # in JUCE's AudioUnit host when processing audio.

    @_skip_no_toolchain
    def test_build_clean_rebuild(self, gigaverb_export: Path, tmp_path: Path):
        """Test that clean + rebuild works via the platform API."""
        project_dir = tmp_path / "gigaverb_rebuild"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="au")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        platform = AudioUnitPlatform()

        # First build
        build_result = platform.build(project_dir)
        assert build_result.success
        assert build_result.output_file is not None
        assert build_result.output_file.name == "gigaverb.component"

        # Clean + rebuild
        build_result = platform.build(project_dir, clean=True)
        assert build_result.success
        assert build_result.output_file is not None

        _validate_au(build_result.output_file, "gigaverb")

    @_skip_no_toolchain
    def test_build_au_polyphony(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        validate_minihost,
    ):
        """Generate and compile a polyphonic AudioUnit plugin (NUM_VOICES=4)."""
        from dataclasses import replace
        from gen_dsp.core.manifest import manifest_from_export_info
        from gen_dsp.core.midi import detect_midi_mapping
        from gen_dsp.platforms.base import Platform

        project_dir = tmp_path / "poly_au"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        # Create manifest but override num_inputs=0 so MIDI detection activates
        manifest = manifest_from_export_info(export_info, [], Platform.GENEXT_VERSION)
        manifest = replace(manifest, num_inputs=0)

        config = ProjectConfig(
            name="polyverb",
            platform="au",
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

        platform = AudioUnitPlatform()
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "build").mkdir()
        platform.generate_project(manifest, project_dir, "polyverb", config=config)

        # Copy gen~ export files (normally done by ProjectGenerator)
        shutil.copytree(gigaverb_export, project_dir / "gen")

        build_dir = project_dir / "build"

        # Configure
        result = subprocess.run(
            ["cmake", ".."],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=60,
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
        )
        assert result.returncode == 0, (
            f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify .component bundle was produced
        component_files = list(build_dir.glob("**/*.component"))
        assert len(component_files) >= 1
        assert component_files[0].name == "polyverb.component"

        # Runtime validation via minihost (check_energy=False: generator with no audio input)
        _validate_au_with_minihost(
            validate_minihost,
            component_files[0],
            "polyverb",
            0,
            2,
            num_params=8,
            check_energy=False,
        )


class TestAudioUnitMidiGeneration:
    """Test MIDI compile definitions in generated AudioUnit projects."""

    def test_cmakelists_no_midi_for_effects(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Effects (gigaverb has 2 inputs) should not get MIDI defines."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="au")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED" not in cmake
        assert "MIDI_GATE_IDX" not in cmake

        plist = (project_dir / "Info.plist").read_text()
        assert "<string>aufx</string>" in plist

    def test_cmakelists_midi_defines_with_explicit_mapping(self, tmp_path: Path):
        """Explicit --midi-* flags on a generator should produce MIDI defines."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping

        output_dir = tmp_path / "midi_au"
        output_dir.mkdir()

        platform = AudioUnitPlatform()
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
            platform="au",
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

    def test_aumu_type_for_midi_generators(self, tmp_path: Path):
        """MIDI-enabled generator should use aumu (music device) type."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping

        output_dir = tmp_path / "midi_au_aumu"
        output_dir.mkdir()

        platform = AudioUnitPlatform()
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
            platform="au",
            midi_gate="gate",
        )
        config.midi_mapping = detect_midi_mapping(
            manifest,
            midi_gate=config.midi_gate,
        )

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        plist = (output_dir / "Info.plist").read_text()
        assert "<string>aumu</string>" in plist
        # Should NOT have augn or aufx
        assert "<string>augn</string>" not in plist
        assert "<string>aufx</string>" not in plist

    def test_augn_without_midi(self, tmp_path: Path):
        """Generator without MIDI mapping should remain augn."""
        from gen_dsp.core.manifest import Manifest, ParamInfo

        output_dir = tmp_path / "no_midi_au"
        output_dir.mkdir()

        platform = AudioUnitPlatform()
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

        config = ProjectConfig(name="testgen", platform="au", no_midi=True)
        from gen_dsp.core.midi import detect_midi_mapping

        config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=config.no_midi,
        )

        platform.generate_project(manifest, output_dir, "testgen", config=config)

        plist = (output_dir / "Info.plist").read_text()
        assert "<string>augn</string>" in plist
        assert "<string>aumu</string>" not in plist

        cmake = (output_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED" not in cmake

    def test_cmakelists_polyphony_defines(self, tmp_path: Path):
        """NUM_VOICES=8 in CMakeLists when num_voices=8."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping
        from gen_dsp.platforms.audiounit import AudioUnitPlatform

        output_dir = tmp_path / "poly_au"
        output_dir.mkdir()

        platform = AudioUnitPlatform()
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
            platform="au",
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
        from gen_dsp.platforms.audiounit import AudioUnitPlatform

        output_dir = tmp_path / "poly_header"
        output_dir.mkdir()

        platform = AudioUnitPlatform()
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
            platform="au",
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
        from gen_dsp.platforms.audiounit import AudioUnitPlatform

        output_dir = tmp_path / "mono_header"
        output_dir.mkdir()

        platform = AudioUnitPlatform()
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
            platform="au",
            midi_gate="gate",
        )

        config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=config.no_midi,
            midi_gate=config.midi_gate,
        )

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        assert not (output_dir / "voice_alloc.h").exists()
