# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **MIDI-to-CV monophonic note handling** for all four DAW plugin formats (CLAP, VST3, AudioUnit, LV2)
  - Auto-detects gen~ parameters named `gate`, `freq`/`frequency`/`pitch`, `vel`/`velocity` on 0-input (generator/instrument) plugins
  - Maps MIDI note-on/off events to `wrapper_set_param()` calls: gate (0/1), frequency (mtof or raw MIDI note), velocity (0-1 normalized)
  - Gate parameter is required for auto-detection; frequency and velocity are optional
  - CLI flags for explicit control: `--midi-gate <name>`, `--midi-freq <name>`, `--midi-vel <name>`, `--midi-freq-unit hz|midi`, `--no-midi`
  - All MIDI code guarded by `#ifdef MIDI_ENABLED` compile definitions -- zero overhead for effects
  - Shared detection logic in `core/midi.py` (`MidiMapping` dataclass, `detect_midi_mapping()`, `build_midi_defines()`)
- **Polyphonic voice allocation** for all four DAW plugin formats (CLAP, VST3, AudioUnit, LV2)
  - `--voices N` CLI flag sets compile-time voice count (default 1 = monophonic)
  - Shared `voice_alloc.h` header with round-robin allocation and oldest-steal when all voices are occupied
  - Each voice is an independent `GenState*` instance; outputs summed without normalization (matches hardware polysynth behavior)
  - Note-off matches by MIDI note number; stolen voices receive gate-off before reuse
  - Non-MIDI parameters (e.g. filter cutoff) broadcast to all voices; MIDI params (gate/freq/vel) routed per-voice
  - Per-voice scratch buffers allocated eagerly at plugin init; first voice renders directly into host buffer (zero-copy), remaining voices summed in
  - All polyphony code guarded by `#if NUM_VOICES > 1` -- zero overhead for monophonic plugins
  - Validation: `--voices > 1` requires MIDI to be enabled (errors with `--no-midi`)
  - **CLAP**: note port extension (`CLAP_EXT_NOTE_PORTS`), CLAP note events in both `process()` and `params_flush()`
  - **VST3**: event input bus, VST3 `NoteOnEvent`/`NoteOffEvent` handling in `process()`
  - **AudioUnit**: AU type changed from `augn` (generator) to `aumu` (music device) for MIDI-enabled instruments, raw MIDI bytes via `kMusicDeviceMIDIEventSelect`
  - **LV2**: `InstrumentPlugin` type, atom input port with `midi:MidiEvent` support, URID map feature for MIDI event type identification, `urid:map` required feature in TTL
- **Polyphony build integration tests** for all four DAW plugin formats -- verifies that `voice_alloc.h` and all `#if NUM_VOICES > 1` code paths compile cleanly across CLAP, VST3, AudioUnit, and LV2

## [0.1.11]

### Fixed

- **VST3: parameters not visible in hosts (e.g. Bitwig)** -- `RangeParameter` instances were created with `flags = 0` (`kNoFlags`), which tells VST3 hosts that parameters are not automatable and should not be exposed in the host UI or automation lanes. Fixed to `ParameterInfo::kCanAutomate`. CLAP and AU backends already had the correct flags (`CLAP_PARAM_IS_AUTOMATABLE`, `kAudioUnitParameterFlag_IsWritable`).

## [0.1.10]

### Changed

- **Refactoring: `CMakePlatform` intermediate base class** (`platforms/cmake_platform.py`) -- the 6 CMake-based platforms (AU, CLAP, VST3, LV2, SC, Max) now inherit from `CMakePlatform` instead of `Platform` directly. Shared `build()`, `clean()`, `get_build_instructions()`, and `resolve_shared_cache()` implementations eliminate ~60 lines of duplication. AU keeps its `build()` override (macOS guard), Max keeps `build()` (SDK setup) and `get_build_instructions()` (git clone step).

- **Refactoring: parameterized `_ext*.h` templates** -- the 8 identical 44-line `_ext_{platform}.h` header files (CLAP, VST3, LV2, SC, AU, VCV Rack, Daisy, Circle) are now generated from a single shared template (`templates/shared/gen_ext_h.template`) via `Platform.generate_ext_header()`. ChucK, Max, and PD retain their genuinely different headers. Removes ~350 lines of duplication.

- **Refactoring: extracted graph init logic from CLI** (`core/graph_init.py`) -- the 4 functions handling `--graph` chain/DAG initialization (~180 lines) moved from `cli.py` to `core/graph_init.py` with explicit parameters instead of `argparse.Namespace`. Functions: `resolve_export_dirs()`, `copy_and_patch_exports()`, `init_chain_linear()`, `init_chain_dag()`.

- **Refactoring: extracted `_build_with_cmake()` into `Platform` base class** -- the identical CMake configure+build sequence previously duplicated across 5 platforms (CLAP, VST3, LV2, SC, AU) is now a single 30-line method in `platforms/base.py`. AU and Max retain platform-specific pre-checks before delegating. Uses `self.name` for the `BuildResult.platform` field, eliminating hardcoded platform name strings.

- **Refactoring: extracted `_clean_build_dir()` into `Platform` base class** -- the identical `rm -rf build/` logic duplicated in 6 platforms (CLAP, VST3, LV2, SC, AU, Max) is now a 3-line method in `platforms/base.py`.

- **Refactoring: collapsed `templates/__init__.py`** -- replaced 274 lines of 22 repetitive getter/lister functions with a single generic `get_templates_dir(platform)` function plus 11 one-liner backward-compatible aliases. Removed all `list_*_templates()` functions (zero callers). Removed `get_max_templates_dir()` side effect (directory creation).

