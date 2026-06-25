# Percussa SSP Backend Assessment

Assessment of the [Percussa SSP SDK](https://github.com/percussa/ssp-sdk) as a
gen-dsp backend. Mirrors the structure of [move-everything.md](move-everything.md).

## What is the Percussa SSP?

The Percussa SSP (Super Signal Processor) is a high-end, ARM-Linux-based Eurorack
module / standalone: a programmable multi-channel DSP host with a colour display,
four encoders, and eight soft keys. The SDK lets third parties build native
modules that run on the device as shared libraries.

## Plugin API (Percussa.h, API 3.5)

SSP modules are `.so` shared libraries that export three C functions and
implement a small C++ interface in namespace `Percussa::SSP`:

- **C exports:** `createDescriptor() -> PluginDescriptor*`,
  `createInstance() -> PluginInterface*`,
  `getApiVersion(unsigned& major, unsigned& minor)`.
- **`PluginInterface`** (audio processor):
  - `prepare(double sampleRate, int samplesPerBlock)` -- init (~ gen~ `create`).
  - `process(float** channelData, int numChannels, int numSamples)` -- the DSP
    callback. Samples are **float32, planar** (`float**`).
  - `buttonPressed(int n, bool)` -- soft keys (0-7), navigation (8-11), shift (12-13).
  - `encoderPressed(int n, bool)` / `encoderTurned(int n, int)` -- encoders 0-3.
  - `inputEnabled(int n, bool)` / `outputEnabled(int n, bool)` -- per-channel enable.
  - `getState(void**, size_t*)` / `setState(void*, size_t)` -- preset save/load.
  - `getEditor() -> PluginEditorInterface*`.
- **`PluginEditorInterface`** (display): `renderToImage(unsigned char*, w, h)` (BGRA
  pixel buffer), `draw(w, h)` (OpenGL ES), `frameStart()`, `visibilityChanged(bool)`.
- **`PluginDescriptor`** (metadata): `name`, `descriptiveName`, `manufacturerName`,
  `version`, `uid` (matches the VST uid for preset compatibility),
  `inputChannelNames` / `outputChannelNames` (`vector<string>`), `colour` (BGRA).

Example module (`examples/api/test`): a `TestPluginInterface : Percussa::SSP::PluginInterface`
declaring 2 in / 2 out (`"In 1/2"`, `"Out 1/2"`), uid `0x54455354`.

**Channel layout (resolved).** `channelData` is a JUCE-style in-place buffer:
TheTechnobear's bridge wraps it directly as
`AudioSampleBuffer buffer(channelData, numChannels, numSamples)` and calls
`processBlock` with no copy. So the raw `float**` pointers are usable as-is; gen-dsp
would map them straight to genlib's `t_sample**` ins/outs. The exact input/output
split (separate `numIn` + `numOut` pointers vs. an in-place `max(in,out)` buffer) is
the one detail to confirm at runtime on the device.

## Build & toolchain

- **CMake** with a cross-compilation toolchain file `xcSSP.cmake`. The SSP runs
  **Rockchip ARM 32-bit hard-float Linux** (Buildroot); target triple
  `arm-rockchip-linux-gnueabihf`. Output is a `.so`.
- The toolchain + sysroot is a **free, public tarball** (a Buildroot SDK), not
  device- or account-tied:
  `https://sw13072022.s3.us-west-1.amazonaws.com/arm-rockchip-linux-gnueabihf_sdk-buildroot.tar.gz`.
  It is extracted under `~/buildroot/...` and the build points at it via
  `export BUILDROOT=...`. Because the URL is public, gen-dsp could **auto-fetch and
  cache** it the way it already does for libDaisy / Circle / the Rack SDK.
- The official SDK build also references Steinberg's **VST3 SDK** (`export VSTSDK=...`),
  but that is for the `examples/vst/` wrappers; the native `examples/api/` path -- the
  one gen-dsp would target -- should not need it (confirm).
- Dev hosts: macOS / Linux.
- Build: `cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_TOOLCHAIN_FILE=../xcSSP.cmake ..`
  then `cmake --build . -- -j4`.

### What `xcSSP.cmake` actually sets

- `CMAKE_SYSTEM_NAME Linux`, `CMAKE_SYSTEM_PROCESSOR armv7l`, triple
  `arm-linux-gnueabihf`.
- **Compiler is host Clang, not the Buildroot GCC.** `CMAKE_C/CXX_COMPILER` =
  `${TOOLSROOT}/clang(++)` with `CMAKE_C/CXX_COMPILER_TARGET=arm-linux-gnueabihf`.
  `TOOLSROOT` defaults to Homebrew LLVM on macOS (`/opt/homebrew/opt/llvm/bin` or
  `/usr/local/opt/llvm/bin`) and `/usr/bin` on Linux. So the host needs **LLVM/Clang**;
  the Buildroot tree supplies only the sysroot + GCC 8.4.0 libstdc++ (clang is pointed at
  its C++ headers via explicit `-I${BUILDROOT}/.../include/c++/8.4.0[...]`).
- `CMAKE_SYSROOT = ${BUILDROOT}/arm-rockchip-linux-gnueabihf/sysroot`;
  `GCCROOT = ${BUILDROOT}/lib/gcc/arm-rockchip-linux-gnueabihf/8.4.0`.
- **CPU flags:** `-mcpu=cortex-a17 -mfloat-abi=hard -mfpu=neon-vfpv4` -- the SSP is a
  **Cortex-A17** SoC (Rockchip RK3288-class), NEON / hard-float.
- Link flags add `-L/-B/-Wl,-rpath-link` for `${CMAKE_SYSROOT}/lib` and `${GCCROOT}`,
  applied to exe/module/shared linker flags.
- Env overrides: `BUILDROOT` (sysroot root) and `TOOLSROOT` (clang location).

This is reproducible by gen-dsp directly: emit a toolchain file that runs the host Clang
with `--target=arm-linux-gnueabihf`, the cached Buildroot sysroot, the libstdc++ 8.4.0
include paths, and the cortex-a17 NEON flags -- no Percussa `xcSSP.cmake` needed at
generation time. A `doctor` check would verify Clang and the Buildroot sysroot are
present.

## Constraints vs. gen-dsp typical backends

- **float32 planar** matches gen-dsp's `GENLIB_USE_FLOAT32` (`t_sample = float`) and
  gen~'s `float**` perform signature -- essentially a direct mapping, no int16 or
  interleave conversion (unlike Move).
- **No float-parameter API.** Control is via 4 encoders + 8 soft keys, not a CLAP/VST
  parameter list. gen~ params must be mapped onto the encoders with paging (as the
  Daisy/Circle backends map params to hardware knobs), with `getState`/`setState`
  serializing the current values for presets.
- **Cross-compile sysroot -- but auto-fetchable.** Unlike a device-tied SDK, the
  `arm-rockchip-linux-gnueabihf` Buildroot toolchain is a public tarball, so gen-dsp can
  download and cache it automatically (as it does libDaisy / Circle / Rack SDK) instead
  of requiring a user-set path. A `BUILDROOT` override (cf. `RACK_DIR`) can still point
  at an existing install.
- **AGPL-3.0 SDK.** `Percussa.h` is AGPL-3.0. Generated glue that includes it is
  AGPL-encumbered, and the resulting module is AGPL. gen-dsp itself is MIT; the
  SSP-specific template/glue files would carry the AGPL implications (the genlib and
  user DSP are separate TUs under the header-isolation pattern). Worth flagging to
  users, not a blocker.
- **Optional display.** `renderToImage`/`draw` can be stubbed or used to render a
  minimal parameter readout; not required for audio to work.

## Feasibility: Yes -- a good fit

The shared-library-plus-descriptor/instance model is very close to gen-dsp's existing
CLAP / LV2 backends, and `prepare`/`process` map almost 1:1 onto gen~'s
`create`/`perform`. float32 planar audio removes the format-conversion friction that
complicates the Move backend. The user owns the hardware, so the build and audio path
can be verified on-device.

## Implementation requirements

- Platform key `"ssp"`; `platforms/ssp.py` plus a `templates/ssp/` set.
- Header-isolation bridge `_ext_ssp.cpp` / `_ext_ssp.h`: the SSP-side `.cpp` includes
  only `Percussa.h`; the genlib-side `_ext*.cpp` includes only genlib; they meet at an
  opaque `GenState*` C interface (the established gen-dsp pattern).
- `process()` bridge: slice `channelData` into gen~ inputs (`[0 .. numIn)`) and outputs
  (`[numIn .. numIn+numOut)`) -- **exact layout to confirm on device** -- and call the
  genlib perform.
- Parameter -> encoder mapping with paging, plus `getState`/`setState` (de)serialization
  of param values; map `PluginDescriptor.inputChannelNames`/`outputChannelNames` from the
  manifest I/O.
- CMakeLists wired to a `xcSSP.cmake`-style toolchain. gen-dsp can auto-download and
  cache the public Buildroot toolchain tarball (like libDaisy / Circle), with a
  `BUILDROOT` env override for an existing install.
- Optional minimal `PluginEditorInterface` rendering param names/values.

## Reference implementation (TheTechnobear)

[TheTechnobear/SSP](https://github.com/TheTechnobear/SSP) is a mature, ~39-module
collection that proves the path end to end. Its `technobear/common/` provides a
reusable framework:

- `SSPApiProcessor.{h,cpp}` -- bridges `Percussa::SSP::PluginInterface` to a JUCE
  `AudioProcessor` (`AudioSampleBuffer buffer(channelData, numChannels, numSamples);
  processor_->processBlock(buffer, midi)`).
- `SSPExApi.h` (`SSPExtendedApi`) -- an **extended parameter model** layered on the raw
  SDK: `numberOfParameters()`, `parameterDesc(idx, ...)`, `parameterValue(idx)`, with
  `buttonPressed`/`encoderTurned` translated to parameter updates and paged across the
  four encoders. This is the cleanest reference for gen-dsp's param->encoder mapping.
- Editor base (`SSPApiEditor.{h,cpp}`) for the display.

**Two implementation paths for gen-dsp:**

1. **Native (recommended)** -- generate a module that implements
   `Percussa::SSP::PluginInterface` directly against the official `Percussa.h`, bridging
   `process()` to genlib with no JUCE. Matches gen-dsp's other backends (minimal wrapper,
   no heavy framework dependency) and the official `examples/api/test`.
2. **JUCE-based** -- reuse TheTechnobear's `SSPApiProcessor`/`SSPExtendedApi`. More
   machinery (JUCE + madronalib submodules) but a ready-made parameter/encoder/editor
   layer. Heavier; only worth it if the display/param UX is a priority.

Either way, TheTechnobear's `SSPExtendedApi` parameter abstraction is the model to copy
for mapping gen~ params onto the encoders.

## Implementation plan

A concrete, phased plan to add an `"ssp"` backend, native (no JUCE), following the
existing gen-dsp backend anatomy (header isolation + a per-platform bridge over the
shared `wrapper_*` C interface, as in the Web Audio backend).

### Files to add

- `src/gen_dsp/platforms/ssp.py` -- `SspPlatform(Platform)`; register `"ssp"` in
  `platforms/__init__.py` `PLATFORM_REGISTRY`. Implements `generate_project`, `build`,
  `clean`, `find_output`, `get_build_instructions`, `extension` (`.so`), `description`,
  `build_system` (`"CMake (clang cross)"`), and `list_boards()` -> `[]`.
- `src/gen_dsp/templates/ssp/`:
  - `_ext_ssp.cpp` (static) -- genlib side: includes genlib + the exported gen~ code,
    defines the `wrapper_*` functions in `WRAPPER_NAMESPACE`. Mirrors
    `_ext_webaudio.cpp` (drop the buffer section unless/until SSP buffers are wired).
  - `gen_ext_common_ssp.h` (static) -- the `WRAPPER_NAMESPACE` macros.
  - `_ext_ssp.h` -- generated from the shared `gen_ext_h.template` (opaque `GenState*`
    C interface). Reused unchanged.
  - `ssp_plugin.cpp.template` -- **the only genuinely new code**: implements
    `Percussa::SSP::PluginInterface`, `createDescriptor`/`createInstance`/`getApiVersion`,
    the `process()` bridge, the param->encoder layer, and `getState`/`setState`.
  - `CMakeLists.txt.template` -- builds the `.so`; pulls in the generated toolchain.
  - `ssp_toolchain.cmake.template` -- emitted per project (see below).
- `src/gen_dsp/core/doctor.py` -- add an `ssp` entry checking for `clang`/`clang++` and
  the Buildroot sysroot.

### Build & toolchain strategy

- **Fetch the SDK like Daisy/Circle fetch theirs**, but as a tarball, not a clone: a
  helper (cf. `daisy._resolve_libdaisy_dir`) downloads
  `arm-rockchip-linux-gnueabihf_sdk-buildroot.tar.gz` into the shared cache
  (`core/cache.get_cache_dir()`), extracts once, and returns the root. A `BUILDROOT`
  env var overrides to an existing install. Pin the URL + a version/sha constant.
- **Emit our own toolchain file** rather than depend on Percussa's `xcSSP.cmake`:
  `ssp_toolchain.cmake` sets `CMAKE_SYSTEM_NAME Linux`, `SYSTEM_PROCESSOR armv7l`,
  `CMAKE_C/CXX_COMPILER` = host `clang/clang++` with
  `--target=arm-linux-gnueabihf`, `CMAKE_SYSROOT` = cached Buildroot sysroot, the
  libstdc++ 8.4.0 include paths, `-mcpu=cortex-a17 -mfloat-abi=hard -mfpu=neon-vfpv4`,
  and the sysroot/GCCROOT link flags. (Reproduces `xcSSP.cmake` from values we now know.)
- `build()` resolves the SDK, writes the toolchain into the project, then runs
  `cmake -DCMAKE_TOOLCHAIN_FILE=ssp_toolchain.cmake -B build` + `cmake --build build`.
  This makes `ssp` the first **CMake cross-compile** backend (existing cross-compile
  backends -- Daisy, Circle -- are Make-based).

### `process()` bridge

The SSP gives `process(float** channelData, int numChannels, int numSamples)`. genlib's
`perform(state, t_sample** ins, long nins, t_sample** outs, long nouts, long n)` takes the
same planar `float**`. Bridge: pass `channelData[0 .. num_inputs)` as ins and
`channelData[num_inputs .. num_inputs+num_outputs)` as outs (the **inputs-then-outputs**
assumption). Guard with a one-time check of `numChannels` vs `num_inputs+num_outputs`;
keep an in-place fallback (`outs` overlap `ins`) behind a clearly marked switch, to flip
after the on-device confirmation. genlib already tolerates `t_sample = float`.

### Parameter -> encoder layer (model: `SSPExtendedApi`)

- The manifest's `ParamInfo[]` (name/min/max/default) drives a fixed param table.
- Four encoders address a **page** of four params; `encoderTurned(n, delta)` updates param
  `page*4 + n` by `delta * (max-min) * step`, clamped; `encoderPressed` resets to default.
- Soft keys / navigation buttons change page; the editor's `renderToImage` draws the
  current page's four `name: value` rows (BGRA). The editor can be a stub initially.
- `getState`/`setState` serialize the param-value array (+ current page) to a blob for
  presets. (gen~ MIDI-to-CV is **N/A** for SSP -- no MIDI in the callback; treat all I/O
  as audio/CV and disable the MIDI path for this backend.)

### Descriptor

`createDescriptor()` fills `name`/`manufacturerName`/`version` from the project config,
a deterministic `uid` (e.g. hashed from the name), and
`inputChannelNames`/`outputChannelNames` sized from `manifest.num_inputs`/`num_outputs`
(generic `"In N"`/`"Out N"`, or gen~ I/O names when present).

### Phasing

1. **Scaffold + generation** (verifiable here, in CI): platform + templates + registry;
   `generate_project` emits all files. Always-run generation tests (cf. the webaudio
   tests): files present, descriptor channel counts match the manifest, toolchain carries
   the cortex-a17/clang flags, param-table code present. No cross-build needed.
2. **Toolchain + build** (verified on the user's device): SDK auto-fetch, toolchain emit,
   `build()` -> `.so`; `doctor` entry. Build/integration tests gated on `clang` +
   `BUILDROOT` (skipped in CI, like the `emcc` gate).
3. **Param/encoder + display**: the `SSPExtendedApi`-style layer, paging, `getState`/
   `setState`, `renderToImage` param readout.
4. **Polish**: confirm the channel split on device, presets, docs + an example, and a
   backend page under `docs/backends/`.

### Decisions / risks

- **Licensing.** `ssp_plugin.cpp` includes the AGPL-3.0 `Percussa.h`, so the *generated
  SSP project* is AGPL-3.0 (genlib + user DSP remain separate TUs). gen-dsp's generator
  code stays MIT (it only emits text). Mark the SSP template/bridge files and generated
  project with an AGPL notice and document it. Not a code blocker.
- **On-device confirmations** before calling it done: the exact in/out channel split;
  whether the native `api/` path needs the VST3 SDK (the `vst/` examples do); the module
  install path on the device.
- **What can be validated in CI vs. on device.** Generation (phase 1) runs everywhere;
  the cross-build + audio (phases 2-4) require the Cortex-A17 sysroot + clang target and
  the hardware, so they live behind a tool gate and are validated by the device owner.

## Closest analog

- **Code shape:** CLAP / LV2 (a `.so` plugin: descriptor + instance factory,
  `prepare`/`process`).
- **Build & control:** Circle / Daisy / VCV Rack (cross-compile against an externally
  installed SDK; map params onto fixed hardware controls).

## Open questions (confirm on device)

- The input/output split within `channelData`: separate `numIn` + `numOut` pointers, or
  an in-place `max(numIn, numOut)` JUCE buffer? (Wrapping is confirmed in-place; only the
  bus interpretation remains.)
- The SSP's fixed I/O width / maximum channel count.
- Module install path on the device (SD card folder?).
- Whether the native `api/` build path needs the VST3 SDK or only the `vst/` wrappers do.
- AGPL-3.0 implications for distributing generated modules.
