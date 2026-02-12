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
    GenState*                    genState;
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
    if (!plug->genState) return;
    for (int i = 0; i < count && i < kMaxParams; i++) {
        saved[i] = wrapper_get_param(plug->genState, i);
    }
}

// Restore parameter values from array into gen state
static void RestoreParams(AUGenPlugin* plug, const float* saved, int count) {
    if (!plug->genState) return;
    for (int i = 0; i < count && i < kMaxParams; i++) {
        wrapper_set_param(plug->genState, i, saved[i]);
    }
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
    if (plug->genState) {
        wrapper_destroy(plug->genState);
        plug->genState = nullptr;
    }
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
    bool hasParams = plug->genState && plug->numParams > 0;
    if (hasParams) {
        SaveParams(plug, savedParams, plug->numParams);
    }

    if (plug->genState) {
        wrapper_destroy(plug->genState);
    }

    plug->genState = wrapper_create((float)plug->sampleRate, (long)plug->maxFramesPerSlice);
    if (!plug->genState) {
        return kAudioUnitErr_FailedInitialization;
    }

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

    // Store parameter values as CFData blob
    if (plug->genState && plug->numParams > 0) {
        int nParams = plug->numParams < kMaxParams ? plug->numParams : kMaxParams;
        float values[kMaxParams];
        for (int i = 0; i < nParams; i++) {
            values[i] = wrapper_get_param(plug->genState, i);
        }
        CFDataRef data = CFDataCreate(kCFAllocatorDefault,
            (const UInt8*)values, (CFIndex)(nParams * sizeof(float)));
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
        int nParams = plug->numParams < kMaxParams ? plug->numParams : kMaxParams;
        CFIndex dataSize = CFDataGetLength(data);
        CFIndex expectedSize = (CFIndex)(nParams * sizeof(float));

        if (dataSize >= expectedSize && plug->genState) {
            const float* values = (const float*)CFDataGetBytePtr(data);
            for (int i = 0; i < nParams; i++) {
                wrapper_set_param(plug->genState, i, values[i]);
            }
        }
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
            const char* pname = plug->genState
                ? wrapper_param_name(plug->genState, (int)elem)
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

            if (plug->genState && wrapper_param_hasminmax(plug->genState, (int)elem)) {
                info->minValue     = wrapper_param_min(plug->genState, (int)elem);
                info->maxValue     = wrapper_param_max(plug->genState, (int)elem);
                info->defaultValue = wrapper_get_param(plug->genState, (int)elem);
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
                bool hasParams = plug->genState && plug->numParams > 0;
                if (hasParams) SaveParams(plug, savedParams, plug->numParams);

                if (plug->genState) wrapper_destroy(plug->genState);
                plug->genState = wrapper_create((float)plug->sampleRate, (long)newMax);
                if (hasParams && plug->genState) RestoreParams(plug, savedParams, plug->numParams);

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
    if (!plug->genState)
        return kAudioUnitErr_Uninitialized;

    *outValue = wrapper_get_param(plug->genState, (int)param);
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
    if (!plug->genState)
        return kAudioUnitErr_Uninitialized;

    wrapper_set_param(plug->genState, (int)param, value);
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

    if (!plug->initialized || !plug->genState)
        return kAudioUnitErr_Uninitialized;

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
    wrapper_perform(
        plug->genState,
        plug->inBuffers, plug->numInputs,
        outPtrs, outCount,
        (long)inNumberFrames
    );

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
    if (plug->genState) {
        // Save parameter values, reset DSP state, restore parameters
        float savedParams[kMaxParams];
        int nParams = plug->numParams < kMaxParams ? plug->numParams : kMaxParams;
        SaveParams(plug, savedParams, nParams);
        wrapper_reset(plug->genState);
        RestoreParams(plug, savedParams, nParams);
    }
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
    plug->genState = wrapper_create((float)plug->sampleRate, (long)plug->maxFramesPerSlice);

    return plug;
}
