# gen-dsp

gen-dsp is a zero-dependency Python CLI that generates buildable audio DSP plugin projects from Max/MSP gen~ code exports. It also includes an optional graph frontend that enables defining DSP graphs in Python/JSON and compiling them through the same pipeline.

## Supported Platforms

| Platform | Key | Build System | Output |
|----------|-----|--------------|--------|
| PureData | `pd` | make (pd-lib-builder) | `.pd_darwin` / `.pd_linux` |
| Max/MSP | `max` | CMake | `.mxo` bundle |
| ChucK | `chuck` | make | `.chug` |
| AudioUnit (AUv2) | `au` | CMake | `.component` bundle |
| AUv3 | `auv3` | CMake (Xcode) | `.app` + `.appex` |
| CLAP | `clap` | CMake (FetchContent) | `.clap` bundle |
| VST3 | `vst3` | CMake (FetchContent) | `.vst3` bundle |
| LV2 | `lv2` | CMake (FetchContent) | `.lv2` bundle |
| SuperCollider | `sc` | CMake (FetchContent) | `.scx` / `.so` |
| VCV Rack | `vcvrack` | make (Rack SDK) | `plugin.dylib` / `.so` |
| Daisy | `daisy` | make (libDaisy) | `.bin` firmware |
| Circle | `circle` | make (Circle SDK) | `.img` kernel image |
| Web Audio | `webaudio` | make (Emscripten) | `.wasm` + `processor.js` |
| Standalone | `standalone` | make (miniaudio) | native executable |
| Csound | `csound` | make | `.dylib` / `.so` opcode |

## Quick Start

```bash
pip install gen-dsp

# Generate a CLAP plugin from a gen~ export
gen-dsp ./my_export -n myeffect -p clap

# Build it
cd myeffect_clap && cmake -B build && cmake --build build
```

## Installation

```bash
# Core (zero dependencies)
pip install gen-dsp

# With graph frontend
pip install gen-dsp[graph]

# With graph simulation (numpy)
pip install gen-dsp[sim]
```
