# Pydantic DSP Graph Vocabulary

How Pydantic models define the DSP graph that serializes to JSON and compiles to C++ in `gen_dsp.graph`.

## Architecture

```text
Python (Pydantic models)  -->  JSON (intermediate)  -->  C++ (compiled output)
      build graph              .model_dump_json()         compile_graph()
```

The graph is the single source of truth. JSON serialization allows storage, diffing, and machine transformation. The C++ compiler produces a self-contained file that follows gen-dsp's `wrapper_*` interface, plugging into any of the 11 platform backends.

## Core Models

```python
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Param & I/O declarations
# ---------------------------------------------------------------------------

class Param(BaseModel):
    name: str
    min: float = 0.0
    max: float = 1.0
    default: float = 0.0


class AudioInput(BaseModel):
    id: str                     # e.g. "in1"


class AudioOutput(BaseModel):
    id: str                     # e.g. "out1"
    source: str                 # node ID that feeds this output


# ---------------------------------------------------------------------------
# Node types (discriminated union on "op")
# ---------------------------------------------------------------------------

class BinOp(BaseModel):
    """Arithmetic binary operator."""
    id: str
    op: Literal["add", "sub", "mul", "div", "min", "max", "mod", "pow"]
    a: str | float              # node ID or literal
    b: str | float


class UnaryOp(BaseModel):
    """Math function applied to a single input."""
    id: str
    op: Literal["sin", "cos", "tanh", "exp", "log", "abs", "sqrt",
                "neg", "floor", "ceil", "round", "sign", "atan", "asin", "acos"]
    a: str | float


class Clamp(BaseModel):
    """Clamp a signal to [lo, hi]."""
    id: str
    op: Literal["clamp"] = "clamp"
    a: str | float
    lo: str | float = 0.0
    hi: str | float = 1.0


class History(BaseModel):
    """Single-sample delay (z^-1). Breaks feedback loops."""
    id: str
    op: Literal["history"] = "history"
    init: float = 0.0
    input: str                  # node ID whose value is stored for next sample


class DelayLine(BaseModel):
    """Multi-sample circular buffer declaration."""
    id: str
    op: Literal["delay"] = "delay"
    max_samples: int = 48000


class DelayRead(BaseModel):
    """Read from a delay line at a tap position (in samples)."""
    id: str
    op: Literal["delay_read"] = "delay_read"
    delay: str                  # delay line ID
    tap: str | float            # tap position node ID or literal
    interp: Literal["none", "linear", "cubic"] = "none"


class DelayWrite(BaseModel):
    """Write a value into a delay line."""
    id: str
    op: Literal["delay_write"] = "delay_write"
    delay: str                  # delay line ID
    value: str | float          # node ID or literal to write


class Phasor(BaseModel):
    """Ramp oscillator 0..1 at given frequency."""
    id: str
    op: Literal["phasor"] = "phasor"
    freq: str | float


class SinOsc(BaseModel):
    """Sine oscillator."""
    id: str
    op: Literal["sinosc"] = "sinosc"
    freq: str | float


class Noise(BaseModel):
    """White noise source."""
    id: str
    op: Literal["noise"] = "noise"


# ... plus SawOsc, TriOsc, PulseOsc, SVF, Biquad, OnePole, DCBlock,
#     Allpass, Buffer, BufRead, BufWrite, BufSize, Compare, Select,
#     Wrap, Fold, Mix, Scale, Delta, Change, SampleHold, Latch,
#     Accum, Counter, RateDiv, SmoothParam, Peek, Constant, Subgraph


# Discriminated union of all node types
Node = Annotated[
    Union[BinOp, UnaryOp, Clamp, History, DelayLine, DelayRead, DelayWrite,
          Phasor, SinOsc, Noise, ...],
    Field(discriminator="op"),
]


# ---------------------------------------------------------------------------
# Top-level graph
# ---------------------------------------------------------------------------

class Graph(BaseModel):
    name: str
    sample_rate: float = 44100.0
    control_interval: int = 0           # 0 = single-loop, >0 = two-tier
    control_nodes: list[str] = []       # node IDs that run at control rate
    inputs: list[AudioInput] = []
    outputs: list[AudioOutput] = []
    params: list[Param] = []
    nodes: list[Node] = []
```

### Node Type Categories

