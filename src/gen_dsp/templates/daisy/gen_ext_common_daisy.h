// gen_ext_common_daisy.h - Macro definitions for Daisy wrapper
// This file provides name mangling macros for the Daisy backend

#ifndef GEN_EXT_COMMON_DAISY_H
#define GEN_EXT_COMMON_DAISY_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from Daisy)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(DAISY_EXT_NAME, _daisy)

#endif // GEN_EXT_COMMON_DAISY_H
