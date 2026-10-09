"""Tests for the Percussa SSP platform."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectConfig, ProjectGenerator
from gen_dsp.platforms import PLATFORM_REGISTRY, SspPlatform, get_platform
from gen_dsp.platforms.ssp import resolve_ssp_name, ssp_module_name
from tests.helpers import fetchcontent_cmake_args

_HOST_CXX = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
_skip_no_host_build = pytest.mark.skipif(
    shutil.which("cmake") is None or _HOST_CXX is None,
    reason="cmake and C++ compiler required",
)
_HARNESS = Path(__file__).parent / "data" / "ssp_host.cpp"

# Button numbers from Percussa.h
_RIGHT = 9
_SOFT_KEY_1 = 0
_SHIFT_L = 12


_NATIVE_EXPORTS = {"createDescriptor", "createInstance", "getApiVersion"}
_JUCE_EXPORTS = _NATIVE_EXPORTS | {
    "apiExtensions",
    "createExtendedDescriptor",
    "GetPluginFactory",
    "ModuleEntry",
    "ModuleExit",
}


def _assert_exports(so: Path, expected: set[str]) -> None:
    """Checks the module's defined dynamic symbols. ELF only: Apple's linker has no version scripts."""
    if os.uname().sysname == "Darwin":
        return
    readelf = shutil.which("readelf")
    assert readelf is not None, "readelf (binutils) required"
    r = subprocess.run(
        [readelf, "--dyn-syms", "-W", str(so)],
        capture_output=True,
        text=True,
        check=True,
    )
    exported = set()
    for line in r.stdout.splitlines():
        f = line.split()
        # Num: Value Size Type Bind Vis Ndx Name
        if len(f) >= 8 and f[4] in ("GLOBAL", "WEAK") and f[6] != "UND":
            exported.add(f[7].split("@")[0])
    assert exported == expected


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _generate(export: Path, out: Path, name: str, **kwargs) -> Path:
    # off, so -DFETCHCONTENT_BASE_DIR puts the SDK in the test cache
    kwargs.setdefault("shared_cache", False)
    info = GenExportParser(export).parse()
    config = ProjectConfig(name=name, platform="ssp", **kwargs)
    return ProjectGenerator(info, config).generate(out)


class TestSspPlatform:
    def test_registry(self):
        assert PLATFORM_REGISTRY["ssp"] is SspPlatform
        assert isinstance(get_platform("ssp"), SspPlatform)

    def test_extension(self):
        assert SspPlatform().extension == ".so"

    @pytest.mark.parametrize(
        "lib_name, expected",
        [
            ("gigaverb", "gvrb"),
            ("csound", "csnd"),
            ("chuck", "chuk"),  # too few consonants: the first vowel fills in
            ("gain", "gain"),
            ("my-fx", "myfx"),
            ("Verb2000", "vrb2"),
            ("fm", "fmxx"),
            ("___", "gdsp"),
        ],
    )
    def test_module_name(self, lib_name, expected):
        assert ssp_module_name(lib_name) == expected

    def test_resolve_name(self):
        assert resolve_ssp_name(None, "gigaverb") == "gvrb"
        config = ProjectConfig(name="gigaverb", platform="ssp", ssp_name="GvB2")
        assert resolve_ssp_name(config, "gigaverb") == "gvb2"

    @pytest.mark.parametrize(
        "ssp_name, ok",
        [
            ("gvrb", True),
            ("GV22", True),
            ("gvr", False),
            ("verb5", False),
            ("gv-b", False),
        ],
    )
    def test_validate_name(self, ssp_name, ok):
        errors = ProjectConfig(
            name="gigaverb", platform="ssp", ssp_name=ssp_name
        ).validate()
        assert (errors == []) is ok

    def test_cli_rejects_name_without_ssp(self, gigaverb_export, capsys):
        from gen_dsp.cli import main

        assert (
            main(
                [str(gigaverb_export), "-p", "clap", "--ssp-name", "gvrb", "--dry-run"]
            )
            == 1
        )
        assert "--ssp-name is only valid for ssp" in capsys.readouterr().err

    def test_cli_name(self, gigaverb_export, tmp_path, capsys):
        from gen_dsp.cli import main

        out = tmp_path / "p"
        args = [
            str(gigaverb_export),
            "-n",
            "gigaverb",
            "-p",
            "ssp",
            "-o",
            str(out),
            "--no-build",
        ]
        assert main([*args, "--ssp-name", "GVB2"]) == 0
        assert "SSP module: gvb2 (uid GVB2)" in capsys.readouterr().out
        assert (
            'set(SSP_MODULE_NAME "gvb2" CACHE STRING'
            in (out / "CMakeLists.txt").read_text()
        )


class TestSspProjectGeneration:
    def test_files(self, gigaverb_export, tmp_path):
        project = _generate(gigaverb_export, tmp_path / "p", "gigaverb")
        for f in (
            "CMakeLists.txt",
            "ssp_toolchain.cmake",
            "gen_ext_ssp.cpp",
            "_ext_ssp.cpp",
            "_ext_ssp.h",
            "gen_ext_common_ssp.h",
            "gen_buffer.h",
            "ssp_buffer.h",
            "ssp_font.h",
            "gen_remap_inputs.h",
            "ssp_exports.map",
        ):
            assert (project / f).is_file(), f
        assert (project / "gen" / "gen_dsp" / "genlib.cpp").is_file()

    def test_cmakelists(self, gigaverb_export, tmp_path):
        project = _generate(gigaverb_export, tmp_path / "p", "gigaverb")
        cmake = (project / "CMakeLists.txt").read_text()
        assert 'set(SSP_MODULE_NAME "gvrb" CACHE STRING' in cmake
        assert "SSP_EXT_NAME=gigaverb" in cmake
        assert "github.com/percussa/ssp-sdk/archive/" in cmake
        assert "gen/gen_dsp/genlib.cpp" in cmake
        assert '"${CMAKE_CURRENT_SOURCE_DIR}/gen/gen_dsp"' in cmake
        assert "ssp_toolchain.cmake" in cmake
        assert "CXX_VISIBILITY_PRESET hidden" in cmake
        assert "--version-script=${_ssp_map}" in cmake
        # the toolchain must be chosen before project()
        assert cmake.index("CMAKE_TOOLCHAIN_FILE") < cmake.index("\nproject(")

    def test_toolchain(self, gigaverb_export, tmp_path):
        project = _generate(gigaverb_export, tmp_path / "p", "gigaverb")
        tc = (project / "ssp_toolchain.cmake").read_text()
        assert "-mcpu=cortex-a17 -mfloat-abi=hard -mfpu=neon-vfpv4" in tc
        assert "arm-rockchip-linux-gnueabihf_sdk-buildroot" in tc
        assert "-fuse-ld=lld" in tc

    def test_remap_defines(self, gigaverb_export, tmp_path):
        project = _generate(
            gigaverb_export, tmp_path / "p", "gigaverb", inputs_as_params=[]
        )
        assert "REMAP_INPUT_COUNT=2" in (project / "CMakeLists.txt").read_text()

    def test_buffers(self, rampleplayer_export, tmp_path):
        project = _generate(
            rampleplayer_export, tmp_path / "p", "rample", buffers=["sample"]
        )
        assert (
            "#define WRAPPER_BUFFER_NAME_0 sample"
            in (project / "gen_buffer.h").read_text()
        )
        names = (project / "ssp_buffer_names.h").read_text()
        assert "#define sample SSP_BUFFER(0)" in names
        assert "#undef sample" in names

    def test_graph_project(self, tmp_path):
        pytest.importorskip("pydantic")
        project = ProjectGenerator.from_graph(
            _gain_graph(), ProjectConfig(name="gain", platform="ssp")
        ).generate(tmp_path / "g")
        for f in (
            "gen_ext_ssp.cpp",
            "_ext_ssp.cpp",
            "_ext_ssp.h",
            "ssp_font.h",
            "ssp_toolchain.cmake",
            "ssp_exports.map",
        ):
            assert (project / f).is_file(), f
        cmake = (project / "CMakeLists.txt").read_text()
        assert "genlib.cpp" not in cmake
        # the user's name survives the shared graph step, which cannot see it
        config = ProjectConfig(name="gain", platform="ssp", ssp_name="GN01")
        project = ProjectGenerator.from_graph(_gain_graph(), config).generate(
            tmp_path / "g2"
        )
        assert (
            'set(SSP_MODULE_NAME "gn01" CACHE STRING'
            in (project / "CMakeLists.txt").read_text()
        )
        assert 'set(SSP_MODULE_NAME "gain" CACHE STRING' in cmake


def _gain_graph():
    from gen_dsp.graph import AudioInput, AudioOutput, BinOp, Graph, Param

    return Graph(
        name="gain",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="scaled")],
        params=[Param(name="volume", min=0.0, max=2.0, default=0.5)],
        nodes=[BinOp(id="scaled", op="mul", a="in1", b="volume")],
    )


# -- Host build, driven through the Percussa API -----------------------------------


def _host_build(project: Path, cache: Path) -> Path:
    build = project / "build"
    cmd = [
        "cmake",
        "-S",
        str(project),
        "-B",
        str(build),
        "-DSSP_HOST_BUILD=ON",
        *fetchcontent_cmake_args(cache),
    ]
    for step in (cmd, ["cmake", "--build", str(build)]):
        r = subprocess.run(
            step, capture_output=True, text=True, env=_build_env(), check=False
        )
        assert r.returncode == 0, f"{step}\n{r.stdout}\n{r.stderr}"
    so = SspPlatform().find_output(project)
    assert so is not None and so.name == f"{project.name}.so"
    return so


def _drive(host: Path, so: Path, *cmds: object) -> list[list[str]]:
    r = subprocess.run(
        [str(host), str(so), *map(str, cmds)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return [
        line.split("\t") if line.startswith("state") else line.split()
        for line in r.stdout.splitlines()
    ]


def _params(lines: list[list[str]]) -> dict[str, float]:
    return {f[1]: float(f[2]) for f in lines if f[0] == "state param"}


def _page(lines: list[list[str]]) -> int:
    return next(int(f[1]) for f in lines if f[0] == "state page")


class TestSspHostBuild:
    """Builds for the host and drives the module as Synthor would."""

    @_skip_no_host_build
    def test_build_ssp_gigaverb(self, gigaverb_export, tmp_path, fetchcontent_cache):
        project = _generate(gigaverb_export, tmp_path / "gigaverb", "gigaverb")
        so = _host_build(project, fetchcontent_cache)
        host = self._harness(fetchcontent_cache, tmp_path)

        out = _drive(host, so, "desc", "prepare", 48000, 64, "run", 50, 200)
        assert ["api", "3.5"] in out
        assert ["name", "gvrb"] in out
        assert ["uid", "47565242"] in out  # "GVRB"
        assert ["io", "2", "2"] in out
        _assert_exports(so, _NATIVE_EXPORTS)
        # 200-sample blocks exceed the announced 64, so the module splits them
        levels = [float(f[2]) for f in out if f[0] == "level"]
        assert len(levels) == 2 and all(v > 0 for v in levels)
        assert ["finite", "1"] in out

    @_skip_no_host_build
    def test_build_ssp_controls_and_state(
        self, gigaverb_export, tmp_path, fetchcontent_cache
    ):
        project = _generate(gigaverb_export, tmp_path / "gigaverb", "gigaverb")
        so = _host_build(project, fetchcontent_cache)
        host = self._harness(fetchcontent_cache, tmp_path)

        before = _drive(host, so, "state")
        names = list(_params(before))
        p0, p5 = names[0], names[5]
        assert _page(before) == 0

        # encoder 0 on page 0 edits param 0 by 1% of its range per pulse
        after = _drive(host, so, "turn", 0, 10, "state")
        assert _params(after)[p0] == pytest.approx(_params(before)[p0] + 0.1, abs=1e-6)

        # Right moves to page 1, where encoder 1 edits param 5; Shift makes it 10x finer
        coarse = _params(_drive(host, so, "down", _RIGHT, "turn", 1, -3, "state"))[p5]
        fine = _params(
            _drive(host, so, "down", _RIGHT, "down", _SHIFT_L, "turn", 1, -3, "state")
        )[p5]
        base = _params(before)[p5]
        assert base - coarse == pytest.approx(10 * (base - fine), rel=1e-4)

        # an encoder press resets to the default; values clamp to the range
        out = _drive(host, so, "turn", 0, 1000, "state", "press", 0, "state")
        states = [f for f in out if f[0] == "state param" and f[1] == p0]
        assert float(states[0][2]) == pytest.approx(1.0)  # bandwidth max
        assert float(states[1][2]) == pytest.approx(_params(before)[p0])

        # soft keys pick a page; out-of-range pages clamp
        assert _page(_drive(host, so, "down", _SOFT_KEY_1 + 1, "state")) == 1
        assert _page(_drive(host, so, "down", _SOFT_KEY_1 + 7, "state")) == 1

        # setState restores what getState saved
        out = _drive(host, so, "save", "turn", 0, 10, "down", _RIGHT, "load", "state")
        assert _params(out) == _params(before)
        assert _page(out) == 0

    @_skip_no_host_build
    @pytest.mark.parametrize(
        "fixture, name, io, buffers",
        [
            ("spectraldelayfb_export", "sdfb", ["3", "2"], []),
            ("rampleplayer_export", "rample", ["1", "2"], ["sample"]),
        ],
    )
    def test_build_ssp_io_shapes(
        self, request, fixture, name, io, buffers, tmp_path, fetchcontent_cache
    ):
        """More inputs than outputs, and the reverse, share one in-place buffer."""
        project = _generate(
            request.getfixturevalue(fixture), tmp_path / name, name, buffers=buffers
        )
        so = _host_build(project, fetchcontent_cache)
        host = self._harness(fetchcontent_cache, tmp_path)
        out = _drive(host, so, "desc", "prepare", 44100, 128, "run", 20, 128)
        assert ["io", *io] in out
        assert ["finite", "1"] in out

    @_skip_no_host_build
    def test_build_ssp_graph(self, tmp_path, fetchcontent_cache):
        pytest.importorskip("pydantic")
        config = ProjectConfig(
            name="gain", platform="ssp", shared_cache=False, ssp_name="GN01"
        )
        project = ProjectGenerator.from_graph(_gain_graph(), config).generate(
            tmp_path / "gain"
        )
        so = _host_build(project, fetchcontent_cache)
        host = self._harness(fetchcontent_cache, tmp_path)
        out = _drive(host, so, "desc")
        assert ["name", "gn01"] in out
        assert ["uid", "474e3031"] in out  # "GN01": the same 4 characters
        _assert_exports(so, _NATIVE_EXPORTS)
        # impulse of 1.0 times volume 0.5
        out = _drive(host, so, "prepare", 48000, 64, "run", 1, 64)
        assert ["level", "0", "0.5"] in out
        # 10 pulses of 1% of the 0..2 range
        out = _drive(host, so, "prepare", 48000, 64, "turn", 0, 10, "run", 1, 64)
        assert ["level", "0", "0.7"] in out

    @_skip_no_host_build
    def test_build_ssp_render(self, gigaverb_export, tmp_path, fetchcontent_cache):
        project = _generate(gigaverb_export, tmp_path / "gigaverb", "gigaverb")
        so = _host_build(project, fetchcontent_cache)
        host = self._harness(fetchcontent_cache, tmp_path)
        for w, h in ((1600, 480), (320, 240)):
            ppm = tmp_path / f"screen_{w}.ppm"
            _drive(host, so, "render", w, h, ppm)
            header, _, pixels = ppm.read_bytes().partition(b"255\n")
            assert header.split()[1:3] == [str(w).encode(), str(h).encode()]
            rgb = [pixels[i : i + 3] for i in range(0, len(pixels), 3)]
            # the harness fills with 0x55; the module must clear every pixel
            assert b"\x55\x55\x55" not in set(rgb)
            assert sum(px == b"\xff\xff\xff" for px in rgb) > 100  # text was drawn

    @staticmethod
    def _harness(cache: Path, tmp_path: Path) -> Path:
        sdk = cache / "ssp_sdk-src"
        exe = tmp_path / "ssp_host"
        if exe.is_file():
            return exe
        cmd = [
            _HOST_CXX,
            "-std=c++17",
            "-O1",
            f"-I{sdk}",
            str(_HARNESS),
            "-o",
            str(exe),
        ]
        if os.uname().sysname != "Darwin":
            cmd.append("-ldl")
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr
        return exe


# -- Cross build -------------------------------------------------------------------------


def _buildroot() -> Path | None:
    if os.environ.get("SSP_BUILDROOT"):
        return Path(os.environ["SSP_BUILDROOT"])
    from gen_dsp.core.cache import get_cache_dir

    cached = (
        get_cache_dir() / "ssp-buildroot" / "arm-rockchip-linux-gnueabihf_sdk-buildroot"
    )
    return cached if cached.is_dir() else None


@pytest.mark.skipif(
    _buildroot() is None or shutil.which("ld.lld") is None,
    reason="SSP buildroot (SSP_BUILDROOT or the gen-dsp cache) and ld.lld required",
)
def test_cross_build_ssp_gigaverb(gigaverb_export, tmp_path, fetchcontent_cache):
    """Cross-compiles for the SSP and checks the result is a 32-bit ARM shared object."""
    project = _generate(gigaverb_export, tmp_path / "gigaverb", "gigaverb")
    build = project / "build"
    configure = [
        "cmake",
        "-S",
        str(project),
        "-B",
        str(build),
        f"-DSSP_BUILDROOT={_buildroot()}",
        *fetchcontent_cmake_args(fetchcontent_cache),
    ]
    for step in (configure, ["cmake", "--build", str(build)]):
        r = subprocess.run(
            step, capture_output=True, text=True, env=_build_env(), check=False
        )
        assert r.returncode == 0, f"{step}\n{r.stdout}\n{r.stderr}"
    so = SspPlatform().find_output(project)
    assert so is not None
    elf = so.read_bytes()[:20]
    assert elf[:4] == b"\x7fELF"
    assert elf[4] == 1  # ELFCLASS32
    assert elf[16] == 3  # ET_DYN
    assert int.from_bytes(elf[18:20], "little") == 40  # EM_ARM
    _assert_exports(so, _NATIVE_EXPORTS)


# -- JUCE format -----------------------------------------------------------------------


class TestSspJuceGeneration:
    def test_files(self, gigaverb_export, tmp_path):
        project = _generate(
            gigaverb_export, tmp_path / "p", "gigaverb", ssp_format="juce"
        )
        for f in (
            "CMakeLists.txt",
            "ssp_toolchain.cmake",
            "PluginProcessor.h",
            "PluginProcessor.cpp",
            "SSPApi.cpp",
            "_ext_ssp.cpp",
            "_ext_ssp.h",
            "gen_ext_common_ssp.h",
            "gen_buffer.h",
            "ssp_buffer.h",
            "ssp_exports.map",
        ):
            assert (project / f).is_file(), f
        assert "ModuleEntry;" in (project / "ssp_exports.map").read_text()
        # the native module and its font are not part of this format
        assert not (project / "gen_ext_ssp.cpp").exists()
        assert not (project / "ssp_font.h").exists()

    def test_cmakelists(self, gigaverb_export, tmp_path):
        project = _generate(
            gigaverb_export, tmp_path / "p", "gigaverb", ssp_format="juce"
        )
        cmake = (project / "CMakeLists.txt").read_text()
        assert "juce_add_plugin(${PROJECT_NAME}" in cmake
        assert "PLUGIN_CODE ${_ssp_code}" in cmake
        assert 'set(SSP_MODULE_NAME "gvrb" CACHE STRING' in cmake
        assert 'set(SSP_DEV_DIR "" CACHE PATH' in cmake
        assert "github.com/shakfu/ssp/archive/" in cmake
        assert "github.com/TheTechnobear/juce/archive/" in cmake
        assert '"${CMAKE_CURRENT_SOURCE_DIR}/PluginProcessor.cpp"' in cmake
        assert '"${CMAKE_CURRENT_SOURCE_DIR}/gen/gen_dsp/genlib.cpp"' in cmake
        assert "gen_ext_ssp.cpp" not in cmake
        assert cmake.index("CMAKE_TOOLCHAIN_FILE") < cmake.index("\nproject(")

    def test_dev_dir(self, gigaverb_export, tmp_path):
        dev = tmp_path / "ssp"
        project = _generate(
            gigaverb_export,
            tmp_path / "p",
            "gigaverb",
            ssp_format="juce",
            ssp_dev_dir=dev,
        )
        cmake = (project / "CMakeLists.txt").read_text()
        assert f'set(SSP_DEV_DIR "{dev.as_posix()}" CACHE PATH' in cmake

    def test_toolchain_pkg_config(self, gigaverb_export, tmp_path):
        """JUCE finds FreeType through pkg-config, which must search the sysroot."""
        project = _generate(
            gigaverb_export, tmp_path / "p", "gigaverb", ssp_format="juce"
        )
        tc = (project / "ssp_toolchain.cmake").read_text()
        assert "PKG_CONFIG_SYSROOT_DIR=${_ssp_sysroot}" in tc

    def test_graph_project(self, tmp_path):
        pytest.importorskip("pydantic")
        config = ProjectConfig(name="gain", platform="ssp", ssp_format="juce")
        project = ProjectGenerator.from_graph(_gain_graph(), config).generate(
            tmp_path / "g"
        )
        assert (project / "PluginProcessor.cpp").is_file()
        assert (project / "_ext_ssp.cpp").is_file()
        assert not (project / "gen_ext_ssp.cpp").exists()
        cmake = (project / "CMakeLists.txt").read_text()
        assert "juce_add_plugin" in cmake
        assert "genlib.cpp" not in cmake

    @pytest.mark.parametrize(
        "fmt, ok", [("native", True), ("juce", True), ("vst", False)]
    )
    def test_validate_format(self, fmt, ok):
        errors = ProjectConfig(name="g", platform="ssp", ssp_format=fmt).validate()
        assert (errors == []) is ok

    @pytest.mark.parametrize(
        "args, message",
        [
            (
                ["-p", "clap", "--ssp-format", "juce"],
                "--ssp-format is only valid for ssp",
            ),
            (
                ["-p", "ssp", "--ssp-dev-dir", "x"],
                "--ssp-dev-dir requires --ssp-format juce",
            ),
        ],
    )
    def test_cli_errors(self, gigaverb_export, capsys, args, message):
        from gen_dsp.cli import main

        assert main([str(gigaverb_export), *args, "--dry-run"]) == 1
        assert message in capsys.readouterr().err


_SSP_DEV_DIR = os.environ.get("SSP_DEV_DIR")


@_skip_no_host_build
@pytest.mark.skipif(
    not _SSP_DEV_DIR or not Path(_SSP_DEV_DIR, "juce", "CMakeLists.txt").is_file(),
    reason="SSP_DEV_DIR (a shakfu/ssp checkout with submodules) required",
)
def test_host_build_ssp_juce_matches_native(
    gigaverb_export, tmp_path, fetchcontent_cache
):
    """The JUCE module produces the native module's audio, through the Percussa API."""
    assert _SSP_DEV_DIR is not None
    dev = Path(_SSP_DEV_DIR)
    native = _host_build(
        _generate(gigaverb_export, tmp_path / "gigaverb", "gigaverb"),
        fetchcontent_cache,
    )
    project = _generate(
        gigaverb_export,
        tmp_path / "juce",
        "gigaverb",
        ssp_format="juce",
        ssp_dev_dir=dev,
    )
    build = project / "build"
    for step in (
        ["cmake", "-S", str(project), "-B", str(build), "-DSSP_HOST_BUILD=ON"],
        ["cmake", "--build", str(build), "--parallel", str(os.cpu_count() or 1)],
    ):
        r = subprocess.run(
            step, capture_output=True, text=True, env=_build_env(), check=False
        )
        assert r.returncode == 0, f"{step}\n{r.stdout[-4000:]}\n{r.stderr[-4000:]}"
    juce = SspPlatform().find_output(project)
    assert juce is not None and juce.name == "gvrb.so"
    _assert_exports(juce, _JUCE_EXPORTS)

    exe = tmp_path / "ssp_host"
    cmd = [_HOST_CXX, "-std=c++17", "-O1", f"-I{dev / 'ssp-sdk'}", str(_HARNESS)]
    r = subprocess.run(
        [*cmd, "-o", str(exe), "-ldl"], capture_output=True, text=True, check=False
    )
    assert r.returncode == 0, r.stderr

    def levels(so: Path, *cmds: object) -> list[list[str]]:
        return [f for f in _drive(exe, so, *cmds) if f[0] == "level"]

    out = _drive(exe, juce, "desc")
    assert ["name", "gvrb"] in out
    assert ["uid", "47565242"] in out
    assert ["io", "2", "2"] in out

    run = ("prepare", 48000, 64, "run", 50, 200)
    assert levels(juce, *run) == levels(native, *run)

    # the framework routes encoders through the editor, which the host creates
    # before turning them; it takes one step per call, 1% of the range
    turned = levels(
        juce,
        "prepare",
        48000,
        64,
        "render",
        320,
        240,
        tmp_path / "s.ppm",
        "turn",
        0,
        1,
        "run",
        50,
        200,
    )
    assert turned == levels(native, "prepare", 48000, 64, "turn", 0, 1, "run", 50, 200)
    assert turned != levels(native, *run)

    # setState restores what getState saved
    restored = levels(
        juce,
        "prepare",
        48000,
        64,
        "render",
        320,
        240,
        tmp_path / "s.ppm",
        "save",
        "turn",
        0,
        1,
        "load",
        "run",
        50,
        200,
    )
    assert restored == levels(native, *run)


