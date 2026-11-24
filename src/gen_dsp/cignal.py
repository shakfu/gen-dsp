"""cignal frontend: wrap a kernel compiled by cignal in a gen-dsp platform project.

The input is the ``<stem>.cignal.json`` manifest that ``cignal build --manifest`` writes beside
``<stem>.h`` and ``<stem>.c``. gen-dsp reads the three files and does not import cignal.

The adapter implements the ``wrapper_*`` interface over cignal's C ABI. cignal kernels never
allocate, so ``wrapper_create`` allocates the struct. cignal has no parameter getter, so the
adapter keeps the last value set for ``wrapper_get_param``. cignal events (``@event``) have no
``wrapper_*`` counterpart and are not reachable from the host.
"""

from __future__ import annotations

import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gen_dsp.errors import ProjectError, ValidationError
from gen_dsp.version import __version__

if TYPE_CHECKING:
    from gen_dsp.core.manifest import Manifest
    from gen_dsp.core.project import ProjectConfig

MANIFEST_SUFFIX = ".cignal.json"
MANIFEST_FORMAT = 1
# Platforms built and run end to end from a cignal kernel. Each new one needs its build file to
# compile the kernel's C source; see `_add_c_source`.
# Build files whose plugin target is `${PROJECT_NAME}`, so the C source can be appended to it.
_CMAKE_TARGET_PLATFORMS = frozenset({"clap", "vst3"})
SUPPORTED_PLATFORMS = _CMAKE_TARGET_PLATFORMS

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FILE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


@dataclass(frozen=True)
class CignalParam:
    name: str
    lo: float
    hi: float
    default: float


@dataclass(frozen=True)
class CignalKernel:
    """A kernel described by a cignal manifest; ``directory`` holds the header and source."""

    name: str
    c_name: str
    header: str
    source: str
    n_inputs: int
    n_outputs: int
    params: tuple[CignalParam, ...]
    events: tuple[str, ...]
    directory: Path

    @property
    def stem(self) -> str:
        return Path(self.header).stem


def is_cignal_manifest(path: Path) -> bool:
    return path.name.endswith(MANIFEST_SUFFIX)


