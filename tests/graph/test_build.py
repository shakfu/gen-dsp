"""Build integration tests for dsp-graph projects across all platforms.

Each test generates a project from a Graph object via ProjectGenerator.from_graph()
and compiles it with the platform's native toolchain. Tests are gated by tool
availability (cmake, make, C++ compiler) and skip gracefully when tools are missing.
"""

from __future__ import annotations

import os
import platform as sys_platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest

pydantic = pytest.importorskip("pydantic")

from tests.helpers import (
    validate_chugin,
    validate_clap,
    validate_lv2,
    validate_pd_external,
    validate_vst3,
)

from gen_dsp.core.project import ProjectConfig, ProjectGenerator
from gen_dsp.graph import (
    ADSR,
    AudioInput,
    AudioOutput,
    BinOp,
    Buffer,
    Cycle,
    Graph,
    OnePole,
    Param,
    Phasor,
    SinOsc,
)

# ---------------------------------------------------------------------------
# Tool availability checks
# ---------------------------------------------------------------------------

_has_cmake = shutil.which("cmake") is not None
_has_make = shutil.which("make") is not None
_has_cxx = shutil.which("c++") is not None or shutil.which("g++") is not None
_has_chuck = shutil.which("chuck") is not None
_is_macos = sys_platform.system().lower() == "darwin"

_skip_no_cmake = pytest.mark.skipif(
    not (_has_cmake and _has_cxx), reason="cmake and C++ compiler required"
)
_skip_no_make = pytest.mark.skipif(
    not (_has_make and _has_cxx), reason="make and C++ compiler required"
)
_has_arm_gcc = shutil.which("arm-none-eabi-gcc") is not None
_has_aarch64_gcc = shutil.which("aarch64-none-elf-gcc") is not None
_has_git = shutil.which("git") is not None

_skip_no_au = pytest.mark.skipif(
    not (_is_macos and _has_cmake and _has_cxx),
    reason="macOS with cmake and C++ compiler required",
)
_skip_no_daisy = pytest.mark.skipif(
    not (_has_make and _has_arm_gcc and _has_git),
    reason="make, arm-none-eabi-gcc, and git required",
)
_skip_no_circle = pytest.mark.skipif(
    not (_has_make and _has_aarch64_gcc and _has_git),
    reason="make, aarch64-none-elf-gcc, and git required",
)


