// genlib_circle.h - Bare metal genlib runtime for Circle (Raspberry Pi)
//
// Replaces the standard genlib.cpp allocator with a simple heap-based
// allocator suitable for bare-metal Raspberry Pi (plenty of RAM available).
//
// Memory: Pi 3 has 1GB, Pi 4 has up to 8GB. We use a simple heap pool
// allocated from the system heap (new/delete available at STDLIB_SUPPORT=1).
//
// This header is self-contained -- no Circle includes required.

#ifndef GENLIB_CIRCLE_H
#define GENLIB_CIRCLE_H

#include <stddef.h>

// Heap pool size (bytes) - 16MB is generous for most gen~ patches
// Pi has plenty of RAM; this can be increased if needed
#define CIRCLE_HEAP_POOL_SIZE (16 * 1024 * 1024)

#ifdef __cplusplus
extern "C" {
#endif

// Initialize the heap pool. Must be called before any genlib allocation.
void circle_init_memory(void);

// Reset the heap pool (free all allocated memory).
// After this call, all previously allocated pointers are invalid.
void circle_reset_memory(void);

#ifdef __cplusplus
}
#endif

#endif // GENLIB_CIRCLE_H
