// gen_ext_common_lv2.h - Macro definitions for LV2 wrapper
// This file provides name mangling macros for the LV2 backend

#ifndef GEN_EXT_COMMON_LV2_H
#define GEN_EXT_COMMON_LV2_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from LV2)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(LV2_EXT_NAME, _lv2)

#endif // GEN_EXT_COMMON_LV2_H
