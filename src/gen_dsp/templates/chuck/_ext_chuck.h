// _ext_chuck.h - Minimal interface for ChucK chugin wrapper
// Provides forward declarations and wrapper functions without exposing genlib types

#ifndef _EXT_CHUCK_H
#define _EXT_CHUCK_H

#include "gen_ext_common_chuck.h"

// Forward declaration - actual type is CommonState from genlib
// We use void* to avoid including genlib headers
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

// Buffers
int wrapper_num_buffers();
const char* wrapper_buffer_name(int index);
int wrapper_load_buffer(int index, const char* path);

} // namespace WRAPPER_NAMESPACE

#endif // _EXT_CHUCK_H
