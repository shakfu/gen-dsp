"""Tests for the cignal frontend (``gen_dsp.cignal``).

``tests/fixtures/cignal_gigaverb`` is the output of
``cignal build gigaverb.py --manifest`` for cignal's Gigaverb fixture.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.cignal import (
    generate_adapter_cpp,
    is_cignal_manifest,
    load_cignal_manifest,
)
from gen_dsp.cli import main
from gen_dsp.core.project import ProjectConfig, ProjectGenerator
from gen_dsp.errors import ProjectError, ValidationError
from tests.helpers import fetchcontent_cmake_args, validate_clap, validate_vst3

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

    @pytest.mark.parametrize("platform", ["clap", "vst3"])
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

    def test_unsupported_platform(self, manifest_path: Path, tmp_path: Path):
        kernel = load_cignal_manifest(manifest_path)
        config = ProjectConfig(name="gigaverb", platform="lv2")
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
        assert main([str(manifest_path), "-p", "lv2", "--dry-run"]) == 1
        assert "not supported on lv2" in capsys.readouterr().err


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
