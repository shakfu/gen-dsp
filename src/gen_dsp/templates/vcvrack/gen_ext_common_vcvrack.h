// gen_ext_common_vcvrack.h - Macro definitions for VCV Rack wrapper
// This file provides name mangling macros for the VCV Rack backend

#ifndef GEN_EXT_COMMON_VCVRACK_H
#define GEN_EXT_COMMON_VCVRACK_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from VCV Rack)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(VCR_EXT_NAME, _vcvrack)

#endif // GEN_EXT_COMMON_VCVRACK_H
