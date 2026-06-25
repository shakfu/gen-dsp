# TODO

gen-dsp can be consumed as a library by [dsp-graph](https://github.com/shakfu/dsp-graph), a React/FastAPI web IDE that imports `gen_dsp.graph.*`directly. Prioritities in this document reflect both standalone CLI use and the requirements to work as a library (especially with dsp-grap).

---

## Medium Priority

### Web Audio backend follow-ups

- [x] **Web Audio runtime buffer loading** -- Done: added `wa_load_buffer` / `wa_get_num_buffers` / `wa_get_buffer_name` Emscripten exports backed by a genlib-side `wrapper_load_buffer()` (writes interleaved samples into the `WebaudioBuffer` instances). The worklet (`processor.js`) handles a `load-buffer` message (queued until the WASM is ready), and `index.html` provides a per-buffer file input that decodes audio via `decodeAudioData()` and posts the samples to the worklet. Verified end-to-end (emcc build + Node round-trip) by `test_buffer_loading_rampleplayer`.

- [ ] **Web Audio build integration tests** -- Currently gated by `emcc` availability (skipped in CI). Consider adding Emscripten to CI or a lightweight WASM validation step.

### Testing

- [ ] **Parameter sanitization tests** -- The three identifier sanitizers lack edge-case unit tests (empty string, Unicode, leading digits, all-symbol names): `sanitize_c_identifier` (`platforms/base.py`, shared by LV2 and others), `_sanitize_sc_arg` (`platforms/supercollider.py`), and `_sanitize_input_name` (`core/manifest.py`). Correctness risk.

- [x] **More fixture diversity** -- Done: added minimal hand-authored gen~-style fixtures covering the missing shapes -- `mono_gain` (1-in/1-out, one ranged param), `multitap` (two buffers, zero params), and `octoverb` (8-in/8-out, two params) -- with parser/manifest shape tests in `tests/test_fixture_shapes.py`. (These are parse/IR-only, not buildable.)

- [x] **CLI integration test for the `manifest` command.** Done: `tests/test_cli.py::TestManifestCommand` (valid-JSON output, `--buffers` override, buffer auto-detection, missing-export error). (`cache --prune` was already covered by `tests/test_cache.py::TestCachePrune`.)

### Templates

- [x] **R10. Switch templates from `safe_substitute()` to `substitute()` with validation** -- Done: all platform generators now route through `substitute_strict()` (`platforms/base.py`), which raises `ProjectError` on an undefined `$placeholder` or malformed `$` token. The audit fixed three stray unescaped tokens that previously survived only by `safe_substitute`'s leniency (`au`/`clap` `$ENV{...}` and `vst3` `$<SEMICOLON>` -> `$$`-escaped).

### CLI / UX

- [x] **`cache clean` subcommand** -- Done: implemented as `gen-dsp cache --prune` (with `--dry-run` and `-y`), which reclaims disk space from downloaded SDKs.

- [x] **`build` command auto-detects platform** -- Done: project generation now writes a `.gen-dsp.json` marker (recording `platform`/`board`/`version`), and `gen-dsp build` reads it when `-p` is omitted (falling back to `pd` if absent). The platform is kept out of the front-end-agnostic `manifest.json` deliberately.

---

## Low Priority / Housekeeping

### Minor Code Quality

- [x] **`builder.py` thinness** -- Resolved by giving `Builder` cohesive responsibility rather than removing it (removal was ruled out: dsp-graph calls `Builder(project_dir).build(platform)`). `Builder` now owns project-directory platform detection: `detect_platform()` reads the `.gen-dsp.json` marker, and `build()`/`clean()` accept `target_platform=None` to auto-detect (falling back to `pd`). The CLI's standalone `_detect_project_platform` helper was removed in favor of `Builder.detect_platform()`. (It already had `get_lib_name()`, dir validation, and error translation, so it was never a pure pass-through.)

### CLI / UX

- [x] **`list` command shows descriptions** -- Done: each `Platform` now carries `description` and `build_system` class attributes; `gen-dsp list -v` prints an aligned table (name, build system, extension, description) and `gen-dsp list --json` emits the same as JSON. The default `gen-dsp list` still prints bare names (backward compatible). (Supported-OS column omitted -- the per-platform OS matrix is nuanced and would risk being misleading.)

- [x] **`--board` dynamic listing** -- Done: `Platform.list_boards()` (overridden by Daisy and Circle) exposes the valid board keys, and `gen-dsp list --boards <platform>` lists them (with `--json`). The `--board` help text now points at this command instead of hardcoding the set. A test asserts the listed boards match the validated set, guarding against drift.

- [x] **Rename `dot` subcommand to `viz`** -- Done: the graph visualization subcommand is now `viz` (top-level and standalone graph CLI), with `dot` retained as a hidden, deprecated alias that still works but warns on stderr. The Python API (`graph_to_dot()`) and the Graphviz `dot` binary references are unchanged.

### Documentation

- [x] **API documentation for core modules** -- Done: added a hand-written, example-driven [Core API guide](docs/api/core-guide.md) (the `docs/graph/api.md` analog) covering the parse -> manifest -> generate -> build pipeline for library users, wired into the mkdocs nav and linked from the API index. Also filled the missing docstrings on the public manifest serialization methods (`to_dict`/`from_dict`/`to_json`/`from_json`) so the mkdocstrings autodoc pages (`docs/api/{parser,manifest,project,builder}.md`) are complete.

- [x] **Architecture diagram** -- Done: added [docs/architecture.md](docs/architecture.md) with Mermaid diagrams (pipeline data flow, CLI orchestration, platform registry by build system, header isolation pattern), enabled Mermaid rendering in mkdocs, wired it into the nav, and linked it from the docs index and CLAUDE.md.

- [x] **`pyproject.toml` keywords** -- Done: added chuck, audiounit, clap, vst3, lv2, supercollider, vcvrack, daisy, circle.

- [x] **`pyproject.toml` classifiers** -- Done: added `"Operating System :: Microsoft :: Windows"`.

---

## New Backends

### Embedded / Hardware

- [ ] **Bela** - BeagleBone-based real-time audio platform. C++ API, ultra-low latency.

  - Docs: <https://learn.bela.io/>

- [ ] **Teensy Audio Library** - Arduino-compatible, popular for DIY synths.

  - Docs: <https://www.pjrc.com/teensy/td_libs_Audio.html>

- [ ] **OWL (Rebel Technology)** - Programmable guitar pedal platform with a C++ API. Similar to Daisy in concept, small but dedicated community.

  - Docs: <https://www.rebeltech.org/docs/>

### Standalone

- [x] **Standalone (miniaudio)** - Self-contained CLI executable that processes audio I/O directly. Useful for testing, prototyping, and headless audio appliances (Raspberry Pi, etc.). Minimal API surface -- just open a stream and call `perform()`. miniaudio is a single header file with no dependencies. Platform key: `"standalone"`.

  - miniaudio: <https://miniaud.io/>

  - PortAudio: <http://www.portaudio.com/>

### Plugin Frameworks

- [x] **AUv3 (macOS)** - Modern Audio Unit API via AUAudioUnit subclass (Objective-C++). Built with `cmake -G Xcode` to produce the required `.appex`-inside-`.app` bundle structure. Platform key: `"auv3"`.

  - Docs: <https://developer.apple.com/documentation/audiotoolbox/audio_unit_v3_plug-ins>

- [ ] **DISTRHO Plugin Framework (DPF)** - Can build LADSPA, DSSI, LV2, VST2, VST3, and CLAP. Main value-add over current coverage is LADSPA/DSSI. JACK/Standalone mode useful for headless testing.

  - Docs: <https://distrho.github.io/DPF/>

- [ ] **JUCE (VST/AU/AAX)** - Abstracts plugin formats. AU, CLAP, VST3, and LV2 are already covered natively without JUCE, so the only real value-add is AAX (Pro Tools). Requires Avid NDA. Low priority unless Pro Tools support is specifically requested.

  - Docs: <https://juce.com/>

### Hardware Platforms

- [ ] **Move Everything (Ableton Move)** - Unofficial framework for custom DSP on Ableton Move hardware. ARM64 Linux `.so` plugins via C plugin API v2. Key challenges: int16 stereo interleaved audio (not float), cross-compilation, stereo-only I/O. CC BY-NC-SA 4.0 license may constrain template code. Closest analog: Daisy backend.

  - Repo: <https://github.com/charlesvestal/move-everything>

  - Assessment: [docs/move-everything.md](docs/move-everything.md)

### Game Audio

- [ ] **FMOD plugin** - Game audio middleware with a clean C DSP plugin API. Taps into game audio market that gen-dsp currently doesn't reach.

  - Docs: <https://www.fmod.com/docs/2.03/api/plugin-api.html>

- [ ] **Wwise plugin** - Audiokinetic's game audio middleware. C++ plugin API. Similar market to FMOD but different ecosystem (Unreal-heavy).

  - Docs: <https://www.audiokinetic.com/en/library/edge/?source=SDK>

### Academic / Music Languages

- [x] **Csound opcode** - Well-defined C API for custom opcodes. Niche but long-lived community (academic, electroacoustic composition). Platform key: `"csound"`.

  - Docs: <https://csound.com/docs/manual/OrchTop.html>
