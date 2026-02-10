// genlib_daisy.cpp - Embedded genlib runtime for Daisy (Electrosmith)
//
// Drop-in replacement for genlib.cpp that uses a two-tier bump allocator
// (SRAM + SDRAM) instead of malloc/free. Compiled INSTEAD of the standard
// genlib.cpp from the gen~ export.
//
// Function names match what genlib_exportfunctions.h declares:
//   sysmem_newptr, sysmem_freeptr, set_zero64, systime_ticks, etc.
// genlib.h macros remap genlib_sysmem_* -> sysmem_* automatically.

#include "genlib_daisy.h"

// libDaisy defines ARM_MATH_CM7 which causes genlib_platform.h to enable
// GENLIB_USE_ARMMATH and GENLIB_USE_FASTMATH. These remap sqrt/pow etc. to
// ARM DSP functions that are not available. Undef before including genlib.
#ifdef ARM_MATH_CM7
#undef ARM_MATH_CM7
#endif
#ifdef ARM_MATH_CM4
#undef ARM_MATH_CM4
#endif

#include "genlib.h"
#include "genlib_exportfunctions.h"

#include <cstring>
#include <cstdlib>

#ifndef MSP_ON_CLANG
#include <cmath>
#endif

// Disable JSON state save/restore on embedded (no filesystem)
#define GENLIB_NO_JSON

#ifndef GENLIB_NO_JSON
#include "json.h"
#include "json_builder.h"
#endif

// DATA_MAXIMUM_ELEMENTS * sizeof(t_sample) = max data size
#define DATA_MAXIMUM_ELEMENTS (33554432)

// ---------------------------------------------------------------------------
// SDRAM placement attribute (no libDaisy header dependency)
// ---------------------------------------------------------------------------
#define DSY_SDRAM_BSS __attribute__((section(".sdram_bss")))

// ---------------------------------------------------------------------------
// Memory pools
// ---------------------------------------------------------------------------

// SRAM pool (malloc'd at init)
static char* sram_pool = nullptr;
static size_t sram_offset = 0;

// SDRAM pool (placed in .sdram_bss section by linker)
DSY_SDRAM_BSS static char sdram_pool[DAISY_SDRAM_POOL_SIZE];
static size_t sdram_offset = 0;

// ---------------------------------------------------------------------------
// Bump allocator
// ---------------------------------------------------------------------------

// Align to 8 bytes for ARM Cortex-M7 (double-word aligned)
static inline size_t align8(size_t n) {
    return (n + 7) & ~(size_t)7;
}

static void* daisy_allocate(size_t size) {
    size = align8(size);

    // Try SRAM first
    if (sram_pool && (sram_offset + size <= DAISY_SRAM_POOL_SIZE)) {
        void* ptr = sram_pool + sram_offset;
        sram_offset += size;
        return ptr;
    }

    // Fall back to SDRAM
    if (sdram_offset + size <= DAISY_SDRAM_POOL_SIZE) {
        void* ptr = sdram_pool + sdram_offset;
        sdram_offset += size;
        return ptr;
    }

    // Out of memory
    return nullptr;
}

// ---------------------------------------------------------------------------
// Public API (Daisy-specific)
// ---------------------------------------------------------------------------

void daisy_init_memory(void) {
    if (!sram_pool) {
        sram_pool = (char*)malloc(DAISY_SRAM_POOL_SIZE);
    }
    if (sram_pool) {
        memset(sram_pool, 0, DAISY_SRAM_POOL_SIZE);
    }
    sram_offset = 0;

    memset(sdram_pool, 0, DAISY_SDRAM_POOL_SIZE);
    sdram_offset = 0;
}

void daisy_reset_memory(void) {
    sram_offset = 0;
    sdram_offset = 0;
    if (sram_pool) {
        memset(sram_pool, 0, DAISY_SRAM_POOL_SIZE);
    }
    memset(sdram_pool, 0, DAISY_SDRAM_POOL_SIZE);
}

