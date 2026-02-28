# gen_dsp.graph

An optional graph frontend for gen-dsp: define DSP signal graphs in Python, compile them to C++, and generate buildable plugin projects for any supported platform.

The primary purpose of `gen_dsp.graph` is to provide a way to test gen-dsp backends without requiring physical gen~ exports. It may also evolve into a useful frontend in its own right. Define audio processing graphs using Pydantic models, validate them, compile to C++, simulate in Python with numpy, and serialize to/from JSON.

Requires pydantic (numpy optional for simulation).

## Install

```bash
pip install gen-dsp[graph]

# With simulation support (numpy):
pip install gen-dsp[sim]
```

## Quick Start

```python
from gen_dsp.graph import (
    AudioInput, AudioOutput, BinOp, Graph, History, Param,
    compile_graph, validate_graph,
)

graph = Graph(
    name="onepole",
    inputs=[AudioInput(id="in1")],
    outputs=[AudioOutput(id="out1", source="result")],
    params=[Param(name="coeff", min=0.0, max=0.999, default=0.5)],
    nodes=[
        BinOp(id="inv_coeff", op="sub", a=1.0, b="coeff"),
        BinOp(id="dry", op="mul", a="in1", b="inv_coeff"),
        History(id="prev", init=0.0, input="result"),
        BinOp(id="wet", op="mul", a="prev", b="coeff"),
        BinOp(id="result", op="add", a="dry", b="wet"),
    ],
)

errors = validate_graph(graph)
assert errors == []

code = compile_graph(graph)  # standalone C++ string
print(graph.model_dump_json(indent=2))
```

## Generating Plugin Projects

The graph frontend integrates directly with gen-dsp's `ProjectGenerator` to produce buildable plugin projects for all 11 supported platforms:

```python
from gen_dsp.graph import AudioInput, AudioOutput, BinOp, Graph, Param
from gen_dsp.core.project import ProjectConfig, ProjectGenerator

graph = Graph(
    name="stereo_gain",
    inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
    outputs=[
        AudioOutput(id="out1", source="scaled1"),
        AudioOutput(id="out2", source="scaled2"),
    ],
    params=[Param(name="gain", min=0.0, max=2.0, default=1.0)],
    nodes=[
        BinOp(id="scaled1", op="mul", a="in1", b="gain"),
        BinOp(id="scaled2", op="mul", a="in2", b="gain"),
    ],
)

config = ProjectConfig(name=graph.name, platform="clap")
gen = ProjectGenerator.from_graph(graph, config)
project_dir = gen.generate(output_dir="build/stereo_gain_clap")
```

This produces a complete, buildable project -- no gen~ export required.

## Simulation

Run graphs in Python without C++ compilation. Useful for prototyping, unit-testing DSP algorithms, and verifying correctness. Requires numpy (`pip install gen-dsp[sim]`).

```python
import numpy as np
from gen_dsp.graph.simulate import simulate, SimState

# Simulate with audio input
inp = np.ones(100, dtype=np.float32)
result = simulate(graph, inputs={"in1": inp}, params={"coeff": 0.3})

# Output arrays keyed by output ID
output = result.outputs["out1"]  # NDArray[np.float32]

# State persists across calls for streaming
result2 = simulate(graph, inputs={"in1": inp}, state=result.state)

# Generators (no inputs) require explicit n_samples
from gen_dsp.graph import Graph, AudioOutput, SinOsc
gen = Graph(
    name="tone",
    outputs=[AudioOutput(id="out1", source="osc")],
    nodes=[SinOsc(id="osc", freq=440.0)],
    sample_rate=44100.0,
)
result = simulate(gen, n_samples=44100)

# Buffer and peek access via SimState
state = SimState(graph)
state.set_param("coeff", 0.7)
state.set_buffer("wt", np.sin(np.linspace(0, 2*np.pi, 1024)).astype(np.float32))
result = simulate(graph, inputs={"in1": inp}, state=state)
print(state.get_peek("monitor"))
```

The simulator executes a per-sample Python loop that mirrors the C++ codegen exactly: same topo-sorted node order, same deferred History write-backs, same interpolation formulas.

## Multi-Rate Processing

