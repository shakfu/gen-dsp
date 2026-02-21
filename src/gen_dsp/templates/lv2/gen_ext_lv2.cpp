// gen_ext_lv2.cpp - LV2 plugin wrapper for gen~ exports
// This file includes ONLY LV2 headers - genlib is isolated in _ext_lv2.cpp
//
// Implements an LV2 plugin with control ports (parameters) and audio ports.
// Audio port pointers are collected into arrays and passed to wrapper_perform().

#include "lv2/core/lv2.h"
#include "lv2/urid/urid.h"
#include "lv2/state/state.h"
#include "lv2/atom/atom.h"

#ifdef MIDI_ENABLED
#include "lv2/atom/util.h"
#include "lv2/midi/midi.h"
#endif

#include "gen_ext_common_lv2.h"
#include "_ext_lv2.h"

#include <cstring>
#include <cstdlib>
#include <cmath>

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
#define LV2_PORT_AUDIO_END       (LV2_NUM_PARAMS + LV2_NUM_INPUTS + LV2_NUM_OUTPUTS)

#ifdef MIDI_ENABLED
#define LV2_MIDI_PORT_INDEX      LV2_PORT_AUDIO_END
#define LV2_PORT_COUNT           (LV2_PORT_AUDIO_END + 1)
#else
#define LV2_PORT_COUNT           LV2_PORT_AUDIO_END
#endif

// Maximum channel count for static arrays
#define LV2_MAX_CHANNELS 64

// ---------------------------------------------------------------------------
// Polyphony support (NUM_VOICES > 1) or monophonic MIDI helpers
// ---------------------------------------------------------------------------

#ifdef MIDI_ENABLED
#if NUM_VOICES > 1
#include "voice_alloc.h"
#else
static inline float mtof(int note) {
    return 440.0f * powf(2.0f, (note - 69) / 12.0f);
}

static inline void handle_note_on(GenState* state, int key, float velocity) {
    (void)velocity;
#ifdef MIDI_GATE_IDX
    wrapper_set_param(state, MIDI_GATE_IDX, 1.0f);
#endif
#ifdef MIDI_FREQ_IDX
#if MIDI_FREQ_UNIT_HZ
    wrapper_set_param(state, MIDI_FREQ_IDX, mtof(key));
#else
    wrapper_set_param(state, MIDI_FREQ_IDX, (float)key);
#endif
#endif
#ifdef MIDI_VEL_IDX
    wrapper_set_param(state, MIDI_VEL_IDX, velocity);
#endif
}

static inline void handle_note_off(GenState* state) {
#ifdef MIDI_GATE_IDX
    wrapper_set_param(state, MIDI_GATE_IDX, 0.0f);
#endif
}
#endif // NUM_VOICES > 1
#endif // MIDI_ENABLED

// ---------------------------------------------------------------------------
// Plugin state
// ---------------------------------------------------------------------------

// State property URI and magic
#define LV2_GEN_STATE_URI "http://gen-dsp.com/plugins/state#params"

struct Lv2GenPlugin {
#if NUM_VOICES > 1
    VoiceAllocator voiceAlloc;
#else
    GenState*  genState;
#endif
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
    LV2_URID_Map* urid_map;
    LV2_URID   state_params_urid;
    LV2_URID   atom_chunk_urid;
#ifdef MIDI_ENABLED
    LV2_URID   midi_event_urid;
    const LV2_Atom_Sequence* midi_in;
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

    Lv2GenPlugin* plug = (Lv2GenPlugin*)calloc(1, sizeof(Lv2GenPlugin));
    if (!plug) return nullptr;

    plug->sampleRate = (float)sample_rate;
    plug->numInputs  = wrapper_num_inputs();
    plug->numOutputs = wrapper_num_outputs();
    plug->numParams  = wrapper_num_params();

