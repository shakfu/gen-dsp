# gen_dsp.graph API Reference

Public API for the `gen_dsp.graph` subpackage. Requires `pip install gen-dsp[graph]` (pydantic).
Simulation functions additionally require `pip install gen-dsp[sim]` (numpy).

All symbols are importable from `gen_dsp.graph` unless otherwise noted.

---

## DSL Parsing

### `parse(source, *, filename="<string>") -> Graph`

Parse a `.gdsp` source string and return a single `Graph`.

If *source* contains multiple `graph` blocks, returns the **last** one (which typically uses the
earlier ones as named subgraphs). Raises `GDSPSyntaxError` on tokenizer/parser errors and
`GDSPCompileError` on semantic errors (e.g. unresolved identifiers, recursive graph calls).

```python
from gen_dsp.graph import parse

graph = parse("""
graph lowpass {
    in x
    out y = onepole(x, coeff=0.9)
}
""")
```

### `parse_multi(source, *, filename="<string>") -> dict[str, Graph]`

Parse a `.gdsp` source string and return **all** graphs as `{name: Graph}`. Use this when you
need access to library subgraphs defined in the same file.

### `parse_file(path, *, multi=False) -> Graph | dict[str, Graph]`

Parse a `.gdsp` file. Equivalent to `parse(path.read_text())` or `parse_multi(...)` when
`multi=True`. Passes the filename to error messages.

### `class GDSPSyntaxError(Exception)`

Raised by the tokenizer and parser for structural errors (unknown tokens, mismatched braces,
unexpected EOF). Attributes: `line: int`, `col: int`, `filename: str`. The `str()` representation
includes the source location: `"<file>:<line>:<col>: <message>"`.

### `class GDSPCompileError(Exception)`

Raised by the compiler for semantic errors (undefined ID, recursive graph reference, wrong number
of arguments, etc.). Same attributes as `GDSPSyntaxError`.

---

## Validation

### `validate_graph(graph, *, warn_unmapped_params=False) -> list[GraphValidationError]`

Validate a `Graph` and return a list of errors. An empty list means the graph is valid.

Before validation, subgraphs are expanded inline via `expand_subgraphs()`.

Checks performed:

1. **Unique IDs** -- no duplicate node IDs; no node ID collides with an audio input or param name.
2. **Reference resolution** -- every string field that refers to another node resolves to a known ID.
3. **Output sources** -- every `AudioOutput.source` references an existing node.
4. **Delay consistency** -- `DelayRead.delay` and `DelayWrite.delay` reference an existing `DelayLine`.
5. **Buffer consistency** -- `BufRead`, `BufWrite`, `BufSize`, `Splat`, `Cycle`, `Wave`, `Lookup`
   reference an existing `Buffer`.
6. **Gate consistency** -- `GateOut.gate` references an existing `GateRoute`; channel is in range.
7. **Control-rate consistency** -- nodes listed in `control_nodes` exist; they must not depend on
   audio inputs or audio-rate nodes.
8. **No pure cycles** -- topological sort on non-feedback edges must succeed.

When `warn_unmapped_params=True`, warnings for subgraph params that fall back to defaults are
appended after all errors.

### `class GraphValidationError(str)`

A structured validation error that behaves as a plain string. Subclasses `str` so existing call
sites (`errors == []`, `"; ".join(errors)`, `print(err)`) work unchanged.

**Constructor:**

```python
GraphValidationError(
    kind: str,
    message: str,
    *,
    node_id: str | None = None,
    field_name: str | None = None,
    severity: str = "error",   # "error" | "warning"
)
```

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `kind` | `str` | Machine-readable error category (see below) |
| `node_id` | `str \| None` | ID of the offending node, if applicable |
| `field_name` | `str \| None` | Name of the offending field, if applicable |
| `severity` | `str` | `"error"` or `"warning"` |

**`kind` values:**

| `kind` | `severity` | Meaning |
|--------|-----------|---------|
| `"duplicate_id"` | error | Two nodes share the same ID |
| `"id_collision"` | error | A node ID equals an audio input ID or param name |
| `"dangling_ref"` | error | A field references an ID that does not exist |
| `"bad_output_source"` | error | `AudioOutput.source` does not reference a node |
| `"missing_delay_line"` | error | `DelayRead`/`DelayWrite` references a non-existent `DelayLine` |
| `"missing_buffer"` | error | A buffer consumer references a non-existent `Buffer` |
| `"missing_gate_route"` | error | `GateOut.gate` references a non-existent `GateRoute` |
| `"gate_channel_range"` | error | `GateOut.channel` is outside `[1, gate_route.count]` |
| `"invalid_control_node"` | error | An ID in `control_nodes` is not a node ID |
| `"control_audio_dep"` | error | A control-rate node depends on an audio input |
| `"control_rate_dep"` | error | A control-rate node depends on an audio-rate node |
| `"cycle"` | error | Graph contains a pure cycle (not through `History` or delay) |
| `"expansion_error"` | error | `expand_subgraphs()` raised (malformed `Subgraph` node) |
| `"unmapped_param"` | warning | A subgraph param uses its default (only with `warn_unmapped_params=True`) |

