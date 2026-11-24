"""Tests for the cignal frontend (``gen_dsp.cignal``).

``tests/fixtures/cignal_gigaverb`` is the output of
``cignal build gigaverb.py --manifest`` for cignal's Gigaverb fixture.
"""

import json
import os
import platform as sys_platform
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from gen_dsp.cignal import (
    generate_adapter_cpp,
    is_cignal_manifest,
    load_cignal_manifest,
)
from gen_dsp.cli import main
from gen_dsp.core.project import ProjectConfig, ProjectGenerator
from gen_dsp.errors import ProjectError, ValidationError
from tests.helpers import (
    fetchcontent_cmake_args,
    validate_clap,
    validate_lv2,
    validate_vst3,
)
from tests.test_audiounit import _validate_au
from tests.test_sc import _validate_sc

_can_build = shutil.which("cmake") is not None and (
    shutil.which("clang++") is not None or shutil.which("g++") is not None
)


@pytest.fixture
def cignal_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "cignal_gigaverb"


@pytest.fixture
def manifest_path(cignal_dir: Path) -> Path:
    return cignal_dir / "gigaverb.cignal.json"


def _edited(tmp_path: Path, cignal_dir: Path, **changes: object) -> Path:
    """A copy of the fixture with top-level manifest fields replaced."""
    for f in cignal_dir.iterdir():
        shutil.copy2(f, tmp_path / f.name)
    path = tmp_path / "gigaverb.cignal.json"
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data))
    return path


class TestManifest:
    def test_detects_manifest_by_suffix(self, manifest_path: Path):
        assert is_cignal_manifest(manifest_path)
        assert not is_cignal_manifest(manifest_path.with_name("graph.json"))

    def test_loads_fixture(self, manifest_path: Path):
        k = load_cignal_manifest(manifest_path)
        assert (k.name, k.c_name, k.stem) == ("Gigaverb", "Gigaverb", "gigaverb")
        assert (k.n_inputs, k.n_outputs) == (1, 2)
        assert [p.name for p in k.params][:2] == ["roomsize", "revtime"]
        assert (k.params[0].lo, k.params[0].hi, k.params[0].default) == (
            1.0,
            50.0,
            10.0,
        )
        assert k.events == ()

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"format": 2}, "format"),
            ({"sample_type": "double"}, "float build"),
            ({"c_name": "Gigaverb; int x"}, "c_name"),
            ({"header": "../gigaverb.h"}, "header"),
            ({"source": "missing.c"}, "not found"),
            ({"n_inputs": True}, "n_inputs"),
            ({"n_outputs": 0}, "n_outputs"),
            ({"params": [{"name": "x", "lo": 0, "hi": 1, "default": 2}]}, "outside"),
            (
                {"params": [{"name": "x", "lo": 0, "hi": float("inf"), "default": 0}]},
                "finite",
            ),
        ],
    )
    def test_rejects_malformed(
        self, tmp_path: Path, cignal_dir: Path, changes: dict, message: str
    ):
        path = _edited(tmp_path, cignal_dir, **changes)
        with pytest.raises(ValidationError, match=message):
            load_cignal_manifest(path)

    def test_rejects_invalid_json(self, tmp_path: Path):
        path = tmp_path / "k.cignal.json"
        path.write_text("{")
        with pytest.raises(ValidationError, match="cannot read"):
            load_cignal_manifest(path)


class TestAdapter:
    def test_adapter_calls_kernel_abi(self, manifest_path: Path):
        cpp = generate_adapter_cpp(load_cignal_manifest(manifest_path), "clap")
        for symbol in (
            '#include "gigaverb.h"',
            "Gigaverb_init(&s->kernel, sr);",
            "Gigaverb_process(",
            "Gigaverb_set_param(",
            "Gigaverb_reset(",
            "Gigaverb_info.params",
            "std::calloc(1, sizeof(State))",
        ):
            assert symbol in cpp

    @pytest.mark.parametrize("platform", ["au", "clap", "lv2", "sc", "vst3"])
    def test_generate_project(self, manifest_path: Path, tmp_path: Path, platform: str):
        kernel = load_cignal_manifest(manifest_path)
        config = ProjectConfig(name="gigaverb", platform=platform)
        out = ProjectGenerator.from_cignal(kernel, config).generate(tmp_path / "p")
        for f in (
            "gigaverb.h",
            "gigaverb.c",
            f"_ext_{platform}.cpp",
            f"_ext_{platform}.h",
            f"gen_ext_{platform}.cpp",
        ):
            assert (out / f).is_file(), f
        cmake = (out / "CMakeLists.txt").read_text()
        assert "target_sources(${PROJECT_NAME} PRIVATE gigaverb.c)" in cmake
        prefix = platform.upper()
        assert f"{prefix}_NUM_INPUTS=1" in cmake and f"{prefix}_NUM_OUTPUTS=2" in cmake
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["source"] == "cignal"
        assert [p["name"] for p in manifest["params"]][-1] == "tail"

    @pytest.mark.parametrize(
        ("platform", "extra"),
        [("au", "Info.plist"), ("lv2", "gigaverb.ttl"), ("sc", "Gigaverb.sc")],
    )
    def test_platform_files(
        self, manifest_path: Path, tmp_path: Path, platform: str, extra: str
    ):
        """The per-platform files come from the same hook the graph path uses."""
        kernel = load_cignal_manifest(manifest_path)
        config = ProjectConfig(name="gigaverb", platform=platform)
        out = ProjectGenerator.from_cignal(kernel, config).generate(tmp_path / "p")
        assert (out / extra).is_file()

    def test_unsupported_platform(self, manifest_path: Path, tmp_path: Path):
        kernel = load_cignal_manifest(manifest_path)
        config = ProjectConfig(name="gigaverb", platform="max")
        with pytest.raises(ProjectError, match="not supported"):
            ProjectGenerator.from_cignal(kernel, config).generate(tmp_path / "p")