def _build_env() -> dict[str, str]:
    """Environment for cmake subprocesses that prevents git credential prompts."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


# ---------------------------------------------------------------------------
# Graph fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gain_graph() -> Graph:
    """Minimal mono gain effect (1in/1out, 1 param)."""
    return Graph(
        name="gain",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="scaled")],
        params=[Param(name="volume", min=0.0, max=1.0, default=0.5)],
        nodes=[BinOp(id="scaled", op="mul", a="in1", b="volume")],
    )


@pytest.fixture
def stereo_graph() -> Graph:
    """Stereo effect (2in/2out, 1 param) -- tests multi-channel handling."""
    return Graph(
        name="stereo_gain",
        inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
        outputs=[
            AudioOutput(id="out1", source="s1"),
            AudioOutput(id="out2", source="s2"),
        ],
        params=[Param(name="gain", min=0.0, max=2.0, default=1.0)],
        nodes=[
            BinOp(id="s1", op="mul", a="in1", b="gain"),
            BinOp(id="s2", op="mul", a="in2", b="gain"),
        ],
    )


@pytest.fixture
def generator_graph() -> Graph:
    """Generator (0 inputs) -- tests instrument/generator detection."""
    return Graph(
        name="sine_gen",
        inputs=[],
        outputs=[AudioOutput(id="out1", source="scaled")],
        params=[
            Param(name="freq", min=20.0, max=20000.0, default=440.0),
            Param(name="amp", min=0.0, max=1.0, default=0.3),
        ],
        nodes=[
            SinOsc(id="osc", freq="freq"),
            BinOp(id="scaled", op="mul", a="osc", b="amp"),
        ],
    )


@pytest.fixture
def filter_graph() -> Graph:
    """Filter graph with stateful node (OnePole) -- tests History/state codegen."""
    return Graph(
        name="lowpass",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="filt")],
        params=[Param(name="coeff", min=0.0, max=0.999, default=0.5)],
        nodes=[OnePole(id="filt", a="in1", coeff="coeff")],
    )


@pytest.fixture
def buffer_graph() -> Graph:
    """Graph with Buffer + Cycle nodes -- tests buffer codegen path."""
    return Graph(
        name="wavetable",
        inputs=[],
        outputs=[AudioOutput(id="out1", source="scaled")],
        params=[
            Param(name="freq", min=20.0, max=20000.0, default=440.0),
            Param(name="amp", min=0.0, max=1.0, default=0.3),
        ],
        nodes=[
            Buffer(id="sine_tbl", size=512, fill="sine"),
            Phasor(id="phase", freq="freq"),
            Cycle(id="osc", buffer="sine_tbl", phase="phase"),
            BinOp(id="scaled", op="mul", a="osc", b="amp"),
        ],
    )


@pytest.fixture
def multichannel_graph() -> Graph:
    """3in/2out graph -- tests multi-channel I/O handling."""
    return Graph(
        name="mixer3to2",
        inputs=[
            AudioInput(id="in1"),
            AudioInput(id="in2"),
            AudioInput(id="in3"),
        ],
        outputs=[
            AudioOutput(id="out1", source="left"),
            AudioOutput(id="out2", source="right"),
        ],
        params=[Param(name="gain", min=0.0, max=1.0, default=0.5)],
        nodes=[
            BinOp(id="sum_l", op="add", a="in1", b="in3"),
            BinOp(id="left", op="mul", a="sum_l", b="gain"),
            BinOp(id="sum_r", op="add", a="in2", b="in3"),
            BinOp(id="right", op="mul", a="sum_r", b="gain"),
        ],
    )


@pytest.fixture
def midi_synth_graph() -> Graph:
    """Generator with gate/freq/vel params -- tests MIDI mapping path."""
    return Graph(
        name="synth",
        inputs=[],
        outputs=[AudioOutput(id="out1", source="output")],
        params=[
            Param(name="gate", min=0.0, max=1.0, default=0.0),
            Param(name="freq", min=20.0, max=20000.0, default=440.0),
            Param(name="vel", min=0.0, max=1.0, default=0.8),
            Param(name="attack", min=1.0, max=5000.0, default=10.0),
            Param(name="release", min=1.0, max=5000.0, default=200.0),
        ],
        nodes=[
            SinOsc(id="osc", freq="freq"),
            ADSR(
                id="env",
                gate="gate",
                attack="attack",
                decay=50.0,
                sustain=0.8,
                release="release",
            ),
            BinOp(id="env_osc", op="mul", a="osc", b="env"),
            BinOp(id="output", op="mul", a="env_osc", b="vel"),
        ],
    )


# ---------------------------------------------------------------------------
# CMake build helpers
# ---------------------------------------------------------------------------


def _cmake_build(
    project_dir: Path,
    fetchcontent_cache: Optional[Path] = None,
    extra_args: Optional[list[str]] = None,
) -> None:
    """Configure and build a CMake project, asserting success at each step."""
    build_dir = project_dir / "build"
    build_dir.mkdir(exist_ok=True)
    env = _build_env()

    cmake_args = ["cmake", ".."]
    if fetchcontent_cache is not None:
        cmake_args.append(f"-DFETCHCONTENT_BASE_DIR={fetchcontent_cache}")
    if extra_args:
        cmake_args.extend(extra_args)

    result = subprocess.run(
        cmake_args,
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    assert result.returncode == 0, (
        f"cmake configure failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    result = subprocess.run(
        ["cmake", "--build", "."],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert result.returncode == 0, (
        f"cmake build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def _make_build(
    project_dir: Path,
    target: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> None:
    """Run make in a project directory, asserting success."""
    cmd = ["make"]
    if target:
        cmd.append(target)
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        cmd,
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# PureData (make-based)
# ---------------------------------------------------------------------------


class TestBuildPdFromGraph:
    @_skip_no_make
    def test_build_pd_gain(self, gain_graph: Graph, tmp_path: Path) -> None:
        """Build a PD external from a graph."""
        project_dir = tmp_path / "gain_pd"
        config = ProjectConfig(name="gain", platform="pd")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

        _make_build(project_dir, target="all")

        from gen_dsp.platforms.puredata import PureDataPlatform

        output = PureDataPlatform().find_output(project_dir)
        assert output is not None
        assert output.stat().st_size > 0

        validate_pd_external(project_dir, "gain")

    @_skip_no_make
    def test_build_pd_stereo(self, stereo_graph: Graph, tmp_path: Path) -> None:
        """Build a stereo PD external from a graph."""
        project_dir = tmp_path / "stereo_pd"
        config = ProjectConfig(name="stereo_gain", platform="pd")
        gen = ProjectGenerator.from_graph(stereo_graph, config)
        gen.generate(project_dir)

        _make_build(project_dir, target="all")

        from gen_dsp.platforms.puredata import PureDataPlatform

        output = PureDataPlatform().find_output(project_dir)
        assert output is not None

        validate_pd_external(project_dir, "stereo_gain")


# ---------------------------------------------------------------------------
# ChucK (make-based)
# ---------------------------------------------------------------------------


class TestBuildChuckFromGraph:
    @_skip_no_make
    def test_build_chuck_gain(self, gain_graph: Graph, tmp_path: Path) -> None:
        """Build a ChucK chugin from a graph."""
        project_dir = tmp_path / "gain_chuck"
        config = ProjectConfig(name="gain", platform="chuck")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

        target = "mac" if _is_macos else "linux"
        _make_build(project_dir, target=target)

        chug_files = list(project_dir.glob("*.chug"))
        assert len(chug_files) == 1
        assert chug_files[0].stat().st_size > 0

        # NOTE: "Gain" collides with ChucK's built-in Gain UGen, skip validation
        # ChucK validation is tested via filter_graph ("Lowpass") below

    @_skip_no_make
    def test_build_chuck_filter(self, filter_graph: Graph, tmp_path: Path) -> None:
        """Build a ChucK chugin with stateful OnePole node."""
        project_dir = tmp_path / "lowpass_chuck"
        config = ProjectConfig(name="lowpass", platform="chuck")
        gen = ProjectGenerator.from_graph(filter_graph, config)
        gen.generate(project_dir)

        target = "mac" if _is_macos else "linux"
        _make_build(project_dir, target=target)

        chug_files = list(project_dir.glob("*.chug"))
        assert len(chug_files) == 1

        validate_chugin(project_dir, "Lowpass", expected_params=1, expect_audio=True)


# ---------------------------------------------------------------------------
# AudioUnit (cmake, macOS only)
# ---------------------------------------------------------------------------


class TestBuildAuFromGraph:
    @_skip_no_au
    def test_build_au_gain(self, gain_graph: Graph, tmp_path: Path) -> None:
        """Build an AudioUnit from a graph."""
        project_dir = tmp_path / "gain_au"
        config = ProjectConfig(name="gain", platform="au")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir)

        components = list((project_dir / "build").glob("**/*.component"))
        assert len(components) >= 1

    @_skip_no_au
    def test_build_au_generator(self, generator_graph: Graph, tmp_path: Path) -> None:
        """Build an AudioUnit generator (0 inputs -> augn) from a graph."""
        project_dir = tmp_path / "sinegen_au"
        config = ProjectConfig(name="sine_gen", platform="au")
        gen = ProjectGenerator.from_graph(generator_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir)

        components = list((project_dir / "build").glob("**/*.component"))
        assert len(components) >= 1


# ---------------------------------------------------------------------------
# CLAP (cmake + FetchContent)
# ---------------------------------------------------------------------------


class TestBuildClapFromGraph:
    @_skip_no_cmake
    def test_build_clap_gain(
        self,
        gain_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ) -> None:
        """Build a CLAP plugin from a graph."""
        project_dir = tmp_path / "gain_clap"
        config = ProjectConfig(name="gain", platform="clap")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache)

        clap_files = list((project_dir / "build").glob("**/*.clap"))
        assert len(clap_files) >= 1
        assert clap_files[0].name == "gain.clap"

        validate_clap(clap_validator, clap_files[0])

    @_skip_no_cmake
    def test_build_clap_generator(
        self,
        generator_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ) -> None:
        """Build a CLAP instrument (0 inputs) from a graph."""
        project_dir = tmp_path / "sinegen_clap"
        config = ProjectConfig(name="sine_gen", platform="clap")
        gen = ProjectGenerator.from_graph(generator_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache)

        clap_files = list((project_dir / "build").glob("**/*.clap"))
        assert len(clap_files) >= 1

        validate_clap(clap_validator, clap_files[0])

    @_skip_no_cmake
    def test_build_clap_stereo(
        self,
        stereo_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ) -> None:
        """Build a stereo CLAP plugin from a graph."""
        project_dir = tmp_path / "stereo_clap"
        config = ProjectConfig(name="stereo_gain", platform="clap")
        gen = ProjectGenerator.from_graph(stereo_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache)

        clap_files = list((project_dir / "build").glob("**/*.clap"))
        assert len(clap_files) >= 1

        validate_clap(clap_validator, clap_files[0])


# ---------------------------------------------------------------------------
# VST3 (cmake + FetchContent)
# ---------------------------------------------------------------------------


class TestBuildVst3FromGraph:
    @_skip_no_cmake
    def test_build_vst3_gain(
        self,
        gain_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        vst3_validator: Optional[Path],
    ) -> None:
        """Build a VST3 plugin from a graph."""
        project_dir = tmp_path / "gain_vst3"
        config = ProjectConfig(name="gain", platform="vst3")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache, ["-DCMAKE_BUILD_TYPE=Release"])

        vst3_dirs = list((project_dir / "build").glob("**/*.vst3"))
        assert len(vst3_dirs) >= 1

        validate_vst3(vst3_validator, vst3_dirs[0])

    @_skip_no_cmake
    def test_build_vst3_generator(
        self,
        generator_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        vst3_validator: Optional[Path],
    ) -> None:
        """Build a VST3 instrument (0 inputs) from a graph."""
        project_dir = tmp_path / "sinegen_vst3"
        config = ProjectConfig(name="sine_gen", platform="vst3")
        gen = ProjectGenerator.from_graph(generator_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache, ["-DCMAKE_BUILD_TYPE=Release"])

        vst3_dirs = list((project_dir / "build").glob("**/*.vst3"))
        assert len(vst3_dirs) >= 1

        validate_vst3(vst3_validator, vst3_dirs[0])


# ---------------------------------------------------------------------------
# LV2 (cmake + FetchContent)
# ---------------------------------------------------------------------------


class TestBuildLv2FromGraph:
    @_skip_no_cmake
    def test_build_lv2_gain(
        self,
        gain_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
    ) -> None:
        """Build an LV2 plugin from a graph."""
        project_dir = tmp_path / "gain_lv2"
        config = ProjectConfig(name="gain", platform="lv2")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache)

        lv2_dirs = list((project_dir / "build").glob("**/*.lv2"))
        assert len(lv2_dirs) >= 1

        validate_lv2(lv2_validator, lv2_dirs[0], "gain", 1, 1, 1)

    @_skip_no_cmake
    def test_build_lv2_filter(
        self,
        filter_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
    ) -> None:
        """Build an LV2 plugin with stateful OnePole node."""
        project_dir = tmp_path / "lowpass_lv2"
        config = ProjectConfig(name="lowpass", platform="lv2")
        gen = ProjectGenerator.from_graph(filter_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache)

        lv2_dirs = list((project_dir / "build").glob("**/*.lv2"))
        assert len(lv2_dirs) >= 1

        validate_lv2(lv2_validator, lv2_dirs[0], "lowpass", 1, 1, 1)


# ---------------------------------------------------------------------------
# SuperCollider (cmake + FetchContent)
# ---------------------------------------------------------------------------


class TestBuildScFromGraph:
    @_skip_no_cmake
    def test_build_sc_gain(
        self, gain_graph: Graph, tmp_path: Path, fetchcontent_cache: Path
    ) -> None:
        """Build a SuperCollider UGen from a graph."""
        project_dir = tmp_path / "gain_sc"
        config = ProjectConfig(name="gain", platform="sc")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache)

        ext = ".scx" if _is_macos else ".so"
        sc_files = list((project_dir / "build").glob(f"**/*{ext}"))
        assert len(sc_files) >= 1


# ---------------------------------------------------------------------------
# Max/MSP (cmake, no FetchContent -- SDK auto-cloned via git)
# ---------------------------------------------------------------------------


class TestBuildMaxFromGraph:
    @pytest.mark.skipif(
        not (_is_macos and _has_cmake and _has_cxx and _has_git),
        reason="macOS with cmake, C++ compiler, and git required",
    )
    def test_build_max_gain(self, gain_graph: Graph, tmp_path: Path) -> None:
        """Build a Max external from a graph."""
        from gen_dsp.platforms.max import MaxPlatform

        project_dir = tmp_path / "gain_max"
        config = ProjectConfig(name="gain", platform="max")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

        platform = MaxPlatform()
        result = platform.build(project_dir)
        assert result.success, f"Max build failed: {result.stderr}"

        output = platform.find_output(project_dir)
        assert output is not None


# ---------------------------------------------------------------------------
# VCV Rack (make-based, Rack SDK)
# ---------------------------------------------------------------------------


class TestBuildVcvRackFromGraph:
    @_skip_no_make
    def test_build_vcvrack_gain(
        self, gain_graph: Graph, tmp_path: Path, fetchcontent_cache: Path
    ) -> None:
        """Build a VCV Rack module from a graph."""
        from gen_dsp.platforms.vcvrack import VcvRackPlatform, ensure_rack_sdk

        project_dir = tmp_path / "gain_vcvrack"
        config = ProjectConfig(name="gain", platform="vcvrack")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

        rack_sdk_dir = fetchcontent_cache / "rack-sdk-src" / "Rack-SDK"
        rack_dir = ensure_rack_sdk(rack_sdk_dir)

        platform = VcvRackPlatform()
        result = platform.run_command(["make", f"RACK_DIR={rack_dir}"], project_dir)
        assert result.returncode == 0, (
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output = platform.find_output(project_dir)
        assert output is not None


# ---------------------------------------------------------------------------
# .gdsp and .json CLI build tests
# ---------------------------------------------------------------------------


_EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples" / "dsl"
_GDSP_EXAMPLES = sorted(_EXAMPLES_DIR.glob("*.gdsp")) if _EXAMPLES_DIR.is_dir() else []


class TestBuildGdspExamples:
    """Build every examples/dsl/*.gdsp file end-to-end.

    PD (make-based) for fast compilation, CLAP (cmake) for validator coverage.
    This is the primary guard against codegen regressions in the DSL -> C++ ->
    binary pipeline -- the hand-constructed Graph fixtures below only cover
    simple topologies and miss features like sr=, ADSR, subgraphs, delays, etc.
    """

    @_skip_no_make
    @pytest.mark.parametrize(
        "gdsp_file",
        _GDSP_EXAMPLES,
        ids=[f.stem for f in _GDSP_EXAMPLES],
    )
    def test_build_gdsp_pd(self, gdsp_file: Path, tmp_path: Path) -> None:
        """Build a PD external from each example .gdsp file."""
        from gen_dsp.cli import main

        name = gdsp_file.stem
        project_dir = tmp_path / f"{name}_pd"
        result = main(
            [str(gdsp_file), "-p", "pd", "-o", str(project_dir), "--no-build"]
        )
        assert result == 0, f"CLI failed for {gdsp_file.name}"

        _make_build(project_dir, target="all")

        from gen_dsp.platforms.puredata import PureDataPlatform

        output = PureDataPlatform().find_output(project_dir)
        assert output is not None

        validate_pd_external(project_dir, name)

    @_skip_no_cmake
    @pytest.mark.parametrize(
        "gdsp_file",
        _GDSP_EXAMPLES,
        ids=[f.stem for f in _GDSP_EXAMPLES],
    )
    def test_build_gdsp_clap(
        self,
        gdsp_file: Path,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ) -> None:
        """Build a CLAP plugin from each example .gdsp file."""
        from gen_dsp.cli import main

        name = gdsp_file.stem
        project_dir = tmp_path / f"{name}_clap"
        result = main(
            [str(gdsp_file), "-p", "clap", "-o", str(project_dir), "--no-build"]
        )
        assert result == 0, f"CLI failed for {gdsp_file.name}"

        _cmake_build(project_dir, fetchcontent_cache)

        clap_files = list((project_dir / "build").glob("**/*.clap"))
        assert len(clap_files) >= 1
        assert clap_files[0].name == f"{name}.clap"

        validate_clap(clap_validator, clap_files[0])


