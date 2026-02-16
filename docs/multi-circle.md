# Multi-Plugin Circle Backend

## Current State

The Circle backend produces a single-purpose bare-metal kernel image: one gen~ export = one `.img` = one Raspberry Pi. The kernel boots, initializes the audio device, and runs a single `GetChunk()` ISR that calls `wrapper_perform()` on one `GenState*`.

## Goal

Support multiple gen~ plugins in a single bare-metal Circle image, with compile-time graph configuration via JSON and runtime parameter control via USB MIDI.

The implementation is split into two phases:
- **Phase 1:** Serial chain (single core) -- linear pipeline of effects
- **Phase 2:** Mixer/router topology -- arbitrary DAGs with splits, parallel paths, and mixing

Both phases use the same JSON configuration format. A serial chain is just a linear graph. Phase 1 validates that the graph is linear and rejects non-linear configs with a clear error. Phase 2 lifts that restriction.

---

## JSON Graph Configuration

The JSON file is an input to `gen-dsp init` at project generation time. The Python code generator reads it, validates the graph, resolves processing order, allocates intermediate buffers, and emits C code. No JSON parsing happens at runtime on the Pi -- the graph is "compiled" into a flat sequence of C function calls.

Parameter *values* and MIDI CC mappings are baked into the generated code from the JSON. **(Not yet implemented:** optional override via an INI file on the SD card at boot, for presets and controller remapping without recompilation.**)**

### Schema

```json
{
  "nodes": {
    "<name>": {
      "export": "<gen_export_dir_name>"
    }
  },
  "connections": [
    ["<source_node>", "<dest_node>"],
    ["<source_node>", "<dest_node>:<input_index>"]
  ],
  "midi": {
    "<node_name>": {
      "channel": 1,
      "cc": {
        "<cc_number>": "<param_name>"
      }
    }
  }
}
```

**Reserved node names:**
- `audio_in` -- hardware audio input (channel count from board config, currently stereo)
- `audio_out` -- hardware audio output

**Connection format:**
- `["A", "B"]` -- connect A's outputs to B's inputs sequentially (out[0]->in[0], out[1]->in[1], zero-pad or truncate on mismatch)
- `["A", "B:1"]` -- connect A's outputs to B's input starting at index 1 (for mixer input selection)

**MIDI mapping:**
- `channel` assigns a MIDI channel to the node
- Without `cc`, CCs map to parameters by index (CC 0 -> param 0, CC 1 -> param 1, etc.)
- With `cc`, explicit CC-to-param-name mappings replace the default index-based mapping

### Phase 1 Example: Serial Chain

```json
{
  "nodes": {
    "reverb": { "export": "gigaverb" },
    "comp":   { "export": "compressor" }
  },
  "connections": [
    ["audio_in", "reverb"],
    ["reverb",   "comp"],
    ["comp",     "audio_out"]
  ],
  "midi": {
    "reverb": { "channel": 1 },
    "comp":   { "channel": 2 }
  }
}
```

The code generator validates this is a linear chain (`audio_in -> ... -> audio_out`, no fan-out or fan-in) and emits:

```cpp
void process_graph(float** hw_in, float** hw_out, int nframes) {
    wrapper_perform_0(states[0], hw_in,    tmp_buf_0, nframes);  // reverb
    wrapper_perform_1(states[1], tmp_buf_0, hw_out,   nframes);  // comp
}
```

### Phase 2 Example: Parallel Paths with Mixer

```json
{
  "nodes": {
    "reverb": { "export": "gigaverb" },
    "delay":  { "export": "stereo_delay" },
    "comp":   { "export": "compressor" },
    "mix":    { "type": "mixer", "inputs": 2 }
  },
  "connections": [
    ["audio_in", "reverb"],
    ["audio_in", "delay"],
    ["reverb",   "mix:0"],
    ["delay",    "mix:1"],
    ["mix",      "comp"],
    ["comp",     "audio_out"]
  ],
  "midi": {
    "reverb": { "channel": 1, "cc": { "21": "revtime", "22": "roomsize" } },
    "delay":  { "channel": 2 },
    "comp":   { "channel": 3 },
    "mix":    { "channel": 4, "cc": { "7": "gain_0", "8": "gain_1" } }
  }
}
```

This represents:

```
             +-> [reverb] --+
audio_in --->|              |--> [mix] --> [comp] --> audio_out
             +-> [delay]  --+
```

The code generator runs topological sort and emits:

```cpp
void process_graph(float** hw_in, float** hw_out, int nframes) {
    // Step 0-1: reverb and delay (both depend only on audio_in)
    wrapper_perform_0(states[0], hw_in, buf_A, nframes);  // reverb
    wrapper_perform_1(states[1], hw_in, buf_B, nframes);  // delay

    // Step 2: mix (weighted sum)
    for (int ch = 0; ch < 2; ch++)
        for (int i = 0; i < nframes; i++)
            buf_C[ch][i] = buf_A[ch][i] * gain_0 + buf_B[ch][i] * gain_1;

    // Step 3: comp
    wrapper_perform_2(states[2], buf_C, hw_out, nframes);  // comp
}
```

