# API Reference

gen-dsp's Python API is organized into three packages:

- **`gen_dsp.core`** -- Pipeline modules: parsing gen~ exports, building manifests, generating projects, and compiling
- **`gen_dsp.platforms`** -- Platform registry and backend implementations
- **`gen_dsp.graph`** -- Optional graph frontend (requires pydantic)

## Data Flow

```text
gen~ export dir -> parser.py -> ExportInfo -> manifest.py -> Manifest -> Platform.generate_project()
```

For the graph frontend:

```text
Graph (Python/JSON) -> compile.py -> C++ -> adapter.py -> Manifest -> ProjectGenerator.from_graph()
```

## Core Modules

| Module | Description |
|--------|-------------|
| [`parser`](parser.md) | Regex-based parser for gen~ exports, produces `ExportInfo` |
| [`manifest`](manifest.md) | `Manifest` dataclass: front-end-agnostic IR with `ParamInfo` |
| [`project`](project.md) | `ProjectGenerator`: copies export files, runs template substitution |
| [`builder`](builder.md) | `Builder` delegates to `Platform.build()`, returns `BuildResult` |
| [`patcher`](patcher.md) | Applies platform-specific fixes (e.g. `exp2f` on macOS) |
| [`cache`](cache.md) | Resolves shared FetchContent cache directory |
| [`midi`](midi.md) | MIDI mapping detection and compile-definition generation |

## Platform Registry

| Module | Description |
|--------|-------------|
| [`platforms`](platforms.md) | `Platform` base class, `PLATFORM_REGISTRY`, helper functions |

## Graph Frontend

| Module | Description |
|--------|-------------|
| [`graph.models`](graph-models.md) | Pydantic models: `Graph`, `Param`, node types |
| [`graph.compile`](graph-compile.md) | `compile_graph()`: Graph to standalone C++ |
| [`graph.validate`](graph-validate.md) | `validate_graph()`: connectivity and type checks |
| [`graph.optimize`](graph-optimize.md) | `optimize_graph()`: dead-code elimination, constant folding |
| [`graph.simulate`](graph-simulate.md) | `simulate()`: run graph in Python (requires numpy) |
| [`graph.algebra`](graph-algebra.md) | `series()`, `parallel()`, `split()`, `merge()` combinators |
| [`graph.adapter`](graph-adapter.md) | Bridge dsp-graph output to gen-dsp platform backends |
