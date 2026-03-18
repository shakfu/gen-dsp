# Web Audio (AudioWorklet + WASM)

Generates browser-ready AudioWorklet + WebAssembly modules from gen~ exports or graph sources. Emscripten compiles C++ to WASM; the generated `processor.js` runs DSP in a real-time audio thread via `AudioWorkletProcessor`. Includes a demo page (`index.html`) with parameter sliders and a `make serve` target for local browser testing.

**OS support:** macOS, Linux, Windows (any platform with Emscripten)

## Prerequisites

- Python >= 3.10
- make
- [Emscripten SDK](https://emscripten.org/docs/getting_started/downloads.html) (`emcc` on PATH)

### Installing Emscripten

```bash
git clone https://github.com/emscripten-core/emsdk.git
cd emsdk
./emsdk install latest
./emsdk activate latest
source ./emsdk_env.sh
```

Verify with `emcc --version`.

## Quick Start

```bash
# Create a Web Audio project from a gen~ export
gen-dsp ./my_export -n myeffect -p webaudio -o ./myeffect_webaudio

# Build
cd myeffect_webaudio && make all

# Serve locally and open in browser
make serve
# Open http://localhost:8080
```

From a graph source:

```bash
gen-dsp graph compile fm_synth.gdsp -p webaudio
cd fm_synth_webaudio && make all && make serve
```

## Output Files

| File | Description |
|------|-------------|
| `processor.js` | Emscripten glue + AudioWorkletProcessor (concatenated at build time) |
| `build/<name>.wasm` | WebAssembly binary |
| `index.html` | Demo page with parameter sliders and start/stop controls |

## How It Works

1. `gen_ext_webaudio.cpp` bridges Emscripten exports (`wa_create`, `wa_perform`, etc.) to the gen~ wrapper functions via `EMSCRIPTEN_KEEPALIVE`
2. `_ext_webaudio.cpp` wraps genlib (header isolation pattern, same as all platforms)
3. `_processor.js` implements `AudioWorkletProcessor` with `parameterDescriptors` auto-generated from gen~ parameter metadata
4. At build time, `make` compiles C++ to WASM, then concatenates the Emscripten glue JS with `_processor.js` into the final `processor.js`
5. `index.html` loads the worklet module, creates an `AudioWorkletNode`, and renders parameter sliders

## Limitations

- Buffer loading is not yet supported (browser file I/O is async and browser-specific)
- Build integration tests require `emcc` and `node` on PATH (skipped in CI if unavailable)

## Platform Key

```text
"webaudio"
```
