// chuck_buffer.h - Buffer class for gen~ code (genlib side)
// Uses DataInterface for gen~ compatibility, no ChucK headers

#ifndef CHUCK_BUFFER_H
#define CHUCK_BUFFER_H

#include "genlib.h"
#include <cstdio>
#include <cstring>
#include <cstdint>

// ChuckBuffer - buffer wrapper for gen~ DataInterface
// Buffers are allocated locally; data is zero-filled by default.
// Supports loading WAV audio via loadWav().
struct ChuckBuffer : public DataInterface<t_sample> {

    ChuckBuffer() : DataInterface<t_sample>() {
        mData = nullptr;
        mOwnedData = nullptr;
        dim = 0;
        channels = 1;
    }

    ~ChuckBuffer() {
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

    // Load WAV audio file into this buffer.
    // Supports PCM 16-bit, 24-bit, and IEEE float 32-bit.
    // Returns number of frames loaded, or -1 on error.
    int loadWav(const char* path) {
        FILE* fp = std::fopen(path, "rb");
        if (!fp) return -1;

        // Validate RIFF/WAVE header
        unsigned char hdr[12];
        if (std::fread(hdr, 1, 12, fp) != 12 ||
            std::memcmp(hdr, "RIFF", 4) != 0 ||
            std::memcmp(hdr + 8, "WAVE", 4) != 0) {
            std::fclose(fp);
            return -1;
        }

        // Scan for fmt and data chunks
        uint16_t audioFmt = 0, nch = 0, bps = 0;
        uint32_t dataSz = 0;
        bool gotFmt = false, gotData = false;

        while (!gotData) {
            unsigned char ch[8];
            if (std::fread(ch, 1, 8, fp) != 8) break;
            uint32_t csz = (uint32_t)ch[4] | ((uint32_t)ch[5] << 8) |
                           ((uint32_t)ch[6] << 16) | ((uint32_t)ch[7] << 24);

            if (std::memcmp(ch, "fmt ", 4) == 0) {
                if (csz < 16) break;
                unsigned char fmt[16];
                if (std::fread(fmt, 1, 16, fp) != 16) break;
                audioFmt = (uint16_t)(fmt[0] | (fmt[1] << 8));
                nch      = (uint16_t)(fmt[2] | (fmt[3] << 8));
                bps      = (uint16_t)(fmt[14] | (fmt[15] << 8));
                if (csz > 16) std::fseek(fp, (long)(csz - 16), SEEK_CUR);
                gotFmt = true;
            } else if (std::memcmp(ch, "data", 4) == 0) {
                dataSz = csz;
                gotData = true;
            } else {
                std::fseek(fp, (long)(csz + (csz & 1)), SEEK_CUR);
            }
        }

        if (!gotFmt || !gotData || nch == 0 || bps == 0 || dataSz == 0) {
            std::fclose(fp);
            return -1;
        }

        long bytesPerSample = bps / 8;
        long frames = (long)(dataSz / (nch * bytesPerSample));
        allocate(frames, nch);

        long total = frames * nch;
        if (audioFmt == 1 && bps == 16) {
            for (long i = 0; i < total; i++) {
                unsigned char b[2];
                if (std::fread(b, 1, 2, fp) != 2) break;
                int16_t s = (int16_t)((uint16_t)b[0] | ((uint16_t)b[1] << 8));
                mData[i] = (t_sample)s / 32768.0f;
            }
        } else if (audioFmt == 1 && bps == 24) {
            for (long i = 0; i < total; i++) {
                unsigned char b[3];
                if (std::fread(b, 1, 3, fp) != 3) break;
                int32_t s = (int32_t)((uint32_t)b[2] << 24 |
                                      (uint32_t)b[1] << 16 |
                                      (uint32_t)b[0] << 8) >> 8;
                mData[i] = (t_sample)s / 8388608.0f;
            }
        } else if (audioFmt == 3 && bps == 32) {
            // IEEE float -- assumes little-endian platform
            std::fread(mData, sizeof(t_sample), total, fp);
        } else {
            std::fclose(fp);
            return -1;
        }

        modified = 1;
        std::fclose(fp);
        return (int)frames;
    }

private:
    t_sample* mOwnedData = nullptr;  // Owned buffer data
};

#endif // CHUCK_BUFFER_H
