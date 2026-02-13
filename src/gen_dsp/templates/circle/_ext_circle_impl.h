// _ext_circle_impl.h - Per-node wrapper interface for Circle chain mode
// Included by generated _ext_circle_N.h with CIRCLE_EXT_NAME pre-defined
//
// Each chain node gets its own namespace (CIRCLE_EXT_NAME ## _circle)
// so multiple gen~ exports can coexist without symbol collisions.

#ifndef _EXT_CIRCLE_IMPL_GUARD
// Allow multiple includes (each with different CIRCLE_EXT_NAME)
#endif

#include "gen_ext_common_circle.h"

// Forward declaration - actual type is CommonState from genlib
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

} // namespace WRAPPER_NAMESPACE
