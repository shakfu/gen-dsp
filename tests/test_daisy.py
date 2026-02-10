"""Tests for Daisy (Electrosmith) embedded platform implementation."""

import shutil
from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    DaisyPlatform,
    get_platform,
)
from gen_dsp.platforms.daisy import (
    DAISY_BOARDS,
    DaisyBoardConfig,
    LIBDAISY_VERSION,
    _generate_main_loop_body,
    _get_default_libdaisy_dir,
    _resolve_libdaisy_dir,
    ensure_libdaisy,
)


# Skip conditions
_has_make = shutil.which("make") is not None
_has_arm_gcc = shutil.which("arm-none-eabi-gcc") is not None
_has_git = shutil.which("git") is not None
_can_build = _has_make and _has_arm_gcc and _has_git

_skip_no_toolchain = pytest.mark.skipif(
    not _can_build, reason="make, arm-none-eabi-gcc, and git required"
)


class TestDaisyPlatform:
    """Test Daisy platform registry and basic properties."""

    def test_registry_contains_daisy(self):
        """Test that daisy is in the registry."""
        assert "daisy" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["daisy"] == DaisyPlatform

    def test_get_platform_daisy(self):
        """Test getting Daisy platform instance."""
        platform = get_platform("daisy")
        assert isinstance(platform, DaisyPlatform)
        assert platform.name == "daisy"

    def test_daisy_extension(self):
        """Test that extension is .bin (firmware binary)."""
        platform = DaisyPlatform()
        assert platform.extension == ".bin"

    def test_daisy_build_instructions(self):
        """Test Daisy build instructions."""
        platform = DaisyPlatform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert len(instructions) > 0
        assert any("make" in instr for instr in instructions)


class TestDaisyLibDaisyResolution:
    """Test libDaisy path resolution."""

    def test_default_libdaisy_dir_in_cache(self):
        """Test that default libDaisy dir is under the gen-dsp cache."""
        sdk_dir = _get_default_libdaisy_dir()
        assert "gen-dsp" in str(sdk_dir)
        assert "libdaisy-src" in str(sdk_dir)
        assert "libDaisy" in str(sdk_dir)

    def test_resolve_libdaisy_dir_env_override(self, monkeypatch):
        """Test that LIBDAISY_DIR env var takes highest priority."""
        monkeypatch.setenv("LIBDAISY_DIR", "/custom/libdaisy")
        assert _resolve_libdaisy_dir() == Path("/custom/libdaisy")

    def test_resolve_libdaisy_dir_cache_override(self, monkeypatch):
        """Test that GEN_DSP_CACHE_DIR env var derives LIBDAISY_DIR."""
        monkeypatch.delenv("LIBDAISY_DIR", raising=False)
        monkeypatch.setenv("GEN_DSP_CACHE_DIR", "/tmp/mycache")
        result = _resolve_libdaisy_dir()
        assert str(result) == "/tmp/mycache/libdaisy-src/libDaisy"

    def test_resolve_libdaisy_dir_default(self, monkeypatch):
        """Test that default falls back to OS cache path."""
        monkeypatch.delenv("LIBDAISY_DIR", raising=False)
        monkeypatch.delenv("GEN_DSP_CACHE_DIR", raising=False)
        result = _resolve_libdaisy_dir()
        assert result == _get_default_libdaisy_dir()

    def test_libdaisy_version_is_string(self):
        """Test that LIBDAISY_VERSION is a valid version string."""
        assert isinstance(LIBDAISY_VERSION, str)
        assert LIBDAISY_VERSION.startswith("v")


