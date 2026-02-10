# Daisy (Electrosmith)

Generates firmware binaries (`.bin`) for the Daisy Seed and related boards from gen~ exports using make and libDaisy. This is gen-dsp's first embedded/cross-compilation target.

**OS support:** Linux (cross-compilation from macOS may work but is untested in CI)

## Prerequisites

- Python >= 3.10
- `arm-none-eabi-gcc` (ARM GCC cross-compilation toolchain)
- make
- git (for cloning libDaisy on first build)
- Network access on first build (to clone libDaisy + submodules)

### Installing the ARM toolchain

**macOS (Homebrew):**

```bash
brew install arm-none-eabi-gcc
```

**Linux (apt):**

```bash
sudo apt install gcc-arm-none-eabi
```

## Quick Start

```bash
# Create a Daisy project (default: Daisy Seed)
gen-dsp init ./my_export -n myeffect -p daisy -o ./myeffect_daisy

# Build (auto-clones libDaisy on first run)
gen-dsp build ./myeffect_daisy -p daisy

# Output: build/myeffect.bin

# Flash via DFU (put Daisy in bootloader mode first)
dfu-util -a 0 -s 0x08000000:leave -D build/myeffect.bin
```

### Board Variants

Use `--board` to target a specific Daisy board:

```bash
gen-dsp init ./my_export -n myeffect -p daisy --board pod -o ./myeffect_pod
```

Supported boards:

| Board | Knobs | Channels | Notes |
|-------|------:|--------:|-------|
| `seed` | 0 | 2 | Default. No built-in controls. |
| `pod` | 2 | 2 | Two knobs + buttons |
| `patch` | 4 | 4 | 4-channel audio |
| `patch_sm` | 4 | 2 | Patch submodule (CV inputs) |
| `field` | 8 | 2 | 8 knobs + keyboard |
| `petal` | 6 | 2 | Guitar pedal form factor |
| `legio` | 2 | 2 | Compact Eurorack |
| `versio` | 7 | 2 | Noise Engineering Versio |

For boards with knobs, gen-dsp auto-generates code that reads hardware knobs and scales values to gen~ parameter ranges (first N knobs map to first N parameters).

## How It Works

gen-dsp uses **header isolation** to separate libDaisy API code from genlib code:

- `gen_ext_daisy.cpp` -- Daisy-facing wrapper (includes libDaisy headers, audio callback, main loop)
- `_ext_daisy.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext_daisy.h` -- C interface connecting the two sides via an opaque `GenState*` pointer

**Signal type:** float (32-bit). gen~ is compiled with `GENLIB_USE_FLOAT32`.

**Audio format:** Float32, non-interleaved. libDaisy's audio callback provides `float**` buffers that match gen~'s format directly.

**Channel mapping:** `min(gen_channels, 2)` mapped to hardware I/O. Extra gen~ channels use scratch buffers (silent input / discarded output).

### Custom genlib Runtime

Daisy uses a custom `genlib_daisy.cpp` that replaces the standard `genlib.cpp`. Key differences:

- **Two-tier bump allocator:** SRAM pool (~450KB, malloc'd at init) + SDRAM pool (64MB, placed in `.sdram_bss` linker section)
- **No-op free:** `sysmem_freeptr()` does nothing (bump allocator -- memory is never freed)
- **Allocate-only resize:** `sysmem_resizeptr()` allocates new memory (old block is wasted)
- **No JSON:** Built with `-DGENLIB_NO_JSON` -- no json.c/json_builder.c compiled

### ARM_MATH_CM7 Workaround

libDaisy defines `ARM_MATH_CM7` which causes genlib's `genlib_platform.h` to enable `GENLIB_USE_ARMMATH` (using `arm_sqrtf`) and `GENLIB_USE_FASTMATH` (using `fasterpow`). These are incompatible with the gen~ export code, so the wrapper `#undef`s both `ARM_MATH_CM7` and `ARM_MATH_CM4` before including genlib headers.

## Parameters

Parameters retain their gen~ defaults at startup. For boards with hardware knobs, the generated code auto-maps the first N knobs to the first N gen~ parameters, scaling the 0-1 knob range to each parameter's min/max range.

For the bare Seed (no knobs), modify `gen_ext_daisy.cpp` to add ADC reads for custom knob/CV circuits.

## Buffers

Buffer support follows the standard gen-dsp pattern. Up to 5 single-channel buffers are supported. Buffer data is allocated from the SRAM/SDRAM memory pools.

## Build Details

- **Build system:** make using libDaisy's `core/Makefile` (provides ARM toolchain rules)
- **SDK:** libDaisy auto-cloned via `git clone --recurse-submodules` (pinned to `v7.1.0`)
- **Target MCU:** STM32H750 (ARM Cortex-M7)
- **Compile flags:** `-DGENLIB_USE_FLOAT32 -DWIN32 -DGENLIB_NO_DENORM_TEST -DGENLIB_NO_JSON`
- **Output:** firmware `.bin` in `build/` directory
- **Shared cache:** not applicable (Make-based, not CMake FetchContent)

### libDaisy Resolution

The libDaisy directory is resolved in priority order:

1. `LIBDAISY_DIR` environment variable (explicit override)
2. `GEN_DSP_CACHE_DIR` env var + `libdaisy-src/libDaisy`
3. OS-appropriate gen-dsp cache path (auto-clone destination)

On first build, libDaisy is cloned and `libdaisy.a` is compiled. This takes a few minutes but only happens once.

## Flashing

Put the Daisy in DFU bootloader mode (hold BOOT, press RESET, release BOOT), then:

```bash
# Using dfu-util
dfu-util -a 0 -s 0x08000000:leave -D build/myeffect.bin

# Or using the Makefile target (if libDaisy is set up)
make program-dfu
```

## Troubleshooting

- **`arm-none-eabi-gcc` not found:** Install the ARM GCC toolchain and ensure it is on PATH.
- **libDaisy clone fails:** Ensure git is installed and you have network access. The clone includes submodules, so it may take a minute. Set `GIT_TERMINAL_PROMPT=0` to prevent git from hanging on credential prompts.
- **libDaisy build fails:** Ensure `arm-none-eabi-gcc` is the correct version (9.x+ recommended). Check that `make` is GNU Make, not BSD make.
- **Out of memory at runtime:** The bump allocator has fixed pools (450KB SRAM + 64MB SDRAM). Complex gen~ patches with many delay lines or buffers may exhaust available memory. There is no runtime error -- behavior is undefined if pools overflow.
- **No audio output:** Check that the Daisy is receiving power and the audio codec is initialized. For the Seed, verify your hardware connections (SAI pins for I2S audio).
