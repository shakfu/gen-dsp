# gen_dsp.graph Operator Coverage vs gen~ Operators

This document compares the operators available in `gen_dsp.graph` against the operators documented in the [gen~ operator reference](https://docs.cycling74.com/userguide/gen/gen~_operators) and [gen common operator reference](https://docs.cycling74.com/userguide/gen/gen_common_operators). It is both a per-operator coverage matrix (below) and the forward-looking gap analysis (roadmap and recommendation at the end).

Last updated: 2026-06-28

## Scope and framing

Coverage is not a subset relation, and "close the gap" should not be read as "reach parity with gen~". The graph frontend exists to exercise gen-dsp's platform backends without requiring gen~ exports; the zero-dependency C++-export path (`core/parser.py`) already handles real gen~ patches for plugin generation. So the target is not full gen~ semantics -- it is enough scalar and stateful coverage that backend tests are representative, plus one escape hatch for everything else.

Two asymmetries matter:

- The graph is a pure dataflow DAG; gen~ / GenExpr is an imperative language. The whole pipeline (`toposort`, `simulate`, `optimize`, `transpile`, and the 11 backends) depends on the acyclic scalar-dataflow invariant. Some gaps are cheap node additions; others cannot be expressed without breaking that invariant (see "Structural / semantic gaps" below).
- gen-dsp is not strictly narrower than gen~. It adds higher-level DSP blocks that gen~ has no primitive for (`Biquad`, `SVF`, `OnePole`, `Allpass`, `ADSR`, and the `SinOsc`/`TriOsc`/`SawOsc`/`PulseOsc` family). So the frontend is a curated, higher-level DSP vocabulary: narrower on language expressiveness, wider on ready-made blocks.

The honest one-line summary: the frontend covers gen~'s straight-line scalar arithmetic, single-sample state, and 1-D buffer/delay access essentially completely, and adds convenience DSP blocks on top. It cannot express gen~'s imperative layer (loops, conditionals, functions), the spectral/complex domain, multichannel or host-bound buffers, or integer-mode operators.

## Recent additions (2026-06-28)

Tier 1 of the roadmap below was implemented and fully tested (full suite green). Each item was wired through every touchpoint -- model, C++ emitter, simulator, constant-fold/CSE, transpiler, differential evaluator, DSL, serializer, visualizer -- with a dedicated test module and differential-corpus cases.

- Bitwise `bitand` / `bitor` / `bitxor` / `bitshift` / `bitnot`. Shared 32-bit-int scalar semantics live in `graph/bitops.py` so the three Python evaluators (simulate, fold, transpile-eval) cannot drift. gen~ `bitshift` direction is a defined-but-Max-unverified convention (non-negative shifts left, negative right, amount masked to `[0, 31]`).
- `interp` node with `linear` and `cosine` modes (the `Mix`-is-linear-only gap). 4-point cubic/spline is deferred.
- `nearest` interpolation mode on `BufRead` / `DelayRead` (round-half-up index vs `none`'s truncation).
- `train` impulse-generator node (one-sample `1.0` each cycle, distinct from the bipolar `PulseOsc`).
- Deferred: `rate` (ambiguous gen~ ramp-resync semantics; `RateDiv` already covers rate-division).

Five demo patches in `examples/dsl/` exercise these: `bitcrush`, `bitglitch`, `sh_sequencer`, `wavemorph`, `lofi_wavetable`.

## Summary

| Category | gen~ Total | Implemented | Coverage |
|----------|-----------|-------------|----------|
| Math / Arithmetic | 12 | 12 | 100% |
| Comparison | 15 | 15 | 100% |
| Logic | 5 | 5 | 100% |
| Bitwise | 5 | 5 | 100% |
| Trigonometry | 19 | 19 | 100% |
| Powers | 9 | 9 | 100% |
| Numeric | 7 | 7 | 100% |
| Constants | 17 | 15 | 88% |
| Range | 4 | 4 | 100% |
| Route / Mixing | 7 | 5 | 71% |
| Filter | 8 | 8 | 100% |
| Waveform / Oscillators | 5 | 5 | 100% |
| Integrator / State | 3 | 3 | 100% |
| Feedback / Delay | 2 | 2 | 100% |
| Buffer / Data | 12 | 8 | 67% |
| Convert | 6 | 6 | 100% |
| DSP | 6 | 6 | 100% |
| FFT | 1 | 0 | 0% |
| Global | 5 | 1 | 20% |
| I/O / Declare | 4 | 3 | 75% |
| Subpatcher | 2 | 1 | 50% |
| **Total** | **~154** | **~139** | **~90%** |

Note: Some gen~ operators have aliases (e.g. `ln`/`log`, `clip`/`clamp`). Each unique function is counted once. The "p" comparison variants (`eqp`, `gtp`, etc.) are counted as separate operators since they have distinct semantics (return value vs return 1/0).

---

## Detailed Coverage by Category

### Math / Arithmetic

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `+` / `add` | `BinOp("add")` | |
| `-` / `sub` | `BinOp("sub")` | |
| `*` / `mul` | `BinOp("mul")` | |
| `/` / `div` | `BinOp("div")` | |
| `%` / `mod` | `BinOp("mod")` | |
| `neg` | `UnaryOp("neg")` | |
| `absdiff` | `BinOp("absdiff")` | |
| `pow` | `BinOp("pow")` | |
| `hypot` | `BinOp("hypot")` | |
| `!-` / `rsub` | `BinOp("rsub")` | Reverse subtract: b - a |
| `!/` / `rdiv` | `BinOp("rdiv")` | Reverse divide: b / a |
| `!%` / `rmod` | `BinOp("rmod")` | Reverse modulo: fmod(b, a) |

**Full coverage.**

### Comparison

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `>` / `gt` | `Compare("gt")` | |
| `<` / `lt` | `Compare("lt")` | |
| `>=` / `gte` | `Compare("gte")` | |
| `<=` / `lte` | `Compare("lte")` | |
| `==` / `eq` | `Compare("eq")` | |
| `!=` / `neq` | `Compare("neq")` | |
| `max` / `maximum` | `BinOp("max")` | |
| `min` / `minimum` | `BinOp("min")` | |
| `step` | `BinOp("step")` | |
| `>p` / `gtp` | `BinOp("gtp")` | Returns a if a > b, else 0 |
| `<p` / `ltp` | `BinOp("ltp")` | Returns a if a < b, else 0 |
| `>=p` / `gtep` | `BinOp("gtep")` | Returns a if a >= b, else 0 |
| `<=p` / `ltep` | `BinOp("ltep")` | Returns a if a <= b, else 0 |
| `==p` / `eqp` | `BinOp("eqp")` | Returns a if a == b, else 0 |
| `!=p` / `neqp` | `BinOp("neqp")` | Returns a if a != b, else 0 |

**Full coverage.**

### Logic

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `!` / `not` | `UnaryOp("not")` | |
| `&&` / `and` | `BinOp("and")` | |
| `\|\|` / `or` | `BinOp("or")` | |
| `^^` / `xor` | `BinOp("xor")` | |
| `bool` | `UnaryOp("bool")` | |

**Full coverage.**

### Bitwise

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `&` / `bitand` | `BinOp("bitand")` | Operates on the 32-bit-int value |
| `\|` / `bitor` | `BinOp("bitor")` | |
| `^` / `bitxor` | `BinOp("bitxor")` | |
| `<<` `>>` / `bitshift` | `BinOp("bitshift")` | `b >= 0` left, `b < 0` right |
| `~` / `bitnot` | `UnaryOp("bitnot")` | |

**Full coverage.**

### Trigonometry

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `sin` | `UnaryOp("sin")` | |
| `cos` | `UnaryOp("cos")` | |
| `tan` | `UnaryOp("tan")` | |
| `asin` | `UnaryOp("asin")` | |
| `acos` | `UnaryOp("acos")` | |
| `atan` | `UnaryOp("atan")` | |
| `atan2` | `BinOp("atan2")` | |
| `sinh` | `UnaryOp("sinh")` | |
| `cosh` | `UnaryOp("cosh")` | |
| `tanh` | `UnaryOp("tanh")` | |
| `asinh` | `UnaryOp("asinh")` | |
| `acosh` | `UnaryOp("acosh")` | |
| `atanh` | `UnaryOp("atanh")` | |
| `hypot` | `BinOp("hypot")` | |
| `degrees` | `UnaryOp("degrees")` | a * 180/pi |
| `radians` | `UnaryOp("radians")` | a * pi/180 |
| `fastsin` | `UnaryOp("fastsin")` | Bhaskara I approximation in C++ |
| `fastcos` | `UnaryOp("fastcos")` | Bhaskara I approximation in C++ |
| `fasttan` | `UnaryOp("fasttan")` | sinf/cosf ratio in C++ |

**Full coverage.**

### Powers

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `exp` | `UnaryOp("exp")` | |
| `exp2` | `UnaryOp("exp2")` | |
| `ln` / `log` | `UnaryOp("log")` | |
| `log2` | `UnaryOp("log2")` | |
| `log10` | `UnaryOp("log10")` | |
| `pow` | `BinOp("pow")` | |
| `sqrt` | `UnaryOp("sqrt")` | |
| `fastexp` | `UnaryOp("fastexp")` | Schraudolph's method in C++ |
| `fastpow` | `BinOp("fastpow")` | exp2(b * log2(a)) in C++ |

**Full coverage.**

### Numeric

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `abs` | `UnaryOp("abs")` | |
| `ceil` | `UnaryOp("ceil")` | |
| `floor` | `UnaryOp("floor")` | |
| `trunc` | `UnaryOp("trunc")` | |
| `fract` | `UnaryOp("fract")` | |
| `round` | `UnaryOp("round")` | |
| `sign` | `UnaryOp("sign")` | |

**Full coverage.**

### Constants

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `pi` | `NamedConstant("pi")` | |
| `twopi` | `NamedConstant("twopi")` | |
| `halfpi` | `NamedConstant("halfpi")` | |
| `invpi` | `NamedConstant("invpi")` | |
| `e` | `NamedConstant("e")` | |
| `degtorad` | `NamedConstant("degtorad")` | |
| `radtodeg` | `NamedConstant("radtodeg")` | |
| `sqrt2` | `NamedConstant("sqrt2")` | |
| `sqrt1_2` | `NamedConstant("sqrt1_2")` | |
| `ln2` | `NamedConstant("ln2")` | |
| `ln10` | `NamedConstant("ln10")` | |
| `log2e` | `NamedConstant("log2e")` | |
| `log10e` | `NamedConstant("log10e")` | |
| `phi` | `NamedConstant("phi")` | |
| `samplerate` | `SampleRate` | Runtime node |
| `vectorsize` | -- | Runtime constant |
| `constant` / `f` / `i` | `Constant` | Literal values |

**Missing**: `vectorsize` (block size -- not relevant to per-sample graph processing).

### Range

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `clamp` / `clip` | `Clamp` | |
| `wrap` | `Wrap` | |
| `fold` | `Fold` | |
| `scale` | `Scale` | |

**Full coverage.**

### Route / Mixing

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `?` / `switch` | `Select` | Conditional select |
| `gate` | `GateRoute` + `GateOut` | Container + satellite |
| `selector` | `Selector` | N-to-1 mux |
| `mix` | `Mix` | Linear interpolation |
| `smoothstep` | `Smoothstep` | |
| `send` / `s` | -- | Named signal bus |
| `receive` / `r` | -- | Named signal bus |

**Missing**: `send`/`receive` (named signal buses). These are a graph-level wiring abstraction -- in the graph frontend, nodes reference each other by ID, which serves the same purpose.

### Filter

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `change` | `Change` | |
| `dcblock` | `DCBlock` | |
| `delta` | `Delta` | |
| `latch` | `Latch` | |
| `sah` | `SampleHold` | Sample-and-hold |
| `slide` | `Slide` | Asymmetric slew limiter |
| `phasewrap` | `UnaryOp("phasewrap")` | Wrap to [-pi, pi] |
| `interp` | `Interp` | Two-point interpolation (linear/cosine) |

**Full coverage** for the two-point modes. gen~'s 4-point `interp` (cubic/spline) is deferred; the `buf_read`/`delay_read` cubic paths already cover 4-point table interpolation.

### Waveform / Oscillators

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `noise` | `Noise` | |
| `phasor` | `Phasor` | |
| `train` | `Train` | Impulse train (`PulseOsc` is the bipolar pulse oscillator) |
| `triangle` | `TriOsc` | |
| `rate` | -- | Phase rate-scaling (composable) |

Note: gen_dsp.graph also provides `SinOsc` and `SawOsc` which are not direct gen~ operators (gen~ uses `cycle` for sine lookup and manual phasor+math for saw). The `rate` operator is phase multiplication, trivially expressed as `BinOp("mul")`.

### Integrator / State

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `+=` / `accum` | `Accum` | |
| `counter` | `Counter` | |
| `*=` / `mulequals` | `MulAccum` | Multiplicative accumulator |

**Full coverage.**

### Feedback / Delay

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `delay` | `DelayLine` + `DelayRead` + `DelayWrite` | |
| `history` | `History` | Single-sample feedback |

**Full coverage.**

### Buffer / Data

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `data` | `Buffer` | Internal sample array |
| `peek` | `BufRead` | Read from buffer |
| `poke` | `BufWrite` | Write to buffer |
| `dim` | `BufSize` | Buffer length query |
| `cycle` | `Cycle` | Sine wavetable oscillator |
| `lookup` | `Lookup` | Waveshaping lookup |
| `wave` | `Wave` | Wavetable synthesis |
| `splat` | `Splat` | Overdub write (buf[idx] += value) |
| `buffer` | -- | External buffer~ ref |
| `channels` | -- | Multi-channel query |
| `nearest` | `BufRead(interp="nearest")` | Round-to-nearest index read |
| `sample` | `BufRead(interp="linear")` | Normalized/interpolated read |

**Missing**: `buffer` (external buffer~ references are out of scope -- see the Tier 2 spike finding below), `channels` (no multi-channel buffer support).

### Convert

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `atodb` | `UnaryOp("atodb")` | 20 * log10(a) |
| `dbtoa` | `UnaryOp("dbtoa")` | pow(10, a/20) |
| `ftom` | `UnaryOp("ftom")` | 69 + 12*log2(a/440) |
| `mtof` | `UnaryOp("mtof")` | 440 * pow(2, (a-69)/12) |
| `mstosamps` | `UnaryOp("mstosamps")` | a * sr / 1000 (sr-dependent) |
| `sampstoms` | `UnaryOp("sampstoms")` | a * 1000 / sr (sr-dependent) |

**Full coverage.** Note: `mstosamps`, `sampstoms` are sample-rate dependent and cannot be constant-folded.

### DSP Utilities

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `fixdenorm` | `UnaryOp("fixdenorm")` | Replace denormals with 0 |
| `fixnan` | `UnaryOp("fixnan")` | Replace NaN with 0 |
| `isdenorm` | `UnaryOp("isdenorm")` | Denormal detection (1 or 0) |
| `isnan` | `UnaryOp("isnan")` | NaN detection (1 or 0) |
| `t60` | `UnaryOp("t60")` | Decay coefficient: exp(-6.9078/(a*sr)) |
| `t60time` | `UnaryOp("t60time")` | Inverse decay time: -6.9078/(log(a)*sr) |

**Full coverage.**

### FFT

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `fftinfo` | -- | FFT frame info |

**Not implemented.** FFT processing (pfft~) is out of scope for the graph frontend.

### Global / Environment

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `elapsed` | `Elapsed` | Sample counter |
| `mc_channel` | -- | MC channel index |
| `mc_channelcount` | -- | MC channel count |
| `voice` | -- | Poly voice index |
| `voicecount` | -- | Poly voice count |

**Missing**: `mc_channel`, `mc_channelcount`, `voice`, `voicecount` -- these are Max/MSP environment queries, out of scope for the graph frontend.

### I/O and Declaration

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `in` | `AudioInput` | Graph-level input |
| `out` | `AudioOutput` | Graph-level output |
| `param` | `Param` | Named parameter |
| `expr` | -- | Inline GenExpr |

`expr` (inline GenExpr code) is not applicable to the graph frontend.

### Subpatcher

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `gen` (subpatcher) | `Subgraph` | Nested graph |
| `setparam` | -- | Set subpatch param |

`setparam` is handled implicitly by `Subgraph.params` mapping.

---

## Additional gen_dsp.graph Nodes (No gen~ Equivalent)

These nodes exist in gen_dsp.graph but have no direct gen~ operator counterpart:

| Node | Description |
|------|-------------|
| `SinOsc` | Direct sine oscillator (gen~ uses `cycle` with wavetable) |
| `SawOsc` | Direct sawtooth oscillator (gen~ uses `phasor` + scaling) |
| `SVF` | State-variable filter (gen~ builds from primitives) |
| `Biquad` | Direct biquad filter (gen~ builds from `history` + math) |
| `Allpass` | Direct allpass filter (gen~ builds from `history` + math) |
| `OnePole` | Direct one-pole filter (gen~ builds from `history` + math) |
| `SmoothParam` | Parameter smoothing (gen~ uses `slide` or `history`) |
| `RateDiv` | Rate divider (gen~ uses `counter` + `latch`) |
| `ADSR` | Attack-Decay-Sustain-Release envelope generator |
| `Peek` | Debug/passthrough (different from gen~'s buffer `peek`) |
| `Pass` | Identity node |

These higher-level nodes provide convenience abstractions that would require multiple gen~ operators to implement.

---

## Remaining Gaps

### Out of Scope

- FFT operators (`fftinfo`, `fftsize`, etc.) -- no pfft~ support

- Max/MSP environment (`voice`, `mc_channel`, etc.) -- host-specific

- `send`/`receive` -- graph wiring abstraction (nodes reference by ID)

### Trivially Composable

- `rate` -- phase multiplication via `BinOp("mul")` (a dedicated node is deferred; ambiguous gen~ semantics)

### Not Yet Implemented

- `buffer` -- external buffer~ references

- `channels` -- multi-channel buffer query

- `vectorsize` -- block size constant

- `setparam` -- handled by `Subgraph.params`

- `expr` -- inline GenExpr (not applicable)

---

## Structural / semantic gaps (beyond the operator matrix)

The matrix above counts operators. The larger gaps are not missing operators but things the IR cannot represent by construction, because a `Graph` is a pure dataflow DAG:

- Imperative control flow and loops. GenExpr codeboxes have `if/else`, `for`, `while`, local variables, and local arrays. A `for` loop over buffer samples (the idiom for block / FFT-style work, custom convolution, variable-length scans) has no expressible form in a node DAG. This is the single largest gap; the transpiler emits into GenExpr but only uses its straight-line subset.
- User-defined functions. GenExpr allows `f(x){...}` declarations and calls. `Subgraph` covers macro inlining and reuse, but not recursion or arbitrary-arity local functions.
- Spectral / complex domain: `fft`, `ifft`, `fftinfo`, and complex arithmetic (`cartopol`, `poltocar`, complex multiply). Absent entirely.
- Multichannel buffers. gen~ `Data`/`Buffer` are N-channel; the frontend `Buffer` is strictly mono (1-D).
- Host-bound buffers. gen~ `Buffer "name"` references a Max `buffer~` by name; the frontend `Buffer` is internal-only with `fill in {zeros, sine}`.

## Roadmap: what could be added

Tiers are ordered by how much they disturb the dataflow-DAG invariant. The tier boundary, not the operator count, drives the decision.

### Tier 1 -- new node types, zero IR change (done)

The cheap, in-scope additions -- each a Pydantic class in `models.py` plus emission in `compile/nodes.py` / `simulate.py` / `transpile.py`, a `validate.py` rule, and tests. This tier is implemented (bitwise, `interp` linear/cosine, `nearest`, `train`); see "Recent additions" above. `rate` and 4-point cubic/spline `interp` are deferred.

### Tier 2 -- model extensions that bend the DAG but do not break it

Still dataflow, but they touch the buffer / IO model and ripple into `adapter.py` and each backend's buffer-header generation: multichannel buffers (`channels` on `Buffer`, a channel argument on the buffer ops, a `channels` node), host-bound buffers (let `Buffer` reference external sample data), and a `vectorsize` node. **Rejected for the graph path** -- see the spike finding below.

#### Tier 2 spike finding (2026-06-28): rejected for the graph path

A design spike for the combined "multichannel + host-bound buffers" path found it leads to a mess and was not implemented. The decisive facts:

- The multichannel host-buffer machinery already exists in the genlib / platform layer, not the graph path. A host buffer is a `DataInterface` (channel-aware C++ class); the WebAudio backend already loads interleaved multichannel data via `wrapper_load_buffer(index, data, frames, channels)` with `WebaudioBuffer : DataInterface` storing `data[frame*channels + ch]`. So multichannel sample playback is already achievable today on the platform built for it, through the gen~-export path.
- The graph compile path is deliberately genlib-free: buffers are raw `float*` arrays, no `DataInterface`. Giving them multichannel host loading would re-implement a channel-aware buffer abstraction next to the real one -- exactly the drift the header-isolation / manifest split exists to prevent.
- The shared `Manifest` IR carries only buffer names (`buffers: list[str]`). Adding size/channels metadata ripples into the gen~-export producer (`manifest_from_export_info`), which has no source for buffer channel counts.
- Host buffer loading is per-platform and already fragmented: only WebAudio has a real multichannel bridge; the graph adapter hard-stubs `wrapper_load_buffer(...) { return -1; }` everywhere else.

Routing by goal instead: multichannel sample playback in a shipping plugin -> use the genlib/export path (WebAudio already does it). Multichannel / wavetable *synthesis* inside the graph frontend -> the only self-contained win is small (`Buffer.channels` plus a 2D/bilinear lookup node, filled procedurally, no Manifest / IR / platform changes). Otherwise -> defer.

### Tier 3 -- breaks the pure-DAG invariant (expensive, mostly out of scope)

Loops, `if/for/while`, local functions, and FFT/complex cannot be node-graph dataflow. Two options, the first not recommended:

1. Rebuild the IR to a control-flow graph, or let nodes contain sub-blocks. This contaminates `toposort`, `simulate`, `optimize`, and the differential harness, all of which assume acyclic scalar dataflow. High cost, high blast radius -- justified only if authoring in the graph frontend becomes a real goal, which it is not under the current project purpose.
2. An escape-hatch node: `RawCodebox` / `RawExpr` holding literal GenExpr (and/or literal C++) with declared input refs and output ids. The transpiler emits it verbatim; `compile/nodes.py` inlines it; `validate` checks only the I/O wiring; `simulate` and `optimize` treat it as opaque, and `transpile_eval` skips it exactly as it skips `NON_DETERMINISTIC_OPS` for `noise`. This unblocks loops, functions, and FFT without touching the IR for the graphs that do not need them. The price is honest and bounded: a raw node is a black box to the optimizer and the differential harness.

FFT as first-class high-level nodes is separately large because the standalone C++ path has no genlib FFT to lean on; it would mean shipping an FFT implementation across backends. Worth it only with concrete spectral demand.

## Recommendation

```
Done:      Tier 1 operators (bitwise, train, interp linear/cosine, nearest) -> shipped, full suite green
Deferred:  rate (ambiguous gen~ semantics) and 4-point cubic/spline interp
Do next:   RawCodebox escape-hatch node -> unblocks loops/functions/FFT without IR damage
Rejected:  multichannel + host buffers for the graph path -> duplicates the genlib path (spike finding)
Maybe:     small 2D/bilinear lookup node -> only if graph-frontend wavetable synthesis is wanted
Don't:     rebuild IR for native control flow -> wrong cost/scope for a backend-testing tool
```

Tier 1 plus the `RawCodebox` escape hatch reaches the actual goal (representative backend coverage, with an outlet for everything else) at a fraction of the cost of Tier 3.
