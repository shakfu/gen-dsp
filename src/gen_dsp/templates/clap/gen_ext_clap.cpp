// gen_ext_clap.cpp - CLAP plugin wrapper for gen~ exports
// This file includes ONLY CLAP headers - genlib is isolated in _ext_clap.cpp
//
// Implements a CLAP plugin with audio-ports and params extensions.
// CLAP's non-interleaved float** layout matches gen~'s exactly,
// so the process function passes buffers directly (zero copy).

#include <clap/clap.h>

#include "gen_ext_common_clap.h"
#include "_ext_clap.h"

#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <cmath>

using namespace WRAPPER_NAMESPACE;

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

struct ClapGenPlugin {
    clap_plugin_t       plugin;
    const clap_host_t*  host;
#if NUM_VOICES > 1
    VoiceAllocator      voiceAlloc;
#else
    GenState*           genState;
#endif
    float               sampleRate;
    uint32_t            maxFrames;
    int                 numInputs;
    int                 numOutputs;
    int                 numParams;
    bool                active;
};

// ---------------------------------------------------------------------------
// Audio ports extension
// ---------------------------------------------------------------------------

static uint32_t audio_ports_count(const clap_plugin_t* plugin, bool is_input) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
    if (is_input) {
        return plug->numInputs > 0 ? 1 : 0;
    }
    return 1;  // always 1 output port
}

static bool audio_ports_get(const clap_plugin_t* plugin,
                            uint32_t index,
                            bool is_input,
                            clap_audio_port_info_t* info) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
    if (index != 0) return false;

    memset(info, 0, sizeof(clap_audio_port_info_t));
    info->id = is_input ? 0 : 1;
    info->in_place_pair = CLAP_INVALID_ID;
    info->flags = CLAP_AUDIO_PORT_IS_MAIN;
    info->port_type = nullptr;  // let host decide

    if (is_input) {
        if (plug->numInputs <= 0) return false;
        strncpy(info->name, "Input", sizeof(info->name) - 1);
        info->channel_count = (uint32_t)plug->numInputs;
    } else {
        strncpy(info->name, "Output", sizeof(info->name) - 1);
        info->channel_count = (uint32_t)plug->numOutputs;
    }
    return true;
}

static const clap_plugin_audio_ports_t s_audio_ports = {
    .count = audio_ports_count,
    .get   = audio_ports_get,
};

// ---------------------------------------------------------------------------
// Params extension
// ---------------------------------------------------------------------------

static uint32_t params_count(const clap_plugin_t* plugin) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
    return (uint32_t)plug->numParams;
}

static bool params_get_info(const clap_plugin_t* plugin,
                            uint32_t param_index,
                            clap_param_info_t* info) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
    if ((int)param_index >= plug->numParams) return false;

    memset(info, 0, sizeof(clap_param_info_t));
    info->id = param_index;
    info->flags = CLAP_PARAM_IS_AUTOMATABLE;

    // Get metadata from gen~ wrapper
#if NUM_VOICES > 1
    GenState* queryState = plug->voiceAlloc.states[0];
#else
    GenState* queryState = plug->genState;
#endif
    if (queryState) {
        const char* pname = wrapper_param_name(queryState, (int)param_index);
        if (pname) {
            strncpy(info->name, pname, sizeof(info->name) - 1);
        }

        const char* punits = wrapper_param_units(queryState, (int)param_index);
        if (punits) {
            strncpy(info->module, punits, sizeof(info->module) - 1);
        }

        if (wrapper_param_hasminmax(queryState, (int)param_index)) {
            info->min_value = (double)wrapper_param_min(queryState, (int)param_index);
            info->max_value = (double)wrapper_param_max(queryState, (int)param_index);
        } else {
            info->min_value = 0.0;
            info->max_value = 1.0;
        }

        double def = (double)wrapper_get_param(queryState, (int)param_index);
        // Clamp default to declared range -- gen~ initial values may exceed it
        if (def < info->min_value) def = info->min_value;
        if (def > info->max_value) def = info->max_value;
        info->default_value = def;
    } else {
        snprintf(info->name, sizeof(info->name), "Param %u", param_index);
        info->min_value = 0.0;
        info->max_value = 1.0;
        info->default_value = 0.0;
    }

    return true;
}

static bool params_get_value(const clap_plugin_t* plugin,
                             clap_id param_id,
                             double* value) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
    int idx = (int)param_id;
    if (idx < 0 || idx >= plug->numParams) return false;
#if NUM_VOICES > 1
    *value = (double)voice_alloc_get_param(&plug->voiceAlloc, idx);
