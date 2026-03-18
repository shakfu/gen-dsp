# Csound

Generates Csound opcode plugins via the `csdl.h` C API. The opcode is discovered by Csound at startup from the `OPCODE6DIR64` directory.

**OS support:** macOS, Linux

## Prerequisites

- Python >= 3.10
- C++ compiler
- make
- Csound headers (`csdl.h`) -- from the CsoundLib64 framework (macOS), or the `csound` / `libcsound-dev` package (Linux)

## Quick Start

```bash
# From a gen~ export
gen-dsp ./my_export -n myeffect -p csound
cd myeffect_csound && make all

# Verify Csound discovers the opcode
OPCODE6DIR64=. csound --list-opcodes | grep myeffect
```

## Usage in a .csd File

Audio inputs map to `a`-rate args, parameters to `k`-rate args, audio outputs to `a`-rate outputs:

```csound
; Effect (2 audio in, 2 audio out, 8 k-rate params)
aout1, aout2 gigaverb ain1, ain2, kroomsize, krevtime, kdamping, ...

; Generator (0 audio in, 1 audio out, 5 k-rate params)
aout fm_synth kgate, kfreq, kmod_ratio, kmod_index, kamp
```

## How It Works

1. `gen_ext_csound.cpp` implements the OENTRY registration, init callback (creates gen~ state), and perf callback (per-ksmps-block processing)
2. `_ext_csound.cpp` wraps genlib (header isolation pattern)
3. OENTRY type strings are auto-generated from the gen~ manifest I/O counts (e.g. `"aa"` outputs, `"aakkkkkkkk"` inputs for 2in/2out/8params)
4. Handles float (gen~/GENLIB_USE_FLOAT32) to MYFLT (double, Csound default) conversion
5. Supports sample-accurate timing via `ksmps_offset` / `ksmps_no_end`
6. The plugin registers via `LINKAGE_BUILTIN` which exports `csound_opcode_init()`

## Header Discovery

The Makefile searches for Csound headers in this order:

1. `CSOUND_INCLUDE` environment variable (explicit override)
2. `/Library/Frameworks/CsoundLib64.framework/Headers` (macOS framework)
3. `$(brew --prefix)/include/csound` (Homebrew)
4. `/usr/local/include/csound`
5. `/usr/include/csound`

## Platform Key

```text
"csound"
```
