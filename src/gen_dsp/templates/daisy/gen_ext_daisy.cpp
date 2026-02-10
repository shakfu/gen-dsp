// gen_ext_daisy.cpp - Daisy Seed wrapper for gen~ exports
// This file includes ONLY libDaisy headers - genlib is isolated in _ext_daisy.cpp
//
// Implements a bare Daisy Seed firmware with stereo audio I/O.
// Parameters retain gen~ defaults; modify this file to add ADC reads for knobs/CV.

#include "daisy_seed.h"

#include "gen_ext_common_daisy.h"
#include "_ext_daisy.h"
#include "genlib_daisy.h"

using namespace WRAPPER_NAMESPACE;
using namespace daisy;

// ---------------------------------------------------------------------------
// Hardware and state
// ---------------------------------------------------------------------------

static DaisySeed hw;
static GenState* genState = nullptr;

// ---------------------------------------------------------------------------
// Scratch buffers for I/O channel mismatch
// DaisySeed has 2 hardware channels; gen~ export may have more.
// Extra gen~ inputs get zeros; extra gen~ outputs are discarded.
// ---------------------------------------------------------------------------

// Maximum block size (Daisy default is 48, but user may change)
#define DAISY_MAX_BLOCK_SIZE 256

// Hardware channel count (DaisySeed = stereo)
#define DAISY_HW_CHANNELS 2

// Effective channel counts: min(gen~, hardware)
#define DAISY_MAPPED_INPUTS  ((DAISY_NUM_INPUTS < DAISY_HW_CHANNELS) ? DAISY_NUM_INPUTS : DAISY_HW_CHANNELS)
#define DAISY_MAPPED_OUTPUTS ((DAISY_NUM_OUTPUTS < DAISY_HW_CHANNELS) ? DAISY_NUM_OUTPUTS : DAISY_HW_CHANNELS)

// Total gen~ channel count (max of inputs and outputs, at least 1)
#define DAISY_MAX_GEN_CHANNELS ((DAISY_NUM_INPUTS > DAISY_NUM_OUTPUTS) ? DAISY_NUM_INPUTS : DAISY_NUM_OUTPUTS)

// Scratch buffer for unused gen~ channels
static float scratch_zero[DAISY_MAX_BLOCK_SIZE] = {0};
static float scratch_discard[DAISY_MAX_BLOCK_SIZE];

// Pointer arrays for gen~ perform()
static float* gen_ins[DAISY_NUM_INPUTS > 0 ? DAISY_NUM_INPUTS : 1];
static float* gen_outs[DAISY_NUM_OUTPUTS > 0 ? DAISY_NUM_OUTPUTS : 1];

// ---------------------------------------------------------------------------
// Audio callback
// ---------------------------------------------------------------------------

static void AudioCallback(const float* const* in, float** out, size_t size) {
    // Lazy-create gen~ state
    if (!genState) {
        genState = wrapper_create(hw.AudioSampleRate(), (long)size);
    }

    // Map hardware inputs to gen~ inputs
    for (int i = 0; i < DAISY_NUM_INPUTS; i++) {
        if (i < DAISY_HW_CHANNELS) {
            gen_ins[i] = const_cast<float*>(in[i]);
        } else {
            gen_ins[i] = scratch_zero;
        }
    }

    // Map gen~ outputs: real hardware channels + scratch for extras
    for (int i = 0; i < DAISY_NUM_OUTPUTS; i++) {
        if (i < DAISY_HW_CHANNELS) {
            gen_outs[i] = out[i];
        } else {
            gen_outs[i] = scratch_discard;
        }
    }

    // Run gen~ DSP
    wrapper_perform(genState, gen_ins, DAISY_NUM_INPUTS,
                    gen_outs, DAISY_NUM_OUTPUTS, (long)size);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

int main(void) {
    // Initialize memory pools before any genlib allocation
    daisy_init_memory();

    // Initialize Daisy Seed hardware
    hw.Init();

    // Configure audio: 48kHz, 48 samples per block (1ms latency)
    hw.SetAudioSampleRate(SaiHandle::Config::SampleRate::SAI_48KHZ);
    hw.SetAudioBlockSize(48);

    // Start non-interleaved audio processing
    hw.StartAudio(AudioCallback);

    // Main loop (audio runs in interrupt)
    for (;;) {
        // User code: read ADCs, update parameters, etc.
        // Example:
        //   float knob = hw.adc.GetFloat(0);
        //   wrapper_set_param(genState, 0, knob);
    }
}
