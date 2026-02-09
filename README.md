# gen-dsp

This project is a friendly fork of Michael Spears' [gen_ext](https://github.com/samesimilar/gen_ext) which was originally created to "compile code exported from a Max gen~ object into an "external" object that can be loaded into a PureData patch."

This fork has taken this excellent original idea and implementation and extended it to include Max/MSP externals, ChucK chugins, AudioUnit (AUv2) plugins, CLAP plugins, VST3 plugins, LV2 plugins, and possibly other DSP architectures (see [TODO.md](TODO.md)).

gen-dsp compiles code exported from Max gen~ objects into external objects for PureData, Max/MSP, ChucK, AudioUnit (AUv2), CLAP, VST3, and LV2. It automates project setup, buffer detection, and platform-specific patches.

## Key Improvements

- **Python package**: gen-dsp is a pip installable zero-dependency python package with a cli which embeds all templates and related code.

- **Automated project scaffolding**: `gen-dsp init` creates a complete, buildable project from a gen~ export in one command, versus manually copying files and editing Makefiles.

- **Automatic buffer detection**: Scans exported code for buffer usage patterns and configures them without manual intervention.

- **Max/MSP support**: Generates CMake-based Max externals with proper 64-bit signal handling and buffer lock/unlock API.

- **ChucK support**: Generates chugins (.chug) with multi-channel I/O and runtime parameter control.

- **AudioUnit support**: Generates macOS AUv2 plugins (.component) using the raw C API -- no Apple SDK dependency, just system frameworks.

- **CLAP support**: Generates cross-platform CLAP plugins (.clap) with zero-copy audio processing -- CLAP headers fetched via CMake FetchContent.

- **VST3 support**: Generates cross-platform VST3 plugins (.vst3) with zero-copy audio processing -- Steinberg VST3 SDK fetched via CMake FetchContent.

- **LV2 support**: Generates cross-platform LV2 plugins (.lv2 bundles) with TTL metadata containing real parameter names/ranges parsed from gen~ exports -- LV2 headers fetched via CMake FetchContent.

- **Platform-specific patches**: Automatically fixes compatibility issues like the exp2f -> exp2 problem in Max 9 exports on macOS.

- **Analysis tools**: `gen-dsp detect` inspects exports to show I/O counts, parameters, and buffers before committing to a build.

- **Dry-run mode**: Preview what changes will be made before applying them.

- **Platform registry**: To make it easy to discover new backends

## Installation

install from source:

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
- `-p, --platform` - Target platform: `pd` (default), `max`, `chuck`, `au`, `clap`, `vst3`, `lv2`, or `both`
- `-o, --output` - Output directory (default: `./<name>`)
- `--buffers` - Explicit buffer names (overrides auto-detection)
- `--shared-cache` - Use a shared OS cache for FetchContent downloads (clap, vst3, lv2 only)
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

## Using the External in PureData

### Parameters

Send `<parameter-name> <value>` messages to the first inlet:

```text
[frequency 440(
|
[mysynth~]
```

Send `bang` to print all available parameters.

### Buffers

Buffers connect to PureData arrays with matching names. To remap a buffer to a different array:

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

## Max/MSP Support

gen-dsp supports generating Max/MSP externals using CMake and the max-sdk-base submodule.

### Quick Start (Max)

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

## ChucK Support

gen-dsp supports generating ChucK chugins (.chug files) using make and a bundled `chugin.h` header.

### Quick Start (ChucK)

```bash
# Create a ChucK project
gen-dsp init ./my_export -n myeffect -p chuck -o ./myeffect_chuck

# Build
cd myeffect_chuck
make mac    # macOS
make linux  # Linux

# Use in ChucK
# @import "Myeffect"
# Myeffect eff => dac;
```

### ChucK API

The generated chugin extends `UGen` and provides:

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

### Key Differences from PureData

| Aspect | ChucK | PureData |
|--------|-------|----------|
| Signal type | float (32-bit) | float (32-bit) |
| Build system | make (chugin pattern) | make (pd-lib-builder) |
| Output format | .chug | .pd_darwin / .pd_linux |
| Parameter access | `param(string, float)` | message to first inlet |
| Multi-channel | `CK_DLL_TICKF` (interleaved) | per-signal inlets/outlets |

## AudioUnit (AUv2) Support

gen-dsp supports generating macOS AudioUnit v2 plugins (.component bundles) using CMake and the raw AUv2 C API. No Apple AudioUnitSDK is needed -- only system frameworks (AudioToolbox, CoreFoundation, CoreAudio).

### Quick Start (AudioUnit)

