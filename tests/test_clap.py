"""Tests for CLAP plugin platform implementation."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    ClapPlatform,
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
_has_cargo = shutil.which("cargo") is not None
_can_build = _has_cmake and _has_cxx

_skip_no_toolchain = pytest.mark.skipif(
    not _can_build, reason="cmake and C++ compiler required"
)

# -- Persistent CLAP validator build directory (reused across sessions) --------
_VALIDATOR_DIR = Path(__file__).resolve().parent.parent / "build" / ".clap_validator"


@pytest.fixture(scope="session")
def clap_validator() -> Optional[Path]:
    """Build the clap-validator once per session.

    The validator binary persists in build/.clap_validator/ so it is only
    compiled on first run.  Returns None (and prints a warning) if the
    build fails -- this lets the build integration tests still pass
    without validation.
    """
    if not _can_build or not _has_cargo:
        return None

    src_dir = _VALIDATOR_DIR / "src"
    binary = src_dir / "target" / "release" / "clap-validator"

    # Check for a previously built validator
    if binary.is_file() and os.access(binary, os.X_OK):
        return binary

    # Clone and build clap-validator
    _VALIDATOR_DIR.mkdir(parents=True, exist_ok=True)

    if not (src_dir / "Cargo.toml").is_file():
        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://github.com/free-audio/clap-validator.git",
                str(src_dir),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"clap-validator clone failed:\n{result.stderr}")
            return None

    result = subprocess.run(
        ["cargo", "build", "--release"],
        cwd=src_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        print(f"clap-validator build failed:\n{result.stderr}")
        return None

    if binary.is_file() and os.access(binary, os.X_OK):
        return binary

    print("clap-validator binary not found after build")
    return None


def _validate_clap(validator: Optional[Path], clap_bundle: Path) -> None:
    """Run the CLAP validator against a plugin, if available."""
    if validator is None:
        return
    result = subprocess.run(
        [str(validator), "validate", str(clap_bundle)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    # Check for failures in output (validator returns 0 even with warnings)
    assert "0 failed" in result.stdout, (
        f"CLAP validation failed:\n{result.stdout}\n{result.stderr}"
    )
    assert result.returncode == 0, (
        f"CLAP validation failed:\n{result.stdout}\n{result.stderr}"
    )


class TestClapPlatform:
    """Test CLAP platform registry and basic properties."""

    def test_registry_contains_clap(self):
        """Test that CLAP is in the registry."""
        assert "clap" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["clap"] == ClapPlatform

    def test_get_platform_clap(self):
        """Test getting CLAP platform instance."""
        platform = get_platform("clap")
        assert isinstance(platform, ClapPlatform)
        assert platform.name == "clap"

    def test_clap_extension(self):
        """Test that extension is .clap."""
        platform = ClapPlatform()
        assert platform.extension == ".clap"

    def test_clap_build_instructions(self):
        """Test CLAP build instructions."""
        platform = ClapPlatform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert len(instructions) > 0
        assert any("cmake" in instr for instr in instructions)

    def test_detect_plugin_type_effect(self):
        """Test that inputs > 0 gives effect."""
        platform = ClapPlatform()
        assert platform._detect_plugin_type(2) == "effect"
        assert platform._detect_plugin_type(1) == "effect"

    def test_detect_plugin_type_instrument(self):
        """Test that inputs == 0 gives instrument."""
        platform = ClapPlatform()
        assert platform._detect_plugin_type(0) == "instrument"


class TestClapProjectGeneration:
    """Test CLAP project generation."""

    def test_generate_clap_project_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating CLAP project without buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="clap")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check directory was created
        assert project_dir.is_dir()

        # Check required files exist
        assert (project_dir / "CMakeLists.txt").is_file()
        assert (project_dir / "gen_ext_clap.cpp").is_file()
        assert (project_dir / "_ext_clap.cpp").is_file()
        assert (project_dir / "_ext_clap.h").is_file()
        assert (project_dir / "gen_ext_common_clap.h").is_file()
        assert (project_dir / "clap_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()
        assert (project_dir / "gen").is_dir()
        assert (project_dir / "build").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_clap_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating CLAP project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="clap",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check gen_buffer.h has buffer configured
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_generate_clap_project_multiple_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating CLAP project with multiple buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="multibuf",
            platform="clap",
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

        config = ProjectConfig(name="testverb", platform="clap")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "set(PROJECT_NAME testverb)" in cmake
        assert "CLAP_EXT_NAME=testverb" in cmake
        assert "GEN_EXPORTED_NAME=gen_exported" in cmake
        assert "GENLIB_USE_FLOAT32" in cmake
        assert "FetchContent_Declare" in cmake
        assert "free-audio/clap" in cmake
        assert '".clap"' in cmake

    def test_cmakelists_num_io(self, gigaverb_export: Path, tmp_project: Path):
        """Test that CMakeLists.txt has correct I/O counts."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="clap")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert f"CLAP_NUM_INPUTS={export_info.num_inputs}" in cmake
        assert f"CLAP_NUM_OUTPUTS={export_info.num_outputs}" in cmake

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="clap")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()

    def test_effect_type_for_inputs(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gigaverb (has inputs) is detected as effect."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()
        assert export_info.num_inputs > 0

        platform = ClapPlatform()
        assert platform._detect_plugin_type(export_info.num_inputs) == "effect"

    def test_instrument_type_for_no_inputs(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that 0 inputs gives instrument type."""
        platform = ClapPlatform()
        assert platform._detect_plugin_type(0) == "instrument"

    def test_cmakelists_shared_cache_off_by_default(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that default generation has shared cache OFF."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="clap")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(OFF)" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake

    def test_cmakelists_shared_cache_on(self, gigaverb_export: Path, tmp_project: Path):
        """Test that --shared-cache produces ON with resolved path."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="clap", shared_cache=True)
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(ON)" in cmake
        assert "gen-dsp" in cmake
        assert "fetchcontent" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake


class TestClapBuildIntegration:
    """Integration tests that generate and compile a CLAP plugin.

    Skipped when no cmake/C++ compiler is available.
    """

    @_skip_no_toolchain
    def test_build_clap_no_buffers(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ):
        """Generate and compile a CLAP plugin from gigaverb (no buffers)."""
        project_dir = tmp_path / "gigaverb_clap"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="clap")
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

        # Verify .clap file was produced
        clap_files = list(build_dir.glob("**/*.clap"))
        assert len(clap_files) >= 1
        assert clap_files[0].name == "gigaverb.clap"

        # Validate against CLAP spec
        _validate_clap(clap_validator, clap_files[0])

    @_skip_no_toolchain
    def test_build_clap_with_buffers(
        self,
        rampleplayer_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ):
        """Generate and compile a CLAP plugin from RamplePlayer (has buffers)."""
        project_dir = tmp_path / "rampleplayer_clap"
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="rampleplayer",
            platform="clap",
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

        clap_files = list(build_dir.glob("**/*.clap"))
        assert len(clap_files) >= 1
        assert clap_files[0].name == "rampleplayer.clap"

        _validate_clap(clap_validator, clap_files[0])

    @_skip_no_toolchain
    def test_build_clap_spectraldelayfb(
        self,
        spectraldelayfb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ):
        """Generate and compile a CLAP plugin from spectraldelayfb (3in/2out)."""
        project_dir = tmp_path / "spectraldelayfb_clap"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="clap")
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

        clap_files = list(build_dir.glob("**/*.clap"))
        assert len(clap_files) >= 1
        assert clap_files[0].name == "spectraldelayfb.clap"

        _validate_clap(clap_validator, clap_files[0])

    @_skip_no_toolchain
    def test_build_clean_rebuild(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
        monkeypatch,
    ):
        """Test that clean + rebuild works via the platform API."""
        monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")

        project_dir = tmp_path / "gigaverb_rebuild"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="clap")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        # Inject shared FetchContent cache
        cmakelists = project_dir / "CMakeLists.txt"
        original = cmakelists.read_text()
        inject = (
            f'set(FETCHCONTENT_BASE_DIR "{fetchcontent_cache}" CACHE PATH "" FORCE)\n'
        )
        cmakelists.write_text(inject + original)

        platform = ClapPlatform()

        # First build
        build_result = platform.build(project_dir)
        assert build_result.success
        assert build_result.output_file is not None
        assert build_result.output_file.name == "gigaverb.clap"

        # Clean + rebuild
        build_result = platform.build(project_dir, clean=True)
        assert build_result.success
        assert build_result.output_file is not None

        # Validate the rebuilt bundle
        _validate_clap(clap_validator, build_result.output_file)