| Category | Nodes | State |
|----------|-------|-------|
| Arithmetic | `BinOp`, `UnaryOp`, `Clamp`, `Constant` | none |
| Comparison | `Compare`, `Select` | none |
| Range | `Wrap`, `Fold`, `Mix`, `Scale` | none |
| Delay | `DelayLine`, `DelayRead`, `DelayWrite` | N samples (circular buffer) |
| Feedback | `History` | 1 sample |
| Buffer | `Buffer`, `BufRead`, `BufWrite`, `BufSize` | N samples (random access) |
| Filters | `Biquad`, `SVF`, `OnePole`, `DCBlock`, `Allpass` | 1-4 samples |
| Oscillators | `Phasor`, `SinOsc`, `TriOsc`, `SawOsc`, `PulseOsc`, `Noise` | 1 sample (phase/seed) |
| State | `Delta`, `Change`, `SampleHold`, `Latch`, `Accum`, `Counter`, `RateDiv` | 1-2 samples |
| Control | `SmoothParam` | 1 sample |
| Debug | `Peek` | 1 sample |
| Composition | `Subgraph` | varies |

---

## Example: One-Pole Lowpass

### Building the Graph in Python

```python
from gen_dsp.graph import (
    AudioInput, AudioOutput, BinOp, Graph, History, Param,
)

graph = Graph(
    name="onepole",
    inputs=[AudioInput(id="in1")],
    outputs=[AudioOutput(id="out1", source="result")],
    params=[Param(name="coeff", min=0.0, max=0.999, default=0.5)],
    nodes=[
        # (1 - coeff)
        BinOp(id="inv_coeff", op="sub", a=1.0, b="coeff"),
        # in1 * (1 - coeff)
        BinOp(id="dry", op="mul", a="in1", b="inv_coeff"),
        # previous output
        History(id="prev", init=0.0, input="result"),
        # prev * coeff
        BinOp(id="wet", op="mul", a="prev", b="coeff"),
        # dry + wet
        BinOp(id="result", op="add", a="dry", b="wet"),
    ],
)
```

### JSON Output (`graph.model_dump_json(indent=2)`)

```json
{
  "name": "onepole",
  "sample_rate": 44100.0,
  "inputs": [
    { "id": "in1" }
  ],
  "outputs": [
    { "id": "out1", "source": "result" }
  ],
  "params": [
    { "name": "coeff", "min": 0.0, "max": 0.999, "default": 0.5 }
  ],
  "nodes": [
    { "id": "inv_coeff", "op": "sub", "a": 1.0, "b": "coeff" },
    { "id": "dry",       "op": "mul", "a": "in1", "b": "inv_coeff" },
    { "id": "prev",      "op": "history", "init": 0.0, "input": "result" },
    { "id": "wet",       "op": "mul", "a": "prev", "b": "coeff" },
    { "id": "result",    "op": "add", "a": "dry", "b": "wet" }
  ]
}
```

### C++ Output (from `compile_graph()`)

```cpp
struct OnepoleState {
    float sr;
    float p_coeff;
    float m_prev;       // history: prev
};

OnepoleState* create(float sr) {
    OnepoleState* self = new OnepoleState();
    self->sr = sr;
    self->p_coeff = 0.5f;
    self->m_prev = 0.0f;
    return self;
}

void perform(OnepoleState* self,
             float** __restrict ins, float** __restrict outs, int n) {
    float* in1  = ins[0];
    float* out1 = outs[0];
    float coeff = self->p_coeff;
    float prev  = self->m_prev;

    // Invariant: hoisted before loop
    float inv_coeff = 1.0f - coeff;

    for (int i = 0; i < n; i++) {
        float dry    = in1[i] * inv_coeff;
        float wet    = prev * coeff;
        float result = dry + wet;

        out1[i] = result;
        prev = result;      // history feedback
    }

    self->m_prev = prev;
}
```

---

## Example: Feedback Delay

### Python

