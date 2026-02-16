# TODO

## Backends

### Implemented

- [x] **PureData** - Primary target. Full support.

- [x] **Max/MSP** - Full support. See `src/gen_dsp/templates/max/`.

- [x] **ChucK** - Full support. Generates chugins (.chug) with multi-channel I/O and runtime parameter control. See `src/gen_dsp/templates/chuck/`.

- [x] **AudioUnit (AUv2)** - Full support. Generates macOS .component bundles using raw AUv2 C API (no SDK dependency). Auto-detects effect vs generator from I/O. See `src/gen_dsp/templates/au/`.

- [x] **CLAP** - Full support. Generates cross-platform .clap plugins using the CLAP C API (header-only, MIT licensed, fetched via CMake FetchContent). Zero-copy audio processing. Auto-detects effect vs instrument from I/O. See `src/gen_dsp/templates/clap/`.

- [x] **VST3** - Full support. Generates cross-platform .vst3 bundles using the Steinberg VST3 SDK (fetched via CMake FetchContent). Zero-copy audio processing. Auto-detects effect vs instrument from I/O. Deterministic FUID generation. See `src/gen_dsp/templates/vst3/`.

- [x] **LV2** - Full support. Generates cross-platform .lv2 bundles using the LV2 C API (header-only, ISC licensed, fetched via CMake FetchContent). TTL metadata generated with real parameter names/ranges parsed from gen~ exports. Auto-detects effect vs generator from I/O. See `src/gen_dsp/templates/lv2/`.

- [x] **SuperCollider UGens** - Full support. Generates cross-platform SC UGens (.scx on macOS, .so on Linux) using the SC plugin interface headers (fetched via CMake FetchContent). Generates .sc class files with parameter names/defaults parsed from gen~ exports. Auto-detects effect vs generator from I/O. See `src/gen_dsp/templates/sc/`.

- [x] **VCV Rack modules** - Full support. Generates VCV Rack modules using the Rack SDK's Makefile-based build system. Per-sample processing via perform(n=1). Auto-generates plugin.json manifest and panel SVG. Auto-detects effect vs generator from I/O. Parameter names/ranges parsed from gen~ exports. See `src/gen_dsp/templates/vcvrack/`.

- [x] **Daisy (Electrosmith)** - Full support. Generates Daisy Seed firmware (.bin) using libDaisy's Make-based build system with ARM cross-compilation. Custom genlib runtime with two-tier bump allocator (SRAM + SDRAM). Auto-maps stereo I/O with scratch buffers for channel mismatch. libDaisy auto-cloned and built on first use. See `src/gen_dsp/templates/daisy/`.

- [x] **Circle (Raspberry Pi bare metal)** - Full support. Generates bare-metal kernel images (.img) for Raspberry Pi 3/4 using the Circle C++ framework with ARM cross-compilation. I2S audio output via external DAC (PCM5102A, PCM5122, WM8960, etc.). Custom genlib runtime with heap-backed bump allocator. Circle SDK auto-cloned and built on first use. See `src/gen_dsp/templates/circle/`.

### Refactoring / Improvements

From code review (2026-02-16). R1-R9, R11, R12 completed.

#### Templates

- [ ] **R10. Switch templates from `safe_substitute()` to `substitute()` with validation.** Catches typos in template variables at generation time rather than producing broken build files. Requires auditing all templates to ensure no intentional unsubstituted `$` tokens (beyond `$$` for make variables).

#### Architecture

- [ ] **`"both"` platform mode needs per-platform subdirectories or a warning.** `ProjectGenerator.generate()` iterates all registered platforms when `platform == "both"`, but generates everything into the same output directory. Platforms with same-named files (e.g. `gen_buffer.h`, `CMakeLists.txt`) overwrite each other.
- [ ] **`cmake_platforms` set hardcoded in CLI.** The set `{"clap", "vst3", "lv2", "sc"}` at `cli.py` for `--shared-cache` validation should be derived from a class attribute or registry query, not hardcoded.

#### Error Handling

- [ ] **`TemplateError` defined but never raised.** Template-related failures currently raise `ProjectError`. Either use `TemplateError` consistently or remove it.

#### Minor Code Quality

- [ ] **`builder.py` may be too thin a wrapper** -- adds no logic beyond `get_platform(name).build()`. Could be a standalone function.
- [ ] **`parser.py`: `validate_buffer_names()` recompiles regex every call.** Pattern should be a class constant.
- [ ] **`project.py`: `shared_cache` docstring** says "(clap, vst3)" but also applies to LV2 and SC.

#### CLI / UX

- [ ] **`list` command could show descriptions.** Currently just prints platform names. Could show build system type, supported OS, brief description.
- [ ] **`build` command could auto-detect platform** from `manifest.json` in project directory, removing the need for `-p <platform>`.
- [ ] **`cache clean` subcommand.** Let users reclaim disk space from downloaded SDKs.
- [ ] **`--board` dynamic listing.** Consider `gen-dsp list --boards daisy` to dynamically list valid boards instead of hardcoding in help text.

#### Testing

- [ ] **Parameter sanitization tests.** `_sanitize_symbol()` (LV2) and SC arg sanitization lack edge-case unit tests (empty string, Unicode, leading digits).
- [ ] **More fixture diversity.** No mono (1-in/1-out), high channel count, multi-buffer, or zero-parameter (other than RamplePlayer) fixtures.
- [ ] **CLI integration tests for `cache` and `manifest` commands.**
- [ ] **Fix `test_project.py::test_generate_pd_project_no_buffers`** -- expects `gen_dsp.cpp` but PD template has `gen_ext.cpp`.

#### Documentation

- [ ] **API documentation** for core modules (`parser`, `manifest`, `project`, `builder`) for library users.
- [ ] **Architecture diagram** (visual, not just text in CLAUDE.md).
- [ ] **`pyproject.toml` keywords** missing newer platform names (chuck, audiounit, clap, vst3, lv2, supercollider, daisy, vcvrack, circle).
- [ ] **`pyproject.toml` classifiers** missing `"Operating System :: Microsoft :: Windows"` despite Windows support.

### To Implement

#### Embedded/Hardware Targets

- [ ] **Bela** - BeagleBone-based real-time audio platform. C++ API, ultra-low latency. Similar audience to Organelle.
  - Docs: <https://learn.bela.io/>

- [ ] **Teensy Audio Library** - Arduino-compatible, popular for DIY synths.
  - Docs: <https://www.pjrc.com/teensy/td_libs_Audio.html>

#### Other

- [ ] **DISTRHO Plugin Framework** - [DPF](https://github.com/DISTRHO/DPF) can build LADSPA, DSSI, LV2, VST2, VST3 and CLAP formats. A JACK/Standalone mode is also available, allowing you to quickly test plugins.
  - Docs: <https://distrho.github.io/DPF/>

- [ ] **JUCE (VST/AU/AAX)** - Abstracts plugin formats. Note: AU, CLAP, VST3, and LV2 are already covered natively without JUCE, so main value-add is AAX (Pro Tools, requires Avid NDA).
  - Docs: <https://juce.com/>

- [ ] **Web Audio (AudioWorklet + WASM)** - Compile gen~ to WebAssembly for browser. Growing interest in web-based audio.
  - Docs: <https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet>
