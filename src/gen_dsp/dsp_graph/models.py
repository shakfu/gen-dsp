from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

# Type alias for node input references: either a node/input/param ID or a literal float.
Ref = Union[str, float]


# ---------------------------------------------------------------------------
# Param & I/O declarations
# ---------------------------------------------------------------------------


class Param(BaseModel):
    name: str
    min: float = 0.0
    max: float = 1.0
    default: float = 0.0


class AudioInput(BaseModel):
    id: str


class AudioOutput(BaseModel):
    id: str
    source: str  # node ID that feeds this output


# ---------------------------------------------------------------------------
# Node types (discriminated union on "op")
# ---------------------------------------------------------------------------


class BinOp(BaseModel):
    id: str
    op: Literal["add", "sub", "mul", "div", "min", "max", "mod", "pow"]
    a: Ref
    b: Ref


class UnaryOp(BaseModel):
    id: str
    op: Literal[
        "sin",
        "cos",
        "tanh",
        "exp",
        "log",
        "abs",
        "sqrt",
        "neg",
        "floor",
        "ceil",
        "round",
        "sign",
        "atan",
        "asin",
        "acos",
    ]
    a: Ref


class Clamp(BaseModel):
    id: str
    op: Literal["clamp"] = "clamp"
    a: Ref
    lo: Ref = 0.0
    hi: Ref = 1.0


class Constant(BaseModel):
    id: str
    op: Literal["constant"] = "constant"
    value: float


class History(BaseModel):
    id: str
    op: Literal["history"] = "history"
    init: float = 0.0
    input: str  # node ID whose value is stored for next sample


class DelayLine(BaseModel):
    id: str
    op: Literal["delay"] = "delay"
    max_samples: int = 48000


class DelayRead(BaseModel):
    id: str
    op: Literal["delay_read"] = "delay_read"
    delay: str  # delay line ID
    tap: Ref  # tap position: node ID or literal
    interp: Literal["none", "linear", "cubic"] = "none"


class DelayWrite(BaseModel):
    id: str
    op: Literal["delay_write"] = "delay_write"
    delay: str  # delay line ID
    value: Ref  # node ID or literal to write


class Phasor(BaseModel):
    id: str
    op: Literal["phasor"] = "phasor"
    freq: Ref


class Noise(BaseModel):
    id: str
    op: Literal["noise"] = "noise"


class Compare(BaseModel):
    id: str
    op: Literal["gt", "lt", "gte", "lte", "eq"]
    a: Ref
    b: Ref


class Select(BaseModel):
    id: str
    op: Literal["select"] = "select"
    cond: Ref
    a: Ref
    b: Ref


class Wrap(BaseModel):
    id: str
    op: Literal["wrap"] = "wrap"
    a: Ref
    lo: Ref = 0.0
    hi: Ref = 1.0


class Fold(BaseModel):
    id: str
    op: Literal["fold"] = "fold"
    a: Ref
    lo: Ref = 0.0
    hi: Ref = 1.0


class Mix(BaseModel):
    id: str
    op: Literal["mix"] = "mix"
    a: Ref
    b: Ref
    t: Ref


class Delta(BaseModel):
    id: str
    op: Literal["delta"] = "delta"
    a: Ref


class Change(BaseModel):
    id: str
    op: Literal["change"] = "change"
    a: Ref


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


class Biquad(BaseModel):
    id: str
    op: Literal["biquad"] = "biquad"
    a: Ref
    b0: Ref
    b1: Ref
    b2: Ref
    a1: Ref
    a2: Ref


class SVF(BaseModel):
    id: str
    op: Literal["svf"] = "svf"
    a: Ref
    freq: Ref
    q: Ref
    mode: Literal["lp", "hp", "bp", "notch"]


class OnePole(BaseModel):
    id: str
    op: Literal["onepole"] = "onepole"
    a: Ref
    coeff: Ref


class DCBlock(BaseModel):
    id: str
    op: Literal["dcblock"] = "dcblock"
    a: Ref


class Allpass(BaseModel):
    id: str
    op: Literal["allpass"] = "allpass"
    a: Ref
    coeff: Ref


# ---------------------------------------------------------------------------
# Oscillators
# ---------------------------------------------------------------------------


class SinOsc(BaseModel):
    id: str
    op: Literal["sinosc"] = "sinosc"
    freq: Ref


