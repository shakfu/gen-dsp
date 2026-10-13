# nice-plug (Rust)

Generates a Cargo crate that builds CLAP and VST3 plugins with [nice-plug](https://codeberg.org/RustAudio/nice-plug), a Rust plugin framework (ISC license, a community fork of NIH-plug). Use it when you want Rust around the gen~ core:

- an egui editor (`--features gui`, or your own);

- Rust-side MIDI or DSP before and after the gen~ code;

- a Cargo project to hand to Rust users.

To build plain CLAP or VST3 from C++ with no Rust, use the [CLAP](clap.md) or [VST3](vst3.md) backend.

**OS support:** macOS verified; Linux and Windows untested (nice-plug upstream tests both).

## Prerequisites

- Rust toolchain (`cargo`); egui 0.36 needs rustc >= 1.95 for `--features gui`

- C/C++ compiler (clang, gcc, or MSVC), used by the `cc` crate

- Network access on first build (crates.io)

## Quick Start

```bash
gen-dsp ./my_export -n myeffect -p nice --no-build
cd build/myeffect_nice

cargo xtask bundle myeffect --release                 # target/bundled/myeffect.{clap,vst3}
cargo xtask bundle myeffect --release --features gui  # same, with a slider per parameter
cargo test                                            # checks the Rust/C++ boundary
```

`gen-dsp build build/myeffect_nice -p nice` runs the first bundle command.

## Project Layout

| File | Role | Regenerated |
|------|------|-------------|
| `src/lib.rs` | `Plugin` impl, `GenParams`, CLAP/VST3 metadata, tests | yes |
| `src/engine.rs` | `Engine`: safe Rust API over the C ABI | yes |
| `src/editor.rs` | generic egui editor (`gui` feature) | yes |
| `build.rs` | compiles the C++ with the `cc` crate | yes |
| `gen_ext_nice.cpp` | C ABI (`gendsp_*`), polyphony, MIDI-to-param mapping | yes |
| `_ext_nice.cpp` | genlib side; the only file that includes genlib | yes |
| `xtask/`, `.cargo/config.toml` | `cargo xtask bundle` | yes |

Regeneration overwrites every file. Keep your own code in new modules, or put the project under version control first.

## How It Works

The [header isolation](../architecture.md) pattern stays in place. Rust sees one opaque engine through `extern "C"` functions in `gen_ext_nice.cpp`, which has no genlib headers. `_ext_nice.cpp` has the genlib headers and no host headers.

- **Parameters.** Each gen~ parameter becomes a `FloatParam` with a linear range. Its `#[id]` is the sanitized gen~ name, so automation survives regeneration as long as the gen~ name does. `process()` pushes changed values to the engine once per block. `SAMPLE_ACCURATE_AUTOMATION` makes nice-plug split blocks at automation points, so per-block reads are sample accurate. nice-plug smoothing is off; gen~ patches smooth internally.

- **Display precision.** Values display with about 5 significant digits. Full f32 precision does not survive the normalize/denormalize round trip, and hosts (and clap-validator) reject a display string that changes.

- **Audio I/O.** nice-plug's main buffer carries as many channels as the main output. When the gen~ code has more inputs than outputs (e.g. 3 in / 2 out), the extra inputs arrive on one auxiliary input port. Inputs are copied to scratch buffers before `perform`, because nice-plug processes in place.

- **MIDI.** The [MIDI mapping](../midi-cv.md) and `--voices` work as in the CLAP backend. `MIDI_INPUT` is `Basic` when a mapping is active. Note events split the block at their sample offset. A wildcard note-off releases every note.

- **Tail.** `process()` returns `KeepAlive`, since gen~ reverbs and feedback delays can ring indefinitely.

- **IDs.** The CLAP ID is `com.gen-dsp.<name>`. The VST3 class ID is the first 16 hex digits of an MD5 of the name, so it is stable across regenerations.

## Extending in Rust

Use `engine::Engine` directly in the plugin, or from another crate (the crate type includes `lib`):

```rust
let mut engine = Engine::new(48000.0, 512).unwrap();
engine.set_param(0, 0.5);
engine.note_on(60, 1.0);
engine.process(&[&input[..]], &mut [&mut left[..], &mut right[..]]);
```

`Engine::process` checks slice lengths and channel counts, and panics on a mismatch. It does not allocate.

## Tests

The generated crate's `cargo test` checks:

- that the Rust constants match the I/O and parameter counts the C++ was compiled with;

- that defaults reach the engine;

- that rendering produces finite samples.

gen-dsp's own `tests/test_nice.py` builds four projects (effect, 3-in/2-out, buffers, 4-voice graph synth) and the `gui` feature. It runs clap-validator on each CLAP bundle and pluginval (strictness 10) on each VST3 bundle. Those tests share `build/.cargo_target`, so nice-plug compiles once.

## Limitations

- clap-validator's `param-conversions` test divides by zero on plugins with no parameters. This is a validator bug; `tests/helpers.py` already tolerates it.

- For gen~ code with more inputs than outputs, pluginval warns that the auxiliary input bus cannot be disabled. It does not fail.
