// gen_ext_common_vst3.h - Macro definitions for VST3 wrapper
// This file provides name mangling macros for the VST3 backend

#ifndef GEN_EXT_COMMON_VST3_H
#define GEN_EXT_COMMON_VST3_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

// Use GSTR for stringification to avoid collision with VST3 SDK's STR macro
#define GSTR_EXPAND(s) #s
#define GSTR(s) GSTR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from VST3)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(VST3_EXT_NAME, _vst3)

#endif // GEN_EXT_COMMON_VST3_H