**Usage example** (structured access for a UI):

```python
errors = validate_graph(graph)
for err in errors:
    if err.node_id:
        highlight_node(err.node_id, severity=err.severity, kind=err.kind)
    print(str(err))   # plain-text message with context
```

---

## Compilation

### `compile_graph(graph) -> str`

Compile a `Graph` to a standalone C++ source string. Raises `ValueError` if the graph fails
validation or contains IDs that are not valid C identifiers.

The output is a self-contained `.cpp` file (no genlib dependency) with:

- State struct `{Name}State`
- `create(sr)` / `destroy(self)` / `reset(self)` lifecycle functions
- `perform(self, ins, outs, n)` sample-processing loop
- Param introspection: `num_params`, `param_name`, `param_min`, `param_max`, `set_param`, `get_param`
- Buffer introspection: `num_buffers`, `buffer_name`, `buffer_size`, `get_buffer`, `set_buffer`
- Peek introspection: `num_peeks`, `peek_name`, `get_peek`

### `compile_graph_to_file(graph, output_dir) -> Path`

Compile a `Graph` and write `{name}.cpp` to *output_dir* (created if absent). Returns the path
to the written file.

---

## Optimization

### `optimize_graph(graph) -> OptimizeResult`

Apply all optimization passes in sequence and return an `OptimizeResult(graph, stats)`.

Passes applied:

1. **Constant folding** (`constant_fold`) -- pure nodes with all-constant inputs become `Constant`.
2. **Common subexpression elimination** (`eliminate_cse`) -- duplicate pure nodes with identical
   inputs are merged into one.
3. **Dead node elimination** (`eliminate_dead_nodes`) -- nodes not reachable from any output are
   removed. Respects side-effecting writers: when a `DelayRead` or `BufRead`/`BufSize` is live,
   the `DelayWrite`/`BufWrite`/`Splat` nodes feeding the same resource are kept.

All passes return a new `Graph` (immutable). Stateful nodes (`History`, `DelayLine`, oscillators,
filters, etc.) are never constant-folded.

### `constant_fold(graph) -> Graph`

Constant folding pass only. See `optimize_graph` for description.

### `eliminate_dead_nodes(graph) -> Graph`

Dead node elimination pass only.

### `eliminate_cse(graph) -> Graph`

Common subexpression elimination pass only.

### `promote_control_rate(graph) -> Graph`

Promote audio-rate pure nodes to control-rate when all their dependencies are params, literals,
invariant nodes, or existing control-rate nodes. No-op when `graph.control_interval <= 0`.

### `class OptimizeStats(NamedTuple)`

Statistics from one `optimize_graph()` run.

| Field | Type | Description |
|-------|------|-------------|
| `constants_folded` | `int` | Nodes replaced by `Constant` |
| `cse_merges` | `int` | Duplicate nodes merged |
| `dead_nodes_removed` | `int` | Unreachable nodes removed |
| `control_rate_promoted` | `int` | Nodes promoted to control rate |

### `class OptimizeResult(NamedTuple)`

| Field | Type | Description |
|-------|------|-------------|
| `graph` | `Graph` | The optimized graph |
| `stats` | `OptimizeStats` | Per-pass statistics |

---

## Simulation

Simulation requires numpy (`pip install gen-dsp[sim]`). Import directly from the submodule:

```python
from gen_dsp.graph.simulate import simulate, SimState, SimResult
```

### `simulate(graph, inputs=None, n_samples=0, params=None, state=None, sample_rate=0.0) -> SimResult`

Simulate a `Graph` in Python and return output arrays.

| Argument | Type | Description |
|----------|------|-------------|
| `graph` | `Graph` | The graph to simulate |
| `inputs` | `dict[str, NDArray[float32]] \| None` | Audio input arrays keyed by input ID. `None` for generators. All arrays must have equal length. |
| `n_samples` | `int` | Samples to process. Inferred from `inputs` if 0. Required for generators. |
| `params` | `dict[str, float] \| None` | Parameter overrides applied before processing. |
| `state` | `SimState \| None` | Reuse existing state for streaming. Created fresh if `None`. |
| `sample_rate` | `float` | Override sample rate. Uses `graph.sample_rate` if 0. |

Returns a `SimResult` with `outputs: dict[str, NDArray[float32]]` and `state: SimState`.

### `class SimState`

Mutable simulation state. Created automatically by `simulate()`, or explicitly for direct
parameter/buffer access.

```python
state = SimState(graph, sample_rate=44100.0)
```

**Methods:**

| Method | Description |
|--------|-------------|
| `reset()` | Reset all state to initial values (params reset to defaults). |
| `set_param(name, value)` | Set a parameter. Raises `KeyError` if unknown. |
| `get_param(name) -> float` | Read a parameter. Raises `KeyError` if unknown. |
| `set_buffer(buffer_id, data)` | Set buffer contents. Data is truncated/zero-padded to buffer size. |
| `get_buffer(buffer_id) -> NDArray[float32]` | Get a copy of buffer contents. |
| `get_peek(peek_id) -> float` | Read the last value captured by a `Peek` node. |