#else
    if (!plug->genState) return false;
    *value = (double)wrapper_get_param(plug->genState, idx);
#endif
    return true;
}

static bool params_value_to_text(const clap_plugin_t* plugin,
                                 clap_id param_id,
                                 double value,
                                 char* display,
                                 uint32_t size) {
    (void)plugin;
    (void)param_id;
    snprintf(display, size, "%.4f", value);
    return true;
}

static bool params_text_to_value(const clap_plugin_t* plugin,
                                 clap_id param_id,
                                 const char* display,
                                 double* value) {
    (void)plugin;
    (void)param_id;
    char* end = nullptr;
    double v = strtod(display, &end);
    if (end == display) return false;
    *value = v;
    return true;
}

static void params_flush(const clap_plugin_t* plugin,
                         const clap_input_events_t* in,
                         const clap_output_events_t* out) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
    (void)out;

    uint32_t count = in->size(in);
    for (uint32_t i = 0; i < count; i++) {
        const clap_event_header_t* hdr = in->get(in, i);
        if (hdr->space_id != CLAP_CORE_EVENT_SPACE_ID) continue;
        if (hdr->type == CLAP_EVENT_PARAM_VALUE) {
            const clap_event_param_value_t* ev = (const clap_event_param_value_t*)hdr;
            int idx = (int)ev->param_id;
            if (idx >= 0 && idx < plug->numParams) {
#if NUM_VOICES > 1
                voice_alloc_set_global_param(&plug->voiceAlloc, idx, (float)ev->value);
#else
                wrapper_set_param(plug->genState, idx, (float)ev->value);
#endif
            }
        }
#ifdef MIDI_ENABLED
        else if (hdr->type == CLAP_EVENT_NOTE_ON) {
            const clap_event_note_t* ev = (const clap_event_note_t*)hdr;
#if NUM_VOICES > 1
            voice_alloc_note_on(&plug->voiceAlloc, ev->key, (float)ev->velocity);
#else
            handle_note_on(plug->genState, ev->key, (float)ev->velocity);
#endif
        }
        else if (hdr->type == CLAP_EVENT_NOTE_OFF) {
            const clap_event_note_t* ev = (const clap_event_note_t*)hdr;
#if NUM_VOICES > 1
            voice_alloc_note_off(&plug->voiceAlloc, ev->key);
#else
            handle_note_off(plug->genState);
#endif
        }
#endif
    }
}

static const clap_plugin_params_t s_params = {
    .count          = params_count,
    .get_info       = params_get_info,
    .get_value      = params_get_value,
    .value_to_text  = params_value_to_text,
    .text_to_value  = params_text_to_value,
    .flush          = params_flush,
};

// ---------------------------------------------------------------------------
// Note ports extension (MIDI input for instruments)
// ---------------------------------------------------------------------------

#ifdef MIDI_ENABLED
static uint32_t note_ports_count(const clap_plugin_t* plugin, bool is_input) {
    (void)plugin;
    return is_input ? 1 : 0;
}

static bool note_ports_get(const clap_plugin_t* plugin, uint32_t index,
                           bool is_input, clap_note_port_info_t* info) {
    (void)plugin;
    if (!is_input || index != 0) return false;
    memset(info, 0, sizeof(clap_note_port_info_t));
    info->id = 0;
    info->supported_dialects = CLAP_NOTE_DIALECT_CLAP | CLAP_NOTE_DIALECT_MIDI;
    info->preferred_dialect = CLAP_NOTE_DIALECT_CLAP;
    strncpy(info->name, "Note Input", sizeof(info->name) - 1);
    return true;
}

static const clap_plugin_note_ports_t s_note_ports = {
    .count = note_ports_count,
    .get   = note_ports_get,
};
#endif // MIDI_ENABLED

// ---------------------------------------------------------------------------
// Plugin lifecycle
// ---------------------------------------------------------------------------

static bool clap_gen_init(const clap_plugin_t* plugin) {
    (void)plugin;
    return true;
}

static void clap_gen_destroy(const clap_plugin_t* plugin) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
#if NUM_VOICES > 1
    voice_alloc_destroy(&plug->voiceAlloc);
#else
    if (plug->genState) {
        wrapper_destroy(plug->genState);
        plug->genState = nullptr;
    }
#endif
    free(plug);
}

static bool clap_gen_activate(const clap_plugin_t* plugin,
                              double sample_rate,
                              uint32_t min_frames,
                              uint32_t max_frames) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
    (void)min_frames;

    plug->sampleRate = (float)sample_rate;
    plug->maxFrames = max_frames;

