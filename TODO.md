# TODO

gen-dsp can be consumed as a library by [dsp-graph](https://github.com/shakfu/dsp-graph), a React/FastAPI web IDE that imports `gen_dsp.graph.*`directly. Prioritities in this document reflect both standalone CLI use and the requirements to work as a library (especially with dsp-grap).

---

## High Priority

### API surface (library contract with dsp-graph)

- [x] **API documentation for graph subpackage** -- `docs/graph/api.md` written covering all public symbols: parse/parse_multi/parse_file, validate_graph, GraphValidationError, compile_graph, optimize_graph + individual passes, simulate/SimState/SimResult, graph_to_gdsp, graph_to_dot, series/parallel/split/merge, toposort, generate_adapter_cpp, generate_manifest, compile_for_gen_dsp, and ProjectGenerator.from_graph usage.

- [x] **Stabilize GraphValidationError fields** -- all 14 `kind` values documented in the class docstring with descriptions of `node_id`, `field_name`, and `severity`. Fields are stable public API; dsp-graph can safely access `error.kind`, `error.node_id`, etc.

---

## Medium Priority

### Web Audio backend follow-ups

- [ ] **Web Audio buffer loading** -- The `webaudio` backend currently stubs buffer support
  (`WRAPPER_BUFFER_COUNT 0`). Browser file loading is async and browser-specific; needs a
  `wa_load_buffer()` Emscripten export + JS-side `fetch()` + `decodeAudioData()` bridge.

- [ ] **Web Audio build integration tests** -- Currently gated by `emcc` availability (skipped
  in CI). Consider adding Emscripten to CI or a lightweight WASM validation step.

### Testing

- [ ] **Parameter sanitization tests** -- `_sanitize_symbol()` (LV2) and SC arg sanitization lack edge-case unit tests (empty string, Unicode, leading digits). Correctness risk.

- [ ] **More fixture diversity** -- No mono (1-in/1-out), high channel count, multi-buffer, or zero-parameter (other than RamplePlayer) fixtures. dsp-graph exercises more graph shapes than the CLI tests do.

- [ ] **CLI integration tests for `cache` and `manifest` commands.**

### Templates

- [ ] **R10. Switch templates from `safe_substitute()` to `substitute()` with validation** --
  Catches typos in template variables at generation time rather than producing broken build files. Requires auditing all templates to ensure no intentional unsubstituted `$` tokens (beyond `$$` for make variables).

### CLI / UX

- [ ] **`cache clean` subcommand** -- Let users reclaim disk space from downloaded SDKs. Relevant for both CLI users and dsp-graph deployments that accumulate SDK fetches.

- [ ] **`build` command could auto-detect platform** from `manifest.json` in project directory, removing the need for `-p <platform>`.

---

## Low Priority / Housekeeping

### Architecture

- [x] **`cmake_platforms` set hardcoded in CLI** -- Added `list_cmake_platforms()` to `platforms/__init__.py` that derives the set dynamically via `issubclass(cls, CMakePlatform)`. Fixed CLI help text and stale comments. Merged misleading split dict in `adapter.py`.

- [x] **`"both"` platform mode needs per-platform subdirectories or a warning** -- Verified "both" was unreachable from CLI (argparse `choices` excluded it). Removed dead code: the `"both"` branch in `_generate_from_export()`, the `+ ["both"]` in `validate()`, and stale comments.

### Error Handling

- [x] **Structured DSL compile errors** -- Added `line` and `col` fields to all expression AST nodes (`ASTNumber`, `ASTIdent`, `ASTBinExpr`, `ASTUnaryExpr`, `ASTCall`, `ASTDotAccess`, `ASTCompose`). Parser populates them from tokens. All `GDSPCompileError` raise sites now consistently carry source location. dsp-graph can safely access `error.line`, `error.col`, `error.filename` for inline editor markers.

- [x] **`TemplateError` defined but never raised** -- Removed the dead `TemplateError` class from `errors.py`. Template-related failures continue to use `ProjectError`.

### Minor Code Quality

- [ ] **`builder.py` may be too thin a wrapper** -- adds no logic beyond `get_platform(name).build()`. Note: dsp-graph calls `Builder(project_dir).build(platform)`, so removing the class would require a coordinated change in both repos.

- [x] **`parser.py`: `validate_buffer_names()` recompiles regex every call** -- Hoisted to `C_IDENTIFIER_PATTERN` class constant.

- [x] **`project.py`: `shared_cache` docstring** says "(clap, vst3)" but also applies to LV2 and SC. Fixed to say "CMake-based platforms".

### CLI / UX

- [ ] **`list` command could show descriptions** -- Currently just prints platform names. Could show build system type, supported OS, brief description. Less pressing since dsp-graph has its own platform listing via `/api/build/platforms`.

- [ ] **`--board` dynamic listing** -- Consider `gen-dsp list --boards daisy` to dynamically list valid boards instead of hardcoding in help text.

- [ ] **Rename `dot` subcommand to `viz`** -- The current name is implementation-specific (Graphviz DOT format). Renaming allows for future visualization methods beyond DOT (e.g., SVG, interactive web view). dsp-graph uses the Python API (`graph_to_dot()`) directly, not the CLI subcommand.

### Documentation

- [ ] **API documentation for core modules** (`parser`, `manifest`, `project`, `builder`) for CLI library users. Lower priority than graph subpackage docs since dsp-graph doesn't consume these.

- [ ] **Architecture diagram** (visual, not just text in CLAUDE.md).
- [ ] **`pyproject.toml` keywords** missing newer platform names (chuck, audiounit, clap, vst3, lv2, supercollider, daisy, vcvrack, circle).
- [ ] **`pyproject.toml` classifiers** missing `"Operating System :: Microsoft :: Windows"` despite Windows support.

---

## New Backends

### Embedded / Hardware

- [ ] **Bela** - BeagleBone-based real-time audio platform. C++ API, ultra-low latency.
  - Docs: <https://learn.bela.io/>

- [ ] **Teensy Audio Library** - Arduino-compatible, popular for DIY synths.
  - Docs: <https://www.pjrc.com/teensy/td_libs_Audio.html>

### Plugin Frameworks

- [ ] **DISTRHO Plugin Framework (DPF)** - Can build LADSPA, DSSI, LV2, VST2, VST3, and CLAP.
  Main value-add over current coverage is LADSPA/DSSI. JACK/Standalone mode useful for headless
  testing.
  - Docs: <https://distrho.github.io/DPF/>

- [ ] **JUCE (VST/AU/AAX)** - Abstracts plugin formats. AU, CLAP, VST3, and LV2 are already
  covered natively without JUCE, so the only real value-add is AAX (Pro Tools). Requires Avid NDA. Low priority unless Pro Tools support is specifically requested.
  - Docs: <https://juce.com/>
