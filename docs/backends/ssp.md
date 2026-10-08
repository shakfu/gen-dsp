# Percussa SSP

Generates native modules (`.so`) for the [Percussa SSP](https://www.percussa.com/) from gen~ exports or graph files. Modules implement `Percussa::SSP::PluginInterface` from the [Percussa SSP SDK](https://github.com/percussa/ssp-sdk) (API 3.5) directly, without JUCE, and cross-compile with host clang against the Percussa buildroot.

**OS support (build host):** macOS, Linux

**Device status:** builds and passes host tests; not yet confirmed on SSP hardware.

## Prerequisites

- Python >= 3.10

- CMake >= 3.19

- LLVM clang and lld (`brew install llvm lld` on macOS; `apt install clang lld` on Linux)

- Network access on first configure: the SDK header (32 KB) and the SSP buildroot (608 MB download), both cached afterward

`gen-dsp doctor -p ssp` checks these.

## Quick Start

```bash
gen-dsp ./my_export -n myverb -p ssp -o ./myverb_ssp

# or build by hand
cd myverb_ssp
cmake -B build && cmake --build build

# Output: build/myverb.so
```

Copy the `.so` to the `plugins/` folder on the SD card's `BOOT` partition. Synthor lists it as `myvr`.

## Module name

A module's name must be exactly 4 letters or digits, and its uid must spell the same 4 characters. Synthor does not list a module whose uid differs from its name. This rule was inferred from the 39 modules on one SSP card; Percussa does not document it. gen-dsp derives both from one value, so they always match: the name in lowercase, the uid in uppercase.

Two names on one card collide. gen-dsp cannot see the card, so choose the name yourself when the default might clash:

```bash
gen-dsp ./gigaverb -n gigaverb -p ssp --ssp-name gvb2   # or ssp_name = "gvb2" in gen-dsp.toml
cmake -B build -DSSP_MODULE_NAME=gvb2                   # or at configure time
```

Without `--ssp-name`, gen-dsp derives the name from `-n` and prints it. It keeps the first character, then prefers new consonants and digits, then vowels, in reading order:

| `-n` | name | uid |
|-|-|-|
| `gigaverb` | `gvrb` | `GVRB` (`0x47565242`) |
| `csound` | `csnd` | `CSND` |
| `chuck` | `chuk` | `CHUK` |
| `fm` | `fmxx` | `FMXX` (padded with `x`) |

The check runs in gen-dsp, in CMake, and as a C++ `static_assert`.

## Controls and display

| Control | Action |
|-|-|
| Encoders 1-4 | edit the 4 parameters of the current page, 1% of the range per pulse |
| Shift L or R held | 10x finer encoder steps |
| Encoder press | reset that parameter to its default |
| Left / Up, Right / Down | previous / next page |
| Soft key N | jump to page N |

The screen shows the module name, the page number, and each encoder's parameter name, value and position in its range. It scales with the screen height, so the compact view works too.

## How it works

- `gen_ext_ssp.cpp` -- the module: includes only `Percussa.h` and `_ext_ssp.h`

- `_ext_ssp.cpp` -- the genlib bridge: includes only genlib headers

- `ssp_toolchain.cmake` -- the cross toolchain, chosen automatically unless `SSP_HOST_BUILD` is on

**Audio.** The host passes one in-place buffer of `max(inputs, outputs)` channels. The module copies the inputs before `perform`, since gen~ outputs overwrite them. It splits blocks larger than the size announced in `prepare()`. Denormals flush to zero on ARM.

**Threads.** `encoderTurned` runs on the audio thread, while `buttonPressed` and `setState` run on the UI thread. All three write parameter values to an atomic array. `process()` applies changed values to genlib at the start of each block, so only the audio thread touches genlib's parameter state.

**State.** `getState`/`setState` use a text blob: the page, then one `name value` line per parameter. Parameters are matched by name, so presets survive reordering in the patch.

**Symbols.** Synthor loads every module into one process. Symbols are hidden by default, so two gen~ modules cannot bind each other's genlib. The three entry points stay exported.

## Toolchain

`ssp_toolchain.cmake` follows the SDK's `xcSSP.cmake`: host clang targeting `arm-linux-gnueabihf`, lld, the buildroot sysroot with its GCC 8.4 libstdc++, and `-mcpu=cortex-a17 -mfloat-abi=hard -mfpu=neon-vfpv4`.

| Variable | Effect |
|-|-|
| `SSP_BUILDROOT` (`-D` or env) | use an extracted buildroot instead of downloading one |
| `TOOLSROOT` (env) | directory holding `clang`/`clang++`; default Homebrew LLVM, then `PATH` |
| `SSP_HOST_BUILD=ON` | build for the host, for testing off the device |
| `SSP_MODULE_NAME` | module name, see above |

Without `SSP_BUILDROOT`, the buildroot is downloaded once to `<FetchContent cache>/ssp-buildroot/`.

## Testing off the device

`tests/data/ssp_host.cpp` loads a module with `dlopen` and drives it through the Percussa API, as Synthor does: descriptor, `prepare`, `process`, encoders, buttons, state and screen rendering. `tests/test_ssp.py` builds modules with `SSP_HOST_BUILD=ON` and runs it. The cross build test runs when a buildroot is available.

## Limitations

- **rack and XMX.** TheTechnobear's rack-style hosts load only modules that export the JUCE-based `SSPExtendedApi`, so these modules do not load inside them. His [RNBO template](https://github.com/thetechnobear/rnbo.example.ssp) takes the JUCE route for RNBO exports.

- **No MIDI.** The Percussa API passes no MIDI, so gen-dsp's MIDI-to-CV mapping does not apply.

- **Buffers** are allocated but cannot be loaded from files.

## Licence

`Percussa.h` is licensed GPL-2.0-or-later or AGPL-3.0. gen-dsp fetches it at configure time and does not ship it. A built module includes it, so the module is covered by one of those licences.
