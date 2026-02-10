# gen_dsp TODO

## Backends

### Implemented

- [x] **PureData** - Primary target. Full support.

- [x] **Max/MSP** - Full support. See `src/gen_dsp/templates/max/`.

- [x] **ChucK** - Full support. Generates chugins (.chug) with multi-channel I/O and runtime parameter control. See `src/gen_dsp/templates/chuck/`.

- [x] **AudioUnit (AUv2)** - Full support. Generates macOS .component bundles using raw AUv2 C API (no SDK dependency). Auto-detects effect vs generator from I/O. See `src/gen_dsp/templates/au/`.

- [x] **CLAP** - Full support. Generates cross-platform .clap plugins using the CLAP C API (header-only, MIT licensed, fetched via CMake FetchContent). Zero-copy audio processing. Auto-detects effect vs instrument from I/O. See `src/gen_dsp/templates/clap/`.

- [x] **VST3** - Full support. Generates cross-platform .vst3 bundles using the Steinberg VST3 SDK (fetched via CMake FetchContent). Zero-copy audio processing. Auto-detects effect vs instrument from I/O. Deterministic FUID generation. See `src/gen_dsp/templates/vst3/`.

- [x] **LV2** - Full support. Generates cross-platform .lv2 bundles using the LV2 C API (header-only, ISC licensed, fetched via CMake FetchContent). TTL metadata generated with real parameter names/ranges parsed from gen~ exports. Auto-detects effect vs generator from I/O. See `src/gen_dsp/templates/lv2/`.

- [x] **SuperCollider UGens** - Full support. Generates cross-platform SC UGens (.scx on macOS, .so on Linux) using the SC plugin interface headers (fetched via CMake FetchContent). Generates .sc class files with parameter names/defaults parsed from gen~ exports. Auto-detects effect vs generator from I/O. See `src/gen_dsp/templates/sc/`.

- [x] **VCV Rack modules** - Full support. Generates VCV Rack modules using the Rack SDK's Makefile-based build system. Per-sample processing via perform(n=1). Auto-generates plugin.json manifest and panel SVG. Auto-detects effect vs generator from I/O. Parameter names/ranges parsed from gen~ exports. See `src/gen_dsp/templates/vcvrack/`.

### To Implement

#### Embedded/Hardware Targets

- [ ] **Bela** - BeagleBone-based real-time audio platform. C++ API, ultra-low latency. Similar audience to Organelle.
  - Docs: <https://learn.bela.io/>

- [ ] **Daisy (Electrosmith)** - STM32-based embedded audio. Powers commercial Eurorack modules and DIY projects.
  - Docs:
    - <https://github.com/electro-smith/libDaisy>
    - <https://github.com/electro-smith/DaisySP>

- [ ] **Teensy Audio Library** - Arduino-compatible, popular for DIY synths.
  - Docs: <https://www.pjrc.com/teensy/td_libs_Audio.html>

#### Other

- [ ] **JUCE (VST/AU/AAX)** - Abstracts plugin formats. Note: AU, CLAP, VST3, and LV2 are already covered natively without JUCE, so main value-add is AAX (Pro Tools, requires Avid NDA).
  - Docs: <https://juce.com/>

- [ ] **Web Audio (AudioWorklet + WASM)** - Compile gen~ to WebAssembly for browser. Growing interest in web-based audio.
  - Docs: <https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet>
