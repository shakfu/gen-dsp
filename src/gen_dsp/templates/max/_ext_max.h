// _ext_max.h - Minimal interface for Max/MSP wrapper
// Provides forward declarations and wrapper functions without exposing genlib types

#ifndef _EXT_MAX_H
#define _EXT_MAX_H

#include "gen_ext_common_max.h"

// Forward declaration - actual type is CommonState from genlib
// We use void* to avoid including genlib headers
typedef void GenState;

namespace WRAPPER_NAMESPACE {

// Object lifecycle
GenState* wrapper_create(double sr, long bs);
void wrapper_destroy(GenState* state);
void wrapper_reset(GenState* state);

// DSP perform - takes double** (t_sample is double without GENLIB_USE_FLOAT32)
void wrapper_perform(GenState* state, double** ins, long numins, double** outs, long numouts, long n);

// I/O counts
int wrapper_num_inputs();
int wrapper_num_outputs();

// Parameters
int wrapper_num_params();
const char* wrapper_param_name(GenState* state, int index);
const char* wrapper_param_units(GenState* state, int index);
double wrapper_param_min(GenState* state, int index);
double wrapper_param_max(GenState* state, int index);
char wrapper_param_hasminmax(GenState* state, int index);
void wrapper_set_param(GenState* state, int index, double value);

// Buffers
int wrapper_num_buffers();
const char* wrapper_buffer_name(int index);
void wrapper_set_buffer(int index, float* data, long frames, long channels);

} // namespace WRAPPER_NAMESPACE

#endif // _EXT_MAX_H
