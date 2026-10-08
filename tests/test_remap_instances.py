"""--inputs-as-params keeps each instance's remapped values and buffers to itself.

Builds each backend's genlib bridge (``_ext_<platform>.cpp``, which includes no platform
SDK headers) with ``tests/data/remap_instances_test.cpp`` under sanitizers.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.manifest import Manifest, _build_remap_defs
from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectConfig, ProjectGenerator

_DRIVER = Path(__file__).parent / "data" / "remap_instances_test.cpp"

# every backend whose bridge includes gen_remap_inputs.h
_PLATFORMS = [
    "au",
    "auv3",
    "chuck",
    "circle",
    "clap",
    "csound",
    "daisy",
    "lv2",
    "sc",
    "ssp",
    "standalone",
    "vcvrack",
    "vst3",
    "webaudio",
]

_CC = shutil.which("clang")
_CXX = shutil.which("clang++")


@pytest.mark.skipif(
    _CC is None or _CXX is None or os.uname().sysname == "Darwin",
    reason="clang with sanitizers on Linux required",
)
@pytest.mark.parametrize("sanitizer", ["address,undefined", "thread"])
@pytest.mark.parametrize("platform", _PLATFORMS)
def test_remap_per_instance(gigaverb_export, tmp_path, platform, sanitizer):
    assert _CC is not None and _CXX is not None
    info = GenExportParser(gigaverb_export).parse()
    config = ProjectConfig(
        name="gigaverb",
        platform=platform,
        inputs_as_params=[],  # all inputs
        shared_cache=False,
    )
    project = ProjectGenerator(info, config).generate(tmp_path / "p")
    manifest = Manifest.from_json((project / "manifest.json").read_text())
    defines = [
        "-DGENLIB_USE_FLOAT32",
        f"-D{platform.upper()}_EXT_NAME=gigaverb",
        f"-DGEN_EXPORTED_NAME={manifest.gen_name}",
        f'-DGEN_EXPORTED_HEADER="{manifest.gen_name}.h"',
        f'-DGEN_EXPORTED_CPP="{manifest.gen_name}.cpp"',
        f'-DEXT_HEADER="_ext_{platform}.h"',
        *(f"-D{d}" for d in _build_remap_defs(manifest)),
    ]
    gen = project / "gen" / "gen_dsp"
    # -iquote: Circle projects ship a bare-metal <cmath> shim at their root
    includes = [f"-iquote{project}", f"-I{project / 'gen'}", f"-I{gen}"]
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
        subprocess.run([_CC, "-c", *flags, str(gen / c), "-o", str(obj)], check=True)
        objs.append(str(obj))
    runtime = subprocess.run(
        [_CXX, "--print-runtime-dir"], capture_output=True, text=True, check=True
    ).stdout.strip()
    exe = tmp_path / "remap_instances_test"
    r = subprocess.run(
        [
            _CXX,
            "-std=c++17",
            "-pthread",
            *flags,
            str(_DRIVER),
            str(project / f"_ext_{platform}.cpp"),
            str(gen / "genlib.cpp"),
            *objs,
            "-ldl",
            f"-Wl,-rpath,{runtime}",
            "-o",
            str(exe),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr[-4000:]
    # genlib never frees the data objects reset() obtains (gigaverb's delay lines)
    supp = tmp_path / "lsan.supp"
    supp.write_text("leak:genlib_obtain_data_from_reference\n")
    env = dict(
        os.environ, TSAN_OPTIONS="exitcode=66", LSAN_OPTIONS=f"suppressions={supp}"
    )
    r = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stderr[-4000:]
    assert r.stdout.strip() == "ok"
