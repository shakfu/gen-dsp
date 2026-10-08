// _ext_ssp_buffers.h - loading audio files into an instance's gen~ buffers
// Defined in _ext_ssp.cpp; graph projects have no buffers and no definitions.
#ifndef _EXT_SSP_BUFFERS_H
#define _EXT_SSP_BUFFERS_H

#include <dlfcn.h>

#include <string>

#include "_ext_ssp.h"

namespace WRAPPER_NAMESPACE {

// Reads a WAV file (PCM 16/24-bit or float 32-bit) into buffer `index`, resized to the file;
// the file's sample rate is ignored. Not on the audio thread, and one thread at a time. The
// next wrapper_perform() picks the data up. Returns the frames read, or -1.
long wrapper_buffer_load(GenState* state, int index, const char* path);

}  // namespace WRAPPER_NAMESPACE

// Where a module's default files live: `module` beside the folder holding this .so. On the
// card, plugins/gvrb.so reads gvrb/<buffer>.wav. Empty if the path cannot be found.
static inline std::string ssp_buffer_dir(const char* module) {
    Dl_info info;
    if (dladdr(reinterpret_cast<void*>(&ssp_buffer_dir), &info) == 0 || !info.dli_fname) return {};
    std::string so = info.dli_fname;
    size_t slash = so.rfind('/');
    std::string dir = slash == std::string::npos ? std::string(".") : so.substr(0, slash);
    return dir + "/../" + module;
}

#endif  // _EXT_SSP_BUFFERS_H
