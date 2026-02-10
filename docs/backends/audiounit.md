# AudioUnit (AUv2)

Generates macOS AudioUnit v2 plugins (`.component` bundles) from gen~ exports using CMake and the raw AUv2 C API.

**OS support:** macOS only

## Prerequisites

- macOS
- Python >= 3.10
- CMake >= 3.19
- C/C++ compiler (clang via Xcode or Command Line Tools)

```bash
xcode-select --install
```

No external SDK is needed -- only system frameworks (AudioToolbox, CoreFoundation, CoreAudio).

## Quick Start

```bash
# Create an AudioUnit project
gen-dsp init ./my_export -n myeffect -p au -o ./myeffect_au

# Build
cd myeffect_au
mkdir -p build && cd build
cmake .. && cmake --build .

# Output: build/myeffect.component
```

Or use `gen-dsp build`:

```bash
gen-dsp build ./myeffect_au -p au
```

## How It Works

gen-dsp uses **header isolation** to separate AU API code from genlib code:

- `gen_ext_au.cpp` -- AudioUnit-facing wrapper (includes only system AU headers)
- `_ext_au.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext_au.h` -- C interface connecting the two sides via an opaque `GenState*` pointer

The plugin implements `AudioComponentPlugInInterface` directly using the raw C API -- no Apple AudioUnitSDK wrapper classes are needed.

**Signal type:** float (32-bit). gen~ is compiled with `GENLIB_USE_FLOAT32`.

**Plugin type detection:** Automatic based on I/O configuration:

- `aufx` (effect) if the gen~ export has audio inputs
- `augn` (generator) if the gen~ export has no audio inputs

**Component identifiers:**

- **Type:** `aufx` or `augn` (auto-detected)
- **Subtype:** first 4 characters of lib_name, lowercased, padded with `x` if shorter
- **Manufacturer:** `gdsp`

## Parameters

All gen~ parameters are exposed as AU parameters with their original names, minimum, maximum, and default values. Parameters are automatable by the host DAW.

## Buffers

Buffer support follows the standard gen-dsp pattern. Up to 5 single-channel buffers are supported.

## Build Details

- **Build system:** CMake
- **SDK:** none -- uses system frameworks only (`AudioToolbox.framework`, `CoreFoundation.framework`, `CoreAudio.framework`)
- **Audio format:** Float32, non-interleaved (standard AU format)
- **Code signing:** ad-hoc code signed during build
- **Compile flags:** `-DGENLIB_USE_FLOAT32 -DWIN32 -DGENLIB_NO_DENORM_TEST`
- **Shared cache:** not applicable (no FetchContent)

An `Info.plist` is generated with the correct component type, subtype, and manufacturer codes.

## Install

```bash
cp -r build/myeffect.component ~/Library/Audio/Plug-Ins/Components/
```

After installing, you may need to restart your DAW or run `auval` to validate the plugin:

```bash
auval -a  # List all AudioUnits
auval -v aufx <subtype> gdsp  # Validate a specific plugin
```

## Troubleshooting

- **"Not a macOS system" error:** AudioUnit plugins can only be built on macOS. This is an Apple platform limitation.
- **Plugin not appearing in DAW:** Ensure the `.component` bundle is in `~/Library/Audio/Plug-Ins/Components/`. Try restarting the DAW or running `killall -9 AudioComponentRegistrar` to refresh the AU cache.
- **`auval` failures:** The initial implementation may not pass all `auval` validation checks. Common issues include missing property handlers. The plugin should still load and function in most DAWs.
- **Code signing issues:** The build produces an ad-hoc signed bundle. For distribution, you will need to re-sign with a valid Apple Developer certificate.
