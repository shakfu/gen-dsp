// vst3_buffer.h - Buffer class for gen~ code (genlib side)
// Uses DataInterface for gen~ compatibility, no VST3 headers

#ifndef VST3_BUFFER_H
#define VST3_BUFFER_H

#include "genlib.h"

// Vst3Buffer - buffer wrapper for gen~ DataInterface
// Buffers are allocated locally; data is zero-filled by default.
struct Vst3Buffer : public DataInterface<t_sample> {

    Vst3Buffer() : DataInterface<t_sample>() {
        mData = nullptr;
        mOwnedData = nullptr;
        dim = 0;
        channels = 1;
    }

    ~Vst3Buffer() {
        if (mOwnedData) {
            delete[] mOwnedData;
            mOwnedData = nullptr;
        }
    }

    // Allocate buffer storage
    void allocate(long frames, long numChannels) {
        if (mOwnedData) {
            delete[] mOwnedData;
        }
        dim = frames;
        channels = numChannels;
        long total = dim * channels;
        if (total > 0) {
            mOwnedData = new t_sample[total]();  // zero-initialized
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

#endif // VST3_BUFFER_H
