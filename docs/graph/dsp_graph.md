# DSP Graph Representation

This document describes the JSON DSP graph format used by `gen_dsp.graph` and the corresponding C++ code the compiler emits. Three examples illustrate increasing complexity: a stateless gain, a stateful filter, and a feedback delay.

## 1. Stereo Gain (stateless)

Signal flow: `in -> * gain -> out`

### Graph

```json
{
  "name": "stereo_gain",
  "inputs": [{"id": "in1"}, {"id": "in2"}],
  "outputs": [
    {"id": "out1", "source": "scaled1"},
    {"id": "out2", "source": "scaled2"}
  ],
  "params": [
    { "name": "gain", "min": 0.0, "max": 2.0, "default": 1.0 }
  ],
  "nodes": [
    { "id": "scaled1", "op": "mul", "a": "in1", "b": "gain" },
    { "id": "scaled2", "op": "mul", "a": "in2", "b": "gain" }
  ]
}
```

### C++

No state, no history. The `perform()` function is pure arithmetic.

```cpp
struct StereoGainState {
    float sr;
    float p_gain;
};

StereoGainState* create(float sr) {
    StereoGainState* self = new StereoGainState();
    self->sr = sr;
    self->p_gain = 1.0f;
    return self;
}

void perform(StereoGainState* self,
             float** __restrict ins, float** __restrict outs, int n) {
    float* in1  = ins[0];
    float* in2  = ins[1];
    float* out1 = outs[0];
    float* out2 = outs[1];
    float gain = self->p_gain;

    for (int i = 0; i < n; i++) {
        float scaled1 = in1[i] * gain;
        float scaled2 = in2[i] * gain;
        out1[i] = scaled1;
        out2[i] = scaled2;
    }
}
```

---

## 2. One-Pole Lowpass (stateful)

Signal flow: `out = (1 - coeff) * in + coeff * prev`

The `History` node stores the previous output sample. This is the simplest form of state in a DSP graph -- a single-sample delay in a feedback path.

### Graph

```json
{
  "name": "onepole",
  "inputs": [{"id": "in1"}],
  "outputs": [{"id": "out1", "source": "result"}],
  "params": [
    { "name": "coeff", "min": 0.0, "max": 0.999, "default": 0.5 }
  ],
  "nodes": [
    { "id": "inv_coeff", "op": "sub", "a": 1.0, "b": "coeff" },
    { "id": "dry",       "op": "mul", "a": "in1", "b": "inv_coeff" },
    { "id": "prev",      "op": "history", "init": 0.0, "input": "result" },
    { "id": "wet",       "op": "mul", "a": "prev", "b": "coeff" },
    { "id": "result",    "op": "add", "a": "dry", "b": "wet" }
  ]
}
```

Note the feedback edge: `result -> prev`. The `History` node breaks what would otherwise be a circular dependency by providing the *previous* sample's value while accepting the *current* sample's value for next time.

### C++

The compiler resolves the feedback loop by introducing `m_history` state and scheduling operations in topological order.

```cpp
struct OnepoleState {
    float sr;
    float p_coeff;
    float m_prev;       // history: prev
};

OnepoleState* create(float sr) {
    OnepoleState* self = new OnepoleState();
    self->sr = sr;
    self->p_coeff = 0.5f;
    self->m_prev = 0.0f;
    return self;
}

void perform(OnepoleState* self,
             float** __restrict ins, float** __restrict outs, int n) {
    float* in1  = ins[0];
    float* out1 = outs[0];
    float coeff = self->p_coeff;
    float prev  = self->m_prev;

    // Invariant: hoisted before loop
    float inv_coeff = 1.0f - coeff;

    for (int i = 0; i < n; i++) {
        float dry    = in1[i] * inv_coeff;
        float wet    = prev * coeff;
        float result = dry + wet;

        out1[i] = result;
        prev = result;      // history feedback (deferred write-back)
    }

    self->m_prev = prev;
}
```

---

## 3. Feedback Delay (delay line + feedback loop)

Signal flow:

```text
in --+--> [delay] --+--> out
     ^              |
     |   feedback   |
     +---[* fb]<----+
```

The delay line introduces *multi-sample* state (a circular buffer), versus the single-sample state of `History`.