@pytest.mark.skipif(
    _buildroot() is None
    or shutil.which("ld.lld") is None
    or not _SSP_DEV_DIR
    or not Path(_SSP_DEV_DIR, "juce", "CMakeLists.txt").is_file(),
    reason="SSP buildroot, ld.lld and SSP_DEV_DIR required",
)
def test_cross_build_ssp_juce(gigaverb_export, tmp_path):
    """Cross-compiles the JUCE format; links against the sysroot's FreeType."""
    assert _SSP_DEV_DIR is not None
    project = _generate(
        gigaverb_export,
        tmp_path / "gigaverb",
        "gigaverb",
        ssp_format="juce",
        ssp_dev_dir=Path(_SSP_DEV_DIR),
    )
    build = project / "build"
    for step in (
        [
            "cmake",
            "-S",
            str(project),
            "-B",
            str(build),
            f"-DSSP_BUILDROOT={_buildroot()}",
        ],
        ["cmake", "--build", str(build), "--parallel", str(os.cpu_count() or 1)],
    ):
        r = subprocess.run(
            step, capture_output=True, text=True, env=_build_env(), check=False
        )
        assert r.returncode == 0, f"{step}\n{r.stdout[-4000:]}\n{r.stderr[-4000:]}"
    so = build / "gvrb.so"
    elf = so.read_bytes()[:20]
    assert elf[:4] == b"\x7fELF" and elf[4] == 1
    assert int.from_bytes(elf[18:20], "little") == 40  # EM_ARM
    _assert_exports(so, _JUCE_EXPORTS)


