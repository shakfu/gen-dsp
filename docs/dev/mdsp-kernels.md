# mdsp kernels in graphs

Status: proposal. Nothing here is implemented in gen-dsp or mdsp.

[mdsp](https://github.com/shakfu/mdsp) kernels are Mojo structs that implement `Processor` or `WideProcessor` (`src/mdsp/_mojo/dsp/processor.mojo`). This note records what a prototype established, then proposes an `MdspKernel` node modelled on `CignalKernel`.

## Findings

Tested on Linux x86_64 with Mojo 1.2.0 and mdsp 0.2.0 (`112db96`), 2026-11-28.

1. **A C ABI shim per unit is enough.** Each unit gets `<k>_size`, `<k>_init(addr, sr[, channels])`, `<k>_deinit`, `<k>_set(addr, i, v)`, `<k>_reset`, `<k>_process(addr, ports, dst, n[, channels])` and, for mono units, `<k>_tick`. `Player` adds `player_load(addr, src, frames)`. The host owns the state memory, and Mojo constructs into it with `Pointer.unsafe_write` and destroys it with `unsafe_take_pointee`. The kernels themselves are unchanged.
2. **The shims build as plain objects and need no Mojo runtime.** `mojo build --emit object` works for all 21 units. Across all 21, the only symbols needed beyond libc and libm are:

   | Symbol | Needed by |
   |-|-|
   | `KGEN_CompilerRT_AlignedAlloc` | chorus, compressor, delay, reverb, shift |
   | `KGEN_CompilerRT_AlignedFree` | the same, plus player |
   | `KGEN_CompilerRT_fprintf` | reverb |

   A 3-function C++ stub (`posix_memalign`, `free`, `vfprintf`) satisfies them. All 21 objects plus the stub link into one `-shared -fPIC` library with `--no-undefined`. That library exports 146 functions, has no duplicate globals, and loads with `dlopen`.
3. **The shims match mdsp's Python path bit for bit.** Each case ran 3 x 4096 frames, changed one param after the first block, and drove 4 cases through a modulation input. All 21 units match `mdsp._core` exactly, provided the shims are built with mdsp's own flags (`--fp-mode contract=off`, baseline `--target-cpu`). With host defaults they differ by up to 3e-7, from FMA contraction. `Player` was tested with looping and with backward playback across the start of the source.
4. **Output does not depend on block size.** A single 2048-frame call, 64-frame chunks and 1-frame calls give bit-identical output for 21/21 units. This holds with modulation inputs and a `set` placed on a chunk boundary. gen-dsp's cignal staging (`graph/compile/staging.py`) relies on exactly this property.
5. **Per-frame calls cost 1.7-6x more than 64-frame calls.** The ratio is what a scheduler needs, and it stayed the same across machine states. Absolute times did not: the same binary ran 2-3x slower on the first runs than later on. Measured with mdsp's `scripts/bench_c_abi.py`, pinned to one core, 3 runs:

   | Unit | tick / process(64) | tick (ns/frame) | process(64) (ns/frame) |
   |-|-|-|-|
   | gain | 6.1-6.3x | 2.0 | 0.31-0.32 |
   | svf | 2.3-2.4x | 8.7 | 3.6-3.7 |
   | reverb | 1.7x | 29 | 17 |

   Setup: Ryzen 9 PRO 6950H, `powersave` governor, boost on, median clock 4.54 GHz. Kernels built with mdsp's flags (`contract=off`, `x86-64-v2`); harness built with C++ `-O2`. Building for this specific CPU instead of `x86-64-v2` makes svf `tick` about 20% faster.

## Proposal

### mdsp exports, gen-dsp reads

mdsp would ship three artifacts per target triple:

- `libmdsp_kernels.a`, holding the shims.
- `mdsp_kernels.h`, the C declarations.
- `mdsp_kernels.json`, a manifest listing each unit's params (name, index, lo, hi, default, enum labels), input ports, channel mode and the Mojo version it was built with.

gen-dsp reads these files and does not import mdsp, which mirrors `cignal.py`. The stub `.cpp` lives in gen-dsp's templates, so the private `KGEN_*` dependency sits in one file next to a version check.

The alternative is for gen-dsp to generate the shims and run `mojo` during project generation. That puts a Mojo toolchain dependency on gen-dsp. It also duplicates the ABI, which only mdsp's tests can keep correct.

### Graph model

- `MdspKernel(id, spec, inputs, mods, params)` plus `MdspOut` for wide units, alongside `CignalKernel`/`CignalOut`.
- **Modulation ports.** A param bound to a signal goes to the kernel's modulation port. A param bound to a block-constant value goes through `set`. cignal can only call `set` per frame, so this gives mdsp kernels the faster path.
- **Enum params** (`mode`, `curve`, `shape`, `color`) resolve to indices at parse time, using the manifest's labels.
- **Construction-only params** are `Delay.max_delay` and `Chorus.voices`. `Delay.set(MAX_DELAY)` reallocates the line (`delay.mojo:63`), so these params must not reach the host as automatable params.
- **Staging, validation and visualisation** reuse the cignal code paths, generalised over a shared kernel protocol rather than copied.

DSL sketch:

```gdsp
f = mdsp "Svf"(x, mode=peaking, cutoff=sweep, q=4)
```

### Constraints

- **Private ABI.** The `KGEN_CompilerRT_*` names are undocumented. Their signatures were read from call sites and are tested in mdsp, but a Mojo release can change them. Pin the Mojo minor version in the manifest. Fail project generation on a mismatch, and fail CI if `nm -u` finds a new symbol.
- **Bounds checks trap.** `Reverb` indexes `List`s with bounds checks. A failed check prints to stdout through `KGEN_CompilerRT_fprintf`, then executes an illegal instruction, which crashes the host. No other kernel has these checks.
- **One archive per target.** macOS AU/VST3 universal binaries need both arm64 and x86_64 archives, combined with `lipo`. Windows, Web Audio, Circle, Daisy and SSP have no Mojo target and stay unsupported.
- **CPU target.** Archives must be built with a portable `--target-cpu`, not `host`.
- **Simulation.** `simulate()` could call `mdsp._core` directly, since finding 3 shows the two paths agree. cignal kernels cannot be simulated at all.

## Open questions

- Should mdsp own the shim and manifest? Doing so commits mdsp to a stable C ABI.
- Should `MdspKernel` and `CignalKernel` share one `ExternalKernel` node with a per-backend spec, or stay as separate node types?
- Which units matter for gen-dsp? It already has `SVF`, `Biquad`, `OnePole`, `ADSR` and the oscillators. The new units would be `Reverb`, `Compressor`, `Shift`, `Chorus`, `Pan` and `Width`.

Findings 2-4 are tested in mdsp's `tests/test_c_abi.py`. Finding 5 comes from `scripts/bench_c_abi.py`.
