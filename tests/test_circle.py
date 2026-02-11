"""Tests for Circle (Raspberry Pi bare metal) platform implementation."""

from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    CirclePlatform,
    get_platform,
)
from gen_dsp.platforms.circle import (
    CIRCLE_BOARDS,
    CircleBoardConfig,
    CIRCLE_VERSION,
    _get_default_circle_dir,
    _resolve_circle_dir,
    _get_audio_include,
    _get_audio_base_class,
    _get_audio_label,
    _get_extra_libs,
    _get_boot_config,
)


class TestCirclePlatform:
    """Test Circle platform registry and basic properties."""

    def test_registry_contains_circle(self):
        """Test that circle is in the registry."""
        assert "circle" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["circle"] == CirclePlatform

    def test_get_platform_circle(self):
        """Test getting Circle platform instance."""
        platform = get_platform("circle")
        assert isinstance(platform, CirclePlatform)
        assert platform.name == "circle"

    def test_circle_extension(self):
        """Test that extension is .img (kernel image)."""
        platform = CirclePlatform()
        assert platform.extension == ".img"

    def test_circle_build_instructions(self):
        """Test Circle build instructions."""
        platform = CirclePlatform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert len(instructions) > 0
        assert any("make" in instr for instr in instructions)


class TestCircleSDKResolution:
    """Test Circle SDK path resolution."""

    def test_default_circle_dir_in_cache(self):
        """Test that default Circle dir is under the gen-dsp cache."""
        sdk_dir = _get_default_circle_dir()
        assert "gen-dsp" in str(sdk_dir)
        assert "circle-src" in str(sdk_dir)
        assert "circle" in str(sdk_dir)

    def test_resolve_circle_dir_env_override(self, monkeypatch):
        """Test that CIRCLE_DIR env var takes highest priority."""
        monkeypatch.setenv("CIRCLE_DIR", "/custom/circle")
        assert _resolve_circle_dir() == Path("/custom/circle")

    def test_resolve_circle_dir_cache_override(self, monkeypatch):
        """Test that GEN_DSP_CACHE_DIR env var derives CIRCLE_DIR."""
        monkeypatch.delenv("CIRCLE_DIR", raising=False)
        monkeypatch.setenv("GEN_DSP_CACHE_DIR", "/tmp/mycache")
        result = _resolve_circle_dir()
        assert str(result) == "/tmp/mycache/circle-src/circle"

    def test_resolve_circle_dir_default(self, monkeypatch):
        """Test that default falls back to OS cache path."""
        monkeypatch.delenv("CIRCLE_DIR", raising=False)
        monkeypatch.delenv("GEN_DSP_CACHE_DIR", raising=False)
        result = _resolve_circle_dir()
        assert result == _get_default_circle_dir()

    def test_circle_version_is_string(self):
        """Test that CIRCLE_VERSION is a valid version string."""
        assert isinstance(CIRCLE_VERSION, str)
        assert "Step" in CIRCLE_VERSION


class TestAudioDeviceHelpers:
    """Test audio device metadata helper functions."""

    @pytest.mark.parametrize(
        "device,expected_header",
        [
            ("i2s", "i2ssoundbasedevice.h"),
            ("pwm", "pwmsoundbasedevice.h"),
            ("hdmi", "hdmisoundbasedevice.h"),
            ("usb", "usbsoundbasedevice.h"),
        ],
    )
    def test_get_audio_include(self, device, expected_header):
        """Each device type produces the correct include directive."""
        include = _get_audio_include(device)
        assert "#include" in include
        assert expected_header in include

    @pytest.mark.parametrize(
        "device,expected_class",
        [
            ("i2s", "CI2SSoundBaseDevice"),
            ("pwm", "CPWMSoundBaseDevice"),
            ("hdmi", "CHDMISoundBaseDevice"),
            ("usb", "CUSBSoundBaseDevice"),
        ],
    )
    def test_get_audio_base_class(self, device, expected_class):
        """Each device type produces the correct base class name."""
        assert _get_audio_base_class(device) == expected_class

    @pytest.mark.parametrize(
        "device,expected_label",
        [
            ("i2s", "I2S"),
            ("pwm", "PWM"),
            ("hdmi", "HDMI"),
            ("usb", "USB"),
        ],
    )
    def test_get_audio_label(self, device, expected_label):
        """Each device type produces the correct human-readable label."""
        assert _get_audio_label(device) == expected_label

    def test_extra_libs_usb(self):
        """USB audio requires the USB library."""
        libs = _get_extra_libs("usb")
        assert "libusb.a" in libs

    @pytest.mark.parametrize("device", ["i2s", "pwm", "hdmi"])
    def test_extra_libs_non_usb(self, device):
        """Non-USB audio devices require no extra libraries."""
        assert _get_extra_libs(device) == ""

    def test_boot_config_i2s(self):
        """I2S boot config enables dtparam=i2s."""
        cfg = _get_boot_config("i2s")
        assert "dtparam=i2s=on" in cfg

    def test_boot_config_pwm(self):
        """PWM boot config mentions headphone jack."""
        cfg = _get_boot_config("pwm")
        assert "PWM" in cfg

    def test_boot_config_hdmi(self):
        """HDMI boot config mentions HDMI."""
        cfg = _get_boot_config("hdmi")
        assert "HDMI" in cfg

    def test_boot_config_usb(self):
        """USB boot config mentions USB."""
        cfg = _get_boot_config("usb")
        assert "USB" in cfg


