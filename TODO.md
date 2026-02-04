# gen_ext TODO

## Backends

### Implemented

- **PureData** - Primary target. Full support.
- **Max/MSP** - Full support. See `src/gen_ext/templates/max/`.

### To Implement

#### High Priority

- **SuperCollider UGens** - Large academic/experimental community. C++ plugin API, block-based processing, buffer support via SndBuf. Well-documented UGen interface.
  - Docs: https://doc.sccode.org/Guides/WritingUGens.html

- **VCV Rack modules** - Virtual Eurorack with growing community. Sample-by-sample C++ API. Visual/modular paradigm aligns with gen~ patching approach.
  - Docs: https://vcvrack.com/manual/PluginDevelopmentTutorial

- **LV2 plugins** - Open standard for Linux audio. Important for open-source DAWs (Ardour, REAPER on Linux, Bitwig). Supports buffers.
  - Docs: https://lv2plug.in/

- **JUCE (VST/AU/AAX)** - Broadest commercial reach. Abstracts plugin formats. Significant effort but high payoff.
  - Docs: https://juce.com/

#### Embedded/Hardware Targets

- **Bela** - BeagleBone-based real-time audio platform. C++ API, ultra-low latency. Similar audience to Organelle.
  - Docs: https://learn.bela.io/

- **Daisy (Electrosmith)** - STM32-based embedded audio. Powers commercial Eurorack modules and DIY projects.
  - Docs: https://github.com/electro-smith/DaisySP

- **Teensy Audio Library** - Arduino-compatible, popular for DIY synths.
  - Docs: https://www.pjrc.com/teensy/td_libs_Audio.html

#### Other

- **ChucK Chugins** - Academic/experimental. Sample-synchronous programming model.
  - Docs: https://github.com/ccrma/chugins

- **Web Audio (AudioWorklet + WASM)** - Compile gen~ to WebAssembly for browser. Growing interest in web-based audio.
  - Docs: https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet
