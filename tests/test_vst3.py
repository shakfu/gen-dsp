"""Tests for VST3 plugin platform implementation."""

import hashlib
import os
import shutil
import struct
import subprocess
import textwrap
from pathlib import Path
from typing import Optional

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    Vst3Platform,
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

# -- Persistent validator build directory (reused across sessions) -------------
_VALIDATOR_DIR = Path(__file__).resolve().parent.parent / "build" / ".vst3_validator"

_VALIDATOR_CMAKE_TEMPLATE = textwrap.dedent("""\
    cmake_minimum_required(VERSION 3.15)
    project(vst3_validator_build)

    include(FetchContent)
    FetchContent_Declare(
        vst3sdk
        GIT_REPOSITORY https://github.com/steinbergmedia/vst3sdk.git
        GIT_TAG v3.7.9_build_61
        GIT_SHALLOW ON
    )

    set(SMTG_ENABLE_VST3_HOSTING_EXAMPLES ON CACHE BOOL "" FORCE)
    set(SMTG_ENABLE_VST3_PLUGIN_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(SMTG_ENABLE_VSTGUI_SUPPORT OFF CACHE BOOL "" FORCE)
    set(SMTG_RUN_VST_VALIDATOR OFF CACHE BOOL "" FORCE)

    FetchContent_MakeAvailable(vst3sdk)
""")


