// gen_ext_common_clap.h - Macro definitions for CLAP wrapper
// This file provides name mangling macros for the CLAP backend

#ifndef GEN_EXT_COMMON_CLAP_H
#define GEN_EXT_COMMON_CLAP_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from CLAP)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(CLAP_EXT_NAME, _clap)

#endif // GEN_EXT_COMMON_CLAP_H