def _field(data: dict[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    value = data.get(key)
    # bool is an int subclass; a count or a bound given as true/false is a malformed manifest.
    if not isinstance(value, kind) or isinstance(value, bool):
        raise ValidationError(f"cignal manifest: {key!r} must be {kind}, got {value!r}")
    return value


def _number(data: dict[str, Any], key: str) -> float:
    value = float(_field(data, key, (int, float)))
    if not math.isfinite(value):
        raise ValidationError(f"cignal manifest: {key!r} must be finite, got {value!r}")
    return value


def _match(pattern: re.Pattern[str], value: str, key: str) -> str:
    # Names are spliced into C++ source and file paths, so they must not carry anything else.
    if not pattern.fullmatch(value):
        raise ValidationError(f"cignal manifest: invalid {key} {value!r}")
    return value


def load_cignal_manifest(path: Path) -> CignalKernel:
    """Parse and validate a ``<stem>.cignal.json``. Raises ``ValidationError`` if it is malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValidationError(f"cannot read cignal manifest {path}: {e}") from e
    if not isinstance(data, dict):
        raise ValidationError("cignal manifest: top level must be an object")
    if data.get("format") != MANIFEST_FORMAT:
        raise ValidationError(
            f"cignal manifest: format {data.get('format')!r} is not supported "
            f"(expected {MANIFEST_FORMAT})"
        )
    if data.get("sample_type") != "float":
        raise ValidationError(
            "cignal manifest: gen-dsp needs the float build "
            f"(sample_type 'float'), got {data.get('sample_type')!r}"
        )

    params = []
    for i, p in enumerate(_field(data, "params", list)):
        if not isinstance(p, dict):
            raise ValidationError(f"cignal manifest: params[{i}] must be an object")
        param = CignalParam(
            name=_match(_IDENT, _field(p, "name", str), f"params[{i}] name"),
            lo=_number(p, "lo"),
            hi=_number(p, "hi"),
            default=_number(p, "default"),
        )
        if not param.lo <= param.default <= param.hi:
            raise ValidationError(
                f"cignal manifest: param {param.name!r} default is outside [lo, hi]"
            )
        params.append(param)

    events = []
    for i, ev in enumerate(_field(data, "events", list)):
        if not isinstance(ev, dict):
            raise ValidationError(f"cignal manifest: events[{i}] must be an object")
        events.append(_field(ev, "name", str))

    kernel = CignalKernel(
        name=_match(_IDENT, _field(data, "name", str), "name"),
        c_name=_match(_IDENT, _field(data, "c_name", str), "c_name"),
        header=_match(_FILE, _field(data, "header", str), "header"),
        source=_match(_FILE, _field(data, "source", str), "source"),
        n_inputs=_field(data, "n_inputs", int),
        n_outputs=_field(data, "n_outputs", int),
        params=tuple(params),
        events=tuple(events),
        directory=path.resolve().parent,
    )
    if kernel.n_inputs < 0 or kernel.n_outputs < 1:
        raise ValidationError("cignal manifest: needs n_inputs >= 0 and n_outputs >= 1")
    for f in (kernel.header, kernel.source):
        if not (kernel.directory / f).is_file():
            raise ValidationError(f"cignal manifest: {f} not found beside {path.name}")
    return kernel


def manifest_from_cignal(kernel: CignalKernel) -> Manifest:
    from gen_dsp.core.manifest import Manifest, ParamInfo

    return Manifest(
        gen_name=kernel.stem,
        num_inputs=kernel.n_inputs,
        num_outputs=kernel.n_outputs,
        params=[
            ParamInfo(
                index=i,
                name=p.name,
                has_minmax=True,
                min=p.lo,
                max=p.hi,
                default=p.default,
            )
            for i, p in enumerate(kernel.params)
        ],
        source="cignal",
        version=__version__,
    )


def generate_adapter_cpp(kernel: CignalKernel, platform: str) -> str:
    """The ``_ext_{platform}.cpp`` that implements ``wrapper_*`` over the kernel's C ABI."""
    k = kernel.c_name
    return f"""\
// _ext_{platform}.cpp -- cignal adapter for the gen-dsp {platform} backend
// Generated by gen-dsp from {kernel.stem}{MANIFEST_SUFFIX}. Do not edit.

#include <cstdlib>

#include "gen_ext_common_{platform}.h"
#include "_ext_{platform}.h"
#include "{kernel.header}"

namespace WRAPPER_NAMESPACE {{

namespace {{

struct State {{
    {k} kernel;
    float values[{k}_N_PARAMS > 0 ? {k}_N_PARAMS : 1];  // last value set, for wrapper_get_param
}};

const cignal_param_info* param(int index) {{
    return (index >= 0 && index < {k}_N_PARAMS) ? &{k}_info.params[index] : nullptr;
}}

}}  // namespace

GenState* wrapper_create(float sr, long bs) {{
    (void)bs;
    // The kernel struct holds its delay lines inline, so it can be large: allocate, never stack.
    State* s = static_cast<State*>(std::calloc(1, sizeof(State)));
    if (s == nullptr) return nullptr;
    {k}_init(&s->kernel, sr);
    for (int i = 0; i < {k}_N_PARAMS; i++) s->values[i] = (float){k}_info.params[i].def;
    return s;
}}

void wrapper_destroy(GenState* state) {{ std::free(state); }}

void wrapper_reset(GenState* state) {{ {k}_reset(&static_cast<State*>(state)->kernel); }}

void wrapper_perform(GenState* state, float** ins, long numins, float** outs, long numouts, long n) {{
    (void)numins; (void)numouts;
    {k}_process(&static_cast<State*>(state)->kernel, ins, outs, (int)n);
}}

int wrapper_num_inputs() {{ return {k}_N_INPUTS; }}
int wrapper_num_outputs() {{ return {k}_N_OUTPUTS; }}
int wrapper_num_params() {{ return {k}_N_PARAMS; }}

const char* wrapper_param_name(GenState* state, int index) {{
    (void)state;
    const cignal_param_info* p = param(index);
    return p ? p->name : "";
}}

const char* wrapper_param_units(GenState* state, int index) {{
    (void)state; (void)index;
    return "";
}}

float wrapper_param_min(GenState* state, int index) {{
    (void)state;
    const cignal_param_info* p = param(index);
    return p ? (float)p->lo : 0.0f;
}}

float wrapper_param_max(GenState* state, int index) {{
    (void)state;
    const cignal_param_info* p = param(index);
    return p ? (float)p->hi : 0.0f;
}}

char wrapper_param_hasminmax(GenState* state, int index) {{
    (void)state;
    return param(index) ? 1 : 0;
}}

void wrapper_set_param(GenState* state, int index, float value) {{
    const cignal_param_info* p = param(index);
    if (p == nullptr) return;
    State* s = static_cast<State*>(state);
    {k}_set_param(&s->kernel, index, value);
    // The setter clamps the same way, in float.
    const float lo = (float)p->lo, hi = (float)p->hi;
    s->values[index] = value < lo ? lo : (value > hi ? hi : value);
}}

float wrapper_get_param(GenState* state, int index) {{
    return param(index) ? static_cast<State*>(state)->values[index] : 0.0f;
}}

int wrapper_num_buffers() {{ return 0; }}

const char* wrapper_buffer_name(int index) {{
    (void)index;
    return "";
}}

}}  // namespace WRAPPER_NAMESPACE
"""


def _add_c_source(build_file: Path, platform: str, source: str) -> None:
    """Add the kernel's C source to a generated build file.

    The graph build files list only C++ sources. cignal emits C99 with compound literals and
    ``restrict``, which C++ rejects, so the source is compiled as C, not included.
    """
    if platform in _CMAKE_TARGET_PLATFORMS:
        # `project()` without LANGUAGES enables C and CXX, so CMake compiles .c as C99 or later.
        with build_file.open("a", encoding="utf-8") as f:
            f.write(
                f"\n# cignal kernel, compiled as C\ntarget_sources(${{PROJECT_NAME}} PRIVATE {source})\n"
            )
        return
    raise ProjectError(f"cignal kernels are not supported on {platform!r} yet")


def generate_project(
    kernel: CignalKernel,
    manifest: Manifest,
    output_dir: Path,
    name: str,
    config: ProjectConfig,
    midi_defines: str,
) -> None:
    """Write a buildable project for ``config.platform`` into ``output_dir``."""
    platform = config.platform
    if platform not in SUPPORTED_PLATFORMS:
        raise ProjectError(
            f"cignal kernels are not supported on {platform!r} yet; "
            f"supported: {', '.join(sorted(SUPPORTED_PLATFORMS))}"
        )
    # The build-file generators live with the graph frontend, which imports pydantic.
    from gen_dsp.graph.adapter import (
        _copy_platform_templates,
        _generate_buffer_header,
        generate_graph_build_file,
    )
    from gen_dsp.platforms import get_platform

    for f in (kernel.header, kernel.source):
        shutil.copy2(kernel.directory / f, output_dir / f)
    (output_dir / f"_ext_{platform}.cpp").write_text(
        generate_adapter_cpp(kernel, platform), encoding="utf-8"
    )
    _copy_platform_templates(output_dir, platform)
    platform_impl = get_platform(platform)
    if not (output_dir / f"_ext_{platform}.h").is_file():
        platform_impl.generate_ext_header(output_dir, platform)
    _generate_buffer_header(output_dir)
    platform_impl.copy_voice_alloc_header(output_dir, config)
    build_file = generate_graph_build_file(
        output_dir=output_dir,
        platform=platform,
        lib_name=name,
        gen_name=kernel.stem,
        num_inputs=manifest.num_inputs,
        num_outputs=manifest.num_outputs,
        num_params=manifest.num_params,
        gendsp_version=__version__,
        shared_cache=config.shared_cache,
        midi_defines=midi_defines,
    )
    _add_c_source(build_file, platform, kernel.source)
