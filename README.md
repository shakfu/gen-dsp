# gen-dsp

This project is a friendly fork of Michael Spears' [gen_ext](https://github.com/samesimilar/gen_ext) which was originally created to "compile code exported from a Max gen~ object into an "external" object that can be loaded into a PureData patch." 

Building on this excellent original idea and implementation, gen-dsp compiles code exported from Max gen~ objects into external objects for PureData, Max/MSP, ChucK, AudioUnit (AUv2), CLAP, VST3, LV2, SuperCollider, VCV Rack, Daisy (Electrosmith), and Circle (Raspberry Pi bare metal). It automates project setup, buffer detection, and platform-specific patches.

## Cross-Platform Support

gen-dsp builds on macOS, Linux, and Windows. All platforms are tested in CI via GitHub Actions.

| Platform | macOS | Linux | Windows | Build System | Output |
|----------|:-----:|:-----:|:-------:|--------------|--------|
| PureData | yes | yes | -- | make (pd-lib-builder) | `.pd_darwin` / `.pd_linux` |
| Max/MSP | yes | -- | -- | CMake (max-sdk-base) | `.mxo` / `.mxe64` |
| ChucK | yes | yes | -- | make | `.chug` |
| AudioUnit | yes | -- | -- | CMake | `.component` |
| CLAP | yes | yes | yes | CMake (FetchContent) | `.clap` |
| VST3 | yes | yes | yes | CMake (FetchContent) | `.vst3` |
| LV2 | yes | yes | -- | CMake (FetchContent) | `.lv2` |
| SuperCollider | yes | yes | yes | CMake (FetchContent) | `.scx` / `.so` |
| VCV Rack | yes | yes | -- | make (Rack SDK) | `plugin.dylib` / `.so` / `.dll` |
| Daisy | -- | yes | -- | make (libDaisy) | `.bin` (firmware) |
| Circle | -- | yes | -- | make (Circle SDK) | `.img` (kernel image) |

Each platform has a detailed guide covering prerequisites, build details, SDK configuration, install paths, and troubleshooting:

| Platform | Guide |
|----------|-------|
| PureData | [docs/backends/puredata.md](docs/backends/puredata.md) |
| Max/MSP | [docs/backends/max.md](docs/backends/max.md) |
| ChucK | [docs/backends/chuck.md](docs/backends/chuck.md) |
| AudioUnit (AUv2) | [docs/backends/audiounit.md](docs/backends/audiounit.md) |
| CLAP | [docs/backends/clap.md](docs/backends/clap.md) |
| VST3 | [docs/backends/vst3.md](docs/backends/vst3.md) |
| LV2 | [docs/backends/lv2.md](docs/backends/lv2.md) |
| SuperCollider | [docs/backends/supercollider.md](docs/backends/supercollider.md) |
| VCV Rack | [docs/backends/vcvrack.md](docs/backends/vcvrack.md) |
| Daisy | [docs/backends/daisy.md](docs/backends/daisy.md) |
| Circle | [docs/backends/circle.md](docs/backends/circle.md) |

## Key Improvements and Features

- **Python package**: gen-dsp is a pip installable zero-dependency python package with a cli which embeds all templates and related code.

- **Automated project scaffolding**: `gen-dsp init` creates a complete, buildable project from a gen~ export in one command, versus manually copying files and editing Makefiles.

- **Automatic buffer detection**: Scans exported code for buffer usage patterns and configures them without manual intervention.

- **Max/MSP support**: Generates CMake-based Max externals with proper 64-bit signal handling and buffer lock/unlock API.

- **ChucK support**: Generates chugins (.chug) with multi-channel I/O and runtime parameter control.

- **AudioUnit support**: Generates macOS AUv2 plugins (.component) using the raw C API -- no Apple SDK dependency, just system frameworks.

- **CLAP support**: Generates cross-platform CLAP plugins (`.clap`) with zero-copy audio processing -- CLAP headers fetched via CMake FetchContent.

- **VST3 support**: Generates cross-platform VST3 plugins (`.vst3`) with zero-copy audio processing -- Steinberg VST3 SDK fetched via CMake FetchContent.

