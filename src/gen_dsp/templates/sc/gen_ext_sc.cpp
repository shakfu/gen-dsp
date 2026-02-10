// gen_ext_sc.cpp - SuperCollider UGen wrapper for gen~ exports
// This file includes ONLY SC headers - genlib is isolated in _ext_sc.cpp
//
// Input layout (SC UGen inputs are indexed sequentially):
//   Inputs 0..SC_NUM_INPUTS-1:                  audio signal inputs
//   Inputs SC_NUM_INPUTS..+SC_NUM_PARAMS-1:     parameter inputs (control-rate)

#include "SC_PlugIn.h"

#include "gen_ext_common_sc.h"
#include "_ext_sc.h"

using namespace WRAPPER_NAMESPACE;

// Global interface table pointer (required by SC API)
static InterfaceTable* ft;

// Maximum channel count for static arrays
#define SC_MAX_CHANNELS 64

// ---------------------------------------------------------------------------
// UGen struct
// ---------------------------------------------------------------------------

struct ScGenPlugin : public Unit {
    GenState* genState;
};

// Forward declarations
static void ScGenPlugin_Ctor(ScGenPlugin* unit);
static void ScGenPlugin_Dtor(ScGenPlugin* unit);
static void ScGenPlugin_next(ScGenPlugin* unit, int numSamples);

// ---------------------------------------------------------------------------
// Constructor
// ---------------------------------------------------------------------------

static void ScGenPlugin_Ctor(ScGenPlugin* unit) {
    // Create gen~ state (4096 block size for FFT headroom)
    unit->genState = wrapper_create((float)SAMPLERATE, 4096);

    SETCALC(ScGenPlugin_next);

    // Zero first output sample (SC convention)
    for (int i = 0; i < unit->mNumOutputs; i++) {
        OUT0(i) = 0.f;
    }
}

// ---------------------------------------------------------------------------
// Destructor
// ---------------------------------------------------------------------------

static void ScGenPlugin_Dtor(ScGenPlugin* unit) {
    if (unit->genState) {
        wrapper_destroy(unit->genState);
        unit->genState = nullptr;
    }
}

// ---------------------------------------------------------------------------
// Calc function (called each control period)
// ---------------------------------------------------------------------------

static void ScGenPlugin_next(ScGenPlugin* unit, int numSamples) {
    if (!unit->genState) {
        // Output silence on error
        for (int i = 0; i < unit->mNumOutputs; i++) {
            float* out = OUT(i);
            for (int j = 0; j < numSamples; j++) out[j] = 0.f;
        }
        return;
    }

    // Apply parameter inputs (control-rate, after audio inputs)
    for (int i = 0; i < SC_NUM_PARAMS; i++) {
        wrapper_set_param(unit->genState, i, IN0(SC_NUM_INPUTS + i));
    }

    // Build audio I/O buffer arrays
    float* ins[SC_MAX_CHANNELS];
    float* outs[SC_MAX_CHANNELS];

    for (int i = 0; i < SC_NUM_INPUTS; i++) {
        ins[i] = IN(i);
    }
    for (int i = 0; i < SC_NUM_OUTPUTS; i++) {
        outs[i] = OUT(i);
    }

    wrapper_perform(unit->genState,
                    (SC_NUM_INPUTS > 0) ? ins : nullptr, SC_NUM_INPUTS,
                    (SC_NUM_OUTPUTS > 0) ? outs : nullptr, SC_NUM_OUTPUTS,
                    (long)numSamples);
}

// ---------------------------------------------------------------------------
// Entry point -- registers the UGen with the SC server
// For dynamic plugins, PluginLoad always expands to:
//   extern "C" void load(InterfaceTable *inTable)
// ---------------------------------------------------------------------------

PluginLoad(GenDspPlugin) {
    ft = inTable;
    (*ft->fDefineUnit)(
        STR(SC_UGEN_NAME),
        sizeof(ScGenPlugin),
        (UnitCtorFunc)ScGenPlugin_Ctor,
        (UnitDtorFunc)ScGenPlugin_Dtor,
        0
    );
}
