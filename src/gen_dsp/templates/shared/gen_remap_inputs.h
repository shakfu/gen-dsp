// gen_remap_inputs.h - Input-to-parameter remapping for gen-dsp wrappers
//
// When gen~ exports use signal-rate `in` objects for control data (e.g.,
// pitch, gate), --inputs-as-params converts them to plugin parameters.
// The gen~ perform function still receives its expected input buffers --
// this header fills the remapped input buffers with parameter values.
//
// Required defines when REMAP_INPUT_COUNT > 0:
//   REMAP_INPUT_COUNT        - number of remapped inputs
//   REMAP_GEN_TOTAL_INPUTS   - gen~'s original total input count
//   REMAP_INPUT_N_GEN_IDX    - gen~ input index for remap slot N
//   REMAP_INPUT_N_PARAM_IDX  - parameter index for remap slot N
//   REMAP_INPUT_N_NAME       - display name string for remap slot N
//
// Required from the including bridge:
//   perform()       - gen~'s perform function (via genlib_exportfunctions.h)
//   num_inputs()    - gen~'s original input count
//   num_params()    - gen~'s original param count
//   setparameter()  - genlib setparameter
//   getparameter()  - genlib getparameter
//   getparametername(), getparametermin(), getparametermax(),
//   getparameterhasminmax() - genlib parameter accessors
//   _silence[]      - zero-filled float buffer of _REMAP_MAX_BLOCK (from bridge)
//   CommonState, t_sample, t_param - genlib types
//   <atomic>        - included at global scope: bridges include this header
//                     inside their namespace
//
// Each instance keeps its values and buffers in CommonState::parammap, which
// genlib leaves to the host: the bridge calls _remap_attach() after create()
// and _remap_detach() before destroy(). Both are no-ops without remapping.

#ifndef GEN_REMAP_INPUTS_H
#define GEN_REMAP_INPUTS_H

#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0

// ---------------------------------------------------------------------------
// Remap table: compile-time mapping from gen~ input index to param index
// ---------------------------------------------------------------------------

struct RemapEntry { int gen_idx; int param_idx; };

static const RemapEntry _remap_table[] = {
#if REMAP_INPUT_COUNT > 0
    { REMAP_INPUT_0_GEN_IDX, REMAP_INPUT_0_PARAM_IDX },
#endif
#if REMAP_INPUT_COUNT > 1
    { REMAP_INPUT_1_GEN_IDX, REMAP_INPUT_1_PARAM_IDX },
#endif
#if REMAP_INPUT_COUNT > 2
    { REMAP_INPUT_2_GEN_IDX, REMAP_INPUT_2_PARAM_IDX },
#endif
#if REMAP_INPUT_COUNT > 3
    { REMAP_INPUT_3_GEN_IDX, REMAP_INPUT_3_PARAM_IDX },
#endif
#if REMAP_INPUT_COUNT > 4
    { REMAP_INPUT_4_GEN_IDX, REMAP_INPUT_4_PARAM_IDX },
#endif
#if REMAP_INPUT_COUNT > 5
    { REMAP_INPUT_5_GEN_IDX, REMAP_INPUT_5_PARAM_IDX },
#endif
#if REMAP_INPUT_COUNT > 6
    { REMAP_INPUT_6_GEN_IDX, REMAP_INPUT_6_PARAM_IDX },
#endif
#if REMAP_INPUT_COUNT > 7
    { REMAP_INPUT_7_GEN_IDX, REMAP_INPUT_7_PARAM_IDX },
#endif
};

// Display names for remapped params
static const char* _remap_param_names[] = {
#if REMAP_INPUT_COUNT > 0
    REMAP_INPUT_0_NAME,
#endif
#if REMAP_INPUT_COUNT > 1
    REMAP_INPUT_1_NAME,
#endif
#if REMAP_INPUT_COUNT > 2
    REMAP_INPUT_2_NAME,
#endif
#if REMAP_INPUT_COUNT > 3
    REMAP_INPUT_3_NAME,
#endif
#if REMAP_INPUT_COUNT > 4
    REMAP_INPUT_4_NAME,
#endif
#if REMAP_INPUT_COUNT > 5
    REMAP_INPUT_5_NAME,
#endif
#if REMAP_INPUT_COUNT > 6
    REMAP_INPUT_6_NAME,
#endif
#if REMAP_INPUT_COUNT > 7
    REMAP_INPUT_7_NAME,
#endif
};