Nodes can be explicitly assigned to run at control rate (once per block) instead of audio rate (per sample). This is useful for parameter smoothing, coefficient computation, and other operations that don't need per-sample updates.

```python
from gen_dsp.graph import Graph, AudioInput, AudioOutput, BinOp, Param, SmoothParam

graph = Graph(
    name="smooth_gain",
    sample_rate=48000.0,
    control_interval=64,          # control block = 64 samples
    control_nodes=["smoother"],   # these nodes run once per block
    inputs=[AudioInput(id="in0")],
    outputs=[AudioOutput(id="out0", source="scaled")],
    params=[Param(name="vol", default=0.5)],
    nodes=[
        SmoothParam(id="smoother", a="vol", coeff=0.99),   # control-rate
        BinOp(id="scaled", op="mul", a="in0", b="smoother"),  # audio-rate
    ],
)
```

When `control_interval > 0`, the generated C++ uses a two-tier loop structure:

```cpp
for (int _cb = 0; _cb < n; _cb += 64) {
    int _block_end = (_cb + 64 < n) ? _cb + 64 : n;
    // Control-rate nodes (once per block)
    float smoother = ...;
    for (int i = _cb; i < _block_end; i++) {
        // Audio-rate nodes (per sample)
        float scaled = in0[i] * smoother;
        out0[i] = scaled;
    }
}
```

Nodes are classified into three tiers:

1. **Invariant** (LICM): pure nodes depending only on params/literals -- hoisted before both loops.
2. **Control-rate**: nodes listed in `control_nodes` -- computed once per control block.
3. **Audio-rate**: everything else -- computed per sample.

The simulator mirrors this behavior: control-rate nodes compute at block boundaries and hold their values between updates. Setting `control_interval = 0` (the default) preserves the existing single-loop behavior.

Validation enforces that control-rate nodes cannot depend on audio inputs or audio-rate nodes. Dependencies on params, other control-rate nodes, and invariant nodes are allowed.

## Graph Algebra

FAUST-style block diagram combinators for composing graphs without manually wiring `Subgraph` nodes. Four combinators build new `Graph` objects from existing ones:

```python
from gen_dsp.graph import Graph, AudioInput, AudioOutput, OnePole, Param
from gen_dsp.graph.algebra import series, parallel, split, merge

lpf = Graph(
    name="lpf",
    inputs=[AudioInput(id="in")],
    outputs=[AudioOutput(id="out", source="filt")],
    params=[Param(name="coeff", default=0.5)],
    nodes=[OnePole(id="filt", a="in", coeff="coeff")],
)
hpf = Graph(name="hpf", inputs=[AudioInput(id="in")],
            outputs=[AudioOutput(id="out", source="filt")],
            params=[Param(name="coeff", default=0.3)],
            nodes=[OnePole(id="filt", a="in", coeff="coeff")])

# Series: pipe outputs -> inputs (requires matching counts)
chain = series(lpf, hpf)  # 1-in, 1-out, params: lpf_coeff, hpf_coeff

# Parallel: stack side by side (independent I/O)
stack = parallel(lpf, hpf)  # 2-in (lpf_in, hpf_in), 2-out (lpf_out, hpf_out)

# Split: fan-out (cyclic distribution, requires len(b.inputs) % len(a.outputs) == 0)
duo = split(lpf, stack)  # 1-in, 2-out (lpf output duplicated to both)

# Merge: fan-in (grouped summing, requires len(a.outputs) % len(b.inputs) == 0)
mono = merge(stack, lpf)  # 2-in, 1-out (stack outputs summed into lpf input)
```

Operator overloading provides concise syntax -- `>>` for series, `//` for parallel:

```python
chain = lpf >> hpf           # series
stack = lpf // hpf           # parallel
multi = (lpf // hpf) >> out  # parallel then series
```

Params are namespaced with the subgraph ID prefix at each level of nesting. For `series(lpf, hpf)`, inner param `coeff` becomes `lpf_coeff` and `hpf_coeff`. This compounds with deeper nesting: `series(series(a, b), c)` produces params like `a__b_a_coeff`.

All composed graphs work with `expand_subgraphs()`, `compile_graph()`, `validate_graph()`, and `simulate()`.

## CLI

The `gen-dsp graph` subcommand group compiles, validates, and visualizes graph JSON files.