```python
from gen_dsp.graph import (
    AudioInput, AudioOutput, BinOp, DelayLine, DelayRead, DelayWrite,
    Graph, Param,
)

graph = Graph(
    name="fbdelay",
    inputs=[AudioInput(id="in1")],
    outputs=[AudioOutput(id="out1", source="mix_out")],
    params=[
        Param(name="delay_ms", min=1.0, max=1000.0, default=250.0),
        Param(name="feedback", min=0.0, max=0.95, default=0.5),
        Param(name="mix", min=0.0, max=1.0, default=0.5),
    ],
    nodes=[
        # delay time: ms -> samples
        BinOp(id="sr_ms", op="div", a=44100.0, b=1000.0),
        BinOp(id="tap", op="mul", a="delay_ms", b="sr_ms"),

        # delay line
        DelayLine(id="dline", max_samples=48000),
        DelayRead(id="delayed", delay="dline", tap="tap"),

        # feedback path: delayed * feedback + input
        BinOp(id="fb_scaled", op="mul", a="delayed", b="feedback"),
        BinOp(id="write_val", op="add", a="in1", b="fb_scaled"),
        DelayWrite(id="dwrite", delay="dline", value="write_val"),

        # dry/wet mix
        BinOp(id="inv_mix", op="sub", a=1.0, b="mix"),
        BinOp(id="dry", op="mul", a="in1", b="inv_mix"),
        BinOp(id="wet", op="mul", a="delayed", b="mix"),
        BinOp(id="mix_out", op="add", a="dry", b="wet"),
    ],
)
```

### JSON Output

```json
{
  "name": "fbdelay",
  "sample_rate": 44100.0,
  "inputs": [{ "id": "in1" }],
  "outputs": [{ "id": "out1", "source": "mix_out" }],
  "params": [
    { "name": "delay_ms", "min": 1.0, "max": 1000.0, "default": 250.0 },
    { "name": "feedback", "min": 0.0, "max": 0.95, "default": 0.5 },
    { "name": "mix",      "min": 0.0, "max": 1.0,  "default": 0.5 }
  ],
  "nodes": [
    { "id": "sr_ms",     "op": "div",         "a": 44100.0, "b": 1000.0 },
    { "id": "tap",       "op": "mul",         "a": "delay_ms", "b": "sr_ms" },
    { "id": "dline",     "op": "delay",       "max_samples": 48000 },
    { "id": "delayed",   "op": "delay_read",  "delay": "dline", "tap": "tap" },
    { "id": "fb_scaled", "op": "mul",         "a": "delayed", "b": "feedback" },
    { "id": "write_val", "op": "add",         "a": "in1", "b": "fb_scaled" },
    { "id": "dwrite",    "op": "delay_write", "delay": "dline", "value": "write_val" },
    { "id": "inv_mix",   "op": "sub",         "a": 1.0, "b": "mix" },
    { "id": "dry",       "op": "mul",         "a": "in1", "b": "inv_mix" },
    { "id": "wet",       "op": "mul",         "a": "delayed", "b": "mix" },
    { "id": "mix_out",   "op": "add",         "a": "dry", "b": "wet" }
  ]
}
```

---

## The Codegen Pass

The compiler that transforms `Graph` -> C++ needs roughly three stages:

### 1. Topological Sort

Resolve evaluation order. Nodes reference each other by ID; the compiler builds a dependency graph and sorts it. Feedback edges (`History.input`, `DelayWrite.value` -> `DelayRead`) are back-edges that break cycles.

```python
from gen_dsp.graph.toposort import toposort

sorted_nodes = toposort(graph)
```

### 2. State Layout

Walk sorted nodes and collect stateful elements:

| Node type | State fields |
|-----------|-------------|
| `Param` | `float p_{name}` |
| `History` | `float m_{id}` |
| `DelayLine` | `float* m_{id}_buf`, `int m_{id}_len`, `int m_{id}_wr` |
| `Buffer` | `float* m_{id}_buf`, `int m_{id}_len` |
| Oscillators | `float m_{id}_phase` |
| Filters | `float m_{id}_y1`, etc. |

### 3. Code Emission

Walk sorted nodes and emit one C++ statement per node. The compiler classifies each node as invariant (hoisted), control-rate (outer loop), or audio-rate (inner loop) based on its dependencies.

```python
from gen_dsp.graph import compile_graph

code = compile_graph(graph)  # complete C++ string
```

---

## What This Provides

| Concern | gen~ export path | Graph frontend path |
|---------|-----------------|---------------------|
| DSP definition | Max/MSP GUI | Python code or JSON |
| IR format | C++ (opaque) | JSON (inspectable, transformable) |
| Compiler | gen~ (closed source) | `gen_dsp.graph` (open, extensible) |
| Host wrappers | gen-dsp platform backends | Same gen-dsp platform backends |
| Operator set | gen~ vocabulary | 38 node types (extensible) |
| Simulation | N/A | Python/numpy (`simulate()`) |

The JSON IR is the key artifact: it's diffable, version-controllable, and machine-transformable. Both paths produce the same `wrapper_*` C++ interface, so all 11 gen-dsp platform backends work identically regardless of which frontend was used.