#if NUM_VOICES > 1
    voice_alloc_create_voices(&plug->voiceAlloc, plug->sampleRate, (long)max_frames);
    plug->active = (plug->voiceAlloc.states[0] != nullptr);
#else
    if (plug->genState) {
        wrapper_destroy(plug->genState);
    }
    plug->genState = wrapper_create(plug->sampleRate, (long)max_frames);
    plug->active = (plug->genState != nullptr);
#endif
    return plug->active;
}

static void clap_gen_deactivate(const clap_plugin_t* plugin) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
    // Keep genState alive so params remain queryable after deactivation.
    // It will be destroyed/recreated on next activate() or in destroy().
    plug->active = false;
}

static bool clap_gen_start_processing(const clap_plugin_t* plugin) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
#if NUM_VOICES > 1
    return plug->active && plug->voiceAlloc.states[0] != nullptr;
#else
    return plug->active && plug->genState != nullptr;
#endif
}

static void clap_gen_stop_processing(const clap_plugin_t* plugin) {
    (void)plugin;
}

static void clap_gen_reset(const clap_plugin_t* plugin) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;
#if NUM_VOICES > 1
    voice_alloc_reset(&plug->voiceAlloc);
#else
    if (plug->genState) {
        wrapper_reset(plug->genState);
    }
#endif
}

// ---------------------------------------------------------------------------
// Process (zero-copy)
// ---------------------------------------------------------------------------

static clap_process_status clap_gen_process(const clap_plugin_t* plugin,
                                            const clap_process_t* process) {
    ClapGenPlugin* plug = (ClapGenPlugin*)plugin->plugin_data;

#if NUM_VOICES > 1
    if (!plug->voiceAlloc.states[0]) return CLAP_PROCESS_ERROR;
#else
    if (!plug->genState) return CLAP_PROCESS_ERROR;
#endif

    uint32_t nframes = process->frames_count;

    // Handle parameter events
    const clap_input_events_t* in_events = process->in_events;
    uint32_t event_count = in_events->size(in_events);
    for (uint32_t i = 0; i < event_count; i++) {
        const clap_event_header_t* hdr = in_events->get(in_events, i);
        if (hdr->space_id != CLAP_CORE_EVENT_SPACE_ID) continue;
        if (hdr->type == CLAP_EVENT_PARAM_VALUE) {
            const clap_event_param_value_t* ev = (const clap_event_param_value_t*)hdr;
            int idx = (int)ev->param_id;
            if (idx >= 0 && idx < plug->numParams) {
#if NUM_VOICES > 1
                voice_alloc_set_global_param(&plug->voiceAlloc, idx, (float)ev->value);
#else
                wrapper_set_param(plug->genState, idx, (float)ev->value);
#endif
            }
        }
#ifdef MIDI_ENABLED
        else if (hdr->type == CLAP_EVENT_NOTE_ON) {
            const clap_event_note_t* ev = (const clap_event_note_t*)hdr;
#if NUM_VOICES > 1
            voice_alloc_note_on(&plug->voiceAlloc, ev->key, (float)ev->velocity);
#else
            handle_note_on(plug->genState, ev->key, (float)ev->velocity);
#endif
        }
        else if (hdr->type == CLAP_EVENT_NOTE_OFF) {
            const clap_event_note_t* ev = (const clap_event_note_t*)hdr;
#if NUM_VOICES > 1
            voice_alloc_note_off(&plug->voiceAlloc, ev->key);
#else
            handle_note_off(plug->genState);
#endif
        }
#endif
    }

    // Get input buffers (zero-copy: CLAP data32 is already float**)
    float** ins = nullptr;
    if (plug->numInputs > 0 && process->audio_inputs_count > 0) {
        ins = process->audio_inputs[0].data32;
    }

    // Get output buffers (zero-copy)
    float** outs = nullptr;
    if (plug->numOutputs > 0 && process->audio_outputs_count > 0) {
        outs = process->audio_outputs[0].data32;
    }

    if (!outs) {
        return CLAP_PROCESS_ERROR;
    }

#if NUM_VOICES > 1
    voice_alloc_perform(&plug->voiceAlloc,
                        ins, plug->numInputs,
                        outs, plug->numOutputs,
                        (long)nframes);
#else
    wrapper_perform(plug->genState,
                    ins, plug->numInputs,
                    outs, plug->numOutputs,
                    (long)nframes);
#endif

    return CLAP_PROCESS_CONTINUE;
}

// ---------------------------------------------------------------------------
// Extensions
// ---------------------------------------------------------------------------

