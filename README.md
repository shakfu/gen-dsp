# gen_dsp

Generate PureData and Max/MSP externals from Max gen~ exports.

gen_dsp compiles code exported from Max gen~ objects into external objects for PureData and Max/MSP. It automates project setup, buffer detection, and platform-specific patches.

## Installation

```bash
pip install gen-dsp
```

Or install from source:

```bash
git clone https://github.com/samesimilar/gen_dsp.git
cd gen_dsp
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
- `-p, --platform` - Target platform: `pd` (default), `max`, or `both`
- `-o, --output` - Output directory (default: `./<name>`)
- `--buffers` - Explicit buffer names (overrides auto-detection)
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

gen_dsp scans your gen~ export for buffer usage patterns and configures them automatically:

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

Max 9 exports include `exp2f` which fails on macOS. gen_dsp automatically patches this to `exp2` during project creation, or you can apply it manually:

```bash
gen-dsp patch ./my_project --dry-run  # Preview
gen-dsp patch ./my_project            # Apply
```

## Using the External in PureData

### Parameters

Send `<parameter-name> <value>` messages to the first inlet:

```
[frequency 440(
|
[mysynth~]
```

Send `bang` to print all available parameters.

### Buffers

Buffers connect to PureData arrays with matching names. To remap a buffer to a different array:

```
[pdset original_buffer new_array(
|
[mysampler~]
```

### Sample Rate and Block Size

For subpatches with custom block sizes (e.g., spectral processing):

```
[pdsr 96000(  <- Set sample rate
[pdbs 2048(   <- Set block size
|
[myspectral~]
```

## Max/MSP Support

gen_dsp supports generating Max/MSP externals using CMake and the max-sdk-base submodule.

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

### Key Differences from PureData

| Aspect | PureData | Max/MSP |
|--------|----------|---------|
| Signal type | float (32-bit) | double (64-bit) |
| Buffer storage | float (32-bit) | float (32-bit) |
| Build system | make (pd-lib-builder) | CMake (max-sdk-base) |
| Buffer access | Direct array | Lock/unlock API |
| Output format | .pd_darwin / .pd_linux | .mxo / .mxe64 |

For PureData, gen~ is compiled with 32-bit float signals. For Max, gen~ uses native 64-bit double signals, with automatic float conversion for buffer access (Max buffers are always 32-bit).

## Limitations

- Maximum of 5 buffers per external
- Buffers are single-channel only. Use multiple buffers for multi-channel audio.
- Max/MSP: Windows builds require Visual Studio or equivalent MSVC toolchain

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
git clone https://github.com/samesimilar/gen_dsp.git
cd gen_dsp
uv venv && uv pip install -e ".[dev]"
source .venv/bin/activate
make test
```

### Adding New Backends

gen_dsp uses a platform registry system that makes it straightforward to add support for new audio platforms (SuperCollider, VCV Rack, LV2, etc.). See [ADDING_NEW_BACKENDS.md](ADDING_NEW_BACKENDS.md) for a complete guide.

## Attribution

Test fixtures include code exported from examples bundled with Max:
- gigaverb: ported from Juhana Sadeharju's implementation
- spectraldelayfb: from gen~.spectraldelay_feedback

## License

MIT License. See [LICENSE](LICENSE) for details.

Note: Generated gen~ code is subject to Cycling '74's license terms.