// ---------------------------------------------------------------------------
// Per-instance storage: values set by the host, buffers filled with them
// ---------------------------------------------------------------------------

#define _REMAP_MAX_BLOCK 8192
#define _REMAP_MIN_BLOCK 512  // a host announcing 1-sample blocks may still send more

struct _RemapState {
    std::atomic<float> values[REMAP_INPUT_COUNT];
    long cap;     // samples per buffer; longer blocks run in pieces
    float* bufs;  // REMAP_INPUT_COUNT * cap
};

static inline _RemapState* _remap_state(CommonState* state) {
    return static_cast<_RemapState*>(state->parammap);
}

static inline void _remap_attach(CommonState* state, long bs) {
    _RemapState* r = new _RemapState;
    for (int i = 0; i < REMAP_INPUT_COUNT; i++) r->values[i].store(0.0f);
    r->cap = bs < _REMAP_MIN_BLOCK ? _REMAP_MIN_BLOCK : bs > _REMAP_MAX_BLOCK ? _REMAP_MAX_BLOCK : bs;
    r->bufs = new float[REMAP_INPUT_COUNT * r->cap];
    state->parammap = r;
}

static inline void _remap_detach(CommonState* state) {
    _RemapState* r = _remap_state(state);
    if (!r) return;
    delete[] r->bufs;
    delete r;
    state->parammap = nullptr;
}

// The remapped values of one instance, indexed by remap slot.
static inline std::atomic<float>* _remap_values(CommonState* state) {
    return _remap_state(state)->values;
}

// ---------------------------------------------------------------------------
// Helper: is this gen~ input index remapped?
// ---------------------------------------------------------------------------

static inline int _remap_slot_for_gen_idx(int gen_idx) {
    for (int r = 0; r < REMAP_INPUT_COUNT; r++) {
        if (_remap_table[r].gen_idx == gen_idx) return r;
    }
    return -1;
}

// ---------------------------------------------------------------------------
// Perform with remapped inputs
// ---------------------------------------------------------------------------

static inline void _remap_perform(
    CommonState* state,
    float** ins, long numins,
    float** outs, long numouts, long n
) {
    _RemapState* r = _remap_state(state);
    float* full_ins[REMAP_GEN_TOTAL_INPUTS > 0 ? REMAP_GEN_TOTAL_INPUTS : 1];
    float* part_outs[64];
    if (numouts > 64) numouts = 64;
    for (long done = 0; done < n;) {
        long len = n - done < r->cap ? n - done : r->cap;
        // Fill remapped input buffers with their parameter values
        for (int s = 0; s < REMAP_INPUT_COUNT; s++) {
            float val = r->values[s].load(std::memory_order_relaxed);
            float* buf = r->bufs + s * r->cap;
            for (long i = 0; i < len; i++) buf[i] = val;
        }
        // Build full input array for gen~
        int audio_idx = 0;
        for (int i = 0; i < REMAP_GEN_TOTAL_INPUTS; i++) {
            int slot = _remap_slot_for_gen_idx(i);
            if (slot >= 0) {
                full_ins[i] = r->bufs + slot * r->cap;
            } else {
                full_ins[i] = (audio_idx < numins && ins) ? ins[audio_idx] + done : _silence;
                audio_idx++;
            }
        }
        for (long o = 0; o < numouts; o++) part_outs[o] = outs[o] + done;
        perform(state, (t_sample**)full_ins, REMAP_GEN_TOTAL_INPUTS,
                (t_sample**)part_outs, numouts, len);
        done += len;
    }
}

// ---------------------------------------------------------------------------
// Param wrappers: intercept synthetic params for remapped inputs
// ---------------------------------------------------------------------------

static inline int _remap_total_params() {
    return num_params() + REMAP_INPUT_COUNT;
}

static inline bool _is_remap_param(int index) {
    return index >= num_params() && index < num_params() + REMAP_INPUT_COUNT;
}

static inline int _remap_slot_from_param(int index) {
    return index - num_params();
}

#else

static inline void _remap_attach(CommonState*, long) {}
static inline void _remap_detach(CommonState*) {}

#endif // REMAP_INPUT_COUNT > 0

#endif // GEN_REMAP_INPUTS_H