```bash
# Compile graph to C++ (stdout)
gen-dsp graph compile graph.json

# Compile to directory with optimization
gen-dsp graph compile graph.json -o build/ --optimize

# Compile with platform adapter for a specific backend
gen-dsp graph compile graph.json --platform chuck -o build/

# Validate graph JSON
gen-dsp graph validate graph.json

# Generate DOT visualization (stdout or directory)
gen-dsp graph dot graph.json -o build/

# Generate a buildable plugin project directly from a graph JSON
gen-dsp init --from-graph graph.json -n myeffect -p clap -o build/myeffect
```

## Node Types (38)

### Arithmetic / Math

| Node | `op` | Fields | Purpose |
|------|------|--------|---------|
| `BinOp` | `add`, `sub`, `mul`, `div`, `min`, `max`, `mod`, `pow` | `a`, `b` | Binary arithmetic |
| `UnaryOp` | `sin`, `cos`, `tanh`, `exp`, `log`, `abs`, `sqrt`, `neg`, `floor`, `ceil`, `round`, `sign`, `atan`, `asin`, `acos` | `a` | Unary math functions |
| `Clamp` | `clamp` | `a`, `lo`, `hi` | Saturate to `[lo, hi]` |
| `Constant` | `constant` | `value` | Literal float value |
| `Compare` | `gt`, `lt`, `gte`, `lte`, `eq` | `a`, `b` | Comparison (returns 0.0 or 1.0) |
| `Select` | `select` | `cond`, `a`, `b` | Conditional: `a` if `cond > 0`, else `b` |
| `Wrap` | `wrap` | `a`, `lo`, `hi` | Wrap value into range |
| `Fold` | `fold` | `a`, `lo`, `hi` | Fold (reflect) value into range |
| `Mix` | `mix` | `a`, `b`, `t` | Linear interpolation: `a + (b - a) * t` |
| `Scale` | `scale` | `a`, `in_lo`, `in_hi`, `out_lo`, `out_hi` | Linear range mapping |

### Delay

| Node | `op` | Fields | Purpose |
|------|------|--------|---------|
| `DelayLine` | `delay` | `max_samples` | Circular buffer declaration |
| `DelayRead` | `delay_read` | `delay`, `tap`, `interp` | Read from delay line (none/linear/cubic) |
| `DelayWrite` | `delay_write` | `delay`, `value` | Write to delay line |
| `History` | `history` | `input`, `init` | Single-sample delay (z^-1 feedback) |

### Buffer / Table

| Node | `op` | Fields | Purpose |
|------|------|--------|---------|
| `Buffer` | `buffer` | `size` | Random-access data buffer |
| `BufRead` | `buf_read` | `buffer`, `index`, `interp` | Read from buffer (none/linear/cubic, clamped) |
| `BufWrite` | `buf_write` | `buffer`, `index`, `value` | Write to buffer at index |
| `BufSize` | `buf_size` | `buffer` | Returns buffer length as float |

### Filters

| Node | `op` | Fields | Purpose |
|------|------|--------|---------|
| `Biquad` | `biquad` | `a`, `b0`, `b1`, `b2`, `a1`, `a2` | Generic biquad (user supplies coefficients) |
| `SVF` | `svf` | `a`, `freq`, `q`, `mode` | State-variable filter (lp/hp/bp/notch) |
| `OnePole` | `onepole` | `a`, `coeff` | One-pole lowpass |
| `DCBlock` | `dcblock` | `a` | DC blocking filter |
| `Allpass` | `allpass` | `a`, `coeff` | First-order allpass |

### Oscillators / Sources

| Node | `op` | Fields | Purpose |
|------|------|--------|---------|
| `Phasor` | `phasor` | `freq` | Ramp oscillator 0..1 |
| `SinOsc` | `sinosc` | `freq` | Sine oscillator |
| `TriOsc` | `triosc` | `freq` | Triangle wave |
| `SawOsc` | `sawosc` | `freq` | Bipolar saw (-1..1) |
| `PulseOsc` | `pulseosc` | `freq`, `width` | Pulse/square with variable duty cycle |
| `Noise` | `noise` | -- | White noise source |

### State / Timing

