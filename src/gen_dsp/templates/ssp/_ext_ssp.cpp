// _ext_ssp.cpp - Gen~ wrapper implementation for SSP
// This file includes genlib and the exported code, NO SSP headers
// Provides wrapper functions that can be called from the SSP side

#include "gen_ext_common_ssp.h"

#include <atomic>  // gen_remap_inputs.h, included inside a namespace below

// genlib_ops.h defines inline exp2(float) and trunc(float) inside
// #ifndef WIN32, which conflict with std::exp2/std::trunc pulled into
// the global namespace by <cmath> on modern compilers. We define WIN32
// to skip these. We also define GENLIB_NO_DENORM_TEST to avoid the
// WIN32 path that redefines __FLT_MIN__ (creating a circular macro
// with <cfloat>'s FLT_MIN).
#ifndef WIN32
#define WIN32
#define _GENEXT_UNDEF_WIN32
#endif
#ifndef GENLIB_NO_DENORM_TEST
#define GENLIB_NO_DENORM_TEST
#define _GENEXT_UNDEF_DENORM
#endif

// Genlib headers (must NOT be mixed with SSP headers)
#include "genlib.h"
#include "genlib_exportfunctions.h"
#include "genlib_ops.h"

#ifdef _GENEXT_UNDEF_WIN32
#undef WIN32
#undef _GENEXT_UNDEF_WIN32
#endif
#ifdef _GENEXT_UNDEF_DENORM
#undef GENLIB_NO_DENORM_TEST
#undef _GENEXT_UNDEF_DENORM
#endif

// GenState is an opaque handle for CommonState
// Defined here to match the declaration in _ext_ssp.h
typedef void GenState;

// Buffer support for gen~ (uses genlib's DataInterface)
#include "ssp_buffer.h"

