# gen_dsp.graph Operator Coverage vs gen~ Operators

This document compares the operators available in `gen_dsp.graph` against the
operators documented in the [gen~ operator reference](https://docs.cycling74.com/userguide/gen/gen~_operators)
and [gen common operator reference](https://docs.cycling74.com/userguide/gen/gen_common_operators).

Last updated: 2026-02-28

## Summary

| Category | gen~ Total | Implemented | Coverage |
|----------|-----------|-------------|----------|
| Math / Arithmetic | 12 | 12 | 100% |
| Comparison | 15 | 15 | 100% |
| Logic | 5 | 5 | 100% |
| Trigonometry | 19 | 19 | 100% |
| Powers | 9 | 9 | 100% |
| Numeric | 7 | 7 | 100% |
| Constants | 17 | 15 | 88% |
| Range | 4 | 4 | 100% |
| Route / Mixing | 7 | 5 | 71% |
| Filter | 8 | 7 | 88% |
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
| **Total** | **~149** | **~133** | **~89%** |

Note: Some gen~ operators have aliases (e.g. `ln`/`log`, `clip`/`clamp`). Each
unique function is counted once. The "p" comparison variants (`eqp`, `gtp`, etc.)
are counted as separate operators since they have distinct semantics (return
value vs return 1/0).

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

**Missing**: `send`/`receive` (named signal buses). These are a graph-level
wiring abstraction -- in the graph frontend, nodes reference each other by ID,
which serves the same purpose.

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
| `interp` | -- | Functionally equivalent to `Mix` |

**Missing**: `interp` (functionally equivalent to `Mix`).

### Waveform / Oscillators

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `noise` | `Noise` | |
| `phasor` | `Phasor` | |
| `train` | `PulseOsc` | Pulse train |
| `triangle` | `TriOsc` | |
| `rate` | -- | Phase rate-scaling (composable) |

Note: gen_dsp.graph also provides `SinOsc` and `SawOsc` which are not direct
gen~ operators (gen~ uses `cycle` for sine lookup and manual phasor+math for
saw). The `rate` operator is phase multiplication, trivially expressed as
`BinOp("mul")`.

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
| `nearest` | -- | `BufRead(interp="none")` |
| `sample` | -- | `BufRead(interp="linear")` |

**Missing**: `buffer` (external buffer~ references are out of scope),
`channels` (no multi-channel buffer support). `nearest` and `sample` are
aliases for `BufRead` with different interpolation modes.

### Convert

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `atodb` | `UnaryOp("atodb")` | 20 * log10(a) |
| `dbtoa` | `UnaryOp("dbtoa")` | pow(10, a/20) |
| `ftom` | `UnaryOp("ftom")` | 69 + 12*log2(a/440) |
| `mtof` | `UnaryOp("mtof")` | 440 * pow(2, (a-69)/12) |
| `mstosamps` | `UnaryOp("mstosamps")` | a * sr / 1000 (sr-dependent) |
| `sampstoms` | `UnaryOp("sampstoms")` | a * 1000 / sr (sr-dependent) |

**Full coverage.** Note: `mstosamps`, `sampstoms` are sample-rate dependent
and cannot be constant-folded.

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

**Not implemented.** FFT processing (pfft~) is out of scope for the graph
frontend.

### Global / Environment

| gen~ Operator | gen_dsp.graph | Notes |
|--------------|---------------|-------|
| `elapsed` | `Elapsed` | Sample counter |
| `mc_channel` | -- | MC channel index |
| `mc_channelcount` | -- | MC channel count |
| `voice` | -- | Poly voice index |
| `voicecount` | -- | Poly voice count |

**Missing**: `mc_channel`, `mc_channelcount`, `voice`, `voicecount` -- these
are Max/MSP environment queries, out of scope for the graph frontend.

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

These higher-level nodes provide convenience abstractions that would require
multiple gen~ operators to implement.

---

## Remaining Gaps

### Out of Scope

- FFT operators (`fftinfo`, `fftsize`, etc.) -- no pfft~ support
- Max/MSP environment (`voice`, `mc_channel`, etc.) -- host-specific
- `send`/`receive` -- graph wiring abstraction (nodes reference by ID)

### Trivially Composable

- `interp` -- functionally equivalent to `Mix`
- `rate` -- phase multiplication via `BinOp("mul")`
- `nearest`/`sample` -- `BufRead(interp="none"/"linear")`

### Not Yet Implemented

- `buffer` -- external buffer~ references
- `channels` -- multi-channel buffer query
- `vectorsize` -- block size constant
- `setparam` -- handled by `Subgraph.params`
- `expr` -- inline GenExpr (not applicable)
