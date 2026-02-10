# Max/MSP

Generates Max/MSP externals (`.mxo` on macOS, `.mxe64` on Windows) from gen~ exports using CMake and max-sdk-base.

**OS support:** macOS, Windows

## Prerequisites

- Python >= 3.10
- CMake >= 3.19
- C/C++ compiler (clang via Xcode on macOS, MSVC on Windows)
- git (for cloning max-sdk-base)

On macOS:

```bash
xcode-select --install
```

## Quick Start

```bash
# Create a Max project
gen-dsp init ./my_export -n myeffect -p max -o ./myeffect_max

# Build (automatically clones max-sdk-base if needed)
gen-dsp build ./myeffect_max -p max

# Output: myeffect_max/externals/myeffect~.mxo (macOS) or myeffect~.mxe64 (Windows)
```

Or build manually:

```bash
cd myeffect_max
git clone --depth 1 https://github.com/Cycling74/max-sdk-base.git
mkdir -p build && cd build
cmake .. && cmake --build .
```

## How It Works

gen-dsp uses **header isolation** to separate Max API code from genlib code:

- `gen_ext_max.cpp` -- Max-facing wrapper (includes only Max SDK headers)
- `_ext_max.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext_max.h` -- C interface connecting the two sides via an opaque `GenState*` pointer

**Signal type:** double (64-bit). Max/MSP uses native 64-bit double signals -- this is the only platform where gen~ is *not* compiled with `GENLIB_USE_FLOAT32`. Buffer samples are still 32-bit float, so the wrapper performs automatic float<->double conversion for buffer access.

**Plugin type detection:** Max externals are always tilde objects (`name~`), so there is no effect/generator distinction.

## Parameters

Parameters are controlled via messages to the first inlet, the same way as standard Max gen~ objects.

## Buffers

Max buffers use a lock/unlock API (`buffer_locksamples` / `buffer_unlocksamples`) for thread-safe access. Buffer storage is always 32-bit float regardless of signal precision. The gen-dsp wrapper handles the locking and float<->double conversion automatically.

Up to 5 buffers are supported (single-channel each).

## Build Details

- **Build system:** CMake using max-sdk-base (cloned from GitHub on first build)
- **SDK source:** `https://github.com/Cycling74/max-sdk-base.git` (shallow clone)
- **Shared cache:** not applicable (max-sdk-base is cloned per-project)

The CMakeLists.txt includes max-sdk-base's `max-pretarget.cmake` and `max-posttarget.cmake` scripts, which handle platform detection, compiler flags, and output directory setup. The built external is placed in the `externals/` directory.

## Install

| OS | Typical install path |
|----|---------------------|
| macOS | `~/Documents/Max 8/Packages/<name>/externals/` |
| Windows | `%USERPROFILE%/Documents/Max 8/Packages/<name>/externals/` |

Alternatively, copy the `.mxo`/`.mxe64` to any directory in Max's search path.

## Troubleshooting

- **max-sdk-base clone fails:** Ensure git is installed and you have network access. You can also clone manually: `git clone --depth 1 https://github.com/Cycling74/max-sdk-base.git` inside the project directory.
- **`exp2f` errors on macOS:** Max 9 exports include `exp2f` which fails on some macOS versions. gen-dsp automatically patches this during project creation. If you skipped patching (`--no-patch`), run `gen-dsp patch ./myproject`.
- **Windows builds:** Require Visual Studio or equivalent MSVC toolchain. Use `cmake -G "Visual Studio 17 2022" ..` to generate the project.

### PureData vs Max/MSP

| Aspect | PureData | Max/MSP |
|--------|----------|---------|
| Signal type | float (32-bit) | double (64-bit) |
| Buffer storage | float (32-bit) | float (32-bit) |
| Build system | make (pd-lib-builder) | CMake (max-sdk-base) |
| Buffer access | Direct array | Lock/unlock API |
| Output format | .pd_darwin / .pd_linux | .mxo / .mxe64 |
