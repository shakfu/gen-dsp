# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
