// gen_ext_common_pd.h - Macro definitions for PD graph wrapper
// This file provides name mangling macros for the PD graph backend

#ifndef GEN_EXT_COMMON_PD_H
#define GEN_EXT_COMMON_PD_H

// Buffer configuration (defines WRAPPER_BUFFER_COUNT and buffer names)
#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

// Macro concatenation helpers
#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

#define WRAPPER_CLASS WRAPPER_FUN2(PD_EXT_NAME, _tilde_class)

#define WRAPPER_HIDDEN WRAPPER_FUN2(_, PD_EXT_NAME)
#define WRAPPER_STRUCT WRAPPER_FUN2(WRAPPER_HIDDEN, _tilde)
#define WRAPPER_T WRAPPER_FUN2(t_, PD_EXT_NAME)
#define WRAPPER_TYPE WRAPPER_FUN2(WRAPPER_T, _tilde)

// Namespace for wrapper functions (isolates graph code from PD)
#define WRAPPER_NAMESPACE WRAPPER_FUN2(PD_EXT_NAME, _pd)

#define WRAPPER_SETUP WRAPPER_FUN2(PD_EXT_NAME, _tilde_setup)
#define WRAPPER_NEW WRAPPER_FUN2(PD_EXT_NAME, _tilde_new)
#define WRAPPER_FREE WRAPPER_FUN2(PD_EXT_NAME, _tilde_free)
#define WRAPPER_PERFORM WRAPPER_FUN2(PD_EXT_NAME, _tilde_perform)
#define WRAPPER_DSP WRAPPER_FUN2(PD_EXT_NAME, _tilde_DSP)
#define WRAPPER_ANY_METHOD WRAPPER_FUN2(PD_EXT_NAME, _tilde_any_method)
#define WRAPPER_BANG WRAPPER_FUN2(PD_EXT_NAME, _tilde_bang)
#define WRAPPER_SR WRAPPER_FUN2(PD_EXT_NAME, _tilde_sr)
#define WRAPPER_BS WRAPPER_FUN2(PD_EXT_NAME, _tilde_bs)
#define WRAPPER_RESET WRAPPER_FUN2(PD_EXT_NAME, _tilde_reset)

#define MESSAGE_SR pdsr
#define MESSAGE_BS pdbs
#define MESSAGE_RESET reset

#endif // GEN_EXT_COMMON_PD_H