    // Extract URID map feature (needed for state; also used by MIDI)
    for (int i = 0; features[i]; i++) {
        if (!strcmp(features[i]->URI, LV2_URID__map)) {
            plug->urid_map = (LV2_URID_Map*)features[i]->data;
            break;
        }
    }
    if (plug->urid_map) {
        plug->state_params_urid = plug->urid_map->map(
            plug->urid_map->handle, LV2_GEN_STATE_URI);
        plug->atom_chunk_urid = plug->urid_map->map(
            plug->urid_map->handle, LV2_ATOM__Chunk);
#ifdef MIDI_ENABLED
        plug->midi_event_urid = plug->urid_map->map(
            plug->urid_map->handle, LV2_MIDI__MidiEvent);
#endif
    }

    // Create gen~ state with a reasonable default block size
#if NUM_VOICES > 1
    voice_alloc_init(&plug->voiceAlloc, plug->numOutputs, 4096);
    voice_alloc_create_voices(&plug->voiceAlloc, plug->sampleRate, 4096);
#else
    plug->genState = wrapper_create(plug->sampleRate, 4096);
#endif

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
    } else if (port < (uint32_t)LV2_PORT_AUDIO_END) {
        // Audio output port
        int idx = (int)port - LV2_PORT_AUDIO_OUT_START;
        if (idx >= 0 && idx < plug->numOutputs && idx < LV2_MAX_CHANNELS) {
            plug->audio_out[idx] = (float*)data;
        }
    }
#ifdef MIDI_ENABLED
    else if (port == LV2_MIDI_PORT_INDEX) {
        plug->midi_in = (const LV2_Atom_Sequence*)data;
    }
#endif
}

static void
lv2_gen_activate(LV2_Handle instance)
{
    Lv2GenPlugin* plug = (Lv2GenPlugin*)instance;
#if NUM_VOICES > 1
    voice_alloc_reset(&plug->voiceAlloc);
#else
    if (plug->genState) {
        wrapper_reset(plug->genState);
    }
#endif
}

static void
lv2_gen_run(LV2_Handle instance, uint32_t sample_count)
{
    Lv2GenPlugin* plug = (Lv2GenPlugin*)instance;
#if NUM_VOICES > 1
    if (!plug->voiceAlloc.states[0]) return;
#else
    if (!plug->genState) return;
#endif

#ifdef MIDI_ENABLED
    // Process MIDI events from atom sequence
    if (plug->midi_in) {
        LV2_ATOM_SEQUENCE_FOREACH(plug->midi_in, ev) {
            if (ev->body.type == plug->midi_event_urid) {
                const uint8_t* msg = (const uint8_t*)(ev + 1);
                uint32_t size = ev->body.size;
                if (size >= 3) {
                    uint8_t cmd = msg[0] & 0xF0;
                    if (cmd == 0x90 && msg[2] > 0) {
#if NUM_VOICES > 1
                        voice_alloc_note_on(&plug->voiceAlloc, (int)msg[1],
                                            (float)msg[2] / 127.0f);
#else
                        handle_note_on(plug->genState, (int)msg[1],
                                       (float)msg[2] / 127.0f);
#endif
                    } else if (cmd == 0x80 || (cmd == 0x90 && msg[2] == 0)) {
#if NUM_VOICES > 1
                        voice_alloc_note_off(&plug->voiceAlloc, (int)msg[1]);
#else
                        handle_note_off(plug->genState);
#endif
                    }
                }
            }
        }
    }
#endif

    // Apply control port values to gen~ parameters
    for (int i = 0; i < plug->numParams; i++) {
        if (plug->control_in[i]) {
#if NUM_VOICES > 1
            voice_alloc_set_global_param(&plug->voiceAlloc, i, *(plug->control_in[i]));
#else
            wrapper_set_param(plug->genState, i, *(plug->control_in[i]));
#endif
        }
    }

    // Pass audio buffer pointer arrays to gen~ perform
    // audio_in[] and audio_out[] are already populated by connect_port()
    float** ins  = (plug->numInputs > 0)  ? plug->audio_in  : nullptr;
    float** outs = (plug->numOutputs > 0) ? plug->audio_out : nullptr;

#if NUM_VOICES > 1
    voice_alloc_perform(&plug->voiceAlloc,
                        ins, plug->numInputs,
                        outs, plug->numOutputs,
                        (long)sample_count);
#else
    wrapper_perform(plug->genState,
                    ins, plug->numInputs,
                    outs, plug->numOutputs,
                    (long)sample_count);
#endif
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
#if NUM_VOICES > 1
    voice_alloc_destroy(&plug->voiceAlloc);
#else
    if (plug->genState) {
        wrapper_destroy(plug->genState);
    }
#endif
    free(plug);
}

