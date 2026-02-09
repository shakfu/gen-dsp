// gen_ext_common_au.h - Macro definitions for AudioUnit wrapper
// This file provides name mangling macros for the AU backend

#ifndef GEN_EXT_COMMON_AU_H
#define GEN_EXT_COMMON_AU_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from AudioUnit)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(AU_EXT_NAME, _au)

#endif // GEN_EXT_COMMON_AU_H