// ---------------------------------------------------------------------------
// Memory allocation functions (names match genlib_exportfunctions.h)
// genlib.h macros: genlib_sysmem_newptr(s) -> sysmem_newptr(s), etc.
// ---------------------------------------------------------------------------

t_ptr sysmem_newptr(t_ptr_size size) {
    return (t_ptr)daisy_allocate((size_t)size);
}

t_ptr sysmem_newptrclear(t_ptr_size size) {
    t_ptr p = (t_ptr)daisy_allocate((size_t)size);
    if (p) {
        memset(p, 0, (size_t)size);
    }
    return p;
}

t_ptr sysmem_resizeptr(void* ptr, t_ptr_size newsize) {
    // Allocate new block (old block is wasted -- bump allocator)
    return (t_ptr)daisy_allocate((size_t)newsize);
}

t_ptr sysmem_resizeptrclear(void* ptr, t_ptr_size newsize) {
    t_ptr p = (t_ptr)daisy_allocate((size_t)newsize);
    if (p) {
        memset(p, 0, (size_t)newsize);
    }
    return p;
}

t_ptr_size sysmem_ptrsize(void* ptr) {
    // Cannot determine size from bump allocator
    (void)ptr;
    return 0;
}

void sysmem_freeptr(void* ptr) {
    // No-op: bump allocator does not free individual allocations
    (void)ptr;
}

void sysmem_copyptr(const void* src, void* dst, t_ptr_size bytes) {
    memcpy(dst, src, (size_t)bytes);
}

// ---------------------------------------------------------------------------
// Utility functions (names match genlib_exportfunctions.h)
// ---------------------------------------------------------------------------

void set_zero64(t_sample* memory, long size) {
    for (long i = 0; i < size; i++) {
        memory[i] = 0;
    }
}

void genlib_report_error(const char* s) {
    (void)s;
}

void genlib_report_message(const char* s) {
    (void)s;
}

unsigned long systime_ticks(void) {
    return 0;
}

// ---------------------------------------------------------------------------
// Math
// ---------------------------------------------------------------------------

t_sample gen_msp_pow(t_sample value, t_sample power) {
    return (t_sample)powf((float)value, (float)power);
}

// ---------------------------------------------------------------------------
// String/reference stubs (no Max runtime on embedded)
// ---------------------------------------------------------------------------

void* genlib_obtain_reference_from_string(const char* name) {
    return 0;
}

char* genlib_reference_getname(void* ref) {
    return 0;
}

// ---------------------------------------------------------------------------
// Buffer stubs (no Max buffer~ on embedded)
// ---------------------------------------------------------------------------

t_genlib_buffer* genlib_obtain_buffer_from_reference(void* ref) {
    return 0;
}

t_genlib_err genlib_buffer_edit_begin(t_genlib_buffer* b) {
    return 0;
}

t_genlib_err genlib_buffer_edit_end(t_genlib_buffer* b, long valid) {
    return 0;
}

t_genlib_err genlib_buffer_getinfo(t_genlib_buffer* b, t_genlib_buffer_info* info) {
    return 0;
}

void genlib_buffer_dirty(t_genlib_buffer* b) {
}

t_genlib_err genlib_buffer_perform_begin(t_genlib_buffer* b) {
    return 0;
}

void genlib_buffer_perform_end(t_genlib_buffer* b) {
}

// ---------------------------------------------------------------------------
// Data object support (for gen~ delay lines, etc.)
// t_genlib_data is opaque; we define the actual struct here (same as genlib.cpp)
// ---------------------------------------------------------------------------

typedef struct {
    t_genlib_data_info info;
    t_sample cursor;
} t_dsp_gen_data;

void genlib_data_setbuffer(t_genlib_data* b, void* ref) {
    genlib_report_error("not supported for export targets\n");
}

t_genlib_data* genlib_obtain_data_from_reference(void* ref) {
    t_dsp_gen_data* self = (t_dsp_gen_data*)sysmem_newptrclear(sizeof(t_dsp_gen_data));
    self->info.dim = 0;
    self->info.channels = 0;
    self->info.data = 0;
    self->cursor = 0;
    return (t_genlib_data*)self;
}

