# VST3

Generates cross-platform VST3 plugins (`.vst3` bundles) from gen~ exports using CMake and the Steinberg VST3 SDK.

**OS support:** macOS, Linux, Windows

## Prerequisites

- Python >= 3.10
- CMake >= 3.19
- C/C++ compiler (clang, gcc, or MSVC)
- Network access on first configure (to fetch VST3 SDK, ~50MB; cached afterward)

## Quick Start

```bash
# Create a VST3 project
gen-dsp init ./my_export -n myeffect -p vst3 -o ./myeffect_vst3

# Build
cd myeffect_vst3
mkdir -p build && cd build
cmake .. && cmake --build .

# Output: build/VST3/Release/myeffect.vst3/
```

Or use `gen-dsp build`:

```bash
gen-dsp build ./myeffect_vst3 -p vst3
```

## How It Works

gen-dsp uses **header isolation** to separate VST3 SDK code from genlib code:

- `gen_ext_vst3.cpp` -- VST3-facing wrapper (includes only VST3 SDK headers)
- `_ext_vst3.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext_vst3.h` -- C interface connecting the two sides via an opaque `GenState*` pointer

The plugin uses `SingleComponentEffect` -- the simplest VST3 plugin structure that combines the audio processor and edit controller into a single class.

**Signal type:** float (32-bit). gen~ is compiled with `GENLIB_USE_FLOAT32`.

**Zero-copy audio:** VST3's `channelBuffers32[ch][sample]` layout matches gen~'s `float**` exactly, so audio buffers are passed directly with no copying or format conversion.

**Plugin type detection:** Automatic based on I/O configuration:

- `Fx` (effect) if the gen~ export has audio inputs
- `Instrument|Synth` if the gen~ export has no audio inputs

## Parameters

All gen~ parameters are exposed as `RangeParameter` instances with real names, min, max, and default values. Parameters are automatable by the host.

**Plugin FUID:** A deterministic 128-bit ID generated from the MD5 hash of `com.gen-dsp.vst3.<lib_name>`, split into 4 x uint32 and passed to CMake as hex values.

## Buffers

Buffer support follows the standard gen-dsp pattern. Up to 5 single-channel buffers are supported.

## Build Details

- **Build system:** CMake with FetchContent
- **SDK:** Steinberg VST3 SDK fetched via CMake FetchContent (tag `v3.7.9_build_61`)
- **Audio format:** Float32, non-interleaved (zero-copy)
- **Code signing:** ad-hoc signed on macOS during build
- **Compile flags:** `-DGENLIB_USE_FLOAT32 -DWIN32 -DGENLIB_NO_DENORM_TEST`
- **SDK class:** `SingleComponentEffect` (combined processor + controller)

The generated CMakeLists.txt explicitly compiles `vstsinglecomponenteffect.cpp` and platform-specific entry points (`macmain.cpp`, etc.) from the SDK. The SDK's example and VSTGUI options are disabled (`SMTG_ENABLE_VST3_PLUGIN_EXAMPLES=OFF`, `SMTG_ENABLE_VSTGUI_SUPPORT=OFF`).

### Shared FetchContent Cache

By default, each project downloads its own copy of the VST3 SDK (~50MB). To share across projects:

```bash
# Bake OS-appropriate cache path into CMakeLists.txt
gen-dsp init ./my_export -n myeffect -p vst3 --shared-cache

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

If you already have the VST3 SDK on your system, you can skip the FetchContent download entirely by setting CMake's built-in `FETCHCONTENT_SOURCE_DIR_<NAME>` variable:

```bash
cmake -DFETCHCONTENT_SOURCE_DIR_VST3SDK=/path/to/vst3sdk -B build
```

This tells CMake to use your local copy instead of cloning from GitHub. No template or project changes are needed.

Note: the generated project pins SDK tag `v3.7.9_build_61`. If your local SDK is a different version, it will be used as-is with no version check. API differences between versions may cause build failures.

## Install

| OS | Install path |
|----|-------------|
| macOS | `~/Library/Audio/Plug-Ins/VST3/` |
| Linux | `~/.vst3/` |
| Windows | `%COMMONPROGRAMFILES%/VST3/` |

```bash
# macOS
cp -r build/VST3/Release/myeffect.vst3 ~/Library/Audio/Plug-Ins/VST3/

# Linux
cp -r build/VST3/Release/myeffect.vst3 ~/.vst3/
```

## Licensing

The VST3 SDK is **GPL3/proprietary dual licensed**. If you distribute your plugin under a proprietary (non-GPL) license, you must obtain a proprietary license from Steinberg.

## Troubleshooting

- **CMake configure hangs:** The VST3 SDK is ~50MB. The first download may take a while. If it seems stuck, check your network connection. Set `GIT_TERMINAL_PROMPT=0` in your environment to prevent git from prompting for credentials.
- **`STR` macro redefinition warnings:** The VST3 SDK redefines `STR` as `STR16`. The gen-dsp wrapper uses `GSTR()` to avoid this conflict. No action needed.
- **Plugin not appearing in DAW:** Ensure the `.vst3` bundle (it's a directory, not a single file) is in the correct install path. Restart the DAW to rescan.
- **First build is slow:** The VST3 SDK is large. Subsequent builds reuse the cached SDK and are much faster. Consider `--shared-cache` if building multiple plugins.
