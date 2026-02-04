# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [0.8.0] - 2025-02-03

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

## [0.7.0] - 2022-xx-xx

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
