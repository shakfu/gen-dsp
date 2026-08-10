# gen-dsp CLI Cheatsheet

## Default Command -- Generate a Plugin Project

```bash
gen-dsp <source> -p <platform> [options]
```

Source type is auto-detected: directory (gen~ export), `.gdsp` file, or `.json` file.

| Option | Description |
|--------|-------------|
| `-p, --platform PLATFORM` | Target platform(s) (required): a name, a comma-separated list (`clap,vst3,au`), or `all`. Names: `au`, `auv3`, `chuck`, `circle`, `clap`, `csound`, `daisy`, `lv2`, `max`, `pd`, `sc`, `standalone`, `vcvrack`, `vst3`, `webaudio` |
| `-n, --name NAME` | Plugin name (default: inferred from source) |
| `-o, --output DIR` | Output directory (default: `<name>_<platform>`; parent dir for multi-target) |
| `--config PATH` | Read defaults from a `gen-dsp.toml` (default: `./gen-dsp.toml` if present) |
| `--no-build` | Skip building after project creation |
| `--dry-run` | Show what would be done without creating files |
| `--buffers NAME [...]` | Explicit buffer names (overrides auto-detection) |
| `--no-patch` | Skip platform patches (e.g. `exp2f` fix) |
| `--no-shared-cache` | Disable shared OS cache for FetchContent downloads |
| `--cache-dir DIR` | Explicit FetchContent cache directory (baked into CMakeLists.txt) |
| `--board BOARD` | Board variant (see `gen-dsp list --boards daisy\|circle`) |
| `--no-midi` | Disable MIDI note handling |
| `--midi-gate NAME` | MIDI gate parameter name |
| `--midi-freq NAME` | MIDI frequency parameter name |
| `--midi-vel NAME` | MIDI velocity parameter name |
| `--midi-freq-unit {hz,midi}` | Unit for MIDI frequency parameter |
| `--voices N` | Polyphony voices (default: 1) |
| `--inputs-as-params [NAME ...]` | Remap signal inputs to parameters (no names = all; with names = only those) |
| `--tosc` | Also generate a TouchOSC control surface (requires `gen-dsp[tosc]`), plus OSC receiver glue for `pd` and `sc` |
| `--tosc-prefix NS` | OSC namespace (default: the plugin name) |
| `--tosc-port PORT` | UDP port for the generated Pd receiver (default: 8000) |

Examples:

```bash
gen-dsp ./my_export -p vst3
gen-dsp ./my_export -p clap -n myeffect -o ./build
gen-dsp ./my_export -p daisy --board pod
gen-dsp ./my_export -p pd --no-build --buffers sample envelope
gen-dsp synth.gdsp -p clap --midi-freq freq --midi-gate gate --voices 4
gen-dsp ./my_export -p clap,vst3,au          # multi-target
gen-dsp ./my_export -p all --no-build        # every platform
gen-dsp                                       # uses ./gen-dsp.toml
```

A `gen-dsp.toml` in the project directory supplies defaults (keys mirror the options above; `platform` may be a list or `all`). CLI flags override it.

## build -- Build an Existing Project

```bash
gen-dsp build [project-path] [-p PLATFORM] [--clean] [-v]
```

| Option | Description |
|--------|-------------|
| `project-path` | Path to project directory (default: current directory) |
| `-p, --platform PLATFORM` | Target platform (default: `pd`) |
| `--clean` | Clean before building |
| `-v, --verbose` | Show build output |

## detect -- Analyze a gen~ Export or Graph File

```bash
gen-dsp detect <path> [--json]
```

For a gen~ export directory: name, signal I/O counts, parameters, detected buffers, and needed patches. For a `.gdsp`/`.json` graph file: name, I/O, parameters with ranges, node-type breakdown, buffers, delay lines, and validity.

## manifest -- Emit JSON Manifest

```bash
gen-dsp manifest <export-path> [--buffers NAME ...]
```

Outputs a JSON manifest describing I/O counts, parameters with ranges, and buffers.

## tosc -- Generate a TouchOSC Control Surface

Requires `pip install gen-dsp[tosc]`.