- **Refactoring: consolidated dual `GENEXT_VERSION`** -- removed the duplicate `GENEXT_VERSION = "0.8.0"` from `ProjectGenerator` in `core/project.py`. All references now use `Platform.GENEXT_VERSION` from `platforms/base.py` as the single source of truth.

- **Refactoring: `PluginCategory` enum** (`platforms/base.py`) -- replaced string-based plugin type detection across AU, LV2, and VCV Rack with a structured `PluginCategory` enum (`EFFECT`, `GENERATOR`). Each platform maps enum values to platform-specific strings via `_AU_TYPE_MAP`, `_LV2_TYPE_MAP`, `_VCR_TAG_MAP`. Factory method `PluginCategory.from_num_inputs()` centralizes the 0-inputs-means-generator logic.

- **Renamed `gen_buffer_max.h` to `max_buffer.h`** -- consistency with other platforms' buffer header naming convention (`{platform}_buffer.h`).

### Removed

- Dead `_detect_plugin_type()` methods from CLAP, VST3, LV2, and SuperCollider platforms (defined but never called)

- `_detect_plugin_type()` from VCV Rack and `_detect_au_type()` from AudioUnit (replaced by `PluginCategory` enum)

- 8 identical static `_ext_{platform}.h` template files (replaced by shared parameterized template)

### Added

- **Parametrized cross-platform tests** -- `TestCrossPlatformGeneration` class in `test_platforms.py` with 5 `@pytest.mark.parametrize` tests x 11 platforms = 55 new tests validating common invariants (directory creation, gen~ export copy, buffer header, build system file, buffer declarations)