```bash
# Create an AudioUnit project
gen-dsp init ./my_export -n myeffect -p au -o ./myeffect_au

# Build
cd myeffect_au
mkdir -p build && cd build
cmake .. && cmake --build .

# Output: build/myeffect.component

# Install (optional)
cp -r myeffect.component ~/Library/Audio/Plug-Ins/Components/
```

The plugin is automatically detected as an effect (`aufx`) if the gen~ export has inputs, or a generator (`augn`) if it has no inputs. The .component bundle is ad-hoc code signed during build.

### AU Plugin Details

- **Component type**: `aufx` (effect) or `augn` (generator), auto-detected from I/O
- **Subtype**: first 4 characters of the library name (lowercased)
- **Manufacturer**: `gdsp`
- **Parameters**: all gen~ parameters are exposed as AU parameters with name, min, max
- **Audio format**: Float32, non-interleaved (standard AU format)

## CLAP Support

gen-dsp supports generating cross-platform CLAP plugins (.clap files) using CMake and the CLAP C API (header-only, MIT licensed). CLAP headers are fetched automatically at configure time via CMake FetchContent.

### Quick Start (CLAP)

```bash
# Create a CLAP project
gen-dsp init ./my_export -n myeffect -p clap -o ./myeffect_clap

# Build
cd myeffect_clap
mkdir -p build && cd build
cmake .. && cmake --build .

# Output: build/myeffect.clap

# Install (optional)
# macOS:
cp myeffect.clap ~/Library/Audio/Plug-Ins/CLAP/
# Linux:
cp myeffect.clap ~/.clap/
```

The plugin is automatically detected as an audio effect if the gen~ export has inputs, or an instrument if it has no inputs. On macOS, the .clap file is ad-hoc code signed during build.

### CLAP Plugin Details

- **Plugin type**: `audio_effect` or `instrument`, auto-detected from I/O
- **Plugin ID**: `com.gen-dsp.<lib_name>`
- **Parameters**: all gen~ parameters exposed via the CLAP params extension (automatable)
- **Audio format**: Float32, non-interleaved (zero-copy -- CLAP's `data32` layout matches gen~'s `float**` exactly)
- **Cross-platform**: macOS and Linux (unlike AudioUnit)
- **Extensions**: `audio-ports`, `params`

## VST3 Support

gen-dsp supports generating cross-platform VST3 plugins (.vst3 bundles) using CMake and the Steinberg VST3 SDK. The SDK is fetched automatically at configure time via CMake FetchContent.

### Quick Start (VST3)

```bash
# Create a VST3 project
gen-dsp init ./my_export -n myeffect -p vst3 -o ./myeffect_vst3

# Build
cd myeffect_vst3
mkdir -p build && cd build
cmake .. && cmake --build .

# Output: build/VST3/Release/myeffect.vst3/

# Install (optional)
# macOS:
cp -r VST3/Release/myeffect.vst3 ~/Library/Audio/Plug-Ins/VST3/
# Linux:
cp -r VST3/Release/myeffect.vst3 ~/.vst3/
```

The plugin is automatically detected as an effect (`Fx`) if the gen~ export has inputs, or an instrument (`Instrument|Synth`) if it has no inputs. On macOS, the .vst3 bundle is ad-hoc code signed during build.

### VST3 Plugin Details

- **Plugin type**: `Fx` or `Instrument|Synth`, auto-detected from I/O
- **Plugin FUID**: deterministic 128-bit ID from MD5 of `com.gen-dsp.vst3.<lib_name>`
- **Parameters**: all gen~ parameters exposed as `RangeParameter` with real min/max/default (automatable)
- **Audio format**: Float32, non-interleaved (zero-copy -- VST3's `channelBuffers32` layout matches gen~'s `float**` exactly)
- **Cross-platform**: macOS, Linux, and Windows
- **SDK**: `SingleComponentEffect` (combined processor+controller) -- simplest VST3 plugin structure
- **License**: VST3 SDK is GPL3/proprietary dual licensed -- users needing a proprietary license must obtain one from Steinberg

## LV2 Support

gen-dsp supports generating cross-platform LV2 plugins (.lv2 bundle directories) using CMake and the LV2 C API (header-only, ISC licensed). LV2 headers are fetched automatically at configure time via CMake FetchContent.

### Quick Start (LV2)

```bash
# Create an LV2 project
gen-dsp init ./my_export -n myeffect -p lv2 -o ./myeffect_lv2

# Build
cd myeffect_lv2
mkdir -p build && cd build
cmake .. && cmake --build .

# Output: build/myeffect.lv2/

# Install (optional)
# macOS:
cp -r myeffect.lv2 ~/Library/Audio/Plug-Ins/LV2/
# Linux:
cp -r myeffect.lv2 ~/.lv2/
```

