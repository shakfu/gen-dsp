// gen_ext_common_sc.h - Macro definitions for SuperCollider wrapper
// This file provides name mangling macros for the SC backend

#ifndef GEN_EXT_COMMON_SC_H
#define GEN_EXT_COMMON_SC_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from SC)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(SC_EXT_NAME, _sc)

#endif // GEN_EXT_COMMON_SC_H
