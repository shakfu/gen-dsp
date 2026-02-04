// gen_ext_common_max.h - Macro definitions for Max/MSP wrapper
// This file provides name mangling macros similar to the Pd version

#ifndef GEN_EXT_COMMON_MAX_H
#define GEN_EXT_COMMON_MAX_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Class and type naming
#define WRAPPER_CLASS WRAPPER_FUN2(MAX_EXT_NAME, _class)

#define WRAPPER_HIDDEN WRAPPER_FUN2(_, MAX_EXT_NAME)
#define WRAPPER_STRUCT WRAPPER_FUN2(WRAPPER_HIDDEN, _tilde)
#define WRAPPER_T WRAPPER_FUN2(t_, MAX_EXT_NAME)
#define WRAPPER_TYPE WRAPPER_FUN2(WRAPPER_T, _tilde)

// Function naming
#define WRAPPER_NAMESPACE WRAPPER_FUN2(MAX_EXT_NAME, _tilde)
#define EXT_MAIN ext_main
#define WRAPPER_NEW WRAPPER_FUN2(MAX_EXT_NAME, _tilde_new)
#define WRAPPER_FREE WRAPPER_FUN2(MAX_EXT_NAME, _tilde_free)
#define WRAPPER_PERFORM64 WRAPPER_FUN2(MAX_EXT_NAME, _tilde_perform64)
#define WRAPPER_DSP64 WRAPPER_FUN2(MAX_EXT_NAME, _tilde_dsp64)
#define WRAPPER_ANYTHING WRAPPER_FUN2(MAX_EXT_NAME, _tilde_anything)
#define WRAPPER_ASSIST WRAPPER_FUN2(MAX_EXT_NAME, _tilde_assist)
#define WRAPPER_BANG WRAPPER_FUN2(MAX_EXT_NAME, _tilde_bang)
#define WRAPPER_RESET WRAPPER_FUN2(MAX_EXT_NAME, _tilde_reset)

// Message names (can be customized if needed)
#define MESSAGE_RESET reset

#endif // GEN_EXT_COMMON_MAX_H