class TestCircleProjectGeneration:
    """Test Circle project generation."""

    def test_generate_circle_project_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating Circle project without buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check directory was created
        assert project_dir.is_dir()

        # Check required files exist
        assert (project_dir / "Makefile").is_file()
        assert (project_dir / "gen_ext_circle.cpp").is_file()
        assert (project_dir / "_ext_circle.cpp").is_file()
        assert (project_dir / "_ext_circle.h").is_file()
        assert (project_dir / "gen_ext_common_circle.h").is_file()
        assert (project_dir / "circle_buffer.h").is_file()
        assert (project_dir / "genlib_circle.h").is_file()
        assert (project_dir / "genlib_circle.cpp").is_file()
        assert (project_dir / "cmath").is_file()  # shim for -nostdinc++
        assert (project_dir / "gen_buffer.h").is_file()
        assert (project_dir / "config.txt").is_file()

        # Check gen export
        assert (project_dir / "gen").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_circle_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating Circle project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="circle",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check gen_buffer.h has buffer configured
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_generate_circle_project_multiple_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating Circle project with multiple buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="multibuf",
            platform="circle",
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

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "GEN_EXPORTED_NAME=gen_exported" in makefile
        assert "GENLIB_USE_FLOAT32" in makefile
        assert "CIRCLEHOME" in makefile
        assert "Rules.mk" in makefile

    def test_makefile_baked_circle_dir(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has baked-in cache path for CIRCLEHOME."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        # Should contain the OS-appropriate cache path
        assert "gen-dsp" in makefile
        assert "circle-src/circle" in makefile
        # Should support GEN_DSP_CACHE_DIR override
        assert "GEN_DSP_CACHE_DIR" in makefile

    def test_makefile_num_io(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has correct I/O and param counts."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert f"CIRCLE_NUM_INPUTS={export_info.num_inputs}" in makefile
        assert f"CIRCLE_NUM_OUTPUTS={export_info.num_outputs}" in makefile
        assert f"CIRCLE_NUM_PARAMS={export_info.num_params}" in makefile

    def test_makefile_does_not_compile_genlib_cpp(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that Makefile does NOT include genlib.cpp in sources."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        # genlib_circle.cpp replaces genlib.cpp
        assert "genlib_circle.o" in makefile
        # genlib.cpp should NOT be in OBJS (it's in gen/ but not compiled)
        objs_line = [line for line in makefile.split("\n") if line.startswith("OBJS")]
        assert len(objs_line) == 1
        assert "genlib.o" not in objs_line[0]

    def test_makefile_has_override_directives(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that Makefile uses override for RASPPI, AARCH, PREFIX."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "override RASPPI" in makefile
        assert "override AARCH" in makefile
        assert "override PREFIX" in makefile

    def test_makefile_has_libs(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile has LIBS with libsound and libcircle."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "libsound.a" in makefile
        assert "libcircle.a" in makefile

    def test_genlib_circle_files_present(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that genlib_circle.h and genlib_circle.cpp are present."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # genlib_circle.h should contain pool size constants
        circle_h = (project_dir / "genlib_circle.h").read_text()
        assert "CIRCLE_HEAP_POOL_SIZE" in circle_h
        assert "circle_init_memory" in circle_h

        # genlib_circle.cpp should contain allocator implementation
        circle_cpp = (project_dir / "genlib_circle.cpp").read_text()
        assert "sysmem_newptr" in circle_cpp
        assert "sysmem_freeptr" in circle_cpp
        assert "circle_allocate" in circle_cpp
        assert "heap_pool" in circle_cpp

        # genlib_circle.cpp should use <string.h> not <cstring>
        assert "#include <string.h>" in circle_cpp
        assert "#include <cstring>" not in circle_cpp

    def test_cmath_shim_present(self, gigaverb_export: Path, tmp_project: Path):
        """Test that cmath shim is present for Circle's -nostdinc++ flag."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmath_shim = (project_dir / "cmath").read_text()
        assert "#include <math.h>" in cmath_shim

    def test_gen_ext_circle_default_board(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that gen_ext_circle.cpp uses pi3-i2s by default."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_circle.cpp").read_text()
        assert "Board: pi3-i2s" in main_cpp
        assert "Raspberry Pi 3" in main_cpp
        assert "I2S" in main_cpp
        assert "circle_init_memory" in main_cpp
        assert "GetChunk" in main_cpp

    def test_gen_ext_circle_uses_range_conversion(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that gen_ext_circle.cpp uses GetRangeMin/GetRangeMax conversion."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_circle.cpp").read_text()
        assert "GetRangeMin" in main_cpp
        assert "GetRangeMax" in main_cpp

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()

    def test_rampleplayer_io_counts(self, rampleplayer_export: Path, tmp_project: Path):
        """Test that RamplePlayer (1in/2out) gets correct I/O in Makefile."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(name="rampleplayer", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "CIRCLE_NUM_INPUTS=1" in makefile
        assert "CIRCLE_NUM_OUTPUTS=2" in makefile

    def test_spectraldelayfb_io_counts(
        self, spectraldelayfb_export: Path, tmp_project: Path
    ):
        """Test that spectraldelayfb (3in/2out) gets correct I/O in Makefile."""
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "CIRCLE_NUM_INPUTS=3" in makefile
        assert "CIRCLE_NUM_OUTPUTS=2" in makefile

    def test_config_txt_generated(self, gigaverb_export: Path, tmp_project: Path):
        """Test that config.txt is generated with I2S settings (default board)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        config_txt = (project_dir / "config.txt").read_text()
        assert "dtparam=i2s=on" in config_txt
        assert "gpu_mem=16" in config_txt


class TestCircleBoardConfig:
    """Test board configuration registry."""

    def test_registry_has_all_boards(self):
        """All board variants are registered."""
        expected = {
            "pi0-pwm",
            "pi0-i2s",
            "pi0w2-i2s",
            "pi0w2-pwm",
            "pi3-i2s",
            "pi3-pwm",
            "pi3-hdmi",
            "pi4-i2s",
            "pi4-pwm",
            "pi4-usb",
            "pi4-hdmi",
            "pi5-i2s",
            "pi5-usb",
            "pi5-hdmi",
        }
        assert set(CIRCLE_BOARDS.keys()) == expected

    def test_all_entries_are_board_configs(self):
        """Every registry value is a CircleBoardConfig."""
        for key, cfg in CIRCLE_BOARDS.items():
            assert isinstance(cfg, CircleBoardConfig), f"{key} is not CircleBoardConfig"

    def test_key_matches_dict_key(self):
        """Each config's .key matches its dict key."""
        for key, cfg in CIRCLE_BOARDS.items():
            assert cfg.key == key

    def test_pi0_pwm_config(self):
        """Pi Zero PWM board has correct configuration (32-bit)."""
        cfg = CIRCLE_BOARDS["pi0-pwm"]
        assert cfg.rasppi == 1
        assert cfg.aarch == 32
        assert cfg.prefix == "arm-none-eabi-"
        assert cfg.kernel_img == "kernel.img"
        assert cfg.audio_device == "pwm"

    def test_pi0_i2s_config(self):
        """Pi Zero I2S board has correct configuration (32-bit)."""
        cfg = CIRCLE_BOARDS["pi0-i2s"]
        assert cfg.rasppi == 1
        assert cfg.aarch == 32
        assert cfg.prefix == "arm-none-eabi-"
        assert cfg.kernel_img == "kernel.img"
        assert cfg.audio_device == "i2s"

    def test_pi0w2_i2s_config(self):
        """Pi Zero 2 W I2S board has correct configuration (64-bit like Pi 3)."""
        cfg = CIRCLE_BOARDS["pi0w2-i2s"]
        assert cfg.rasppi == 3
        assert cfg.aarch == 64
        assert cfg.prefix == "aarch64-none-elf-"
        assert cfg.kernel_img == "kernel8.img"
        assert cfg.audio_device == "i2s"

    def test_pi0w2_pwm_config(self):
        """Pi Zero 2 W PWM board has correct configuration (64-bit like Pi 3)."""
        cfg = CIRCLE_BOARDS["pi0w2-pwm"]
        assert cfg.rasppi == 3
        assert cfg.aarch == 64
        assert cfg.prefix == "aarch64-none-elf-"
        assert cfg.kernel_img == "kernel8.img"
        assert cfg.audio_device == "pwm"

    def test_pi3_i2s_config(self):
        """Pi 3 I2S board has correct configuration."""
        cfg = CIRCLE_BOARDS["pi3-i2s"]
        assert cfg.rasppi == 3
        assert cfg.aarch == 64
        assert cfg.kernel_img == "kernel8.img"
        assert cfg.audio_device == "i2s"

    def test_pi3_pwm_config(self):
        """Pi 3 PWM board has correct configuration."""
        cfg = CIRCLE_BOARDS["pi3-pwm"]
        assert cfg.rasppi == 3
        assert cfg.aarch == 64
        assert cfg.audio_device == "pwm"

    def test_pi3_hdmi_config(self):
        """Pi 3 HDMI board has correct configuration."""
        cfg = CIRCLE_BOARDS["pi3-hdmi"]
        assert cfg.rasppi == 3
        assert cfg.aarch == 64
        assert cfg.audio_device == "hdmi"

    def test_pi4_i2s_config(self):
        """Pi 4 I2S board has correct configuration."""
        cfg = CIRCLE_BOARDS["pi4-i2s"]
        assert cfg.rasppi == 4
        assert cfg.aarch == 64
        assert cfg.kernel_img == "kernel8-rpi4.img"
        assert cfg.audio_device == "i2s"

    def test_pi4_pwm_config(self):
        """Pi 4 PWM board has correct configuration."""
        cfg = CIRCLE_BOARDS["pi4-pwm"]
        assert cfg.rasppi == 4
        assert cfg.aarch == 64
        assert cfg.kernel_img == "kernel8-rpi4.img"
        assert cfg.audio_device == "pwm"

    def test_pi4_usb_config(self):
        """Pi 4 USB board has correct configuration."""
        cfg = CIRCLE_BOARDS["pi4-usb"]
        assert cfg.rasppi == 4
        assert cfg.aarch == 64
        assert cfg.kernel_img == "kernel8-rpi4.img"
        assert cfg.audio_device == "usb"

    def test_pi4_hdmi_config(self):
        """Pi 4 HDMI board has correct configuration."""
        cfg = CIRCLE_BOARDS["pi4-hdmi"]
        assert cfg.rasppi == 4
        assert cfg.aarch == 64
        assert cfg.kernel_img == "kernel8-rpi4.img"
        assert cfg.audio_device == "hdmi"

    def test_pi5_i2s_config(self):
        """Pi 5 I2S board has correct configuration."""
        cfg = CIRCLE_BOARDS["pi5-i2s"]
        assert cfg.rasppi == 5
        assert cfg.aarch == 64
        assert cfg.kernel_img == "kernel_2712.img"
        assert cfg.audio_device == "i2s"

    def test_pi5_usb_config(self):
        """Pi 5 USB board has correct configuration."""
        cfg = CIRCLE_BOARDS["pi5-usb"]
        assert cfg.rasppi == 5
        assert cfg.aarch == 64
        assert cfg.kernel_img == "kernel_2712.img"
        assert cfg.audio_device == "usb"

    def test_pi5_hdmi_config(self):
        """Pi 5 HDMI board has correct configuration."""
        cfg = CIRCLE_BOARDS["pi5-hdmi"]
        assert cfg.rasppi == 5
        assert cfg.aarch == 64
        assert cfg.kernel_img == "kernel_2712.img"
        assert cfg.audio_device == "hdmi"

    def test_configs_are_frozen(self):
        """Board configs should be immutable."""
        cfg = CIRCLE_BOARDS["pi3-i2s"]
        with pytest.raises(AttributeError):
            cfg.key = "modified"  # type: ignore[misc]

    def test_all_boards_have_prefix(self):
        """All boards have a compiler prefix configured."""
        for key, cfg in CIRCLE_BOARDS.items():
            assert cfg.prefix, f"{key} has empty prefix"
            assert cfg.prefix.endswith("-"), f"{key} prefix should end with '-'"

    def test_all_boards_have_valid_audio_device(self):
        """All boards have a recognized audio device type."""
        valid_devices = {"i2s", "pwm", "hdmi", "usb"}
        for key, cfg in CIRCLE_BOARDS.items():
            assert cfg.audio_device in valid_devices, (
                f"{key} has invalid audio_device '{cfg.audio_device}'"
            )


class TestCircleBoardProjectGeneration:
    """Test project generation for various board variants."""

    @pytest.mark.parametrize("board_key", list(CIRCLE_BOARDS.keys()))
    def test_board_generates_correct_settings(
        self, gigaverb_export: Path, tmp_path: Path, board_key: str
    ):
        """Each board produces gen_ext_circle.cpp with correct board info."""
        board = CIRCLE_BOARDS[board_key]
        project_dir = tmp_path / f"test_{board_key}"

        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board=board_key)
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        main_cpp = (project_dir / "gen_ext_circle.cpp").read_text()
        assert f"Board: {board_key}" in main_cpp
        assert f"Raspberry Pi {board.rasppi}" in main_cpp

    @pytest.mark.parametrize("board_key", list(CIRCLE_BOARDS.keys()))
    def test_board_generates_correct_makefile(
        self, gigaverb_export: Path, tmp_path: Path, board_key: str
    ):
        """Each board produces Makefile with correct RASPPI, AARCH, and PREFIX."""
        board = CIRCLE_BOARDS[board_key]
        project_dir = tmp_path / f"test_{board_key}"

        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board=board_key)
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        makefile = (project_dir / "Makefile").read_text()
        assert f"override RASPPI = {board.rasppi}" in makefile
        assert f"override AARCH = {board.aarch}" in makefile
        assert f"override PREFIX = {board.prefix}" in makefile

    def test_default_board_is_pi3_i2s(self, gigaverb_export: Path, tmp_project: Path):
        """Omitting --board defaults to pi3-i2s."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        main_cpp = (project_dir / "gen_ext_circle.cpp").read_text()
        assert "Board: pi3-i2s" in main_cpp


class TestCircleAudioDeviceProjectGeneration:
    """Test project generation for different audio device types."""

    def test_i2s_board_uses_dma_template(self, gigaverb_export: Path, tmp_path: Path):
        """I2S board uses the DMA template with CI2SSoundBaseDevice."""
        project_dir = tmp_path / "test_i2s"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board="pi3-i2s")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        main_cpp = (project_dir / "gen_ext_circle.cpp").read_text()
        assert "CI2SSoundBaseDevice" in main_cpp
        assert "i2ssoundbasedevice.h" in main_cpp
        assert "I2S" in main_cpp
        assert "GetRangeMin" in main_cpp

    def test_pwm_board_uses_dma_template(self, gigaverb_export: Path, tmp_path: Path):
        """PWM board uses the DMA template with CPWMSoundBaseDevice."""
        project_dir = tmp_path / "test_pwm"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board="pi3-pwm")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        main_cpp = (project_dir / "gen_ext_circle.cpp").read_text()
        assert "CPWMSoundBaseDevice" in main_cpp
        assert "pwmsoundbasedevice.h" in main_cpp
        assert "PWM" in main_cpp

    def test_hdmi_board_uses_dma_template(self, gigaverb_export: Path, tmp_path: Path):
        """HDMI board uses the DMA template with CHDMISoundBaseDevice."""
        project_dir = tmp_path / "test_hdmi"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board="pi3-hdmi")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        main_cpp = (project_dir / "gen_ext_circle.cpp").read_text()
        assert "CHDMISoundBaseDevice" in main_cpp
        assert "hdmisoundbasedevice.h" in main_cpp
        assert "HDMI" in main_cpp

    def test_usb_board_uses_usb_template(self, gigaverb_export: Path, tmp_path: Path):
        """USB board uses the USB template with CUSBSoundBaseDevice + CUSBHCIDevice."""
        project_dir = tmp_path / "test_usb"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board="pi4-usb")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        main_cpp = (project_dir / "gen_ext_circle.cpp").read_text()
        assert "CUSBSoundBaseDevice" in main_cpp
        assert "usbsoundbasedevice.h" in main_cpp
        assert "CUSBHCIDevice" in main_cpp
        assert "usbhcidevice.h" in main_cpp
        assert "USB" in main_cpp

    def test_usb_board_makefile_has_libusb(self, gigaverb_export: Path, tmp_path: Path):
        """USB board Makefile includes libusb.a in LIBS."""
        project_dir = tmp_path / "test_usb_libs"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board="pi4-usb")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        makefile = (project_dir / "Makefile").read_text()
        assert "libusb.a" in makefile

    def test_non_usb_board_makefile_no_libusb(
        self, gigaverb_export: Path, tmp_path: Path
    ):
        """Non-USB board Makefile does not include libusb.a."""
        project_dir = tmp_path / "test_i2s_libs"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board="pi3-i2s")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        makefile = (project_dir / "Makefile").read_text()
        assert "libusb.a" not in makefile

    def test_config_txt_i2s(self, gigaverb_export: Path, tmp_path: Path):
        """I2S board config.txt enables I2S overlay."""
        project_dir = tmp_path / "test_cfg_i2s"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board="pi3-i2s")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        config_txt = (project_dir / "config.txt").read_text()
        assert "dtparam=i2s=on" in config_txt
        assert "gpu_mem=16" in config_txt

    def test_config_txt_pwm(self, gigaverb_export: Path, tmp_path: Path):
        """PWM board config.txt mentions PWM audio."""
        project_dir = tmp_path / "test_cfg_pwm"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board="pi3-pwm")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        config_txt = (project_dir / "config.txt").read_text()
        assert "PWM" in config_txt
        assert "gpu_mem=16" in config_txt
        # PWM should NOT have I2S overlay
        assert "dtparam=i2s=on" not in config_txt

    def test_config_txt_hdmi(self, gigaverb_export: Path, tmp_path: Path):
        """HDMI board config.txt mentions HDMI audio."""
        project_dir = tmp_path / "test_cfg_hdmi"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board="pi3-hdmi")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        config_txt = (project_dir / "config.txt").read_text()
        assert "HDMI" in config_txt
        assert "gpu_mem=16" in config_txt

    def test_config_txt_usb(self, gigaverb_export: Path, tmp_path: Path):
        """USB board config.txt mentions USB audio."""
        project_dir = tmp_path / "test_cfg_usb"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="circle", board="pi4-usb")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        config_txt = (project_dir / "config.txt").read_text()
        assert "USB" in config_txt
        assert "gpu_mem=16" in config_txt


class TestCircleBoardValidation:
    """Test board name validation in ProjectConfig."""

    def test_invalid_board_name(self):
        """Invalid board name produces validation error."""
        config = ProjectConfig(name="test", platform="circle", board="nonexistent")
        errors = config.validate()
        assert any("Unknown Circle board" in e for e in errors)

    def test_valid_board_name(self):
        """Valid board name passes validation."""
        config = ProjectConfig(name="test", platform="circle", board="pi3-i2s")
        errors = config.validate()
        assert not any("board" in e.lower() for e in errors)

    @pytest.mark.parametrize("board_key", list(CIRCLE_BOARDS.keys()))
    def test_all_boards_pass_validation(self, board_key):
        """Every registered board name passes validation."""
        config = ProjectConfig(name="test", platform="circle", board=board_key)
        errors = config.validate()
        assert not any("board" in e.lower() for e in errors)

    def test_none_board_passes(self):
        """None board (default) passes validation."""
        config = ProjectConfig(name="test", platform="circle", board=None)
        errors = config.validate()
        assert not any("board" in e.lower() for e in errors)

    def test_daisy_board_on_circle_fails(self):
        """Daisy board name on Circle platform should fail validation."""
        config = ProjectConfig(name="test", platform="circle", board="seed")
        errors = config.validate()
        assert any("Unknown Circle board" in e for e in errors)

    def test_circle_board_on_daisy_fails(self):
        """Circle board name on Daisy platform should fail validation."""
        config = ProjectConfig(name="test", platform="daisy", board="pi3-i2s")
        errors = config.validate()
        assert any("Unknown Daisy board" in e for e in errors)
