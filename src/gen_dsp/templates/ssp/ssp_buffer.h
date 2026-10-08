// ssp_buffer.h - gen~ buffers for the SSP (genlib side, no SSP headers)
//
// gen~ code names each buffer as a global. _ext_ssp.cpp redirects each name to a view
// owned by the instance being run, so instances do not share buffers and may run on
// different threads.
#ifndef SSP_BUFFER_H
#define SSP_BUFFER_H

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "genlib.h"

// Decoded audio, interleaved frame by frame.
struct SspBufferData {
    std::vector<t_sample> samples;
    long frames = 0;
    long channels = 1;
    SspBufferData* next = nullptr;  // in SspBufferSlot::retired
};

// Reads a RIFF WAVE file: PCM 16/24-bit or IEEE float 32-bit. Returns nullptr on error.
static inline SspBufferData* ssp_read_wav(const char* path) {
    FILE* fp = std::fopen(path, "rb");
    if (!fp) return nullptr;
    unsigned char hdr[12];
    if (std::fread(hdr, 1, 12, fp) != 12 || std::memcmp(hdr, "RIFF", 4) != 0 || std::memcmp(hdr + 8, "WAVE", 4) != 0) {
        std::fclose(fp);
        return nullptr;
    }
    uint16_t fmt = 0, nch = 0, bps = 0;
    uint32_t size = 0;
    bool gotFmt = false, gotData = false;
    while (!gotData) {
        unsigned char ch[8];
        if (std::fread(ch, 1, 8, fp) != 8) break;
        uint32_t csz = uint32_t(ch[4]) | uint32_t(ch[5]) << 8 | uint32_t(ch[6]) << 16 | uint32_t(ch[7]) << 24;
        if (std::memcmp(ch, "fmt ", 4) == 0) {
            unsigned char f[16];
            if (csz < 16 || std::fread(f, 1, 16, fp) != 16) break;
            fmt = uint16_t(f[0] | f[1] << 8);
            nch = uint16_t(f[2] | f[3] << 8);
            bps = uint16_t(f[14] | f[15] << 8);
            long rest = long(csz) - 16;
            // WAVE_FORMAT_EXTENSIBLE: the subformat GUID's first two bytes give the real format
            if (fmt == 0xFFFE && rest >= 10) {
                unsigned char ext[10];
                if (std::fread(ext, 1, 10, fp) != 10) break;
                fmt = uint16_t(ext[8] | ext[9] << 8);
                rest -= 10;
            }
            std::fseek(fp, rest + long(csz & 1), SEEK_CUR);
            gotFmt = true;
        } else if (std::memcmp(ch, "data", 4) == 0) {
            size = csz;
            gotData = true;
        } else {
            std::fseek(fp, long(csz + (csz & 1)), SEEK_CUR);
        }
    }
    bool pcm16 = fmt == 1 && bps == 16, pcm24 = fmt == 1 && bps == 24, float32 = fmt == 3 && bps == 32;
    if (!gotFmt || !gotData || nch == 0 || !(pcm16 || pcm24 || float32)) {
        std::fclose(fp);
        return nullptr;
    }
    size_t width = bps / 8;
    auto* d = new SspBufferData;
    d->channels = nch;
    d->frames = long(size / (nch * width));
    d->samples.resize(size_t(d->frames) * nch);
    std::vector<unsigned char> raw(d->samples.size() * width);
    // a truncated file keeps the samples it has; the rest stay zero
    size_t got = std::fread(raw.data(), 1, raw.size(), fp) / width;
    std::fclose(fp);
    const unsigned char* b = raw.data();
    for (size_t i = 0; i < got; i++, b += width) {
        if (pcm16) {
            d->samples[i] = t_sample(int16_t(uint16_t(b[0] | b[1] << 8))) / 32768.0f;
        } else if (pcm24) {
            int32_t s = int32_t(uint32_t(b[2]) << 24 | uint32_t(b[1]) << 16 | uint32_t(b[0]) << 8) >> 8;
            d->samples[i] = t_sample(s) / 8388608.0f;
        } else {
            uint32_t u = uint32_t(b[0]) | uint32_t(b[1]) << 8 | uint32_t(b[2]) << 16 | uint32_t(b[3]) << 24;
            float f;
            std::memcpy(&f, &u, 4);
            d->samples[i] = t_sample(f);
        }
    }
    return d;
}

// What gen~ code sees as a buffer. Reads and writes outside the data are ignored.
struct SspBufferView : public DataInterface<t_sample> {
    void bind(const SspBufferData* d) {
        mData = d ? const_cast<t_sample*>(d->samples.data()) : nullptr;
        dim = d ? d->frames : 0;
        channels = d ? d->channels : 1;
    }

    inline t_sample read(long index, long channel = 0) const {
        if (!mData || index < 0 || index >= dim || channel < 0 || channel >= channels) return 0;
        return mData[index * channels + channel];
    }

    inline void write(t_sample value, long index, long channel = 0) {
        if (!mData || index < 0 || index >= dim || channel < 0 || channel >= channels) return;
        mData[index * channels + channel] = value;
        modified = 1;
    }

    inline void blend(t_sample value, long index, long channel, t_sample alpha) {
        if (!mData || index < 0 || index >= dim || channel < 0 || channel >= channels) return;
        long offset = index * channels + channel;
        mData[offset] += alpha * (value - mData[offset]);
        modified = 1;
    }
};

// One buffer of one instance. A loader thread publishes data; the audio thread adopts it at
// the start of a block. Data is freed only off the audio thread.
struct SspBufferSlot {
    SspBufferData* current = nullptr;  // audio thread
    std::atomic<SspBufferData*> pending{ nullptr };
    // Data the audio thread replaced: a list it only pushes to and the loader only empties,
    // so a push needs no allocation and a pop-all cannot suffer ABA.
    std::atomic<SspBufferData*> retired{ nullptr };

    ~SspBufferSlot() {
        delete current;
        delete pending.load();
        freeRetired();
    }

    // Loader thread, one at a time.
    void publish(SspBufferData* d) {
        freeRetired();
        delete pending.exchange(d);  // a load the audio thread never adopted
    }

    // Audio thread.
    const SspBufferData* adopt() {
        if (SspBufferData* d = pending.exchange(nullptr)) {
            if (current) {
                current->next = retired.load();
                while (!retired.compare_exchange_weak(current->next, current)) {
                }
            }
            current = d;
        }
        return current;
    }

private:
    void freeRetired() {
        for (SspBufferData* d = retired.exchange(nullptr); d;) {
            SspBufferData* next = d->next;
            delete d;
            d = next;
        }
    }
};

#endif  // SSP_BUFFER_H
