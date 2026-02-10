# VCV Rack

Generates VCV Rack modules with per-sample processing, auto-generated panel SVG, and `plugin.json` manifest from gen~ exports using the Rack SDK's Makefile-based build system.

**OS support:** macOS, Linux, Windows

## Prerequisites

- Python >= 3.10
- C/C++ compiler (clang, gcc)
- make
- VCV Rack SDK (auto-downloaded, or set `RACK_DIR` env var to an existing install)

The Rack SDK is automatically downloaded and cached on first build. No manual SDK installation is required unless you want to use a specific SDK version.

## Quick Start

```bash
# Create a VCV Rack project
gen-dsp init ./my_export -n myeffect -p vcvrack -o ./myeffect_vcvrack

# Build (auto-downloads Rack SDK if needed)
gen-dsp build ./myeffect_vcvrack -p vcvrack

# Output: plugin.dylib (macOS), plugin.so (Linux), or plugin.dll (Windows)
```

Or build manually:

```bash
cd myeffect_vcvrack
export RACK_DIR=/path/to/Rack-SDK  # only if not using auto-download
make
```

## How It Works

gen-dsp uses **header isolation** to separate VCV Rack API code from genlib code:

- `gen_ext_vcvrack.cpp` -- VCV Rack-facing wrapper (includes Rack SDK headers)
- `_ext_vcvrack.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext_vcvrack.h` -- C interface connecting the two sides via an opaque `GenState*` pointer
- `plugin.cpp` / `plugin.hpp` -- Rack plugin registration boilerplate

**Signal type:** float (32-bit). gen~ is compiled with `GENLIB_USE_FLOAT32`.

**Per-sample processing:** gen~'s `perform()` is called with `n=1` per sample from VCV Rack's `process()` callback. This gives zero latency but has higher CPU overhead than block-based processing.

**Voltage scaling:**

- Audio: gen~ [-1, 1] is mapped to VCV standard +/-5V
- Parameters: gen~ min/max maps directly to knob min/max (no voltage scaling)

**Module type detection:** Automatic based on I/O:

- `Effect` tag if the gen~ export has audio inputs
- `Synth Voice` tag if the gen~ export has no audio inputs

## Parameters

All gen~ parameters are exposed as knobs. Parameter names and ranges are queried at module construction time via a temporary gen~ state. The real gen~ state is created lazily on first `process()` call.

## Buffers

Buffer support follows the standard gen-dsp pattern. Up to 5 single-channel buffers are supported.

## Build Details

- **Build system:** make using Rack SDK's `plugin.mk`
- **SDK:** Rack SDK v2.6.1 (auto-downloaded and cached)
- **Compile flags:** `-DGENLIB_USE_FLOAT32 -DWIN32 -DGENLIB_NO_DENORM_TEST`
- **Shared cache:** not applicable (Make-based, not CMake FetchContent)

### Rack SDK Resolution

The Rack SDK location is resolved in priority order:

1. `RACK_DIR` environment variable (explicit override)
2. `GEN_DSP_CACHE_DIR` env var + `rack-sdk-src/Rack-SDK`
3. OS-appropriate gen-dsp cache path (auto-download destination)

Auto-download URLs by platform:

| Platform | SDK archive |
|----------|------------|
| macOS (ARM) | `Rack-SDK-2.6.1-mac-arm64.zip` |
| macOS (x86) | `Rack-SDK-2.6.1-mac-x64.zip` |
| Linux (x86) | `Rack-SDK-2.6.1-lin-x64.zip` |
| Windows (x86) | `Rack-SDK-2.6.1-win-x64.zip` |

### Auto-Generated Assets

- **`plugin.json`:** Module manifest with slug, tags (`Effect` or `Synth Voice`), and brand info
- **Panel SVG:** Dark-themed panel auto-sized to component count:

| Components | Panel width |
|-----------|-------------|
| <= 6 | 6 HP |
| <= 12 | 10 HP |
| <= 20 | 16 HP |
| > 20 | 24 HP |

- **Widget layout:** screws at corners, then knobs for params, input ports, and output ports arranged in columns (max 9 per column)

## Install

Copy the entire plugin directory to VCV Rack's plugins folder:

| OS | Install path |
|----|-------------|
| macOS | `~/Documents/Rack2/plugins/<name>/` |
| Linux | `~/.Rack2/plugins/<name>/` |
| Windows | `%USERPROFILE%/Documents/Rack2/plugins/<name>/` |

The plugin directory must include `plugin.dylib`/`.so`/`.dll`, `plugin.json`, and `res/<name>.svg`.

## Troubleshooting

- **"No Rack SDK download available":** Your platform/architecture combination is not supported. Set `RACK_DIR` to point to a manually installed SDK.
- **`plugin.mk` not found:** The Rack SDK download may have failed or extracted to the wrong location. Delete the cached SDK directory and rebuild to re-download.
- **High CPU usage:** Per-sample processing (`perform(n=1)`) has higher overhead than block-based processing. This is inherent to the VCV Rack architecture (one sample per `process()` call). Complex gen~ patches may need optimization.
- **Module not appearing in VCV Rack:** Ensure the entire plugin directory (not just the binary) is in the plugins folder. VCV Rack requires `plugin.json` to discover modules.
