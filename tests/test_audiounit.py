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
        platform = AudioUnitPlatform()
        assert platform._detect_au_type(2) == "aufx"
        assert platform._detect_au_type(1) == "aufx"

    def test_detect_au_type_generator(self):
        """Test that inputs == 0 gives augn (generator)."""
        platform = AudioUnitPlatform()
        assert platform._detect_au_type(0) == "augn"

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
    def test_build_au_no_buffers(self, gigaverb_export: Path, tmp_path: Path):
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

    @_skip_no_toolchain
    def test_build_au_with_buffers(self, rampleplayer_export: Path, tmp_path: Path):
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

    @_skip_no_toolchain
    def test_build_au_spectraldelayfb(
        self, spectraldelayfb_export: Path, tmp_path: Path
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