| Node | `op` | Fields | Purpose |
|------|------|--------|---------|
| `Delta` | `delta` | `a` | Sample-to-sample difference |
| `Change` | `change` | `a` | 1.0 if value changed, else 0.0 |
| `SampleHold` | `sample_hold` | `a`, `trig` | Latch on any zero crossing |
| `Latch` | `latch` | `a`, `trig` | Latch on rising edge only |
| `Accum` | `accum` | `incr`, `reset` | Running sum, resets when `reset > 0` |
| `Counter` | `counter` | `trig`, `max` | Integer counter, wraps at max |
| `RateDiv` | `rate_div` | `a`, `divisor` | Output every N-th sample, hold between |
| `SmoothParam` | `smooth` | `a`, `coeff` | One-pole smoothing for param changes |
| `Peek` | `peek` | `a` | Debug pass-through, readable externally |

## C++ Compilation

`compile_graph()` generates a single self-contained `.cpp` file with:

- A state struct (`{Name}State`)
- `create(sr)` / `destroy(self)` / `reset(self)` lifecycle
- `perform(self, ins, outs, n)` sample-processing loop
- Param introspection: `num_params`, `param_name`, `param_min`, `param_max`, `set_param`, `get_param`
- Buffer introspection: `num_buffers`, `buffer_name`, `buffer_size`, `get_buffer`, `set_buffer`
- Peek introspection: `num_peeks`, `peek_name`, `get_peek`

```python
from gen_dsp.graph import compile_graph, compile_graph_to_file

code = compile_graph(graph)           # returns C++ string
path = compile_graph_to_file(graph, "build/")  # writes build/{name}.cpp
```

The compiled C++ follows the same `wrapper_*` interface that gen-dsp's platform backends expect, so it plugs directly into any platform's `_ext_{platform}.cpp` adapter without modification.

## Optimization

```python
from gen_dsp.graph import optimize_graph

optimized = optimize_graph(graph)  # constant folding + CSE + dead node elimination
```

- **Constant folding**: pure nodes with all-constant inputs are replaced by `Constant` nodes
- **Common subexpression elimination**: duplicate pure nodes with identical inputs are merged
- **Dead node elimination**: nodes not reachable from any output are removed (respects side-effecting writers for delay lines and buffers)
- **Loop-invariant code motion**: param-only expressions are hoisted before the sample loop
- **Multi-rate processing**: control-rate nodes run once per block in an outer loop, reducing per-sample overhead for smoothing/coefficient computation
- **SIMD hints**: `__restrict` on I/O pointers; vectorization pragmas for pure-only graphs

## Validation

`validate_graph()` checks:

1. Unique node IDs (no collisions with inputs or params)
2. All string references resolve to existing IDs
3. Output sources reference existing nodes
4. DelayRead/DelayWrite reference existing DelayLine nodes
5. BufRead/BufWrite/BufSize reference existing Buffer nodes
6. Control-rate consistency: `control_nodes` reference existing nodes, don't depend on audio inputs or audio-rate nodes
7. No pure cycles (cycles must pass through History or delay)

## Visualization

```python
from gen_dsp.graph import graph_to_dot, graph_to_dot_file

dot_str = graph_to_dot(graph)                  # DOT string
dot_path = graph_to_dot_file(graph, "build/")  # writes .dot, renders .pdf if `dot` is on PATH
```

## Examples

See `examples/graph/` for complete working graphs. All examples are backend-agnostic -- select the target platform with `-p`:

```bash
python examples/graph/stereo_gain.py -p clap
python examples/graph/fbdelay.py -p vst3
python examples/graph/wavetable.py -p sc
```

- `stereo_gain.py` -- stateless stereo gain
- `onepole.py` -- one-pole lowpass with History feedback
- `fbdelay.py` -- feedback delay with dry/wet mix
- `wavetable.py` -- wavetable oscillator using Buffer + Phasor + BufRead
- `smooth_gain.py` -- control-rate parameter smoothing (multi-rate)
- `multirate_synth.py` -- control-rate envelope with audio-rate oscillator (multi-rate)
- `filter_chain.py` -- two filters in series using graph algebra
- `noise_gate.py` -- dynamics gate with envelope follower
- `chorus.py` -- modulated delay chorus effect
- `subtractive_synth.py` -- sawtooth through one-pole lowpass (generator)
