# TODO

gen-dsp is consumed as a library by dsp-graph (~/projects/personal/dsp-graph), a React/FastAPI web IDE that imports gen_dsp.graph.* directly. Priority reflects both standalone CLI use and that library contract.

---

## High Priority

### Fix failing test

- [ ] **Fix `test_project.py::test_generate_pd_project_no_buffers`** -- expects `gen_dsp.cpp` but
  PD template has `gen_ext.cpp`. Zero-tolerance for test failures.

### API surface (library contract with dsp-graph)

- [ ] **API documentation for graph subpackage** -- dsp-graph imports ~15 gen_dsp.graph functions (`parse`, `compile_graph`, `validate_graph`, `optimize_graph`, `simulate`, `graph_to_gdsp`, `graph_to_dot`,
  `generate_adapter_cpp`, `generate_manifest`, `toposort`, etc.). None have stable public-API docs. Docstrings + a `docs/graph/api.md` reference would let dsp-graph developers know what's guaranteed vs. internal.
- [ ] **Stabilize GraphValidationError fields** -- dsp-graph's `/api/graph/validate` currently discards `error.kind`, `error.node_id`, `error.field_name`, `error.severity` and returns only `str(error)`, because the fields are undocumented and their stability is unknown. Document and commit to these fields so dsp-graph can surface per-node highlighting.

### New backend: Web Audio (AudioWorklet + WASM)

- [ ] **Web Audio (AudioWorklet + WASM)** -- Compile graph C++ to WebAssembly for in-browser
  execution. High strategic value: dsp-graph is already a web tool, so users could run their
  compiled graph directly in the browser without installing a plugin. Emscripten target + a
  thin JS AudioWorkletProcessor wrapper.
  - Docs: <https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet>

---

## Medium Priority

### Testing

- [ ] **Parameter sanitization tests** -- `_sanitize_symbol()` (LV2) and SC arg sanitization lack
  edge-case unit tests (empty string, Unicode, leading digits). Correctness risk.
- [ ] **More fixture diversity** -- No mono (1-in/1-out), high channel count, multi-buffer, or
  zero-parameter (other than RamplePlayer) fixtures. dsp-graph exercises more graph shapes than
  the CLI tests do.
- [ ] **CLI integration tests for `cache` and `manifest` commands.**

### Templates

- [ ] **R10. Switch templates from `safe_substitute()` to `substitute()` with validation** --
  Catches typos in template variables at generation time rather than producing broken build files.
  Requires auditing all templates to ensure no intentional unsubstituted `$` tokens (beyond `$$`
  for make variables).

### CLI / UX

- [ ] **`cache clean` subcommand** -- Let users reclaim disk space from downloaded SDKs. Relevant
  for both CLI users and dsp-graph deployments that accumulate SDK fetches.
- [ ] **`build` command could auto-detect platform** from `manifest.json` in project directory,
  removing the need for `-p <platform>`.

---

## Low Priority / Housekeeping

### Architecture

- [ ] **`cmake_platforms` set hardcoded in CLI** -- The set `{"clap", "vst3", "lv2", "sc"}` at
  `cli.py` for `--shared-cache` validation should be derived from a class attribute or registry
  query, not hardcoded.
- [ ] **`"both"` platform mode needs per-platform subdirectories or a warning** --
  `ProjectGenerator.generate()` iterates all registered platforms when `platform == "both"`, but
  generates everything into the same output directory. Platforms with same-named files (e.g.
  `gen_buffer.h`, `CMakeLists.txt`) overwrite each other. May be a stale concern if the refactored
  CLI no longer exposes "both" mode -- verify first.

### Error Handling

- [ ] **`TemplateError` defined but never raised** -- Template-related failures currently raise
  `ProjectError`. Either use `TemplateError` consistently or remove it.

### Minor Code Quality

- [ ] **`builder.py` may be too thin a wrapper** -- adds no logic beyond `get_platform(name).build()`.
  Note: dsp-graph calls `Builder(project_dir).build(platform)`, so removing the class would
  require a coordinated change in both repos.
- [ ] **`parser.py`: `validate_buffer_names()` recompiles regex every call** -- Pattern should be
  a class constant.
- [ ] **`project.py`: `shared_cache` docstring** says "(clap, vst3)" but also applies to LV2 and SC.

### CLI / UX

- [ ] **`list` command could show descriptions** -- Currently just prints platform names. Could
  show build system type, supported OS, brief description. Less pressing since dsp-graph has its
  own platform listing via `/api/build/platforms`.
- [ ] **`--board` dynamic listing** -- Consider `gen-dsp list --boards daisy` to dynamically list
  valid boards instead of hardcoding in help text.
- [ ] **Rename `dot` subcommand to `viz`** -- The current name is implementation-specific (Graphviz
  DOT format). Renaming allows for future visualization methods beyond DOT (e.g., SVG, interactive
  web view). dsp-graph uses the Python API (`graph_to_dot()`) directly, not the CLI subcommand.

### Documentation

- [ ] **API documentation for core modules** (`parser`, `manifest`, `project`, `builder`) for CLI
  library users. Lower priority than graph subpackage docs since dsp-graph doesn't consume these.
- [ ] **Architecture diagram** (visual, not just text in CLAUDE.md).
- [ ] **`pyproject.toml` keywords** missing newer platform names (chuck, audiounit, clap, vst3,
  lv2, supercollider, daisy, vcvrack, circle).
- [ ] **`pyproject.toml` classifiers** missing `"Operating System :: Microsoft :: Windows"` despite
  Windows support.

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
  covered natively without JUCE, so the only real value-add is AAX (Pro Tools). Requires Avid NDA.
  Low priority unless Pro Tools support is specifically requested.
  - Docs: <https://juce.com/>
