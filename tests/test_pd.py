"""Tests for PureData external platform implementation."""

import platform as sys_platform
import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    PureDataPlatform,
    get_platform,
)

# Skip conditions
_has_cxx = shutil.which("g++") is not None or shutil.which("clang++") is not None
_has_make = shutil.which("make") is not None
_has_pd = shutil.which("pd") is not None
_can_build = _has_cxx and _has_make

_skip_no_toolchain = pytest.mark.skipif(
    not _can_build, reason="C++ compiler or make not found"
)
_skip_no_pd = pytest.mark.skipif(
    not (_can_build and _has_pd), reason="C++ toolchain or pd not found"
)


def _validate_pd_external(project_dir: Path, lib_name: str) -> None:
    """Load a built PD external in headless PD and verify it instantiates.

    Creates a self-quitting patch containing the external object, runs PD
    in headless mode with -verbose, and checks that the external was
    loaded successfully (no "couldn't create" error).
    """
    if not _has_pd:
        return

    # Write a minimal self-quitting patch that instantiates the external
    test_pd = project_dir / "test_load.pd"
    test_pd.write_text(
        "#N canvas 0 0 450 300 10;\n"
        f"#X obj 10 10 {lib_name}~;\n"
        "#X obj 10 50 loadbang;\n"
        "#X msg 10 70 \\; pd quit;\n"
        "#X connect 1 0 2 0;\n"
    )

    result = subprocess.run(
        [
            "pd",
            "-nogui",
            "-noaudio",
            "-noadc",
            "-nodac",
            "-stderr",
            "-verbose",
            "-path",
            str(project_dir),
            str(test_pd),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"pd failed (exit {result.returncode}):\n{output}"
    assert "couldn't create" not in output, (
        f"PD failed to load {lib_name}~ external:\n{output}"
    )
    # Verify PD actually found and loaded the binary
    assert f"{lib_name}~" in output


class TestPdPlatform:
    """Test PureData platform registry and basic properties."""

    def test_registry_contains_pd(self):
        """Test that PureData is in the registry."""
        assert "pd" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["pd"] == PureDataPlatform

    def test_get_platform_pd(self):
        """Test getting PureData platform instance."""
        platform = get_platform("pd")
        assert isinstance(platform, PureDataPlatform)
        assert platform.name == "pd"

    def test_pd_extension(self):
        """Test that extension matches current platform."""
        platform = PureDataPlatform()
        system = sys_platform.system().lower()
        if system == "darwin":
            assert platform.extension == ".pd_darwin"
        elif system == "linux":
            assert platform.extension == ".pd_linux"

    def test_pd_build_instructions(self):
        """Test PD build instructions."""
        platform = PureDataPlatform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert len(instructions) > 0
        assert any("make" in instr for instr in instructions)


class TestPdProjectGeneration:
    """Test PureData project generation."""

    def test_generate_pd_project_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating PD project without buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="pd")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        assert project_dir.is_dir()
        assert (project_dir / "Makefile").is_file()
        assert (project_dir / "gen_dsp.cpp").is_file()
        assert (project_dir / "_ext.cpp").is_file()
        assert (project_dir / "_ext.h").is_file()
        assert (project_dir / "gen_ext_common.h").is_file()
        assert (project_dir / "pd_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()
        assert (project_dir / "pd-include" / "m_pd.h").is_file()
        assert (project_dir / "pd-lib-builder").is_dir()
        assert (project_dir / "gen").is_dir()

        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_pd_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating PD project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="pd",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_makefile_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has correct template substitutions."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="pd")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "lib.name = testverb" in makefile
        assert "gen.name = gen_exported" in makefile
        assert "GENLIB_USE_FLOAT32" in makefile
        assert "pd-lib-builder" in makefile

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="pd")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()


class TestPdBuildIntegration:
    """Integration tests that generate and compile a PD external.

    Skipped when no C++ compiler or make is available.
    """

    @_skip_no_toolchain
    def test_build_pd_no_buffers(self, gigaverb_export: Path, tmp_path: Path):
        """Generate and compile a PD external from gigaverb (no buffers)."""
        project_dir = tmp_path / "gigaverb_pd"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="pd")
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
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify external was produced
        platform = PureDataPlatform()
        output = platform.find_output(project_dir)
        assert output is not None
        assert output.stat().st_size > 0
        assert "gigaverb~" in output.name

        _validate_pd_external(project_dir, "gigaverb")

    @_skip_no_toolchain
    def test_build_pd_with_buffers(self, rampleplayer_export: Path, tmp_path: Path):
        """Generate and compile a PD external from RamplePlayer (has buffers)."""
        project_dir = tmp_path / "rampleplayer_pd"
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="rampleplayer",
            platform="pd",
            buffers=["sample"],
        )
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
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        platform = PureDataPlatform()
        output = platform.find_output(project_dir)
        assert output is not None
        assert "rampleplayer~" in output.name

        _validate_pd_external(project_dir, "rampleplayer")

    @_skip_no_toolchain
    def test_build_pd_spectraldelayfb(
        self, spectraldelayfb_export: Path, tmp_path: Path
    ):
        """Generate and compile a PD external from spectraldelayfb (3in/2out)."""
        project_dir = tmp_path / "spectraldelayfb_pd"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="pd")
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
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        platform = PureDataPlatform()
        output = platform.find_output(project_dir)
        assert output is not None
        assert "spectraldelayfb~" in output.name
        assert output.stat().st_size > 0

        _validate_pd_external(project_dir, "spectraldelayfb")

    @_skip_no_toolchain
    def test_build_clean_rebuild(self, gigaverb_export: Path, tmp_path: Path):
        """Test that clean + rebuild works via the platform API."""
        project_dir = tmp_path / "gigaverb_rebuild"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="pd")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        platform = PureDataPlatform()

        # First build
        build_result = platform.build(project_dir)
        assert build_result.success
        assert build_result.output_file is not None
        assert "gigaverb~" in build_result.output_file.name

        # Clean + rebuild
        build_result = platform.build(project_dir, clean=True)
        assert build_result.success
        assert build_result.output_file is not None

        _validate_pd_external(project_dir, "gigaverb")
