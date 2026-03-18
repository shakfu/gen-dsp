"""Tests for Audio Unit v3 (AUv3) platform implementation."""

import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    Auv3Platform,
    get_platform,
)

# AUv3 requires macOS + Xcode + CMake
import platform as sys_platform

_is_macos = sys_platform.system() == "Darwin"
_has_cmake = shutil.which("cmake") is not None
# Check for Xcode generator support (requires full Xcode, not just CLI tools)
_has_xcode = False
if _is_macos and _has_cmake:
    try:
        r = subprocess.run(
            ["cmake", "--help"],
            capture_output=True, text=True, timeout=5,
        )
        _has_xcode = "Xcode" in r.stdout
    except Exception:
        pass

_can_build = _is_macos and _has_cmake and _has_xcode
_skip_no_build = pytest.mark.skipif(
    not _can_build, reason="macOS + CMake + Xcode generator required"
)


class TestAuv3Platform:
    """Test AUv3 platform registry and basic properties."""

    def test_registry_contains_auv3(self):
        assert "auv3" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["auv3"] == Auv3Platform

    def test_get_platform_auv3(self):
        platform = get_platform("auv3")
        assert isinstance(platform, Auv3Platform)
        assert platform.name == "auv3"

    def test_auv3_extension(self):
        platform = Auv3Platform()
        assert platform.extension == ".app"

    def test_auv3_build_instructions(self):
        platform = Auv3Platform()
        instructions = platform.get_build_instructions()
        assert any("Xcode" in i for i in instructions)


class TestAuv3ProjectGeneration:
    """Test AUv3 project generation."""

    def test_generate_project_gigaverb(self, gigaverb_export: Path, tmp_project: Path):
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="auv3")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        assert project_dir.is_dir()
        assert (project_dir / "CMakeLists.txt").is_file()
        assert (project_dir / "gen_ext_auv3.mm").is_file()
        assert (project_dir / "_ext_auv3.cpp").is_file()
        assert (project_dir / "_ext_auv3.h").is_file()
        assert (project_dir / "gen_ext_common_auv3.h").is_file()
        assert (project_dir / "auv3_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()
        assert (project_dir / "Info-AUv3.plist").is_file()
        assert (project_dir / "Info-App.plist").is_file()
        assert (project_dir / "gen").is_dir()

    def test_generate_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler", platform="auv3", buffers=["sample"]
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_cmakelists_content(self, gigaverb_export: Path, tmp_project: Path):
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="auv3")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "GENLIB_USE_FLOAT32" in cmake
        assert "AUV3_EXT_NAME=gigaverb" in cmake
        assert "gen_ext_auv3.mm" in cmake
        assert "_ext_auv3.cpp" in cmake
        assert "com.apple.product-type.app-extension" in cmake
        assert "XCODE_EMBED_APP_EXTENSIONS" in cmake
        assert "AudioToolbox" in cmake
        assert "AVFoundation" in cmake

    def test_info_plist_auv3_content(self, gigaverb_export: Path, tmp_project: Path):
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="auv3")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        plist = (project_dir / "Info-AUv3.plist").read_text()
        assert "NSExtension" in plist
        assert "com.apple.AudioUnit" in plist
        assert "GenDspAUv3Factory" in plist
        assert "aufx" in plist  # gigaverb is an effect
        assert "Gdsp" in plist  # manufacturer
        assert "giga" in plist  # subtype (first 4 chars)
        assert "Effects" in plist  # tag

    def test_info_plist_app_content(self, gigaverb_export: Path, tmp_project: Path):
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="auv3")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        plist = (project_dir / "Info-App.plist").read_text()
        assert "APPL" in plist
        assert "com.gen-dsp.gigaverb" in plist

    def test_gen_ext_auv3_mm_content(self, gigaverb_export: Path, tmp_project: Path):
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="auv3")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        content = (project_dir / "gen_ext_auv3.mm").read_text()
        assert "AUAudioUnit" in content
        assert "AUAudioUnitFactory" in content
        assert "internalRenderBlock" in content
        assert "wrapper_create" in content
        assert "wrapper_perform" in content
        assert "AUParameterTree" in content


class TestAuv3BuildIntegration:
    """Integration tests requiring macOS + Xcode + CMake."""

    @_skip_no_build
    def test_build_gigaverb(self, gigaverb_export: Path, tmp_path: Path):
        project_dir = tmp_path / "gigaverb_auv3"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="auv3")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        platform = Auv3Platform()
        result = platform.build(project_dir, verbose=False)

        assert result.success, (
            f"AUv3 build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert result.output_file is not None
        assert result.output_file.exists()
        assert result.output_file.name.endswith("-Host.app")

        # Verify .appex is embedded
        appex_matches = list(result.output_file.glob("**/*.appex"))
        assert len(appex_matches) >= 1, "No .appex found inside .app"
