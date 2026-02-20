// voice_alloc.h - Polyphonic voice allocator for gen-dsp plugins
// Shared by all plugin platforms (CLAP, VST3, AU, LV2)
// Only included when NUM_VOICES > 1
//
// Round-robin allocation with oldest-steal when all voices are occupied.
// Note-off matches by MIDI note number. After all voices process,
// outputs are summed into the host buffer (no normalization).

#ifndef VOICE_ALLOC_H
#define VOICE_ALLOC_H

#include <cstring>
#include <cstdlib>
#include <cmath>

#ifndef NUM_VOICES
#define NUM_VOICES 1
#endif

#define VOICE_ALLOC_MAX_CHANNELS 64

struct VoiceAllocator {
    GenState*  states[NUM_VOICES];
    int        note[NUM_VOICES];       // MIDI note number, -1 = free
    uint32_t   age[NUM_VOICES];        // allocation counter for oldest-steal
    uint32_t   counter;                // monotonic allocation counter
    int        num_voices;
    // Per-voice output scratch buffers
    float*     voice_out[NUM_VOICES][VOICE_ALLOC_MAX_CHANNELS];
    int        num_out_channels;
    long       max_frames;
};

// Zero-fill the allocator, set dimensions
static inline void voice_alloc_init(VoiceAllocator* va, int num_outputs, long max_frames) {
    memset(va, 0, sizeof(VoiceAllocator));
    va->num_voices = NUM_VOICES;
    va->num_out_channels = num_outputs < VOICE_ALLOC_MAX_CHANNELS ? num_outputs : VOICE_ALLOC_MAX_CHANNELS;
    va->max_frames = max_frames;
    for (int v = 0; v < NUM_VOICES; v++) {
        va->note[v] = -1;
    }
}

// Create N voice states and allocate per-voice output scratch buffers
static inline void voice_alloc_create_voices(VoiceAllocator* va, float sample_rate, long max_frames) {
    va->max_frames = max_frames;
    for (int v = 0; v < NUM_VOICES; v++) {
        if (va->states[v]) {
            wrapper_destroy(va->states[v]);
        }
        va->states[v] = wrapper_create(sample_rate, max_frames);
        // Allocate per-voice output scratch buffers
        for (int ch = 0; ch < va->num_out_channels; ch++) {
            free(va->voice_out[v][ch]);
            va->voice_out[v][ch] = (float*)calloc((size_t)max_frames, sizeof(float));
        }
    }
}

// Destroy all voice states and free scratch buffers
static inline void voice_alloc_destroy(VoiceAllocator* va) {
    for (int v = 0; v < NUM_VOICES; v++) {
        if (va->states[v]) {
            wrapper_destroy(va->states[v]);
            va->states[v] = nullptr;
        }
        for (int ch = 0; ch < va->num_out_channels; ch++) {
            free(va->voice_out[v][ch]);
            va->voice_out[v][ch] = nullptr;
        }
        va->note[v] = -1;
    }
}

// Find free voice (round-robin) or steal oldest, set gate/freq/vel
// Returns voice index
static inline int voice_alloc_note_on(VoiceAllocator* va, int note, float velocity) {
    // First: look for a free voice
    int voice = -1;
    for (int v = 0; v < NUM_VOICES; v++) {
        if (va->note[v] < 0) {
            voice = v;
            break;
        }
    }

    // No free voice: steal the oldest
    if (voice < 0) {
        uint32_t oldest_age = va->age[0];
        voice = 0;
        for (int v = 1; v < NUM_VOICES; v++) {
            if (va->age[v] < oldest_age) {
                oldest_age = va->age[v];
                voice = v;
            }
        }
        // Send gate-off to stolen voice before reuse
#ifdef MIDI_GATE_IDX
        if (va->states[voice]) {
            wrapper_set_param(va->states[voice], MIDI_GATE_IDX, 0.0f);
        }
#endif
    }

    va->note[voice] = note;
    va->age[voice] = va->counter++;

    GenState* state = va->states[voice];
    if (!state) return voice;

    (void)velocity;
#ifdef MIDI_GATE_IDX
    wrapper_set_param(state, MIDI_GATE_IDX, 1.0f);
#endif
#ifdef MIDI_FREQ_IDX
#if MIDI_FREQ_UNIT_HZ
    wrapper_set_param(state, MIDI_FREQ_IDX, 440.0f * powf(2.0f, (note - 69) / 12.0f));
#else
    wrapper_set_param(state, MIDI_FREQ_IDX, (float)note);
#endif
#endif
#ifdef MIDI_VEL_IDX
    wrapper_set_param(state, MIDI_VEL_IDX, velocity);
#endif

    return voice;
}

