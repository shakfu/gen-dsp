# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
