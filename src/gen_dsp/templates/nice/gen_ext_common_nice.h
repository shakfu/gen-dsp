// gen_ext_common_nice.h - Macro definitions for the nice-plug wrapper
// This file provides name mangling macros for the nice-plug backend

#ifndef GEN_EXT_COMMON_NICE_H
#define GEN_EXT_COMMON_NICE_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from the host side)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(NICE_EXT_NAME, _nice)

#endif // GEN_EXT_COMMON_NICE_H
