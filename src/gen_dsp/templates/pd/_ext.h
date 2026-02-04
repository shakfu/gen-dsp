#include "gen_ext_common.h"

#include "genlib.h"
#include "genlib_exportfunctions.h"
#include "genlib_ops.h"

#include "pd_buffer.h"
namespace WRAPPER_NAMESPACE {
#ifdef WRAPPER_BUFFER_NAME_0
	extern PdBuffer WRAPPER_BUFFER_NAME_0;
#endif
#ifdef WRAPPER_BUFFER_NAME_1
	extern PdBuffer WRAPPER_BUFFER_NAME_1;
#endif
#ifdef WRAPPER_BUFFER_NAME_2
	extern PdBuffer WRAPPER_BUFFER_NAME_2;
#endif
#ifdef WRAPPER_BUFFER_NAME_3
	extern PdBuffer WRAPPER_BUFFER_NAME_3;
#endif
#ifdef WRAPPER_BUFFER_NAME_4
	extern PdBuffer WRAPPER_BUFFER_NAME_4;
#endif

#include GEN_EXPORTED_HEADER
}