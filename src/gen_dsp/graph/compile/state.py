"""Per-node state emitters for C++ code generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from gen_dsp.graph.compile.common import _Writer, _float_lit
from gen_dsp.graph.models import (
    SVF,
    ADSR,
    Accum,
    Allpass,
    Biquad,
    Buffer,
    BufRead,
    BufWrite,
    Change,
    Counter,
    Cycle,
    DCBlock,
    DelayLine,
    DelayRead,
    DelayWrite,
    Delta,
    Elapsed,
    History,
    Latch,
    Lookup,
    MulAccum,
    Node,
    Noise,
    OnePole,
    Peek,
    Phasor,
    PulseOsc,
    RateDiv,
    SampleHold,
    SawOsc,
    SinOsc,
    Slide,
    SmoothParam,
    Splat,
    TriOsc,
    Wave,
)
from gen_dsp.graph.optimize import _STATEFUL_TYPES


# ---------------------------------------------------------------------------
# Struct field emission
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Per-node state emitters
#
# Each stateful node type maps to a _StateEmitter describing its contribution to
# the five state passes: struct fields, create()-time init, reset(), and the
# per-sample load/save of perform() locals. Keeping all five in one place per
# node type means adding a stateful node is a single registry entry instead of
# five coordinated edits across the file.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StateField:
    """One scalar struct member of a stateful node.

    suffix: name suffix appended to the node id ("" for History).
    ctype:  C type of the struct member and its perform-loop local.
    init:   value assigned in create(); a literal, a callable(node) -> literal,
            or None to rely on the calloc-zeroed struct.
    reset:  value assigned in reset(); same forms, None to skip.
    save:   whether the perform-loop local is written back to the struct.
    """

    suffix: str
    ctype: str
    init: str | Callable[[Node], str] | None
    reset: str | Callable[[Node], str] | None
    save: bool = True


def _state_value(v: str | Callable[[Node], str], node: Node) -> str:
    return v(node) if callable(v) else v


class _StateEmitter:
    """Base state emitter; each method returns the lines for one pass."""

    def fields(self, node: Node) -> list[str]:
        return []

    def init(self, node: Node) -> list[str]:
        return []

    def reset(self, node: Node) -> list[str]:
        return []

    def load(self, node: Node) -> list[str]:
        return []

    def save(self, node: Node) -> list[str]:
        return []


class _FieldState(_StateEmitter):
    """State emitter for node types whose state is a list of scalar fields."""

    def __init__(self, *fields: _StateField) -> None:
        self._fields = fields

    def fields(self, node: Node) -> list[str]:
        return [f"    {f.ctype} m_{node.id}{f.suffix};" for f in self._fields]

    def init(self, node: Node) -> list[str]:
        return [
            f"    self->m_{node.id}{f.suffix} = {_state_value(f.init, node)};"
            for f in self._fields
            if f.init is not None
        ]

    def reset(self, node: Node) -> list[str]:
        return [
            f"    self->m_{node.id}{f.suffix} = {_state_value(f.reset, node)};"
            for f in self._fields
            if f.reset is not None
        ]

    def load(self, node: Node) -> list[str]:
        return [
            f"    {f.ctype} {node.id}{f.suffix} = self->m_{node.id}{f.suffix};"
            for f in self._fields
        ]

    def save(self, node: Node) -> list[str]:
        return [
            f"    self->m_{node.id}{f.suffix} = {node.id}{f.suffix};"
            for f in self._fields
            if f.save
        ]


class _DelayLineState(_StateEmitter):
    """A ring buffer: pointer + length + write index (only the index is saved)."""

    def fields(self, node: Node) -> list[str]:
        return [
            f"    float* m_{node.id}_buf;",
            f"    int m_{node.id}_len;",
            f"    int m_{node.id}_wr;",
        ]

    def init(self, node: Node) -> list[str]:
        assert isinstance(node, DelayLine)
        return [
            f"    self->m_{node.id}_len = {node.max_samples};",
            f"    self->m_{node.id}_buf = (float*)calloc({node.max_samples}, sizeof(float));",
            f"    self->m_{node.id}_wr = 0;",
        ]

    def reset(self, node: Node) -> list[str]:
        return [
            f"    memset(self->m_{node.id}_buf, 0, self->m_{node.id}_len * sizeof(float));",
            f"    self->m_{node.id}_wr = 0;",
        ]

    def load(self, node: Node) -> list[str]:
        return [
            f"    float* {node.id}_buf = self->m_{node.id}_buf;",
            f"    int {node.id}_len = self->m_{node.id}_len;",
            f"    int {node.id}_wr = self->m_{node.id}_wr;",
        ]

    def save(self, node: Node) -> list[str]:
        return [f"    self->m_{node.id}_wr = {node.id}_wr;"]


class _BufferState(_StateEmitter):
    """A fixed table: pointer + length, optionally sine-filled; never saved."""

    def fields(self, node: Node) -> list[str]:
        return [f"    float* m_{node.id}_buf;", f"    int m_{node.id}_len;"]

    def init(self, node: Node) -> list[str]:
        assert isinstance(node, Buffer)
        lines = [
            f"    self->m_{node.id}_len = {node.size};",
            f"    self->m_{node.id}_buf = (float*)calloc({node.size}, sizeof(float));",
        ]
        if node.fill == "sine":
            lines.append(f"    for (int _k = 0; _k < {node.size}; _k++)")
            lines.append(
                f"        self->m_{node.id}_buf[_k] = sinf(2.0f * 3.14159265f * (float)_k / (float){node.size});"
            )
        return lines

    def reset(self, node: Node) -> list[str]:
        assert isinstance(node, Buffer)
        if node.fill == "sine":
            return [
                f"    for (int _k = 0; _k < self->m_{node.id}_len; _k++)",
                f"        self->m_{node.id}_buf[_k] = sinf(2.0f * 3.14159265f * (float)_k / (float)self->m_{node.id}_len);",
            ]
        return [
            f"    memset(self->m_{node.id}_buf, 0, self->m_{node.id}_len * sizeof(float));"
        ]

    def load(self, node: Node) -> list[str]:
        return [
            f"    float* {node.id}_buf = self->m_{node.id}_buf;",
            f"    int {node.id}_len = self->m_{node.id}_len;",
        ]


def _history_init_value(node: Node) -> str:
    assert isinstance(node, History)
    return _float_lit(node.init)


# Shared emitters for node types with identical state shapes.
_S_PHASE = _FieldState(_StateField("_phase", "float", None, "0.0f"))


_S_PREV = _FieldState(_StateField("_prev", "float", "0.0f", "0.0f"))


_S_BIQUAD = _FieldState(
    _StateField("_s1", "float", "0.0f", "0.0f"),
    _StateField("_s2", "float", "0.0f", "0.0f"),
)


_S_DCBLOCK = _FieldState(
    _StateField("_xprev", "float", "0.0f", "0.0f"),
    _StateField("_yprev", "float", "0.0f", "0.0f"),
)


_S_SAMPLEHOLD = _FieldState(
    _StateField("_held", "float", "0.0f", "0.0f"),
    _StateField("_ptrig", "float", "0.0f", "0.0f"),
)


# Maps each own-state node type to its emitter. Types that participate in
# stateful semantics but store no state of their own (they reference a
# DelayLine/Buffer) are listed in _STATE_BY_REFERENCE below.
_STATE_EMITTERS: dict[type, _StateEmitter] = {
    History: _FieldState(
        _StateField("", "float", _history_init_value, _history_init_value)
    ),
    DelayLine: _DelayLineState(),
    Buffer: _BufferState(),
    Phasor: _S_PHASE,
    SinOsc: _S_PHASE,
    TriOsc: _S_PHASE,
    SawOsc: _S_PHASE,
    PulseOsc: _S_PHASE,
    Noise: _FieldState(_StateField("_seed", "uint32_t", "123456789u", "123456789u")),
    Delta: _S_PREV,
    Change: _S_PREV,
    OnePole: _S_PREV,
    SmoothParam: _S_PREV,
    Slide: _S_PREV,
    Biquad: _S_BIQUAD,
    SVF: _S_BIQUAD,
    DCBlock: _S_DCBLOCK,
    Allpass: _S_DCBLOCK,
    SampleHold: _S_SAMPLEHOLD,
    Latch: _S_SAMPLEHOLD,
    Accum: _FieldState(_StateField("_sum", "float", None, "0.0f")),
    Counter: _FieldState(
        _StateField("_count", "int", None, "0"),
        _StateField("_ptrig", "float", None, "0.0f"),
    ),
    Elapsed: _FieldState(_StateField("_count", "int", None, "0")),
    MulAccum: _FieldState(_StateField("_prod", "float", "1.0f", "1.0f")),
    RateDiv: _FieldState(
        _StateField("_count", "int", "0", "0"),
        _StateField("_held", "float", "0.0f", "0.0f"),
    ),
    ADSR: _FieldState(
        _StateField("_phase", "int", "0", "0"),
        _StateField("_output", "float", "0.0f", "0.0f"),
        _StateField("_ptrig", "float", "0.0f", "0.0f"),
    ),
    Peek: _FieldState(_StateField("_value", "float", "0.0f", "0.0f")),
}


# Stateful node types that store no state of their own -- they read/write the
# state of a DelayLine or Buffer they reference. Listing them keeps the
# exhaustiveness check below honest without requiring an empty emitter each.
_STATE_BY_REFERENCE: frozenset[type] = frozenset(
    {DelayRead, DelayWrite, BufRead, BufWrite, Splat, Cycle, Wave, Lookup}
)


# Fail loudly at import if a stateful node type has neither an emitter nor an
# explicit by-reference declaration (e.g. a new node type added to the model
# and to _STATEFUL_TYPES but missing its state handling here).
_unhandled_stateful = [
    t
    for t in _STATEFUL_TYPES
    if t not in _STATE_EMITTERS and t not in _STATE_BY_REFERENCE
]


assert not _unhandled_stateful, (
    "state emitter registry out of sync with _STATEFUL_TYPES: "
    f"{_unhandled_stateful} unhandled"
)


def _emit_state_fields(node: Node, w: _Writer) -> None:
    emitter = _STATE_EMITTERS.get(type(node))
    if emitter is not None:
        for line in emitter.fields(node):
            w(line)


def _emit_state_init(node: Node, w: _Writer) -> None:
    emitter = _STATE_EMITTERS.get(type(node))
    if emitter is not None:
        for line in emitter.init(node):
            w(line)


def _emit_state_reset(node: Node, w: _Writer) -> None:
    emitter = _STATE_EMITTERS.get(type(node))
    if emitter is not None:
        for line in emitter.reset(node):
            w(line)


def _emit_state_load(node: Node, w: _Writer) -> None:
    emitter = _STATE_EMITTERS.get(type(node))
    if emitter is not None:
        for line in emitter.load(node):
            w(line)


def _emit_state_save(node: Node, w: _Writer) -> None:
    emitter = _STATE_EMITTERS.get(type(node))
    if emitter is not None:
        for line in emitter.save(node):
            w(line)