// ---------------------------------------------------------------------------
// State extension
// ---------------------------------------------------------------------------

// 4-byte magic so restore rejects empty/invalid data
static const uint32_t kStateMagic = 0x47445350; // "GDSP"

static LV2_State_Status
lv2_gen_save(LV2_Handle instance,
             LV2_State_Store_Function store,
             LV2_State_Handle handle,
             uint32_t flags,
             const LV2_Feature* const* features)
{
    (void)flags;
    (void)features;
    Lv2GenPlugin* plug = (Lv2GenPlugin*)instance;

    if (!plug->urid_map || !plug->state_params_urid || !plug->atom_chunk_urid)
        return LV2_STATE_ERR_UNKNOWN;

    // Build blob: magic + float per param
    uint32_t blob_size = sizeof(uint32_t) + (uint32_t)plug->numParams * sizeof(float);
    uint8_t* blob = (uint8_t*)malloc(blob_size);
    if (!blob) return LV2_STATE_ERR_UNKNOWN;

    memcpy(blob, &kStateMagic, sizeof(uint32_t));
    float* params = (float*)(blob + sizeof(uint32_t));
    for (int i = 0; i < plug->numParams; i++) {
#if NUM_VOICES > 1
        params[i] = voice_alloc_get_param(&plug->voiceAlloc, i);
#else
        params[i] = plug->genState ? wrapper_get_param(plug->genState, i) : 0.0f;
#endif
    }

    LV2_State_Status status = store(
        handle,
        plug->state_params_urid,
        blob,
        blob_size,
        plug->atom_chunk_urid,
        LV2_STATE_IS_POD | LV2_STATE_IS_PORTABLE);

    free(blob);
    return status;
}

static LV2_State_Status
lv2_gen_restore(LV2_Handle instance,
                LV2_State_Retrieve_Function retrieve,
                LV2_State_Handle handle,
                uint32_t flags,
                const LV2_Feature* const* features)
{
    (void)flags;
    (void)features;
    Lv2GenPlugin* plug = (Lv2GenPlugin*)instance;

    if (!plug->urid_map || !plug->state_params_urid)
        return LV2_STATE_ERR_UNKNOWN;

    size_t size = 0;
    uint32_t type = 0;
    uint32_t valflags = 0;
    const void* data = retrieve(handle, plug->state_params_urid,
                                &size, &type, &valflags);
    if (!data) return LV2_STATE_ERR_NO_PROPERTY;

    // Validate magic header
    if (size < sizeof(uint32_t)) return LV2_STATE_ERR_BAD_TYPE;
    uint32_t magic;
    memcpy(&magic, data, sizeof(uint32_t));
    if (magic != kStateMagic) return LV2_STATE_ERR_BAD_TYPE;

    // Read parameter values
    const float* params = (const float*)((const uint8_t*)data + sizeof(uint32_t));
    uint32_t available = ((uint32_t)size - sizeof(uint32_t)) / sizeof(float);

    for (int i = 0; i < plug->numParams && (uint32_t)i < available; i++) {
#if NUM_VOICES > 1
        voice_alloc_set_global_param(&plug->voiceAlloc, i, params[i]);
#else
        if (plug->genState) {
            wrapper_set_param(plug->genState, i, params[i]);
        }
#endif
    }

    return LV2_STATE_SUCCESS;
}

static const LV2_State_Interface s_state_interface = {
    lv2_gen_save,
    lv2_gen_restore,
};

static const void*
lv2_gen_extension_data(const char* uri)
{
    if (!strcmp(uri, LV2_STATE__interface))
        return &s_state_interface;
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
