// gen_ext_common_circle.h - Macro definitions for Circle wrapper
// This file provides name mangling macros for the Circle backend

#ifndef GEN_EXT_COMMON_CIRCLE_H
#define GEN_EXT_COMMON_CIRCLE_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from Circle)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(CIRCLE_EXT_NAME, _circle)

#endif // GEN_EXT_COMMON_CIRCLE_H
