// daisy_buffer.h - Buffer class for gen~ code (genlib side)
// Uses DataInterface for gen~ compatibility, no Daisy/libDaisy headers

#ifndef DAISY_BUFFER_H
#define DAISY_BUFFER_H

#include "genlib.h"

// DaisyBuffer - buffer wrapper for gen~ DataInterface
// Buffers are allocated locally; data is zero-filled by default.
// On Daisy, allocation goes through genlib_sysmem_newptr() which
// uses the bump allocator defined in genlib_daisy.cpp.
struct DaisyBuffer : public DataInterface<t_sample> {

    DaisyBuffer() : DataInterface<t_sample>() {
        mData = nullptr;
        mOwnedData = nullptr;
        dim = 0;
        channels = 1;
    }

    ~DaisyBuffer() {
        // On Daisy, genlib_sysmem_freeptr is a no-op (bump allocator),
        // so we skip deallocation. Memory is reclaimed on reset.
        mOwnedData = nullptr;
        mData = nullptr;
    }

    // Allocate buffer storage
    void allocate(long frames, long numChannels) {
        dim = frames;
        channels = numChannels;
        long total = dim * channels;
        if (total > 0) {
            // Use genlib's allocator (routed to bump allocator on Daisy)
            mOwnedData = (t_sample*)genlib_sysmem_newptrclear(total * sizeof(t_sample));
            mData = mOwnedData;
        } else {
            mOwnedData = nullptr;
            mData = nullptr;
        }
    }

    void clearData() {
        if (mOwnedData) {
            long total = dim * channels;
            for (long i = 0; i < total; i++) {
                mOwnedData[i] = 0;
            }
        }
    }

    // Read sample from buffer
    inline t_sample read(long index, long channel = 0) const {
        if (!mData || index < 0 || index >= dim || channel < 0 || channel >= channels) {
            return 0;
        }
        return mData[index * channels + channel];
    }

    // Write sample to buffer
    inline void write(t_sample value, long index, long channel = 0) {
        if (!mData || index < 0 || index >= dim || channel < 0 || channel >= channels) {
            return;
        }
        mData[index * channels + channel] = value;
        modified = 1;
    }

    // Blend (splat) operation
    inline void blend(t_sample value, long index, long channel, t_sample alpha) {
        if (!mData || index < 0 || index >= dim || channel < 0 || channel >= channels) {
            return;
        }
        long offset = index * channels + channel;
        t_sample old = mData[offset];
        mData[offset] = old + alpha * (value - old);
        modified = 1;
    }

private:
    t_sample* mOwnedData = nullptr;  // Owned buffer data
};

#endif // DAISY_BUFFER_H