### `class SimResult`

| Field | Type | Description |
|-------|------|-------------|
| `outputs` | `dict[str, NDArray[float32]]` | Output arrays keyed by `AudioOutput.id` |
| `state` | `SimState` | The (possibly new) simulation state |

---

## Serialization

### `graph_to_gdsp(graph) -> str`

Serialize a `Graph` back to `.gdsp` DSL source. The output round-trips through `parse()`.

Constants are inlined as numeric literals. `NamedConstant` nodes become bare identifiers (`pi`,
`e`, etc.). `History` feedback writes use the `<-` operator. Nodes are emitted in topological
order.

---

## Visualization

### `graph_to_dot(graph) -> str`

Convert a `Graph` to a Graphviz DOT string. Nodes are colored by type, feedback edges are marked
`[style=dashed]`.

### `graph_to_dot_file(graph, output_dir) -> Path`

Write `{name}.dot` to *output_dir*. If `dot` (Graphviz) is on `PATH`, also renders `{name}.pdf`.
Returns the path to the `.dot` file.

---

## Graph Algebra

FAUST-style block-diagram combinators. All return a new `Graph`; params are namespaced with the
subgraph ID prefix to avoid collisions.

### `series(a, b) -> Graph`

Pipe `a`'s outputs into `b`'s inputs positionally. Requires `len(a.outputs) == len(b.inputs)`.
Result: `inputs=a.inputs`, `outputs=b.outputs`.

Operator shorthand: `a >> b`.

### `parallel(a, b) -> Graph`

Stack graphs side by side. Inputs and outputs are concatenated; params are namespaced.

Operator shorthand: `a // b`.

### `split(a, b) -> Graph`

Fan-out: distribute `a`'s outputs cyclically across `b`'s inputs.
Requires `len(b.inputs) % len(a.outputs) == 0`.

### `merge(a, b) -> Graph`

Fan-in: group `a`'s outputs and sum them pairwise into `b`'s inputs.
Requires `len(a.outputs) % len(b.inputs) == 0`.

---

## Subgraph Expansion

### `expand_subgraphs(graph) -> Graph`

Recursively inline all `Subgraph` nodes, rewriting IDs and param bindings to avoid collisions.
Returns a flat `Graph` with no `Subgraph` nodes.

Called automatically by `compile_graph()`, `validate_graph()`, `optimize_graph()`, and
`simulate()`.

---

## Topological Sort

### `toposort(graph) -> list[Node]`

Return graph nodes in topological order using Kahn's algorithm with alphabetical tie-breaking for
determinism. Raises `ValueError` if the graph contains a pure cycle (cycles through `History` or
delay feedback edges are allowed and excluded from the sort).

---

## Platform Adapter

For generating platform-specific plugin projects from a graph (without a gen~ export).

### `generate_adapter_cpp(graph, platform) -> str`

Generate the `_ext_{platform}.cpp` adapter source that bridges the compiled graph to gen-dsp's
platform backend. *platform* must be one of `SUPPORTED_PLATFORMS`.

### `generate_manifest(graph) -> str`

Generate a `manifest.json` string compatible with gen-dsp's `Manifest` dataclass. Contains
`gen_name`, `num_inputs`, `num_outputs`, `params` (with min/max/default), and `buffers`.

### `compile_for_gen_dsp(graph, output_dir, platform) -> Path`

Convenience: compile graph and write three files to *output_dir*:

- `{name}.cpp` -- compiled C++
- `_ext_{platform}.cpp` -- platform adapter
- `manifest.json` -- gen-dsp manifest

Returns the output directory path.

### `SUPPORTED_PLATFORMS`

`set[str]` -- the set of platform keys accepted by `generate_adapter_cpp()` and
`compile_for_gen_dsp()`. Currently: `chuck`, `clap`, `au`, `vst3`, `lv2`, `sc`, `vcvrack`,
`daisy`, `circle`, `pd`, `max`.

---

## Generating Complete Plugin Projects

Use `ProjectGenerator.from_graph()` (from `gen_dsp.core.project`) to produce a fully buildable
project for any platform:

```python
from gen_dsp.graph import Graph, AudioInput, AudioOutput, BinOp, Param
from gen_dsp.core.project import ProjectConfig, ProjectGenerator

graph = Graph(
    name="gain",
    inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
    outputs=[AudioOutput(id="out1", source="g1"), AudioOutput(id="out2", source="g2")],
    params=[Param(name="gain", min=0.0, max=2.0, default=1.0)],
    nodes=[
        BinOp(id="g1", op="mul", a="in1", b="gain"),
        BinOp(id="g2", op="mul", a="in2", b="gain"),
    ],
)

config = ProjectConfig(name=graph.name, platform="clap")
gen = ProjectGenerator.from_graph(graph, config)
project_dir = gen.generate("build/gain_clap")
```

This writes all source files (compiled C++, adapter, platform templates, build files) and runs the
build by default.
