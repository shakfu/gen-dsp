# Double-precision builds

Status as of 2026-10-13. Covers double-precision Pd (pd64) and whether graph code should get a `double` build.

## Summary

| Source | pd64 today | Mechanism |
|-|-|-|
| gen~ export | builds: `make floatsize=64` | genlib compiled as double; external named `<name>~.<os>-<cpu>-64.so` |
| graph (gen-dsp `-p pd`) | rejected at compile time | `static_assert` in `gen_ext_pd.cpp` |
| graph (xtgen Pd) | rejected with `#error` | xtgen template |

Not yet verified: loading a pd64 build in a pd64 binary. No pd64 binary is installed here, so the tests check compilation, the extension name, and the mangled `perform` signature.

## gen~ exports

genlib's sample type is `double` unless `GENLIB_USE_FLOAT32` is defined. The export-path glue (`gen_dsp.cpp`) passes Pd's `t_sample**` straight to genlib's `perform`. So a pd64 build only needs genlib built as double, which means omitting the flag. `Makefile.template` now selects it:

```make
floatsize ?= 32
ifeq ($(floatsize),64)
  cflags += -DPD_FLOATSIZE=64
  override extension = $(pd64.os)-$(pd64.cpu)-64.so
else
  cflags += -DGENLIB_USE_FLOAT32
endif
```

**Extension.** Pd 0.57's loader (`s_loader.c`, `sys_get_dllextensions`; `s_inter.c`, `sys_deken_specifier`) builds names as `.<os>-<cpu>-<8*sizeof(t_float)>.so`. It adds the legacy `.pd_darwin` / `.d_fat` / `.pd_linux` names only `#if PD_FLOATSIZE == 32`. The vendored pd-lib-builder predates `floatsize`, and it sets `extension` with a plain assignment, hence `override`.

**Bugs found on the way.** Both affect 32-bit Pd on 64-bit hosts too:

- `pd_buffer.h`'s fallback array was 8 `float`s, but the accessors index through `t_word`, which is 8 bytes on 64-bit hosts. Reading the fallback ran 32 bytes past the array. It is now `t_word[8]`.
- `PdBuffer::blend` (used by `splat`) wrote `mData[offset]` with a `t_sample` stride instead of through `t_word`. With 32-bit floats on a 64-bit host, that is element `offset/2`.

**Also fixed.** `GENLIB_USE_FLOAT32` was set only in `forDarwin` and `forLinux`, so a Windows build compiled genlib as double against single-precision Pd. It is now set for every OS.

**Tests:** `tests/test_pd.py::TestPdDoublePrecision`.

## Graph code

`compile_graph` emits `float` throughout, so graph code is single precision. Hosts in double precision convert at the boundary:

- **Max:** the graph adapter copies `double**` into `float` arrays (`adapter.py`, `_PLATFORM_INFO` path for `max`).
- **Csound:** `MYFLT` is double; the README lists the conversion cost.
- **pd64:** rejected for now.

### Option 1: convert at the boundary (recommended now)

In the Pd glue, copy each `t_sample*` into float scratch, call `<name>_perform`, and copy back. The cost is two copies per channel per block.

- Allocate scratch in the `dsp` method, sized to the block, and free it in `free`. Do not use stack arrays.
- The Max adapter declares `float in{i}[n];` (`adapter.py:116`). In C++ that is a variable-length array, a GCC/clang extension MSVC rejects, and its stack use grows with block size. Fix it the same way.
- Limit: the DSP stays 32-bit. pd64 users gain nothing for the reasons they run pd64, e.g. phase accumulators over long durations, or indexing tables beyond 2^24 samples.

For xtgen this replaces the `#error`. gen-dsp's graph Pd glue would change the same way, replacing the `static_assert`.

### Option 2: `compile_graph(..., sample="double")` (defer)

Parameterise the emitter's sample type. Measured in `src/gen_dsp/graph/compile/`:

- about 280 `float` occurrences;
- about 220 `f`-suffixed literals (via `_float_lit` and inline);
- about 40 suffixed math calls (`sinf`, `floorf`, `fmodf`, ...).

The change is mechanical: a type token, a literal formatter per precision, and a table mapping each math function to its `float`/`double` form.

The hard part is reference semantics. `simulate.py` computes in `float32`, so a double build has no exact reference. The differential tests would need tolerances or a float64 simulation mode.

What it buys: no boundary conversion for Max, Csound and pd64, and graph code closer to gen~, which runs in double precision in Max.

**Decide on evidence.** Build it when a concrete patch shows float DSP is audibly or measurably wrong, for example drift in a long `phasor` or table indexing past 2^24 samples. Until then it means two precisions to emit, test and maintain.
