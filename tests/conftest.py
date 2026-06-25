"""Pytest configuration and fixtures for gen_dsp tests."""

import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Optional

import pytest

try:
    import minihost as _minihost
except ImportError:
    _minihost = None


def _validate_plugin_with_minihost(
    plugin_path,
    num_inputs,
    num_outputs,
    num_params=0,
    send_midi=False,
    check_energy=True,
):
    """Load a plugin via minihost, process audio, verify output energy.

    Silently returns if minihost is not installed.
    """
    if _minihost is None:
        return

    import numpy as np

    plugin = _minihost.Plugin(
        str(plugin_path),
        sample_rate=48000.0,
        max_block_size=512,
        in_channels=num_inputs,
        out_channels=num_outputs,
    )
    assert plugin.num_params >= num_params

    n_blocks = 8  # enough for FFT-based processors
    block_size = 512
    output = np.zeros((num_outputs, block_size), dtype=np.float32)
    energy = 0.0

    for i in range(n_blocks):
        if num_inputs > 0:
            inp = np.random.uniform(-0.5, 0.5, (num_inputs, block_size)).astype(
                np.float32
            )
        else:
            inp = np.zeros((0, block_size), dtype=np.float32)

        if send_midi and i == 0:
            events = [(0, 0x90, 60, 100)]  # note-on C4
            plugin.process_midi(inp, output, events)
        else:
            plugin.process(inp, output)

        energy += float(np.sum(output**2))

    if check_energy:
        assert energy > 1e-10, f"Plugin produced no audio output (energy={energy})"


@pytest.fixture
def validate_minihost():
    """Fixture providing the minihost validation helper."""
    return _validate_plugin_with_minihost


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def gigaverb_export(fixtures_dir: Path) -> Path:
    """Path to the gigaverb gen~ export (no buffers)."""
    return fixtures_dir / "gigaverb" / "gen"


@pytest.fixture
def rampleplayer_export(fixtures_dir: Path) -> Path:
    """Path to the RamplePlayer gen~ export (has buffers)."""
    return fixtures_dir / "RamplePlayer" / "gen"


@pytest.fixture
def spectraldelayfb_export(fixtures_dir: Path) -> Path:
    """Path to the spectraldelayfb gen~ export."""
    return fixtures_dir / "spectraldelayfb" / "gen"


# Minimal hand-authored gen~-style exports for parser/manifest shape coverage.
# These are NOT real Max exports and are not buildable (no genlib sources);
# they reproduce only the idioms the parser/manifest read, for shapes the real
# fixtures above do not cover. See tests/fixtures/<name>/gen/<name>.cpp.


@pytest.fixture
def mono_gain_export(fixtures_dir: Path) -> Path:
    """Minimal mono (1-in/1-out) export with one ranged parameter."""
    return fixtures_dir / "mono_gain" / "gen"


@pytest.fixture
def multitap_export(fixtures_dir: Path) -> Path:
    """Minimal export with two buffers and zero parameters."""
    return fixtures_dir / "multitap" / "gen"


@pytest.fixture
def octoverb_export(fixtures_dir: Path) -> Path:
    """Minimal high-channel-count (8-in/8-out) export with two parameters."""
    return fixtures_dir / "octoverb" / "gen"


@pytest.fixture
def examples_dir() -> Path:
    """Path to the gen_export examples directory."""
    return Path(__file__).parent.parent / "examples" / "gen_export"


@pytest.fixture
def fm_bells_export(examples_dir: Path) -> Path:
    """Path to the fm_bells gen~ export (no buffers, 2in/2out)."""
    return examples_dir / "fm_bells"


