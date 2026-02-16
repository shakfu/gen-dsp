"""Tests for platform registry and platform implementations."""

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    PureDataPlatform,
    MaxPlatform,
    get_platform,
    get_platform_class,
    list_platforms,
    is_valid_platform,
)


class TestPlatformRegistry:
    """Test platform registry functions."""

    def test_registry_contains_pd(self):
        """Test that PureData is in the registry."""
        assert "pd" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["pd"] == PureDataPlatform

    def test_registry_contains_max(self):
        """Test that Max is in the registry."""
        assert "max" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["max"] == MaxPlatform

    def test_get_platform_pd(self):
        """Test getting PureData platform instance."""
        platform = get_platform("pd")
        assert isinstance(platform, PureDataPlatform)
        assert platform.name == "pd"

    def test_get_platform_max(self):
        """Test getting Max platform instance."""
        platform = get_platform("max")
        assert isinstance(platform, MaxPlatform)
        assert platform.name == "max"

    def test_get_platform_invalid(self):
        """Test getting invalid platform raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_platform("invalid")
        assert "Unknown platform" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_get_platform_class_pd(self):
        """Test getting PureData platform class."""
        cls = get_platform_class("pd")
        assert cls == PureDataPlatform

    def test_get_platform_class_invalid(self):
        """Test getting invalid platform class raises ValueError."""
        with pytest.raises(ValueError):
            get_platform_class("invalid")

    def test_list_platforms(self):
        """Test listing all platforms."""
        platforms = list_platforms()
        assert isinstance(platforms, list)
        assert "pd" in platforms
        assert "max" in platforms
        # List should be sorted
        assert platforms == sorted(platforms)

    def test_is_valid_platform_pd(self):
        """Test checking valid platform."""
        assert is_valid_platform("pd") is True

    def test_is_valid_platform_max(self):
        """Test checking valid platform."""
        assert is_valid_platform("max") is True

    def test_is_valid_platform_invalid(self):
        """Test checking invalid platform."""
        assert is_valid_platform("invalid") is False


class TestPlatformBase:
    """Test Platform base class."""

    def test_platform_has_required_attributes(self):
        """Test that platforms have required attributes."""
        for name in list_platforms():
            platform = get_platform(name)
            assert hasattr(platform, "name")
            assert hasattr(platform, "extension")
            assert hasattr(platform, "GENEXT_VERSION")

    def test_platform_has_required_methods(self):
        """Test that platforms have required methods."""
        for name in list_platforms():
            platform = get_platform(name)
            assert callable(getattr(platform, "generate_project", None))
            assert callable(getattr(platform, "build", None))
            assert callable(getattr(platform, "clean", None))
            assert callable(getattr(platform, "find_output", None))
            assert callable(getattr(platform, "get_build_instructions", None))

    def test_platform_get_build_instructions_returns_list(self):
        """Test that get_build_instructions returns a list."""
        for name in list_platforms():
            platform = get_platform(name)
            instructions = platform.get_build_instructions()
            assert isinstance(instructions, list)
            assert len(instructions) > 0
            for instruction in instructions:
                assert isinstance(instruction, str)


class TestPureDataPlatform:
    """Test PureData-specific functionality."""

    def test_pd_extension_is_platform_specific(self):
        """Test that extension is OS-specific."""
        platform = PureDataPlatform()
        ext = platform.extension
        assert ext in [".pd_darwin", ".pd_linux", ".dll"]

    def test_pd_build_instructions(self):
        """Test PureData build instructions."""
        platform = PureDataPlatform()
        instructions = platform.get_build_instructions()
        assert "make all" in instructions


class TestMaxPlatform:
    """Test Max-specific functionality."""

    def test_max_extension_is_platform_specific(self):
        """Test that extension is OS-specific."""
        platform = MaxPlatform()
        ext = platform.extension
        assert ext in [".mxo", ".mxe64", ".mxl"]

    def test_max_build_instructions(self):
        """Test Max build instructions."""
        platform = MaxPlatform()
        instructions = platform.get_build_instructions()
        assert any("cmake" in instr for instr in instructions)
        assert any("max-sdk-base" in instr for instr in instructions)


# Map platform keys to the build system file they generate.
_BUILD_SYSTEM_FILES = {
    "pd": "Makefile",
    "max": "CMakeLists.txt",
    "chuck": "makefile",
    "au": "CMakeLists.txt",
    "clap": "CMakeLists.txt",
    "vst3": "CMakeLists.txt",
    "lv2": "CMakeLists.txt",
    "sc": "CMakeLists.txt",
    "vcvrack": "Makefile",
    "daisy": "Makefile",
    "circle": "Makefile",
}


def _generate_project(platform_key, export_path, tmp_path, buffers=None):
    """Helper: generate a project for the given platform and export."""
    parser = GenExportParser(export_path)
    export_info = parser.parse()
    config = ProjectConfig(
        name="testlib",
        platform=platform_key,
        buffers=buffers or [],
    )
    generator = ProjectGenerator(export_info, config)
    return generator.generate(tmp_path / platform_key)


class TestCrossPlatformGeneration:
    """Parametrized tests validating common invariants across all platforms."""

    @pytest.mark.parametrize("platform_key", sorted(PLATFORM_REGISTRY.keys()))
    def test_generate_project_creates_directory(
        self, platform_key, gigaverb_export, tmp_path
    ):
        """Every platform must create a project directory."""
        project_dir = _generate_project(platform_key, gigaverb_export, tmp_path)
        assert project_dir.is_dir()

    @pytest.mark.parametrize("platform_key", sorted(PLATFORM_REGISTRY.keys()))
    def test_generate_project_copies_gen_export(
        self, platform_key, gigaverb_export, tmp_path
    ):
        """Every platform must copy the gen~ export files into gen/ subdir."""
        project_dir = _generate_project(platform_key, gigaverb_export, tmp_path)
        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir(), f"{platform_key}: gen/ subdirectory not found"
        gen_files = list(gen_dir.glob("*.cpp"))
        assert len(gen_files) > 0, f"{platform_key}: no .cpp files in gen/"

    @pytest.mark.parametrize("platform_key", sorted(PLATFORM_REGISTRY.keys()))
    def test_generate_project_creates_buffer_header(
        self, platform_key, gigaverb_export, tmp_path
    ):
        """Every platform must generate gen_buffer.h."""
        project_dir = _generate_project(platform_key, gigaverb_export, tmp_path)
        buffer_h = project_dir / "gen_buffer.h"
        assert buffer_h.is_file(), f"{platform_key}: gen_buffer.h not found"
        content = buffer_h.read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in content

    @pytest.mark.parametrize("platform_key", sorted(PLATFORM_REGISTRY.keys()))
    def test_generate_project_has_build_system_file(
        self, platform_key, gigaverb_export, tmp_path
    ):
        """Every platform must produce its build system entry point."""
        project_dir = _generate_project(platform_key, gigaverb_export, tmp_path)
        build_file = _BUILD_SYSTEM_FILES.get(platform_key)
        assert build_file is not None, f"No build file mapping for {platform_key}"
        assert (project_dir / build_file).is_file(), (
            f"{platform_key}: {build_file} not found"
        )

    @pytest.mark.parametrize("platform_key", sorted(PLATFORM_REGISTRY.keys()))
    def test_generate_project_with_buffers(
        self, platform_key, rampleplayer_export, tmp_path
    ):
        """Every platform must handle buffer declarations."""
        project_dir = _generate_project(
            platform_key, rampleplayer_export, tmp_path, buffers=["sample"]
        )
        buffer_h = project_dir / "gen_buffer.h"
        assert buffer_h.is_file()
        content = buffer_h.read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in content
        assert "WRAPPER_BUFFER_NAME_0 sample" in content
