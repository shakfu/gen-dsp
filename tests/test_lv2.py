"""Tests for LV2 plugin platform implementation."""

import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Optional

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    Lv2Platform,
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

# -- Persistent LV2 validator (compiled from C using lilv) ---------------------
_VALIDATOR_DIR = Path(__file__).resolve().parent.parent / "build" / ".lv2_validator"

_LV2_VALIDATOR_SRC = textwrap.dedent("""\
    /*  lv2_validate.c -- minimal LV2 plugin validator using lilv.
     *
     *  Instantiates the plugin, connects all ports, runs one block of audio,
     *  and verifies non-zero output energy (for effects with audio input).
     *
     *  Usage: lv2_validate <lv2_path> <uri> <audio_in> <audio_out> <params>
     */
    #include <lilv/lilv.h>
    #include <stdio.h>
    #include <stdlib.h>

    #define BLOCK_SIZE 512
    #define NUM_BLOCKS 8
    #define SAMPLE_RATE 44100.0

    int main(int argc, char** argv) {
        if (argc < 6) {
            fprintf(stderr,
                "Usage: %s <lv2_path> <uri> <audio_in> <audio_out> <params>\\n",
                argv[0]);
            return 1;
        }

        const char* lv2_path = argv[1];
        const char* uri_str  = argv[2];
        int exp_ain   = atoi(argv[3]);
        int exp_aout  = atoi(argv[4]);
        int exp_param = atoi(argv[5]);

        setenv("LV2_PATH", lv2_path, 1);

        LilvWorld* world = lilv_world_new();
        lilv_world_load_all(world);

        LilvNode* uri = lilv_new_uri(world, uri_str);
        const LilvPlugin* plugin = lilv_plugins_get_by_uri(
            lilv_world_get_all_plugins(world), uri);

        if (!plugin) {
            fprintf(stderr, "FAIL: plugin <%s> not found\\n", uri_str);
            return 1;
        }

        LilvNode* name_node = lilv_plugin_get_name(plugin);
        printf("Plugin: %s\\n", lilv_node_as_string(name_node));
        lilv_node_free(name_node);

        uint32_t n_ports = lilv_plugin_get_num_ports(plugin);
        printf("Ports: %u\\n", n_ports);

        /* Instantiate */
        LilvInstance* inst = lilv_plugin_instantiate(plugin, SAMPLE_RATE, NULL);
        if (!inst) {
            fprintf(stderr, "FAIL: could not instantiate\\n");
            return 1;
        }
        printf("Instantiated OK\\n");

        /* URI nodes for port classification */
        LilvNode* cls_audio   = lilv_new_uri(world,
            "http://lv2plug.in/ns/lv2core#AudioPort");
        LilvNode* cls_control = lilv_new_uri(world,
            "http://lv2plug.in/ns/lv2core#ControlPort");
        LilvNode* cls_input   = lilv_new_uri(world,
            "http://lv2plug.in/ns/lv2core#InputPort");

        /* Per-port storage */
        float** bufs = (float**)calloc(n_ports, sizeof(float*));
        float*  ctrl = (float*) calloc(n_ports, sizeof(float));
        int ain = 0, aout = 0, cin = 0;

        for (uint32_t p = 0; p < n_ports; p++) {
            const LilvPort* port = lilv_plugin_get_port_by_index(plugin, p);
            int is_in = lilv_port_is_a(plugin, port, cls_input);

            if (lilv_port_is_a(plugin, port, cls_audio)) {
                bufs[p] = (float*)calloc(BLOCK_SIZE, sizeof(float));
                if (is_in) {
                    for (int j = 0; j < BLOCK_SIZE; j++)
                        bufs[p][j] = ((float)rand() / RAND_MAX) * 2.0f - 1.0f;
                    ain++;
                } else {
                    aout++;
                }
                lilv_instance_connect_port(inst, p, bufs[p]);
            } else if (lilv_port_is_a(plugin, port, cls_control)) {
                LilvNode* defval = NULL;
                lilv_port_get_range(plugin, port, &defval, NULL, NULL);
                if (defval) {
                    ctrl[p] = lilv_node_as_float(defval);
                    lilv_node_free(defval);
                }
                lilv_instance_connect_port(inst, p, &ctrl[p]);
                if (is_in) cin++;
            }
        }

        printf("Audio: %d in, %d out; Control: %d in\\n", ain, aout, cin);

        int fail = 0;
        if (ain != exp_ain) {
            fprintf(stderr, "FAIL: audio_in %d != expected %d\\n", ain, exp_ain);
            fail = 1;
        }
        if (aout != exp_aout) {
            fprintf(stderr, "FAIL: audio_out %d != expected %d\\n", aout, exp_aout);
            fail = 1;
        }
        if (cin != exp_param) {
            fprintf(stderr, "FAIL: params %d != expected %d\\n", cin, exp_param);
            fail = 1;
        }

        if (!fail) {
            lilv_instance_activate(inst);

            /* Run multiple blocks to account for FFT latency in spectral
               processors.  Refill audio inputs with fresh noise each block
               and accumulate output energy across all blocks. */
            double energy = 0.0;
            for (int blk = 0; blk < NUM_BLOCKS; blk++) {
                /* Refill input buffers */
                for (uint32_t p = 0; p < n_ports; p++) {
                    const LilvPort* port =
                        lilv_plugin_get_port_by_index(plugin, p);
                    if (lilv_port_is_a(plugin, port, cls_audio) &&
                        lilv_port_is_a(plugin, port, cls_input)) {
                        for (int j = 0; j < BLOCK_SIZE; j++)
                            bufs[p][j] =
                                ((float)rand() / RAND_MAX) * 2.0f - 1.0f;
                    }
                }

                lilv_instance_run(inst, BLOCK_SIZE);

                /* Accumulate output energy */
                for (uint32_t p = 0; p < n_ports; p++) {
                    const LilvPort* port =
                        lilv_plugin_get_port_by_index(plugin, p);
                    if (lilv_port_is_a(plugin, port, cls_audio) &&
                        !lilv_port_is_a(plugin, port, cls_input)) {
                        for (int j = 0; j < BLOCK_SIZE; j++)
                            energy += (double)(bufs[p][j] * bufs[p][j]);
                    }
                }
            }
            printf("Output energy: %.6f (%d blocks)\\n", energy, NUM_BLOCKS);

            if (ain > 0 && energy == 0.0) {
                fprintf(stderr, "FAIL: zero output energy\\n");
                fail = 1;
            }

            lilv_instance_deactivate(inst);
        }

        /* Cleanup */
        lilv_instance_free(inst);
        for (uint32_t p = 0; p < n_ports; p++)
            free(bufs[p]);
        free(bufs);
        free(ctrl);
        lilv_node_free(cls_audio);
        lilv_node_free(cls_control);
        lilv_node_free(cls_input);
        lilv_node_free(uri);
        lilv_world_free(world);

        printf(fail ? "FAILED\\n" : "PASS\\n");
        return fail;
    }
""")