- **LV2 support**: Generates cross-platform LV2 plugins (`.lv2` bundles) with TTL metadata containing real parameter names/ranges parsed from gen~ exports -- LV2 headers fetched via CMake FetchContent.

- **SuperCollider support**: Generates cross-platform SC UGens (`.scx`/`.so`) with `.sc` class files containing parameter names/defaults parsed from gen~ exports -- SC plugin headers fetched via CMake FetchContent.

- **VCV Rack support**: Generates VCV Rack modules with per-sample processing, auto-generated `plugin.json` manifest and panel SVG -- Rack SDK auto-downloaded and cached on first build.

- **Daisy support**: Generates Daisy Seed firmware (.bin) with custom genlib runtime (bump allocator for SRAM/SDRAM) -- first embedded/cross-compilation target, requires `arm-none-eabi-gcc`.

- **Circle support**: Generates bare-metal Raspberry Pi kernel images (.img) for Pi Zero through Pi 5 using the [Circle](https://github.com/rsta2/circle) framework -- 14 board variants covering I2S, PWM, HDMI, and USB audio outputs. Supports multi-plugin mode via `--graph` with USB MIDI CC parameter control: linear chains use an optimized ping-pong buffer codegen path, while arbitrary DAGs (fan-out, fan-in via mixer nodes) use topological sort with per-edge buffer allocation.

- **Platform-specific patches**: Automatically fixes compatibility issues like the `exp2f -> exp2` problem in Max 9 exports on macOS.

- **Analysis tools**: `gen-dsp detect` inspects exports to show I/O counts, parameters, and buffers before committing to a build.

- **Dry-run mode**: Preview what changes will be made before applying them.

- **Platform registry**: To make it easy to discover new backends

## Installation

```bash
pip install gen-dsp
```

Or install from source:

```bash
git clone https://github.com/shakfu/gen-dsp.git
cd gen-dsp
pip install -e .
```

## Quick Start

```bash
# 1. Export your gen~ code in Max (send 'exportcode' to gen~ object)

# 2. Create a project from the export
gen-dsp init ./path/to/export -n myeffect -o ./myeffect

# 3. Build the external
cd myeffect
make all

# 4. Use in PureData as myeffect~
```

## Commands

### init

Create a new project from a gen~ export:

```bash
gen-dsp init <export-path> -n <name> [-p <platform>] [-o <output>]
```

Options:

- `-n, --name` - Name for the external (required)
- `-p, --platform` - Target platform: `pd` (default), `max`, `chuck`, `au`, `clap`, `vst3`, `lv2`, `sc`, `vcvrack`, `daisy`, `circle`, or `both`
- `-o, --output` - Output directory (default: `./<name>`)
- `--buffers` - Explicit buffer names (overrides auto-detection)
- `--shared-cache` - Use a shared OS cache for FetchContent downloads (clap, vst3, lv2, sc only)
- `--board` - Board variant for embedded platforms (Daisy: `seed`, `pod`, etc.; Circle: `pi3-i2s`, `pi4-usb`, etc.)
- `--graph` - JSON graph file for multi-plugin chain mode (Circle only; see [Chain Mode](#circle-chain-mode) below)
- `--export` - Additional export path for chain node resolution (repeatable; use with `--graph`)
- `--no-patch` - Skip automatic exp2f fix
- `--dry-run` - Preview without creating files

### build

Build an existing project:

```bash
gen-dsp build [project-path] [-p <platform>] [--clean] [-v]
```

### manifest

Emit a JSON manifest describing a gen~ export (I/O counts, parameters with ranges, buffers):

```bash
gen-dsp manifest <export-path> [--buffers sample envelope]
```

The same manifest is also written as `manifest.json` to the project root during `gen-dsp init`.

### detect

Analyze a gen~ export:

```bash
gen-dsp detect <export-path> [--json]
```

Shows: export name, signal I/O counts, parameters, detected buffers, and needed patches.

### patch

Apply platform-specific fixes:

```bash
gen-dsp patch <target-path> [--dry-run]
```

Currently applies the `exp2f -> exp2` fix for macOS compatibility with Max 9 exports.

## Features

### Automatic Buffer Detection

gen-dsp scans your gen~ export for buffer usage patterns and configures them automatically:

```bash
$ gen-dsp detect ./my_sampler_export
Gen~ Export: my_sampler
  Signal inputs: 1
  Signal outputs: 2
  Parameters: 3
  Buffers: ['sample', 'envelope']
```

Buffer names must be valid C identifiers (alphanumeric, starting with a letter).

### Platform Patches

Max 9 exports include `exp2f` which fails on macOS. gen-dsp automatically patches this to `exp2` during project creation, or you can apply it manually:

```bash
gen-dsp patch ./my_project --dry-run  # Preview
gen-dsp patch ./my_project            # Apply
```

## PureData

See the [PureData guide](docs/backends/puredata.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p pd -o ./myeffect_pd
cd myeffect_pd && make all
```

Parameters: send `<name> <value>` messages to the first inlet. Send `bang` to list all parameters. Buffers connect to PureData arrays by name; use `pdset` to remap.

## Max/MSP

See the [Max/MSP guide](docs/backends/max.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p max -o ./myeffect_max
gen-dsp build ./myeffect_max -p max
# Output: externals/myeffect~.mxo (macOS) or myeffect~.mxe64 (Windows)
```

Max is the only platform using 64-bit double signals. The SDK (max-sdk-base) is auto-cloned on first build.

## ChucK

See the [ChucK guide](docs/backends/chuck.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p chuck -o ./myeffect_chuck
cd myeffect_chuck && make mac  # or make linux
```

Class names are auto-capitalized (`myeffect` -> `Myeffect`). Parameters are controlled via `eff.param("name", value)`. Buffer-based chugins can load WAV files at runtime via `eff.loadBuffer("sample", "amen.wav")`.

## AudioUnit (AUv2)

See the [AudioUnit guide](docs/backends/audiounit.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p au -o ./myeffect_au
cd myeffect_au && cmake -B build && cmake --build build
# Output: build/myeffect.component
```

macOS only. Uses the raw AUv2 C API -- no external SDK needed, just system frameworks. Auto-detects `aufx` (effect) vs `augn` (generator). Passes Apple's `auval` validation.

## CLAP

See the [CLAP guide](docs/backends/clap.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p clap -o ./myeffect_clap
cd myeffect_clap && cmake -B build && cmake --build build
# Output: build/myeffect.clap
```

Cross-platform (macOS, Linux, Windows). Zero-copy audio. Passes [clap-validator](https://github.com/free-audio/clap-validator) conformance tests. CLAP headers fetched via CMake FetchContent (tag 1.2.2, MIT licensed).

## VST3

See the [VST3 guide](docs/backends/vst3.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p vst3 -o ./myeffect_vst3
cd myeffect_vst3 && cmake -B build && cmake --build build
# Output: build/VST3/Release/myeffect.vst3/
```

Cross-platform (macOS, Linux, Windows). Zero-copy audio. Passes Steinberg's SDK validator (47/47 tests). VST3 SDK fetched via CMake FetchContent (tag v3.7.9_build_61, GPL3/proprietary dual licensed).

## LV2

See the [LV2 guide](docs/backends/lv2.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p lv2 -o ./myeffect_lv2
cd myeffect_lv2 && cmake -B build && cmake --build build
# Output: build/myeffect.lv2/
```

macOS and Linux. Passes lilv-based instantiation and audio processing validation. LV2 headers fetched via CMake FetchContent (tag v1.18.10, ISC licensed). TTL metadata with real parameter names/ranges generated at project creation time.

## SuperCollider

See the [SuperCollider guide](docs/backends/supercollider.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p sc -o ./myeffect_sc
cd myeffect_sc && cmake -B build && cmake --build build
# Output: build/myeffect.scx (macOS) or build/myeffect.so (Linux)
```

Cross-platform (macOS, Linux, Windows). Passes sclang class compilation and scsynth NRT audio rendering validation. SC plugin headers fetched via CMake FetchContent (~80MB tarball). Generates `.sc` class file with parameter names/defaults. UGen name is auto-capitalized.

## VCV Rack

See the [VCV Rack guide](docs/backends/vcvrack.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p vcvrack -o ./myeffect_vcvrack
cd myeffect_vcvrack && make  # Rack SDK auto-downloaded
# Output: plugin.dylib (macOS), plugin.so (Linux), or plugin.dll (Windows)
```

Per-sample processing via `perform(n=1)`. Auto-generates `plugin.json` manifest and dark panel SVG. Passes headless Rack runtime validation (plugin loading + module instantiation). Rack SDK v2.6.1 auto-downloaded and cached.

## Daisy (Electrosmith)

See the [Daisy guide](docs/backends/daisy.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p daisy -o ./myeffect_daisy
gen-dsp build ./myeffect_daisy -p daisy
# Output: build/myeffect.bin
```

Cross-compilation target for STM32H750. Requires `arm-none-eabi-gcc`. libDaisy (v7.1.0) auto-cloned on first build. Supports 8 board variants via `--board` flag (seed, pod, patch, patch_sm, field, petal, legio, versio).

## Circle (Raspberry Pi bare metal)

See the [Circle guide](docs/backends/circle.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p circle --board pi3-i2s -o ./myeffect_circle
gen-dsp build ./myeffect_circle -p circle
# Output: kernel8.img (copy to SD card boot partition)
```

Bare-metal kernel images for Raspberry Pi using the [Circle](https://github.com/rsta2/circle) framework (no OS). Requires `aarch64-none-elf-gcc` (64-bit) or `arm-none-eabi-gcc` (32-bit Pi Zero). Circle SDK auto-cloned on first build. Supports 14 board variants via `--board` flag:

| Audio | Boards |
|-------|--------|
| I2S (external DAC) | `pi0-i2s`, `pi0w2-i2s`, `pi3-i2s` (default), `pi4-i2s`, `pi5-i2s` |
| PWM (3.5mm jack) | `pi0-pwm`, `pi0w2-pwm`, `pi3-pwm`, `pi4-pwm` |
| HDMI | `pi3-hdmi`, `pi4-hdmi`, `pi5-hdmi` |
| USB (USB DAC) | `pi4-usb`, `pi5-usb` |

### Circle Multi-Plugin Mode

Multi-plugin mode lets you run multiple gen~ plugins on a single Circle kernel image, with USB MIDI CC parameter control at runtime. Provide a JSON graph file via `--graph`:

```bash
gen-dsp init ./exports -n mychain -p circle --graph chain.json --board pi4-i2s -o ./mychain
cd mychain && make
# Output: kernel8-rpi4.img
```

#### Linear chain (auto-detected)

When connections form a simple series, gen-dsp uses an optimized ping-pong buffer codegen path:

```json
{
  "nodes": {
    "reverb": { "export": "gigaverb", "midi_channel": 1 },
    "comp":   { "export": "compressor", "midi_channel": 2,
                "cc": { "21": "threshold", "22": "ratio" } }
  },
  "connections": [
    ["audio_in", "reverb"],
    ["reverb",   "comp"],
    ["comp",     "audio_out"]
  ]
}
```

#### DAG with fan-out and mixer

For non-linear topologies, use fan-out (one output feeding multiple nodes) and built-in mixer nodes for fan-in:

```json
{
  "nodes": {
    "reverb":  { "export": "gigaverb" },
    "delay":   { "export": "spectraldelayfb" },
    "mix":     { "type": "mixer", "inputs": 2 }
  },
  "connections": [
    ["audio_in", "reverb"],
    ["audio_in", "delay"],
    ["reverb",   "mix:0"],
    ["delay",    "mix:1"],
    ["mix",      "audio_out"]
  ]
}
```

Mixer nodes combine inputs via weighted sum with per-input gain parameters (default 1.0, range 0.0-2.0), controllable via MIDI CC like any other parameter. The `"mix:0"` syntax routes to a specific mixer input index.

#### Graph reference

- **`nodes`**: dict of `id -> config`. Gen~ nodes require `"export"` (references a gen~ export directory name under the base `export_path`). Mixer nodes require `"type": "mixer"` and `"inputs"` count. `midi_channel` defaults to position + 1. `cc` is optional (default: CC-by-param-index).
- **`connections`**: list of `[from, to]` pairs. `audio_in` and `audio_out` are reserved endpoints. Use `"node:N"` to target a specific input index on mixer nodes.

The positional `export_path` argument is the base directory; each node's `export` field is resolved as a subdirectory (e.g. `./exports/gigaverb/gen/`). Use `--export /path/to/export` to provide explicit paths for individual nodes.

At runtime, connect a USB MIDI controller. Each node listens on its assigned MIDI channel for CC messages. With the default CC-by-index mapping, CC 0 controls parameter 0, CC 1 controls parameter 1, etc. Explicit `cc` mappings let you assign specific CC numbers to named parameters.

## Shared FetchContent Cache

CLAP, VST3, LV2, and SC backends use CMake FetchContent to download their SDKs/headers at configure time. By default each project downloads its own copy. Two opt-in mechanisms allow sharing a single download across projects:

### `--shared-cache` flag

Pass `--shared-cache` to `gen-dsp init` to bake an OS-appropriate cache path into the generated CMakeLists.txt:

```bash
gen-dsp init ./my_export -n myeffect -p vst3 --shared-cache
```

This resolves to:

| OS | Cache path |
|----|------------|
| macOS | `~/Library/Caches/gen-dsp/fetchcontent/` |
| Linux | `$XDG_CACHE_HOME/gen-dsp/fetchcontent/` (defaults to `~/.cache/`) |
| Windows | `%LOCALAPPDATA%/gen-dsp/fetchcontent/` |

### `GEN_DSP_CACHE_DIR` environment variable

Set this at cmake configure time to override any baked-in path (or use it without `--shared-cache`):

```bash
GEN_DSP_CACHE_DIR=/path/to/cache cmake ..
```

The env var takes highest priority, followed by the `--shared-cache` path, followed by CMake's default (project-local `build/_deps/`).

The development Makefile exports `GEN_DSP_CACHE_DIR=build/.fetchcontent_cache` automatically, so `make example-clap`, `make example-vst3`, `make example-lv2`, and `make example-sc` share the same SDK cache used by tests.

## Limitations

- Maximum of 5 buffers per external
- Buffers are single-channel only. Use multiple buffers for multi-channel audio.
- Max/MSP: Windows builds require Visual Studio or equivalent MSVC toolchain
- AudioUnit: macOS only
- CLAP: first CMake configure requires network access to fetch CLAP headers (cached afterward)
- VST3: first CMake configure requires network access to fetch VST3 SDK (~50MB, cached afterward); GPL3/proprietary dual license
- LV2: first CMake configure requires network access to fetch LV2 headers (cached afterward)
- SuperCollider: first CMake configure requires network access to fetch SC headers (~80MB tarball, cached afterward)
- VCV Rack: first build requires network access to fetch Rack SDK (cached afterward); `RACK_DIR` env var can override auto-download; per-sample `perform(n=1)` has higher CPU overhead than block-based processing
- Daisy: requires `arm-none-eabi-gcc` cross-compiler; first clone of libDaisy requires network access and `git`; v1 targets Daisy Seed only (no board-specific knob/CV mapping)
- Circle: requires `aarch64-none-elf-gcc` (or `arm-none-eabi-gcc` for Pi Zero) cross-compiler; first clone of Circle SDK requires network access and `git`; output-only (no audio input capture); single-plugin mode requires manual GPIO/ADC code for parameter control; multi-plugin mode (`--graph`) supports linear chains and arbitrary DAGs (fan-out, fan-in via mixer nodes) but no buffers

## Requirements

### Runtime

- Python >= 3.10
- C/C++ compiler (gcc, clang)

### PureData builds

- make
- PureData headers (typically installed with PureData)

### Max/MSP builds

- CMake >= 3.19
- git (for cloning max-sdk-base)

### ChucK builds

- make
- C/C++ compiler (clang on macOS, gcc on Linux)
- ChucK (for running the chugin)

### AudioUnit builds

- macOS (AudioUnit is macOS-only)
- CMake >= 3.19
- C/C++ compiler (clang via Xcode or Command Line Tools)

### CLAP builds

- CMake >= 3.19
- C/C++ compiler (clang, gcc)
- Network access on first configure (to fetch CLAP headers)

### VST3 builds

- CMake >= 3.19
- C/C++ compiler (clang, gcc, MSVC)
- Network access on first configure (to fetch VST3 SDK, ~50MB)

### LV2 builds

- CMake >= 3.19
- C/C++ compiler (clang, gcc)
- Network access on first configure (to fetch LV2 headers)

### SuperCollider builds

- CMake >= 3.19
- C/C++ compiler (clang, gcc)
- Network access on first configure (to fetch SC plugin headers)

### VCV Rack builds

- make
- C/C++ compiler (clang, gcc)
- Network access on first build (Rack SDK auto-downloaded and cached; override with `RACK_DIR` env var)

### Daisy builds

- make
- `arm-none-eabi-gcc` ([ARM GNU Toolchain Downloads](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads) -- select `arm-none-eabi`)
- git (for cloning libDaisy on first build)
- Network access on first build (to clone libDaisy + submodules)

### Circle builds

- make
- `aarch64-none-elf-gcc` ([ARM GNU Toolchain Downloads](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads) -- select `aarch64-none-elf`) or `arm-none-eabi-gcc` (for Pi Zero)
- git (for cloning Circle SDK on first build)
- Network access on first build (to clone Circle)

### macOS

Install Xcode or Command Line Tools:

```bash
xcode-select --install
```

### Linux / Organelle

Standard build tools (gcc, make) are typically pre-installed.

## Cross-Compilation Note

Build artifacts are platform-specific. When moving projects between macOS and Linux/Organelle:

```bash
make clean
make all
```

## Development

```bash
git clone https://github.com/samesimilar/gen-dsp.git
cd gen-dsp
uv venv && uv pip install -e ".[dev]"
source .venv/bin/activate
make test
```

### Building Example Plugins

The Makefile includes targets for generating and building example plugins from the test fixtures:

```bash
make example-pd       # PureData external
make example-max      # Max/MSP external
make example-chuck    # ChucK chugin
make example-au       # AudioUnit plugin (macOS only)
make example-clap     # CLAP plugin
make example-vst3     # VST3 plugin
make example-lv2      # LV2 plugin
make example-sc       # SuperCollider UGen
make example-vcvrack  # VCV Rack module (auto-downloads Rack SDK)
make example-daisy    # Daisy firmware (requires arm-none-eabi-gcc)
make example-circle   # Circle kernel image (requires aarch64-none-elf-gcc)
make examples         # All platforms
```

Override the fixture, name, or buffers:

```bash
make example-chuck FIXTURE=RamplePlayer NAME=rampleplayer BUFFERS="--buffers sample"
```

Available fixtures: `gigaverb` (default, no buffers), `RamplePlayer` (has buffers), `spectraldelayfb`.

Output goes to `build/examples/`.

### Adding New Backends

gen-dsp uses a platform registry system that makes it straightforward to add support for new audio platforms (Bela, Daisy, etc.). See [docs/new_backends.md](docs/new_backends.md) for a complete guide.

## Attribution

The gen~ language was created by [Graham Wakefield](https://github.com/grrrwaaa) at Cycling '74.

This project builds on the original idea and work of [gen_ext](https://github.com/samesimilar/gen_ext) by Michael Spears.

Test fixtures include code exported from examples bundled with Max:

- gigaverb: ported from Juhana Sadeharju's implementation
- spectraldelayfb: from gen~.spectraldelay_feedback

The Daisy backend was informed by techniques from [oopsy](https://github.com/electro-smith/oopsy) by Electrosmith and contributors, including Graham Wakefield.

The Circle backend uses [Circle](https://github.com/rsta2/circle) by Rene Stange, a C++ bare metal programming environment for the Raspberry Pi.

## License

MIT License. See [LICENSE](LICENSE) for details.

Note: Generated gen~ code is subject to Cycling '74's license terms.
