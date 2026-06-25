# gen_dsp core API guide

A usage-oriented guide to the zero-dependency `gen_dsp.core` pipeline for library
users (no gen~ export tooling or pydantic required). The per-symbol reference is
auto-generated on the [Parser](parser.md), [Manifest](manifest.md),
[Project](project.md), and [Builder](builder.md) pages; this guide shows how the
pieces fit together.

The pipeline has four stages, each a thin, independently usable layer:

```text
export dir --GenExportParser--> ExportInfo --manifest_from_export_info--> Manifest
           --ProjectGenerator.generate--> project dir --Builder.build--> BuildResult
```

All symbols below are importable from `gen_dsp.core.<module>`.

---

## 1. Parsing a gen~ export -- `core.parser`

### `GenExportParser(export_path)`

Wraps a gen~ export directory (the folder containing the exported `<name>.cpp` /
`<name>.h` pair and a `gen_dsp/` subdirectory). Construction validates that the
path is a directory; `parse()` does the analysis.

### `GenExportParser.parse() -> ExportInfo`

Reads the main `.cpp` with a set of regexes and returns an `ExportInfo` carrying:

- `name` -- the export's base name (also the C++ namespace)
- `num_inputs` / `num_outputs` -- signal I/O counts (`gen_kernel_numins/numouts`)
- `num_params` -- parameter count (`num_params()`)
- `input_names` -- signal input names (`gen_kernel_innames[]`)
- `buffers` -- referenced buffer names (two detection strategies: codebox `Data`
  members, or direct `buf.dim`/`buf.read()` access)
- `has_exp2f_issue` -- whether `genlib_ops.h` uses `exp2f` (patched on macOS)

```python
from gen_dsp.core.parser import GenExportParser

info = GenExportParser("path/to/export/gen").parse()
print(info.name, info.num_inputs, info.num_outputs, info.buffers)
```

`parse()` raises `ParseError` (a `GenExtError`) when no `.cpp`/`.h` pair is found.

---

## 2. Building the manifest -- `core.manifest`

The `Manifest` is the front-end-agnostic intermediate representation every
platform backend consumes. It deliberately does not know about gen~ -- the same
manifest can come from a gen~ export or the graph frontend.

### `manifest_from_export_info(export_info, buffers, version) -> Manifest`

Builds a `Manifest` from an `ExportInfo`, parsing full parameter metadata
(`ParamInfo` with `min`/`max`/`default`, defaults clamped into range) from the
export. Pass `export_info.buffers` for `buffers` to keep auto-detection, or an
explicit list to override it.

```python
from gen_dsp.core.manifest import manifest_from_export_info
from gen_dsp.version import __version__

manifest = manifest_from_export_info(info, info.buffers, __version__)
manifest.to_json()          # the exact content of a project's manifest.json
```

### Key types

- **`Manifest`** -- fields: `gen_name`, `num_inputs`, `num_outputs`,
  `params: list[ParamInfo]`, `buffers: list[str]`, `remapped_inputs`, `source`,
  `version`; `num_params` property; `to_dict`/`from_dict`/`to_json`/`from_json`
  round-trip helpers.
- **`ParamInfo`** -- one parameter: `index`, `name`, `has_minmax`, `min`, `max`,
  `default`.
- **`RemappedInput`** -- records a signal input converted to a parameter (see
  below).

### `apply_inputs_as_params(manifest, input_names, remap_names=None) -> Manifest`

Returns a new manifest with signal inputs remapped to parameters -- the library
form of `--inputs-as-params`. With `remap_names=None` all inputs are remapped;
pass a subset of `input_names` to remap only those. The result has reduced
`num_inputs`, extra `ParamInfo` entries, and populated `remapped_inputs`.

---

## 3. Generating a project -- `core.project`

### `ProjectConfig`

A dataclass of generation options. The commonly set fields:

- `name` (required) -- external/library name (`lib.name` in Makefiles)
- `platform` -- target key (default `"pd"`); any registered platform
- `buffers`, `apply_patches`, `output_dir`
- `shared_cache` / `cache_dir` -- FetchContent cache control for CMake platforms
- `board` -- variant for embedded platforms (see `gen-dsp list --boards <platform>`)
- MIDI-to-CV fields (`no_midi`, `midi_gate`, `midi_freq`, ...)

`ProjectConfig.validate()` rejects invalid names (including C/C++ reserved words)
and bad board values.

### `ProjectGenerator(export_info, config)` and `.generate(output_dir=None) -> Path`

Copies the export, runs template substitution for the target platform, writes
`manifest.json` and a `.gen-dsp.json` marker (recording the platform for later
`build` auto-detection), and applies patches. Returns the project directory.

```python
from gen_dsp.core.project import ProjectConfig, ProjectGenerator

config = ProjectConfig(name="myverb", platform="clap")
project_dir = ProjectGenerator(info, config).generate("build/myverb")
```

### `ProjectGenerator.from_graph(graph, config)` (classmethod)

Constructs a generator from a `gen_dsp.graph.Graph` instead of a gen~ export, so
the same backends produce projects from the graph frontend. Requires the
`[graph]` extra.

---

## 4. Building -- `core.builder`

### `Builder(project_dir)`

Owns "build this project directory". Construction validates the directory exists.

- **`build(target_platform=None, clean=False, verbose=False) -> BuildResult`** --
  compiles the project. When `target_platform` is `None`, the platform is
  auto-detected from the project's `.gen-dsp.json` marker, falling back to `pd`.
- **`clean(target_platform=None)`** -- removes build artifacts (same auto-detect).
- **`detect_platform() -> str | None`** -- returns the platform recorded in the
  marker, or `None` if absent/unreadable/unknown.
- **`get_lib_name() -> str | None`** -- reads `lib.name` from the project Makefile.

### `BuildResult`

Dataclass returned by `build()`: `success`, `platform`, `output_file`, `stdout`,
`stderr`, `return_code`.

```python
from gen_dsp.core.builder import Builder

result = Builder(project_dir).build()   # platform read from .gen-dsp.json
if result.success:
    print("built", result.output_file)
```

---

## End-to-end example

```python
from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.manifest import manifest_from_export_info
from gen_dsp.core.project import ProjectConfig, ProjectGenerator
from gen_dsp.core.builder import Builder
from gen_dsp.version import __version__

# 1. parse the gen~ export
info = GenExportParser("path/to/export/gen").parse()

# 2. (optional) inspect the manifest IR
manifest = manifest_from_export_info(info, info.buffers, __version__)
print(f"{manifest.gen_name}: {manifest.num_inputs}in/{manifest.num_outputs}out, "
      f"{manifest.num_params} params")

# 3. generate a CLAP project
config = ProjectConfig(name="myverb", platform="clap")
project_dir = ProjectGenerator(info, config).generate("build/myverb")

# 4. build it (platform auto-detected from the project marker)
result = Builder(project_dir).build()
print("ok" if result.success else result.stderr)
```

For multi-target generation, board selection, and MIDI options from the command
line, see the [cheatsheet](../cheatsheet.md).
