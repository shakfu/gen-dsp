# LV2

Generates cross-platform LV2 plugins (`.lv2` bundle directories) from gen~ exports using CMake and the LV2 C API (header-only, ISC licensed).

**OS support:** macOS, Linux

## Prerequisites

- Python >= 3.10
- CMake >= 3.19
- C/C++ compiler (clang, gcc)
- Network access on first configure (to fetch LV2 headers; cached afterward)

## Quick Start

```bash
# Create an LV2 project
gen-dsp init ./my_export -n myeffect -p lv2 -o ./myeffect_lv2

# Build
cd myeffect_lv2
mkdir -p build && cd build
cmake .. && cmake --build .

# Output: build/myeffect.lv2/
```

Or use `gen-dsp build`:

```bash
gen-dsp build ./myeffect_lv2 -p lv2
```

## How It Works

gen-dsp uses **header isolation** to separate LV2 API code from genlib code:

- `gen_ext_lv2.cpp` -- LV2-facing wrapper (includes only LV2 headers)
- `_ext_lv2.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext_lv2.h` -- C interface connecting the two sides via an opaque `GenState*` pointer

**Signal type:** float (32-bit). gen~ is compiled with `GENLIB_USE_FLOAT32`.

**Port-based I/O:** LV2 uses individual `float*` pointers per port (unlike the `float**` arrays used by most other APIs). The wrapper collects these per-port pointers into `float*[]` arrays in `connect_port()` for passing to gen~'s perform function.

**Port layout:** control parameters first (indices 0..N-1), then audio inputs, then audio outputs. This matches the order in the generated TTL files.

**Plugin type detection:** Automatic based on I/O configuration:

- `EffectPlugin` if the gen~ export has audio inputs
- `GeneratorPlugin` if the gen~ export has no audio inputs

## Parameters

All gen~ parameters are exposed as LV2 control input ports. Parameter names and ranges (min/max) are parsed from the gen~ export `.cpp` file using regex on the `pi->name`, `pi->outputmin`, and `pi->outputmax` fields.

- **Plugin URI:** `http://gen-dsp.com/plugins/<lib_name>`
- **Symbol sanitization:** parameter names are converted to valid LV2 symbols (C identifiers) -- non-alphanumeric characters become underscores

## Buffers

Buffer support follows the standard gen-dsp pattern. Up to 5 single-channel buffers are supported.

## Build Details

- **Build system:** CMake with FetchContent
- **SDK:** LV2 headers fetched via CMake FetchContent (tag `v1.18.10`)
- **FetchContent note:** LV2 uses Meson (not CMake) as its build system, so the generated CMakeLists.txt uses `FetchContent_Populate` with a manual include directory instead of `FetchContent_MakeAvailable`
- **Audio format:** Float32, port-based
- **Code signing:** ad-hoc signed on macOS during build
- **Compile flags:** `-DGENLIB_USE_FLOAT32 -DWIN32 -DGENLIB_NO_DENORM_TEST`
- **Binary suffix:** `.dylib` on macOS, `.so` on Linux

### TTL Metadata

Two TTL files are generated at project creation time (not at build time):

- `manifest.ttl` -- plugin discovery metadata (URI, binary location)
- `<name>.ttl` -- full port definitions (control ports with names/ranges, audio ports)

These are copied into the `.lv2` bundle directory during the CMake build.

### Shared FetchContent Cache

By default, each project downloads its own copy of the LV2 headers. To share across projects:

```bash
# Bake OS-appropriate cache path into CMakeLists.txt
gen-dsp init ./my_export -n myeffect -p lv2 --shared-cache

# Or set at cmake configure time
GEN_DSP_CACHE_DIR=/path/to/cache cmake ..
```

Cache paths by OS:

| OS | Default shared cache path |
|----|--------------------------|
| macOS | `~/Library/Caches/gen-dsp/fetchcontent/` |
| Linux | `$XDG_CACHE_HOME/gen-dsp/fetchcontent/` (defaults to `~/.cache/`) |

### Using a Local SDK

If you already have the LV2 headers on your system, you can skip the FetchContent download entirely by setting CMake's built-in `FETCHCONTENT_SOURCE_DIR_<NAME>` variable:

```bash
cmake -DFETCHCONTENT_SOURCE_DIR_LV2=/path/to/lv2 -B build
```

This tells CMake to use your local copy instead of cloning from GitHub. No template or project changes are needed. LV2 is header-only, so minor version differences are generally tolerable.

## Install

| OS | Install path |
|----|-------------|
| macOS | `~/Library/Audio/Plug-Ins/LV2/` |
| Linux | `~/.lv2/` |

```bash
# macOS
cp -r build/myeffect.lv2 ~/Library/Audio/Plug-Ins/LV2/

# Linux
cp -r build/myeffect.lv2 ~/.lv2/
```

The `.lv2` bundle is a directory containing the shared library and both TTL files.

## Troubleshooting

- **CMake configure fails on first run:** Network access is required to fetch LV2 headers. Ensure you have internet connectivity.
- **Plugin not found by host:** Ensure the entire `.lv2` directory (not just the binary) is copied to the install path. The host needs both the binary and the TTL files.
- **Parameter ranges look wrong:** Parameter min/max values are parsed from the gen~ export source code at project creation time. If you modify parameter ranges in your gen~ patch and re-export, re-run `gen-dsp init` to regenerate the TTL files.
- **`lv2:default` vs actual default:** The TTL generator currently uses `output_min` as the default value. If your parameters have a different intended default, edit the generated `<name>.ttl` file.
