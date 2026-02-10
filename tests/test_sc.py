"""Tests for SuperCollider UGen platform implementation."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    SuperColliderPlatform,
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


class TestScPlatform:
    """Test SuperCollider platform registry and basic properties."""

    def test_registry_contains_sc(self):
        """Test that SC is in the registry."""
        assert "sc" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["sc"] == SuperColliderPlatform

    def test_get_platform_sc(self):
        """Test getting SC platform instance."""
        platform = get_platform("sc")
        assert isinstance(platform, SuperColliderPlatform)
        assert platform.name == "sc"

    def test_sc_extension(self):
        """Test that extension is .scx on macOS or .so on Linux."""
        platform = SuperColliderPlatform()
        assert platform.extension in (".scx", ".so")

    def test_sc_build_instructions(self):
        """Test SC build instructions."""
        platform = SuperColliderPlatform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert len(instructions) > 0
        assert any("cmake" in instr for instr in instructions)

    def test_detect_plugin_type_effect(self):
        """Test that inputs > 0 gives effect."""
        platform = SuperColliderPlatform()
        assert platform._detect_plugin_type(2) == "effect"
        assert platform._detect_plugin_type(1) == "effect"

    def test_detect_plugin_type_generator(self):
        """Test that inputs == 0 gives generator."""
        platform = SuperColliderPlatform()
        assert platform._detect_plugin_type(0) == "generator"

    def test_capitalize_name(self):
        """Test first-letter capitalization for SC class names."""
        assert SuperColliderPlatform._capitalize_name("gigaverb") == "Gigaverb"
        assert SuperColliderPlatform._capitalize_name("myPlugin") == "MyPlugin"
        assert SuperColliderPlatform._capitalize_name("Already") == "Already"
        assert SuperColliderPlatform._capitalize_name("x") == "X"
        assert SuperColliderPlatform._capitalize_name("") == ""

    def test_sanitize_sc_arg(self):
        """Test SC argument name sanitization."""
        assert SuperColliderPlatform._sanitize_sc_arg("bandwidth") == "bandwidth"
        assert SuperColliderPlatform._sanitize_sc_arg("my_param") == "my_param"
        assert SuperColliderPlatform._sanitize_sc_arg("my param") == "my_param"
        assert SuperColliderPlatform._sanitize_sc_arg("0gain") == "p_0gain"

    def test_format_sc_number(self):
        """Test SC number formatting."""
        assert SuperColliderPlatform._format_sc_number(0.0) == "0"
        assert SuperColliderPlatform._format_sc_number(1.0) == "1"
        assert SuperColliderPlatform._format_sc_number(0.1) == "0.1"
        assert SuperColliderPlatform._format_sc_number(0.5) == "0.5"


class TestScParamParsing:
    """Test parameter metadata extraction from gen~ exports."""

    def test_parse_gigaverb_params(self, gigaverb_export: Path):
        """Test parsing parameters from gigaverb (8 params)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        platform = SuperColliderPlatform()
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

        platform = SuperColliderPlatform()
        params = platform._parse_params(export_info)

        assert len(params) == 0

    def test_parse_params_sorted_by_index(self, gigaverb_export: Path):
        """Test that parsed params are sorted by index."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        platform = SuperColliderPlatform()
        params = platform._parse_params(export_info)

        indices = [p.index for p in params]
        assert indices == sorted(indices)


class TestScProjectGeneration:
    """Test SuperCollider project generation."""

    def test_generate_sc_project_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating SC project without buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="sc")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check directory was created
        assert project_dir.is_dir()

        # Check required C++ files exist
        assert (project_dir / "CMakeLists.txt").is_file()
        assert (project_dir / "gen_ext_sc.cpp").is_file()
        assert (project_dir / "_ext_sc.cpp").is_file()
        assert (project_dir / "_ext_sc.h").is_file()
        assert (project_dir / "gen_ext_common_sc.h").is_file()
        assert (project_dir / "sc_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()

        # Check SC class file exists (capitalized name)
        assert (project_dir / "Testverb.sc").is_file()

        # Check gen export and build dir
        assert (project_dir / "gen").is_dir()
        assert (project_dir / "build").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_sc_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating SC project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="sc",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check gen_buffer.h has buffer configured
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_cmakelists_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test that CMakeLists.txt has correct template substitutions."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="sc")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "set(PROJECT_NAME testverb)" in cmake
        assert "SC_EXT_NAME=testverb" in cmake
        assert "SC_UGEN_NAME=Testverb" in cmake
        assert "GEN_EXPORTED_NAME=gen_exported" in cmake
        assert "GENLIB_USE_FLOAT32" in cmake
        assert "FetchContent_Declare" in cmake
        assert "supercollider" in cmake

    def test_cmakelists_num_io(self, gigaverb_export: Path, tmp_project: Path):
        """Test that CMakeLists.txt has correct I/O and param counts."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="sc")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert f"SC_NUM_INPUTS={export_info.num_inputs}" in cmake
        assert f"SC_NUM_OUTPUTS={export_info.num_outputs}" in cmake
        assert f"SC_NUM_PARAMS={export_info.num_params}" in cmake

    def test_sc_class_file_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test SC class file content for gigaverb (2in/2out/8params)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="sc")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        sc_class = (project_dir / "Testverb.sc").read_text()

        # Class definition
        assert "Testverb : MultiOutUGen {" in sc_class

        # *ar method with audio inputs and params
        assert "*ar {" in sc_class
        assert "in0" in sc_class
        assert "in1" in sc_class
        assert "bandwidth" in sc_class
        assert "multiNew('audio'" in sc_class

        # init method for MultiOutUGen
        assert "initOutputs(2, rate)" in sc_class

        # checkInputs for audio-rate validation
        assert "checkInputs" in sc_class
        assert "2.do" in sc_class

    def test_sc_class_file_no_audio_inputs(self, tmp_project: Path):
        """Test SC class file for a generator (0 audio inputs, 1 output).

        Uses _generate_sc_class directly since no fixture has 0 inputs + 1 output.
        """
        project_dir = tmp_project
        project_dir.mkdir(parents=True, exist_ok=True)

        platform = SuperColliderPlatform()
        platform._generate_sc_class(
            output_dir=project_dir,
            lib_name="testgen",
            ugen_name="Testgen",
            num_inputs=0,
            num_outputs=1,
            num_params=1,
            params=[],
        )

        sc_class = (project_dir / "Testgen.sc").read_text()

        # Should extend UGen (1 output)
        assert "Testgen : UGen {" in sc_class

        # No checkInputs since no audio inputs
        assert "checkInputs" not in sc_class

        # No initOutputs since single output
        assert "initOutputs" not in sc_class

        # Should still have *ar method with param
        assert "*ar {" in sc_class
        assert "multiNew('audio'" in sc_class

    def test_sc_class_file_multiout(
        self, spectraldelayfb_export: Path, tmp_project: Path
    ):
        """Test SC class file for multi-output (3in/2out)."""
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()
        assert export_info.num_outputs > 1

        config = ProjectConfig(name="specfb", platform="sc")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        sc_class = (project_dir / "Specfb.sc").read_text()

        # Should extend MultiOutUGen
        assert "Specfb : MultiOutUGen {" in sc_class

        # Should have initOutputs
        assert f"initOutputs({export_info.num_outputs}, rate)" in sc_class

        # Should have checkInputs for audio inputs
        assert "checkInputs" in sc_class
        assert f"{export_info.num_inputs}.do" in sc_class

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="sc")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()

    def test_cmakelists_shared_cache_off_by_default(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that default generation has shared cache OFF."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="sc")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(OFF)" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake

    def test_cmakelists_shared_cache_on(self, gigaverb_export: Path, tmp_project: Path):
        """Test that --shared-cache produces ON with resolved path."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="sc", shared_cache=True)
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(ON)" in cmake
        assert "gen-dsp" in cmake
        assert "fetchcontent" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake


class TestScBuildIntegration:
    """Integration tests that generate and compile a SuperCollider UGen.

    Skipped when no cmake/C++ compiler is available.
    """

    @_skip_no_toolchain
    def test_build_sc_no_buffers(
        self, gigaverb_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile an SC UGen from gigaverb (no buffers)."""
        project_dir = tmp_path / "gigaverb_sc"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="sc")
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

        # Verify binary was produced
        import sys

        ext = ".scx" if sys.platform == "darwin" else ".so"
        binaries = list(build_dir.glob(f"**/gigaverb{ext}"))
        assert len(binaries) >= 1

        # Verify .sc class file exists in project dir
        assert (project_dir / "Gigaverb.sc").is_file()

    @_skip_no_toolchain
    def test_build_sc_with_buffers(
        self, rampleplayer_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile an SC UGen from RamplePlayer (has buffers)."""
        project_dir = tmp_path / "rampleplayer_sc"
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="rampleplayer",
            platform="sc",
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

        import sys

        ext = ".scx" if sys.platform == "darwin" else ".so"
        binaries = list(build_dir.glob(f"**/rampleplayer{ext}"))
        assert len(binaries) >= 1

    @_skip_no_toolchain
    def test_build_sc_spectraldelayfb(
        self, spectraldelayfb_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile an SC UGen from spectraldelayfb (3in/2out)."""
        project_dir = tmp_path / "spectraldelayfb_sc"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="sc")
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

        import sys

        ext = ".scx" if sys.platform == "darwin" else ".so"
        binaries = list(build_dir.glob(f"**/spectraldelayfb{ext}"))
        assert len(binaries) >= 1

    @_skip_no_toolchain
    def test_build_clean_rebuild(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        monkeypatch,
    ):
        """Test that clean + rebuild works via the platform API."""
        monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")

        project_dir = tmp_path / "gigaverb_rebuild"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="sc")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        # Inject shared FetchContent cache
        cmakelists = project_dir / "CMakeLists.txt"
        original = cmakelists.read_text()
        inject = (
            f'set(FETCHCONTENT_BASE_DIR "{fetchcontent_cache}" CACHE PATH "" FORCE)\n'
        )
        cmakelists.write_text(inject + original)

        platform = SuperColliderPlatform()

        # First build
        build_result = platform.build(project_dir)
        assert build_result.success
        assert build_result.output_file is not None

        # Clean + rebuild
        build_result = platform.build(project_dir, clean=True)
        assert build_result.success
        assert build_result.output_file is not None
