// gen_buffer_max.h - Buffer class for gen~ code (genlib side)
// Uses DataInterface for gen~ compatibility, no Max headers

#ifndef GEN_BUFFER_MAX_H
#define GEN_BUFFER_MAX_H

#include "genlib.h"

// GenBuffer - simple buffer wrapper for gen~ DataInterface
// Data is set from the Max side before each perform call
struct GenBuffer : public DataInterface<t_sample> {

    GenBuffer() : DataInterface<t_sample>() {
        mData = nullptr;
        dim = 0;
        channels = 1;
    }

    // Called from Max side to set buffer data before perform
    void setData(float* data, long frames, long numChannels) {
        // Note: Max buffers are always 32-bit float, but our t_sample is double
        // The Max wrapper handles conversion by passing locked float* data
        // We store the pointer and let read/write do the conversion
        mFloatData = data;
        dim = frames;
        channels = numChannels;
    }

    void clearData() {
        mFloatData = nullptr;
        dim = 0;
        channels = 1;
    }

    // Override read to handle float->double conversion
    inline t_sample read(long index, long channel = 0) const {
        if (!mFloatData || index < 0 || index >= dim || channel < 0 || channel >= channels) {
            return 0;
        }
        // Max buffers are interleaved: [ch0_s0, ch1_s0, ch0_s1, ch1_s1, ...]
        return (t_sample)mFloatData[index * channels + channel];
    }

    // Override write to handle double->float conversion
    inline void write(t_sample value, long index, long channel = 0) {
        if (!mFloatData || index < 0 || index >= dim || channel < 0 || channel >= channels) {
            return;
        }
        mFloatData[index * channels + channel] = (float)value;
        modified = 1;
    }

    // Override blend for splat operations
    inline void blend(t_sample value, long index, long channel, t_sample alpha) {
        if (!mFloatData || index < 0 || index >= dim || channel < 0 || channel >= channels) {
            return;
        }
        long offset = index * channels + channel;
        const float old = mFloatData[offset];
        mFloatData[offset] = old + (float)(alpha * (value - old));
        modified = 1;
    }

private:
    float* mFloatData = nullptr;  // Pointer to Max buffer's float data
};

#endif // GEN_BUFFER_MAX_H
