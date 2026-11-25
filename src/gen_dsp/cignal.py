"""cignal frontend: wrap a kernel compiled by cignal in a gen-dsp platform project.

The input is the ``<stem>.cignal.json`` manifest that ``cignal build --manifest`` writes beside
``<stem>.h`` and ``<stem>.c``. gen-dsp reads the three files and does not import cignal.

The adapter implements the ``wrapper_*`` interface over cignal's C ABI. cignal kernels never
allocate, so ``wrapper_create`` allocates the struct. cignal has no parameter getter, so the
adapter keeps the last value set for ``wrapper_get_param``.

A kernel with events ``note(pitch, velocity)`` and ``off(pitch)`` gets MIDI notes on the platforms
in ``NOTE_EVENT_PLATFORMS``, through the optional ``wrapper_note_on``/``wrapper_note_off`` hooks.
The kernel allocates its own voices. Other events have no host binding and are unreachable.
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
    from gen_dsp.core.midi import MidiMapping
    from gen_dsp.core.project import ProjectConfig

MANIFEST_SUFFIX = ".cignal.json"
MANIFEST_FORMAT = 1
# CMake build files whose plugin target is `${PROJECT_NAME}`, so the C source can be appended.
# Max is left out: its wrapper passes double buffers. SSP cross-compiles for one device.
_CMAKE_TARGET_PLATFORMS = frozenset({"au", "clap", "lv2", "sc", "vst3"})
SUPPORTED_PLATFORMS = _CMAKE_TARGET_PLATFORMS
# Templates that call `wrapper_note_on`/`wrapper_note_off` under WRAPPER_NOTE_EVENTS.
NOTE_EVENT_PLATFORMS = frozenset({"clap", "lv2", "vst3"})
_EVENT_ARG_TYPES = frozenset({"i32", "f32", "f64", "bool"})

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FILE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


@dataclass(frozen=True)
class CignalParam:
    name: str
    lo: float
    hi: float
    default: float


@dataclass(frozen=True)
class CignalEvent:
    name: str
    args: tuple[str, ...]


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
    events: tuple[CignalEvent, ...]
    directory: Path

    @property
    def stem(self) -> str:
        return Path(self.header).stem

    def note_event_indices(self) -> tuple[int, int] | None:
        """Indices of ``note(pitch, velocity)`` and ``off(pitch)``, if the kernel has both."""
        index = {e.name: i for i, e in enumerate(self.events)}
        note, off = index.get("note"), index.get("off")
        if note is None or off is None:
            return None
        if len(self.events[note].args) != 2 or len(self.events[off].args) != 1:
            return None
        return note, off

    def unreachable_events(self, platform: str) -> list[str]:
        """Events no host can call on ``platform``."""
        bound = (
            {"note", "off"}
            if platform in NOTE_EVENT_PLATFORMS and self.note_event_indices()
            else set()
        )
        return [e.name for e in self.events if e.name not in bound]


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
        args = _field(ev, "args", list)
        if not all(isinstance(a, str) and a in _EVENT_ARG_TYPES for a in args):
            raise ValidationError(
                f"cignal manifest: events[{i}] args must be in {sorted(_EVENT_ARG_TYPES)}"
            )
        events.append(
            CignalEvent(
                name=_match(_IDENT, _field(ev, "name", str), f"events[{i}] name"),
                args=tuple(args),
            )
        )

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


def note_mapping(kernel: CignalKernel, config: ProjectConfig) -> MidiMapping | None:
    """The MIDI mapping that routes notes to the kernel's events, or None to map parameters.

    Raises ``ValidationError`` for polyphony: a kernel with note events allocates its own voices.
    """
    from gen_dsp.core.midi import MidiMapping

    if (
        config.no_midi
        or config.platform not in NOTE_EVENT_PLATFORMS
        or kernel.note_event_indices() is None
    ):
        return None
    if config.num_voices > 1:
        raise ValidationError(
            f"{kernel.name} allocates its own voices (note/off events); drop --voices"
        )
    return MidiMapping(enabled=True, note_events=True)


def _note_hooks_cpp(kernel: CignalKernel) -> str:
    indices = kernel.note_event_indices()
    assert indices is not None
    note, off = indices
    k = kernel.c_name
    return f"""
// MIDI notes call the kernel's `note` and `off` events; cignal converts each argument.
void wrapper_note_on(GenState* state, int key, float velocity) {{
    const float args[2] = {{(float)key, velocity}};
    {k}_event(&static_cast<State*>(state)->kernel, {note}, args);
}}

void wrapper_note_off(GenState* state, int key) {{
    const float args[1] = {{(float)key}};
    {k}_event(&static_cast<State*>(state)->kernel, {off}, args);
}}
"""


def generate_adapter_cpp(
    kernel: CignalKernel, platform: str, note_events: bool = False
) -> str:
    """The ``_ext_{platform}.cpp`` that implements ``wrapper_*`` over the kernel's C ABI.

    ``note_events`` adds the ``wrapper_note_*`` hooks; see ``note_mapping``.
    """
    k = kernel.c_name
    hooks = _note_hooks_cpp(kernel) if note_events else ""
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
{hooks}
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
    from gen_dsp.platforms import get_platform

    for f in (kernel.header, kernel.source):
        shutil.copy2(kernel.directory / f, output_dir / f)
    note_events = config.midi_mapping is not None and config.midi_mapping.note_events
    (output_dir / f"_ext_{platform}.cpp").write_text(
        generate_adapter_cpp(kernel, platform, note_events), encoding="utf-8"
    )
    build_file = get_platform(platform).generate_wrapped_project(
        manifest, output_dir, name, config, midi_defines
    )
    _add_c_source(build_file, platform, kernel.source)
