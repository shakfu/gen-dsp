# Move Everything Backend Assessment

Feasibility review for adding [Move Everything](https://github.com/charlesvestal/move-everything) as a gen-dsp target backend.

## What is Move Everything?

An unofficial open-source framework for running custom instruments/effects on **Ableton Move** hardware. It intercepts the device's SPI communication via an LD_PRELOAD shim and runs custom DSP modules as native ARM64 `.so` shared libraries on the device's Linux OS.

- Author: Charles Vestal
- License: CC BY-NC-SA 4.0
- Language: C (DSP), JavaScript (UI via embedded QuickJS)

## Plugin API (v2)

Well-defined C plugin interface:

- `create_instance(module_dir, json_defaults)` / `destroy_instance(instance)` -- lifecycle
- `render_block(instance, out_lr, frames)` -- 128-frame stereo int16 blocks, in-place
- `on_midi(instance, msg, len, source)` -- MIDI handling
- `set_param(instance, key, val)` / `get_param(instance, key, buf, len)` -- string-based params
- Entry point: `move_plugin_init_v2()` (generators) or `move_audio_fx_init_v2()` (effects)
- Packaged as a directory with `module.json` metadata

## Constraints vs. gen-dsp Typical Backends

| Aspect | gen-dsp typical | Move Everything |
|---|---|---|
| Audio format | `float*[]` per channel | int16 stereo interleaved |
| Sample rate | Host-determined | 44.1kHz fixed |
| Block size | Host-determined | 128 frames fixed |
| Channel layout | Arbitrary in/out counts | Stereo only (2in/2out) |
| Build target | Native or CMake/Make | ARM64 Linux cross-compile (Docker or aarch64-linux-gnu-gcc) |
| Plugin packaging | Binary + build system | `.so` + `module.json` directory |

## Feasibility: Yes, with caveats

Architecturally viable -- gen-dsp already has precedent for:

- Embedded ARM targets (Daisy backend)
- Make-based builds (ChucK, PD, VCV Rack, Daisy)
- Per-sample or per-block processing adaptation
- Custom genlib runtimes (Daisy's `genlib_daisy.cpp`)

## Implementation Requirements

1. **int16 conversion layer** -- gen~ works in float; `render_block` receives/produces interleaved int16. Wrapper needed to deinterleave int16->float on input, run gen~'s `perform()`, then interleave float->int16 on output.

2. **Custom genlib runtime** (`genlib_move.cpp`) -- Similar to Daisy's custom allocator, though less constrained (full Linux userspace, not bare-metal). Standard malloc/free likely sufficient.

3. **Cross-compilation** -- Docker-based or `aarch64-linux-gnu-gcc` toolchain. Similar complexity to Daisy's `arm-none-eabi-gcc`. Build would be a Makefile producing a `.so`.

4. **Stereo-only constraint** -- gen~ exports with >2 channels (e.g. spectraldelayfb's 3in/2out) would need channel mapping/clamping.

5. **`module.json` generation** -- Straightforward from `Manifest`'s `ParamInfo` list (name, min, max, default).

6. **No CMake** -- Pure gcc invocation or simple Makefile.

## Closest Analog

The Daisy backend is the closest existing parallel: embedded ARM target, custom genlib runtime, Make-based build, cross-compilation toolchain. Move Everything is simpler in some ways (full Linux userspace vs bare-metal, standard memory allocation) but adds the int16 interleaved audio format conversion.

## Open Questions

- **Licensing**: CC BY-NC-SA 4.0 is viral and non-commercial. Need to verify that the plugin API headers are usable without the NC restriction, or that gen-dsp's generated output (templates, runtime code) is not considered a derivative work.
- **API stability**: The project is relatively young and unofficial -- the plugin API could change.
- **Testing**: Build integration tests would require either Docker or `aarch64-linux-gnu-gcc` on the host, similar to Daisy's `arm-none-eabi-gcc` gating.
