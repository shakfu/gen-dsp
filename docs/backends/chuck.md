# ChucK

Generates ChucK chugins (`.chug` files) from gen~ exports using make and a bundled `chugin.h` header.

**OS support:** macOS, Linux

## Prerequisites

- Python >= 3.10
- C/C++ compiler (clang on macOS, gcc on Linux)
- make
- ChucK (for running the chugin)

On macOS:

```bash
xcode-select --install
```

## Quick Start

```bash
# Create a ChucK project
gen-dsp init ./my_export -n myeffect -p chuck -o ./myeffect_chuck

# Build
cd myeffect_chuck
make mac    # macOS
make linux  # Linux

# Output: Myeffect.chug
```

Or use `gen-dsp build`:

```bash
gen-dsp build ./myeffect_chuck -p chuck
```

## How It Works

gen-dsp uses **header isolation** to separate ChucK API code from genlib code:

- `gen_ext_chuck.cpp` -- ChucK-facing wrapper (includes only chugin.h)
- `_ext_chuck.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext_chuck.h` -- C interface connecting the two sides via an opaque `GenState*` pointer

**Signal type:** float (32-bit). ChucK's `SAMPLE` type is float, so gen~ is compiled with `GENLIB_USE_FLOAT32`.

**Multi-channel I/O:** Uses `CK_DLL_TICKF` with `add_ugen_funcf()` for multi-channel support. Audio is processed as interleaved frames.

**Class naming:** ChucK class names are capitalized -- `myeffect` becomes `Myeffect`. This is applied automatically during project generation.

## Parameters

The generated chugin extends `UGen` and provides a `param()` method for parameter control:

```chuck
// Import and instantiate (connects as UGen)
@import "Myeffect"
Myeffect eff => dac;

// Set a parameter by name
eff.param("frequency", 440.0);

// Get a parameter by name
eff.param("frequency") => float freq;

// Query parameters
eff.numParams() => int n;
eff.paramName(0) => string name;

// Print info (parameters, I/O, buffers)
eff.info();

// Reset internal state
eff.reset();
```

## Buffers

Buffer support follows the standard gen-dsp pattern. Up to 5 single-channel buffers are supported. Buffer data is stored in 32-bit float arrays.

## Build Details

- **Build system:** make (dispatches to `makefile.mac` or `makefile.linux` based on target)
- **Header:** bundled `chugin.h` in `chuck/include/` (no external ChucK SDK dependency for compilation)
- **Compile flags:** `-DGENLIB_USE_FLOAT32 -DWIN32 -DGENLIB_NO_DENORM_TEST`
- **Shared cache:** not applicable (no FetchContent)

The `WIN32` and `GENLIB_NO_DENORM_TEST` flags are a genlib compatibility workaround -- they disable x86 denormal flushing code that depends on MSVC intrinsics.

## Install

Copy the `.chug` file to ChucK's chugin search path:

| OS | Typical install path |
|----|---------------------|
| macOS | `/usr/local/lib/chuck/` or `~/.chuck/lib/` |
| Linux | `/usr/local/lib/chuck/` or `~/.chuck/lib/` |

## Troubleshooting

- **`@import` not found at runtime:** Ensure the `.chug` file is in ChucK's chugin search path. Use `chuck --chugin-path:/path/to/dir` to specify a custom path.
- **Class name mismatch:** ChucK class names are auto-capitalized. If your lib name is `myeffect`, use `Myeffect` in ChucK code.
- **Undefined symbol errors on Linux:** Ensure you used `make linux` (not `make mac`). The two targets use different compiler flags and linker options.