```bash
gen-dsp tosc <source> [-o PATH] [-n NAME] [--prefix NS] [--port PORT]
                      [--columns N] [--rows N] [--size WxH]
                      [--no-osc] [--no-midi] [--xml] [--receiver pd|sc|none]
```

The source can be a generated project, a gen~ export, a `manifest.json`, or a
`.gdsp`/`.json` graph file. One captioned fader per parameter, each sending OSC
scaled into the parameter's range and a MIDI CC numbered by parameter index.
Pointing it at a generated project reuses that project's platform and name and
writes back into it, including OSC receiver glue for the `pd` and `sc` targets.

`--tosc` on the default command does the same as part of project generation;
see [TouchOSC Surfaces](tosc.md).

## patch -- Apply Platform-Specific Patches

```bash
gen-dsp patch <target-path> [--dry-run]
```

Currently applies the `exp2f -> exp2` fix for macOS compatibility with Max 9 exports.

## chain -- Multi-Plugin Chain Mode (Circle)

```bash
gen-dsp chain <export-path> --graph GRAPH -n NAME [-p PLATFORM] [-o OUTPUT] [options]
```

| Option | Description |
|--------|-------------|
| `export-path` | Base directory for gen~ exports |
| `--graph GRAPH` | JSON graph file for multi-plugin chain (required) |
| `-n, --name NAME` | Name for the chain project (required) |
| `-p, --platform PLATFORM` | Target platform (default: `circle`) |
| `-o, --output OUTPUT` | Output directory (default: `./<name>`) |
| `--export EXPORTS` | Additional export path (repeatable) |
| `--board BOARD` | Board variant |
| `--no-patch` | Skip platform patches |
| `--no-build` | Skip building |
| `--dry-run` | Show what would be done |

## compile -- Compile Graph to C++ (requires gen-dsp[graph])

```bash
gen-dsp compile <file> [-o DIR] [--optimize]
```

Compiles a `.gdsp` or `.json` graph file to C++. Outputs to stdout by default, or to a directory with `-o`.

## validate -- Validate a Graph File (requires gen-dsp[graph])

```bash
gen-dsp validate <file> [--warn-unmapped-params]
```

Checks graph connectivity and type correctness.

## viz -- Generate Graph Visualization (DOT) (requires gen-dsp[graph])

```bash
gen-dsp viz <file> [-o DIR]   # 'dot' is a deprecated alias
```

Generates a Graphviz DOT file for the graph.

## sim -- Simulate a Graph (requires gen-dsp[sim])

```bash
gen-dsp sim <file> [-i [NAME=]FILE] [-o DIR] [-n SAMPLES] [--param NAME=VALUE] [--sample-rate SR] [--optimize]
```

| Option | Description |
|--------|-------------|
| `-i, --input [NAME=]FILE` | Map audio input to WAV file (repeatable) |
| `-o, --output DIR` | Output directory (default: current dir) |
| `-n, --samples N` | Number of samples (required for generators) |
| `--param NAME=VALUE` | Set parameter (repeatable) |
| `--sample-rate SR` | Override sample rate |
| `--optimize` | Optimize before simulation |

## list -- List Available Platforms

```bash
gen-dsp list                  # platform names, one per line
gen-dsp list -v               # name, build system, extension, description
gen-dsp list --json           # machine-readable metadata
gen-dsp list --boards daisy   # valid --board variants for a platform
```

## cache -- Show or Prune Cached SDKs

```bash
gen-dsp cache                    # list cached SDKs with sizes
gen-dsp cache --prune            # delete them (asks for confirmation)
gen-dsp cache --prune -y         # delete without prompting
gen-dsp cache --prune --dry-run  # preview what would be removed
```

## doctor -- Check Build Prerequisites

```bash
gen-dsp doctor              # all platforms
gen-dsp doctor -p daisy     # one platform
gen-dsp doctor --json       # machine-readable
```

Reports, per platform, whether the host has the tools needed to build (compilers, CMake/Make, cross-toolchains, Emscripten, Xcode, git), with install hints. Exits non-zero when a requested platform is not ready (usable as a CI gate).

## Global Options

| Option | Description |
|--------|-------------|
| `-V, --version` | Show version |
| `-h, --help` | Show help |
