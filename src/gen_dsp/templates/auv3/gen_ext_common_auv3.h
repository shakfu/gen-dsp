// gen_ext_common_auv3.h - Macro definitions for AUv3 wrapper
#ifndef GEN_EXT_COMMON_AUV3_H
#define GEN_EXT_COMMON_AUV3_H

#include "gen_buffer.h"

#define STR_EXPAND(s) #s
#define STR(s) STR_EXPAND(s)

#define WRAPPER_FUN(NAME, POST) NAME ## POST
#define WRAPPER_FUN2(NAME, POST) WRAPPER_FUN(NAME, POST)

#define WRAPPER_NAMESPACE WRAPPER_FUN2(AUV3_EXT_NAME, _auv3)

#endif // GEN_EXT_COMMON_AUV3_H