def _check_pkg_config_lilv() -> bool:
    """Return True if pkg-config can resolve lilv-0."""
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", "lilv-0"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


_has_pkg_config_lilv = _check_pkg_config_lilv()


@pytest.fixture(scope="session")
def lv2_validator() -> Optional[Path]:
    """Compile a minimal LV2 validator from C once per session.

    Uses pkg-config for lilv-0 flags.  The binary is cached in
    build/.lv2_validator/ and reused across pytest sessions.
    Returns None if lilv-0 is not available or compilation fails.
    """
    if not _has_pkg_config_lilv:
        return None

    _VALIDATOR_DIR.mkdir(parents=True, exist_ok=True)
    binary = _VALIDATOR_DIR / "lv2_validate"

    # Reuse previously compiled binary
    if binary.is_file() and os.access(binary, os.X_OK):
        return binary

    # Write C source
    src = _VALIDATOR_DIR / "lv2_validate.c"
    src.write_text(_LV2_VALIDATOR_SRC)

    # Get compiler flags from pkg-config
    try:
        cflags = subprocess.run(
            ["pkg-config", "--cflags", "lilv-0"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        libs = subprocess.run(
            ["pkg-config", "--libs", "lilv-0"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    # Compile
    cc = "cc"
    cmd = f"{cc} {cflags} {str(src)} {libs} -lm -o {str(binary)}"
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=_VALIDATOR_DIR,
    )
    if result.returncode != 0:
        print(f"LV2 validator compile failed:\n{result.stderr}")
        return None

    return binary


def _validate_lv2(
    validator: Optional[Path],
    bundle_dir: Path,
    lib_name: str,
    expected_audio_in: int,
    expected_audio_out: int,
    expected_params: int,
) -> None:
    """Validate a built LV2 bundle by instantiating and processing audio.

    Uses a custom C validator that loads the plugin via lilv, connects
    all ports, runs one block of audio, and checks output energy.
    Copies the bundle to an isolated directory so lilv doesn't scan
    stray build artifacts.
    """
    if validator is None:
        return

    plugin_uri = f"http://gen-dsp.com/plugins/{lib_name}"

    # Copy bundle to a clean directory to avoid lilv scanning noise
    with tempfile.TemporaryDirectory() as tmpdir:
        isolated = Path(tmpdir) / bundle_dir.name
        shutil.copytree(bundle_dir, isolated)

        result = subprocess.run(
            [
                str(validator),
                tmpdir,
                plugin_uri,
                str(expected_audio_in),
                str(expected_audio_out),
                str(expected_params),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"LV2 validation failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout


class TestLv2Platform:
    """Test LV2 platform registry and basic properties."""

    def test_registry_contains_lv2(self):
        """Test that LV2 is in the registry."""
        assert "lv2" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["lv2"] == Lv2Platform

    def test_get_platform_lv2(self):
        """Test getting LV2 platform instance."""
        platform = get_platform("lv2")
        assert isinstance(platform, Lv2Platform)
        assert platform.name == "lv2"

    def test_lv2_extension(self):
        """Test that extension is .lv2."""
        platform = Lv2Platform()
        assert platform.extension == ".lv2"

    def test_lv2_build_instructions(self):
        """Test LV2 build instructions."""
        platform = Lv2Platform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert len(instructions) > 0
        assert any("cmake" in instr for instr in instructions)

    def test_sanitize_symbol_valid(self):
        """Test that valid symbols pass through."""
        assert Lv2Platform._sanitize_symbol("bandwidth") == "bandwidth"
        assert Lv2Platform._sanitize_symbol("my_param") == "my_param"

    def test_sanitize_symbol_spaces(self):
        """Test that spaces are replaced with underscores."""
        assert Lv2Platform._sanitize_symbol("my param") == "my_param"

    def test_sanitize_symbol_leading_digit(self):
        """Test that leading digits get underscore prefix."""
        assert Lv2Platform._sanitize_symbol("0gain") == "_0gain"

    def test_sanitize_symbol_special_chars(self):
        """Test that special characters are replaced."""
        assert Lv2Platform._sanitize_symbol("gain-level") == "gain_level"


class TestLv2ProjectGeneration:
    """Test LV2 project generation."""

    def test_generate_lv2_project_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating LV2 project without buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check directory was created
        assert project_dir.is_dir()

        # Check required C++ files exist
        assert (project_dir / "CMakeLists.txt").is_file()
        assert (project_dir / "gen_ext_lv2.cpp").is_file()
        assert (project_dir / "_ext_lv2.cpp").is_file()
        assert (project_dir / "_ext_lv2.h").is_file()
        assert (project_dir / "gen_ext_common_lv2.h").is_file()
        assert (project_dir / "lv2_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()

        # Check TTL files exist
        assert (project_dir / "manifest.ttl").is_file()
        assert (project_dir / "testverb.ttl").is_file()

        # Check gen export and build dir
        assert (project_dir / "gen").is_dir()
        assert (project_dir / "build").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_lv2_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating LV2 project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="lv2",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        # Check gen_buffer.h has buffer configured
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_generate_lv2_project_multiple_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test generating LV2 project with multiple buffers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="multibuf",
            platform="lv2",
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

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "set(PROJECT_NAME testverb)" in cmake
        assert "LV2_EXT_NAME=testverb" in cmake
        assert "GEN_EXPORTED_NAME=gen_exported" in cmake
        assert "GENLIB_USE_FLOAT32" in cmake
        assert "FetchContent_Declare" in cmake
        assert "lv2/lv2" in cmake

    def test_cmakelists_num_io(self, gigaverb_export: Path, tmp_project: Path):
        """Test that CMakeLists.txt has correct I/O and param counts."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert f"LV2_NUM_INPUTS={export_info.num_inputs}" in cmake
        assert f"LV2_NUM_OUTPUTS={export_info.num_outputs}" in cmake
        assert f"LV2_NUM_PARAMS={export_info.num_params}" in cmake

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()

    def test_manifest_ttl_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test manifest.ttl has correct URI and binary reference."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        manifest = (project_dir / "manifest.ttl").read_text()
        assert "http://gen-dsp.com/plugins/testverb" in manifest
        assert "lv2:binary" in manifest
        assert "lv2:Plugin" in manifest
        assert "rdfs:seeAlso" in manifest
        assert "testverb.ttl" in manifest

    def test_plugin_ttl_ports(self, gigaverb_export: Path, tmp_project: Path):
        """Test plugin.ttl has correct port definitions."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        ttl = (project_dir / "testverb.ttl").read_text()
        assert "http://gen-dsp.com/plugins/testverb" in ttl
        assert 'doap:name "testverb"' in ttl
        assert "lv2:hardRTCapable" in ttl

        # Check param ports exist with real names
        assert '"bandwidth"' in ttl
        assert '"damping"' in ttl
        assert '"revtime"' in ttl
        assert "lv2:ControlPort" in ttl

        # Check audio ports
        assert "lv2:AudioPort" in ttl
        assert '"in0"' in ttl
        assert '"out0"' in ttl

        # Check port indices are present
        assert "lv2:index 0" in ttl  # first param

    def test_plugin_ttl_effect_type(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gigaverb (has inputs) is EffectPlugin."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()
        assert export_info.num_inputs > 0

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        ttl = (project_dir / "testverb.ttl").read_text()
        assert "lv2:EffectPlugin" in ttl

    def test_plugin_ttl_no_params(
        self, spectraldelayfb_export: Path, tmp_project: Path
    ):
        """Test TTL for export with no parameters."""
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="specfb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        ttl = (project_dir / "specfb.ttl").read_text()
        # Should have audio ports but no control ports
        assert "lv2:AudioPort" in ttl
        assert "lv2:ControlPort" not in ttl

    def test_cmakelists_shared_cache_off_by_default(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that default generation has shared cache OFF."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(OFF)" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake

    def test_cmakelists_shared_cache_on(self, gigaverb_export: Path, tmp_project: Path):
        """Test that --shared-cache produces ON with resolved path."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2", shared_cache=True)
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "elseif(ON)" in cmake
        assert "gen-dsp" in cmake
        assert "fetchcontent" in cmake
        assert "GEN_DSP_CACHE_DIR" in cmake


class TestLv2BuildIntegration:
    """Integration tests that generate and compile an LV2 plugin.

    Skipped when no cmake/C++ compiler is available.
    """

    @_skip_no_toolchain
    def test_build_lv2_no_buffers(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
        validate_minihost,
    ):
        """Generate and compile an LV2 plugin from gigaverb (no buffers)."""
        project_dir = tmp_path / "gigaverb_lv2"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="lv2")
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

        # Verify .lv2 bundle directory was produced
        lv2_bundles = [d for d in build_dir.glob("**/*.lv2") if d.is_dir()]
        assert len(lv2_bundles) >= 1
        bundle = lv2_bundles[0]
        assert bundle.name == "gigaverb.lv2"
        # Check bundle contents
        assert (bundle / "manifest.ttl").is_file()
        assert (bundle / "gigaverb.ttl").is_file()
        # Check binary exists (name varies by platform)
        binaries = list(bundle.glob("gigaverb.*"))
        assert len(binaries) >= 1

        _validate_lv2(lv2_validator, bundle, "gigaverb", 2, 2, 8)

        # Runtime validation via minihost
        validate_minihost(bundle, 2, 2, num_params=8)

    @_skip_no_toolchain
    def test_build_lv2_with_buffers(
        self,
        rampleplayer_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
        validate_minihost,
    ):
        """Generate and compile an LV2 plugin from RamplePlayer (has buffers)."""
        project_dir = tmp_path / "rampleplayer_lv2"
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="rampleplayer",
            platform="lv2",
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

        lv2_bundles = [d for d in build_dir.glob("**/*.lv2") if d.is_dir()]
        assert len(lv2_bundles) >= 1
        assert lv2_bundles[0].name == "rampleplayer.lv2"

        _validate_lv2(lv2_validator, lv2_bundles[0], "rampleplayer", 1, 2, 0)

        # Runtime validation via minihost
        validate_minihost(lv2_bundles[0], 1, 2, num_params=0)

    @_skip_no_toolchain
    def test_build_lv2_spectraldelayfb(
        self,
        spectraldelayfb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
        validate_minihost,
    ):
        """Generate and compile an LV2 plugin from spectraldelayfb (3in/2out)."""
        project_dir = tmp_path / "spectraldelayfb_lv2"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="lv2")
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

        lv2_bundles = [d for d in build_dir.glob("**/*.lv2") if d.is_dir()]
        assert len(lv2_bundles) >= 1
        assert lv2_bundles[0].name == "spectraldelayfb.lv2"

        _validate_lv2(lv2_validator, lv2_bundles[0], "spectraldelayfb", 3, 2, 0)

        # Runtime validation via minihost
        validate_minihost(lv2_bundles[0], 3, 2, num_params=0)

    @_skip_no_toolchain
    def test_build_clean_rebuild(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
        monkeypatch,
    ):
        """Test that clean + rebuild works via the platform API."""
        monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")

        project_dir = tmp_path / "gigaverb_rebuild"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        # Inject shared FetchContent cache
        cmakelists = project_dir / "CMakeLists.txt"
        original = cmakelists.read_text()
        inject = (
            f'set(FETCHCONTENT_BASE_DIR "{fetchcontent_cache}" CACHE PATH "" FORCE)\n'
        )
        cmakelists.write_text(inject + original)

        platform = Lv2Platform()

        # First build
        build_result = platform.build(project_dir)
        assert build_result.success
        assert build_result.output_file is not None
        assert build_result.output_file.name == "gigaverb.lv2"

        # Clean + rebuild
        build_result = platform.build(project_dir, clean=True)
        assert build_result.success
        assert build_result.output_file is not None

        _validate_lv2(lv2_validator, build_result.output_file, "gigaverb", 2, 2, 8)

    @_skip_no_toolchain
    def test_build_lv2_polyphony(
        self,
        gigaverb_export: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
    ):
        """Generate and compile a polyphonic LV2 plugin (NUM_VOICES=4)."""
        import shutil
        from dataclasses import replace
        from gen_dsp.core.manifest import manifest_from_export_info
        from gen_dsp.core.midi import detect_midi_mapping
        from gen_dsp.platforms.base import Platform

        project_dir = tmp_path / "poly_lv2"
        project_dir.mkdir(parents=True, exist_ok=True)
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        # Create manifest but override num_inputs=0 so MIDI detection activates
        manifest = manifest_from_export_info(export_info, [], Platform.GENEXT_VERSION)
        manifest = replace(manifest, num_inputs=0)

        config = ProjectConfig(
            name="polyverb",
            platform="lv2",
            midi_gate="damping",
            midi_freq="roomsize",
            num_voices=4,
        )
        config.midi_mapping = detect_midi_mapping(
            manifest,
            midi_gate=config.midi_gate,
            midi_freq=config.midi_freq,
        )
        config.midi_mapping.num_voices = config.num_voices

        platform = Lv2Platform()
        platform.generate_project(manifest, project_dir, "polyverb", config=config)

        # Copy gen~ export files (normally done by ProjectGenerator)
        shutil.copytree(gigaverb_export, project_dir / "gen")

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

        # Verify .lv2 bundle directory was produced
        lv2_bundles = [d for d in build_dir.glob("**/*.lv2") if d.is_dir()]
        assert len(lv2_bundles) >= 1
        bundle = lv2_bundles[0]
        assert bundle.name == "polyverb.lv2"
        # Check bundle contents
        assert (bundle / "manifest.ttl").is_file()
        assert (bundle / "polyverb.ttl").is_file()
        # Check binary exists (name varies by platform)
        binaries = list(bundle.glob("polyverb.*"))
        assert len(binaries) >= 1

        # Verify TTL has MIDI atom port and InstrumentPlugin type
        ttl = (bundle / "polyverb.ttl").read_text()
        assert "lv2:InstrumentPlugin" in ttl
        assert "atom:AtomPort" in ttl
        assert "midi:MidiEvent" in ttl

        # Verify CMakeLists has polyphony defines
        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "NUM_VOICES=4" in cmake
        assert "MIDI_ENABLED=1" in cmake

        # Validator: poly plugin is a generator (0 audio inputs) with MIDI.
        # The C validator checks audio port counts; for a poly generator the
        # expected audio_in is 0.  The atom MIDI port is not an audio port so
        # lilv won't count it.  gigaverb has 8 params.
        _validate_lv2(lv2_validator, bundle, "polyverb", 0, 2, 8)

        # NOTE: minihost validation skipped for polyphony -- the gen~
        # exported code expects 2 audio inputs but the manifest overrides
        # num_inputs=0 for MIDI detection, causing a segfault in process.


class TestLv2MidiGeneration:
    """Test MIDI compile definitions and TTL in generated LV2 projects."""

    def test_cmakelists_no_midi_for_effects(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Effects (gigaverb has 2 inputs) should not get MIDI defines."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="lv2")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED" not in cmake
        assert "MIDI_GATE_IDX" not in cmake

        ttl = (project_dir / "testverb.ttl").read_text()
        assert "lv2:EffectPlugin" in ttl
        assert "atom:AtomPort" not in ttl
        assert "midi:MidiEvent" not in ttl

    def test_cmakelists_midi_defines_with_explicit_mapping(self, tmp_path: Path):
        """Explicit --midi-* flags on a generator should produce MIDI defines."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping

        output_dir = tmp_path / "midi_lv2"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_synth",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0,
                    name="gate",
                    has_minmax=True,
                    min=0.0,
                    max=1.0,
                    default=0.0,
                ),
                ParamInfo(
                    index=1,
                    name="freq",
                    has_minmax=True,
                    min=20.0,
                    max=20000.0,
                    default=440.0,
                ),
                ParamInfo(
                    index=2,
                    name="vel",
                    has_minmax=True,
                    min=0.0,
                    max=1.0,
                    default=0.0,
                ),
            ],
        )

        config = ProjectConfig(
            name="testsynth",
            platform="lv2",
            midi_gate="gate",
            midi_freq="freq",
            midi_vel="vel",
        )
        config.midi_mapping = detect_midi_mapping(
            manifest,
            midi_gate=config.midi_gate,
            midi_freq=config.midi_freq,
            midi_vel=config.midi_vel,
        )

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        cmake = (output_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED=1" in cmake
        assert "MIDI_GATE_IDX=0" in cmake
        assert "MIDI_FREQ_IDX=1" in cmake
        assert "MIDI_VEL_IDX=2" in cmake
        assert "MIDI_FREQ_UNIT_HZ=1" in cmake

    def test_ttl_instrument_type_with_midi(self, tmp_path: Path):
        """MIDI-enabled generator should use InstrumentPlugin type in TTL."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping

        output_dir = tmp_path / "midi_lv2_ttl"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_synth",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0,
                    name="gate",
                    has_minmax=True,
                    min=0.0,
                    max=1.0,
                    default=0.0,
                ),
            ],
        )

        config = ProjectConfig(
            name="testsynth",
            platform="lv2",
            midi_gate="gate",
        )
        config.midi_mapping = detect_midi_mapping(
            manifest,
            midi_gate=config.midi_gate,
        )

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        ttl = (output_dir / "testsynth.ttl").read_text()
        assert "lv2:InstrumentPlugin" in ttl
        assert "lv2:GeneratorPlugin" not in ttl

        # Check MIDI atom port is present
        assert "atom:AtomPort" in ttl
        assert "midi:MidiEvent" in ttl
        assert '"midi_in"' in ttl
        assert "urid:map" in ttl
        assert "atom:bufferType atom:Sequence" in ttl

    def test_ttl_generator_without_midi(self, tmp_path: Path):
        """Generator without MIDI mapping should remain GeneratorPlugin."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping

        output_dir = tmp_path / "no_midi_lv2"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_gen",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0,
                    name="volume",
                    has_minmax=True,
                    min=0.0,
                    max=1.0,
                    default=0.5,
                ),
            ],
        )

        config = ProjectConfig(name="testgen", platform="lv2", no_midi=True)
        config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=config.no_midi,
        )

        platform.generate_project(manifest, output_dir, "testgen", config=config)

        ttl = (output_dir / "testgen.ttl").read_text()
        assert "lv2:GeneratorPlugin" in ttl
        assert "lv2:InstrumentPlugin" not in ttl
        assert "atom:AtomPort" not in ttl
        assert "midi:MidiEvent" not in ttl

        cmake = (output_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED" not in cmake

    def test_cmakelists_polyphony_defines(self, tmp_path: Path):
        """NUM_VOICES=8 in CMakeLists when num_voices=8."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping
        from gen_dsp.platforms.lv2 import Lv2Platform

        output_dir = tmp_path / "poly_lv2"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_synth",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0, name="gate", has_minmax=True, min=0.0, max=1.0, default=0.0
                ),
                ParamInfo(
                    index=1,
                    name="freq",
                    has_minmax=True,
                    min=20.0,
                    max=20000.0,
                    default=440.0,
                ),
            ],
        )

        config = ProjectConfig(
            name="testsynth",
            platform="lv2",
            midi_gate="gate",
            midi_freq="freq",
            num_voices=8,
        )

        config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=config.no_midi,
            midi_gate=config.midi_gate,
            midi_freq=config.midi_freq,
            midi_vel=config.midi_vel,
            midi_freq_unit=config.midi_freq_unit,
        )
        config.midi_mapping.num_voices = config.num_voices

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        cmake = (output_dir / "CMakeLists.txt").read_text()
        assert "NUM_VOICES=8" in cmake
        assert "MIDI_ENABLED=1" in cmake

    def test_voice_alloc_header_copied(self, tmp_path: Path):
        """voice_alloc.h is copied when num_voices > 1."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping
        from gen_dsp.platforms.lv2 import Lv2Platform

        output_dir = tmp_path / "poly_header"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_synth",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0, name="gate", has_minmax=True, min=0.0, max=1.0, default=0.0
                ),
            ],
        )

        config = ProjectConfig(
            name="testsynth",
            platform="lv2",
            midi_gate="gate",
            num_voices=4,
        )

        config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=config.no_midi,
            midi_gate=config.midi_gate,
        )
        config.midi_mapping.num_voices = config.num_voices

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        assert (output_dir / "voice_alloc.h").is_file()

    def test_no_voice_alloc_header_mono(self, tmp_path: Path):
        """voice_alloc.h is NOT copied when num_voices=1 (mono)."""
        from gen_dsp.core.manifest import Manifest, ParamInfo
        from gen_dsp.core.midi import detect_midi_mapping
        from gen_dsp.platforms.lv2 import Lv2Platform

        output_dir = tmp_path / "mono_header"
        output_dir.mkdir()

        platform = Lv2Platform()
        manifest = Manifest(
            gen_name="test_synth",
            num_inputs=0,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0, name="gate", has_minmax=True, min=0.0, max=1.0, default=0.0
                ),
            ],
        )

        config = ProjectConfig(
            name="testsynth",
            platform="lv2",
            midi_gate="gate",
        )

        config.midi_mapping = detect_midi_mapping(
            manifest,
            no_midi=config.no_midi,
            midi_gate=config.midi_gate,
        )

        platform.generate_project(manifest, output_dir, "testsynth", config=config)

        assert not (output_dir / "voice_alloc.h").exists()
