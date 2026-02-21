# CLAP

Generates cross-platform CLAP plugins (`.clap` bundles on macOS, shared libraries on Linux/Windows) from gen~ exports using CMake and the CLAP C API (header-only, MIT licensed). Passes all [clap-validator](https://github.com/free-audio/clap-validator) conformance tests.

**OS support:** macOS, Linux, Windows

## Prerequisites

- Python >= 3.10
- CMake >= 3.19
- C/C++ compiler (clang, gcc, or MSVC)
- Network access on first configure (to fetch CLAP headers; cached afterward)

## Quick Start

```bash
# Create a CLAP project
gen-dsp init ./my_export -n myeffect -p clap -o ./myeffect_clap

# Build
cd myeffect_clap
cmake -B build && cmake --build build

# Output: build/myeffect.clap (bundle on macOS, .clap file on Linux/Windows)
```

Or use `gen-dsp build`:

```bash
gen-dsp build ./myeffect_clap -p clap
```

## How It Works

gen-dsp uses **header isolation** to separate CLAP API code from genlib code:

- `gen_ext_clap.cpp` -- CLAP-facing wrapper (includes only CLAP headers)
- `_ext_clap.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext_clap.h` -- C interface connecting the two sides via an opaque `GenState*` pointer

**Signal type:** float (32-bit). gen~ is compiled with `GENLIB_USE_FLOAT32`.

**Zero-copy audio:** CLAP's `data32[ch][sample]` layout matches gen~'s `float**` exactly, so audio buffers are passed directly with no copying or format conversion.

**Lifecycle:** Gen state is created eagerly when the plugin factory instantiates the plugin, so parameter values are queryable before activation. The state survives deactivate/reactivate cycles (only destroyed and recreated on activate, or destroyed on plugin destroy).

**Plugin type detection:** Automatic based on I/O configuration:

- `audio_effect` if the gen~ export has audio inputs
- `instrument` if the gen~ export has no audio inputs

## Parameters

All gen~ parameters are exposed via the CLAP params extension. Parameters are automatable by the host.

- **Plugin ID:** `com.gen-dsp.<lib_name>`
- **Extensions:** `audio-ports`, `params`, `state`

## State Save/Restore

The plugin implements the CLAP state extension (`clap_plugin_state_t`), allowing hosts to save and recall presets and session state. Parameters are serialized as a flat binary blob (4-byte magic header + one float per parameter). Stream helpers handle partial reads/writes as required by the CLAP spec. Empty or invalid state data is rejected on load.

## Buffers

Buffer support follows the standard gen-dsp pattern. Up to 5 single-channel buffers are supported.

## Build Details

- **Build system:** CMake with FetchContent
- **SDK:** CLAP headers fetched via CMake FetchContent (tag `1.2.2`)
- **Audio format:** Float32, non-interleaved (zero-copy)
- **Code signing:** ad-hoc signed on macOS during build
- **Compile flags:** `-DGENLIB_USE_FLOAT32 -DWIN32 -DGENLIB_NO_DENORM_TEST`

### Shared FetchContent Cache

By default, each project downloads its own copy of the CLAP headers. To share across projects:

```bash
# Bake OS-appropriate cache path into CMakeLists.txt
gen-dsp init ./my_export -n myeffect -p clap --shared-cache

# Or set at cmake configure time
GEN_DSP_CACHE_DIR=/path/to/cache cmake ..
```

Cache paths by OS:

| OS | Default shared cache path |
|----|--------------------------|
| macOS | `~/Library/Caches/gen-dsp/fetchcontent/` |
| Linux | `$XDG_CACHE_HOME/gen-dsp/fetchcontent/` (defaults to `~/.cache/`) |
| Windows | `%LOCALAPPDATA%/gen-dsp/fetchcontent/` |

### Using a Local SDK

If you already have the CLAP headers on your system, you can skip the FetchContent download entirely by setting CMake's built-in `FETCHCONTENT_SOURCE_DIR_<NAME>` variable:

```bash
cmake -DFETCHCONTENT_SOURCE_DIR_CLAP=/path/to/clap -B build
```

This tells CMake to use your local copy instead of cloning from GitHub. No template or project changes are needed. CLAP is header-only, so minor version differences are generally tolerable.

## Install

| OS | Install path |
|----|-------------|
| macOS | `~/Library/Audio/Plug-Ins/CLAP/` |
| Linux | `~/.clap/` |
| Windows | `%COMMONPROGRAMFILES%/CLAP/` |

```bash
# macOS (bundle directory)
cp -r build/myeffect.clap ~/Library/Audio/Plug-Ins/CLAP/

# Linux (flat shared library)
cp build/myeffect.clap ~/.clap/
```

## Troubleshooting

- **CMake configure fails on first run:** Network access is required to fetch CLAP headers. Ensure you have internet connectivity. After the first successful configure, headers are cached locally.
- **Plugin not appearing in DAW:** Ensure the `.clap` bundle (macOS) or file (Linux/Windows) is in the correct install path for your OS. On macOS, `myeffect.clap` is a directory -- copy it with `cp -r`. Restart the DAW to rescan plugins.
- **Windows build issues:** CLAP uses C++20 designated initializers, which require MSVC 2019 16.1+ or a recent gcc/clang.
