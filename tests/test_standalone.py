"""Tests for standalone audio application platform implementation."""

import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    StandalonePlatform,
    get_platform,
)

# Skip integration tests if compiler not available
_has_cxx = shutil.which("c++") is not None or shutil.which("g++") is not None
_has_make = shutil.which("make") is not None
_has_curl = shutil.which("curl") is not None
_can_build = _has_cxx and _has_make and _has_curl
_skip_no_build = pytest.mark.skipif(
    not _can_build, reason="c++, make, or curl not found"
)


class TestStandalonePlatform:
    """Test standalone platform registry and basic properties."""

    def test_registry_contains_standalone(self):
        """Test that standalone is in the registry."""
        assert "standalone" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["standalone"] == StandalonePlatform

    def test_get_platform_standalone(self):
        """Test getting standalone platform instance."""
        platform = get_platform("standalone")
        assert isinstance(platform, StandalonePlatform)
        assert platform.name == "standalone"

    def test_standalone_extension(self):
        """Test that extension is empty on Unix."""
        platform = StandalonePlatform()
        # On macOS/Linux the extension is empty
        assert platform.extension == "" or platform.extension == ".exe"

    def test_standalone_build_instructions(self):
        """Test standalone build instructions."""
        platform = StandalonePlatform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert "make all" in instructions


class TestStandaloneProjectGeneration:
    """Test standalone project generation."""

    def test_generate_project_gigaverb(self, gigaverb_export: Path, tmp_project: Path):
        """Test generating standalone project from gigaverb (no buffers)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="standalone")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        assert project_dir.is_dir()

        # Check required files exist
        assert (project_dir / "Makefile").is_file()
        assert (project_dir / "gen_ext_standalone.cpp").is_file()
        assert (project_dir / "_ext_standalone.cpp").is_file()
        assert (project_dir / "_ext_standalone.h").is_file()
        assert (project_dir / "gen_ext_common_standalone.h").is_file()
        assert (project_dir / "standalone_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()
        assert (project_dir / "gen").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating standalone project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="standalone",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_makefile_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has correct content."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="standalone")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "GENLIB_USE_FLOAT32" in makefile
        assert "STANDALONE_EXT_NAME=testverb" in makefile
        assert "miniaudio.h" in makefile
        assert "gen_ext_standalone.cpp" in makefile
        assert "_ext_standalone.cpp" in makefile
        assert "genlib.cpp" in makefile

    def test_gen_ext_standalone_cpp_content(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that gen_ext_standalone.cpp has correct content."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="standalone")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        content = (project_dir / "gen_ext_standalone.cpp").read_text()
        assert "miniaudio.h" in content
        assert "MINIAUDIO_IMPLEMENTATION" in content
        assert "audio_callback" in content
        assert "wrapper_create" in content
        assert "wrapper_perform" in content
        assert "ma_device" in content
        assert "STANDALONE_EXT_NAME" in content

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="standalone")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()

    def test_ext_header_uses_shared_template(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that _ext_standalone.h is generated from shared template."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="standalone")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        header = (project_dir / "_ext_standalone.h").read_text()
        assert "WRAPPER_NAMESPACE" in header
        assert "wrapper_create" in header
        assert "wrapper_perform" in header
        assert "STANDALONE" in header


class TestStandaloneBuildIntegration:
    """Integration tests that generate and compile standalone executables.

    Skipped when c++, make, or curl is not available.
    """

    @_skip_no_build
    def test_build_gigaverb(self, gigaverb_export: Path, tmp_path: Path):
        """Generate and compile gigaverb standalone executable."""
        project_dir = tmp_path / "gigaverb_standalone"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="standalone")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        result = subprocess.run(
            ["make", "all"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify executable was produced
        exe = project_dir / "gigaverb"
        assert exe.is_file()
        assert exe.stat().st_size > 0

    @_skip_no_build
    def test_build_spectraldelayfb(self, spectraldelayfb_export: Path, tmp_path: Path):
        """Generate and compile spectraldelayfb (3in/2out) standalone."""
        project_dir = tmp_path / "spectraldelayfb_standalone"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="standalone")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        result = subprocess.run(
            ["make", "all"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        exe = project_dir / "spectraldelayfb"
        assert exe.is_file()
        assert exe.stat().st_size > 0

    @_skip_no_build
    def test_list_params(self, gigaverb_export: Path, tmp_path: Path):
        """Build gigaverb and verify -l flag lists parameters."""
        project_dir = tmp_path / "gigaverb_params"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="standalone")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        build_result = subprocess.run(
            ["make", "all"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert build_result.returncode == 0, (
            f"make all failed:\nstdout: {build_result.stdout}\n"
            f"stderr: {build_result.stderr}"
        )

        # Run with -l to list params
        result = subprocess.run(
            ["./gigaverb", "-l"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"-l failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        output = result.stdout
        assert "Parameters" in output
        assert "roomsize" in output
        assert "revtime" in output
        assert "Audio I/O" in output