t_genlib_err genlib_data_getinfo(t_genlib_data* b, t_genlib_data_info* info) {
    t_dsp_gen_data* self = (t_dsp_gen_data*)b;
    info->dim = self->info.dim;
    info->channels = self->info.channels;
    info->data = self->info.data;
    return GENLIB_ERR_NONE;
}

void genlib_data_release(t_genlib_data* b) {
    // No-op on bump allocator (cannot free individual allocations)
    (void)b;
}

long genlib_data_getcursor(t_genlib_data* b) {
    t_dsp_gen_data* self = (t_dsp_gen_data*)b;
    return long(self->cursor);
}

void genlib_data_setcursor(t_genlib_data* b, long cursor) {
    t_dsp_gen_data* self = (t_dsp_gen_data*)b;
    self->cursor = t_sample(cursor);
}

void genlib_data_resize(t_genlib_data* b, long s, long c) {
    t_dsp_gen_data* self = (t_dsp_gen_data*)b;

    t_sample* old = self->info.data;
    int olddim = self->info.dim;
    int oldchannels = self->info.channels;

    // Limit data size
    if (s * c > DATA_MAXIMUM_ELEMENTS) {
        s = DATA_MAXIMUM_ELEMENTS / c;
    }

    size_t sz = sizeof(t_sample) * s * c;
    size_t oldsz = sizeof(t_sample) * olddim * oldchannels;

    if (old && sz == oldsz) {
        // Same size, just re-zero and update dims
        if (s > olddim) {
            self->info.channels = c;
            self->info.dim = s;
        } else {
            self->info.dim = s;
            self->info.channels = c;
        }
        set_zero64(self->info.data, s * c);
        return;
    }

    // Allocate new
    t_sample* replaced = (t_sample*)sysmem_newptr(sz);
    if (replaced == 0) {
        genlib_report_error("allocating [data]: out of memory");
        if (s > 512 || c > 1) {
            genlib_data_resize((t_genlib_data*)self, 512, 1);
        } else {
            genlib_data_resize((t_genlib_data*)self, 4, 1);
        }
        return;
    }

    // Fill with zeroes
    set_zero64(replaced, s * c);

    // Copy old data
    if (old) {
        int copydim = olddim > s ? s : olddim;
        if (c == oldchannels) {
            size_t copysz = sizeof(t_sample) * copydim * c;
            memcpy(replaced, old, copysz);
        } else {
            int copychannels = oldchannels > c ? c : oldchannels;
            for (int i = 0; i < copydim; i++) {
                for (int j = 0; j < copychannels; j++) {
                    replaced[j + i * c] = old[j + i * oldchannels];
                }
            }
        }
    }

    // Update info (order matters for thread safety)
    if (old == 0) {
        self->info.data = replaced;
        self->info.dim = s;
        self->info.channels = c;
    } else {
        if (oldsz > sz) {
            if (s > olddim) {
                self->info.channels = c;
                self->info.dim = s;
            } else {
                self->info.dim = s;
                self->info.channels = c;
            }
            self->info.data = replaced;
        } else {
            self->info.data = replaced;
            if (s > olddim) {
                self->info.channels = c;
                self->info.dim = s;
            } else {
                self->info.dim = s;
                self->info.channels = c;
            }
        }
        // Old pointer is wasted (bump allocator cannot free)
    }
}

// ---------------------------------------------------------------------------
// Reset / state
// ---------------------------------------------------------------------------

void genlib_reset_complete(void* data) {
}

// State save/restore (stubbed for embedded -- no JSON on Daisy)
size_t genlib_getstatesize(CommonState* cself, getparameter_method getmethod) {
    return 0;
}

short genlib_getstate(CommonState* cself, char* state, getparameter_method getmethod) {
    return 0;
}

short genlib_setstate(CommonState* cself, const char* state, setparameter_method setmethod) {
    return 0;
}
