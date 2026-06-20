# --inputs-as-params

## The problem

In gen~, *all* external inputs are signal-rate `in` objects -- there's no distinction between audio and control data. A patch like fm_bells has `in 1` (carrier/pitch) and `in 2` (c/m ratio), but these are control values, not audio streams. When gen-dsp sees 2 signal inputs, it classifies the plugin as an **effect** (audio passthrough), when it should be an **instrument/generator** (no audio input, parameters drive synthesis).

## What it does

`--inputs-as-params` intercepts specified gen~ signal inputs and exposes them as plugin parameters instead. At the C level, the bridge code fills internal input buffers with the parameter values before calling gen~'s `perform()` -- gen~ sees the same signal inputs it expects, but the host sees knobs/sliders.

## Usage

Two forms:

```bash
# Remap ALL signal inputs to parameters
gen-dsp examples/gen_export/fm_bells/fm_bells -p clap --inputs-as-params

# Remap only specific inputs by name (from gen_kernel_innames[])
gen-dsp examples/gen_export/fm_bells/fm_bells -p clap --inputs-as-params carrier "c/m ratio"
```

Input names are taken from `gen_kernel_innames[]` in the exported `.cpp`. Use `gen-dsp detect <export>` to see what names are available.

## Concrete effect on fm_bells

| | Before | After (`--inputs-as-params`) |
|---|---|---|
| Signal inputs | 2 (carrier, c/m ratio) | 0 |
| Parameters | 3 (depth, t60, smooth) | 5 (depth, t60, smooth, carrier, c_m_ratio) |
| Plugin type | Effect (`aufx`/`audio_effect`) | Generator/Instrument (`augn`/`instrument`) |

## Implementation

1. **Parser** extracts input names from `gen_kernel_innames[]` in the exported `.cpp`
2. **`apply_inputs_as_params()`** creates a modified Manifest: decrements `num_inputs`, appends synthetic `ParamInfo` entries, records the mapping in `remapped_inputs`
3. **`build_remap_defines()`** emits compile defines like `REMAP_INPUT_COUNT=2`, `REMAP_INPUT_0_GEN_IDX=0`, `REMAP_INPUT_0_PARAM_IDX=3`
4. **`gen_remap_inputs.h`** (shared header included by all bridge templates) provides `_remap_perform()` which builds the full input array, fills remapped slots with parameter values, and calls gen~'s real `perform()`
5. Each bridge template's `wrapper_perform()`, `wrapper_num_inputs()`, `wrapper_num_params()`, and param accessors are guarded with `#if defined(REMAP_INPUT_COUNT)` to switch between normal and remapped behavior

The key design constraint: gen~'s compiled code is untouched. The remapping happens entirely in the bridge layer between the host API and gen~'s `perform()`.

## Supported platforms

All 15 platforms support `--inputs-as-params`. CMake-based platforms (CLAP, VST3, AU, AUv3, LV2, SC, Max) pass remap defines via `target_compile_definitions()`. Make-based platforms (ChucK, VCV Rack, PD, Daisy, Circle, Web Audio, Standalone, Csound) pass them via compiler flags (`FLAGS`, `CFLAGS`/`CPPFLAGS`, or `cflags` depending on platform).