# ---------------------------------------------------------------------------
# Daisy (make-based, ARM cross-compilation)
# ---------------------------------------------------------------------------


class TestBuildDaisyFromGraph:
    @_skip_no_daisy
    def test_build_daisy_gain(
        self, gain_graph: Graph, tmp_path: Path, fetchcontent_cache: Path
    ) -> None:
        """Build Daisy firmware from a graph."""
        from gen_dsp.platforms.daisy import DaisyPlatform, ensure_libdaisy

        project_dir = tmp_path / "gain_daisy"
        config = ProjectConfig(name="gain", platform="daisy")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

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

    @_skip_no_daisy
    def test_build_daisy_generator(
        self, generator_graph: Graph, tmp_path: Path, fetchcontent_cache: Path
    ) -> None:
        """Build Daisy firmware from a generator graph (0 inputs)."""
        from gen_dsp.platforms.daisy import DaisyPlatform, ensure_libdaisy

        project_dir = tmp_path / "sinegen_daisy"
        config = ProjectConfig(name="sine_gen", platform="daisy")
        gen = ProjectGenerator.from_graph(generator_graph, config)
        gen.generate(project_dir)

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


# ---------------------------------------------------------------------------
# Circle (make-based, bare-metal Raspberry Pi cross-compilation)
# ---------------------------------------------------------------------------