class TestDaisyProjectGeneration:
    """Test Daisy project generation."""

    def test_generate_daisy_project_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating Daisy project without buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check directory was created
        assert project_dir.is_dir()

        # Check required files exist
        assert (project_dir / "Makefile").is_file()
        assert (project_dir / "gen_ext_daisy.cpp").is_file()
        assert (project_dir / "_ext_daisy.cpp").is_file()
        assert (project_dir / "_ext_daisy.h").is_file()
        assert (project_dir / "gen_ext_common_daisy.h").is_file()
        assert (project_dir / "daisy_buffer.h").is_file()
        assert (project_dir / "genlib_daisy.h").is_file()
        assert (project_dir / "genlib_daisy.cpp").is_file()
        assert (project_dir / "gen_buffer.h").is_file()

        # Check gen export
        assert (project_dir / "gen").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_daisy_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating Daisy project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="daisy",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check gen_buffer.h has buffer configured
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_generate_daisy_project_multiple_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating Daisy project with multiple buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="multibuf",
            platform="daisy",
            buffers=["buf1", "buf2", "buf3"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 3" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 buf1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_1 buf2" in buffer_h
        assert "WRAPPER_BUFFER_NAME_2 buf3" in buffer_h

    def test_makefile_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has correct template substitutions."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "TARGET = testverb" in makefile
        assert "GEN_EXPORTED_NAME=gen_exported" in makefile
        assert "GENLIB_USE_FLOAT32" in makefile
        assert "LIBDAISY_DIR" in makefile
        assert "SYSTEM_FILES_DIR" in makefile

    def test_makefile_baked_libdaisy_dir(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that Makefile has baked-in cache path for LIBDAISY_DIR."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        # Should contain the OS-appropriate cache path
        assert "gen-dsp" in makefile
        assert "libdaisy-src/libDaisy" in makefile
        # Should support GEN_DSP_CACHE_DIR override
        assert "GEN_DSP_CACHE_DIR" in makefile

    def test_makefile_num_io(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has correct I/O and param counts."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert f"DAISY_NUM_INPUTS={export_info.num_inputs}" in makefile
        assert f"DAISY_NUM_OUTPUTS={export_info.num_outputs}" in makefile
        assert f"DAISY_NUM_PARAMS={export_info.num_params}" in makefile

    def test_makefile_does_not_compile_genlib_cpp(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that Makefile does NOT include genlib.cpp in sources."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        # genlib_daisy.cpp replaces genlib.cpp
        assert "genlib_daisy.cpp" in makefile
        # genlib.cpp should NOT be in CPP_SOURCES (it's in gen/ but not compiled)
        cpp_sources_line = [
            l for l in makefile.split("\n") if l.startswith("CPP_SOURCES")
        ]
        assert len(cpp_sources_line) == 1
        assert "genlib.cpp" not in cpp_sources_line[0]

    def test_genlib_daisy_files_present(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that genlib_daisy.h and genlib_daisy.cpp are present."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # genlib_daisy.h should contain pool size constants
        daisy_h = (project_dir / "genlib_daisy.h").read_text()
        assert "DAISY_SRAM_POOL_SIZE" in daisy_h
        assert "DAISY_SDRAM_POOL_SIZE" in daisy_h
        assert "daisy_init_memory" in daisy_h

        # genlib_daisy.cpp should contain bump allocator implementation
        # Note: genlib.h macros remap genlib_sysmem_* -> sysmem_* so the
        # actual function definitions use the short names
        daisy_cpp = (project_dir / "genlib_daisy.cpp").read_text()
        assert "sysmem_newptr" in daisy_cpp
        assert "sysmem_freeptr" in daisy_cpp
        assert "daisy_allocate" in daisy_cpp
        assert "sdram_pool" in daisy_cpp
        assert "sram_pool" in daisy_cpp

    def test_gen_ext_daisy_uses_daisy_seed(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that gen_ext_daisy.cpp includes daisy_seed.h by default."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_daisy.cpp").read_text()
        assert "daisy_seed.h" in main_cpp
        assert "DaisySeed" in main_cpp
        assert "Board: seed" in main_cpp
        assert "AudioCallback" in main_cpp
        assert "daisy_init_memory" in main_cpp
        assert "StartAudio" in main_cpp

    def test_generate_copies_gen_export(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()

    def test_rampleplayer_io_counts(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test that RamplePlayer (1in/2out) gets correct I/O in Makefile."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(name="rampleplayer", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "DAISY_NUM_INPUTS=1" in makefile
        assert "DAISY_NUM_OUTPUTS=2" in makefile

    def test_spectraldelayfb_io_counts(
        self, spectraldelayfb_export: Path, tmp_project: Path
    ):
        """Test that spectraldelayfb (3in/2out) gets correct I/O in Makefile."""
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "DAISY_NUM_INPUTS=3" in makefile
        assert "DAISY_NUM_OUTPUTS=2" in makefile


class TestDaisyBoardConfig:
    """Test board configuration registry."""

    def test_registry_has_all_boards(self):
        """All 8 board variants are registered."""
        expected = {"seed", "pod", "patch", "patch_sm", "field", "petal", "legio", "versio"}
        assert set(DAISY_BOARDS.keys()) == expected

    def test_all_entries_are_board_configs(self):
        """Every registry value is a DaisyBoardConfig."""
        for key, cfg in DAISY_BOARDS.items():
            assert isinstance(cfg, DaisyBoardConfig), f"{key} is not DaisyBoardConfig"

    def test_key_matches_dict_key(self):
        """Each config's .key matches its dict key."""
        for key, cfg in DAISY_BOARDS.items():
            assert cfg.key == key

    def test_knob_exprs_length(self):
        """knob_exprs tuple length matches expected knob counts."""
        expected_knobs = {
            "seed": 0, "pod": 2, "patch": 4, "patch_sm": 4,
            "field": 8, "petal": 6, "legio": 2, "versio": 7,
        }
        for key, cfg in DAISY_BOARDS.items():
            assert len(cfg.knob_exprs) == expected_knobs[key], (
                f"{key}: expected {expected_knobs[key]} knobs, got {len(cfg.knob_exprs)}"
            )

    def test_patch_has_4_channels(self):
        """Patch is the only board with 4 hardware channels."""
        assert DAISY_BOARDS["patch"].hw_channels == 4
        for key, cfg in DAISY_BOARDS.items():
            if key != "patch":
                assert cfg.hw_channels == 2, f"{key} should have 2 channels"

    def test_patch_sm_has_extra_using(self):
        """patch_sm requires using namespace daisy::patch_sm."""
        assert "patch_sm" in DAISY_BOARDS["patch_sm"].extra_using
        for key, cfg in DAISY_BOARDS.items():
            if key != "patch_sm":
                assert cfg.extra_using == "", f"{key} should have empty extra_using"

    def test_configs_are_frozen(self):
        """Board configs should be immutable."""
        cfg = DAISY_BOARDS["seed"]
        with pytest.raises(AttributeError):
            cfg.key = "modified"  # type: ignore[misc]


class TestDaisyMainLoopBody:
    """Test _generate_main_loop_body() helper."""

    def test_seed_no_params_comment_only(self):
        """Seed (0 knobs) produces comment-only loop body."""
        body = _generate_main_loop_body(DAISY_BOARDS["seed"], num_params=8)
        assert "ProcessAllControls" not in body
        assert "No hardware knobs" in body

    def test_seed_with_zero_params_comment_only(self):
        """Any board with 0 params produces comment-only loop body."""
        body = _generate_main_loop_body(DAISY_BOARDS["pod"], num_params=0)
        assert "ProcessAllControls" not in body
        assert "No hardware knobs" in body

    def test_pod_two_knobs_two_params(self):
        """Pod with 2+ params maps 2 knobs."""
        body = _generate_main_loop_body(DAISY_BOARDS["pod"], num_params=5)
        assert "hw.ProcessAllControls();" in body
        assert "hw.knob1.Value()" in body
        assert "hw.knob2.Value()" in body
        assert "wrapper_param_min(genState, 0)" in body
        assert "wrapper_param_min(genState, 1)" in body
        # Should not have param index 2 (only 2 knobs)
        assert "wrapper_set_param(genState, 2" not in body

    def test_knob_count_capped_by_params(self):
        """If fewer params than knobs, only map params count."""
        body = _generate_main_loop_body(DAISY_BOARDS["field"], num_params=3)
        assert "Automap: 3 knob(s) -> first 3 param(s)" in body
        # Should have indices 0, 1, 2 but not 3
        assert "wrapper_set_param(genState, 2" in body
        assert "wrapper_set_param(genState, 3" not in body

    def test_scaling_uses_min_max(self):
        """Generated code scales knob 0-1 to param min/max range."""
        body = _generate_main_loop_body(DAISY_BOARDS["pod"], num_params=2)
        assert "wrapper_param_min(genState, 0)" in body
        assert "wrapper_param_max(genState, 0)" in body
        assert "lo + knob * (hi - lo)" in body


class TestDaisyBoardProjectGeneration:
    """Test project generation for various board variants."""

    @pytest.mark.parametrize("board_key", list(DAISY_BOARDS.keys()))
    def test_board_generates_correct_header_and_class(
        self, gigaverb_export: Path, tmp_path: Path, board_key: str
    ):
        """Each board produces gen_ext_daisy.cpp with correct header/class/channels."""
        board = DAISY_BOARDS[board_key]
        project_dir = tmp_path / f"test_{board_key}"

        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy", board=board_key)
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        main_cpp = (project_dir / "gen_ext_daisy.cpp").read_text()
        assert f'#include "{board.header}"' in main_cpp
        assert f"static {board.hw_class} hw;" in main_cpp
        assert f"#define DAISY_HW_CHANNELS {board.hw_channels}" in main_cpp
        assert f"Board: {board_key}" in main_cpp

    def test_default_board_is_seed(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Omitting --board defaults to seed."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_daisy.cpp").read_text()
        assert "daisy_seed.h" in main_cpp
        assert "DaisySeed" in main_cpp

    def test_pod_board_has_knob_automap(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Pod board generates ProcessAllControls + knob1/knob2 mapping."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy", board="pod")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_daisy.cpp").read_text()
        assert "hw.ProcessAllControls();" in main_cpp
        assert "hw.knob1.Value()" in main_cpp
        assert "hw.knob2.Value()" in main_cpp
        assert "wrapper_set_param(genState, 0" in main_cpp
        assert "wrapper_set_param(genState, 1" in main_cpp

    def test_seed_board_no_knob_code(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Seed board has comment-only main loop (no ProcessAllControls)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy", board="seed")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_daisy.cpp").read_text()
        assert "ProcessAllControls" not in main_cpp
        assert "No hardware knobs" in main_cpp

    def test_patch_sm_has_using_namespace(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """patch_sm board includes 'using namespace daisy::patch_sm;'."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy", board="patch_sm")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_daisy.cpp").read_text()
        assert "using namespace daisy::patch_sm;" in main_cpp

    def test_patch_board_4_channels(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Patch board has 4 hardware channels."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy", board="patch")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_daisy.cpp").read_text()
        assert "#define DAISY_HW_CHANNELS 4" in main_cpp

    def test_knob_scaling_uses_param_range(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Knob automap uses wrapper_param_min/max for scaling."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="daisy", board="versio")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_daisy.cpp").read_text()
        assert "wrapper_param_min(genState," in main_cpp
        assert "wrapper_param_max(genState," in main_cpp
        assert "lo + knob * (hi - lo)" in main_cpp

    def test_zero_params_export_no_automap(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """RamplePlayer (0 params) with pod board gets comment-only loop."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testplayer", platform="daisy", board="pod")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_daisy.cpp").read_text()
        assert "ProcessAllControls" not in main_cpp


class TestDaisyBoardValidation:
    """Test board name validation in ProjectConfig."""

    def test_invalid_board_name(self):
        """Invalid board name produces validation error."""
        config = ProjectConfig(name="test", platform="daisy", board="nonexistent")
        errors = config.validate()
        assert any("Unknown Daisy board" in e for e in errors)

    def test_valid_board_name(self):
        """Valid board name passes validation."""
        config = ProjectConfig(name="test", platform="daisy", board="pod")
        errors = config.validate()
        assert not any("board" in e.lower() for e in errors)

    def test_none_board_passes(self):
        """None board (default) passes validation."""
        config = ProjectConfig(name="test", platform="daisy", board=None)
        errors = config.validate()
        assert not any("board" in e.lower() for e in errors)


class TestDaisyBuildIntegration:
    """Integration tests that generate and compile Daisy firmware.

    Skipped when arm-none-eabi-gcc/make/git is not available. libDaisy is
    auto-cloned to the shared fetchcontent cache on first run.
    """

    @_skip_no_toolchain
    def test_build_daisy_no_buffers(
        self, gigaverb_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile Daisy firmware from gigaverb (no buffers)."""
        project_dir = tmp_path / "gigaverb_daisy"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        # Ensure libDaisy is available in shared cache
        libdaisy_dir = fetchcontent_cache / "libdaisy-src" / "libDaisy"
        libdaisy_dir = ensure_libdaisy(libdaisy_dir)

        platform = DaisyPlatform()
        result = platform.run_command(
            ["make", f"LIBDAISY_DIR={libdaisy_dir}"], project_dir
        )
        assert result.returncode == 0, (
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output = platform.find_output(project_dir)
        assert output is not None
        assert output.suffix == ".bin"

    @_skip_no_toolchain
    def test_build_daisy_with_buffers(
        self, rampleplayer_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile Daisy firmware from RamplePlayer (has buffers)."""
        project_dir = tmp_path / "rampleplayer_daisy"
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="rampleplayer",
            platform="daisy",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        libdaisy_dir = fetchcontent_cache / "libdaisy-src" / "libDaisy"
        libdaisy_dir = ensure_libdaisy(libdaisy_dir)

        platform = DaisyPlatform()
        result = platform.run_command(
            ["make", f"LIBDAISY_DIR={libdaisy_dir}"], project_dir
        )
        assert result.returncode == 0, (
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output = platform.find_output(project_dir)
        assert output is not None

    @_skip_no_toolchain
    @pytest.mark.parametrize("board_key", ["pod", "patch"])
    def test_build_daisy_board_variant(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        board_key: str,
    ):
        """Generate and compile Daisy firmware for non-seed boards."""
        project_dir = tmp_path / f"gigaverb_daisy_{board_key}"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="daisy", board=board_key)
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        libdaisy_dir = fetchcontent_cache / "libdaisy-src" / "libDaisy"
        libdaisy_dir = ensure_libdaisy(libdaisy_dir)

        platform = DaisyPlatform()
        result = platform.run_command(
            ["make", f"LIBDAISY_DIR={libdaisy_dir}"], project_dir
        )
        assert result.returncode == 0, (
            f"make failed for board={board_key}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output = platform.find_output(project_dir)
        assert output is not None
        assert output.suffix == ".bin"

    @_skip_no_toolchain
    def test_build_daisy_spectraldelayfb(
        self, spectraldelayfb_export: Path, tmp_path: Path, fetchcontent_cache: Path
    ):
        """Generate and compile Daisy firmware from spectraldelayfb (3in/2out)."""
        project_dir = tmp_path / "spectraldelayfb_daisy"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="daisy")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        libdaisy_dir = fetchcontent_cache / "libdaisy-src" / "libDaisy"
        libdaisy_dir = ensure_libdaisy(libdaisy_dir)

        platform = DaisyPlatform()
        result = platform.run_command(
            ["make", f"LIBDAISY_DIR={libdaisy_dir}"], project_dir
        )
        assert result.returncode == 0, (
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output = platform.find_output(project_dir)
        assert output is not None