- **Circle: DAG topology for multi-plugin mode (Phase 2)** -- the `--graph` flag now supports arbitrary directed acyclic graphs, lifting the Phase 1 linear-chain-only restriction
  - Fan-out: a single node's output can feed multiple downstream nodes (zero-copy, shared buffer)
  - Fan-in via mixer nodes: built-in `"type": "mixer"` node type combines multiple inputs with per-input gain parameters (weighted sum)
  - Topological sort (Kahn's algorithm) determines execution order for arbitrary DAGs
  - Per-edge buffer allocation with fan-out sharing -- edges from the same source reuse one buffer
  - Channel mismatch handling: zero-pad missing channels, truncate extras; mixer output channels = max of input channel counts
  - Mixer gain parameters controllable via USB MIDI CC (same mapping as gen~ node params)
  - Connection targeting: `["reverb", "mix:1"]` syntax routes to specific mixer input indices
  - Linear chains detected automatically and still use the simpler Phase 1 codegen path
  - New DAG kernel templates for both DMA and USB audio devices
  - Example DAG graph with fan-out and mixer:
    ```json
    {
      "nodes": {
        "reverb":  { "export": "gigaverb" },
        "delay":   { "export": "spectraldelayfb" },
        "mix":     { "type": "mixer", "inputs": 2 }
      },
      "connections": [
        ["audio_in", "reverb"],
        ["audio_in", "delay"],
        ["reverb",   "mix:0"],
        ["delay",    "mix:1"],
        ["mix",      "audio_out"]
      ]
    }
    ```
- **Graph data model: DAG support** (`src/gen_dsp/core/graph.py`)
  - `Connection` dataclass replacing raw tuples, with optional `dst_input_index` for mixer input targeting
  - `ChainNodeConfig` extended with `node_type` ("gen" / "mixer") and `mixer_inputs` count
  - `validate_dag()`: cycle detection (DFS), connectivity checks, mixer input count validation, MIDI validation
  - `topological_sort()`: Kahn's algorithm for execution ordering
  - `allocate_edge_buffers()`: per-edge buffer assignment with fan-out sharing
  - `resolve_dag()`: resolves gen~ nodes and constructs synthetic manifests for mixer nodes (with `gain_N` parameters)
  - `EdgeBuffer` dataclass for tracking buffer assignments

### Fixed

- **Test infrastructure: FetchContent stale cache** -- build/subbuild directories in the shared FetchContent cache are now cleaned at session start to prevent stale absolute paths from previous pytest temp directories causing CMake build failures

- **Test infrastructure: AU auval resilience** -- `_validate_au()` now verifies codesign success and retries auval with a longer sleep if CoreAudio component discovery is slow under load

## [0.1.9]

### Added

- **Circle: multi-plugin serial chain mode** -- new `--graph` flag on `gen-dsp init` enables chaining multiple gen~ plugins in series on a single Circle bare-metal kernel image
  - JSON graph file defines nodes (gen~ exports), connections (linear audio chain), and MIDI CC mapping
  - Phase 1 supports linear chains only (no fan-out, fan-in, or cycles); non-linear graphs rejected with clear errors
  - Compile-time graph: JSON consumed by Python at project-gen time, generates flat C code (no JSON parser on Pi)
  - Per-node wrapper shims (`_ext_circle_N.cpp/h`) with `#define` macros before `#include`-ing shared `_ext_circle_impl.cpp/h` -- avoids fragile per-target Make variable assignment through Circle's Rules.mk
  - Ping-pong scratch buffers for zero-copy inter-node audio routing
  - USB MIDI CC parameter control at runtime: each node gets a MIDI channel (auto-assigned or explicit), with CC-by-param-index (default) or explicit CC-to-param-name mapping
  - USB always linked in chain mode (even DMA audio boards need USB for MIDI)
  - Channel mismatch handling: scratch buffers sized to max channel count across all nodes; zero-padding for missing channels
  - All 14 board variants supported (I2S, PWM, HDMI, USB audio) with both DMA and USB audio chain templates
  - No buffer support in chain Phase 1 (`WRAPPER_BUFFER_COUNT=0`)
  - Example usage:
    ```bash
    gen-dsp init ./exports -n mychain -p circle --graph chain.json -o ./mychain
    ```
- **Graph data model** (`src/gen_dsp/core/graph.py`) -- pure data model for multi-plugin chain configurations
  - `ChainNodeConfig`, `GraphConfig`, `ResolvedChainNode` dataclasses
  - `parse_graph()`: JSON loading with validation (missing fields, bad types, invalid CC keys)
  - `validate_linear_chain()`: rejects fan-out, fan-in, cycles, missing audio_in/audio_out, bad MIDI values, unconnected nodes, reserved name collisions
  - `extract_chain_order()`: walks connections from audio_in to audio_out
  - `resolve_chain()`: parses exports, builds manifests, assigns default MIDI channels
- **CLI: `--graph` and `--export` flags** for `gen-dsp init`
  - `--graph <path>`: JSON graph file for multi-plugin chain mode (Circle only in Phase 1)
  - `--export <path>`: additional export path (repeatable) for explicit per-node export resolution

### Fixed

- **CLI: `--board` flag accepted for Circle platform** -- previously `--board` was only valid for Daisy; now accepts both `daisy` and `circle` with updated help text listing Circle board variants

- **AudioUnit: parameter default clamping** -- gen~ initial values that exceed the declared `[outputmin, outputmax]` range are now clamped before reporting to the host (e.g. gigaverb `revtime` init=11, max=1 now reports default=1.0 instead of 12.1). Matches the existing clamping in VST3 and CLAP backends.

- **Manifest: parameter defaults from gen~ initial values** -- `parse_params_from_export()` now extracts actual default values from gen~ exports by parsing `pi->defaultvalue` member variable references and looking up their initialization in `reset()`. Previously all defaults were set to `outputmin`, causing incorrect metadata in LV2 TTL files and any backend consuming `manifest.params`. Defaults are clamped to `[min, max]` to handle gen~ values that exceed the declared range.

## [0.1.8]

### Added

- **ChucK: `loadBuffer(name, path)` method** -- chugins can now load WAV audio files into gen~ internal buffers at runtime from ChucK scripts
  - Supports PCM 16-bit, 24-bit, and IEEE float 32-bit WAV files
  - Minimal WAV reader in `ChuckBuffer::loadWav()` (genlib side, no external dependencies)
  - Returns frame count on success, -1 on error
  - Example: `eff.loadBuffer("sample", "amen.wav")`
- **ChucK: runtime validation in build integration tests** -- all 4 build tests now load the compiled chugin in the ChucK VM and verify correct operation (previously only gigaverb had runtime validation)
  - Audio flow validation: feeds Noise (effects) or Phasor (position-controlled sample players) through the chugin and asserts non-zero energy in the output
  - Buffer loading validation: RamplePlayer test loads a WAV file via `loadBuffer()` and verifies audio playback from the internal gen~ buffer
  - Parameter metadata validation: verifies `numParams()` and `paramName()` return expected values

- **LV2: lilv-based runtime validation in build integration tests** -- all 4 build tests now instantiate the plugin via a custom C validator that uses the lilv API to load, connect ports, process 8 blocks of audio, and verify non-zero output energy
  - Validator compiled once from C source using `pkg-config lilv-0` and cached in `build/.lv2_validator/`
  - Validates port counts (audio in/out, control params), successful instantiation, and audio flow
  - Bundle copied to isolated temp directory to avoid lilv scanning noise
  - Gracefully skipped when `lilv-0` pkg-config is not available

- **SuperCollider: sclang + scsynth NRT runtime validation in build integration tests** -- all 4 build tests now compile a SynthDef via sclang and render audio via scsynth in non-realtime mode
  - Two-phase validation: sclang compiles the `.sc` class and builds a binary SynthDef, then scsynth renders NRT audio using the `.scx` plugin
  - Verifies: class compilation, UGen binary loading, audio processing with non-zero output energy
  - Custom OSC binary score generation from Python (no external dependencies)
  - sclang library config (`-l`) includes standard SCClassLibrary + custom class directory
  - Tool discovery: PATH > `SCLANG`/`SCSYNTH` env vars > standard macOS app bundle
  - Gracefully skipped when sclang, scsynth, or SCClassLibrary not available

- **PureData: build integration tests and runtime validation** -- new `test_pd.py` with 12 tests covering all 3 fixtures
  - Build tests: generate and compile PD externals (gigaverb, RamplePlayer, spectraldelayfb) plus clean/rebuild
  - Runtime validation: loads each compiled external in headless PD (`pd -nogui -verbose`) and verifies successful instantiation (no "couldn't create" errors)
  - Gated by `pd` availability on PATH

- **VCV Rack: headless runtime validation in build integration tests** -- all 3 build tests now load the compiled plugin in VCV Rack headless mode and verify correct operation
  - Plugin copied to isolated temp user dir (`--user <tmpdir>`) with minimal autosave patch that instantiates the module
  - `/dev/null` stdin causes Rack to load plugins, process the patch, then exit cleanly (~0.6s)
  - Log-based validation: asserts "Loaded plugin <slug>" present and "Could not create module" absent
  - Rack binary discovery: PATH > `RACK_APP` env var > well-known macOS app bundle paths
  - Gracefully skipped when VCV Rack is not installed

### Fixed

- **VCV Rack: plugin.json version** -- changed from `"1.0.0"` to `"2.0.0"` to match VCV Rack 2 ABI version (Rack rejects plugins with mismatched major version)
- **PureData: bundle `m_pd.h` in package** -- PureData externals can be built without a system PureData installation; the Pd API header is included in generated projects under `pd-include/` (overridable via `PDINCLUDEDIR`)
- **CMake: `FETCHCONTENT_BASE_DIR` cache fix** -- `GEN_DSP_CACHE_DIR` and `--shared-cache` now actually cache SDK build artifacts across runs; previously the normal `set()` was silently overridden by FetchContent's own `CACHE` variable, causing full SDK recompilation every build (e.g. VST3: 52s → 3s)

## [0.1.7]

### Fixed

- **CLAP: full clap-validator conformance** -- all non-skipped validator tests pass (10/10 passed, 10 skipped for unimplemented extensions)
  - Fixed macOS bundle structure: CLAP on macOS must be a proper bundle directory (`Contents/MacOS/`), not a flat shared library (was failing `dlopen` via `CFBundle`)
  - Fixed parameter queryability: gen state now created eagerly in factory function so `get_value()` works before activation
  - Fixed deactivate lifecycle: gen state kept alive through deactivate so parameters remain queryable (CLAP spec requires this)
  - Fixed parameter default clamping: gen~ initial values may exceed declared range
- **VST3: full SDK validator conformance** -- all 47 validator tests pass (was crashing during Silence Flags test for multi-channel plugins)
  - Fixed bus speaker arrangements: use correct channel count from gen~ export instead of always kStereo (caused buffer overrun crash for plugins with != 2 channels, e.g. spectraldelayfb 3in/2out)
  - Fixed parameter unitId: changed `RangeParameter` unitId from `(ParamID)i` to `0` (kRootUnitId) so parameters reference the root unit instead of nonexistent unit IDs
  - Fixed parameter default clamping: gen~ initial values may exceed declared `[outputmin, outputmax]` range (e.g. gigaverb revtime init=11, max=1), causing out-of-range normalized defaults
- **AudioUnit: full `auval` conformance** -- comprehensive rewrite of `gen_ext_au.cpp` to pass Apple's `auval -v` validation tool
  - Manufacturer code changed from `gdsp` to `Gdsp` (Apple requires at least one non-lowercase character in OSType)
  - Added `version` integer to Info.plist AudioComponents dict (required for CoreAudio component registration)
  - Added property listener support: `AddPropertyListener`, `RemovePropertyListenerWithUserData` with tracked callbacks and `FirePropertyChanged()` on `MaxFramesPerSlice` change
  - Added `PresentPreset` property (get/set current preset name and number)
  - Added `ClassInfo` state save/restore via CFDictionary with version, component description, name, and parameter data blob
  - Added `MakeConnection` property for AU-to-AU input pulling via `AudioUnitRender`
  - Added `AddRenderNotify` / `RemoveRenderNotify` selector stubs
  - Fixed parameter retention across `Reset` and `Initialize` (save/restore cycle)
  - Fixed channel validation in `SetStreamFormat` to reject mismatched channel counts (prevents buffer overflows during render)
  - Fixed `Latency` / `TailTime` scope checking (only valid for `kAudioUnitScope_Global`)
  - Fixed NULL `mData` crash in render: host may pass NULL `AudioBufferList.mData` expecting plugin to provide buffers
  - Gen state now created eagerly in factory function (parameter names available before `Initialize`)
  - `MaxFramesPerSlice` change while initialized now recreates gen state with parameter save/restore

### Added

- **VST3 SDK validator in build integration tests** -- all 4 VST3 build tests now run the SDK `validator` tool after compilation to verify conformance
  - Validator binary built once per session from SDK hosting examples (persistent cache in `build/.vst3_validator/`)
  - Reuses shared FetchContent SDK source to avoid duplicate downloads
  - Gracefully skipped if validator build fails
- **`auval` validation in AU build integration tests** -- all 4 AU build tests now run `auval -v` after compilation to verify conformance
  - Component copied to `~/Library/Audio/Plug-Ins/Components/` for CoreAudio discovery, cleaned up after validation
  - Gated by `auval` availability on PATH
- **clap-validator in CLAP build integration tests** -- all 4 CLAP build tests now run `clap-validator validate` after compilation
  - Validator binary built once per session from clap-validator Rust source (persistent cache in `build/.clap_validator/`)
  - Gated by `cargo` availability on PATH

## [0.1.6]

### Added

- **Manifest IR** (`src/gen_dsp/core/manifest.py`) -- front-end-agnostic intermediate representation decoupling parsing from platform generation
  - `Manifest` dataclass: `gen_name`, `num_inputs`, `num_outputs`, `params`, `buffers`, `source`, `version` with JSON/dict serialization
  - `ParamInfo` dataclass: `index`, `name`, `has_minmax`, `min`, `max`, `default` (replaces duplicated SC/LV2 `ParamInfo`)
  - `parse_params_from_export()`: consolidated parameter parsing regex (was duplicated in SC and LV2)
  - `manifest_from_export_info()`: builds a Manifest from a parsed gen~ ExportInfo
- **`gen-dsp manifest` CLI command** -- emits the parsed Manifest as JSON to stdout without generating a project
  ```bash
  gen-dsp manifest ./path/to/export [--buffers ...]
  ```
- **`manifest.json` emitted to project root** on every `gen-dsp init` -- machine-readable provenance file describing I/O, parameters, buffers, and tool version
- Parameter metadata now available to all 11 platform backends via `manifest.params` (previously only SC and LV2 parsed params)

### Changed

- **`Platform.generate_project()` signature**: `(export_info, output_dir, lib_name, buffers, config)` -> `(manifest, output_dir, lib_name, config)` -- buffers moved into Manifest
- All 11 platform implementations updated to accept `Manifest` instead of `ExportInfo` + `buffers`
- SC and LV2 backends no longer re-parse gen~ `.cpp` for parameter metadata; they consume `manifest.params` directly
- LV2 TTL `lv2:default` now uses `ParamInfo.default` (was hardcoded to `output_min`)

### Removed

- Duplicated `ParamInfo` dataclass from `platforms/supercollider.py` and `platforms/lv2.py`
- Duplicated `_PARAM_BLOCK_RE` regex from both files
- Duplicated `_parse_params()` method from both platform classes

## [0.1.5]

### Added

- **Circle (Raspberry Pi bare metal) platform support** with Make-based cross-compilation
  - Generates bare-metal kernel images (`.img`) for Raspberry Pi Zero through Pi 5 using the [Circle](https://github.com/rsta2/circle) C++ framework (no OS)
  - 14 board variants via `--board` flag covering 4 audio output types:
    - **I2S**: `pi0-i2s`, `pi0w2-i2s`, `pi3-i2s`, `pi4-i2s`, `pi5-i2s` (external DAC: PCM5102A, PCM5122, etc.)
    - **PWM**: `pi0-pwm`, `pi0w2-pwm`, `pi3-pwm`, `pi4-pwm` (built-in 3.5mm headphone jack)
    - **HDMI**: `pi3-hdmi`, `pi4-hdmi`, `pi5-hdmi` (HDMI audio output)
    - **USB**: `pi4-usb`, `pi5-usb` (USB DAC / audio interface)
  - Cross-compilation: `arm-none-eabi-gcc` (32-bit Pi Zero) or `aarch64-none-elf-gcc` (64-bit Pi 3/4/5)
  - Custom genlib runtime (`genlib_circle.cpp`) with heap-backed bump allocator (16MB pool)
  - Universal sample conversion via `GetRangeMin()`/`GetRangeMax()` works across all audio device types
  - DMA-based audio devices (I2S, PWM, HDMI) share one template; USB gets a separate template with `CUSBHCIDevice` init
  - GNU Make `override` directives ensure project RASPPI/AARCH/PREFIX take precedence over Circle's `Config.mk`
  - Circle SDK auto-cloned and built on first use (`git clone --depth 1 --branch Step50.1`)
  - SDK resolution priority: `CIRCLE_DIR` env var > `GEN_DSP_CACHE_DIR` env var > OS-appropriate cache path
  - Boot partition `config.txt` generated with audio-device-specific settings
  - `cmath` shim header included in generated projects -- Circle's `Rules.mk` adds `-nostdinc++` which strips C++ standard library include paths; the shim wraps `<math.h>` so genlib's `#include <cmath>` resolves correctly
  - Compiler prerequisite check: `ensure_circle()` verifies `aarch64-none-elf-gcc` is on PATH before attempting SDK clone/build, with download instructions pointing to ARM GNU Toolchain
  - 32-bit float signal processing (`GENLIB_USE_FLOAT32`)
  - Buffer support via `CircleBuffer` class (same pattern as other backends)
  - Platform key: `"circle"`, default board: `pi3-i2s`

## [0.1.4]

### Added

- **Per-platform documentation guides** in `docs/backends/`
  - 11 standalone guides (one per DSP target): puredata, max, chuck, audiounit, clap, vst3, lv2, supercollider, vcvrack, daisy, circle
  - Each guide covers prerequisites, quick start, architecture (header isolation, signal format, plugin type detection), parameters, buffers, build details (SDK versions, compile flags, shared cache), install paths, and troubleshooting
  - FetchContent-based platforms (CLAP, VST3, LV2, SC) document `FETCHCONTENT_SOURCE_DIR_<NAME>` for using a pre-existing local SDK
- **Platform guides link table** in README cross-platform support section

- **Cross-platform build examples workflow** (`build-examples.yml`) with `fail-fast: false`
  - Matrix of 9 platforms x 3 OSes (macOS, Linux, Windows) with appropriate exclusions
  - All platform builds now pass on all supported OSes: macOS (all 9), Linux (all except AU), Windows (CLAP, VST3, SC)
  - FetchContent SDK cache shared across runs via `actions/cache` and `GEN_DSP_CACHE_DIR`

### Changed

- **README condensed** from ~745 to ~480 lines by replacing verbose per-platform sections with compact summaries linking to the detailed guides
  - Removed duplicated plugin details, API docs, and comparison tables (now in individual guides)
  - Each platform section retains a quick start snippet and one-line description

### Fixed

- **Windows: UTF-8 encoding** across all file I/O operations (14 source files)
  - Python defaults to cp1252 on Windows; explicit `encoding="utf-8"` on every `read_text()`/`write_text()` call prevents decode errors on gen~ exports
- **Windows: CMake backslash path escaping** in FetchContent cache paths
  - `GEN_DSP_CACHE_DIR` on Windows produces backslash paths (e.g. `D:\a\...`) which CMake 3.31's `cmake_language(EVAL)` inside FetchContent re-parses as escape sequences (`\a` = invalid escape)
  - Fixed with `file(TO_CMAKE_PATH ...)` in all 4 CMake templates (CLAP, VST3, LV2, SC) to normalize env var paths to forward slashes
  - Python-side `Path.as_posix()` for baked-in `--shared-cache` paths
- **Windows: CLAP designated initializers** require C++20 under MSVC
  - MSVC enforces strict C++20 requirement for `.field = value` syntax; GCC/Clang accept it as a C++17 extension
  - CLAP CMake template bumped from C++17 to C++20
- **Linux: PureData `t_sample` typedef conflict and `exp2` overload ambiguity**
  - Added `-DGENLIB_USE_FLOAT32 -DWIN32 -DGENLIB_NO_DENORM_TEST` to PD Makefile `forLinux` section, matching all other platforms
  - `GENLIB_USE_FLOAT32` resolves `t_sample` double-vs-float mismatch; `WIN32` suppresses genlib's inline `exp2`/`trunc` that conflict with system math headers on Linux
- **macOS: PureData CI builds** now download `m_pd.h` and set `PDINCLUDEDIR` since PureData is not pre-installed on CI runners

## [0.1.3]

### Added

- **GitHub Actions CI workflow** with 3 jobs: `lint` (ruff + mypy), `test` (unit tests on Python 3.10 + 3.12), `build` (full C++ compilation integration tests on Ubuntu + macOS)
  - FetchContent SDK cache persisted across runs via `actions/cache`
  - ARM cross-compiler (`gcc-arm-none-eabi`) installed on Linux for Daisy build tests
  - All 10 platforms covered across the two runners (AU macOS-only, Daisy Linux-only, rest on both)
- **Preliminary Windows support** in CMake templates for CLAP, LV2, SuperCollider, and VST3
  - MSVC-compatible compiler flags (`/wd4101 /wd4244`) alongside GCC/Clang `-Wno-*` flags
  - Windows install paths: `%COMMONPROGRAMFILES%/CLAP`, `%APPDATA%/LV2`, `%LOCALAPPDATA%/SuperCollider/Extensions`
  - Correct binary suffixes: `.dll` for LV2, `.scx` for SuperCollider on Windows
- **Daisy (Electrosmith) embedded platform support** with Make-based cross-compilation
  - Generates Daisy Seed firmware binaries (`.bin`) from gen~ exports for the STM32H750-based audio platform
  - First cross-compilation target: requires `arm-none-eabi-gcc` (ARM GCC toolchain)
  - Custom genlib runtime (`genlib_daisy.cpp`) replaces standard `genlib.cpp` with two-tier bump allocator:
    - SRAM pool (~450KB, fast) allocated at init; SDRAM pool (64MB, `.sdram_bss` section) for overflow
    - No-op `free` (bump allocator never frees individually); no heap fragmentation
  - libDaisy auto-cloned and built on first use via `git clone --recurse-submodules --depth 1` (pinned to v7.1.0)
  - SDK resolution priority: `LIBDAISY_DIR` env var > `GEN_DSP_CACHE_DIR` env var > OS-appropriate cache path
  - Non-interleaved audio callback matches gen~ directly (zero-copy for stereo)
  - Auto-maps `min(gen_channels, 2)` hardware channels; extra gen~ I/O uses scratch buffers
  - 32-bit float signal processing (`GENLIB_USE_FLOAT32`)
  - v1 targets Daisy Seed only (2in/2out stereo, no built-in controls); board targets (Pod, Patch, etc.) can be added later
  - Parameters retain gen~ defaults; users modify `gen_ext_daisy.cpp` to add ADC reads for knobs/CV
  - Buffer support via `DaisyBuffer` class (same pattern as other backends)
  - Platform key: `"daisy"`

### Changed

- **Build instructions modernized** to use `cmake -B build && cmake --build build` instead of `mkdir -p build && cd build && cmake .. && cmake --build .` across all CMake-based platforms (AU, CLAP, VST3, LV2, SC) and Makefile example targets

### Fixed

- Ambiguous variable name `l` in list comprehensions (`tests/test_cli.py`, `tests/test_daisy.py`) flagged by ruff E741
- Ruff formatting inconsistencies in `cli.py`, `daisy.py`, `test_daisy.py`

## [0.1.2]

### Added

- **VCV Rack module platform support** with Make-based build system
  - Generates VCV Rack plugins (`plugin.dylib`/`.so`/`.dll`) from gen~ exports
  - Uses the Rack SDK's Makefile-based build (`plugin.mk`); requires `RACK_DIR` env var
  - Per-sample processing: gen~'s `perform()` called with `n=1` for zero-latency (VCV Rack's `process()` runs once per sample)
  - Voltage scaling: gen~ audio [-1, 1] mapped to VCV standard +/-5V; parameters map directly (gen~ min/max = knob min/max)
  - Parameter metadata (names, ranges) queried from gen~ at module construction time via temporary state
  - Auto-generates `plugin.json` manifest with module slug, tags (`Effect` vs `Synth Voice`), and brand info
  - Auto-generates minimal dark panel SVG sized to component count (6/10/16/24 HP)
  - Auto-layout widget: screws at corners, knobs for params, ports for I/O, arranged in columns (max 9 per column)
  - Auto-detects effect vs generator from input count
  - 32-bit float signal processing (`GENLIB_USE_FLOAT32`)
  - Buffer support via `VcvrackBuffer` class (same pattern as LV2/SC/etc.)
  - Cross-platform: macOS, Linux, Windows
  - Platform key: `"vcvrack"`

- **SuperCollider UGen platform support** with CMake-based build system
  - Generates cross-platform SC UGens (`.scx` on macOS, `.so` on Linux) from gen~ exports
  - SuperCollider plugin interface headers fetched via CMake FetchContent (URL tarball, pinned to Version-3.13.0)
  - Uses `FetchContent_Populate` with manual include dirs (`plugin_interface/`, `common/`) since we only need headers
  - UGen struct extends SC's `Unit`, holds opaque `GenState*`; registered via `fDefineUnit()` with capitalized name
  - Input layout: audio inputs first (0..N-1), then parameters (N..N+P-1) as control-rate via `IN0()`
  - Zero-copy audio: SC's `IN()`/`OUT()` return `float*` buffers passed directly to gen~'s `float**` (`GENLIB_USE_FLOAT32`)
  - Generates `.sc` class file at project-gen time with parameter names/defaults parsed from gen~ exports
  - `.sc` class extends `MultiOutUGen` (num_outputs > 1) or `UGen` (single output); includes `checkInputs` for audio-rate validation
  - Auto-detects effect vs generator from input count
  - Ad-hoc code signing on macOS; cross-platform install targets (macOS + Linux)
  - No vendored dependencies -- first configure requires network access, cached afterward
  - Platform key: `"sc"`

## [0.1.1]

### Added

- **LV2 plugin platform support** with CMake-based build system
  - Generates cross-platform `.lv2` plugin bundles from gen~ exports
  - Header-only LV2 C API (ISC licensed), fetched via CMake FetchContent (pinned to v1.18.10)
  - Uses `FetchContent_Populate` (not `MakeAvailable`) since LV2 uses Meson, not CMake
  - Port-based I/O model: individual `float*` per port, collected into arrays and passed to `wrapper_perform()`
  - TTL metadata files (`manifest.ttl`, `<name>.ttl`) generated in Python at project-gen time with real parameter names and ranges parsed from gen~ export code
  - 32-bit float signal processing (`GENLIB_USE_FLOAT32`)
  - Auto-detects `EffectPlugin` vs `GeneratorPlugin` from input count
  - Plugin URI: `http://gen-dsp.com/plugins/<lib_name>`
  - Port layout: control params first (indices 0..N-1), then audio inputs, then audio outputs
  - `.lv2` bundle directory assembled via CMake post-build commands (binary + 2 TTL files)
  - Ad-hoc code signing on macOS; cross-platform install targets (macOS + Linux)
  - `_sanitize_symbol()` ensures parameter names are valid LV2 symbols (C identifiers)
  - No vendored dependencies -- first configure requires network access, cached afterward
- **Shared FetchContent cache** for CLAP, VST3, and LV2 backends
  - `--shared-cache` flag on `gen-dsp init` bakes an OS-appropriate cache path into CMakeLists.txt so multiple projects share one SDK download
  - `GEN_DSP_CACHE_DIR` environment variable support in all generated CMakeLists.txt for build-time override (highest priority, no init flag needed)
  - Cache paths: `~/Library/Caches/gen-dsp/fetchcontent/` (macOS), `$XDG_CACHE_HOME/gen-dsp/fetchcontent/` (Linux), `%LOCALAPPDATA%/gen-dsp/fetchcontent/` (Windows)
  - Both mechanisms are opt-in; default behavior (project-local downloads) is unchanged
  - Warning emitted when `--shared-cache` is used with non-CMake platforms (pd, max, chuck, au)
  - Development Makefile exports `GEN_DSP_CACHE_DIR` so `make example-clap`/`example-vst3`/`example-lv2` share the test fixture cache automatically
- **VST3 plugin platform support** with CMake-based build system
  - Generates cross-platform `.vst3` plugin bundles from gen~ exports
  - Steinberg VST3 SDK (`SingleComponentEffect`) fetched via CMake FetchContent (pinned to `v3.7.9_build_61`)
  - Zero-copy audio processing: VST3's non-interleaved `channelBuffers32[channel][sample]` matches gen~'s `float**` exactly
  - 32-bit float signal processing (`GENLIB_USE_FLOAT32`)
  - Auto-detects `Fx` (effect) vs `Instrument|Synth` from input count
  - Deterministic 128-bit FUID from MD5 of `com.gen-dsp.vst3.<lib_name>`
  - Parameters exposed as `RangeParameter` with real min/max/default; normalized-to-plain conversion in process
  - State save/restore via `IBStreamer` binary serialization
  - Platform entry points: `macmain.cpp` (macOS), `linuxmain.cpp` (Linux), `dllmain.cpp` (Windows)
  - Ad-hoc code signing on macOS; cross-platform support (macOS + Linux + Windows)
  - GPL3/proprietary dual license (users needing proprietary license must obtain from Steinberg)
- **CLAP plugin platform support** with CMake-based build system
  - Generates cross-platform `.clap` plugin files from gen~ exports
  - Header-only CLAP C API (MIT licensed), fetched via CMake FetchContent (pinned to v1.2.2)
  - Zero-copy audio processing: CLAP's non-interleaved `data32[channel][sample]` matches gen~'s `float**` exactly
  - 32-bit float signal processing (`GENLIB_USE_FLOAT32`)
  - Auto-detects `audio_effect` vs `instrument` from input count
  - Extensions: `audio-ports` (I/O port info), `params` (full parameter interface with automation)
  - Plugin ID: `com.gen-dsp.<lib_name>`
  - Ad-hoc code signing on macOS; cross-platform install targets (macOS + Linux)
  - No vendored dependencies -- first configure requires network access, cached afterward
- **AudioUnit (AUv2) platform support** with CMake-based build system
  - Generates macOS `.component` bundles from gen~ exports
  - Raw AUv2 C API (`AudioComponentPlugInInterface`) -- no Apple AudioUnitSDK dependency
  - Only requires system frameworks: AudioToolbox, CoreFoundation, CoreAudio
  - 32-bit float signal processing (`GENLIB_USE_FLOAT32`)
  - Auto-detects `aufx` (effect) vs `augn` (generator) from input count
  - Full AU property dispatch: StreamFormat, ParameterList/Info, MaxFramesPerSlice, ElementCount, Latency, TailTime, SupportedNumChannels, FactoryPresets
  - Render callback input pull for effects; direct output for generators
  - Ad-hoc code signing via CMake post-build step
  - 4-char subtype derived from lib name; manufacturer code `gdsp`
  - Buffer support via `AuBuffer` class (same pattern as ChucK)
- **ChucK chugin platform support** with make-based build system
  - Generates ChucK chugins (.chug) from gen~ exports
  - 32-bit float signal processing (matches ChucK's `SAMPLE = float`)
  - Multi-channel I/O via `CK_DLL_TICKF` with per-frame deinterleave/interleave
  - Generic `param(string, float)` setter and `param(string)` getter for runtime parameter control
  - `info()` and `reset()` methods on the chugin class
  - Buffer support via `ChuckBuffer` class (allocated, zero-filled)
  - Bundled `chugin.h` header -- no external ChucK SDK dependency needed
  - Platform-specific makefiles for macOS (`makefile.mac`) and Linux (`makefile.linux`)
  - Workaround for genlib `exp2`/`trunc` redefinition conflicts with modern C++ stdlib
  - Capitalized class name follows ChucK convention (e.g. `Gigaverb`, not `gigaverb`)
- Integration tests for ChucK: build compilation and ChucK runtime load verification
- Makefile targets for generating example plugins: `example-pd`, `example-max`, `example-chuck`, `example-au`, `example-clap`, `example-vst3`, `example-lv2`, `examples`
  - Configurable via `FIXTURE`, `NAME`, and `BUFFERS` variables

### Fixed

- **Parser bug**: `_find_main_files()` filtered by absolute path (`"gen_dsp" not in str(f)`), which excluded all `.cpp` files when the project directory contained "gen_dsp". Fixed to check only the file's parent directory name (`f.parent.name != "gen_dsp"`)
- **PD template filename mismatch**: template file `gen_ext.cpp` was renamed to `gen_dsp.cpp` to match what `puredata.py` and the Makefile template expect

### Changed

- **Strict mypy compliance** across all platform modules
  - `Platform.extension` changed from class attribute to `@property @abstractmethod` so subclass `@property` overrides are type-safe
  - `generate_project()` `config` parameter typed as `Optional[ProjectConfig]` in base class and all 7 platform subclasses
  - `run_command()` return type narrowed to `CompletedProcess[str]`
  - Fixed `process.stdout` iteration guard in verbose mode
  - Fixed variable shadowing in CLI error reporting loop
- **Platform registry refactor** for easier addition of new backends
  - Added `PLATFORM_REGISTRY` dict in `platforms/__init__.py` for dynamic platform lookup
  - New helper functions: `get_platform()`, `get_platform_class()`, `list_platforms()`, `is_valid_platform()`
  - Adding a new platform now requires only 3 steps (create class, import, add to registry)
  - Eliminated hardcoded platform selection in `builder.py`, `project.py`, and `cli.py`
- Extracted common code to `Platform` base class
  - `generate_buffer_header()` - shared buffer header generation
  - `run_command()` - shared subprocess execution with output streaming
  - `get_build_instructions()` - returns platform-specific build commands for CLI output
- CLI platform choices now dynamically populated from registry
- Reduced code duplication in platform implementations (~100 lines removed)

### Added

- `ADDING_NEW_BACKENDS.md` - comprehensive guide for implementing new platform backends
- `tests/test_platforms.py` - 18 new tests for platform registry and implementations

## [0.1.0]

### Added

- Python package with CLI (`gen-dsp`) for automated project generation
- `gen-dsp init` command to create projects from gen~ exports
- `gen-dsp build` command to compile externals
- `gen-dsp detect` command to analyze gen~ exports (buffers, I/O, parameters)
- `gen-dsp patch` command to apply platform-specific fixes
- Automatic buffer detection from gen~ export code
- Automatic exp2f -> exp2 patch for macOS compatibility
- JSON output option for `detect` command
- Dry-run mode for `init` and `patch` commands
- Comprehensive test suite
- **Max/MSP platform support** with CMake build system
  - Generates Max externals (.mxo on macOS, .mxe64 on Windows)
  - Uses max-sdk-base submodule for SDK integration (auto-cloned by `build` command)
  - Native 64-bit signal processing (matches Max's double precision)
  - Thread-safe buffer access via t_buffer_ref lock/unlock API
  - Isolated compilation units to avoid type conflicts between Max SDK and genlib

### Changed

- Converted from manual template-based workflow to Python package
- Templates now bundled inside the package
- Examples moved to test fixtures

### Removed

- Manual `template/` directory (now bundled in package)
- Manual `example/` directory (moved to `tests/fixtures/`)

## [0.0.9]

### Added

- Initial release as template-based workflow
- Support for PureData external generation
- Buffer support (up to 5 single-channel buffers)
- Custom sample rate and block size messages (`pdsr`, `pdbs`)
- Buffer remapping via `pdset` message
- Examples: gigaverb, RamplePlayer, spectraldelayfb

### Notes

- Tested with Max 8.3.2 and Max 9
- Targets Organelle synth but works on macOS and Linux