// Find voice playing this note and set gate=0
static inline void voice_alloc_note_off(VoiceAllocator* va, int note) {
    for (int v = 0; v < NUM_VOICES; v++) {
        if (va->note[v] == note) {
#ifdef MIDI_GATE_IDX
            if (va->states[v]) {
                wrapper_set_param(va->states[v], MIDI_GATE_IDX, 0.0f);
            }
#endif
            va->note[v] = -1;
            return;
        }
    }
}

// Broadcast a non-MIDI parameter to all voices
static inline void voice_alloc_set_global_param(VoiceAllocator* va, int idx, float value) {
    for (int v = 0; v < NUM_VOICES; v++) {
        if (va->states[v]) {
            wrapper_set_param(va->states[v], idx, value);
        }
    }
}

// Get parameter value from the first voice (all voices share global params)
static inline float voice_alloc_get_param(VoiceAllocator* va, int idx) {
    if (va->states[0]) {
        return wrapper_get_param(va->states[0], idx);
    }
    return 0.0f;
}

// Process all voices and sum outputs
static inline void voice_alloc_perform(VoiceAllocator* va,
                                        float** ins, int num_ins,
                                        float** outs, int num_outs,
                                        long nframes) {
    int out_ch = num_outs < va->num_out_channels ? num_outs : va->num_out_channels;

    // Process first voice directly into output buffers
    if (va->states[0]) {
        wrapper_perform(va->states[0], ins, (long)num_ins, outs, (long)num_outs, nframes);
    } else {
        for (int ch = 0; ch < out_ch; ch++) {
            memset(outs[ch], 0, (size_t)nframes * sizeof(float));
        }
    }

    // Process remaining voices into scratch buffers and sum
    for (int v = 1; v < NUM_VOICES; v++) {
        if (!va->states[v]) continue;

        float* scratch[VOICE_ALLOC_MAX_CHANNELS];
        for (int ch = 0; ch < out_ch; ch++) {
            scratch[ch] = va->voice_out[v][ch];
        }

        wrapper_perform(va->states[v], ins, (long)num_ins, scratch, (long)num_outs, nframes);

        // Sum into output
        for (int ch = 0; ch < out_ch; ch++) {
            float* dst = outs[ch];
            float* src = scratch[ch];
            for (long s = 0; s < nframes; s++) {
                dst[s] += src[s];
            }
        }
    }
}

// Reset all voice states (preserves allocator state)
static inline void voice_alloc_reset(VoiceAllocator* va) {
    for (int v = 0; v < NUM_VOICES; v++) {
        if (va->states[v]) {
            wrapper_reset(va->states[v]);
        }
        va->note[v] = -1;
    }
    va->counter = 0;
}

// Save all parameter values from all voices (saves from voice 0 since globals are broadcast)
static inline void voice_alloc_save_params(VoiceAllocator* va, float* saved, int num_params) {
    if (va->states[0]) {
        for (int i = 0; i < num_params; i++) {
            saved[i] = wrapper_get_param(va->states[0], i);
        }
    }
}

// Restore parameter values to all voices
static inline void voice_alloc_restore_params(VoiceAllocator* va, const float* saved, int num_params) {
    for (int v = 0; v < NUM_VOICES; v++) {
        if (va->states[v]) {
            for (int i = 0; i < num_params; i++) {
                wrapper_set_param(va->states[v], i, saved[i]);
            }
        }
    }
}

#endif // VOICE_ALLOC_H
