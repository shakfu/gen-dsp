// gen_ext_au.cpp - AudioUnit v2 wrapper for gen~ exports
// This file includes ONLY AudioUnit/system headers - genlib is isolated in _ext_au.cpp
//
// Implements AUv2 via the raw C API (AudioComponentPlugInInterface) which is
// stable since macOS 10.7 and requires only system frameworks. No external SDK
// dependencies are needed.
//
// The plugin registers via AudioComponentFactoryFunction (Info.plist entry point).
// The host calls Open/Close on the interface, and Lookup to obtain function
// pointers for each AU selector (Initialize, GetProperty, Render, etc.).

#include <AudioToolbox/AudioToolbox.h>
#include <CoreFoundation/CoreFoundation.h>

#include "gen_ext_common_au.h"
#include "_ext_au.h"

#include <cstring>
#include <cstdlib>
#include <cstdio>

using namespace WRAPPER_NAMESPACE;

// ---------------------------------------------------------------------------
// Polyphony support (NUM_VOICES > 1) or monophonic MIDI helpers
// ---------------------------------------------------------------------------

#ifdef MIDI_ENABLED
#include <cmath>

#if NUM_VOICES > 1
#include "voice_alloc.h"
#else
static inline float mtof(int note) {
    return 440.0f * powf(2.0f, (note - 69) / 12.0f);
}

static inline void handle_note_on(GenState* state, int key, float velocity) {
    (void)velocity;
#ifdef MIDI_GATE_IDX
    wrapper_set_param(state, MIDI_GATE_IDX, 1.0f);
#endif
#ifdef MIDI_FREQ_IDX
#if MIDI_FREQ_UNIT_HZ
    wrapper_set_param(state, MIDI_FREQ_IDX, mtof(key));
#else
    wrapper_set_param(state, MIDI_FREQ_IDX, (float)key);
#endif
#endif
#ifdef MIDI_VEL_IDX
    wrapper_set_param(state, MIDI_VEL_IDX, velocity);
#endif
}

static inline void handle_note_off(GenState* state) {
#ifdef MIDI_GATE_IDX
    wrapper_set_param(state, MIDI_GATE_IDX, 0.0f);
#endif
}
#endif // NUM_VOICES > 1
#endif // MIDI_ENABLED

// Maximum number of parameters we support for save/restore
static const int kMaxParams = 256;
// Maximum number of property listeners
static const int kMaxListeners = 32;

// ---------------------------------------------------------------------------
// Plugin state
// ---------------------------------------------------------------------------

struct PropertyListener {
    AudioUnitPropertyID property;
    AudioUnitPropertyListenerProc proc;
    void* refCon;
};

struct AUGenPlugin {
    AudioComponentPlugInInterface interface;  // must be first member
    AudioComponentInstance       instance;
    Float64                      sampleRate;
    UInt32                       maxFramesPerSlice;
#if NUM_VOICES > 1
    VoiceAllocator               voiceAlloc;
#else
    GenState*                    genState;
#endif
    int                          numInputs;
    int                          numOutputs;
    int                          numParams;
    float**                      inBuffers;
    float**                      outBuffers;
    AURenderCallbackStruct       inputCallback;
    bool                         initialized;

    // Component description (from factory)
    UInt32                       componentType;
    UInt32                       componentSubType;
    UInt32                       componentManufacturer;

    // Current preset
    SInt32                       currentPresetNumber;

    // Property listeners
    PropertyListener             listeners[kMaxListeners];
    int                          numListeners;

    // AU-to-AU connection (alternative to render callback)
    AudioUnitConnection          connection;
    bool                         hasConnection;

