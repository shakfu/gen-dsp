# `.gdsp` and Max/MSP's gen: the relationship

Short version: `.gdsp` is **inspired by** gen~ but is **not** gen~. It is gen-dsp's own independent front-end, and it sits on the *opposite* end of the pipeline from gen~ exports. They are sibling inputs that converge on the same backend, not derivatives of each other.

## They are two separate entry points to the same pipeline

gen-dsp has two front-ends that both produce the same intermediate representation (`Manifest` / `Graph`) and feed the same 11 platform backends:

```
gen~ export dir --> parser.py --> ExportInfo --+
                                               +--> Manifest --> Platform backends
.gdsp / Graph   --> compile.py --> Graph ------+
```

- **gen~ path** is the original, zero-dependency reason the tool exists: you author a patch in Max/MSP's gen~, export the C++ (`genlib`-based) code, and gen-dsp wraps it into a buildable plugin. gen-dsp *consumes* gen's output; it never parses the gen~ patcher itself, only the exported C++.

- **`.gdsp` path** is part of the optional graph frontend. Its stated primary purpose is to **test the platform backends without needing gen~ exports**: you write a DSP graph directly and compile it to standalone C++ that has *no* genlib dependency.

The key structural fact: a `.gdsp` graph compiles to **self-contained C++**, whereas a gen~ export is genlib-dependent C++ that gen-dsp merely packages. Graph-frontend projects produce simplified build files (no `genlib.cpp`, no `json.c`, no `gen/` subdirectory).

## Linguistic relationship to gen

`.gdsp` deliberately borrows gen~ idioms but is its own language:

- The DSL doc states it "borrows from Gen~ codebox, Faust, and SuperCollider idioms".

- Many node/function names are lifted straight from gen~'s codebox vocabulary: `cycle`, `phasor`, `mstosamps`/`sampstoms`, `mtof`/`ftom`, `dbtoa`/`atodb`, `t60`, `history` with feedback, `delay`/`delay_read`/`delay_write`, `gate`/`selector`, `clamp`/`wrap`/`fold`/ `scale`, `fixdenorm`/`fixnan`. If you know gen~ codebox, the function set is immediately familiar.

- The `history NAME = init` declaration with a `<-` write arrow is a direct analog of gen~'s `History` single-sample feedback operator.

But it diverges in important ways -- it is **not** gen~ syntax:

- It is a line-oriented, newline-delimited language with explicit `graph { ... }` blocks, and `in`/`out`/`param`/`buffer`/`delay` declarations -- closer to a Faust/SC-style textual graph than gen~'s codebox C-like syntax.

- It adds constructs gen~ codebox does not have: typed `param NAME MIN..MAX = DEFAULT` declarations, first-class **subgraphs** (call a `graph` like a function), and **composition algebra operators** `>>` (series) and `//` (parallel). (`split`/`merge` exist in the Python algebra module but are not callable from `.gdsp` source -- see implementation status below.)

- Node types are **inferred from function names** with a fixed name->node-type mapping, rather than gen~'s operator-object model.

## Summary

| | gen~ (Max/MSP) | `.gdsp` |
|---|---|---|
| Role in gen-dsp | upstream source you export *from* | native front-end you author *in* |
| What gen-dsp sees | exported genlib C++ (parsed by `parser.py`) | DSL text -> `Graph` (compiled by `dsl.py`) |
| Output C++ | genlib-dependent | standalone, no genlib |
| Dependency | zero-dependency core path | optional (`pip install gen-dsp[graph]`, needs pydantic) |
| Language lineage | proprietary Cycling '74 gen | original; borrows gen~ + Faust + SC idioms |

`.gdsp` is best understood as a **gen-flavored re-implementation of the same DSP vocabulary**, built so gen-dsp can exercise and demonstrate its backends independently of Cycling '74's toolchain -- explicitly "not intended to replace gen~, but may evolve into a useful frontend in its own right".

## Implementation status (verified against `src/gen_dsp/graph/dsl/`)

The DSL spec in `dsl.md` is almost entirely implemented. Two documented features are **aspirational / not callable from `.gdsp` source** and are flagged inline in `dsl.md` with "not yet implemented" markers:

- **External file imports** (`import "file.gdsp":graph_name(...)`) -- the grammar reserves and parses the syntax, but the compiler deliberately rejects it (`lower.py`), directing users to compose graphs via the Python `algebra` API. No cross-file resolver or cycle detection exists.

- **`split()` / `merge()` composition functions** -- documented with full semantics, but there is no DSL language support; they exist only in `gen_dsp.graph.algebra` (Python API).

One documented nuance to note:

- **`@control` on a `param`** is a no-op (parameters are not nodes, so they cannot join `control_nodes`). Only `@control` on an *assignment* adds the node to `Graph.control_nodes`.

Everything else in the spec is implemented and tested, including `sr`/`control` graph options, implicit `sr`, `in`/`out`/multi-`out`, range-clamped `param`, `buffer`/`delay`, `history` with `<-`, destructuring `gate_route`, `delay_read`/`delay_write` (with `interp`), buffer ops, the full operator set including `>>` (series) and `//` (parallel), function-name node-type inference, named constants, in-source subgraphs, multi-output dot notation (`stereo.left`), and the `parse` / `parse_file(..., multi=True)` API. </content>