### Graph

```json
{
  "name": "fbdelay",
  "inputs": [{"id": "in1"}],
  "outputs": [{"id": "out1", "source": "mix_out"}],
  "params": [
    { "name": "delay_ms", "min": 1.0,  "max": 1000.0, "default": 250.0 },
    { "name": "feedback", "min": 0.0,  "max": 0.95,   "default": 0.5 },
    { "name": "mix",      "min": 0.0,  "max": 1.0,    "default": 0.5 }
  ],
  "nodes": [
    { "id": "sr_ms",     "op": "div",         "a": 44100.0, "b": 1000.0 },
    { "id": "tap",       "op": "mul",         "a": "delay_ms", "b": "sr_ms" },
    { "id": "dline",     "op": "delay",       "max_samples": 48000 },
    { "id": "delayed",   "op": "delay_read",  "delay": "dline", "tap": "tap" },
    { "id": "fb_scaled", "op": "mul",         "a": "delayed", "b": "feedback" },
    { "id": "write_val", "op": "add",         "a": "in1", "b": "fb_scaled" },
    { "id": "dwrite",    "op": "delay_write", "delay": "dline", "value": "write_val" },
    { "id": "inv_mix",   "op": "sub",         "a": 1.0, "b": "mix" },
    { "id": "dry",       "op": "mul",         "a": "in1", "b": "inv_mix" },
    { "id": "wet",       "op": "mul",         "a": "delayed", "b": "mix" },
    { "id": "mix_out",   "op": "add",         "a": "dry", "b": "wet" }
  ]
}
```

### C++

The compiler allocates the circular buffer, converts delay time to samples, and resolves the feedback ordering (read before write).

```cpp
struct FbdelayState {
    float  sr;
    float  p_delay_ms;
    float  p_feedback;
    float  p_mix;
    float* m_dline_buf;
    int    m_dline_len;
    int    m_dline_wr;
};

FbdelayState* create(float sr) {
    FbdelayState* self = new FbdelayState();
    self->sr = sr;
    self->p_delay_ms = 250.0f;
    self->p_feedback = 0.5f;
    self->p_mix = 0.5f;
    self->m_dline_len = 48000;
    self->m_dline_buf = new float[48000]();
    self->m_dline_wr = 0;
    return self;
}

void perform(FbdelayState* self,
             float** __restrict ins, float** __restrict outs, int n) {
    float* in1  = ins[0];
    float* out1 = outs[0];
    float delay_ms = self->p_delay_ms;
    float feedback = self->p_feedback;
    float mix      = self->p_mix;
    float* buf     = self->m_dline_buf;
    int    len     = self->m_dline_len;
    int    wr      = self->m_dline_wr;

    // Invariant: hoisted before loop
    float sr_ms   = 44100.0f / 1000.0f;
    float tap     = delay_ms * sr_ms;
    float inv_mix = 1.0f - mix;

    for (int i = 0; i < n; i++) {
        // delay_read
        int rd = wr - (int)tap;
        if (rd < 0) rd += len;
        float delayed = buf[rd];

        // feedback + write
        float fb_scaled = delayed * feedback;
        float write_val = in1[i] + fb_scaled;
        buf[wr] = write_val;
        wr = (wr + 1) % len;

        // dry/wet mix
        float dry     = in1[i] * inv_mix;
        float wet     = delayed * mix;
        out1[i]       = dry + wet;
    }

    self->m_dline_wr = wr;
}
```

---

## The Compilation Pipeline

Going from the Graph model to C++ requires:

1. **Topological sort** -- schedule nodes so that inputs are computed before outputs, with feedback edges broken at `History`/`Delay` boundaries.
2. **State allocation** -- determine how much memory each `History`/`Delay`/`Buffer` node needs, lay out the state struct.
3. **Loop-invariant code motion** -- identify param-only expressions and hoist them before the sample loop.
4. **Code emission** -- walk sorted nodes and emit one C++ statement per node.
5. **Optimization** -- constant folding, dead code elimination, common subexpression elimination.

The compiled C++ follows the same `wrapper_*` interface (create/destroy/reset/perform + param/buffer introspection) that gen-dsp's platform backends expect, allowing graph-compiled code to plug directly into any of the 11 supported platforms.