class TestCli:
    def test_dry_run(self, manifest_path: Path, capsys: pytest.CaptureFixture[str]):
        assert main([str(manifest_path), "-p", "clap,vst3", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "Source: cignal (gigaverb.cignal.json)" in out
        assert "Platform: vst3" in out
        assert "Parameters: 8" in out

    def test_unsupported_platform(
        self, manifest_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        assert main([str(manifest_path), "-p", "max", "--dry-run"]) == 1
        assert "not supported on max" in capsys.readouterr().err


def _build(manifest_path: Path, project_dir: Path, platform: str, cache: Path) -> Path:
    """Generate and build a cignal project; returns the build directory."""
    kernel = load_cignal_manifest(manifest_path)
    config = ProjectConfig(name="gigaverb", platform=platform)
    ProjectGenerator.from_cignal(kernel, config).generate(project_dir)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    for cmd in (
        ["cmake", "-B", "build", *fetchcontent_cmake_args(cache)],
        ["cmake", "--build", "build"],
    ):
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
            check=False,
        )
        assert result.returncode == 0, f"{cmd}:\n{result.stdout}\n{result.stderr}"
    # The kernel is compiled as C, not included into the C++ adapter.
    assert "Building C object" in result.stdout
    return project_dir / "build"


@pytest.mark.skipif(not _can_build, reason="cmake and C++ compiler required")
def test_build_clap(
    manifest_path: Path,
    tmp_path: Path,
    fetchcontent_cache: Path,
    clap_validator: Path | None,
):
    build_dir = _build(manifest_path, tmp_path / "p", "clap", fetchcontent_cache)
    bundles = list(build_dir.glob("**/gigaverb.clap"))
    assert bundles
    validate_clap(clap_validator, bundles[0])


@pytest.mark.skipif(not _can_build, reason="cmake and C++ compiler required")
def test_build_vst3(
    manifest_path: Path,
    tmp_path: Path,
    fetchcontent_cache: Path,
    vst3_validator: Path | None,
    validate_minihost,
):
    """Builds, passes the SDK validator, and processes audio through minihost."""
    build_dir = _build(manifest_path, tmp_path / "p", "vst3", fetchcontent_cache)
    bundles = list(build_dir.glob("**/gigaverb.vst3"))
    assert bundles
    validate_vst3(vst3_validator, bundles[0])
    validate_minihost(bundles[0], 1, 2, num_params=8)


@pytest.mark.skipif(
    not _can_build or sys_platform.system() != "Darwin",
    reason="AudioUnit needs macOS, cmake and a C++ compiler",
)
def test_build_au(manifest_path: Path, tmp_path: Path, fetchcontent_cache: Path):
    build_dir = _build(manifest_path, tmp_path / "p", "au", fetchcontent_cache)
    bundles = list(build_dir.glob("**/gigaverb.component"))
    assert bundles
    _validate_au(bundles[0], "gigaverb")


@pytest.mark.skipif(not _can_build, reason="cmake and C++ compiler required")
def test_build_sc(manifest_path: Path, tmp_path: Path, fetchcontent_cache: Path):
    """Builds; sclang compiles the class and scsynth renders audio, if installed."""
    project_dir = tmp_path / "p"
    build_dir = _build(manifest_path, project_dir, "sc", fetchcontent_cache)
    _validate_sc(project_dir, build_dir, "Gigaverb", "gigaverb", 1, 2)


# Runs the kernel directly, in the blocks the plugin test uses, so the plugin's output can be
# compared sample for sample. argv: in.f32 out.f32 change_frame roomsize.
_REFERENCE_MAIN = r"""
#include <stdio.h>
#include <stdlib.h>
#include "gigaverb.h"

enum { B = 512 };
static Gigaverb k;  /* static: the struct holds its delay lines inline */

int main(int argc, char **argv) {
    if (argc != 5) return 2;
    FILE *fi = fopen(argv[1], "rb");
    if (!fi) return 1;
    fseek(fi, 0, SEEK_END);
    long n = ftell(fi) / 4;
    rewind(fi);
    float *x = malloc((size_t)n * 4), *y = malloc((size_t)n * 8);
    if (fread(x, 4, (size_t)n, fi) != (size_t)n) return 1;
    fclose(fi);
    long change = atol(argv[3]);
    Gigaverb_init(&k, 48000.0f);
    for (long pos = 0; pos < n; pos += B) {
        int m = (int)(n - pos < B ? n - pos : B);
        if (pos == change) Gigaverb_set_param(&k, 0, (float)atof(argv[4]));
        const float *in[1] = {x + pos};
        float *out[2] = {y + pos, y + n + pos};
        Gigaverb_process(&k, in, out, m);
    }
    FILE *fo = fopen(argv[2], "wb");
    fwrite(y, 4, (size_t)n * 2, fo);
    fclose(fo);
    return 0;
}
"""


def _cmake_c_compiler(build_dir: Path) -> list[str]:
    """The C compiler and flags CMake used for the kernel, so the reference rounds the same."""
    cache = (build_dir / "CMakeCache.txt").read_text()
    compiler = re.search(r"^CMAKE_C_COMPILER:\w+=(.+)$", cache, re.MULTILINE)
    assert compiler, "no CMAKE_C_COMPILER in CMakeCache.txt"
    flags = next(build_dir.glob("CMakeFiles/*.dir/flags.make")).read_text()
    c_flags = re.search(r"^C_FLAGS = (.*)$", flags, re.MULTILINE)
    return [compiler.group(1), *shlex.split(c_flags.group(1) if c_flags else "")]


@pytest.mark.skipif(not _can_build, reason="cmake and C++ compiler required")
def test_lv2_matches_kernel(
    manifest_path: Path,
    cignal_dir: Path,
    tmp_path: Path,
    fetchcontent_cache: Path,
    lv2_validator: Path | None,
):
    """The adapter adds nothing: the plugin's output equals the kernel's, bit for bit.

    LV2 takes plain parameter values, so a mid-run change reaches the kernel unrounded; VST3
    converts from normalized in float and can move a value by one ulp.
    """
    minihost = pytest.importorskip("minihost")
    build_dir = _build(manifest_path, tmp_path / "p", "lv2", fetchcontent_cache)
    bundles = list(build_dir.glob("**/gigaverb.lv2"))
    assert bundles
    validate_lv2(lv2_validator, bundles[0], "gigaverb", 1, 2, 8)

    rng = np.random.default_rng(1234)
    x = np.zeros(48000, dtype=np.float32)
    x[:12000] = 0.5 * rng.uniform(-1, 1, 12000)
    change, block = 24576, 512

    ref_exe = tmp_path / "reference"
    main_c = tmp_path / "reference_main.c"
    main_c.write_text(_REFERENCE_MAIN)
    subprocess.run(
        [
            *_cmake_c_compiler(build_dir),
            f"-I{cignal_dir}",
            str(main_c),
            str(cignal_dir / "gigaverb.c"),
            "-lm",
            "-o",
            str(ref_exe),
        ],
        check=True,
    )
    x.tofile(tmp_path / "x.f32")
    subprocess.run(
        [
            str(ref_exe),
            str(tmp_path / "x.f32"),
            str(tmp_path / "y.f32"),
            str(change),
            "25.5",
        ],
        check=True,
    )
    expected = np.fromfile(tmp_path / "y.f32", dtype=np.float32).reshape(2, -1)

    plugin = minihost.Plugin(
        str(bundles[0]),
        sample_rate=48000.0,
        max_block_size=block,
        in_channels=1,
        out_channels=2,
    )
    actual = np.zeros_like(expected)
    for pos in range(0, len(x), block):
        if pos == change:
            plugin.set_param(0, 0.5)  # normalized: 1 + 0.5 * (50 - 1) = 25.5
        out = np.zeros((2, min(block, len(x) - pos)), dtype=np.float32)
        plugin.process(np.ascontiguousarray(x[None, pos : pos + out.shape[1]]), out)
        actual[:, pos : pos + out.shape[1]] = out
    assert not np.array_equal(expected[:, change:], 0.0)
    assert np.array_equal(actual, expected), float(np.max(np.abs(actual - expected)))
