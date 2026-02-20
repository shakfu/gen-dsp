# MIDI-to-CV for gen-dsp Instruments

## Problem

gen~ is a signal-rate DSP environment with no concept of MIDI events. In Max/MSP, MIDI handling happens *outside* gen~ -- objects like `notein`, `poly~`, and `mc.gen~` convert MIDI to control signals before feeding them into gen~. gen-dsp currently inherits this limitation: plugins with 0 audio inputs are declared as "instruments" in the host but have no way to receive note events.

## Current State

Every platform wrapper feeds data into gen~ through exactly two channels:

1. **Audio inputs** (`float**` passed to `perform()`) -- sample-accurate, but defined at export time by the gen~ patch topology.
2. **Parameters** (`wrapper_set_param()`) -- scalar values applied once per block. No sample-accurate scheduling in any current backend.

There is no MIDI input, no note event handling, and no voice allocation anywhere in the codebase.

## Design Space

### How to get note data into gen~

There are three realistic approaches. They are not mutually exclusive.

#### Option A: Map MIDI to gen~ parameters

On note-on, set `freq`, `gate`, and `vel` parameters via `wrapper_set_param()`. The gen~ patch must expose parameters with these names (or configurable names).

**Pros:**
- Minimal wrapper complexity -- just call `wrapper_set_param()` with 2-3 extra values
- Works with existing gen~ patches that already have `freq`/`gate` params
- No change to gen~ state API or `perform()` call signature
- Parameter values persist between blocks (gate stays high until note-off)

**Cons:**
- Control-rate only -- at most one note transition per audio block (e.g., 512 samples at 48kHz = ~10.7ms granularity)
- Fast note sequences may be lost or merged (two note-ons in one block = only the last one is seen)
- Requires convention or configuration for which params are MIDI-mapped
- Polyphony is awkward -- must duplicate entire gen~ state for each voice

**Verdict:** Good enough for most synth patches. The block-rate limitation is the same as Max/MSP's `param` objects inside gen~, so users already design around it.

#### Option B: Inject note data as virtual audio inputs

Synthesize sample-accurate gate/freq/vel signals and prepend them to the `float** ins` array passed to `perform()`. The gen~ patch declares explicit signal inputs for these (e.g., `in 1` = gate, `in 2` = freq).

**Pros:**
- Sample-accurate note timing -- gate transitions land on the exact sample
- Natural fit for gen~ patches designed with signal-rate inputs
- No new API -- just adds channels to the existing `perform()` call

**Cons:**
- Requires the gen~ patch to be designed with specific input channels for MIDI data (not the typical instrument pattern)
- Breaks the "0 inputs = instrument" heuristic (patch now has 2-3 inputs for note data)
- Buffer allocation and management overhead for synthesized signals
- Confusing UX: the plugin is an "instrument" but gen~ sees audio inputs

**Verdict:** Elegant for sample-accurate synthesis, but the UX is confusing. Users would need to design gen~ patches differently from how they'd design them in Max/MSP.

#### Option C: Extend the gen~ wrapper API with an event interface

Add a new function to `_ext_*.h`:

```c
void wrapper_note_on(GenState* state, int note, float velocity);
void wrapper_note_off(GenState* state, int note, float velocity);
```

The `_ext_*.cpp` implementation would translate these into `wrapper_set_param()` calls for the mapped parameters.

**Pros:**
- Clean separation of concerns -- host wrapper handles MIDI protocol, ext layer handles mapping
- Could support sample-accurate event scheduling by queuing events and applying them during `perform()`
- Single implementation shared across all platforms

**Cons:**
- More API surface in the ext layer
- Still fundamentally limited to what gen~ can express (no native event handling)
- Sample-accurate scheduling would require splitting `perform()` into sub-blocks around event boundaries, adding complexity

**Verdict:** Over-engineered for the current use case. Option A with a thin event queue (for sub-block scheduling if needed later) gives 90% of the benefit.

### Recommended approach: Option A with auto-detection and CLI overrides

