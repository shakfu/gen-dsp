// auv3_buffer.h - Buffer class for gen~ code (genlib side)
#ifndef AUV3_BUFFER_H
#define AUV3_BUFFER_H

#include "genlib.h"

struct Auv3Buffer : public DataInterface<t_sample> {
    Auv3Buffer() : DataInterface<t_sample>() {
        mData = nullptr; mOwnedData = nullptr; dim = 0; channels = 1;
    }
    ~Auv3Buffer() { if (mOwnedData) { delete[] mOwnedData; mOwnedData = nullptr; } }

    void allocate(long frames, long numChannels) {
        if (mOwnedData) delete[] mOwnedData;
        dim = frames; channels = numChannels;
        long total = dim * channels;
        if (total > 0) { mOwnedData = new t_sample[total](); mData = mOwnedData; }
        else { mOwnedData = nullptr; mData = nullptr; }
    }
    void clearData() {
        if (mOwnedData) { long t = dim * channels; for (long i = 0; i < t; i++) mOwnedData[i] = 0; }
    }
    inline t_sample read(long index, long channel = 0) const {
        if (!mData || index < 0 || index >= dim || channel < 0 || channel >= channels) return 0;
        return mData[index * channels + channel];
    }
    inline void write(t_sample value, long index, long channel = 0) {
        if (!mData || index < 0 || index >= dim || channel < 0 || channel >= channels) return;
        mData[index * channels + channel] = value; modified = 1;
    }
    inline void blend(t_sample value, long index, long channel, t_sample alpha) {
        if (!mData || index < 0 || index >= dim || channel < 0 || channel >= channels) return;
        long offset = index * channels + channel;
        t_sample old = mData[offset]; mData[offset] = old + alpha * (value - old); modified = 1;
    }
private:
    t_sample* mOwnedData = nullptr;
};

#endif // AUV3_BUFFER_H
