# Percussa SSP

Generates modules (`.so`) for the [Percussa SSP](https://www.percussa.com/) from gen~ exports or graph files, in two formats. Both cross-compile with host clang against the Percussa buildroot.

| `--ssp-format` | Built on | Loads in | Size |
|-|-|-|-|
| `native` (default) | `Percussa::SSP::PluginInterface` from the [Percussa SSP SDK](https://github.com/percussa/ssp-sdk) (API 3.5), no JUCE | Synthor | 70 KB |
| `juce` | the SSP plugin framework and JUCE, as the SSP's own modules are; see [JUCE format](#juce-format) | Synthor, rack-style hosts | 10 MB |

**OS support (build host):** macOS, Linux

**Device status:** `native` runs on an SSP: listed by Synthor, audio, encoders, paging and the display confirmed. Presets save and reload. `juce` runs in Synthor (`gvbj`, gigaverb); presets save and reload, including loaded file paths; rack not yet tested. Buffer loading from the module's folder works in both formats, and so does the JUCE format's Load; two instances play different files (`rmpl`, `rmpj`: RamplePlayer).

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

## JUCE format

```bash
gen-dsp ./my_export -n myverb -p ssp --ssp-format juce                          # downloads a dev tree
gen-dsp ./my_export -n myverb -p ssp --ssp-format juce --ssp-dev-dir ~/ssp      # uses a checkout
```

The module builds on `plugins/common` of [shakfu/ssp](https://github.com/shakfu/ssp): TheTechnobear's SSP framework with its `ssp::engine` layer. It gets the framework's editor, compact view and preset handling, and exports `SSPExtendedApi`, so rack-style hosts load it.

The dev tree is a shakfu/ssp checkout with its `juce` (TheTechnobear's fork) and `ssp-sdk` submodules:

- **Downloaded** (default): pinned archives of all three, cached in the FetchContent cache (23 MB).
- **Existing** (`--ssp-dev-dir`, `ssp_dev_dir` in `gen-dsp.toml`, or `SSP_DEV_DIR` at configure time): the checkout as it is. Its `buildroot/` is used too, unless `SSP_BUILDROOT` is set.

The framework's source lists come from the dev tree's own `CMakeLists.txt` files, so a newer checkout builds without a gen-dsp change.

Building needs the host headers that JUCE's `juceaide` tool uses: X11, FreeType and fontconfig (`libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev libxrender-dev libxcomposite-dev libfreetype-dev libfontconfig1-dev` on Debian/Ubuntu). The first build compiles JUCE and the framework: about 7 CPU-minutes; ccache (`CMAKE_CXX_COMPILER_LAUNCHER=ccache`) makes later builds faster.

Output: `build/<module name>.so`, copied from the VST3 bundle JUCE builds.

Controls follow the framework, not the table below: encoders move one step per call (1% of the range, 0.1% fine) and need the editor, which Synthor creates. Load fills a buffer; see [Buffers](#buffers).

## Buffers

Each gen~ buffer (`--buffers`) loads `<buffer>.wav` from the module's folder at start: a folder named after the module, beside `plugins/`. On the card, `plugins/rmpl.so` reads `rmpl/sample.wav`.

- **Formats:** WAV, PCM 16/24-bit or float 32-bit, any channel count.
- **Size:** the buffer takes the file's length and channels. The file's sample rate is ignored: samples play as stored.
- **Instances** keep their own buffers. A load takes effect at the start of a block, and the audio thread never reads, allocates or frees file data.
- **Native:** the screen shows each buffer's frame count, or the missing file's name.
- **JUCE:** Load opens the framework's file browser and fills a buffer; with several buffers, the `load into` choice on the `buffers` page picks which. Presets keep each buffer's path. The status panel shows what each buffer holds.

## Module name

Synthor does not list a module whose uid does not spell its name. Percussa does not document this rule; renaming one module's uid on a device confirmed it. gen-dsp requires exactly 4 letters or digits, which is stricter than the device: `shq` (uid `SHQ4`) is listed. gen-dsp derives both from one value, so they always match: the name in lowercase, the uid in uppercase.

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

## Controls and display (native)

| Control | Action |
|-|-|
| Encoders 1-4 | edit the 4 parameters of the current page, 1% of the range per pulse |
| Shift L or R held | 10x finer encoder steps |
| Encoder press | reset that parameter to its default |
| Left / Up, Right / Down | previous / next page |
| Soft key N | jump to page N |

The screen shows the module name, the page number, and each encoder's parameter name, value and position in its range. It scales with the screen height, so the compact view works too.

## How it works (native)

- `gen_ext_ssp.cpp` -- the module: includes only `Percussa.h` and `_ext_ssp.h`

- `_ext_ssp.cpp` -- the genlib bridge: includes only genlib headers

- `ssp_toolchain.cmake` -- the cross toolchain, chosen automatically unless `SSP_HOST_BUILD` is on

**Audio.** The host passes one in-place buffer of `max(inputs, outputs)` channels. The module copies the inputs before `perform`, since gen~ outputs overwrite them. It splits blocks larger than the size announced in `prepare()`. Denormals flush to zero on ARM.

**Threads.** `encoderTurned` runs on the audio thread, while `buttonPressed` and `setState` run on the UI thread. All three write parameter values to an atomic array. `process()` applies changed values to genlib at the start of each block, so only the audio thread touches genlib's parameter state.

**State.** `getState`/`setState` use a text blob: the page, then one `name value` line per parameter. Parameters are matched by name, so presets survive reordering in the patch.

**Symbols.** Synthor loads every module into one process. Symbols are hidden by default, so two gen~ modules cannot bind each other's genlib. A version script, `ssp_exports.map`, exports only the three entry points. Visibility alone leaves genlib's replacement `operator new`/`delete` and inline `std::` instances exported. Apple's linker has no version scripts, so macOS host builds skip it.

## Toolchain

`ssp_toolchain.cmake` follows the SDK's `xcSSP.cmake`: host clang targeting `arm-linux-gnueabihf`, lld, the buildroot sysroot with its GCC 8.4 libstdc++, and `-mcpu=cortex-a17 -mfloat-abi=hard -mfpu=neon-vfpv4`.

| Variable | Effect |
|-|-|
| `SSP_BUILDROOT` (`-D` or env) | use an extracted buildroot instead of downloading one |
| `TOOLSROOT` (env) | directory holding `clang`/`clang++`; default Homebrew LLVM, then `PATH` |
| `SSP_HOST_BUILD=ON` | build for the host, for testing off the device |
| `SSP_MODULE_NAME` | module name, see above |
| `SSP_DEV_DIR` (`-D` or env) | JUCE format: the dev tree, see above |

Without `SSP_BUILDROOT`, the buildroot is downloaded once to `<FetchContent cache>/ssp-buildroot/`.

## Testing off the device

`tests/data/ssp_host.cpp` loads a module with `dlopen` and drives it through the Percussa API, as Synthor does: descriptor, `prepare`, `process`, encoders, buttons, state and screen rendering. `tests/test_ssp.py` builds modules with `SSP_HOST_BUILD=ON` and runs it. The cross build test runs when a buildroot is available. The JUCE tests run when `SSP_DEV_DIR` names a dev tree; one checks that the JUCE module's output matches the native module's, sample for sample.

## Limitations

- **rack and XMX.** TheTechnobear's rack-style hosts load only modules that export the JUCE-based `SSPExtendedApi`. Use the JUCE format for them.

- **No MIDI.** The Percussa API passes no MIDI, so gen-dsp's MIDI-to-CV mapping does not apply.

## Licence

`Percussa.h` is licensed GPL-2.0-or-later or AGPL-3.0. gen-dsp fetches it at configure time and does not ship it. A built module includes it, so the module is covered by one of those licences. The JUCE format also builds on the SSP framework (AGPL-3.0), so a JUCE-format module is AGPL-3.0.