For 0-input (generator) plugins, gen-dsp auto-detects MIDI parameter mappings by scanning gen~ param names:

| Role | Auto-detected names | CLI override |
|---|---|---|
| Frequency | `freq`, `frequency`, `pitch` | `--midi-freq <name>` |
| Gate | `gate` | `--midi-gate <name>` |
| Velocity | `vel`, `velocity` | `--midi-vel <name>` |

**Detection rules:**

1. Only triggers for 0-input plugins (generators). Effects are never MIDI-mapped.
2. `gate` is required for auto-detection to activate. A generator with `freq` but no `gate` is probably a test-tone oscillator, not a keyboard instrument.
3. If `gate` is found, `freq`/`frequency`/`pitch` and `vel`/`velocity` are mapped if present. Missing frequency or velocity is allowed (gate-only instruments exist).
4. If auto-detection finds nothing, no MIDI code is generated. The plugin remains a parameter-only generator (current behavior).

**CLI controls:**

```bash
# Auto-detection (default for 0-input plugins) -- no flags needed
gen-dsp init export/ --platform vst3 --name mysynth

# Override auto-detected names (e.g. param is called "note" not "freq")
gen-dsp init export/ --platform vst3 --name mysynth \
    --midi-freq note --midi-gate trig

# Force MIDI off even if gate/freq params are present
gen-dsp init export/ --platform vst3 --name mysynth --no-midi
```

