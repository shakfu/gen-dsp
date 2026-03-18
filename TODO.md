# TODO

gen-dsp can be consumed as a library by [dsp-graph](https://github.com/shakfu/dsp-graph), a React/FastAPI web IDE that imports `gen_dsp.graph.*`directly. Prioritities in this document reflect both standalone CLI use and the requirements to work as a library (especially with dsp-grap).

---

## Medium Priority

### Web Audio backend follow-ups

- [ ] **Web Audio buffer loading** -- The `webaudio` backend currently stubs buffer support
  (`WRAPPER_BUFFER_COUNT 0`). Browser file loading is async and browser-specific; needs a
  `wa_load_buffer()` Emscripten export + JS-side `fetch()` + `decodeAudioData()` bridge.

- [ ] **Web Audio build integration tests** -- Currently gated by `emcc` availability (skipped
  in CI). Consider adding Emscripten to CI or a lightweight WASM validation step.

### Testing

- [ ] **Parameter sanitization tests** -- `_sanitize_symbol()` (LV2) and SC arg sanitization lack edge-case unit tests (empty string, Unicode, leading digits). Correctness risk.

- [ ] **More fixture diversity** -- No mono (1-in/1-out), high channel count, multi-buffer, or zero-parameter (other than RamplePlayer) fixtures. dsp-graph exercises more graph shapes than the CLI tests do.

- [ ] **CLI integration tests for `cache` and `manifest` commands.**

### Templates

- [ ] **R10. Switch templates from `safe_substitute()` to `substitute()` with validation** --
  Catches typos in template variables at generation time rather than producing broken build files. Requires auditing all templates to ensure no intentional unsubstituted `$` tokens (beyond `$$` for make variables).

### CLI / UX

- [ ] **`cache clean` subcommand** -- Let users reclaim disk space from downloaded SDKs. Relevant for both CLI users and dsp-graph deployments that accumulate SDK fetches.

- [ ] **`build` command could auto-detect platform** from `manifest.json` in project directory, removing the need for `-p <platform>`.

---

## Low Priority / Housekeeping

### Minor Code Quality

- [ ] **`builder.py` may be too thin a wrapper** -- adds no logic beyond `get_platform(name).build()`. Note: dsp-graph calls `Builder(project_dir).build(platform)`, so removing the class would require a coordinated change in both repos.

### CLI / UX

- [ ] **`list` command could show descriptions** -- Currently just prints platform names. Could show build system type, supported OS, brief description. Less pressing since dsp-graph has its own platform listing via `/api/build/platforms`.

- [ ] **`--board` dynamic listing** -- Consider `gen-dsp list --boards daisy` to dynamically list valid boards instead of hardcoding in help text.

- [ ] **Rename `dot` subcommand to `viz`** -- The current name is implementation-specific (Graphviz DOT format). Renaming allows for future visualization methods beyond DOT (e.g., SVG, interactive web view). dsp-graph uses the Python API (`graph_to_dot()`) directly, not the CLI subcommand.

### Documentation

- [ ] **API documentation for core modules** (`parser`, `manifest`, `project`, `builder`) for CLI library users. Lower priority than graph subpackage docs since dsp-graph doesn't consume these.

- [ ] **Architecture diagram** (visual, not just text in CLAUDE.md).
- [ ] **`pyproject.toml` keywords** missing newer platform names (chuck, audiounit, clap, vst3, lv2, supercollider, daisy, vcvrack, circle).
- [ ] **`pyproject.toml` classifiers** missing `"Operating System :: Microsoft :: Windows"` despite Windows support.

---

## New Backends

### Embedded / Hardware

- [ ] **Bela** - BeagleBone-based real-time audio platform. C++ API, ultra-low latency.
  - Docs: <https://learn.bela.io/>

- [ ] **Teensy Audio Library** - Arduino-compatible, popular for DIY synths.
  - Docs: <https://www.pjrc.com/teensy/td_libs_Audio.html>

- [ ] **OWL (Rebel Technology)** - Programmable guitar pedal platform with a C++ API. Similar to
  Daisy in concept, small but dedicated community.
  - Docs: <https://www.rebeltech.org/docs/>

### Standalone

- [x] **Standalone (miniaudio)** - Self-contained CLI executable that processes audio
  I/O directly. Useful for testing, prototyping, and headless audio appliances (Raspberry Pi,
  etc.). Minimal API surface -- just open a stream and call `perform()`. miniaudio is a single
  header file with no dependencies. Platform key: `"standalone"`.
  - miniaudio: <https://miniaud.io/>
  - PortAudio: <http://www.portaudio.com/>

### Plugin Frameworks

- [ ] **AUv3 (iOS/macOS)** - Modern Audio Unit API, required for iOS and increasingly preferred
  on macOS. Obj-C/Swift wrapper around C++ gen~ core. Significantly different from AUv2 (uses
  AUAudioUnit base class, Cocoa extension model). Large market.
  - Docs: <https://developer.apple.com/documentation/audiotoolbox/audio_unit_v3_plug-ins>

- [ ] **DISTRHO Plugin Framework (DPF)** - Can build LADSPA, DSSI, LV2, VST2, VST3, and CLAP.
  Main value-add over current coverage is LADSPA/DSSI. JACK/Standalone mode useful for headless
  testing.
  - Docs: <https://distrho.github.io/DPF/>

- [ ] **JUCE (VST/AU/AAX)** - Abstracts plugin formats. AU, CLAP, VST3, and LV2 are already
  covered natively without JUCE, so the only real value-add is AAX (Pro Tools). Requires Avid NDA. Low priority unless Pro Tools support is specifically requested.
  - Docs: <https://juce.com/>

### Hardware Platforms

- [ ] **Move Everything (Ableton Move)** - Unofficial framework for custom DSP on Ableton Move
  hardware. ARM64 Linux `.so` plugins via C plugin API v2. Key challenges: int16 stereo
  interleaved audio (not float), cross-compilation, stereo-only I/O. CC BY-NC-SA 4.0 license
  may constrain template code. Closest analog: Daisy backend.
  - Repo: <https://github.com/charlesvestal/move-everything>
  - Assessment: [docs/move-everything.md](docs/move-everything.md)

### Game Audio

- [ ] **FMOD plugin** - Game audio middleware with a clean C DSP plugin API. Taps into game audio
  market that gen-dsp currently doesn't reach.
  - Docs: <https://www.fmod.com/docs/2.03/api/plugin-api.html>

- [ ] **Wwise plugin** - Audiokinetic's game audio middleware. C++ plugin API. Similar market to
  FMOD but different ecosystem (Unreal-heavy).
  - Docs: <https://www.audiokinetic.com/en/library/edge/?source=SDK>

### Academic / Music Languages

- [x] **Csound opcode** - Well-defined C API for custom opcodes. Niche but long-lived community
  (academic, electroacoustic composition). Platform key: `"csound"`.
  - Docs: <https://csound.com/docs/manual/OrchTop.html>