@pytest.fixture(scope="session")
def vst3_validator(fetchcontent_cache: Path) -> Optional[Path]:
    """Build the VST3 SDK validator once per session.

    The validator binary persists in build/.vst3_validator/ so it is only
    compiled on first run.  Returns None (and prints a warning) if the
    build fails -- this lets the build integration tests still pass
    without validation.
    """
    if not _can_build:
        return None

    _VALIDATOR_DIR.mkdir(parents=True, exist_ok=True)
    build_dir = _VALIDATOR_DIR / "build"
    build_dir.mkdir(exist_ok=True)

    # Check for a previously built validator
    for candidate in build_dir.glob("**/validator"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    # Write the CMakeLists.txt that builds just the validator
    cmakelists = _VALIDATOR_DIR / "CMakeLists.txt"
    cmakelists.write_text(_VALIDATOR_CMAKE_TEMPLATE)

    env = _build_env()

    # Use FETCHCONTENT_SOURCE_DIR to reuse already-downloaded SDK source
    # without sharing the build tree (which causes cross-project
    # contamination when FETCHCONTENT_BASE_DIR is shared).
    cmake_configure = ["cmake", "..", "-DCMAKE_BUILD_TYPE=Release"]
    sdk_src = fetchcontent_cache / "vst3sdk-src"
    if sdk_src.is_dir():
        cmake_configure.append(f"-DFETCHCONTENT_SOURCE_DIR_VST3SDK={sdk_src}")

    # Configure
    result = subprocess.run(
        cmake_configure,
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    if result.returncode != 0:
        print(f"VST3 validator cmake configure failed:\n{result.stderr}")
        return None

    # Build only the validator target
    result = subprocess.run(
        ["cmake", "--build", ".", "--target", "validator"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    if result.returncode != 0:
        print(f"VST3 validator build failed:\n{result.stderr}")
        return None

    for candidate in build_dir.glob("**/validator"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    print("VST3 validator binary not found after build")
    return None


def _validate_vst3(validator: Optional[Path], vst3_bundle: Path) -> None:
    """Run the VST3 SDK validator against a bundle, if available."""
    if validator is None:
        return
    result = subprocess.run(
        [str(validator), str(vst3_bundle)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"VST3 validation failed:\n{result.stdout}\n{result.stderr}"
    )


class TestVst3Platform:
    """Test VST3 platform registry and basic properties."""

    def test_registry_contains_vst3(self):
        """Test that VST3 is in the registry."""
        assert "vst3" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["vst3"] == Vst3Platform

    def test_get_platform_vst3(self):
        """Test getting VST3 platform instance."""
        platform = get_platform("vst3")
        assert isinstance(platform, Vst3Platform)
        assert platform.name == "vst3"

    def test_vst3_extension(self):
        """Test that extension is .vst3."""
        platform = Vst3Platform()
        assert platform.extension == ".vst3"

    def test_vst3_build_instructions(self):
        """Test VST3 build instructions."""
        platform = Vst3Platform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert len(instructions) > 0
        assert any("cmake" in instr for instr in instructions)

    def test_fuid_generation_deterministic(self):
        """Test that FUID is deterministic for same name."""
        platform = Vst3Platform()
        fuid1 = platform._generate_fuid("testplugin")
        fuid2 = platform._generate_fuid("testplugin")
        assert fuid1 == fuid2

    def test_fuid_generation_different_names(self):
        """Test that different names produce different FUIDs."""
        platform = Vst3Platform()
        fuid1 = platform._generate_fuid("plugin_a")
        fuid2 = platform._generate_fuid("plugin_b")
        assert fuid1 != fuid2

    def test_fuid_returns_four_ints(self):
        """Test that FUID returns a tuple of 4 integers."""
        platform = Vst3Platform()
        fuid = platform._generate_fuid("testplugin")
        assert isinstance(fuid, tuple)
        assert len(fuid) == 4
        for val in fuid:
            assert isinstance(val, int)
            assert 0 <= val <= 0xFFFFFFFF

    def test_fuid_matches_md5(self):
        """Test that FUID matches MD5 of expected input string."""
        platform = Vst3Platform()
        name = "gigaverb"
        fuid = platform._generate_fuid(name)
        digest = hashlib.md5(f"com.gen-dsp.vst3.{name}".encode()).digest()
        expected = struct.unpack(">IIII", digest)
        assert fuid == expected


class TestVst3ProjectGeneration:
    """Test VST3 project generation."""

    def test_generate_vst3_project_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating VST3 project without buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vst3")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check directory was created
        assert project_dir.is_dir()

        # Check required files exist
        assert (project_dir / "CMakeLists.txt").is_file()
        assert (project_dir / "gen_ext_vst3.cpp").is_file()
        assert (project_dir / "_ext_vst3.cpp").is_file()
        assert (project_dir / "_ext_vst3.h").is_file()
        assert (project_dir / "gen_ext_common_vst3.h").is_file()
        assert (project_dir / "vst3_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()
        assert (project_dir / "gen").is_dir()
        assert (project_dir / "build").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_vst3_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating VST3 project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="vst3",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check gen_buffer.h has buffer configured
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_generate_vst3_project_multiple_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating VST3 project with multiple buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="multibuf",
            platform="vst3",
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

        config = ProjectConfig(name="testverb", platform="vst3")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "set(PROJECT_NAME testverb)" in cmake
        assert "VST3_EXT_NAME=testverb" in cmake
        assert "GEN_EXPORTED_NAME=gen_exported" in cmake
        assert "GENLIB_USE_FLOAT32" in cmake
        assert "FetchContent_Declare" in cmake
        assert "steinbergmedia/vst3sdk" in cmake
        assert "smtg_add_vst3plugin" in cmake

    def test_cmakelists_fuid(self, gigaverb_export: Path, tmp_project: Path):
        """Test that CMakeLists.txt has FUID defines."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vst3")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "VST3_FUID_0=0x" in cmake
        assert "VST3_FUID_1=0x" in cmake
        assert "VST3_FUID_2=0x" in cmake
        assert "VST3_FUID_3=0x" in cmake

    def test_cmakelists_num_io(self, gigaverb_export: Path, tmp_project: Path):
        """Test that CMakeLists.txt has correct I/O counts."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vst3")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert f"VST3_NUM_INPUTS={export_info.num_inputs}" in cmake
        assert f"VST3_NUM_OUTPUTS={export_info.num_outputs}" in cmake

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="vst3")
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

        config = ProjectConfig(name="testverb", platform="vst3")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(OFF)" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake

    def test_cmakelists_shared_cache_on(self, gigaverb_export: Path, tmp_project: Path):
        """Test that --shared-cache produces ON with resolved path."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="vst3", shared_cache=True)
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(ON)" in cmake
        assert "gen-dsp" in cmake
        assert "fetchcontent" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake


class TestVst3BuildIntegration:
    """Integration tests that generate and compile a VST3 plugin.

    Skipped when no cmake/C++ compiler is available.
    Note: First run requires network access to fetch VST3 SDK (~50MB).
    Uses a session-scoped FETCHCONTENT_BASE_DIR so the SDK is only
    downloaded once across all tests in the session.
    """

    @_skip_no_toolchain
    def test_build_vst3_no_buffers(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        vst3_validator: Optional[Path],
    ):
        """Generate and compile a VST3 plugin from gigaverb (no buffers)."""
        project_dir = tmp_path / "gigaverb_vst3"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="vst3")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        build_dir = project_dir / "build"
        env = _build_env()

        # Configure (share SDK cache across tests)
        result = subprocess.run(
            ["cmake", "..", f"-DFETCHCONTENT_BASE_DIR={fetchcontent_cache}"],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=300,
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
            timeout=300,
            env=env,
        )
        assert result.returncode == 0, (
            f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify .vst3 bundle was produced
        vst3_dirs = list(build_dir.glob("**/*.vst3"))
        assert len(vst3_dirs) >= 1
        assert any("gigaverb" in str(d) for d in vst3_dirs)

        # Validate against VST3 spec
        vst3_bundle = next(d for d in vst3_dirs if "gigaverb" in str(d))
        _validate_vst3(vst3_validator, vst3_bundle)

    @_skip_no_toolchain
    def test_build_vst3_with_buffers(
        self,
        rampleplayer_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        vst3_validator: Optional[Path],
    ):
        """Generate and compile a VST3 plugin from RamplePlayer (has buffers)."""
        project_dir = tmp_path / "rampleplayer_vst3"
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="rampleplayer",
            platform="vst3",
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
            timeout=300,
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
            timeout=300,
            env=env,
        )
        assert result.returncode == 0, (
            f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        vst3_dirs = list(build_dir.glob("**/*.vst3"))
        assert len(vst3_dirs) >= 1
        assert any("rampleplayer" in str(d) for d in vst3_dirs)

        vst3_bundle = next(d for d in vst3_dirs if "rampleplayer" in str(d))
        _validate_vst3(vst3_validator, vst3_bundle)

    @_skip_no_toolchain
    def test_build_vst3_spectraldelayfb(
        self,
        spectraldelayfb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        vst3_validator: Optional[Path],
    ):
        """Generate and compile a VST3 plugin from spectraldelayfb (3in/2out)."""
        project_dir = tmp_path / "spectraldelayfb_vst3"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="vst3")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        build_dir = project_dir / "build"
        env = _build_env()

        result = subprocess.run(
            ["cmake", "..", f"-DFETCHCONTENT_BASE_DIR={fetchcontent_cache}"],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=300,
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
            timeout=300,
            env=env,
        )
        assert result.returncode == 0, (
            f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        vst3_dirs = list(build_dir.glob("**/*.vst3"))
        assert len(vst3_dirs) >= 1
        assert any("spectraldelayfb" in str(d) for d in vst3_dirs)

        vst3_bundle = next(d for d in vst3_dirs if "spectraldelayfb" in str(d))
        _validate_vst3(vst3_validator, vst3_bundle)

    @_skip_no_toolchain
    def test_build_clean_rebuild(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        vst3_validator: Optional[Path],
        monkeypatch,
    ):
        """Test that clean + rebuild works via the platform API."""
        # Prevent git credential prompts in platform.build() subprocesses
        monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")

        project_dir = tmp_path / "gigaverb_rebuild"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="vst3")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        # Inject shared FETCHCONTENT_BASE_DIR into CMakeLists.txt so
        # platform.build() uses the cached SDK instead of re-downloading
        cmakelists = project_dir / "CMakeLists.txt"
        original = cmakelists.read_text()
        inject = (
            f'set(FETCHCONTENT_BASE_DIR "{fetchcontent_cache}" CACHE PATH "" FORCE)\n'
        )
        cmakelists.write_text(inject + original)

        platform = Vst3Platform()

        # First build
        build_result = platform.build(project_dir)
        assert build_result.success
        assert build_result.output_file is not None
        assert "gigaverb" in str(build_result.output_file)

        # Clean + rebuild
        build_result = platform.build(project_dir, clean=True)
        assert build_result.success
        assert build_result.output_file is not None

        # Validate the rebuilt bundle
        _validate_vst3(vst3_validator, build_result.output_file)
