# gen-dsp

This project is a friendly fork of Michael Spears' [gen_ext](https://github.com/samesimilar/gen_ext) which was originally created to "compile code exported from a Max gen~ object into an "external" object that can be loaded into a PureData patch."

This fork has taken this excellent original idea and implementation and extended it to include Max/MSP externals, ChucK chugins, AudioUnit (AUv2) plugins, CLAP plugins, VST3 plugins, LV2 plugins, SuperCollider UGens, VCV Rack modules, Daisy (Electrosmith) embedded firmware, and possibly other DSP architectures (see [TODO.md](TODO.md)).

gen-dsp compiles code exported from Max gen~ objects into external objects for PureData, Max/MSP, ChucK, AudioUnit (AUv2), CLAP, VST3, LV2, SuperCollider, VCV Rack, and Daisy (Electrosmith). It automates project setup, buffer detection, and platform-specific patches.

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

## Key Improvements

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

- **VCV Rack support**: Generates VCV Rack modules with per-sample processing, auto-generated `plugin.json` manifest and panel SVG -- requires pre-installed Rack SDK.

- **Daisy support**: Generates Daisy Seed firmware (.bin) with custom genlib runtime (bump allocator for SRAM/SDRAM) -- first embedded/cross-compilation target, requires `arm-none-eabi-gcc`.

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
- `-p, --platform` - Target platform: `pd` (default), `max`, `chuck`, `au`, `clap`, `vst3`, `lv2`, `sc`, `vcvrack`, `daisy`, or `both`
- `-o, --output` - Output directory (default: `./<name>`)
- `--buffers` - Explicit buffer names (overrides auto-detection)
- `--shared-cache` - Use a shared OS cache for FetchContent downloads (clap, vst3, lv2, sc only)
- `--no-patch` - Skip automatic exp2f fix
- `--dry-run` - Preview without creating files

### build

Build an existing project:

```bash
gen-dsp build [project-path] [-p <platform>] [--clean] [-v]
```

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

Currently applies the exp2f -> exp2 fix for macOS compatibility with Max 9 exports.

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

Class names are auto-capitalized (`myeffect` -> `Myeffect`). Parameters are controlled via `eff.param("name", value)`.

## AudioUnit (AUv2)

See the [AudioUnit guide](docs/backends/audiounit.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p au -o ./myeffect_au
cd myeffect_au && cmake -B build && cmake --build build
# Output: build/myeffect.component
```

macOS only. Uses the raw AUv2 C API -- no external SDK needed, just system frameworks. Auto-detects `aufx` (effect) vs `augn` (generator).

## CLAP

See the [CLAP guide](docs/backends/clap.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p clap -o ./myeffect_clap
cd myeffect_clap && cmake -B build && cmake --build build
# Output: build/myeffect.clap
```

Cross-platform (macOS, Linux, Windows). Zero-copy audio. CLAP headers fetched via CMake FetchContent (tag 1.2.2, MIT licensed).

## VST3

See the [VST3 guide](docs/backends/vst3.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p vst3 -o ./myeffect_vst3
cd myeffect_vst3 && cmake -B build && cmake --build build
# Output: build/VST3/Release/myeffect.vst3/
```

Cross-platform (macOS, Linux, Windows). Zero-copy audio. VST3 SDK fetched via CMake FetchContent (tag v3.7.9_build_61, GPL3/proprietary dual licensed).

## LV2

See the [LV2 guide](docs/backends/lv2.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p lv2 -o ./myeffect_lv2
cd myeffect_lv2 && cmake -B build && cmake --build build
# Output: build/myeffect.lv2/
```

macOS and Linux. LV2 headers fetched via CMake FetchContent (tag v1.18.10, ISC licensed). TTL metadata with real parameter names/ranges generated at project creation time.

## SuperCollider

See the [SuperCollider guide](docs/backends/supercollider.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p sc -o ./myeffect_sc
cd myeffect_sc && cmake -B build && cmake --build build
# Output: build/myeffect.scx (macOS) or build/myeffect.so (Linux)
```

Cross-platform (macOS, Linux, Windows). SC plugin headers fetched via CMake FetchContent (~80MB tarball). Generates `.sc` class file with parameter names/defaults. UGen name is auto-capitalized.

## VCV Rack

See the [VCV Rack guide](docs/backends/vcvrack.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p vcvrack -o ./myeffect_vcvrack
cd myeffect_vcvrack && make  # Rack SDK auto-downloaded
# Output: plugin.dylib (macOS), plugin.so (Linux), or plugin.dll (Windows)
```

Per-sample processing via `perform(n=1)`. Auto-generates `plugin.json` manifest and dark panel SVG. Rack SDK v2.6.1 auto-downloaded and cached.

## Daisy (Electrosmith)

See the [Daisy guide](docs/backends/daisy.md) for full details.

```bash
gen-dsp init ./my_export -n myeffect -p daisy -o ./myeffect_daisy
gen-dsp build ./myeffect_daisy -p daisy
# Output: build/myeffect.bin
```

Cross-compilation target for STM32H750. Requires `arm-none-eabi-gcc`. libDaisy (v7.1.0) auto-cloned on first build. Supports 8 board variants via `--board` flag (seed, pod, patch, patch_sm, field, petal, legio, versio).

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
- AudioUnit: macOS only; initial implementation may not pass all `auval` checks
- CLAP: first CMake configure requires network access to fetch CLAP headers (cached afterward)
- VST3: first CMake configure requires network access to fetch VST3 SDK (~50MB, cached afterward); GPL3/proprietary dual license
- LV2: first CMake configure requires network access to fetch LV2 headers (cached afterward)
- SuperCollider: first CMake configure requires network access to fetch SC headers (~80MB tarball, cached afterward)
- VCV Rack: requires pre-installed Rack SDK (`RACK_DIR` env var); per-sample `perform(n=1)` has higher CPU overhead than block-based processing
- Daisy: requires `arm-none-eabi-gcc` cross-compiler; first clone of libDaisy requires network access and `git`; v1 targets Daisy Seed only (no board-specific knob/CV mapping)

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
- VCV Rack SDK (`RACK_DIR` environment variable must point to SDK path)

### Daisy builds

- make
- `arm-none-eabi-gcc` (ARM GCC toolchain for cross-compilation)
- git (for cloning libDaisy on first build)
- Network access on first build (to clone libDaisy + submodules)

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
make example-vcvrack  # VCV Rack module (requires RACK_DIR)
make example-daisy    # Daisy firmware (requires arm-none-eabi-gcc)
make examples         # All platforms
```

Override the fixture, name, or buffers:

```bash
make example-chuck FIXTURE=RamplePlayer NAME=rampleplayer BUFFERS="--buffers sample"
```

Available fixtures: `gigaverb` (default, no buffers), `RamplePlayer` (has buffers), `spectraldelayfb`.

Output goes to `build/examples/`.

### Adding New Backends

gen-dsp uses a platform registry system that makes it straightforward to add support for new audio platforms (VCV Rack, Bela, Daisy, etc.). See [docs/new_backends.md](docs/new_backends.md) for a complete guide.

## Attribution

Test fixtures include code exported from examples bundled with Max:

- gigaverb: ported from Juhana Sadeharju's implementation
- spectraldelayfb: from gen~.spectraldelay_feedback

## License

MIT License. See [LICENSE](LICENSE) for details.

Note: Generated gen~ code is subject to Cycling '74's license terms.
