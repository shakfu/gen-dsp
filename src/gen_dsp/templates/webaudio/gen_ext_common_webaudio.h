// gen_ext_common_webaudio.h - Macro definitions for Web Audio wrapper
// This file provides name mangling macros for the Web Audio backend

#ifndef GEN_EXT_COMMON_WEBAUDIO_H
#define GEN_EXT_COMMON_WEBAUDIO_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

// Namespace for wrapper functions (isolates genlib from Emscripten bridge)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(WEBAUDIO_EXT_NAME, _webaudio)

// Web Audio buffer loading: defined on the genlib side in _ext_webaudio.cpp and
// called from the Emscripten bridge. Copies `frames * channels` interleaved
// float32 samples (frame-major) into the buffer at `index`. Declared here so it
// is visible to both sides without exposing genlib's WebaudioBuffer type.
namespace WRAPPER_NAMESPACE {
void wrapper_load_buffer(int index, const float* data, long frames, long channels);
}

#endif // GEN_EXT_COMMON_WEBAUDIO_H