All buffer allocation and routing is resolved at compile time. No runtime graph traversal, no dynamic dispatch. The generated code is a flat sequence of calls -- as efficient as hand-written C.

### Built-in Node Types (Phase 2)

- **`mixer`** -- weighted sum of N inputs. Each input has a `gain_N` parameter (default 1.0), controllable via MIDI CC. The `inputs` field specifies how many inputs.
- **Fan-out (splitter)** -- implicit. If `audio_in` connects to both `reverb` and `delay`, the code generator passes the same buffer pointer to both. No copy needed since gen~ does not modify its input buffers.

### Graph Validation (Python, at generation time)

1. **Cycle detection** -- the graph must be a DAG
2. **Connectivity** -- all nodes must be reachable from `audio_in`; all paths must reach `audio_out`
3. **Channel compatibility** -- warn on channel count mismatches between connected nodes (zero-pad missing channels, truncate extras)
4. **Phase 1 linearity check** -- reject fan-out/fan-in until Phase 2 is implemented
5. **Export resolution** -- each node's `export` field must correspond to a gen~ export directory provided via `--export`

---

## Parameter Control via MIDI CC

The current single-plugin Circle backend has entirely static parameters -- `CKernel::Run()` is an empty spin loop. A multi-plugin chain needs runtime control.

### Execution Context Separation

- `GetChunk()` runs in DMA ISR context -- cannot poll I/O, but reads `GenState` params (already updated).
- `CKernel::Run()` runs in the main loop on core 0 between interrupts -- this is where MIDI/GPIO/network input is polled.
- `wrapper_set_param()` writes a single aligned 32-bit float, which is atomic on ARM. No lock needed between `Run()` and the ISR.

```
CKernel::Run()                          DMA ISR (GetChunk)
  |                                       |
  v                                       v
  Poll USB MIDI / GPIO / network    Read GenState params
  |                                  (already updated)
  v                                       |
  Lookup (cc, channel) -> (plugin, param) |
  |                                       v
  v                                  process_graph()
  wrapper_set_param(states[i], p, v)   wrapper_perform(states[0])
  |                                    wrapper_perform(states[1])
  v                                       |
  (loop)                             Convert to DMA samples
```

### Mapping Scheme

**Default: MIDI channel per plugin.** CCs map to parameters by index (CC 0 -> param 0, CC 1 -> param 1, etc.). Requires zero CC configuration in the JSON -- just assign a channel per node.

**Override: explicit CC mappings.** When a `cc` object is present in the node's MIDI config, it replaces the default index-based mapping entirely. This allows multiple plugins to share a MIDI channel, or CCs to match a physical controller layout.

### Implementation

The mapping table is a 2D lookup indexed by MIDI channel and CC number, generated from the JSON at build time:

```cpp
struct ParamMapping {
    uint8_t plugin_index;
    uint8_t param_index;
    float   range_min;    // gen~ param min (from manifest)
    float   range_max;    // gen~ param max (from manifest)
};

// 16 channels x 128 CCs = 16KB
ParamMapping mapping_table[16][128];  // UNMAPPED sentinel for unused slots
```

Gen~ param ranges are known at compile time from the manifest, so defaults are baked in. On CC receive:

```cpp
void OnMidiCC(uint8_t channel, uint8_t cc, uint8_t value) {
    auto& m = mapping_table[channel][cc];
    if (m.plugin_index != UNMAPPED) {
        float normalized = value / 127.0f;
        float scaled = m.range_min + normalized * (m.range_max - m.range_min);
        wrapper_set_param(states[m.plugin_index], m.param_index, scaled);
    }
}
```

### Beyond MIDI CC

The same `ParamMapping` table can be driven by other input sources using the same `(plugin_index, param_index, value)` triple:

- **GPIO/ADC knobs** via external MCP3008 (SPI) or ADS1115 (I2C) -- polled in `Run()`, mapped to a fixed param
- **Network control** via HTTP API or MQTT -- parsed in `Run()`, dispatched to mapping table
- **MIDI program change** -- switch parameter presets (load a saved set of values from SD card) **(not yet implemented)**

---

## CLI Interface

```bash
# Generate multi-plugin project from graph config
gen-dsp init \
    --graph graph.json \
    --export ~/exports/gigaverb/gen \
    --export ~/exports/compressor/gen \
    --board pi4-i2s \
    --name my_fx_chain \
    -p circle \
    my_fx_chain_circle

# Build
gen-dsp build my_fx_chain_circle -p circle

# Output: kernel8-rpi4.img
```

When `--graph` is provided, the Circle platform switches to multi-plugin mode. Without `--graph`, the existing single-plugin behavior is unchanged.

Each `--export` path provides a gen~ export directory. The JSON `nodes[*].export` field references these by directory name. The code generator resolves node exports against the provided `--export` paths.

