// _ext_max.cpp - Gen~ wrapper implementation
// This file includes genlib and the exported code, NO Max headers
// Provides wrapper functions that can be called from the Max side

#include "gen_ext_common_max.h"

// Genlib headers (must NOT be mixed with Max headers)
#include "genlib.h"
#include "genlib_exportfunctions.h"
#include "genlib_ops.h"

// GenState is an opaque handle for CommonState
// Defined here to match the declaration in _ext_max.h
typedef void GenState;

// Buffer support for gen~ (uses genlib's DataInterface)
#include "gen_buffer_max.h"

namespace WRAPPER_NAMESPACE {

// Define buffer instances
#ifdef WRAPPER_BUFFER_NAME_0
    GenBuffer WRAPPER_BUFFER_NAME_0;
#endif
#ifdef WRAPPER_BUFFER_NAME_1
    GenBuffer WRAPPER_BUFFER_NAME_1;
#endif
#ifdef WRAPPER_BUFFER_NAME_2
    GenBuffer WRAPPER_BUFFER_NAME_2;
#endif
#ifdef WRAPPER_BUFFER_NAME_3
    GenBuffer WRAPPER_BUFFER_NAME_3;
#endif
#ifdef WRAPPER_BUFFER_NAME_4
    GenBuffer WRAPPER_BUFFER_NAME_4;
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

// Buffer instance pointers for iteration
static GenBuffer* buffer_instances[] = {
#ifdef WRAPPER_BUFFER_NAME_0
    &WRAPPER_BUFFER_NAME_0,
#endif
#ifdef WRAPPER_BUFFER_NAME_1
    &WRAPPER_BUFFER_NAME_1,
#endif
#ifdef WRAPPER_BUFFER_NAME_2
    &WRAPPER_BUFFER_NAME_2,
#endif
#ifdef WRAPPER_BUFFER_NAME_3
    &WRAPPER_BUFFER_NAME_3,
#endif
#ifdef WRAPPER_BUFFER_NAME_4
    &WRAPPER_BUFFER_NAME_4,
#endif
    nullptr
};

using namespace GEN_EXPORTED_NAME;

// Wrapper function implementations
GenState* wrapper_create(double sr, long bs) {
    return (GenState*)create(sr, bs);
}

void wrapper_destroy(GenState* state) {
    destroy((CommonState*)state);
}

void wrapper_reset(GenState* state) {
    reset((CommonState*)state);
}

void wrapper_perform(GenState* state, double** ins, long numins, double** outs, long numouts, long n) {
    // t_sample is double (no GENLIB_USE_FLOAT32), so we can cast directly
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

double wrapper_param_min(GenState* state, int index) {
    return getparametermin((CommonState*)state, index);
}

double wrapper_param_max(GenState* state, int index) {
    return getparametermax((CommonState*)state, index);
}

char wrapper_param_hasminmax(GenState* state, int index) {
    return getparameterhasminmax((CommonState*)state, index);
}

void wrapper_set_param(GenState* state, int index, double value) {
    setparameter((CommonState*)state, index, value, nullptr);
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

void wrapper_set_buffer(int index, float* data, long frames, long channels) {
    if (index >= 0 && index < WRAPPER_BUFFER_COUNT && buffer_instances[index]) {
        buffer_instances[index]->setData(data, frames, channels);
    }
}

} // namespace WRAPPER_NAMESPACE
