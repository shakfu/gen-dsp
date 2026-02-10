# SuperCollider

Generates cross-platform SuperCollider UGens (`.scx` on macOS/Windows, `.so` on Linux) from gen~ exports using CMake and the SC plugin interface headers.

**OS support:** macOS, Linux, Windows

## Prerequisites

- Python >= 3.10
- CMake >= 3.19
- C/C++ compiler (clang, gcc, or MSVC)
- Network access on first configure (to fetch SC plugin headers, ~80MB tarball; cached afterward)

## Quick Start

```bash
# Create a SuperCollider project
gen-dsp init ./my_export -n myeffect -p sc -o ./myeffect_sc

# Build
cd myeffect_sc
mkdir -p build && cd build
cmake .. && cmake --build .

# Output: build/myeffect.scx (macOS/Windows) or build/myeffect.so (Linux)
```

Or use `gen-dsp build`:

```bash
gen-dsp build ./myeffect_sc -p sc
```

## How It Works

gen-dsp uses **header isolation** to separate SC plugin API code from genlib code:

- `gen_ext_sc.cpp` -- SuperCollider-facing wrapper (includes only SC plugin interface headers)
- `_ext_sc.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext_sc.h` -- C interface connecting the two sides via an opaque `GenState*` pointer

The UGen struct extends SC's `Unit`, holds a `GenState*`, and is registered via `fDefineUnit()` in the `PluginLoad` entry point.

**Signal type:** float (32-bit). gen~ is compiled with `GENLIB_USE_FLOAT32`.

**Audio format:** Block-based, zero-copy -- SC's `IN()`/`OUT()` buffers are passed directly to gen~'s `float**` perform function.

**UGen naming:** SC class names must start with an uppercase letter. The lib_name is automatically capitalized: `myeffect` becomes `Myeffect`, `gigaverb` becomes `Gigaverb`.

**Plugin type detection:** Automatic based on I/O -- effects have audio inputs, generators have none.

## Parameters

**Input layout:** audio inputs first (indices 0..N-1), then parameters (indices N..N+P-1) at control rate.

All gen~ parameters are exposed as SC UGen inputs with real names and default values parsed from the gen~ export `.cpp` file.

## Buffers

Buffer support follows the standard gen-dsp pattern. Up to 5 single-channel buffers are supported.

## Build Details

- **Build system:** CMake with FetchContent
- **SDK:** SC plugin_interface headers fetched via CMake FetchContent (URL tarball, tag `Version-3.13.0`)
- **Include paths:** `plugin_interface/` and `common/` from the SC source tree
- **Code signing:** ad-hoc signed on macOS during build
- **Compile flags:** `-DGENLIB_USE_FLOAT32 -DWIN32 -DGENLIB_NO_DENORM_TEST`

### SC Class File

A `.sc` class file is generated at project creation time (alongside the C++ sources). This file tells sclang about the UGen's interface:

- Extends `MultiOutUGen` if the gen~ export has multiple outputs, otherwise `UGen`
- Includes `*ar` method with argument names matching gen~ parameter names
- Includes `checkInputs` validation for audio-rate inputs
- Includes `init` method for multi-output routing

### Shared FetchContent Cache

The SC source tarball is ~80MB. To share across projects:

```bash
# Bake OS-appropriate cache path into CMakeLists.txt
gen-dsp init ./my_export -n myeffect -p sc --shared-cache

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

If you already have the SuperCollider source tree on your system, you can skip the FetchContent download entirely by setting CMake's built-in `FETCHCONTENT_SOURCE_DIR_<NAME>` variable:

```bash
cmake -DFETCHCONTENT_SOURCE_DIR_SUPERCOLLIDER=/path/to/supercollider -B build
```

This tells CMake to use your local source tree instead of downloading the ~80MB tarball. No template or project changes are needed. Only the `include/plugin_interface/` and `include/common/` directories are used, so any SC version with a compatible plugin interface will work.

## Install

Install both the binary and the `.sc` class file:

```bash
# macOS
cp build/myeffect.scx ~/Library/Application\ Support/SuperCollider/Extensions/
cp Myeffect.sc ~/Library/Application\ Support/SuperCollider/Extensions/

# Linux
cp build/myeffect.so ~/.local/share/SuperCollider/Extensions/
cp Myeffect.sc ~/.local/share/SuperCollider/Extensions/
```

## Using in SuperCollider

```supercollider
// Boot the server
s.boot;

// Effect (has audio inputs)
{ Gigaverb.ar(SoundIn.ar([0, 1]), revtime: 0.8, damping: 0.5) }.play;

// Generator (no audio inputs)
{ MyOsc.ar(freq: 440, amp: 0.3) }.play;
```

## Troubleshooting

- **"Class not found" in sclang:** Ensure the `.sc` class file is installed alongside the binary in the Extensions directory. Recompile the class library (`Language > Recompile Class Library` or Cmd+Shift+L).
- **"UGen not installed" at audio boot:** The binary (`.scx`/`.so`) is missing or in the wrong directory. Check the Extensions path with `Platform.userExtensionDir` in sclang.
- **First build is slow:** The SC source tarball is ~80MB. Subsequent builds reuse the cached download. Consider `--shared-cache` if building multiple UGens.
- **Class name must start uppercase:** SC enforces this. gen-dsp handles it automatically, but if you copy files manually, ensure the `.sc` filename matches the capitalized class name (e.g., `Myeffect.sc`, not `myeffect.sc`).
