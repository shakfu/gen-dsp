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
// Plugin state
// ---------------------------------------------------------------------------

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

    if (plug->genState) {
        wrapper_destroy(plug->genState);
    }

    plug->genState = wrapper_create((float)plug->sampleRate, (long)plug->maxFramesPerSlice);
    if (!plug->genState) {
        return kAudioUnitErr_FailedInitialization;
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

    if (plug->genState) {
        wrapper_destroy(plug->genState);
        plug->genState = nullptr;
    }

    FreeBuffers(plug->inBuffers, plug->numInputs);
    FreeBuffers(plug->outBuffers, plug->numOutputs);
    plug->inBuffers = nullptr;
    plug->outBuffers = nullptr;

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
    AUGenPlugin* plug = (AUGenPlugin*)self;

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

        case kAudioUnitProperty_ParameterList:
            if (scope == kAudioUnitScope_Global) {
                if (outDataSize) *outDataSize = (UInt32)(plug->numParams * sizeof(AudioUnitParameterID));
                if (outWritable) *outWritable = false;
                return noErr;
            }
            if (outDataSize) *outDataSize = 0;
            if (outWritable) *outWritable = false;
            return noErr;

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

        default:
            return kAudioUnitErr_InvalidProperty;
    }
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
            if (*ioDataSize < sizeof(Float64))
                return kAudioUnitErr_InvalidPropertyValue;
            *(Float64*)outData = 0.0;
            *ioDataSize = sizeof(Float64);
            return noErr;
        }

        case kAudioUnitProperty_TailTime: {
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

            plug->sampleRate = fmt->mSampleRate;
            plug->streamFormat = *fmt;
            return noErr;
        }

        case kAudioUnitProperty_MaximumFramesPerSlice: {
            if (inDataSize < sizeof(UInt32))
                return kAudioUnitErr_InvalidPropertyValue;

            UInt32 newMax = *(const UInt32*)inData;
            plug->maxFramesPerSlice = newMax;

            // Reallocate internal buffers if already initialized
            if (plug->initialized) {
                AllocateBufferFrames(plug->inBuffers, plug->numInputs, newMax);
                AllocateBufferFrames(plug->outBuffers, plug->numOutputs, newMax);
            }
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

    // For effects: pull input audio via render callback
    if (plug->numInputs > 0 && plug->inputCallback.inputProc) {
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
        OSStatus pullErr = plug->inputCallback.inputProc(
            plug->inputCallback.inputProcRefCon,
            &pullFlags,
            inTimeStamp,
            0,  // input bus 0
            inNumberFrames,
            inputBufList
        );

        if (pullErr != noErr) {
            // Zero output on pull failure
            for (UInt32 b = 0; b < ioData->mNumberBuffers; b++) {
                memset(ioData->mBuffers[b].mData, 0, ioData->mBuffers[b].mDataByteSize);
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
    // Use ioData buffers directly if they match our channel count
    float* outPtrs[64];  // reasonable max
    int outCount = plug->numOutputs < 64 ? plug->numOutputs : 64;
    for (int i = 0; i < outCount; i++) {
        if (i < (int)ioData->mNumberBuffers && ioData->mBuffers[i].mData) {
            outPtrs[i] = (float*)ioData->mBuffers[i].mData;
        } else if (plug->outBuffers && plug->outBuffers[i]) {
            outPtrs[i] = plug->outBuffers[i];
        } else {
            // Should not happen -- fallback to silence
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
        wrapper_reset(plug->genState);
    }
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
    plug->genState           = nullptr;
    plug->numInputs          = wrapper_num_inputs();
    plug->numOutputs         = wrapper_num_outputs();
    plug->numParams          = wrapper_num_params();
    plug->inBuffers          = nullptr;
    plug->outBuffers         = nullptr;
    plug->initialized        = false;

    memset(&plug->inputCallback, 0, sizeof(AURenderCallbackStruct));

    InitStreamFormat(&plug->streamFormat, plug->sampleRate, (UInt32)plug->numOutputs);

    return plug;
}
