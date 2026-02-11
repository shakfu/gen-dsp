# Circle (Raspberry Pi bare metal)

Generates bare-metal kernel images (`.img`) for Raspberry Pi using the [Circle](https://github.com/rsta2/circle) C++ framework. The firmware boots directly on the Pi hardware with no operating system -- just your gen~ DSP code running on bare metal.

**OS support:** Linux (cross-compilation host)

## Prerequisites

- Python >= 3.10
- `aarch64-none-elf-gcc` (AArch64 bare-metal toolchain, for Pi 3/4/5/Zero 2 W) or `arm-none-eabi-gcc` (for Pi Zero original)
- make
- git (for cloning Circle SDK on first build)
- Network access on first build (to clone Circle)

### Installing the cross-compiler

Download the AArch64 bare-metal toolchain from the [ARM GNU Toolchain Downloads](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads) page. Select the **aarch64-none-elf** variant for your host OS, extract it, and add its `bin/` directory to your PATH.

For 32-bit Pi Zero targets, you also need the `arm-none-eabi-` toolchain:

**Linux (apt):**

```bash
sudo apt install gcc-arm-none-eabi
```

**macOS (Homebrew):**

```bash
brew install arm-none-eabi-gcc
```

## Quick Start

```bash
# Create a Circle project (default: pi3-i2s)
gen-dsp init ./my_export -n myeffect -p circle -o ./myeffect_circle

# Build (auto-clones and builds Circle SDK on first run)
gen-dsp build ./myeffect_circle -p circle

# Output: kernel8.img

# Deploy: copy kernel8.img + config.txt to SD card boot partition
```

### Board Variants

Use `--board` to target a specific Pi model and audio output:

```bash
gen-dsp init ./my_export -n myeffect -p circle --board pi4-usb -o ./myeffect_pi4usb
```

Supported boards:

| Board | Pi Model | Audio | Arch | Output |
|-------|----------|-------|------|--------|
| `pi0-pwm` | Zero (original/W) | PWM (3.5mm jack) | 32-bit | `kernel.img` |
| `pi0-i2s` | Zero (original/W) | I2S (external DAC) | 32-bit | `kernel.img` |
| `pi0w2-i2s` | Zero 2 W | I2S (external DAC) | 64-bit | `kernel8.img` |
| `pi0w2-pwm` | Zero 2 W | PWM (3.5mm jack) | 64-bit | `kernel8.img` |
| `pi3-i2s` | 3 / 3B+ | I2S (external DAC) | 64-bit | `kernel8.img` |
| `pi3-pwm` | 3 / 3B+ | PWM (3.5mm jack) | 64-bit | `kernel8.img` |
| `pi3-hdmi` | 3 / 3B+ | HDMI | 64-bit | `kernel8.img` |
| `pi4-i2s` | 4 / 400 | I2S (external DAC) | 64-bit | `kernel8-rpi4.img` |
| `pi4-pwm` | 4 / 400 | PWM (3.5mm jack) | 64-bit | `kernel8-rpi4.img` |
| `pi4-hdmi` | 4 / 400 | HDMI | 64-bit | `kernel8-rpi4.img` |
| `pi4-usb` | 4 / 400 | USB (USB DAC) | 64-bit | `kernel8-rpi4.img` |
| `pi5-i2s` | 5 | I2S (external DAC) | 64-bit | `kernel_2712.img` |
| `pi5-hdmi` | 5 | HDMI | 64-bit | `kernel_2712.img` |
| `pi5-usb` | 5 | USB (USB DAC) | 64-bit | `kernel_2712.img` |

The default board is `pi3-i2s`.

### Audio Output Types

| Type | Description | Hardware Required |
|------|-------------|-------------------|
| **I2S** | External DAC via GPIO I2S bus | PCM5102A, PCM5122, UDA1334A, or similar DAC board |
| **PWM** | Analog audio from PWM pins (3.5mm jack on Pi 3/4) | None (built-in) |
| **HDMI** | Digital audio over HDMI | HDMI monitor or audio receiver |
| **USB** | USB audio class device (Pi 4/5 only) | USB DAC or audio interface |

## How It Works

gen-dsp uses **header isolation** to separate Circle API code from genlib code:

- `gen_ext_circle.cpp` -- Circle-facing wrapper (includes Circle headers, audio device class, kernel main loop)
- `_ext_circle.cpp` -- genlib-facing bridge (includes only genlib headers)
- `_ext_circle.h` -- C interface connecting the two sides via an opaque `GenState*` pointer

This isolation is required because Circle and genlib define conflicting symbols (e.g., both define `min`/`max` macros). The two compilation units never see each other's headers.

**Signal type:** float (32-bit). gen~ is compiled with `GENLIB_USE_FLOAT32`.

**Audio format:** DMA-based audio devices (I2S, PWM, HDMI) use Circle's `CSoundBaseDevice` with a `GetChunk()` callback called from the DMA interrupt handler. USB uses `CUSBSoundBaseDevice` with USB transfer-driven callbacks.

**Sample conversion:** gen~ outputs float [-1, 1] which is converted to the device's native integer range using `GetRangeMin()`/`GetRangeMax()`. This works across all audio device types without device-specific code.

**Channel mapping:** All devices use 2-channel stereo output. If the gen~ patch has fewer output channels, the extra hardware channels are filled with silence. Audio input is not captured (output-only).

### Template Selection

DMA-based audio devices (I2S, PWM, HDMI) share `gen_ext_circle.cpp.template` with template variables for the device-specific include, base class, and label. USB gets a separate `gen_ext_circle_usb.cpp.template` because it requires `CUSBHCIDevice` initialization before the sound device.

### Custom genlib Runtime

Circle uses a custom `genlib_circle.cpp` that replaces the standard `genlib.cpp`. Key differences:

- **Heap-backed bump allocator:** 16MB pool allocated from the system heap at init via `circle_init_memory()`
- **No-op free:** `sysmem_freeptr()` does nothing (bump allocator never frees individually)
- **Allocate-only resize:** `sysmem_resizeptr()` allocates new memory (old block is wasted)
- **No JSON:** Built with `-DGENLIB_NO_JSON` -- no filesystem on bare metal
- **8-byte alignment:** All allocations aligned for AArch64

### `cmath` Shim

Circle's `Rules.mk` adds `-nostdinc++` to compiler flags, which strips C++ standard library include paths. genlib's `genlib_ops.h` includes `<cmath>`, which would fail. gen-dsp includes a `cmath` shim file in the generated project that wraps `<math.h>` (available via Circle's newlib). The shim is found via the `-I.` include path already in the Makefile.

### WIN32 / GENLIB_NO_DENORM_TEST Workaround

genlib's `genlib_ops.h` defines inline `exp2(float)` and `trunc(float)` under `#ifndef WIN32`, which conflict with standard math functions. The wrapper defines `WIN32` before including genlib headers to skip these, and `GENLIB_NO_DENORM_TEST` to avoid the WIN32 path that redefines `__FLT_MIN__`. Both defines are scoped -- they are `#undef`'d immediately after the genlib includes.

## Parameters

Parameters retain their gen~ defaults at startup. The main loop in `gen_ext_circle.cpp` is an infinite loop that currently does nothing beyond keeping the system alive. To add runtime parameter control (e.g., from GPIO knobs or ADC), modify the `Run()` method:

```cpp
void Run(void)
{
    // Example: read ADC and set parameter
    // wrapper_set_param(m_pSound->GetState(), 0, adc_value);
    for (;;) {
        // Your parameter control code here
    }
}
```

Parameter query functions are available via the wrapper:

- `wrapper_num_params()` -- number of parameters
- `wrapper_param_name(state, index)` -- parameter name
- `wrapper_param_min(state, index)` / `wrapper_param_max(state, index)` -- range
- `wrapper_set_param(state, index, value)` / `wrapper_get_param(state, index)` -- get/set

## Buffers

Buffer support follows the standard gen-dsp pattern. Up to 5 single-channel buffers are supported via the `CircleBuffer` class. Buffer data is allocated from the 16MB memory pool.

## Build Details

- **Build system:** make using Circle's `Rules.mk` (provides ARM toolchain rules, linker script, boot image generation)
- **SDK:** Circle auto-cloned via `git clone --depth 1 --branch Step50.1`
- **Compile flags:** `-DGENLIB_USE_FLOAT32 -DGENLIB_NO_JSON`
- **Override directives:** `override RASPPI`, `override AARCH`, `override PREFIX` ensure project settings take precedence over Circle's `Config.mk`
- **Link libraries:** `libsound.a`, `libcircle.a` (plus `libusb.a` for USB boards)
- **Object files:** `gen_ext_circle.o`, `_ext_circle.o`, `genlib_circle.o`
- **Output:** kernel image (`.img`) named per Pi model
- **Shared cache:** not applicable (Make-based, not CMake FetchContent)

### Circle SDK Resolution

The Circle SDK directory is resolved in priority order:

1. `CIRCLEHOME` environment variable (or passed to make: `make CIRCLEHOME=/path`)
2. `GEN_DSP_CACHE_DIR` env var + `circle-src/circle`
3. OS-appropriate gen-dsp cache path (auto-clone destination)

On first build, Circle is cloned and its libraries are compiled (`./configure -r 3 -p aarch64-none-elf-` followed by `./makeall`). This takes a few minutes but only happens once.

### Generated config.txt

A `config.txt` file is generated for the Pi boot partition with settings appropriate to the audio device:

- **I2S:** Enables I2S overlay (`dtparam=i2s=on`) with GPIO wiring guide
- **PWM:** Documents default PWM GPIO pins
- **HDMI:** Notes HDMI audio requirements
- **USB:** Notes USB DAC requirements

All configs set `gpu_mem=16` to maximize application RAM (no GPU needed for audio-only firmware).

## Deploying to the Pi

1. Format an SD card with a FAT32 partition
2. Copy the Pi's firmware files to the SD card (from the [Raspberry Pi firmware repository](https://github.com/raspberrypi/firmware/tree/master/boot)):
   - `bootcode.bin` (Pi 0/3 only)
   - `start.elf` / `start4.elf` (Pi 4) / `start_cd.elf`
   - `fixup.dat` / `fixup4.dat`
3. Copy from your build output:
   - The kernel image (e.g., `kernel8.img`)
   - `config.txt` (generated by gen-dsp)
4. Insert SD card and power on the Pi

The firmware starts immediately -- there is no OS boot delay.

## Troubleshooting

- **`aarch64-none-elf-gcc` not found:** Download the AArch64 bare-metal toolchain from the [ARM GNU Toolchain Downloads](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads) page and add its `bin/` directory to your PATH. Note: this is **not** the same as `aarch64-linux-gnu-gcc` (which targets Linux, not bare metal).
- **Circle clone fails:** Ensure git is installed and you have network access. The clone uses `--depth 1` for a minimal download. Set `GIT_TERMINAL_PROMPT=0` to prevent git from hanging on credential prompts.
- **Circle build fails:** Ensure `aarch64-none-elf-gcc` is the correct toolchain (bare-metal, not Linux-targeted). Verify with `aarch64-none-elf-gcc --version`. The SDK build runs `./configure` followed by `./makeall`.
- **`cmath: No such file or directory`:** The `cmath` shim file is missing from the project directory. Re-generate the project with `gen-dsp init`. Circle's `-nostdinc++` flag removes C++ standard library headers; the shim provides `<cmath>` via `<math.h>`.
- **No audio output (I2S):** Verify DAC wiring: BCK -> GPIO 18, LRCK -> GPIO 19, DIN -> GPIO 21. Ensure `dtparam=i2s=on` is in `config.txt`. Check that the DAC receives 3.3V power.
- **No audio output (USB):** USB DAC must be plugged in before power-on (no hot-plug support in bare metal). The USB host controller initializes during boot.
- **No audio output (PWM):** PWM audio quality is limited (effective ~11-bit resolution). Connect headphones or powered speakers to the 3.5mm jack.
- **No audio output (HDMI):** Ensure the HDMI display/receiver is connected before power-on.
- **Wrong kernel image name:** Each Pi model expects a specific filename. Pi Zero uses `kernel.img`, Pi 3 uses `kernel8.img`, Pi 4 uses `kernel8-rpi4.img`, Pi 5 uses `kernel_2712.img`. The correct name is printed in the build output.
- **Out of memory at runtime:** The bump allocator has a fixed 16MB pool. Complex gen~ patches with many delay lines or large buffers may exhaust available memory. There is no runtime error message -- behavior is undefined if the pool overflows.
