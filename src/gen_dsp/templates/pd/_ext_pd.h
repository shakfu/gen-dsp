// _ext_pd.h - Minimal interface for PD graph wrapper
// Provides forward declarations and wrapper functions without exposing graph types

#ifndef _EXT_PD_H
#define _EXT_PD_H

#include "gen_ext_common_pd.h"

// Forward declaration - actual type is graph state
// We use void* to avoid including graph headers
typedef void GenState;

namespace WRAPPER_NAMESPACE {

// Object lifecycle
GenState* wrapper_create(float sr, long bs);
void wrapper_destroy(GenState* state);
void wrapper_reset(GenState* state);

// DSP perform - takes float** (GENLIB_USE_FLOAT32 so t_sample = float)
void wrapper_perform(GenState* state, float** ins, long numins, float** outs, long numouts, long n);

// I/O counts
int wrapper_num_inputs();
int wrapper_num_outputs();

// Parameters
int wrapper_num_params();
const char* wrapper_param_name(GenState* state, int index);
const char* wrapper_param_units(GenState* state, int index);
float wrapper_param_min(GenState* state, int index);
float wrapper_param_max(GenState* state, int index);
char wrapper_param_hasminmax(GenState* state, int index);
void wrapper_set_param(GenState* state, int index, float value);
float wrapper_get_param(GenState* state, int index);

} // namespace WRAPPER_NAMESPACE

#endif // _EXT_PD_H