namespace WRAPPER_NAMESPACE {

// An instance: the gen~ state and its own buffers. The exported code reaches it through
// CommonState::api, which genlib leaves to the host.
struct SspInstance {
    CommonState* gen = nullptr;
    SspBufferSlot buffers[WRAPPER_BUFFER_COUNT > 0 ? WRAPPER_BUFFER_COUNT : 1];
    SspBufferView views[WRAPPER_BUFFER_COUNT > 0 ? WRAPPER_BUFFER_COUNT : 1];  // audio thread
};

// ssp_buffer_names.h renames each buffer the exported code names, e.g. `sample`, to
// SSP_BUFFER(k). That reads `__commonstate`, so it works inside State's methods, which is
// where gen~ code uses buffers; elsewhere it fails to compile. create() runs reset()
// before api is set, so reset() must not use a buffer.
#define SSP_BUFFER(k) (static_cast<SspInstance*>(__commonstate.api)->views[k])

// Include the exported gen~ code
#include "ssp_buffer_names.h"
#include GEN_EXPORTED_CPP
#define SSP_BUFFER_NAMES_END
#include "ssp_buffer_names.h"
#undef SSP_BUFFER

// Buffer name array for iteration
static const char* buffer_names[] = {
#ifdef WRAPPER_BUFFER_NAME_0
    STR(WRAPPER_BUFFER_NAME_0),
#endif
#ifdef WRAPPER_BUFFER_NAME_1
    STR(WRAPPER_BUFFER_NAME_1),
#endif
#ifdef WRAPPER_BUFFER_NAME_2
    STR(WRAPPER_BUFFER_NAME_2),
#endif
#ifdef WRAPPER_BUFFER_NAME_3
    STR(WRAPPER_BUFFER_NAME_3),
#endif
#ifdef WRAPPER_BUFFER_NAME_4
    STR(WRAPPER_BUFFER_NAME_4),
#endif
#ifdef WRAPPER_BUFFER_NAME_5
    STR(WRAPPER_BUFFER_NAME_5),
#endif
#ifdef WRAPPER_BUFFER_NAME_6
    STR(WRAPPER_BUFFER_NAME_6),
#endif
#ifdef WRAPPER_BUFFER_NAME_7
    STR(WRAPPER_BUFFER_NAME_7),
#endif
    nullptr
};

using namespace GEN_EXPORTED_NAME;

static float _silence[8192] = {0};

// Input-to-parameter remapping support
#include "gen_remap_inputs.h"

static CommonState* gen_of(GenState* state) {
    return static_cast<SspInstance*>(state)->gen;
}

// Wrapper function implementations
GenState* wrapper_create(float sr, long bs) {
    auto* inst = new SspInstance;
    inst->gen = (CommonState*)create((double)sr, (long)bs);
    inst->gen->api = inst;
    _remap_attach(inst->gen, bs);
    return inst;
}

void wrapper_destroy(GenState* state) {
    _remap_detach(gen_of(state));
    destroy(gen_of(state));
    delete static_cast<SspInstance*>(state);
}

void wrapper_reset(GenState* state) {
    reset(gen_of(state));
}

long wrapper_buffer_load(GenState* state, int index, const char* path) {
    if (index < 0 || index >= WRAPPER_BUFFER_COUNT) return -1;
    SspBufferData* d = ssp_read_wav(path);
    if (!d) return -1;
    long frames = d->frames;
    static_cast<SspInstance*>(state)->buffers[index].publish(d);
    return frames;
}

void wrapper_perform(GenState* state, float** ins, long numins, float** outs, long numouts, long n) {
    auto* inst = static_cast<SspInstance*>(state);
    for (int k = 0; k < WRAPPER_BUFFER_COUNT; k++) inst->views[k].bind(inst->buffers[k].adopt());
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    _remap_perform(gen_of(state), ins, numins, outs, numouts, n);
#else
    // t_sample is float (GENLIB_USE_FLOAT32), so we can cast directly
    long gen_ins = (long)num_inputs();
    float* safe_ins[64];

    if (numins < gen_ins) {
        for (long i = 0; i < gen_ins; i++)
            safe_ins[i] = (i < numins && ins) ? ins[i] : _silence;
        ins = safe_ins;
        numins = gen_ins;
    }

    perform(gen_of(state), (t_sample**)ins, numins, (t_sample**)outs, numouts, n);
#endif
}

int wrapper_num_inputs() {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    return num_inputs() - REMAP_INPUT_COUNT;
#else
    return num_inputs();
#endif
}

int wrapper_num_outputs() {
    return num_outputs();
}

int wrapper_num_params() {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    return _remap_total_params();
#else
    return num_params();
#endif
}

const char* wrapper_param_name(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return _remap_param_names[_remap_slot_from_param(index)];
#endif
    return getparametername(gen_of(state), index);
}

const char* wrapper_param_units(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return "";
#endif
    return getparameterunits(gen_of(state), index);
}

float wrapper_param_min(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return 0.0f;
#endif
    return (float)getparametermin(gen_of(state), index);
}

float wrapper_param_max(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return 1.0f;
#endif
    return (float)getparametermax(gen_of(state), index);
}

char wrapper_param_hasminmax(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return 0;
#endif
    return getparameterhasminmax(gen_of(state), index);
}

void wrapper_set_param(GenState* state, int index, float value) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index)) {
        _remap_values(gen_of(state))[_remap_slot_from_param(index)] = value;
        return;
    }
#endif
    setparameter(gen_of(state), index, (double)value, nullptr);
}

float wrapper_get_param(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return _remap_values(gen_of(state))[_remap_slot_from_param(index)];
#endif
    t_param val = 0;
    getparameter(gen_of(state), index, &val);
    return (float)val;
}

int wrapper_num_buffers() {
    return WRAPPER_BUFFER_COUNT;
}

const char* wrapper_buffer_name(int index) {
    if (index >= 0 && index < WRAPPER_BUFFER_COUNT) {
        return buffer_names[index];
    }
    return nullptr;
}

} // namespace WRAPPER_NAMESPACE