class TestBuildCircleFromGraph:
    @_skip_no_circle
    def test_build_circle_gain(
        self, gain_graph: Graph, tmp_path: Path, fetchcontent_cache: Path
    ) -> None:
        """Build Circle kernel image from a graph."""
        from gen_dsp.platforms.circle import CirclePlatform, ensure_circle

        project_dir = tmp_path / "gain_circle"
        config = ProjectConfig(name="gain", platform="circle")
        gen = ProjectGenerator.from_graph(gain_graph, config)
        gen.generate(project_dir)

        circle_dir = fetchcontent_cache / "circle-src" / "circle"
        circle_dir = ensure_circle(circle_dir)

        platform = CirclePlatform()
        result = platform.run_command(["make", f"CIRCLEHOME={circle_dir}"], project_dir)
        assert result.returncode == 0, (
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output = platform.find_output(project_dir)
        assert output is not None
        assert output.suffix == ".img"

    @_skip_no_circle
    def test_build_circle_generator(
        self, generator_graph: Graph, tmp_path: Path, fetchcontent_cache: Path
    ) -> None:
        """Build Circle kernel image from a generator graph (0 inputs)."""
        from gen_dsp.platforms.circle import CirclePlatform, ensure_circle

        project_dir = tmp_path / "sinegen_circle"
        config = ProjectConfig(name="sine_gen", platform="circle")
        gen = ProjectGenerator.from_graph(generator_graph, config)
        gen.generate(project_dir)

        circle_dir = fetchcontent_cache / "circle-src" / "circle"
        circle_dir = ensure_circle(circle_dir)

        platform = CirclePlatform()
        result = platform.run_command(["make", f"CIRCLEHOME={circle_dir}"], project_dir)
        assert result.returncode == 0, (
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output = platform.find_output(project_dir)
        assert output is not None
        assert output.suffix == ".img"


# ---------------------------------------------------------------------------
# Buffer-bearing graph builds
# ---------------------------------------------------------------------------


class TestBuildBufferGraph:
    """Test that graphs with Buffer/Cycle nodes compile across platforms."""

    @_skip_no_make
    def test_build_buffer_pd(self, buffer_graph: Graph, tmp_path: Path) -> None:
        """Build PD external from a wavetable graph with buffers."""
        project_dir = tmp_path / "wavetable_pd"
        config = ProjectConfig(name="wavetable", platform="pd")
        gen = ProjectGenerator.from_graph(buffer_graph, config)
        gen.generate(project_dir)

        _make_build(project_dir, target="all")

        from gen_dsp.platforms.puredata import PureDataPlatform

        output = PureDataPlatform().find_output(project_dir)
        assert output is not None

        validate_pd_external(project_dir, "wavetable")

    @_skip_no_make
    def test_build_buffer_chuck(self, buffer_graph: Graph, tmp_path: Path) -> None:
        """Build ChucK chugin from a wavetable graph with buffers."""
        project_dir = tmp_path / "wavetable_chuck"
        config = ProjectConfig(name="wavetable", platform="chuck")
        gen = ProjectGenerator.from_graph(buffer_graph, config)
        gen.generate(project_dir)

        target = "mac" if _is_macos else "linux"
        _make_build(project_dir, target=target)

        chug_files = list(project_dir.glob("*.chug"))
        assert len(chug_files) == 1

        validate_chugin(project_dir, "Wavetable", expected_params=2)

    @_skip_no_cmake
    def test_build_buffer_clap(
        self,
        buffer_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ) -> None:
        """Build CLAP plugin from a wavetable graph with buffers."""
        project_dir = tmp_path / "wavetable_clap"
        config = ProjectConfig(name="wavetable", platform="clap")
        gen = ProjectGenerator.from_graph(buffer_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache)

        clap_files = list((project_dir / "build").glob("**/*.clap"))
        assert len(clap_files) >= 1

        validate_clap(clap_validator, clap_files[0])

    @_skip_no_au
    def test_build_buffer_au(self, buffer_graph: Graph, tmp_path: Path) -> None:
        """Build AudioUnit from a wavetable graph with buffers."""
        project_dir = tmp_path / "wavetable_au"
        config = ProjectConfig(name="wavetable", platform="au")
        gen = ProjectGenerator.from_graph(buffer_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir)

        components = list((project_dir / "build").glob("**/*.component"))
        assert len(components) >= 1


# ---------------------------------------------------------------------------
# Multi-channel (>2) graph builds
# ---------------------------------------------------------------------------


class TestBuildMultiChannelGraph:
    """Test that 3in/2out graphs compile across platforms."""

    @_skip_no_make
    def test_build_multichannel_pd(
        self, multichannel_graph: Graph, tmp_path: Path
    ) -> None:
        """Build PD external from a 3in/2out graph."""
        project_dir = tmp_path / "mixer3to2_pd"
        config = ProjectConfig(name="mixer3to2", platform="pd")
        gen = ProjectGenerator.from_graph(multichannel_graph, config)
        gen.generate(project_dir)

        _make_build(project_dir, target="all")

        from gen_dsp.platforms.puredata import PureDataPlatform

        output = PureDataPlatform().find_output(project_dir)
        assert output is not None

        validate_pd_external(project_dir, "mixer3to2")

    @_skip_no_cmake
    def test_build_multichannel_clap(
        self,
        multichannel_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ) -> None:
        """Build CLAP plugin from a 3in/2out graph."""
        project_dir = tmp_path / "mixer3to2_clap"
        config = ProjectConfig(name="mixer3to2", platform="clap")
        gen = ProjectGenerator.from_graph(multichannel_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache)

        clap_files = list((project_dir / "build").glob("**/*.clap"))
        assert len(clap_files) >= 1

        validate_clap(clap_validator, clap_files[0])

    @_skip_no_cmake
    def test_build_multichannel_vst3(
        self,
        multichannel_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        vst3_validator: Optional[Path],
    ) -> None:
        """Build VST3 plugin from a 3in/2out graph."""
        project_dir = tmp_path / "mixer3to2_vst3"
        config = ProjectConfig(name="mixer3to2", platform="vst3")
        gen = ProjectGenerator.from_graph(multichannel_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache, ["-DCMAKE_BUILD_TYPE=Release"])

        vst3_dirs = list((project_dir / "build").glob("**/*.vst3"))
        assert len(vst3_dirs) >= 1

        validate_vst3(vst3_validator, vst3_dirs[0])

    @_skip_no_cmake
    def test_build_multichannel_lv2(
        self,
        multichannel_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        lv2_validator: Optional[Path],
    ) -> None:
        """Build LV2 plugin from a 3in/2out graph."""
        project_dir = tmp_path / "mixer3to2_lv2"
        config = ProjectConfig(name="mixer3to2", platform="lv2")
        gen = ProjectGenerator.from_graph(multichannel_graph, config)
        gen.generate(project_dir)

        _cmake_build(project_dir, fetchcontent_cache)

        lv2_dirs = list((project_dir / "build").glob("**/*.lv2"))
        assert len(lv2_dirs) >= 1

        validate_lv2(lv2_validator, lv2_dirs[0], "mixer3to2", 3, 2, 1)

    @_skip_no_daisy
    def test_build_multichannel_daisy(
        self, multichannel_graph: Graph, tmp_path: Path, fetchcontent_cache: Path
    ) -> None:
        """Build Daisy firmware from a 3in/2out graph (scratch buffer padding)."""
        from gen_dsp.platforms.daisy import DaisyPlatform, ensure_libdaisy

        project_dir = tmp_path / "mixer3to2_daisy"
        config = ProjectConfig(name="mixer3to2", platform="daisy")
        gen = ProjectGenerator.from_graph(multichannel_graph, config)
        gen.generate(project_dir)

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


# ---------------------------------------------------------------------------
# MIDI / Polyphony graph builds
# ---------------------------------------------------------------------------


class TestBuildMidiGraph:
    """Test that MIDI-mapped generator graphs compile with MIDI defines."""

    @_skip_no_cmake
    def test_build_midi_clap(
        self,
        midi_synth_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ) -> None:
        """Build CLAP instrument with MIDI mapping from a graph."""
        project_dir = tmp_path / "synth_clap"
        config = ProjectConfig(
            name="synth",
            platform="clap",
            midi_gate="gate",
            midi_freq="freq",
            midi_vel="vel",
        )
        gen = ProjectGenerator.from_graph(midi_synth_graph, config)
        gen.generate(project_dir)

        cmakelists = (project_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED=1" in cmakelists
        assert "MIDI_GATE_IDX=" in cmakelists
        assert "MIDI_FREQ_IDX=" in cmakelists

        _cmake_build(project_dir, fetchcontent_cache)

        clap_files = list((project_dir / "build").glob("**/*.clap"))
        assert len(clap_files) >= 1

        validate_clap(clap_validator, clap_files[0])

    @_skip_no_au
    def test_build_midi_au(self, midi_synth_graph: Graph, tmp_path: Path) -> None:
        """Build AudioUnit instrument (aumu) with MIDI mapping from a graph."""
        project_dir = tmp_path / "synth_au"
        config = ProjectConfig(
            name="synth",
            platform="au",
            midi_gate="gate",
            midi_freq="freq",
            midi_vel="vel",
        )
        gen = ProjectGenerator.from_graph(midi_synth_graph, config)
        gen.generate(project_dir)

        cmakelists = (project_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED=1" in cmakelists

        _cmake_build(project_dir)

        components = list((project_dir / "build").glob("**/*.component"))
        assert len(components) >= 1

    @_skip_no_cmake
    def test_build_midi_vst3(
        self,
        midi_synth_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        vst3_validator: Optional[Path],
    ) -> None:
        """Build VST3 instrument with MIDI mapping from a graph."""
        project_dir = tmp_path / "synth_vst3"
        config = ProjectConfig(
            name="synth",
            platform="vst3",
            midi_gate="gate",
            midi_freq="freq",
            midi_vel="vel",
        )
        gen = ProjectGenerator.from_graph(midi_synth_graph, config)
        gen.generate(project_dir)

        cmakelists = (project_dir / "CMakeLists.txt").read_text()
        assert "MIDI_ENABLED=1" in cmakelists

        _cmake_build(project_dir, fetchcontent_cache, ["-DCMAKE_BUILD_TYPE=Release"])

        vst3_dirs = list((project_dir / "build").glob("**/*.vst3"))
        assert len(vst3_dirs) >= 1

        validate_vst3(vst3_validator, vst3_dirs[0])


class TestBuildPolyphonyGraph:
    """Test that polyphonic graphs compile with NUM_VOICES > 1."""

    @_skip_no_cmake
    def test_build_poly_clap(
        self,
        midi_synth_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        clap_validator: Optional[Path],
    ) -> None:
        """Build polyphonic CLAP instrument (4 voices) from a graph."""
        project_dir = tmp_path / "polysynth_clap"
        config = ProjectConfig(
            name="polysynth",
            platform="clap",
            midi_gate="gate",
            midi_freq="freq",
            midi_vel="vel",
            num_voices=4,
        )
        gen = ProjectGenerator.from_graph(midi_synth_graph, config)
        gen.generate(project_dir)

        cmakelists = (project_dir / "CMakeLists.txt").read_text()
        assert "NUM_VOICES=4" in cmakelists
        assert "MIDI_ENABLED=1" in cmakelists

        _cmake_build(project_dir, fetchcontent_cache)

        clap_files = list((project_dir / "build").glob("**/*.clap"))
        assert len(clap_files) >= 1

        validate_clap(clap_validator, clap_files[0])

    @_skip_no_cmake
    def test_build_poly_vst3(
        self,
        midi_synth_graph: Graph,
        tmp_path: Path,
        fetchcontent_cache: Path,
        vst3_validator: Optional[Path],
    ) -> None:
        """Build polyphonic VST3 instrument (4 voices) from a graph."""
        project_dir = tmp_path / "polysynth_vst3"
        config = ProjectConfig(
            name="polysynth",
            platform="vst3",
            midi_gate="gate",
            midi_freq="freq",
            midi_vel="vel",
            num_voices=4,
        )
        gen = ProjectGenerator.from_graph(midi_synth_graph, config)
        gen.generate(project_dir)

        cmakelists = (project_dir / "CMakeLists.txt").read_text()
        assert "NUM_VOICES=4" in cmakelists

        _cmake_build(project_dir, fetchcontent_cache, ["-DCMAKE_BUILD_TYPE=Release"])

        vst3_dirs = list((project_dir / "build").glob("**/*.vst3"))
        assert len(vst3_dirs) >= 1

        validate_vst3(vst3_validator, vst3_dirs[0])
