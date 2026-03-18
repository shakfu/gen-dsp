// gen_ext_csound.cpp - Csound opcode bridge
// This file includes ONLY Csound headers, NO genlib headers
// The opcode struct and OENTRY are built from compile-time defines.
//
// Opcode signature (generated):
//   outypes: "a" repeated num_outputs times (e.g. "aa" for stereo)
//   intypes: "a" repeated num_inputs times + "k" repeated num_params times
//            (e.g. "aakkkk" for 2 audio in + 4 control params)
//
// Usage in .csd:
//   aout1 [, aout2, ...] <opcode_name> ain1 [, ain2, ...], kparam1 [, kparam2, ...]
//
// For generators (0 audio inputs):
//   aout1 [, aout2, ...] <opcode_name> kparam1 [, kparam2, ...]

#include <cstring>
#include <cstdlib>

// The genlib WIN32 workaround is defined globally via -DWIN32 in CFLAGS
// (needed by _ext_csound.cpp). We must undef it here so Csound's sysdep.h
// does not try to include <io.h> (Windows-only).
#ifdef WIN32
#undef WIN32
#endif

#include "csdl.h"
#include "_ext_csound.h"

using namespace WRAPPER_NAMESPACE;

// -- Opcode struct ---------------------------------------------------------
// OPDS header, then output pointers, then input pointers.
// Max 8 audio outputs, 8 audio inputs, 32 k-rate params.
// The struct must fit in uint16 (dsblksiz field of OENTRY), so conversion
// buffers are heap-allocated, not embedded.

#ifndef GEN_NUM_INPUTS
#define GEN_NUM_INPUTS 0
#endif
#ifndef GEN_NUM_OUTPUTS
#define GEN_NUM_OUTPUTS 1
#endif
#ifndef GEN_NUM_PARAMS
#define GEN_NUM_PARAMS 0
#endif

#define MAX_AUDIO_OUTS 8
#define MAX_AUDIO_INS  8
#define MAX_PARAMS     32

typedef struct {
    OPDS    h;
    // Outputs: audio-rate pointers (MYFLT* buffers of CS_KSMPS samples)
    MYFLT   *aout[MAX_AUDIO_OUTS];
    // Inputs: audio-rate, then k-rate params
    MYFLT   *ain[MAX_AUDIO_INS];
    MYFLT   *kparam[MAX_PARAMS];
    // Internal state
    GenState *state;
    int      initialized;
    // Heap-allocated conversion buffers (allocated in init)
    float    *in_buf;
    float    *out_buf;
} GENOPCODE;

// -- Init callback ---------------------------------------------------------

static int32_t gen_opcode_init(CSOUND *csound, GENOPCODE *p)
{
    float sr = (float)csound->GetSr(csound);
    long ksmps = (long)csound->GetKsmps(csound);

    if (p->state) {
        wrapper_destroy(p->state);
    }

    p->state = wrapper_create(sr, ksmps);
    if (!p->state) {
        return csound->InitError(csound, "%s",
            "gen-dsp: failed to create gen~ state");
    }

    p->initialized = 1;

    // Allocate conversion buffers (freed when Csound deallocates the instrument)
    size_t buf_frames = (size_t)ksmps;
    if (p->in_buf) free(p->in_buf);
    if (p->out_buf) free(p->out_buf);
    p->in_buf = (float*)calloc(MAX_AUDIO_INS * buf_frames, sizeof(float));
    p->out_buf = (float*)calloc(MAX_AUDIO_OUTS * buf_frames, sizeof(float));

    // Set initial parameter values from i-time k-rate defaults
    int nparams = wrapper_num_params();
    for (int i = 0; i < nparams && i < MAX_PARAMS; i++) {
        if (p->kparam[i]) {
            wrapper_set_param(p->state, i, (float)*p->kparam[i]);
        }
    }

    return OK;
}

// -- Perf callback (k-rate / a-rate) ---------------------------------------

static int32_t gen_opcode_perf(CSOUND *csound, GENOPCODE *p)
{
    if (!p->initialized || !p->state) {
        return csound->PerfError(csound, &(p->h), "%s",
            "gen-dsp: opcode not initialized");
    }

    uint32_t offset = p->h.insdshead->ksmps_offset;
    uint32_t early  = p->h.insdshead->ksmps_no_end;
    uint32_t nsmps  = CS_KSMPS;

    int num_in  = GEN_NUM_INPUTS;
    int num_out = GEN_NUM_OUTPUTS;
    int nparams = wrapper_num_params();

    // Update parameters from k-rate inputs
    for (int i = 0; i < nparams && i < MAX_PARAMS; i++) {
        if (p->kparam[i]) {
            wrapper_set_param(p->state, i, (float)*p->kparam[i]);
        }
    }

    // Zero output for sample-accurate onset
    if (UNLIKELY(offset)) {
        for (int ch = 0; ch < num_out; ch++) {
            memset(p->aout[ch], '\0', offset * sizeof(MYFLT));
        }
    }
    // Zero output for early release
    if (UNLIKELY(early)) {
        nsmps -= early;
        for (int ch = 0; ch < num_out; ch++) {
            memset(&p->aout[ch][nsmps], '\0', early * sizeof(MYFLT));
        }
    }

    uint32_t n = nsmps - offset;

    // Convert Csound MYFLT inputs to gen~ float buffers
    float *in_ptrs[MAX_AUDIO_INS];
    for (int ch = 0; ch < num_in && ch < MAX_AUDIO_INS; ch++) {
        in_ptrs[ch] = &p->in_buf[ch * nsmps];
        for (uint32_t i = 0; i < n; i++) {
            in_ptrs[ch][i] = (float)p->ain[ch][offset + i];
        }
    }

    // Set up output float buffers
    float *out_ptrs[MAX_AUDIO_OUTS];
    for (int ch = 0; ch < num_out && ch < MAX_AUDIO_OUTS; ch++) {
        out_ptrs[ch] = &p->out_buf[ch * nsmps];
        for (uint32_t i = 0; i < n; i++) {
            out_ptrs[ch][i] = 0.0f;
        }
    }

    // Process
    wrapper_perform(p->state, in_ptrs, (long)num_in,
                    out_ptrs, (long)num_out, (long)n);

    // Convert gen~ float output back to Csound MYFLT
    for (int ch = 0; ch < num_out && ch < MAX_AUDIO_OUTS; ch++) {
        for (uint32_t i = 0; i < n; i++) {
            p->aout[ch][offset + i] = (MYFLT)out_ptrs[ch][i];
        }
    }

    return OK;
}

// -- Opcode registration ---------------------------------------------------
// The OENTRY type strings and opcode name are injected via -D defines
// from the Makefile at compile time.

#ifndef CSOUND_OPCODE_NAME
#define CSOUND_OPCODE_NAME "gendsp"
#endif
#ifndef CSOUND_OUTYPES
#define CSOUND_OUTYPES "a"
#endif
#ifndef CSOUND_INTYPES
#define CSOUND_INTYPES "k"
#endif

static OENTRY localops[] = {
    {
        (char*)CSOUND_OPCODE_NAME,
        sizeof(GENOPCODE),
        0,      // flags
        3,      // thread: i-time + perf-time
        (char*)CSOUND_OUTYPES,
        (char*)CSOUND_INTYPES,
        (SUBR)gen_opcode_init,
        (SUBR)gen_opcode_perf,
        NULL
    },
    { NULL, 0, 0, 0, NULL, NULL, NULL, NULL, NULL }
};

LINKAGE_BUILTIN(localops)
