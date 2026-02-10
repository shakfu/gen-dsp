# PureData

Generates PureData externals (`.pd_darwin`, `.pd_linux`) from gen~ exports using pd-lib-builder.

**OS support:** macOS, Linux

## Prerequisites

- Python >= 3.10
- C/C++ compiler (gcc, clang)
- make
- PureData headers (typically installed with PureData)

On macOS:

```bash
xcode-select --install
```

On Linux, standard build tools (gcc, make) are typically pre-installed.

## Quick Start

```bash
# Create a PureData project
gen-dsp init ./my_export -n myeffect -p pd -o ./myeffect_pd

# Build
cd myeffect_pd
make all

# Output: myeffect~.pd_darwin (macOS) or myeffect~.pd_linux (Linux)
```

If PureData is installed in a non-standard location, set `PDINCLUDEDIR`:

```bash
make all PDINCLUDEDIR=/path/to/pd/include
```

## How It Works

gen-dsp uses **header isolation** to separate PureData API code from genlib code:

- `gen_dsp.cpp` -- PureData-facing wrapper (includes only PD headers)
- `_ext.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext.h` -- C interface connecting the two sides via an opaque `GenState*` pointer

The gen~ export files are copied into a `gen/` subdirectory. At runtime, the external creates a gen~ state, wires PD signal vectors to gen~'s `float**` perform function, and routes inlet messages to gen~ parameters.

**Signal type:** float (32-bit). gen~ is compiled with `GENLIB_USE_FLOAT32`.

**Plugin type detection:** PureData externals are always tilde objects (`name~`), so there is no effect/generator distinction.

## Parameters

Send `<parameter-name> <value>` messages to the first inlet:

```text
[frequency 440(
|
[mysynth~]
```

Send `bang` to the first inlet to print all available parameters to the PD console.

## Buffers

Buffers connect to PureData arrays with matching names. Up to 5 buffers are supported (single-channel each).

To remap a buffer to a different array at runtime:

```text
[pdset original_buffer new_array(
|
[mysampler~]
```

### Sample Rate and Block Size

For subpatches with custom block sizes (e.g., spectral processing):

```text
[pdsr 96000(  <- Set sample rate
[pdbs 2048(   <- Set block size
|
[myspectral~]
```

## Build Details

- **Build system:** make via [pd-lib-builder](https://github.com/pure-data/pd-lib-builder) (bundled with the generated project)
- **Compile flags (macOS):** `-DMSP_ON_CLANG -DGENLIB_USE_FLOAT32 -mmacosx-version-min=10.9`
- **Compile flags (Linux):** `-DGENLIB_USE_FLOAT32 -DWIN32 -DGENLIB_NO_DENORM_TEST`
- **Shared cache:** not applicable (no FetchContent)

The `WIN32` and `GENLIB_NO_DENORM_TEST` flags on Linux are a genlib compatibility workaround -- they disable x86 denormal flushing code that depends on MSVC intrinsics.

## Install

Copy the built external to your PureData search path:

| OS | Typical install path |
|----|---------------------|
| macOS | `~/Library/Pd/externals/` or `~/Documents/Pd/externals/` |
| Linux | `~/.local/lib/pd/extra/` or `/usr/local/lib/pd/extra/` |

## Troubleshooting

- **`pd.h` not found:** PureData headers are missing. Install PureData or set `PDINCLUDEDIR` to the directory containing `m_pd.h`.
- **`exp2f` errors on macOS:** Max 9 exports include `exp2f` which fails on some macOS versions. gen-dsp automatically patches this to `exp2` during project creation. If you skipped patching (`--no-patch`), run `gen-dsp patch ./myproject`.
- **Cross-compilation (macOS <-> Linux):** Build artifacts are platform-specific. Run `make clean && make all` when moving projects between platforms.