static const void* clap_gen_get_extension(const clap_plugin_t* plugin,
                                          const char* id) {
    (void)plugin;
    if (strcmp(id, CLAP_EXT_AUDIO_PORTS) == 0) return &s_audio_ports;
    if (strcmp(id, CLAP_EXT_PARAMS) == 0)      return &s_params;
#ifdef MIDI_ENABLED
    if (strcmp(id, CLAP_EXT_NOTE_PORTS) == 0)  return &s_note_ports;
#endif
    return nullptr;
}

static void clap_gen_on_main_thread(const clap_plugin_t* plugin) {
    (void)plugin;
}

// ---------------------------------------------------------------------------
// Plugin descriptor
// ---------------------------------------------------------------------------

#define CLAP_GEN_PLUGIN_ID "com.gen-dsp." STR(CLAP_EXT_NAME)

#if CLAP_NUM_INPUTS > 0
static const char* s_features[] = {
    CLAP_PLUGIN_FEATURE_AUDIO_EFFECT,
    nullptr,
};
#else
static const char* s_features[] = {
    CLAP_PLUGIN_FEATURE_INSTRUMENT,
    nullptr,
};
#endif

static const clap_plugin_descriptor_t s_descriptor = {
    .clap_version = CLAP_VERSION,
    .id           = CLAP_GEN_PLUGIN_ID,
    .name         = STR(CLAP_EXT_NAME),
    .vendor       = "gen-dsp",
    .url          = "",
    .manual_url   = "",
    .support_url  = "",
    .version      = GEN_EXT_VERSION,
    .description  = "Generated from gen~ export by gen-dsp",
    .features     = s_features,
};

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

static uint32_t factory_get_plugin_count(const clap_plugin_factory_t* factory) {
    (void)factory;
    return 1;
}

static const clap_plugin_descriptor_t* factory_get_plugin_descriptor(
    const clap_plugin_factory_t* factory,
    uint32_t index) {
    (void)factory;
    if (index != 0) return nullptr;
    return &s_descriptor;
}

static const clap_plugin_t* factory_create_plugin(
    const clap_plugin_factory_t* factory,
    const clap_host_t* host,
    const char* plugin_id) {
    (void)factory;

    if (strcmp(plugin_id, s_descriptor.id) != 0) {
        return nullptr;
    }

    ClapGenPlugin* plug = (ClapGenPlugin*)calloc(1, sizeof(ClapGenPlugin));
    if (!plug) return nullptr;

    plug->host       = host;
    plug->sampleRate = 44100.0f;
    plug->maxFrames  = 1024;
    plug->numInputs  = wrapper_num_inputs();
    plug->numOutputs = wrapper_num_outputs();
    plug->numParams  = wrapper_num_params();
    plug->active     = false;

    // Create gen state eagerly so params are queryable before activation
#if NUM_VOICES > 1
    voice_alloc_init(&plug->voiceAlloc, plug->numOutputs, (long)plug->maxFrames);
    voice_alloc_create_voices(&plug->voiceAlloc, plug->sampleRate, (long)plug->maxFrames);
#else
    plug->genState   = wrapper_create(plug->sampleRate, (long)plug->maxFrames);
#endif

    plug->plugin.desc            = &s_descriptor;
    plug->plugin.plugin_data     = plug;
    plug->plugin.init            = clap_gen_init;
    plug->plugin.destroy         = clap_gen_destroy;
    plug->plugin.activate        = clap_gen_activate;
    plug->plugin.deactivate      = clap_gen_deactivate;
    plug->plugin.start_processing = clap_gen_start_processing;
    plug->plugin.stop_processing = clap_gen_stop_processing;
    plug->plugin.reset           = clap_gen_reset;
    plug->plugin.process         = clap_gen_process;
    plug->plugin.get_extension   = clap_gen_get_extension;
    plug->plugin.on_main_thread  = clap_gen_on_main_thread;

    return &plug->plugin;
}

static const clap_plugin_factory_t s_factory = {
    .get_plugin_count      = factory_get_plugin_count,
    .get_plugin_descriptor = factory_get_plugin_descriptor,
    .create_plugin         = factory_create_plugin,
};

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

static bool entry_init(const char* path) {
    (void)path;
    return true;
}

static void entry_deinit(void) {
}

static const void* entry_get_factory(const char* factory_id) {
    if (strcmp(factory_id, CLAP_PLUGIN_FACTORY_ID) == 0) {
        return &s_factory;
    }
    return nullptr;
}

extern "C" CLAP_EXPORT const clap_plugin_entry_t clap_entry = {
    .clap_version = CLAP_VERSION,
    .init         = entry_init,
    .deinit       = entry_deinit,
    .get_factory  = entry_get_factory,
};