# -- Buffers -----------------------------------------------------------------------------

_BUFFERS_TEST = Path(__file__).parent / "data" / "ssp_buffers_test.cpp"
_HOST_CC = shutil.which("clang") or shutil.which("cc")


def _write_wav(path: Path, value: int, frames: int = 1000) -> Path:
    """Mono 16-bit WAV holding a constant."""
    import struct
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(struct.pack(f"<{frames}h", *([value] * frames)))
    return path


@pytest.mark.skipif(
    shutil.which("clang++") is None
    or _HOST_CC is None
    or os.uname().sysname == "Darwin",
    reason="clang++ with sanitizers on Linux required",
)
@pytest.mark.parametrize("sanitizer", ["address,undefined", "thread"])
def test_buffers_per_instance_and_thread_safe(rampleplayer_export, tmp_path, sanitizer):
    """Instances own their buffers, run on separate threads, and take loads mid-perform."""
    project = _generate(
        rampleplayer_export, tmp_path / "rample", "rample", buffers=["sample"]
    )
    defines = [
        "-DGENLIB_USE_FLOAT32",
        "-DSSP_EXT_NAME=rample",
        "-DGEN_EXPORTED_NAME=RamplePlayer",
        '-DGEN_EXPORTED_HEADER="RamplePlayer.h"',
        '-DGEN_EXPORTED_CPP="RamplePlayer.cpp"',
    ]
    includes = [
        f"-I{project}",
        f"-I{project / 'gen'}",
        f"-I{project / 'gen' / 'gen_dsp'}",
    ]
    # a shared sanitizer runtime: TSan's static one defines the operator new genlib replaces
    flags = [
        "-g",
        "-O1",
        f"-fsanitize={sanitizer}",
        "-shared-libsan",
        *defines,
        *includes,
    ]
    objs = []
    for c in ("json.c", "json_builder.c"):
        obj = tmp_path / f"{c}.o"
        subprocess.run(
            [
                _HOST_CC,
                "-c",
                *flags,
                str(project / "gen" / "gen_dsp" / c),
                "-o",
                str(obj),
            ],
            check=True,
        )
        objs.append(str(obj))
    exe = tmp_path / "ssp_buffers_test"
    runtime = subprocess.run(
        ["clang++", "--print-runtime-dir"], capture_output=True, text=True, check=True
    ).stdout.strip()
    r = subprocess.run(
        [
            "clang++",
            "-std=c++17",
            "-pthread",
            *flags,
            str(_BUFFERS_TEST),
            str(project / "_ext_ssp.cpp"),
            str(project / "gen" / "gen_dsp" / "genlib.cpp"),
            *objs,
            "-ldl",
            f"-Wl,-rpath,{runtime}",
            "-o",
            str(exe),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    a = _write_wav(tmp_path / "a.wav", 16384)  # 0.5
    b = _write_wav(tmp_path / "b.wav", 8192)  # 0.25
    env = dict(os.environ, TSAN_OPTIONS="exitcode=66")
    r = subprocess.run(
        [str(exe), str(a), str(b)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )
    assert r.returncode == 0, r.stderr[-4000:]
    assert r.stdout.strip() == "ok"


def _rample_levels(lines: list[list[str]]) -> list[float]:
    return [float(f[2]) for f in lines if f[0] == "level"]


@_skip_no_host_build
def test_host_build_ssp_loads_buffer_file(
    rampleplayer_export, tmp_path, fetchcontent_cache
):
    """The native module reads <card>/<module>/<buffer>.wav beside plugins/."""
    project = _generate(
        rampleplayer_export, tmp_path / "rample", "rample", buffers=["sample"]
    )
    so = _host_build(project, fetchcontent_cache)
    host = TestSspHostBuild._harness(fetchcontent_cache, tmp_path)
    run = ("prepare", 48000, 64, "run", 4, 64)
    # out1 plays the buffer; without a file it is empty
    assert _rample_levels(_drive(host, so, *run))[0] == 0
    # the module is build/rample.so, so its folder is <project>/rmpl
    _write_wav(project / "rmpl" / "sample.wav", 16384)  # 0.5
    assert _rample_levels(_drive(host, so, *run))[0] == pytest.approx(4 * 64 * 0.5)


def _set_juce_path(state: bytes, attribute: str, path: str) -> bytes:
    """Rewrites one attribute in a JUCE state blob: magic, uint32 size, XML, NUL."""
    import re
    import struct

    magic, size = state[:4], struct.unpack("<I", state[4:8])[0]
    xml = state[8 : 8 + size].rstrip(b"\0").decode()
    xml = re.sub(f'{attribute}="[^"]*"', f'{attribute}="{path}"', xml)
    body = xml.encode() + b"\0"
    return magic + struct.pack("<I", len(body)) + body


@_skip_no_host_build
@pytest.mark.skipif(
    not _SSP_DEV_DIR or not Path(_SSP_DEV_DIR, "juce", "CMakeLists.txt").is_file(),
    reason="SSP_DEV_DIR (a shakfu/ssp checkout with submodules) required",
)
def test_host_build_ssp_juce_buffers(rampleplayer_export, tmp_path):
    """The JUCE module loads the default file, keeps its path in presets, and loads a preset's."""
    assert _SSP_DEV_DIR is not None
    dev = Path(_SSP_DEV_DIR)
    project = _generate(
        rampleplayer_export,
        tmp_path / "rample",
        "rample",
        buffers=["sample"],
        ssp_format="juce",
        ssp_dev_dir=dev,
    )
    build = project / "build"
    for step in (
        ["cmake", "-S", str(project), "-B", str(build), "-DSSP_HOST_BUILD=ON"],
        ["cmake", "--build", str(build), "--parallel", str(os.cpu_count() or 1)],
    ):
        r = subprocess.run(
            step, capture_output=True, text=True, env=_build_env(), check=False
        )
        assert r.returncode == 0, f"{step}\n{r.stdout[-4000:]}\n{r.stderr[-4000:]}"
    so = build / "rmpl.so"
    exe = tmp_path / "ssp_host"
    cmd = [_HOST_CXX, "-std=c++17", "-O1", f"-I{dev / 'ssp-sdk'}", str(_HARNESS)]
    r = subprocess.run(
        [*cmd, "-o", str(exe), "-ldl", "-pthread"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr

    default = _write_wav(project / "rmpl" / "sample.wav", 16384)  # 0.5
    other = _write_wav(tmp_path / "other.wav", 8192)  # 0.25
    state = tmp_path / "state.bin"
    # loads run on the module's worker thread, every 10 ms
    run = ("prepare", 48000, 64, "sleep", 100, "run", 4, 64)
    out = _drive(exe, so, *run, "savefile", state)
    assert _rample_levels(out)[0] == pytest.approx(4 * 64 * 0.5)
    assert f'buffer_sample="{default}"'.encode() in state.read_bytes()

    state.write_bytes(_set_juce_path(state.read_bytes(), "buffer_sample", str(other)))
    out = _drive(exe, so, "loadfile", state, *run)
    assert _rample_levels(out)[0] == pytest.approx(4 * 64 * 0.25)
