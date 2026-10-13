// gen_ext_nice.cpp - C ABI over the gen~ wrapper, called from Rust (src/engine.rs)
// This file includes no genlib headers - genlib is isolated in _ext_nice.cpp
//
// Hides the monophonic / polyphonic split behind one opaque GenDspEngine, so
// the Rust side sees the same API whatever NUM_VOICES is.

#include "gen_ext_common_nice.h"
#include "_ext_nice.h"

#include <cstdlib>
#include <cmath>

using namespace WRAPPER_NAMESPACE;

#ifdef MIDI_ENABLED
#if NUM_VOICES > 1
#include "voice_alloc.h"
#else
static inline float mtof(int note) {
    return 440.0f * powf(2.0f, (note - 69) / 12.0f);
}
#endif
#endif

struct GenDspEngine {
#if NUM_VOICES > 1
    VoiceAllocator voiceAlloc;
#else
    GenState* state;
#endif
};

extern "C" {

GenDspEngine* gendsp_create(float sr, int max_frames) {
    GenDspEngine* e = (GenDspEngine*)calloc(1, sizeof(GenDspEngine));
    if (!e) return nullptr;
#if NUM_VOICES > 1
    voice_alloc_init(&e->voiceAlloc, wrapper_num_outputs(), (long)max_frames);
    voice_alloc_create_voices(&e->voiceAlloc, sr, (long)max_frames);
    if (!e->voiceAlloc.states[0]) {
        voice_alloc_destroy(&e->voiceAlloc);
        free(e);
        return nullptr;
    }
#else
    e->state = wrapper_create(sr, (long)max_frames);
    if (!e->state) {
        free(e);
        return nullptr;
    }
#endif
    return e;
}

void gendsp_destroy(GenDspEngine* e) {
    if (!e) return;
#if NUM_VOICES > 1
    voice_alloc_destroy(&e->voiceAlloc);
#else
    wrapper_destroy(e->state);
#endif
    free(e);
}

void gendsp_reset(GenDspEngine* e) {
#if NUM_VOICES > 1
    voice_alloc_reset(&e->voiceAlloc);
#else
    wrapper_reset(e->state);
#endif
}

void gendsp_perform(GenDspEngine* e, float** ins, int num_ins, float** outs, int num_outs, int n) {
#if NUM_VOICES > 1
    voice_alloc_perform(&e->voiceAlloc, ins, num_ins, outs, num_outs, (long)n);
#else
    wrapper_perform(e->state, ins, (long)num_ins, outs, (long)num_outs, (long)n);
#endif
}

void gendsp_set_param(GenDspEngine* e, int index, float value) {
#if NUM_VOICES > 1
    voice_alloc_set_global_param(&e->voiceAlloc, index, value);
#else
    wrapper_set_param(e->state, index, value);
#endif
}

float gendsp_get_param(GenDspEngine* e, int index) {
#if NUM_VOICES > 1
    return voice_alloc_get_param(&e->voiceAlloc, index);
#else
    return wrapper_get_param(e->state, index);
#endif
}

// Note handling mirrors the CLAP backend: MIDI_*_IDX select the gate, freq
// and velocity parameters; without MIDI_ENABLED these are no-ops.
void gendsp_note_on(GenDspEngine* e, int note, float velocity) {
    (void)e; (void)note; (void)velocity;
#ifdef MIDI_ENABLED
#if NUM_VOICES > 1
    voice_alloc_note_on(&e->voiceAlloc, note, velocity);
#else
#ifdef MIDI_GATE_IDX
    wrapper_set_param(e->state, MIDI_GATE_IDX, 1.0f);
#endif
#ifdef MIDI_FREQ_IDX
#if MIDI_FREQ_UNIT_HZ
    wrapper_set_param(e->state, MIDI_FREQ_IDX, mtof(note));
#else
    wrapper_set_param(e->state, MIDI_FREQ_IDX, (float)note);
#endif
#endif
#ifdef MIDI_VEL_IDX
    wrapper_set_param(e->state, MIDI_VEL_IDX, velocity);
#endif
#endif
#endif
}

void gendsp_note_off(GenDspEngine* e, int note) {
    (void)e; (void)note;
#ifdef MIDI_ENABLED
#if NUM_VOICES > 1
    voice_alloc_note_off(&e->voiceAlloc, note);
#else
#ifdef MIDI_GATE_IDX
    wrapper_set_param(e->state, MIDI_GATE_IDX, 0.0f);
#endif
#endif
#endif
}

int gendsp_num_inputs(void) { return wrapper_num_inputs(); }
int gendsp_num_outputs(void) { return wrapper_num_outputs(); }
int gendsp_num_params(void) { return wrapper_num_params(); }

} // extern "C"
