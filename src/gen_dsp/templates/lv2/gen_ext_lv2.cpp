// gen_ext_lv2.cpp - LV2 plugin wrapper for gen~ exports
// This file includes ONLY LV2 headers - genlib is isolated in _ext_lv2.cpp
//
// Implements an LV2 plugin with control ports (parameters) and audio ports.
// Audio port pointers are collected into arrays and passed to wrapper_perform().

#include "lv2/core/lv2.h"

#include "gen_ext_common_lv2.h"
#include "_ext_lv2.h"

#include <cstring>
#include <cstdlib>

using namespace WRAPPER_NAMESPACE;

// ---------------------------------------------------------------------------
// Port index layout (compile-time constants from CMake)
// ---------------------------------------------------------------------------
// Ports 0..LV2_NUM_PARAMS-1              = ControlPort + InputPort (parameters)
// Ports LV2_NUM_PARAMS..+LV2_NUM_INPUTS  = AudioPort + InputPort
// Ports above..+LV2_NUM_OUTPUTS          = AudioPort + OutputPort

#define LV2_PORT_PARAM_START     0
#define LV2_PORT_AUDIO_IN_START  LV2_NUM_PARAMS
#define LV2_PORT_AUDIO_OUT_START (LV2_NUM_PARAMS + LV2_NUM_INPUTS)
#define LV2_PORT_COUNT           (LV2_NUM_PARAMS + LV2_NUM_INPUTS + LV2_NUM_OUTPUTS)

// Maximum channel count for static arrays
#define LV2_MAX_CHANNELS 64

// ---------------------------------------------------------------------------
// Plugin state
// ---------------------------------------------------------------------------

struct Lv2GenPlugin {
    GenState*  genState;
    float      sampleRate;
    int        numInputs;
    int        numOutputs;
    int        numParams;
    float*     audio_in[LV2_MAX_CHANNELS];
    float*     audio_out[LV2_MAX_CHANNELS];
#if LV2_NUM_PARAMS > 0
    const float* control_in[LV2_NUM_PARAMS];
#else
    const float* control_in[1];  // placeholder to avoid zero-length array
#endif
};

// ---------------------------------------------------------------------------
// LV2 descriptor callbacks
// ---------------------------------------------------------------------------

static LV2_Handle
lv2_gen_instantiate(const LV2_Descriptor* descriptor,
                    double sample_rate,
                    const char* bundle_path,
                    const LV2_Feature* const* features)
{
    (void)descriptor;
    (void)bundle_path;
    (void)features;

    Lv2GenPlugin* plug = (Lv2GenPlugin*)calloc(1, sizeof(Lv2GenPlugin));
    if (!plug) return nullptr;

    plug->sampleRate = (float)sample_rate;
    plug->numInputs  = wrapper_num_inputs();
    plug->numOutputs = wrapper_num_outputs();
    plug->numParams  = wrapper_num_params();

    // Create gen~ state with a reasonable default block size
    plug->genState = wrapper_create(plug->sampleRate, 4096);

    return (LV2_Handle)plug;
}

static void
lv2_gen_connect_port(LV2_Handle instance, uint32_t port, void* data)
{
    Lv2GenPlugin* plug = (Lv2GenPlugin*)instance;

    if (port < (uint32_t)LV2_PORT_AUDIO_IN_START) {
        // Control port (parameter)
        int idx = (int)port - LV2_PORT_PARAM_START;
        if (idx >= 0 && idx < plug->numParams) {
            plug->control_in[idx] = (const float*)data;
        }
    } else if (port < (uint32_t)LV2_PORT_AUDIO_OUT_START) {
        // Audio input port
        int idx = (int)port - LV2_PORT_AUDIO_IN_START;
        if (idx >= 0 && idx < plug->numInputs && idx < LV2_MAX_CHANNELS) {
            plug->audio_in[idx] = (float*)data;
        }
    } else {
        // Audio output port
        int idx = (int)port - LV2_PORT_AUDIO_OUT_START;
        if (idx >= 0 && idx < plug->numOutputs && idx < LV2_MAX_CHANNELS) {
            plug->audio_out[idx] = (float*)data;
        }
    }
}

static void
lv2_gen_activate(LV2_Handle instance)
{
    Lv2GenPlugin* plug = (Lv2GenPlugin*)instance;
    if (plug->genState) {
        wrapper_reset(plug->genState);
    }
}

static void
lv2_gen_run(LV2_Handle instance, uint32_t sample_count)
{
    Lv2GenPlugin* plug = (Lv2GenPlugin*)instance;
    if (!plug->genState) return;

    // Apply control port values to gen~ parameters
    for (int i = 0; i < plug->numParams; i++) {
        if (plug->control_in[i]) {
            wrapper_set_param(plug->genState, i, *(plug->control_in[i]));
        }
    }

    // Pass audio buffer pointer arrays to gen~ perform
    // audio_in[] and audio_out[] are already populated by connect_port()
    float** ins  = (plug->numInputs > 0)  ? plug->audio_in  : nullptr;
    float** outs = (plug->numOutputs > 0) ? plug->audio_out : nullptr;

    wrapper_perform(plug->genState,
                    ins, plug->numInputs,
                    outs, plug->numOutputs,
                    (long)sample_count);
}

static void
lv2_gen_deactivate(LV2_Handle instance)
{
    (void)instance;
}

static void
lv2_gen_cleanup(LV2_Handle instance)
{
    Lv2GenPlugin* plug = (Lv2GenPlugin*)instance;
    if (plug->genState) {
        wrapper_destroy(plug->genState);
    }
    free(plug);
}

static const void*
lv2_gen_extension_data(const char* uri)
{
    (void)uri;
    return nullptr;
}

// ---------------------------------------------------------------------------
// Descriptor and entry point
// ---------------------------------------------------------------------------

#define LV2_GEN_URI "http://gen-dsp.com/plugins/" STR(LV2_EXT_NAME)

static const LV2_Descriptor s_descriptor = {
    LV2_GEN_URI,
    lv2_gen_instantiate,
    lv2_gen_connect_port,
    lv2_gen_activate,
    lv2_gen_run,
    lv2_gen_deactivate,
    lv2_gen_cleanup,
    lv2_gen_extension_data,
};

LV2_SYMBOL_EXPORT const LV2_Descriptor*
lv2_descriptor(uint32_t index)
{
    if (index == 0) return &s_descriptor;
    return nullptr;
}
