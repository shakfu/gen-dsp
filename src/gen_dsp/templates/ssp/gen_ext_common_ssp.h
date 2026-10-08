// gen_ext_common_ssp.h - Macro definitions for SSP wrapper
// This file provides name mangling macros for the SSP backend

#ifndef GEN_EXT_COMMON_SSP_H
#define GEN_EXT_COMMON_SSP_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from SSP)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(SSP_EXT_NAME, _ssp)

#endif // GEN_EXT_COMMON_SSP_H