    // Stream format (same for input and output)
    AudioStreamBasicDescription  streamFormat;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static void InitStreamFormat(AudioStreamBasicDescription* fmt, Float64 sr, UInt32 channels) {
    memset(fmt, 0, sizeof(AudioStreamBasicDescription));
    fmt->mSampleRate       = sr;
    fmt->mFormatID         = kAudioFormatLinearPCM;
    fmt->mFormatFlags      = kAudioFormatFlagIsFloat
                           | kAudioFormatFlagIsPacked
                           | kAudioFormatFlagIsNonInterleaved;
    fmt->mBytesPerPacket   = sizeof(Float32);
    fmt->mFramesPerPacket  = 1;
    fmt->mBytesPerFrame    = sizeof(Float32);
    fmt->mChannelsPerFrame = channels;
    fmt->mBitsPerChannel   = sizeof(Float32) * 8;
}

static void AllocateBuffers(float*** buffers, int count) {
    if (count <= 0) {
        *buffers = nullptr;
        return;
    }
    *buffers = (float**)calloc((size_t)count, sizeof(float*));
}

static void FreeBuffers(float** buffers, int count) {
    if (!buffers) return;
    for (int i = 0; i < count; i++) {
        free(buffers[i]);
    }
    free(buffers);
}

static void AllocateBufferFrames(float** buffers, int count, UInt32 frames) {
    if (!buffers) return;
    for (int i = 0; i < count; i++) {
        free(buffers[i]);
        buffers[i] = (float*)calloc(frames, sizeof(float));
    }
}

// Save current parameter values from gen state into array
static void SaveParams(AUGenPlugin* plug, float* saved, int count) {
#if NUM_VOICES > 1
    if (!plug->voiceAlloc.states[0]) return;
    for (int i = 0; i < count && i < kMaxParams; i++) {
        saved[i] = wrapper_get_param(plug->voiceAlloc.states[0], i);
    }
#else
    if (!plug->genState) return;
    for (int i = 0; i < count && i < kMaxParams; i++) {
        saved[i] = wrapper_get_param(plug->genState, i);
    }
#endif
}

// Restore parameter values from array into gen state
static void RestoreParams(AUGenPlugin* plug, const float* saved, int count) {
#if NUM_VOICES > 1
    for (int i = 0; i < count && i < kMaxParams; i++) {
        voice_alloc_set_global_param(&plug->voiceAlloc, i, saved[i]);
    }
#else
    if (!plug->genState) return;
    for (int i = 0; i < count && i < kMaxParams; i++) {
        wrapper_set_param(plug->genState, i, saved[i]);
    }
#endif
}

// Fire property change notifications to all registered listeners
static void FirePropertyChanged(AUGenPlugin* plug, AudioUnitPropertyID prop,
                                AudioUnitScope scope, AudioUnitElement elem) {
    for (int i = 0; i < plug->numListeners; i++) {
        if (plug->listeners[i].property == prop) {
            plug->listeners[i].proc(
                plug->listeners[i].refCon, plug->instance,
                prop, scope, elem);
        }
    }
}

// ---------------------------------------------------------------------------
// Open / Close
// ---------------------------------------------------------------------------

static OSStatus AUGenOpen(void* self, AudioUnit instance) {
    AUGenPlugin* plug = (AUGenPlugin*)self;
    plug->instance = instance;
    return noErr;
}

static OSStatus AUGenClose(void* self) {
    AUGenPlugin* plug = (AUGenPlugin*)self;
#if NUM_VOICES > 1
    voice_alloc_destroy(&plug->voiceAlloc);
#else
    if (plug->genState) {
        wrapper_destroy(plug->genState);
        plug->genState = nullptr;
    }
#endif
    FreeBuffers(plug->inBuffers, plug->numInputs);
    FreeBuffers(plug->outBuffers, plug->numOutputs);
    plug->inBuffers = nullptr;
    plug->outBuffers = nullptr;
    free(plug);
    return noErr;
}

// ---------------------------------------------------------------------------
// Initialize / Uninitialize
// ---------------------------------------------------------------------------

static OSStatus AUGenInitialize(void* self) {
    AUGenPlugin* plug = (AUGenPlugin*)self;

    // Save parameter values across re-initialization
    float savedParams[kMaxParams];
#if NUM_VOICES > 1
    bool hasParams = plug->voiceAlloc.states[0] && plug->numParams > 0;
#else
    bool hasParams = plug->genState && plug->numParams > 0;
#endif
    if (hasParams) {
        SaveParams(plug, savedParams, plug->numParams);
    }

#if NUM_VOICES > 1
    voice_alloc_init(&plug->voiceAlloc, plug->numOutputs, (long)plug->maxFramesPerSlice);
    voice_alloc_create_voices(&plug->voiceAlloc, (float)plug->sampleRate, (long)plug->maxFramesPerSlice);
    if (!plug->voiceAlloc.states[0]) {
        return kAudioUnitErr_FailedInitialization;
    }
#else
    if (plug->genState) {
        wrapper_destroy(plug->genState);
    }

    plug->genState = wrapper_create((float)plug->sampleRate, (long)plug->maxFramesPerSlice);
    if (!plug->genState) {
        return kAudioUnitErr_FailedInitialization;
    }
#endif

    // Restore parameter values
    if (hasParams) {
        RestoreParams(plug, savedParams, plug->numParams);
    }

    // Allocate per-channel I/O buffers
    FreeBuffers(plug->inBuffers, plug->numInputs);
    FreeBuffers(plug->outBuffers, plug->numOutputs);

    AllocateBuffers(&plug->inBuffers, plug->numInputs);
    AllocateBuffers(&plug->outBuffers, plug->numOutputs);

    AllocateBufferFrames(plug->inBuffers, plug->numInputs, plug->maxFramesPerSlice);
    AllocateBufferFrames(plug->outBuffers, plug->numOutputs, plug->maxFramesPerSlice);

    plug->initialized = true;
    return noErr;
}

static OSStatus AUGenUninitialize(void* self) {
    AUGenPlugin* plug = (AUGenPlugin*)self;

    FreeBuffers(plug->inBuffers, plug->numInputs);
    FreeBuffers(plug->outBuffers, plug->numOutputs);
    plug->inBuffers = nullptr;
    plug->outBuffers = nullptr;

    // Keep genState alive for parameter queries while uninitialized
    plug->initialized = false;
    return noErr;
}

// ---------------------------------------------------------------------------
// GetPropertyInfo
// ---------------------------------------------------------------------------

static OSStatus AUGenGetPropertyInfo(void* self,
                                     AudioUnitPropertyID prop,
                                     AudioUnitScope scope,
                                     AudioUnitElement elem,
                                     UInt32* outDataSize,
                                     Boolean* outWritable) {
    (void)self;

    switch (prop) {
        case kAudioUnitProperty_StreamFormat:
            if (outDataSize) *outDataSize = sizeof(AudioStreamBasicDescription);
            if (outWritable) *outWritable = true;
            return noErr;

        case kAudioUnitProperty_SupportedNumChannels: {
            if (outDataSize) *outDataSize = sizeof(AUChannelInfo);
            if (outWritable) *outWritable = false;
            return noErr;
        }

        case kAudioUnitProperty_ParameterList: {
            AUGenPlugin* plug = (AUGenPlugin*)self;
            if (scope == kAudioUnitScope_Global) {
                if (outDataSize) *outDataSize = (UInt32)(plug->numParams * sizeof(AudioUnitParameterID));
                if (outWritable) *outWritable = false;
                return noErr;
            }
            if (outDataSize) *outDataSize = 0;
            if (outWritable) *outWritable = false;
            return noErr;
        }

        case kAudioUnitProperty_ParameterInfo:
            if (scope == kAudioUnitScope_Global) {
                if (outDataSize) *outDataSize = sizeof(AudioUnitParameterInfo);
                if (outWritable) *outWritable = false;
                return noErr;
            }
            return kAudioUnitErr_InvalidProperty;

        case kAudioUnitProperty_MaximumFramesPerSlice:
            if (outDataSize) *outDataSize = sizeof(UInt32);
            if (outWritable) *outWritable = true;
            return noErr;

        case kAudioUnitProperty_Latency:
        case kAudioUnitProperty_TailTime:
            if (scope != kAudioUnitScope_Global)
                return kAudioUnitErr_InvalidProperty;
            if (outDataSize) *outDataSize = sizeof(Float64);
            if (outWritable) *outWritable = false;
            return noErr;

        case kAudioUnitProperty_ElementCount:
            if (outDataSize) *outDataSize = sizeof(UInt32);
            if (outWritable) *outWritable = false;
            return noErr;

        case kAudioUnitProperty_ShouldAllocateBuffer:
            if (outDataSize) *outDataSize = sizeof(UInt32);
            if (outWritable) *outWritable = true;
            return noErr;

        case kAudioUnitProperty_SetRenderCallback:
            if (outDataSize) *outDataSize = sizeof(AURenderCallbackStruct);
            if (outWritable) *outWritable = true;
            return noErr;

        case kAudioUnitProperty_FactoryPresets:
            if (outDataSize) *outDataSize = sizeof(CFArrayRef);
            if (outWritable) *outWritable = false;
            return noErr;

        case kAudioUnitProperty_PresentPreset:
            if (outDataSize) *outDataSize = sizeof(AUPreset);
            if (outWritable) *outWritable = true;
            return noErr;

        case kAudioUnitProperty_ClassInfo:
            if (outDataSize) *outDataSize = sizeof(CFPropertyListRef);
            if (outWritable) *outWritable = true;
            return noErr;

        case kAudioUnitProperty_MakeConnection:
            if (outDataSize) *outDataSize = sizeof(AudioUnitConnection);
            if (outWritable) *outWritable = true;
            return noErr;

        default:
            return kAudioUnitErr_InvalidProperty;
    }
}

// ---------------------------------------------------------------------------
// ClassInfo helpers (state save/restore)
// ---------------------------------------------------------------------------

// 4-byte magic so RestoreClassInfo rejects empty/invalid data blobs
static const uint32_t kStateMagic = 0x47445350; // "GDSP"

static CFMutableDictionaryRef CreateClassInfo(AUGenPlugin* plug) {
    CFMutableDictionaryRef dict = CFDictionaryCreateMutable(
        kCFAllocatorDefault, 0,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);

    // Standard AU state keys
    SInt32 version = 0;
    CFNumberRef versionNum = CFNumberCreate(kCFAllocatorDefault, kCFNumberSInt32Type, &version);
    CFDictionarySetValue(dict, CFSTR("version"), versionNum);
    CFRelease(versionNum);

    SInt32 typeVal = (SInt32)plug->componentType;
    CFNumberRef typeNum = CFNumberCreate(kCFAllocatorDefault, kCFNumberSInt32Type, &typeVal);
    CFDictionarySetValue(dict, CFSTR("type"), typeNum);
    CFRelease(typeNum);

    SInt32 subtypeVal = (SInt32)plug->componentSubType;
    CFNumberRef subtypeNum = CFNumberCreate(kCFAllocatorDefault, kCFNumberSInt32Type, &subtypeVal);
    CFDictionarySetValue(dict, CFSTR("subtype"), subtypeNum);
    CFRelease(subtypeNum);

    SInt32 mfrVal = (SInt32)plug->componentManufacturer;
    CFNumberRef mfrNum = CFNumberCreate(kCFAllocatorDefault, kCFNumberSInt32Type, &mfrVal);
    CFDictionarySetValue(dict, CFSTR("manufacturer"), mfrNum);
    CFRelease(mfrNum);

    CFDictionarySetValue(dict, CFSTR("name"), CFSTR(""));

    // Store parameter values as CFData blob: magic + float per param
#if NUM_VOICES > 1
    GenState* saveState = plug->voiceAlloc.states[0];
#else
    GenState* saveState = plug->genState;
#endif
    {
        int nParams = (saveState && plug->numParams > 0)
            ? (plug->numParams < kMaxParams ? plug->numParams : kMaxParams)
            : 0;
        CFIndex blobSize = (CFIndex)(sizeof(uint32_t) + nParams * sizeof(float));
        uint8_t blob[sizeof(uint32_t) + kMaxParams * sizeof(float)];
        memcpy(blob, &kStateMagic, sizeof(uint32_t));
        float* values = (float*)(blob + sizeof(uint32_t));
        for (int i = 0; i < nParams; i++) {
            values[i] = wrapper_get_param(saveState, i);
        }
        CFDataRef data = CFDataCreate(kCFAllocatorDefault, blob, blobSize);
        CFDictionarySetValue(dict, CFSTR("data"), data);
        CFRelease(data);
    }

    return dict;
}

static OSStatus RestoreClassInfo(AUGenPlugin* plug, CFPropertyListRef plist) {
    if (CFGetTypeID(plist) != CFDictionaryGetTypeID())
        return kAudioUnitErr_InvalidPropertyValue;

    CFDictionaryRef dict = (CFDictionaryRef)plist;

    // Restore parameter values from data blob
    CFDataRef data = nullptr;
    if (CFDictionaryGetValueIfPresent(dict, CFSTR("data"), (const void**)&data) &&
        data && CFGetTypeID(data) == CFDataGetTypeID()) {
        CFIndex dataSize = CFDataGetLength(data);
        const uint8_t* bytes = CFDataGetBytePtr(data);

        // Validate magic header
        if (dataSize < (CFIndex)sizeof(uint32_t))
            return kAudioUnitErr_InvalidPropertyValue;
        uint32_t magic;
        memcpy(&magic, bytes, sizeof(uint32_t));
        if (magic != kStateMagic)
            return kAudioUnitErr_InvalidPropertyValue;

        int nParams = plug->numParams < kMaxParams ? plug->numParams : kMaxParams;
        const float* values = (const float*)(bytes + sizeof(uint32_t));
        CFIndex available = (dataSize - (CFIndex)sizeof(uint32_t)) / (CFIndex)sizeof(float);

#if NUM_VOICES > 1
        for (int i = 0; i < nParams && i < (int)available; i++) {
            voice_alloc_set_global_param(&plug->voiceAlloc, i, values[i]);
        }
#else
        if (plug->genState) {
            for (int i = 0; i < nParams && i < (int)available; i++) {
                wrapper_set_param(plug->genState, i, values[i]);
            }
        }
#endif
    }

    return noErr;
}

// ---------------------------------------------------------------------------
// GetProperty
// ---------------------------------------------------------------------------

static OSStatus AUGenGetProperty(void* self,
                                 AudioUnitPropertyID prop,
                                 AudioUnitScope scope,
                                 AudioUnitElement elem,
                                 void* outData,
                                 UInt32* ioDataSize) {
    AUGenPlugin* plug = (AUGenPlugin*)self;

    switch (prop) {
        case kAudioUnitProperty_StreamFormat: {
            if (*ioDataSize < sizeof(AudioStreamBasicDescription))
                return kAudioUnitErr_InvalidPropertyValue;

            AudioStreamBasicDescription* fmt = (AudioStreamBasicDescription*)outData;
            if (scope == kAudioUnitScope_Input && plug->numInputs > 0) {
                InitStreamFormat(fmt, plug->sampleRate, (UInt32)plug->numInputs);
            } else if (scope == kAudioUnitScope_Output) {
                InitStreamFormat(fmt, plug->sampleRate, (UInt32)plug->numOutputs);
            } else {
                *fmt = plug->streamFormat;
            }
            *ioDataSize = sizeof(AudioStreamBasicDescription);
            return noErr;
        }

        case kAudioUnitProperty_SupportedNumChannels: {
            if (*ioDataSize < sizeof(AUChannelInfo))
                return kAudioUnitErr_InvalidPropertyValue;

            AUChannelInfo* info = (AUChannelInfo*)outData;
            info->inChannels  = (SInt16)plug->numInputs;
            info->outChannels = (SInt16)plug->numOutputs;
            *ioDataSize = sizeof(AUChannelInfo);
            return noErr;
        }

        case kAudioUnitProperty_ParameterList: {
            if (scope == kAudioUnitScope_Global) {
                UInt32 needed = (UInt32)(plug->numParams * sizeof(AudioUnitParameterID));
                if (*ioDataSize < needed)
                    return kAudioUnitErr_InvalidPropertyValue;

                AudioUnitParameterID* ids = (AudioUnitParameterID*)outData;
                for (int i = 0; i < plug->numParams; i++) {
                    ids[i] = (AudioUnitParameterID)i;
                }
                *ioDataSize = needed;
                return noErr;
            }
            *ioDataSize = 0;
            return noErr;
        }

        case kAudioUnitProperty_ParameterInfo: {
            if (scope != kAudioUnitScope_Global)
                return kAudioUnitErr_InvalidProperty;
            if ((int)elem >= plug->numParams)
                return kAudioUnitErr_InvalidParameter;
            if (*ioDataSize < sizeof(AudioUnitParameterInfo))
                return kAudioUnitErr_InvalidPropertyValue;

            AudioUnitParameterInfo* info = (AudioUnitParameterInfo*)outData;
            memset(info, 0, sizeof(AudioUnitParameterInfo));

            // Get parameter metadata from gen~ wrapper
#if NUM_VOICES > 1
            GenState* queryState = plug->voiceAlloc.states[0];
#else
            GenState* queryState = plug->genState;
#endif
            const char* pname = queryState
                ? wrapper_param_name(queryState, (int)elem)
                : nullptr;
            if (pname) {
                info->cfNameString = CFStringCreateWithCString(
                    kCFAllocatorDefault, pname, kCFStringEncodingUTF8);
                info->flags |= kAudioUnitParameterFlag_HasCFNameString;
                strncpy(info->name, pname, sizeof(info->name) - 1);
                info->name[sizeof(info->name) - 1] = '\0';
            }

            info->unit = kAudioUnitParameterUnit_Generic;
            info->flags |= kAudioUnitParameterFlag_IsReadable
                         | kAudioUnitParameterFlag_IsWritable;

            if (queryState && wrapper_param_hasminmax(queryState, (int)elem)) {
                info->minValue     = wrapper_param_min(queryState, (int)elem);
                info->maxValue     = wrapper_param_max(queryState, (int)elem);
                float pdefault     = wrapper_get_param(queryState, (int)elem);
                // Clamp default to [min, max] -- gen~ initial values may exceed
                // the declared range (e.g. gigaverb revtime init=11, max=1)
                if (pdefault < info->minValue) pdefault = info->minValue;
                if (pdefault > info->maxValue) pdefault = info->maxValue;
                info->defaultValue = pdefault;
            } else {
                info->minValue     = 0.0f;
                info->maxValue     = 1.0f;
                info->defaultValue = 0.0f;
            }

            *ioDataSize = sizeof(AudioUnitParameterInfo);
            return noErr;
        }

        case kAudioUnitProperty_MaximumFramesPerSlice: {
            if (*ioDataSize < sizeof(UInt32))
                return kAudioUnitErr_InvalidPropertyValue;
            *(UInt32*)outData = plug->maxFramesPerSlice;
            *ioDataSize = sizeof(UInt32);
            return noErr;
        }

        case kAudioUnitProperty_Latency: {
            if (scope != kAudioUnitScope_Global)
                return kAudioUnitErr_InvalidProperty;
            if (*ioDataSize < sizeof(Float64))
                return kAudioUnitErr_InvalidPropertyValue;
            *(Float64*)outData = 0.0;
            *ioDataSize = sizeof(Float64);
            return noErr;
        }

        case kAudioUnitProperty_TailTime: {
            if (scope != kAudioUnitScope_Global)
                return kAudioUnitErr_InvalidProperty;
            if (*ioDataSize < sizeof(Float64))
                return kAudioUnitErr_InvalidPropertyValue;
            *(Float64*)outData = 0.0;
            *ioDataSize = sizeof(Float64);
            return noErr;
        }

        case kAudioUnitProperty_ElementCount: {
            if (*ioDataSize < sizeof(UInt32))
                return kAudioUnitErr_InvalidPropertyValue;
            if (scope == kAudioUnitScope_Input) {
                *(UInt32*)outData = (plug->numInputs > 0) ? 1 : 0;
            } else if (scope == kAudioUnitScope_Output) {
                *(UInt32*)outData = 1;
            } else if (scope == kAudioUnitScope_Global) {
                *(UInt32*)outData = 1;
            } else {
                *(UInt32*)outData = 0;
            }
            *ioDataSize = sizeof(UInt32);
            return noErr;
        }

        case kAudioUnitProperty_ShouldAllocateBuffer: {
            if (*ioDataSize < sizeof(UInt32))
                return kAudioUnitErr_InvalidPropertyValue;
            *(UInt32*)outData = 1;  // yes, host should allocate buffers
            *ioDataSize = sizeof(UInt32);
            return noErr;
        }

        case kAudioUnitProperty_FactoryPresets: {
            // Return empty array (no presets)
            CFArrayRef empty = CFArrayCreate(kCFAllocatorDefault, nullptr, 0, nullptr);
            *(CFArrayRef*)outData = empty;
            *ioDataSize = sizeof(CFArrayRef);
            return noErr;
        }

        case kAudioUnitProperty_PresentPreset: {
            if (*ioDataSize < sizeof(AUPreset))
                return kAudioUnitErr_InvalidPropertyValue;
            AUPreset* preset = (AUPreset*)outData;
            preset->presetNumber = plug->currentPresetNumber;
            preset->presetName = CFSTR("Untitled");
            CFRetain(preset->presetName);
            *ioDataSize = sizeof(AUPreset);
            return noErr;
        }

        case kAudioUnitProperty_ClassInfo: {
            if (*ioDataSize < sizeof(CFPropertyListRef))
                return kAudioUnitErr_InvalidPropertyValue;
            *(CFPropertyListRef*)outData = CreateClassInfo(plug);
            *ioDataSize = sizeof(CFPropertyListRef);
            return noErr;
        }

        default:
            return kAudioUnitErr_InvalidProperty;
    }
}

// ---------------------------------------------------------------------------
// SetProperty
// ---------------------------------------------------------------------------

static OSStatus AUGenSetProperty(void* self,
                                 AudioUnitPropertyID prop,
                                 AudioUnitScope scope,
                                 AudioUnitElement elem,
                                 const void* inData,
                                 UInt32 inDataSize) {
    AUGenPlugin* plug = (AUGenPlugin*)self;

    switch (prop) {
        case kAudioUnitProperty_StreamFormat: {
            if (inDataSize < sizeof(AudioStreamBasicDescription))
                return kAudioUnitErr_InvalidPropertyValue;

            const AudioStreamBasicDescription* fmt =
                (const AudioStreamBasicDescription*)inData;

            // Only accept Float32 non-interleaved LPCM
            if (fmt->mFormatID != kAudioFormatLinearPCM)
                return kAudioUnitErr_FormatNotSupported;
            if (!(fmt->mFormatFlags & kAudioFormatFlagIsFloat))
                return kAudioUnitErr_FormatNotSupported;
            if (!(fmt->mFormatFlags & kAudioFormatFlagIsNonInterleaved))
                return kAudioUnitErr_FormatNotSupported;

            // Validate channel count matches our fixed configuration
            if (scope == kAudioUnitScope_Input) {
                if ((int)fmt->mChannelsPerFrame != plug->numInputs)
                    return kAudioUnitErr_FormatNotSupported;
            } else if (scope == kAudioUnitScope_Output) {
                if ((int)fmt->mChannelsPerFrame != plug->numOutputs)
                    return kAudioUnitErr_FormatNotSupported;
            }

            plug->sampleRate = fmt->mSampleRate;
            plug->streamFormat = *fmt;
            return noErr;
        }

        case kAudioUnitProperty_MaximumFramesPerSlice: {
            if (inDataSize < sizeof(UInt32))
                return kAudioUnitErr_InvalidPropertyValue;

            UInt32 newMax = *(const UInt32*)inData;
            plug->maxFramesPerSlice = newMax;

            // Recreate gen state and reallocate buffers if already initialized
            if (plug->initialized) {
                float savedParams[kMaxParams];
#if NUM_VOICES > 1
                bool hasParams = plug->voiceAlloc.states[0] && plug->numParams > 0;
#else
                bool hasParams = plug->genState && plug->numParams > 0;
#endif
                if (hasParams) SaveParams(plug, savedParams, plug->numParams);

#if NUM_VOICES > 1
                voice_alloc_init(&plug->voiceAlloc, plug->numOutputs, (long)newMax);
                voice_alloc_create_voices(&plug->voiceAlloc, (float)plug->sampleRate, (long)newMax);
                if (hasParams) RestoreParams(plug, savedParams, plug->numParams);
#else
                if (plug->genState) wrapper_destroy(plug->genState);
                plug->genState = wrapper_create((float)plug->sampleRate, (long)newMax);
                if (hasParams && plug->genState) RestoreParams(plug, savedParams, plug->numParams);
#endif

                AllocateBufferFrames(plug->inBuffers, plug->numInputs, newMax);
                AllocateBufferFrames(plug->outBuffers, plug->numOutputs, newMax);
            }

            FirePropertyChanged(plug, kAudioUnitProperty_MaximumFramesPerSlice,
                                kAudioUnitScope_Global, 0);
            return noErr;
        }

        case kAudioUnitProperty_SetRenderCallback: {
            if (inDataSize < sizeof(AURenderCallbackStruct))
                return kAudioUnitErr_InvalidPropertyValue;

            plug->inputCallback = *(const AURenderCallbackStruct*)inData;
            return noErr;
        }

        case kAudioUnitProperty_ShouldAllocateBuffer:
            return noErr;

        case kAudioUnitProperty_PresentPreset: {
            if (inDataSize < sizeof(AUPreset))
                return kAudioUnitErr_InvalidPropertyValue;
            const AUPreset* preset = (const AUPreset*)inData;
            plug->currentPresetNumber = preset->presetNumber;
            return noErr;
        }

        case kAudioUnitProperty_ClassInfo: {
            if (inDataSize < sizeof(CFPropertyListRef))
                return kAudioUnitErr_InvalidPropertyValue;
            CFPropertyListRef plist = *(const CFPropertyListRef*)inData;
            return RestoreClassInfo(plug, plist);
        }

        case kAudioUnitProperty_MakeConnection: {
            if (inDataSize < sizeof(AudioUnitConnection))
                return kAudioUnitErr_InvalidPropertyValue;
            plug->connection = *(const AudioUnitConnection*)inData;
            plug->hasConnection = (plug->connection.sourceAudioUnit != nullptr);
            return noErr;
        }

        default:
            return kAudioUnitErr_InvalidProperty;
    }
}

// ---------------------------------------------------------------------------
// Get/Set Parameter
// ---------------------------------------------------------------------------

static OSStatus AUGenGetParameter(void* self,
                                  AudioUnitParameterID param,
                                  AudioUnitScope scope,
                                  AudioUnitElement elem,
                                  AudioUnitParameterValue* outValue) {
    AUGenPlugin* plug = (AUGenPlugin*)self;

    if (scope != kAudioUnitScope_Global)
        return kAudioUnitErr_InvalidParameter;
    if ((int)param >= plug->numParams)
        return kAudioUnitErr_InvalidParameter;

#if NUM_VOICES > 1
    if (!plug->voiceAlloc.states[0])
        return kAudioUnitErr_Uninitialized;
    *outValue = voice_alloc_get_param(&plug->voiceAlloc, (int)param);
#else
    if (!plug->genState)
        return kAudioUnitErr_Uninitialized;
    *outValue = wrapper_get_param(plug->genState, (int)param);
#endif
    return noErr;
}

static OSStatus AUGenSetParameter(void* self,
                                  AudioUnitParameterID param,
                                  AudioUnitScope scope,
                                  AudioUnitElement elem,
                                  AudioUnitParameterValue value,
                                  UInt32 bufferOffset) {
    AUGenPlugin* plug = (AUGenPlugin*)self;

    if (scope != kAudioUnitScope_Global)
        return kAudioUnitErr_InvalidParameter;
    if ((int)param >= plug->numParams)
        return kAudioUnitErr_InvalidParameter;

#if NUM_VOICES > 1
    voice_alloc_set_global_param(&plug->voiceAlloc, (int)param, value);
#else
    if (!plug->genState)
        return kAudioUnitErr_Uninitialized;
    wrapper_set_param(plug->genState, (int)param, value);
#endif
    return noErr;
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

static OSStatus AUGenRender(void* self,
                            AudioUnitRenderActionFlags* ioActionFlags,
                            const AudioTimeStamp* inTimeStamp,
                            UInt32 inOutputBusNumber,
                            UInt32 inNumberFrames,
                            AudioBufferList* ioData) {
    AUGenPlugin* plug = (AUGenPlugin*)self;

#if NUM_VOICES > 1
    if (!plug->initialized || !plug->voiceAlloc.states[0])
        return kAudioUnitErr_Uninitialized;
#else
    if (!plug->initialized || !plug->genState)
        return kAudioUnitErr_Uninitialized;
#endif

    if (inOutputBusNumber != 0)
        return kAudioUnitErr_InvalidElement;

    if (inNumberFrames > plug->maxFramesPerSlice)
        return kAudioUnitErr_TooManyFramesToProcess;

    // For effects: pull input audio via connection or render callback
    if (plug->numInputs > 0 && (plug->hasConnection || plug->inputCallback.inputProc)) {
        // Create an AudioBufferList for input
        UInt32 inputBufListSize = offsetof(AudioBufferList, mBuffers) +
            sizeof(AudioBuffer) * (UInt32)plug->numInputs;
        AudioBufferList* inputBufList = (AudioBufferList*)alloca(inputBufListSize);
        inputBufList->mNumberBuffers = (UInt32)plug->numInputs;

        for (int i = 0; i < plug->numInputs; i++) {
            inputBufList->mBuffers[i].mNumberChannels = 1;
            inputBufList->mBuffers[i].mDataByteSize = inNumberFrames * sizeof(Float32);
            inputBufList->mBuffers[i].mData = plug->inBuffers[i];
        }

        AudioUnitRenderActionFlags pullFlags = 0;
        OSStatus pullErr;

        if (plug->hasConnection) {
            // Pull input from connected AU
            pullErr = AudioUnitRender(
                plug->connection.sourceAudioUnit,
                &pullFlags,
                inTimeStamp,
                plug->connection.sourceOutputNumber,
                inNumberFrames,
                inputBufList
            );
        } else {
            // Pull input via render callback
            pullErr = plug->inputCallback.inputProc(
                plug->inputCallback.inputProcRefCon,
                &pullFlags,
                inTimeStamp,
                0,  // input bus 0
                inNumberFrames,
                inputBufList
            );
        }

        if (pullErr != noErr) {
            // Zero output on pull failure
            for (UInt32 b = 0; b < ioData->mNumberBuffers; b++) {
                if (ioData->mBuffers[b].mData) {
                    memset(ioData->mBuffers[b].mData, 0, ioData->mBuffers[b].mDataByteSize);
                }
            }
            return pullErr;
        }

        // Input data is now in plug->inBuffers (non-interleaved Float32*)
    } else if (plug->numInputs > 0) {
        // Effect with no input callback: zero inputs
        for (int i = 0; i < plug->numInputs; i++) {
            memset(plug->inBuffers[i], 0, inNumberFrames * sizeof(float));
        }
    }

    // Set up output buffer pointers
    // Use ioData buffers directly if they match our channel count.
    // When ioData->mData is NULL, the host expects us to provide the buffer.
    float* outPtrs[64];  // reasonable max
    int outCount = plug->numOutputs < 64 ? plug->numOutputs : 64;
    for (int i = 0; i < outCount; i++) {
        if (i < (int)ioData->mNumberBuffers) {
            if (ioData->mBuffers[i].mData) {
                outPtrs[i] = (float*)ioData->mBuffers[i].mData;
            } else {
                // Host provided NULL mData -- render into our buffer
                outPtrs[i] = plug->outBuffers[i];
                ioData->mBuffers[i].mData = plug->outBuffers[i];
                ioData->mBuffers[i].mDataByteSize = inNumberFrames * sizeof(Float32);
            }
        } else if (plug->outBuffers && plug->outBuffers[i]) {
            outPtrs[i] = plug->outBuffers[i];
        } else {
            static float silence[4096];
            outPtrs[i] = silence;
        }
    }

    // Call gen~ perform
#if NUM_VOICES > 1
    voice_alloc_perform(
        &plug->voiceAlloc,
        plug->inBuffers, plug->numInputs,
        outPtrs, outCount,
        (long)inNumberFrames
    );
#else
    wrapper_perform(
        plug->genState,
        plug->inBuffers, plug->numInputs,
        outPtrs, outCount,
        (long)inNumberFrames
    );
#endif

    // If we used our own outBuffers (not ioData directly), copy to ioData
    for (int i = 0; i < outCount; i++) {
        if (i < (int)ioData->mNumberBuffers && ioData->mBuffers[i].mData != outPtrs[i]) {
            memcpy(ioData->mBuffers[i].mData, outPtrs[i],
                   inNumberFrames * sizeof(Float32));
        }
    }

    return noErr;
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

static OSStatus AUGenReset(void* self, AudioUnitScope scope, AudioUnitElement elem) {
    AUGenPlugin* plug = (AUGenPlugin*)self;
#if NUM_VOICES > 1
    if (plug->voiceAlloc.states[0]) {
        float savedParams[kMaxParams];
        int nParams = plug->numParams < kMaxParams ? plug->numParams : kMaxParams;
        voice_alloc_save_params(&plug->voiceAlloc, savedParams, nParams);
        voice_alloc_reset(&plug->voiceAlloc);
        voice_alloc_restore_params(&plug->voiceAlloc, savedParams, nParams);
    }
#else
    if (plug->genState) {
        // Save parameter values, reset DSP state, restore parameters
        float savedParams[kMaxParams];
        int nParams = plug->numParams < kMaxParams ? plug->numParams : kMaxParams;
        SaveParams(plug, savedParams, nParams);
        wrapper_reset(plug->genState);
        RestoreParams(plug, savedParams, nParams);
    }
#endif
    return noErr;
}

// ---------------------------------------------------------------------------
// Property Listener stubs
// ---------------------------------------------------------------------------

static OSStatus AUGenAddPropertyListener(void* self,
                                         AudioUnitPropertyID prop,
                                         AudioUnitPropertyListenerProc proc,
                                         void* refCon) {
    AUGenPlugin* plug = (AUGenPlugin*)self;
    if (plug->numListeners >= kMaxListeners) return noErr;
    plug->listeners[plug->numListeners].property = prop;
    plug->listeners[plug->numListeners].proc = proc;
    plug->listeners[plug->numListeners].refCon = refCon;
    plug->numListeners++;
    return noErr;
}

static OSStatus AUGenRemovePropertyListenerWithUserData(void* self,
                                                        AudioUnitPropertyID prop,
                                                        AudioUnitPropertyListenerProc proc,
                                                        void* refCon) {
    AUGenPlugin* plug = (AUGenPlugin*)self;
    for (int i = 0; i < plug->numListeners; i++) {
        if (plug->listeners[i].property == prop &&
            plug->listeners[i].proc == proc &&
            plug->listeners[i].refCon == refCon) {
            // Shift remaining listeners down
            for (int j = i; j < plug->numListeners - 1; j++) {
                plug->listeners[j] = plug->listeners[j + 1];
            }
            plug->numListeners--;
            i--;  // re-check this index
        }
    }
    return noErr;
}

// ---------------------------------------------------------------------------
// Render notify stubs
// ---------------------------------------------------------------------------

static OSStatus AUGenAddRenderNotify(void* self,
                                     AURenderCallback proc,
                                     void* refCon) {
    (void)self; (void)proc; (void)refCon;
    return noErr;
}

static OSStatus AUGenRemoveRenderNotify(void* self,
                                        AURenderCallback proc,
                                        void* refCon) {
    (void)self; (void)proc; (void)refCon;
    return noErr;
}

// ---------------------------------------------------------------------------
// MIDI Event (kMusicDeviceMIDIEventSelect)
// ---------------------------------------------------------------------------

#ifdef MIDI_ENABLED
static OSStatus AUGenMIDIEvent(void* self,
                               UInt32 inStatus,
                               UInt32 inData1,
                               UInt32 inData2,
                               UInt32 inOffsetSampleFrame) {
    (void)inOffsetSampleFrame;
    AUGenPlugin* plug = (AUGenPlugin*)self;

    UInt32 cmd = inStatus & 0xF0;
    if (cmd == 0x90 && inData2 > 0) {
#if NUM_VOICES > 1
        voice_alloc_note_on(&plug->voiceAlloc, (int)inData1, (float)inData2 / 127.0f);
#else
        if (!plug->genState) return kAudioUnitErr_Uninitialized;
        handle_note_on(plug->genState, (int)inData1, (float)inData2 / 127.0f);
#endif
    } else if (cmd == 0x80 || (cmd == 0x90 && inData2 == 0)) {
#if NUM_VOICES > 1
        voice_alloc_note_off(&plug->voiceAlloc, (int)inData1);
#else
        if (!plug->genState) return kAudioUnitErr_Uninitialized;
        handle_note_off(plug->genState);
#endif
    }
    return noErr;
}
#endif // MIDI_ENABLED

// ---------------------------------------------------------------------------
// Selector Lookup - returns function pointers for each AU selector
//
// The AudioComponentPlugInInterface.Lookup field is called by the host to
// obtain the function pointer for a given selector. Each function has the
// signature matching the AU selector's expected parameter list (passed as
// the first argument is always `self` = the plugin instance).
// ---------------------------------------------------------------------------

static AudioComponentMethod AUGenLookup(SInt16 selector) {
    switch (selector) {
        case kAudioUnitInitializeSelect:
            return (AudioComponentMethod)AUGenInitialize;
        case kAudioUnitUninitializeSelect:
            return (AudioComponentMethod)AUGenUninitialize;
        case kAudioUnitGetPropertyInfoSelect:
            return (AudioComponentMethod)AUGenGetPropertyInfo;
        case kAudioUnitGetPropertySelect:
            return (AudioComponentMethod)AUGenGetProperty;
        case kAudioUnitSetPropertySelect:
            return (AudioComponentMethod)AUGenSetProperty;
        case kAudioUnitGetParameterSelect:
            return (AudioComponentMethod)AUGenGetParameter;
        case kAudioUnitSetParameterSelect:
            return (AudioComponentMethod)AUGenSetParameter;
        case kAudioUnitRenderSelect:
            return (AudioComponentMethod)AUGenRender;
        case kAudioUnitResetSelect:
            return (AudioComponentMethod)AUGenReset;
        case kAudioUnitAddPropertyListenerSelect:
            return (AudioComponentMethod)AUGenAddPropertyListener;
        case kAudioUnitRemovePropertyListenerWithUserDataSelect:
            return (AudioComponentMethod)AUGenRemovePropertyListenerWithUserData;
        case kAudioUnitAddRenderNotifySelect:
            return (AudioComponentMethod)AUGenAddRenderNotify;
        case kAudioUnitRemoveRenderNotifySelect:
            return (AudioComponentMethod)AUGenRemoveRenderNotify;
#ifdef MIDI_ENABLED
        case kMusicDeviceMIDIEventSelect:
            return (AudioComponentMethod)AUGenMIDIEvent;
#endif
        default:
            return nullptr;
    }
}

// ---------------------------------------------------------------------------
// Factory function - entry point registered in Info.plist
// ---------------------------------------------------------------------------

extern "C" void* AUGenFactory(const AudioComponentDescription* desc) {
    AUGenPlugin* plug = (AUGenPlugin*)calloc(1, sizeof(AUGenPlugin));
    if (!plug) return nullptr;

    plug->interface.Open   = AUGenOpen;
    plug->interface.Close  = AUGenClose;
    plug->interface.Lookup = AUGenLookup;
    plug->interface.reserved = nullptr;

    plug->sampleRate         = 44100.0;
    plug->maxFramesPerSlice  = 1024;
    plug->numInputs          = wrapper_num_inputs();
    plug->numOutputs         = wrapper_num_outputs();
    plug->numParams          = wrapper_num_params();
    plug->inBuffers          = nullptr;
    plug->outBuffers         = nullptr;
    plug->initialized        = false;
    plug->currentPresetNumber = -1;
    plug->hasConnection      = false;
    plug->numListeners       = 0;

    // Store component description for ClassInfo serialization
    if (desc) {
        plug->componentType         = desc->componentType;
        plug->componentSubType      = desc->componentSubType;
        plug->componentManufacturer = desc->componentManufacturer;
    }

    memset(&plug->inputCallback, 0, sizeof(AURenderCallbackStruct));

    InitStreamFormat(&plug->streamFormat, plug->sampleRate, (UInt32)plug->numOutputs);

    // Create gen state eagerly so parameter metadata is available before Initialize
#if NUM_VOICES > 1
    voice_alloc_init(&plug->voiceAlloc, plug->numOutputs, (long)plug->maxFramesPerSlice);
    voice_alloc_create_voices(&plug->voiceAlloc, (float)plug->sampleRate, (long)plug->maxFramesPerSlice);
#else
    plug->genState = wrapper_create((float)plug->sampleRate, (long)plug->maxFramesPerSlice);
#endif

    return plug;
}
