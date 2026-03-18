"""Tests for Csound opcode plugin platform implementation."""

import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    CsoundPlatform,
    get_platform,
)
from gen_dsp.platforms.csound import _build_type_strings

# Skip integration tests if csound headers / compiler not available
_has_cxx = shutil.which("c++") is not None or shutil.which("g++") is not None
_has_make = shutil.which("make") is not None
_csound_headers_exist = (
    Path("/Library/Frameworks/CsoundLib64.framework/Headers/csdl.h").exists()
    or Path("/usr/local/include/csound/csdl.h").exists()
    or Path("/usr/include/csound/csdl.h").exists()
)
_can_build = _has_cxx and _has_make and _csound_headers_exist
_skip_no_build = pytest.mark.skipif(
    not _can_build, reason="c++, make, or Csound headers not found"
)

_has_csound = shutil.which("csound") is not None
_can_validate = _can_build and _has_csound
_skip_no_validation = pytest.mark.skipif(
    not _can_validate, reason="csound binary not found"
)


class TestBuildTypeStrings:
    """Test OENTRY type string generation."""

    def test_stereo_effect_no_params(self):
        out, inp = _build_type_strings(2, 2, 0)
        assert out == "aa"
        assert inp == "aa"

    def test_stereo_effect_with_params(self):
        out, inp = _build_type_strings(2, 2, 4)
        assert out == "aa"
        assert inp == "aakkkk"

    def test_generator_with_params(self):
        out, inp = _build_type_strings(0, 1, 3)
        assert out == "a"
        assert inp == "kkk"

    def test_mono_effect_one_param(self):
        out, inp = _build_type_strings(1, 1, 1)
        assert out == "a"
        assert inp == "ak"

    def test_three_in_two_out(self):
        """spectraldelayfb-like: 3in/2out, no params."""
        out, inp = _build_type_strings(3, 2, 0)
        assert out == "aa"
        assert inp == "aaa"


class TestCsoundPlatform:
    """Test Csound platform registry and basic properties."""

    def test_registry_contains_csound(self):
        assert "csound" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["csound"] == CsoundPlatform

    def test_get_platform_csound(self):
        platform = get_platform("csound")
        assert isinstance(platform, CsoundPlatform)
        assert platform.name == "csound"

    def test_csound_extension(self):
        platform = CsoundPlatform()
        assert platform.extension in (".dylib", ".so")

    def test_csound_build_instructions(self):
        platform = CsoundPlatform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert "make all" in instructions


class TestCsoundProjectGeneration:
    """Test Csound opcode project generation."""

    def test_generate_project_gigaverb(self, gigaverb_export: Path, tmp_project: Path):
        """Test generating Csound opcode from gigaverb (stereo, 8 params)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="csound")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        assert project_dir.is_dir()

        # Check required files exist
        assert (project_dir / "Makefile").is_file()
        assert (project_dir / "gen_ext_csound.cpp").is_file()
        assert (project_dir / "_ext_csound.cpp").is_file()
        assert (project_dir / "_ext_csound.h").is_file()
        assert (project_dir / "gen_ext_common_csound.h").is_file()
        assert (project_dir / "csound_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()
        assert (project_dir / "gen").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating Csound opcode with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="csound",
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

        config = ProjectConfig(name="gigaverb", platform="csound")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "GENLIB_USE_FLOAT32" in makefile
        assert "CSOUND_EXT_NAME=gigaverb" in makefile
        assert "gen_ext_csound.cpp" in makefile
        assert "_ext_csound.cpp" in makefile
        assert "genlib.cpp" in makefile
        assert "CSOUND_INCLUDE" in makefile
        assert "-fPIC" in makefile
        assert "CSOUND_OPCODE_NAME" in makefile
        assert "CSOUND_OUTYPES" in makefile
        assert "CSOUND_INTYPES" in makefile

    def test_makefile_type_strings_gigaverb(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that Makefile has correct type strings for gigaverb (2in/2out/8params)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="csound")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        # gigaverb: 2 audio inputs, 2 audio outputs, 8 params
        assert 'CSOUND_OUTYPES=\\"aa\\"' in makefile
        assert 'CSOUND_INTYPES=\\"aakkkkkkkk\\"' in makefile

    def test_makefile_type_strings_spectraldelayfb(
        self, spectraldelayfb_export: Path, tmp_project: Path
    ):
        """Test type strings for spectraldelayfb (3in/2out/0params)."""
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="csound")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert 'CSOUND_OUTYPES=\\"aa\\"' in makefile
        assert 'CSOUND_INTYPES=\\"aaa\\"' in makefile

    def test_gen_ext_csound_cpp_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen_ext_csound.cpp has correct content."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="csound")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        content = (project_dir / "gen_ext_csound.cpp").read_text()
        assert "csdl.h" in content
        assert "OENTRY" in content
        assert "LINKAGE_BUILTIN" in content
        assert "gen_opcode_init" in content
        assert "gen_opcode_perf" in content
        assert "wrapper_create" in content
        assert "wrapper_perform" in content

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="csound")
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
        """Test that _ext_csound.h is generated from shared template."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="csound")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        header = (project_dir / "_ext_csound.h").read_text()
        assert "WRAPPER_NAMESPACE" in header
        assert "wrapper_create" in header
        assert "wrapper_perform" in header
        assert "CSOUND" in header


class TestCsoundBuildIntegration:
    """Integration tests that generate and compile Csound opcode plugins.

    Skipped when c++, make, or Csound headers are not available.
    """

    @_skip_no_build
    def test_build_gigaverb(self, gigaverb_export: Path, tmp_path: Path):
        """Generate and compile gigaverb Csound opcode."""
        project_dir = tmp_path / "gigaverb_csound"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="csound")
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

        # Verify shared library was produced
        libs = list(project_dir.glob("lib*.*"))
        assert len(libs) == 1
        assert libs[0].stat().st_size > 0

    @_skip_no_build
    def test_build_spectraldelayfb(self, spectraldelayfb_export: Path, tmp_path: Path):
        """Generate and compile spectraldelayfb (3in/2out) Csound opcode."""
        project_dir = tmp_path / "spectraldelayfb_csound"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="csound")
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

        libs = list(project_dir.glob("lib*.*"))
        assert len(libs) == 1
        assert libs[0].stat().st_size > 0

    @_skip_no_validation
    def test_validate_gigaverb(self, gigaverb_export: Path, tmp_path: Path):
        """Build gigaverb and validate with csound --opcode-list."""
        project_dir = tmp_path / "gigaverb_validate"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="csound")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        build_result = subprocess.run(
            ["make", "all"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert build_result.returncode == 0

        # Point Csound at the plugin directory and list opcodes
        import os

        env = os.environ.copy()
        env["OPCODE6DIR64"] = str(project_dir)

        result = subprocess.run(
            ["csound", "--list-opcodes"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        # csound --list-opcodes lists all opcodes including loaded plugins
        all_output = result.stdout + result.stderr
        assert "gigaverb" in all_output, (
            f"gigaverb opcode not found in csound --list-opcodes:\n{all_output[:2000]}"
        )