The explicit `--midi-freq` / `--midi-gate` / `--midi-vel` flags serve two purposes: override auto-detected names, or force MIDI mapping for params with non-standard names (even when auto-detection wouldn't find them). Any explicit `--midi-*` flag implies MIDI is enabled regardless of auto-detection.

The wrapper template receives the param indices at code generation time and wires them in the process loop:

```
MIDI note-on  -> wrapper_set_param(state, MIDI_FREQ_IDX, mtof(note))
                 wrapper_set_param(state, MIDI_GATE_IDX, 1.0)
                 wrapper_set_param(state, MIDI_VEL_IDX, velocity / 127.0)
MIDI note-off -> wrapper_set_param(state, MIDI_GATE_IDX, 0.0)
```

---

## Monophonic Implementation

### Scope

Single-voice MIDI instrument. Last-note priority (new note-on steals immediately). No voice allocation.

### Per-platform changes

**VST3:**
- Add event bus: `addEventInput(STR16("MIDI In"), 1)` in `initialize()`
- In `process()`, iterate `data.inputEvents->getEvent()`, handle `Event::kNoteOnEvent` and `Event::kNoteOffEvent`
- Convert `event.noteOn.pitch` (MIDI note 0-127) to frequency, `event.noteOn.velocity` (float 0-1) to velocity
- Call `wrapper_set_param()` for the mapped indices
- Declare `kInstrumentSynth` subcategory (already done for 0-input plugins)

**CLAP:**
- Add note port via `CLAP_EXT_NOTE_PORTS` extension
- In the event loop inside `clap_gen_process()`, handle `CLAP_EVENT_NOTE_ON` / `CLAP_EVENT_NOTE_OFF`
- CLAP note events have `key` (MIDI note) and `velocity` (float 0-1)
- Declare `CLAP_PLUGIN_FEATURE_INSTRUMENT` (already done)

**AU:**
- Change type from `augn` (generator) to `aumu` (music device) for MIDI-capable instruments
- Implement `kMusicDeviceMIDIEventSelect` handler to receive raw MIDI bytes
- Parse status byte 0x90 (note-on) / 0x80 (note-off), extract note and velocity
- `augn` stays available for generators that don't want MIDI

**LV2:**
- Add `atom:AtomPort` with `atom:bufferType atom:Sequence` and `atom:supports midi:MidiEvent`
- In `run()`, iterate the atom sequence, parse MIDI events from `LV2_MIDI_MSG_NOTE_ON` / `LV2_MIDI_MSG_NOTE_OFF`
- Declare `lv2:InstrumentPlugin` class

**SC / ChucK / VCV Rack / Daisy:**
- SC: MIDI routing handled in the SC language layer, not the UGen. No change needed.
- ChucK: MIDI handled by ChucK's `MidiIn` class. No change to the chugin.
- VCV Rack: V/Oct and gate are CV signals, not MIDI. Could add a "MIDI-to-CV" mode, but VCV's own MIDI-CV module is the standard approach. Low priority.
- Daisy: Could receive MIDI via UART/USB. Worth supporting eventually.

### Pitch conversion

`mtof(note)` = 440 * 2^((note - 69) / 12). Implemented inline in the wrapper, no dependency needed.

Alternative: pass raw MIDI note number instead of frequency. Let the user choose via `--midi-freq-unit hz|midi` (default: `hz`). Some gen~ patches expect MIDI note numbers and do their own conversion.

### Template changes

The gen~ param indices for freq/gate/vel are compile-time constants injected via `target_compile_definitions()` (same pattern as `VST3_NUM_INPUTS` etc.). Only the detected/overridden params are defined:

```cmake
# All three detected (typical synth patch with freq, gate, velocity params)
target_compile_definitions(${PROJECT_NAME} PRIVATE
    MIDI_ENABLED=1
    MIDI_GATE_IDX=5
    MIDI_FREQ_IDX=2
    MIDI_VEL_IDX=3
    MIDI_FREQ_UNIT_HZ=1    # 0 = raw MIDI note number
)

# Gate-only (no freq or vel param found/mapped)
target_compile_definitions(${PROJECT_NAME} PRIVATE
    MIDI_ENABLED=1
    MIDI_GATE_IDX=0
)

# No MIDI (effect, or --no-midi, or no gate param found)
# No MIDI_* defines emitted
```

The process loop checks `#ifdef MIDI_ENABLED` to conditionally compile the MIDI handling code. Individual `#ifdef MIDI_FREQ_IDX` / `#ifdef MIDI_VEL_IDX` guards handle partial mappings (gate-only instruments). If `MIDI_ENABLED` is not defined, no MIDI code is generated (zero overhead for effects).

---

## Polyphony

### Voice architecture

Polyphony requires N independent gen~ states processing in parallel, with a voice allocator distributing notes across them.

```
                    +-- GenState[0] --+
MIDI note-on  -->   |   GenState[1]  |  --> mix --> audio output
voice allocator --> |   ...          |
                    +-- GenState[N-1]-+
```

### Voice allocator design

The allocator is shared code, not platform-specific. It lives in the ext layer (`_ext_*.cpp`) or a new shared file.

```c
typedef struct {
    GenState* states[MAX_VOICES];
    int active_note[MAX_VOICES];   // -1 = free
    int num_voices;
    int next_voice;                // round-robin counter
} VoicePool;
```

**Allocation policy:** Round-robin with oldest-steal. When all voices are active and a new note arrives, steal the oldest voice (lowest `next_voice` counter). This is the most common synth behavior and avoids stuck notes.

**Note-off routing:** Match by MIDI note number. If multiple voices play the same note (unlikely but possible with fast retrigger), release the oldest one.

### CLI interface

```bash
gen-dsp init export/ --platform clap --name polysynth \
    --midi-freq freq --midi-gate gate --midi-vel velocity \
    --voices 8
```

`--voices 1` is the default (monophonic). `--voices N` allocates N gen~ states.

### Memory and CPU implications

Each gen~ state is an independent allocation. For gigaverb, a single state is roughly 200KB (delay lines, filters). 8 voices = ~1.6MB. This is fine for most patches, but complex patches with large buffers could be expensive.

CPU scales linearly: 8 voices = 8x the `perform()` cost. The mixer sums all voice outputs, which is negligible relative to DSP cost.

**Lazy allocation option:** Only allocate voices when first triggered. This avoids the memory hit for unused voices, but adds latency on first note-on (gen~ `create()` does heap allocation). Not recommended -- allocate all voices eagerly at plugin init.

### Mixing strategy

After processing all active voices, sum their outputs into the plugin's output buffer:

```c
// Clear output
memset(out[ch], 0, n * sizeof(float));
// Sum all active voices
for (int v = 0; v < num_voices; v++) {
    if (active[v]) {
        for (int ch = 0; ch < num_outputs; ch++) {
            for (int s = 0; s < n; s++) {
                out[ch][s] += voice_out[v][ch][s];
            }
        }
    }
}
```

Each voice needs its own output buffer (`voice_out[v][ch]`). These are allocated once at init, same lifetime as the voice states.

No normalization by voice count -- this matches how hardware polysynths work (more voices = louder). The user can normalize in their gen~ patch if desired.

### Global vs per-voice parameters

All gen~ parameters that are *not* MIDI-mapped (freq/gate/vel) are **global** -- setting "filter cutoff" affects all voices simultaneously. This matches the standard synth paradigm (one knob controls all voices).

Implementation: when a non-MIDI parameter changes, iterate all voice states and call `wrapper_set_param()` on each:

```c
for (int v = 0; v < num_voices; v++) {
    wrapper_set_param(voices[v], param_idx, value);
}
```

### Per-note expression (MPE / CLAP per-note params)

Out of scope for initial implementation. CLAP and VST3 both support per-note expression (pitch bend, pressure, brightness per voice), but this requires a much more complex event routing system. It can be added later without breaking the basic polyphony architecture.

### Sample-accurate voice triggering

For the monophonic case, block-rate note handling is acceptable. For polyphony, fast arpeggios and drum patterns can have multiple note-ons in a single block. Dropping events is audible.

**Sub-block splitting:** Process the audio block in segments, applying note events at their sample-accurate timestamps:

```
Block: [0 .................. 512]
Events:    ^note-on@42  ^note-off@300  ^note-on@301

Segments:  [0..41] process all voices
           apply note-on@42
           [42..299] process all voices
           apply note-off@300, note-on@301
           [300..511] process all voices
```

This is the correct approach but adds complexity. All plugin APIs provide sample-accurate timestamps (VST3 `Event::sampleOffset`, CLAP `clap_event_header::time`, LV2 atom event frames).

**Recommendation:** Implement block-rate first (last-event-wins per block), add sub-block splitting as an optimization later. The infrastructure (event sorting, segment processing) is mechanical but verbose.

---

## Implementation Order

1. **Monophonic CLAP** -- CLAP has the cleanest MIDI API (typed note events, float velocity, sample-accurate timestamps). Use as the reference implementation.
2. **Monophonic VST3** -- Similar event model to CLAP. Second easiest.
3. **Monophonic AU** -- Raw MIDI bytes require manual parsing. More work but well-understood.
4. **Monophonic LV2** -- Atom sequences add complexity (LV2 atom API is verbose).
5. **Polyphony** -- Voice allocator is platform-independent. Add to all platforms simultaneously once mono works.
6. **Sub-block scheduling** -- Performance optimization, add after polyphony works.
7. **MPE / per-note expression** -- Stretch goal.

## Open Questions

1. **Should `--voices` be a runtime parameter or compile-time?** Compile-time (current plan) means the voice count is baked into the binary. Runtime would let users change it in the DAW, but requires dynamic allocation and a max-voices cap.

> compile-time for now

2. **Note priority for monophonic mode:** Last-note priority (proposed) is most common, but some users prefer lowest-note or highest-note priority. Worth a `--note-priority` flag?

> Yes, worth a `--note-priority` flag to override the default last-note priority

3. **Portamento/glide:** Frequency smoothing between notes is common in monosynths. gen~ patches can implement this internally (using `slide` or `history`), but the wrapper could also offer a built-in glide option. Probably better to leave this to the gen~ patch.

> Agreed.

4. **Sustain pedal (CC64):** Should the wrapper handle sustain hold (delay note-offs while pedal is down)? This is expected behavior for keyboard instruments. Simple to implement in the voice allocator but adds state.

> Should be added as a subsequent extension.

5. **MIDI channel filtering:** Accept all channels (default) or filter to a specific channel? Relevant for multi-timbral setups but probably overkill for v1.

> Overkill for v1, but should be added later.