class TriOsc(BaseModel):
    id: str
    op: Literal["triosc"] = "triosc"
    freq: Ref


class SawOsc(BaseModel):
    id: str
    op: Literal["sawosc"] = "sawosc"
    freq: Ref


class PulseOsc(BaseModel):
    id: str
    op: Literal["pulseosc"] = "pulseosc"
    freq: Ref
    width: Ref


# ---------------------------------------------------------------------------
# State / Timing
# ---------------------------------------------------------------------------


class SampleHold(BaseModel):
    id: str
    op: Literal["sample_hold"] = "sample_hold"
    a: Ref
    trig: Ref


class Latch(BaseModel):
    id: str
    op: Literal["latch"] = "latch"
    a: Ref
    trig: Ref


class Accum(BaseModel):
    id: str
    op: Literal["accum"] = "accum"
    incr: Ref
    reset: Ref


class Counter(BaseModel):
    id: str
    op: Literal["counter"] = "counter"
    trig: Ref
    max: Ref


class RateDiv(BaseModel):
    id: str
    op: Literal["rate_div"] = "rate_div"
    a: Ref
    divisor: Ref


class SmoothParam(BaseModel):
    id: str
    op: Literal["smooth"] = "smooth"
    a: Ref
    coeff: Ref


class Peek(BaseModel):
    id: str
    op: Literal["peek"] = "peek"
    a: Ref


# ---------------------------------------------------------------------------
# Range mapping
# ---------------------------------------------------------------------------


class Scale(BaseModel):
    id: str
    op: Literal["scale"] = "scale"
    a: Ref
    in_lo: Ref = 0.0
    in_hi: Ref = 1.0
    out_lo: Ref = 0.0
    out_hi: Ref = 1.0


# ---------------------------------------------------------------------------
# Subgraph / Macro
# ---------------------------------------------------------------------------


class Subgraph(BaseModel):
    id: str
    op: Literal["subgraph"] = "subgraph"
    graph: Graph
    inputs: dict[str, Ref]
    params: dict[str, Ref] = {}
    output: str = ""


# ---------------------------------------------------------------------------
# Buffer / Table
# ---------------------------------------------------------------------------


class Buffer(BaseModel):
    id: str
    op: Literal["buffer"] = "buffer"
    size: int = 48000


class BufRead(BaseModel):
    id: str
    op: Literal["buf_read"] = "buf_read"
    buffer: str  # Buffer node ID
    index: Ref  # read position (float, will be clamped)
    interp: Literal["none", "linear", "cubic"] = "none"


class BufWrite(BaseModel):
    id: str
    op: Literal["buf_write"] = "buf_write"
    buffer: str  # Buffer node ID
    index: Ref  # write position
    value: Ref  # value to write


class BufSize(BaseModel):
    id: str
    op: Literal["buf_size"] = "buf_size"
    buffer: str  # Buffer node ID


# Discriminated union of all node types
Node = Annotated[
    Union[
        BinOp,
        UnaryOp,
        Clamp,
        Constant,
        History,
        DelayLine,
        DelayRead,
        DelayWrite,
        Phasor,
        Noise,
        Compare,
        Select,
        Wrap,
        Fold,
        Mix,
        Delta,
        Change,
        Biquad,
        SVF,
        OnePole,
        DCBlock,
        Allpass,
        SinOsc,
        TriOsc,
        SawOsc,
        PulseOsc,
        SampleHold,
        Latch,
        Accum,
        Counter,
        RateDiv,
        SmoothParam,
        Peek,
        Scale,
        Subgraph,
        Buffer,
        BufRead,
        BufWrite,
        BufSize,
    ],
    Field(discriminator="op"),
]


# ---------------------------------------------------------------------------
# Top-level graph
# ---------------------------------------------------------------------------


class Graph(BaseModel):
    name: str
    sample_rate: float = 44100.0
    control_interval: int = 0  # 0 = disabled; >0 = samples per control block
    control_nodes: list[str] = []  # node IDs that run at control rate
    inputs: list[AudioInput] = []
    outputs: list[AudioOutput] = []
    params: list[Param] = []
    nodes: list[Node] = []


# Resolve circular reference: Subgraph.graph -> Graph -> list[Node] -> Subgraph
Subgraph.model_rebuild()
