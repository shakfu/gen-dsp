# GDSP DSL Specification

A line-oriented DSL for defining DSP graphs that compiles to `gen_dsp.graph.Graph` objects. Parsed by pure Python (no external dependencies). File extension: `.gdsp`.

## Design Principles

1. **Pure Python parser** -- tokenizer + recursive descent, stdlib only.
2. **1:1 mapping to Graph** -- every construct compiles to exactly one (or a small fixed number of) graph node(s). No hidden magic.
3. **Familiar to DSP practitioners** -- borrows from Gen~ codebox, Faust, and SuperCollider idioms.
4. **Concise but unambiguous** -- eliminate boilerplate without introducing ambiguity.

## Node Type Inference

GDSP has no type annotations. Every node's type is inferred from how it is written:

- **Operators** desugar to typed nodes: `a + b` produces `BinOp(op="add")`, `a > b` produces `Compare(op="gt")`, `-x` produces `UnaryOp(op="neg")`.
- **Function names determine node types.** `onepole(x, 0.5)` produces an `OnePole` node, `sinosc(440)` produces a `SinOsc` node, `sin(x)` produces `UnaryOp(op="sin")`. The function name *is* the type -- there is a fixed mapping from DSL function names to graph node types (see [Function Calls](#function-calls) below).
- **Subgraph calls use the same syntax as builtins.** If a function name matches a `graph` definition in the same file, it produces a `Subgraph` node; if it matches a builtin DSP function, it produces the corresponding node type. The parser treats both identically -- the compiler disambiguates via deferred resolution.

This means `y = onepole(x, coeff)` and `y = my_filter(input=x)` look the same syntactically. The compiler resolves `onepole` to the builtin `OnePole` node type, and `my_filter` to a `Subgraph` referencing `graph my_filter { ... }` if defined in the file.

## Example

```gdsp
graph fm_synth (sr=44100) {
    out output = result

    param freq  20..20000 = 440
    param depth 0..1000   = 200
    param gate  0..1      = 0

    buffer sine_tbl 512 fill=sine

    mod_phase = phasor(freq * 2.0)
    mod       = sin(mod_phase) * depth
    phase     = phasor(freq) + mod / sr
    carrier   = cycle(sine_tbl, phase)
    env       = adsr(gate, 10, 100, 0.7, 200)
    result    = carrier * env
}
```

Equivalent Python (~30 lines of Pydantic constructors) compresses to 13 lines of DSL.

---

## Syntax Reference

### File Structure

A `.gdsp` file contains one or more `graph` definitions. Comments start with `#` and extend to end of line. Statements are newline-delimited; semicolons allowed as alternative separators.

```gdsp
# Top-level: one or more graph definitions
graph name (...) { ... }
graph name2 (...) { ... }
```

### Graph Definition

```gdsp
graph NAME [(options)] {
    statements...
}
```

Options (all optional):

- `sr=NUMBER` -- sample rate (default 44100). Makes `sr` available as an implicit `SampleRate` node inside the graph body.
- `control=NUMBER` -- control interval in samples (default 0 = disabled).

#### Numeric Precision

All numeric values (parameters, constants, intermediate results) compile to 32-bit `float` in the generated C++. This matches gen-dsp's `GENLIB_USE_FLOAT32` convention used across all platform backends. The DSL itself is precision-agnostic -- a future `precision=double` graph option may allow 64-bit output for backends that support it.

### Audio I/O

```gdsp
in in1, in2              # declare audio inputs (omit entirely for generators)
out output = source_node # declare audio output: output_name = source_node_id
out left = mix_l         # multiple out statements allowed
out right = mix_r
```

Omitting `in` entirely (no `in` statement) produces a generator/instrument (0 audio inputs).

### Parameters

```gdsp
         param NAME MIN..MAX = DEFAULT   # standard parameter
@control param NAME MIN..MAX = DEFAULT   # marked as control-rate node
```

- `MIN..MAX` defines the range (floats or ints).
- `DEFAULT` is clamped to `[MIN, MAX]`.
- `@control` prefix adds the parameter to the graph's `control_nodes` list.

Parameters are referenced by name in expressions, occupying the same namespace as node IDs and audio input IDs.

### Resources

Resources are stateful objects (memory) referenced by name in read/write operations.

```gdsp
buffer NAME SIZE [fill=zeros|sine]   # Buffer node (default fill=zeros)
delay NAME MAX_SAMPLES               # DelayLine node
```

### History (Feedback)

Single-sample feedback loops use `history` declarations and `<-` write arrows:

```gdsp
history fb = 0.0           # declare with initial value
y = in1 + fb * 0.99        # read: use the name directly
fb <- y                    # write: sets value for next sample
```

Compiles to `History(id="fb", init=0.0, input="y")`. The `<-` write must appear exactly once per declared history. Reads of the history name resolve to the History node's output (previous sample's written value).

### Assignments

```gdsp
         NAME = expr       # assign expression result to a named node
@control NAME = expr       # assign + mark as control-rate
```

The left-hand side becomes the node's `id`. If the expression is a single function call, the node gets the assigned name directly. If it's a compound expression (e.g. `a * b + c`), intermediate nodes get auto-generated IDs (`_mul_0`, `_add_0`, etc.) and the final result gets the assigned name.

### Destructuring Assignment

For multi-output nodes (`gate_route`):

```gdsp
a, b, c = gate_route(signal, index, 3)
```

Compiles to:

- `GateRoute(id="_gate_0", a="signal", index="index", count=3)`
- `GateOut(id="a", gate="_gate_0", channel=1)`
- `GateOut(id="b", gate="_gate_0", channel=2)`
- `GateOut(id="c", gate="_gate_0", channel=3)`

The number of names on the left must equal the `count` argument.

### Delay Operations

```gdsp
delay_write NAME (value_expr)                        # statement (no assignment)
tap = delay_read NAME (tap_expr)                     # expression
tap = delay_read NAME (tap_expr, interp=linear)      # with interpolation
tap = delay_read NAME (tap_expr, interp=cubic)
```

`delay_write` is a statement, not an expression -- it produces a `DelayWrite` node but has no output to assign. `delay_read` is an expression that produces a `DelayRead` node.

### Buffer Operations

Buffer reads are expressions via function calls:

```gdsp
buffer tbl 512 fill=sine

val = cycle(tbl, phase)                    # wavetable [0,1) phase, wraps
val = wave(tbl, phase)                     # wavetable [-1,1] phase
val = lookup(tbl, index)                   # [0,1] index, clamped
val = buf_read(tbl, index)                 # raw sample index
val = buf_read(tbl, index, interp=linear)  # interpolated
sz  = buf_size(tbl)                        # buffer size
```

Buffer writes are statements:

```gdsp
buf_write(tbl, index, value)    # overwrite
splat(tbl, index, value)        # overdub (add to existing)
```

### Control Rate

```gdsp
graph synth (sr=48000, control=64) {
    @control param freq 20..20000 = 440
    @control smooth_freq = smooth(freq, 0.999)   # runs at control rate
             phase = phasor(smooth_freq)          # no annotation = audio rate
}
```

The `@control` prefix on params or assignments adds the node ID to `Graph.control_nodes`. The `control=N` option in the graph header sets `Graph.control_interval`.

---

## Expression Language

### Infix Operators

Standard arithmetic and comparison operators desugar to `BinOp` / `Compare` nodes.

| Operator | Precedence | Node | Associativity |
|----------|-----------|------|---------------|
| `**` | 6 (highest) | `BinOp(op="pow")` | right |
| `-x` (unary) | 5 | `UnaryOp(op="neg")` | right |
| `* / %` | 4 | `BinOp(op="mul/div/mod")` | left |
| `+ -` | 3 | `BinOp(op="add/sub")` | left |
| `> < >= <= == !=` | 2 | `Compare(op="gt/lt/gte/lte/eq/neq")` | non-assoc |
| `>> //` | 1 (lowest) | `series()` / `parallel()` | left |

Parentheses for grouping: `(a + b) * c`.

### Function Calls

Function-call syntax maps to node constructors -- the function name determines the node type (see [Node Type Inference](#node-type-inference) above). Positional args fill fields in declaration order; keyword args fill by name.

**Unary math** (all `UnaryOp` variants):

```text
sin(x)  cos(x)  tan(x)  tanh(x)  sinh(x)  cosh(x)
asin(x) acos(x) atan(x) asinh(x) acosh(x) atanh(x)
exp(x)  exp2(x) log(x)  log2(x)  log10(x)
abs(x)  sqrt(x) neg(x)  sign(x)
floor(x) ceil(x) round(x) trunc(x) fract(x)
not(x)  bool(x)
mtof(x) ftom(x) atodb(x) dbtoa(x)
phasewrap(x) degrees(x) radians(x)
mstosamps(x) sampstoms(x) t60(x) t60time(x)
fixdenorm(x) fixnan(x) isdenorm(x) isnan(x)
fastsin(x) fastcos(x) fasttan(x) fastexp(x) fastpow(a, b)
```

Note: `fastpow(a, b)` is a `BinOp(op="fastpow")`, not unary.

**Binary math** (additional `BinOp` variants not covered by infix):

```text
min(a, b)     max(a, b)     atan2(a, b)
hypot(a, b)   absdiff(a, b) step(a, b)
and(a, b)     or(a, b)      xor(a, b)
```

**Oscillators**:

```text
phasor(freq)                  # 0..1 ramp
sinosc(freq)                  # sine wave
triosc(freq)                  # triangle wave
sawosc(freq)                  # sawtooth wave
pulseosc(freq, width)         # pulse wave
noise()                       # white noise
```

**Filters**:

```text
onepole(input, coeff)
svf(input, freq, q, mode=lp)           # mode: lp|hp|bp|notch
biquad(input, b0, b1, b2, a1, a2)
dcblock(input)
allpass(input, coeff)
```

**Range / shaping**:

```text
clamp(x, lo, hi)              # default lo=0 hi=1
wrap(x, lo, hi)
fold(x, lo, hi)
scale(x, in_lo, in_hi, out_lo, out_hi)
mix(a, b, t)                  # linear interpolate
smoothstep(x, edge0, edge1)
```

**Control / dynamics**:

```text
smooth(x, coeff)              # one-pole parameter smoother
slide(x, up, down)            # slew limiter
adsr(gate, attack, decay, sustain, release)   # times in ms
select(cond, a, b)            # cond != 0 ? a : b
```

**State**:

```text
delta(x)                      # difference from previous sample
change(x)                     # 1 when value changes, else 0
sample_hold(x, trig)
latch(x, trig)
accum(incr, reset)
counter(trig, max)
elapsed()                     # sample counter
rate_div(x, divisor)
```

**Routing**:

```text
gate_route(signal, index, count)    # 1-to-N demux (use with destructuring)
gate_out(gate_node, channel)        # read one lane (explicit style)
selector(index, a, b, ...)         # N-to-1 mux, variadic, 1-based index
pass(x)                            # identity
```

### Named Constants

Bare keywords (no parentheses):

```text
pi  e  twopi  halfpi  invpi
degtorad  radtodeg
sqrt2  sqrt1_2
ln2  ln10  log2e  log10e  phi
```

### Implicit `sr`

If the graph header declares `sr=N`, the identifier `sr` is available in expressions as an implicit `SampleRate` node. If the graph header omits `sr`, using `sr` in an expression is an error -- use `samplerate()` explicitly instead.

```gdsp
graph with_sr (sr=48000) {
    out o = x
    x = phasor(440.0 / sr)     # OK: sr is implicit SampleRate node
}

graph without_sr {
    out o = x
    rate = samplerate()        # explicit SampleRate node
    x = phasor(440.0 / rate)
}
```

---

## Multi-Graph Files and Subgraphs

A `.gdsp` file may contain multiple `graph` definitions. Graphs defined in the same file are in scope and can be instantiated as subgraphs using ordinary function-call syntax -- no `import` keyword needed.

### In-Source Subgraphs

Calling a graph name like a function instantiates it as a `Subgraph` node. Arguments are keyword-only, mapping the subgraph's audio input and parameter names to expressions in the calling graph.

```gdsp
graph allpass_section {
    in input
    out output = y

    param coeff 0..1 = 0.7
    delay dly 4410

    history state = 0.0
    delay_write dly (input + state * coeff)
    tap = delay_read dly (4410)
    y = tap - input * coeff
    state <- y
}

graph reverb {
    in input
    out output = wet_mix

    param decay 0.1..10 = 2.5
    param mix   0..1    = 0.3

    # Instantiate subgraph -- same syntax as any function call
    ap1 = allpass_section(input=input, coeff=0.7)
    ap2 = allpass_section(input=ap1, coeff=0.7)
    ap3 = allpass_section(input=ap2, coeff=0.5)

    dry = input * (1 - mix)
    wet = ap3 * mix
    wet_mix = dry + wet
}
```

The compiler resolves function calls using deferred resolution: if the callee name matches a graph defined in the file, it emits a `Subgraph` node; if it matches a built-in DSP function, it emits the corresponding node type; otherwise it's an error. This keeps the parser context-free.

Compiles to:

```python
Subgraph(
    id="ap1",
    graph=allpass_section_graph,
    inputs={"input": "input"},
    params={"coeff": 0.7},
    output="output",
)
```

### Multi-Output Subgraphs

Dot notation accesses individual outputs of a subgraph with multiple `out` declarations:

```gdsp
graph stereo_processor {
    in in_l, in_r
    out left = processed_l
    out right = processed_r
    ...
}

graph main {
    in in_l, in_r
    out out_l = stereo.left
    out out_r = stereo.right

    stereo = stereo_processor(in_l=in_l, in_r=in_r)
}
```

### External File Imports

The `import` keyword is reserved for referencing graphs defined in other `.gdsp` files:

```gdsp
graph main {
    in input
    out output = processed

    # Import from external file (colon separates file path from graph name)
    processed = import "filters.gdsp":bandpass(input=input, freq=1000)
}
```

- `"file.gdsp":GRAPH_NAME` -- the file path is a string literal, the graph name follows after `:`.
- If the file contains only one graph, the graph name can be omitted: `import "filter.gdsp"(input=x)`.
- Resolution: relative to the importing file's directory (TBD: search path rules).

---

## Inline Composition

Series (`>>`), parallel (`//`), `split()`, and `merge()` are expression-level operators that wire graphs together. They operate on partially-applied graph calls -- graph references with keyword arguments bound but audio inputs left unbound. No separate `compose` block is needed; composition happens inline within any graph body.

### Partially-Applied Graph Calls

A graph reference with keyword arguments (params or audio inputs) but no positional audio wiring produces a partially-applied graph. The `>>` and `//` operators connect these by positional I/O matching.

```gdsp
graph lpf {
    in input
    out output = filtered
    param coeff 0..1 = 0.3
    filtered = onepole(input, coeff)
}

graph hpf {
    in input
    out output = filtered
    param coeff 0..1 = 0.7
    filtered = input - onepole(input, coeff)
}

graph main {
    in input
    out output = processed

    # Series: lpf's output feeds hpf's input
    #
    #   input --> [lpf(coeff=0.2)] --> [hpf(coeff=0.8)] --> output
    #
    processed = lpf(coeff=0.2) >> hpf(coeff=0.8)
}
```

When `>>` appears in an assignment, the first graph's unbound audio inputs become the composed expression's inputs (wired from the calling graph's namespace), and the last graph's outputs become the result. Parameters are bound at each call site.

### Parallel

Parallel (`//`) places graphs side by side. Inputs and outputs are concatenated.

```gdsp
graph delay_fx {
    in input
    out output = delayed
    param time 1..2000 = 500
    delay dly 96000
    delay_write dly (input)
    delayed = delay_read dly (mstosamps(time), interp=linear)
}

graph distortion {
    in input
    out output = dist
    param drive 0..10 = 3.0
    dist = tanh(input * drive)
}

graph main {
    in in_l, in_r
    out out_l = fx.delay_fx_output
    out out_r = fx.distortion_output

    # Parallel: independent, side by side (2 ins, 2 outs)
    #
    #   in_l --> [delay_fx(time=500)]    --> out_l
    #   in_r --> [distortion(drive=3.0)] --> out_r
    #
    fx = delay_fx(time=500) // distortion(drive=3.0)
}
```

### Split and Merge

`split()` and `merge()` are functions that work on composition expressions for fan-out and fan-in patterns.

```gdsp
graph main {
    in input
    out output = mixed

    # Split mono input to feed both effects, then merge outputs
    #
    #              +--> [delay_fx]    --+
    #   input ---->|                    |--> sum --> output
    #              +--> [distortion] --+
    #
    effects = delay_fx(time=300) // distortion(drive=2.0)
    mixed = split(input, effects) >> merge(effects, mono_sum)
}
```

- `split(source, target)` -- distributes source's outputs cyclically across target's inputs.
- `merge(source, target)` -- sums groups of source's outputs into target's inputs.

### Chaining

Composition operators can be chained freely in expressions:

```gdsp
graph main {
    in input
    out output = result

    # Three-stage series
    result = lpf(coeff=0.2) >> hpf(coeff=0.8) >> gain(level=0.5)
}
```

### Operator Reference

| Operator | Semantics | Resulting I/O | Constraint |
|----------|-----------|--------------|-----------|
| `a >> b` | a's outputs feed b's inputs | ins=a.ins, outs=b.outs | `len(a.outputs) == len(b.inputs)` |
| `a // b` | independent, side by side | ins=a.ins+b.ins, outs=a.outs+b.outs | none |
| `split(a, b)` | a's outs distributed cyclically to b's ins | ins=a.ins, outs=b.outs | `len(b.inputs) % len(a.outputs) == 0` |
| `merge(a, b)` | groups of a's outs summed into b's ins | ins=a.ins, outs=b.outs | `len(a.outputs) % len(b.inputs) == 0` |

---

## Grammar (EBNF)

```ebnf
file         = graph_def+ ;

graph_def    = "graph" IDENT [ "(" option_list ")" ] "{" stmt_list "}" ;

option_list  = option ( "," option )* ;
option       = IDENT "=" value ;

stmt_list    = ( stmt ( NEWLINE | ";" ) )* ;
stmt         = in_decl | out_decl | param_decl | resource_decl
             | history_decl | feedback_write | delay_write_stmt
             | buf_write_stmt | assignment | import_assign ;

in_decl      = "in" IDENT ( "," IDENT )* ;
out_decl     = "out" IDENT "=" ref ;
param_decl   = [ "@control" ] "param" IDENT NUMBER ".." NUMBER "=" NUMBER ;
resource_decl = ( "buffer" IDENT NUMBER ( key_val )* )
              | ( "delay" IDENT NUMBER ) ;
key_val      = IDENT "=" IDENT ;
history_decl = "history" IDENT "=" NUMBER ;
feedback_write = IDENT "<-" expr ;
delay_write_stmt = "delay_write" IDENT "(" expr ")" ;
buf_write_stmt = ( "buf_write" | "splat" ) "(" IDENT "," expr "," expr ")" ;

(* External file import *)
import_assign = IDENT "=" "import" STRING [ ":" IDENT ] "(" [ arg_list ] ")" ;

(* Assignment -- includes in-source subgraph calls via deferred resolution *)
(* Destructuring: a, b, c = gate_route(...) *)
assignment   = [ "@control" ] ident_list "=" expr ;
ident_list   = IDENT ( "," IDENT )* ;

(* Expressions -- composition operators >> and // at lowest precedence *)
expr         = composition ;
composition  = comparison ( ( ">>" | "//" ) comparison )* ;
comparison   = addition ( ( ">" | "<" | ">=" | "<=" | "==" | "!=" ) addition )? ;
addition     = multiply ( ( "+" | "-" ) multiply )* ;
multiply     = power ( ( "*" | "/" | "%" ) power )* ;
power        = unary ( "**" power )? ;
unary        = "-" unary | postfix ;
postfix      = atom ( "." IDENT )* ;
atom         = NUMBER | IDENT | func_call | "(" expr ")" ;
func_call    = IDENT "(" [ arg_list ] ")" ;
arg_list     = arg ( "," arg )* ;
arg          = expr | IDENT "=" ( expr | IDENT ) ;

(* Tokens *)
NUMBER       = [0-9]+ ( "." [0-9]+ )? ;
IDENT        = [a-zA-Z_] [a-zA-Z0-9_]* ;
STRING       = '"' [^"]* '"' ;
NEWLINE      = "\n" ;
```

---

## Compilation Pipeline

```text
.gdsp source
  |
  v
Tokenizer (pure Python, yields Token stream)
  |
  v
Parser (recursive descent, produces AST)
  |
  v
Compiler (AST -> gen_dsp.graph.Graph)
  |  - collects graph names (first pass)
  |  - resolves function calls: graph name -> Subgraph, builtin -> node type
  |  - resolves >> and // operators into series()/parallel() algebra calls
  |  - resolves implicit sr
  |  - generates auto-IDs for intermediate nodes
  |  - expands destructuring into GateRoute + GateOut
  |  - resolves external imports (file I/O)
  |  - validates references (undefined names, duplicate IDs)
  v
Graph object (ready for compile_graph / platform backends)
```

### API

```python
from gen_dsp.graph.dsl import parse, parse_file

# Parse a string
graph = parse("""
graph gain {
    in input
    out output = scaled
    param gain 0..1 = 0.5
    scaled = input * gain
}
""")

# Parse a file
graph = parse_file("synth.gdsp")

# Parse a multi-graph file -- returns dict
graphs = parse_file("library.gdsp", multi=True)
# {"allpass_section": Graph(...), "reverb": Graph(...)}

# All graphs in the file
graphs = parse_file("library.gdsp", multi=True)
# {"lpf": Graph(...), "hpf": Graph(...), "main": Graph(...)}
```

---

## Full Example: Feedback Delay with Filtering

```gdsp
graph fbdelay (sr=48000) {
    in input
    out output = wet_mix

    param time    1..2000   = 500    # delay time in ms
    param feedback 0..0.99  = 0.6
    param tone     0..1     = 0.3    # lowpass on feedback
    param mix      0..1     = 0.5

    delay dly 96000
    history fb_state = 0.0

    # Convert ms to samples
    time_samps = mstosamps(time)

    # Read from delay line
    tap = delay_read dly (time_samps, interp=linear)

    # Filter the feedback
    fb_filtered = onepole(tap, tone)

    # Write input + filtered feedback into delay
    delay_write dly (input + fb_filtered * feedback)

    # Crossfade dry/wet
    dry = input * (1 - mix)
    wet = tap * mix
    wet_mix = dry + wet
}
```

## Full Example: Polyphonic Subgraph Reuse

```gdsp
graph voice {
    in gate_in
    out output = out_signal

    param freq 20..20000 = 440
    param attack 1..5000 = 10
    param release 1..5000 = 200

    env = adsr(gate_in, attack, 50, 0.8, release)
    osc = sawosc(freq)
    out_signal = osc * env
}

graph poly_synth {
    out output = mixed

    param freq1 20..20000 = 440
    param freq2 20..20000 = 550
    param gate  0..1      = 0

    v1 = voice(gate_in=gate, freq=freq1)
    v2 = voice(gate_in=gate, freq=freq2)

    mixed = (v1 + v2) * 0.5
}
```

## Full Example: Signal Router with Destructuring

```gdsp
graph router {
    in input
    out out1 = clean
    out out2 = distorted
    out out3 = filtered

    param route 0..3 = 1

    a, b, c = gate_route(input, route, 3)

    clean     = a
    distorted = tanh(b * 3.0)
    filtered  = onepole(c, 0.2)
}
```
