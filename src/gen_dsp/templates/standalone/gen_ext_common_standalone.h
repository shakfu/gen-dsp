// gen_ext_common_standalone.h - Macro definitions for standalone wrapper
// This file provides name mangling macros for the standalone backend

#ifndef GEN_EXT_COMMON_STANDALONE_H
#define GEN_EXT_COMMON_STANDALONE_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from main application)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(STANDALONE_EXT_NAME, _standalone)

#endif // GEN_EXT_COMMON_STANDALONE_H
