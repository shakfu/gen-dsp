// genlib_daisy.h - Embedded genlib runtime for Daisy (Electrosmith)
//
// Replaces the standard genlib.cpp allocator with a two-tier bump allocator
// suitable for bare-metal STM32H750 (no heap fragmentation).
//
// Memory layout:
//   SRAM pool:  malloc'd at init time (~450KB usable on STM32H750)
//   SDRAM pool: static array in .sdram_bss section (64MB on Daisy Seed)
//
// This header is self-contained -- no libDaisy includes required.

#ifndef GENLIB_DAISY_H
#define GENLIB_DAISY_H

#include <stddef.h>

// Pool sizes (bytes)
// SRAM: conservatively sized to leave room for stack + libDaisy internals
#define DAISY_SRAM_POOL_SIZE  (450 * 1024)
// SDRAM: Daisy Seed has 64MB SDRAM
#define DAISY_SDRAM_POOL_SIZE (64 * 1024 * 1024)

#ifdef __cplusplus
extern "C" {
#endif

// Initialize memory pools. Must be called before any genlib allocation.
// Allocates the SRAM pool via malloc and zeros both pools.
void daisy_init_memory(void);

// Reset memory pools (free all bump-allocated memory).
// After this call, all previously allocated pointers are invalid.
void daisy_reset_memory(void);

#ifdef __cplusplus
}
#endif

#endif // GENLIB_DAISY_H