---

## Implementation Plan

### Phase 1: Serial Chain (Single Core)

| Step | What | Scope |
|------|------|-------|
| 1 | JSON schema definition + validation in Python | Small -- dataclass + manual validation |
| 2 | Linear chain code generation from JSON | Small -- validate linearity, emit loop |
| 3 | Kernel template with N plugins + USB MIDI CC dispatch in `Run()` | Medium -- new template |
| 4 | Makefile template for N gen~ exports | Small -- extend existing template |
| 5 | CLI: `--graph` and multi `--export` flags | Small -- new flags on `init` command |
| 6 | Tests with 2-3 fixture exports chained | Medium |

### Phase 2: Mixer/Router Topology

| Step | What | Scope |
|------|------|-------|
| 7 | Topological sort of node graph | Medium -- standard algorithm, emit ordered calls |
| 8 | Intermediate buffer allocation | Medium -- one buffer per edge, reuse after consumption |
| 9 | Built-in mixer node (weighted sum of N inputs) | Small |
| 10 | Fan-out support (implicit from DAG structure) | Small -- falls out of toposort naturally |
| 11 | Channel mismatch handling (zero-pad / truncate) | Small |
| 12 | Tests with parallel paths + mixer configs | Medium |

Phase 1 uses the same JSON format as Phase 2. The only difference is that Phase 1 rejects non-linear graphs with a clear error message.

---

## Design Decisions

### Compile-Time vs Runtime Configuration

The JSON graph is a **compile-time** input. It is read by `gen-dsp init` in Python, and the output is generated C code with a hardcoded `process_graph()` function. No JSON parser runs on the Pi.

This means:
- Changing the graph topology requires re-running `gen-dsp init` + `build`
- Changing parameter values does not -- presets could be loaded from SD card at boot **(not yet implemented)**
- Changing MIDI CC mappings could go either way; baked-in defaults with optional SD card overrides is the pragmatic choice **(SD card overrides not yet implemented)**

### Why Not Runtime Graph Configuration?

1. No JSON parser on bare metal (Circle has no stdlib JSON support; adding one is possible but adds complexity)
2. Compile-time resolution allows the C compiler to optimize the processing function (inlining, constant propagation)
3. The graph topology is inherently a "design-time" decision -- you don't change your effects chain at runtime, you change parameter values

### Buffer Allocation Strategy

**Phase 1:** Two scratch buffers (A and B), ping-ponged between stages. Plugin 0 reads from hw_in and writes to A. Plugin 1 reads from A and writes to B. Plugin 2 reads from B and writes to hw_out (or A again). Memory cost: `2 * max_channels * chunk_size * sizeof(float)`.

**Phase 2:** One buffer per active edge in the graph. After a downstream node has consumed an edge's buffer, it can be reused. A simple approach: allocate one buffer per edge. A more sophisticated approach: graph coloring to minimize total buffer count. The simple approach is likely sufficient -- even 8 intermediate stereo buffers at 256 samples is only 16KB.

### Channel Mismatch Handling

When plugin A outputs 2 channels but plugin B expects 3 inputs:
- Zero-pad: B's input[2] receives silence
- Log a warning at generation time so the user is aware

When plugin A outputs 3 channels but plugin B expects 2 inputs:
- Truncate: B only receives A's first 2 channels
- Log a warning at generation time

This matches how most DAWs handle bus width mismatches.

---

## Reference: Circle Capabilities

### Multi-Core

Circle's `CMultiCoreSupport` provides:
- `Run(unsigned nCore)` entry point for cores 1-3
- `CSpinLock` for critical sections
- `SendIPI()` / `IPIHandler()` for inter-processor interrupts
- All peripheral interrupts (DMA, USB, timers) run exclusively on core 0

Proven by [MiniDexed](https://github.com/probonopd/MiniDexed): 8-16 Dexed tone generators across 4 cores with USB MIDI, I2S output, and SD card patch loading.

Not needed for Phase 1 or 2 (single-core is sufficient for typical gen~ patch counts), but available as a future optimization if DSP budget becomes tight.

### USB MIDI

`CUSBMIDIDevice` provides:
- `RegisterPacketHandler()` for receiving 4-byte USB-MIDI event packets
- Hot-plug support (devices can be attached/removed at any time)
- Multiple devices via USB hub

### Filesystem

FatFs addon provides full FAT32 with long filenames and subdirectories. Sufficient for reading preset files and MIDI CC override configs from SD card at boot. **(Not yet used by gen-dsp.)**

### Networking

Built-in TCP/IP stack with HTTP server, DHCP, DNS, mDNS. Could serve a browser-based control UI in a future iteration.

### Dynamic Loading

Circle has no dynamic linker. All plugins are statically compiled into the kernel image. This is the correct tradeoff for this use case -- the graph topology is a design-time decision, and static compilation allows full compiler optimization of the processing path.
