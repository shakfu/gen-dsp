# Standalone (miniaudio)

Generates self-contained CLI audio applications using [miniaudio](https://miniaud.io/) (public domain, single-header, zero-dependency). Processes real-time audio from the system's default input/output devices.

**OS support:** macOS (CoreAudio), Linux (ALSA/PulseAudio), Windows (WASAPI)

## Prerequisites

- Python >= 3.10
- C++ compiler (`c++` or `g++`)
- make
- curl (for downloading miniaudio.h at build time)

## Quick Start

```bash
# From a gen~ export
gen-dsp ./my_export -n myeffect -p standalone
cd myeffect_standalone && make all

# Run
./myeffect -p revtime 0.8 -p roomsize 0.5

# List parameters
./myeffect -l
```

From a graph source:

```bash
python examples/graph/fm_synth.py -p standalone -b
./build/examples/fm_synth_standalone/fm_synth -p gate 1 -p freq 440 -p amp 0.3
```

## CLI Flags

| Flag | Description | Default |
|------|-------------|---------|
| `-sr <rate>` | Sample rate in Hz | 44100 |
| `-bs <frames>` | Block size in frames | 256 |
| `-p <name> <value>` | Set parameter (repeatable) | -- |
| `-l` | List parameters and exit | -- |
| `-h` | Show help | -- |

## How It Works

1. `gen_ext_standalone.cpp` implements `main()` with miniaudio audio callback, CLI argument parsing, and audio device setup
2. `_ext_standalone.cpp` wraps genlib (header isolation pattern)
3. miniaudio.h is downloaded at build time via `curl` (not bundled)
4. Mono gen~ outputs are automatically duplicated to stereo for device compatibility
5. Audio I/O conversion: miniaudio delivers interleaved float; the callback deinterleaves for gen~'s per-channel `float**` layout

## Platform Key

```text
"standalone"
```
