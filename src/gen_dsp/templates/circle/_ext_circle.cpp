// _ext_circle.cpp - Gen~ wrapper implementation for Circle
// This file includes genlib and the exported code, NO Circle headers
// Provides wrapper functions that can be called from the Circle side

#include "gen_ext_common_circle.h"

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

// Genlib headers (must NOT be mixed with Circle headers)
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
// Defined here to match the declaration in _ext_circle.h
typedef void GenState;

// Buffer support for gen~ (uses genlib's DataInterface)
#include "circle_buffer.h"

namespace WRAPPER_NAMESPACE {

// Define buffer instances
#ifdef WRAPPER_BUFFER_NAME_0
    CircleBuffer WRAPPER_BUFFER_NAME_0;
#endif
#ifdef WRAPPER_BUFFER_NAME_1
    CircleBuffer WRAPPER_BUFFER_NAME_1;
#endif
#ifdef WRAPPER_BUFFER_NAME_2
    CircleBuffer WRAPPER_BUFFER_NAME_2;
#endif
#ifdef WRAPPER_BUFFER_NAME_3
    CircleBuffer WRAPPER_BUFFER_NAME_3;
#endif
#ifdef WRAPPER_BUFFER_NAME_4
    CircleBuffer WRAPPER_BUFFER_NAME_4;
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
    // t_sample is float (GENLIB_USE_FLOAT32), so we can cast directly
    perform((CommonState*)state, (t_sample**)ins, numins, (t_sample**)outs, numouts, n);
}

int wrapper_num_inputs() {
    return num_inputs();
}

int wrapper_num_outputs() {
    return num_outputs();
}

int wrapper_num_params() {
    return num_params();
}

const char* wrapper_param_name(GenState* state, int index) {
    return getparametername((CommonState*)state, index);
}

const char* wrapper_param_units(GenState* state, int index) {
    return getparameterunits((CommonState*)state, index);
}

float wrapper_param_min(GenState* state, int index) {
    return (float)getparametermin((CommonState*)state, index);
}

float wrapper_param_max(GenState* state, int index) {
    return (float)getparametermax((CommonState*)state, index);
}

char wrapper_param_hasminmax(GenState* state, int index) {
    return getparameterhasminmax((CommonState*)state, index);
}

void wrapper_set_param(GenState* state, int index, float value) {
    setparameter((CommonState*)state, index, (double)value, nullptr);
}

float wrapper_get_param(GenState* state, int index) {
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