@pytest.fixture
def slicer_export(examples_dir: Path) -> Path:
    """Path to the slicer gen~ export (has buffer, 1in/1out)."""
    return examples_dir / "slicer"


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Temporary directory for project generation tests."""
    return tmp_path / "test_project"


# -- Shared FetchContent cache for CMake-based build integration tests --------

# Fixed path under build/ (gitignored) so SDK downloads persist across
# pytest sessions.  Both CLAP and VST3 build tests use this.
_FETCHCONTENT_CACHE = (
    Path(__file__).resolve().parent.parent / "build" / ".fetchcontent_cache"
)


# Network platforms whose build tests may download an SDK on first run, matched
# against the platform token embedded in each test name (e.g. test_build_clap_*).
_NETWORK_PLATFORMS = ("vcvrack", "daisy", "circle", "clap", "vst3", "lv2", "sc")


@pytest.fixture(autouse=True)
def _gate_sdk_network(request: pytest.FixtureRequest) -> None:
    """Skip build-integration tests that would need an offline SDK download.

    Scoped to tests that actually request the ``fetchcontent_cache`` fixture --
    i.e. real build-integration tests -- so plain unit tests (which may share a
    platform token in their name) are never affected.  The cache-aware check in
    ``skip_if_sdk_download_needed`` still lets cached SDKs build offline.
    """
    if "fetchcontent_cache" not in request.fixturenames:
        return
    from tests.helpers import skip_if_sdk_download_needed

    name = f"_{request.node.name}_"
    for platform in _NETWORK_PLATFORMS:
        if f"_{platform}_" in name:
            skip_if_sdk_download_needed(platform, _FETCHCONTENT_CACHE)
            return


@pytest.fixture(scope="session")
def fetchcontent_cache() -> Path:
    """Fixed-path FetchContent cache shared across all build tests.

    Persists across pytest sessions so large SDKs (e.g. VST3 ~50 MB)
    are only downloaded once.  Build/subbuild directories are cleared
    each session to avoid stale absolute paths from previous pytest
    temp directories baked into CMake state.
    """
    _FETCHCONTENT_CACHE.mkdir(parents=True, exist_ok=True)
    for d in _FETCHCONTENT_CACHE.iterdir():
        if d.is_dir() and (d.name.endswith("-build") or d.name.endswith("-subbuild")):
            shutil.rmtree(d, ignore_errors=True)
    return _FETCHCONTENT_CACHE


# -- Shared build environment helper ------------------------------------------


def _build_env() -> dict[str, str]:
    """Environment for cmake subprocesses that prevents git credential prompts."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


# -- CLAP validator fixture ----------------------------------------------------

_CLAP_VALIDATOR_DIR = _FETCHCONTENT_CACHE.parent / ".clap_validator"
_has_cargo = shutil.which("cargo") is not None


@pytest.fixture(scope="session")
def clap_validator() -> Optional[Path]:
    """Build the clap-validator once per session.

    The validator binary persists in build/.clap_validator/ so it is only
    compiled on first run.  Returns None if cargo is unavailable or the
    build fails.
    """
    if not _has_cargo:
        return None

    src_dir = _CLAP_VALIDATOR_DIR / "src"
    binary = src_dir / "target" / "release" / "clap-validator"

    if binary.is_file() and os.access(binary, os.X_OK):
        return binary

    _CLAP_VALIDATOR_DIR.mkdir(parents=True, exist_ok=True)

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


# -- VST3 validator fixture ----------------------------------------------------

_VST3_VALIDATOR_DIR = _FETCHCONTENT_CACHE.parent / ".vst3_validator"

_VST3_VALIDATOR_CMAKE = textwrap.dedent("""\
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

    Returns None if cmake is unavailable or the build fails.
    """
    if not shutil.which("cmake"):
        return None

    _VST3_VALIDATOR_DIR.mkdir(parents=True, exist_ok=True)
    build_dir = _VST3_VALIDATOR_DIR / "build"
    build_dir.mkdir(exist_ok=True)

    for candidate in build_dir.glob("**/validator"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    cmakelists = _VST3_VALIDATOR_DIR / "CMakeLists.txt"
    cmakelists.write_text(_VST3_VALIDATOR_CMAKE)

    env = _build_env()

    cmake_configure = ["cmake", "..", "-DCMAKE_BUILD_TYPE=Release"]
    sdk_src = fetchcontent_cache / "vst3sdk-src"
    if sdk_src.is_dir():
        cmake_configure.append(f"-DFETCHCONTENT_SOURCE_DIR_VST3SDK={sdk_src}")

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


# -- LV2 validator fixture ----------------------------------------------------

_LV2_VALIDATOR_DIR = _FETCHCONTENT_CACHE.parent / ".lv2_validator"

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

            double energy = 0.0;
            for (int blk = 0; blk < NUM_BLOCKS; blk++) {
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

    Uses pkg-config for lilv-0 flags.  Returns None if lilv-0 is not
    available or compilation fails.
    """
    if not _has_pkg_config_lilv:
        return None

    _LV2_VALIDATOR_DIR.mkdir(parents=True, exist_ok=True)
    binary = _LV2_VALIDATOR_DIR / "lv2_validate"

    if binary.is_file() and os.access(binary, os.X_OK):
        return binary

    src = _LV2_VALIDATOR_DIR / "lv2_validate.c"
    src.write_text(_LV2_VALIDATOR_SRC)

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

    cmd = f"cc {cflags} {str(src)} {libs} -lm -o {str(binary)}"
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=_LV2_VALIDATOR_DIR,
    )
    if result.returncode != 0:
        print(f"LV2 validator compile failed:\n{result.stderr}")
        return None

    return binary
