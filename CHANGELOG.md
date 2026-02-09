# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
- Makefile targets for generating example plugins: `example-pd`, `example-max`, `example-chuck`, `examples`
  - Configurable via `FIXTURE`, `NAME`, and `BUFFERS` variables

### Fixed

- **Parser bug**: `_find_main_files()` filtered by absolute path (`"gen_dsp" not in str(f)`), which excluded all `.cpp` files when the project directory contained "gen_dsp". Fixed to check only the file's parent directory name (`f.parent.name != "gen_dsp"`)
- **PD template filename mismatch**: template file `gen_ext.cpp` was renamed to `gen_dsp.cpp` to match what `puredata.py` and the Makefile template expect

### Changed

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
