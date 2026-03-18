// _ext_csound.cpp - Gen~ wrapper implementation for Csound opcode
// This file includes genlib and the exported code, NO Csound headers
// Provides wrapper functions that can be called from the Csound bridge

#include "gen_ext_common_csound.h"

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

// Genlib headers (must NOT be mixed with Csound headers)
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
typedef void GenState;

// Buffer support for gen~ (uses genlib's DataInterface)
#include "csound_buffer.h"

namespace WRAPPER_NAMESPACE {

// Define buffer instances
#ifdef WRAPPER_BUFFER_NAME_0
    CsoundBuffer WRAPPER_BUFFER_NAME_0;
#endif
#ifdef WRAPPER_BUFFER_NAME_1
    CsoundBuffer WRAPPER_BUFFER_NAME_1;
#endif
#ifdef WRAPPER_BUFFER_NAME_2
    CsoundBuffer WRAPPER_BUFFER_NAME_2;
#endif
#ifdef WRAPPER_BUFFER_NAME_3
    CsoundBuffer WRAPPER_BUFFER_NAME_3;
#endif
#ifdef WRAPPER_BUFFER_NAME_4
    CsoundBuffer WRAPPER_BUFFER_NAME_4;
#endif

// Include the exported gen~ code
#include GEN_EXPORTED_CPP

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
    nullptr
};

using namespace GEN_EXPORTED_NAME;

static float _silence[8192] = {0};

// Input-to-parameter remapping support
#include "gen_remap_inputs.h"

// Wrapper function implementations
GenState* wrapper_create(float sr, long bs) {
    return (GenState*)create((double)sr, (long)bs);
}

void wrapper_destroy(GenState* state) {
    destroy((CommonState*)state);
}

void wrapper_reset(GenState* state) {
    reset((CommonState*)state);
}

void wrapper_perform(GenState* state, float** ins, long numins, float** outs, long numouts, long n) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    _remap_perform((CommonState*)state, ins, numins, outs, numouts, n);
#else
    long gen_ins = (long)num_inputs();
    float* safe_ins[64];

    if (numins < gen_ins) {
        for (long i = 0; i < gen_ins; i++)
            safe_ins[i] = (i < numins && ins) ? ins[i] : _silence;
        ins = safe_ins;
        numins = gen_ins;
    }

    perform((CommonState*)state, (t_sample**)ins, numins, (t_sample**)outs, numouts, n);
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
    return getparametername((CommonState*)state, index);
}

const char* wrapper_param_units(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return "";
#endif
    return getparameterunits((CommonState*)state, index);
}

float wrapper_param_min(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return 0.0f;
#endif
    return (float)getparametermin((CommonState*)state, index);
}

float wrapper_param_max(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return 1.0f;
#endif
    return (float)getparametermax((CommonState*)state, index);
}

char wrapper_param_hasminmax(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return 0;
#endif
    return getparameterhasminmax((CommonState*)state, index);
}

void wrapper_set_param(GenState* state, int index, float value) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index)) {
        _remap_param_values[_remap_slot_from_param(index)] = value;
        return;
    }
#endif
    setparameter((CommonState*)state, index, (double)value, nullptr);
}

float wrapper_get_param(GenState* state, int index) {
#if defined(REMAP_INPUT_COUNT) && REMAP_INPUT_COUNT > 0
    if (_is_remap_param(index))
        return _remap_param_values[_remap_slot_from_param(index)];
#endif
    t_param val = 0;
    getparameter((CommonState*)state, index, &val);
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