The plugin is automatically detected as an effect (`EffectPlugin`) if the gen~ export has inputs, or a generator (`GeneratorPlugin`) if it has no inputs. On macOS, the binary is ad-hoc code signed during build.

### LV2 Plugin Details

- **Plugin type**: `EffectPlugin` or `GeneratorPlugin`, auto-detected from I/O
- **Plugin URI**: `http://gen-dsp.com/plugins/<lib_name>`
- **Parameters**: all gen~ parameters exposed as LV2 control ports with real names and ranges parsed from the gen~ export
- **Audio format**: Float32, port-based (individual `float*` per audio channel, collected into arrays for `wrapper_perform()`)
- **Cross-platform**: macOS and Linux
- **TTL metadata**: `manifest.ttl` (discovery) and `<name>.ttl` (ports, parameters) generated at project creation time
- **Bundle output**: `.lv2` directory containing shared library + 2 TTL files

### Platform Comparison

| Aspect | LV2 | VST3 | CLAP | AudioUnit | ChucK | PureData | Max/MSP |
|--------|-----|------|------|-----------|-------|----------|---------|
| Signal type | float (32-bit) | float (32-bit) | float (32-bit) | float (32-bit) | float (32-bit) | float (32-bit) | double (64-bit) |
| Build system | CMake (FetchContent) | CMake (FetchContent) | CMake (FetchContent) | CMake | make | make (pd-lib-builder) | CMake (max-sdk-base) |
| Output format | .lv2 | .vst3 | .clap | .component | .chug | .pd_darwin / .pd_linux | .mxo / .mxe64 |
| macOS only | no | no | no | yes | no | no | no |
| External deps | LV2 headers (fetched) | VST3 SDK (fetched) | CLAP headers (fetched) | none (system frameworks) | none (bundled chugin.h) | PureData headers | max-sdk-base (git) |

### PureData vs Max/MSP

| Aspect | PureData | Max/MSP |
|--------|----------|---------|
| Signal type | float (32-bit) | double (64-bit) |
| Buffer storage | float (32-bit) | float (32-bit) |
| Build system | make (pd-lib-builder) | CMake (max-sdk-base) |
| Buffer access | Direct array | Lock/unlock API |
| Output format | .pd_darwin / .pd_linux | .mxo / .mxe64 |

For PureData, gen~ is compiled with 32-bit float signals. For Max, gen~ uses native 64-bit double signals, with automatic float conversion for buffer access (Max buffers are always 32-bit).

## Shared FetchContent Cache

CLAP, VST3, and LV2 backends use CMake FetchContent to download their SDKs/headers at configure time. By default each project downloads its own copy. Two opt-in mechanisms allow sharing a single download across projects:

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

The development Makefile exports `GEN_DSP_CACHE_DIR=build/.fetchcontent_cache` automatically, so `make example-clap`, `make example-vst3`, and `make example-lv2` share the same SDK cache used by tests.

## Limitations

- Maximum of 5 buffers per external
- Buffers are single-channel only. Use multiple buffers for multi-channel audio.
- Max/MSP: Windows builds require Visual Studio or equivalent MSVC toolchain
- AudioUnit: macOS only; initial implementation may not pass all `auval` checks
- CLAP: first CMake configure requires network access to fetch CLAP headers (cached afterward)
- VST3: first CMake configure requires network access to fetch VST3 SDK (~50MB, cached afterward); GPL3/proprietary dual license
- LV2: first CMake configure requires network access to fetch LV2 headers (cached afterward)

## Requirements

### Runtime

- Python >= 3.9
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
make examples         # All platforms
```

Override the fixture, name, or buffers:

```bash
make example-chuck FIXTURE=RamplePlayer NAME=rampleplayer BUFFERS="--buffers sample"
```

Available fixtures: `gigaverb` (default, no buffers), `RamplePlayer` (has buffers), `spectraldelayfb`.

Output goes to `build/examples/`.

### Adding New Backends

gen-dsp uses a platform registry system that makes it straightforward to add support for new audio platforms (SuperCollider, VCV Rack, etc.). See [NEW_BACKENDS.md](NEW_BACKENDS.md) for a complete guide.

## Attribution

Test fixtures include code exported from examples bundled with Max:

- gigaverb: ported from Juhana Sadeharju's implementation
- spectraldelayfb: from gen~.spectraldelay_feedback

## License

MIT License. See [LICENSE](LICENSE) for details.

Note: Generated gen~ code is subject to Cycling '74's license terms.
