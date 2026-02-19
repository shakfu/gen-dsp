// gen_ext_vst3.cpp - VST3 plugin wrapper for gen~ exports
// This file includes ONLY VST3 SDK headers - genlib is isolated in _ext_vst3.cpp
//
// Implements a VST3 plugin using SingleComponentEffect.
// VST3's channelBuffers32 is float** (non-interleaved), matching gen~'s
// layout exactly, so the process function passes buffers directly (zero copy).

#include "public.sdk/source/vst/vstsinglecomponenteffect.h"
#include "public.sdk/source/vst/vstparameters.h"
#include "pluginterfaces/vst/ivstparameterchanges.h"
#include "pluginterfaces/vst/ivstaudioprocessor.h"
#include "pluginterfaces/vst/ivstprocesscontext.h"
#include "public.sdk/source/main/pluginfactory.h"
#include "pluginterfaces/base/futils.h"
#include "base/source/fstreamer.h"

// Include gen wrapper AFTER VST3 headers to avoid macro conflicts
// gen_ext_common_vst3.h uses GSTR instead of STR to avoid clashing
// with the SDK's STR macro (which maps to STR16)
#include "gen_ext_common_vst3.h"
#include "_ext_vst3.h"

#include <cstring>
#include <cstdio>
#include <cmath>

using namespace Steinberg;
using namespace Steinberg::Vst;
using namespace WRAPPER_NAMESPACE;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// ASCII to UTF-16LE conversion for String128
static void asciiToString128(Steinberg::Vst::String128 dest, const char* src) {
    int i = 0;
    if (src) {
        for (; src[i] != '\0' && i < 127; i++) {
            dest[i] = (Steinberg::char16)src[i];
        }
    }
    dest[i] = 0;
}

// ---------------------------------------------------------------------------
// FUID (defined via preprocessor from CMakeLists.txt)
// ---------------------------------------------------------------------------

static const FUID kProcessorUID(VST3_FUID_0, VST3_FUID_1, VST3_FUID_2, VST3_FUID_3);

// ---------------------------------------------------------------------------
// Subcategories (effect vs instrument)
// ---------------------------------------------------------------------------

#if VST3_NUM_INPUTS > 0
static const char* kSubCategories = PlugType::kFx;
#else
static const char* kSubCategories = PlugType::kInstrumentSynth;
#endif

// ---------------------------------------------------------------------------
// GenVst3Plugin
// ---------------------------------------------------------------------------

class GenVst3Plugin : public SingleComponentEffect {
public:
    GenVst3Plugin();
    ~GenVst3Plugin() override;

    // IPluginBase
    tresult PLUGIN_API initialize(FUnknown* context) override;
    tresult PLUGIN_API terminate() override;

    // IAudioProcessor
    tresult PLUGIN_API setActive(TBool state) override;
    tresult PLUGIN_API canProcessSampleSize(int32 symbolicSize) override;
    tresult PLUGIN_API setBusArrangements(
        SpeakerArrangement* inputs, int32 numIns,
        SpeakerArrangement* outputs, int32 numOuts) override;
    tresult PLUGIN_API process(ProcessData& data) override;

    // IEditController (state)
    tresult PLUGIN_API setState(IBStream* state) override;
    tresult PLUGIN_API getState(IBStream* state) override;

    // Factory method
    static FUnknown* createInstance(void*) {
        return (IAudioProcessor*)new GenVst3Plugin();
    }

private:
    GenState* mGenState;
    float mSampleRate;
    int32 mMaxFrames;

    struct ParamRange {
        float min;
        float max;
        float defaultVal;
    };
    ParamRange mParamRanges[128];
    int mNumParams;
};

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

GenVst3Plugin::GenVst3Plugin()
    : mGenState(nullptr)
    , mSampleRate(44100.0f)
    , mMaxFrames(1024)
    , mNumParams(0)
{
    memset(mParamRanges, 0, sizeof(mParamRanges));
}

GenVst3Plugin::~GenVst3Plugin() {
    if (mGenState) {
        wrapper_destroy(mGenState);
        mGenState = nullptr;
    }
}

tresult PLUGIN_API GenVst3Plugin::initialize(FUnknown* context) {
    tresult result = SingleComponentEffect::initialize(context);
    if (result != kResultOk) return result;

    // Build speaker arrangements matching gen~ channel counts
    auto speakerArrForCount = [](int n) -> SpeakerArrangement {
        if (n == 1) return SpeakerArr::kMono;
        if (n == 2) return SpeakerArr::kStereo;
        // Generic N-channel: set first N speaker bits
        SpeakerArrangement arr = 0;
        for (int i = 0; i < n; i++) arr |= (SpeakerArrangement)1 << i;
        return arr;
    };

    // Add audio buses
    if (VST3_NUM_INPUTS > 0) {
        addAudioInput(STR16("Input"), speakerArrForCount(VST3_NUM_INPUTS));
    }
    addAudioOutput(STR16("Output"), speakerArrForCount(VST3_NUM_OUTPUTS));

    // Create a temporary gen state to query parameter metadata
    GenState* tmpState = wrapper_create(44100.0f, 512);
    if (!tmpState) return kResultFalse;

    mNumParams = wrapper_num_params();
    if (mNumParams > 128) mNumParams = 128;

    for (int i = 0; i < mNumParams; i++) {
        const char* pname = wrapper_param_name(tmpState, i);
        const char* punits = wrapper_param_units(tmpState, i);

        float pmin = 0.0f;
        float pmax = 1.0f;
        if (wrapper_param_hasminmax(tmpState, i)) {
            pmin = wrapper_param_min(tmpState, i);
            pmax = wrapper_param_max(tmpState, i);
        }
        float pdefault = wrapper_get_param(tmpState, i);

        // Clamp default to [min, max] -- gen~ initial values may exceed
        // the declared range (e.g. gigaverb revtime init=11, max=1)
        if (pdefault < pmin) pdefault = pmin;
        if (pdefault > pmax) pdefault = pmax;

        mParamRanges[i].min = pmin;
        mParamRanges[i].max = pmax;
        mParamRanges[i].defaultVal = pdefault;

        // Convert name to String128
        String128 title;
        if (pname) {
            asciiToString128(title, pname);
        } else {
            char fallback[32];
            snprintf(fallback, sizeof(fallback), "Param %d", i);
            asciiToString128(title, fallback);
        }

        // Convert units
        String128 units;
        if (punits && punits[0] != '\0') {
            asciiToString128(units, punits);
        } else {
            units[0] = 0;
        }

        // Add as RangeParameter (handles normalized <-> plain conversion)
        auto* param = new RangeParameter(
            title,          // title
            (ParamID)i,     // tag/id
            units,          // units
            (ParamValue)pmin,   // minPlain
            (ParamValue)pmax,   // maxPlain
            (ParamValue)pdefault, // defaultValuePlain
            0,              // stepCount (0 = continuous)
            ParameterInfo::kCanAutomate, // flags
            0               // unitId (kRootUnitId -- no unit hierarchy)
        );
        parameters.addParameter(param);
    }

    wrapper_destroy(tmpState);
    return kResultOk;
}

tresult PLUGIN_API GenVst3Plugin::terminate() {
    if (mGenState) {
        wrapper_destroy(mGenState);
        mGenState = nullptr;
    }
    return SingleComponentEffect::terminate();
}

tresult PLUGIN_API GenVst3Plugin::setActive(TBool state) {
    if (state) {
        if (mGenState) {
            wrapper_destroy(mGenState);
        }
        mGenState = wrapper_create(mSampleRate, (long)mMaxFrames);
        if (!mGenState) return kResultFalse;

        // Set parameters to their current values
        for (int i = 0; i < mNumParams; i++) {
            ParamValue normValue = getParamNormalized((ParamID)i);
            float range = mParamRanges[i].max - mParamRanges[i].min;
            float plain = mParamRanges[i].min + (float)normValue * range;
            wrapper_set_param(mGenState, i, plain);
        }
    } else {
        if (mGenState) {
            wrapper_destroy(mGenState);
            mGenState = nullptr;
        }
    }
    return SingleComponentEffect::setActive(state);
}

tresult PLUGIN_API GenVst3Plugin::canProcessSampleSize(int32 symbolicSize) {
    if (symbolicSize == kSample32) return kResultOk;
    return kResultFalse;
}

tresult PLUGIN_API GenVst3Plugin::setBusArrangements(
    SpeakerArrangement* inputs, int32 numIns,
    SpeakerArrangement* outputs, int32 numOuts) {

    // Accept any arrangement that matches our channel counts
    if (VST3_NUM_INPUTS > 0) {
        if (numIns < 1) return kResultFalse;
        int inChannels = SpeakerArr::getChannelCount(inputs[0]);
        if (inChannels != VST3_NUM_INPUTS) return kResultFalse;
    }

    if (numOuts < 1) return kResultFalse;
    int outChannels = SpeakerArr::getChannelCount(outputs[0]);
    if (outChannels != VST3_NUM_OUTPUTS) return kResultFalse;

    return SingleComponentEffect::setBusArrangements(inputs, numIns, outputs, numOuts);
}

tresult PLUGIN_API GenVst3Plugin::process(ProcessData& data) {
    if (!mGenState) return kResultFalse;

    // Handle sample rate changes
    if (data.processContext && data.processContext->sampleRate > 0) {
        float newRate = (float)data.processContext->sampleRate;
        if (newRate != mSampleRate) {
            mSampleRate = newRate;
        }
    }

    // Handle parameter changes
    IParameterChanges* paramChanges = data.inputParameterChanges;
    if (paramChanges) {
        int32 numParamsChanged = paramChanges->getParameterCount();
        for (int32 i = 0; i < numParamsChanged; i++) {
            IParamValueQueue* queue = paramChanges->getParameterData(i);
            if (!queue) continue;

            ParamID paramId = queue->getParameterId();
            if ((int)paramId >= mNumParams) continue;

            // Get the last value in the queue
            int32 numPoints = queue->getPointCount();
            if (numPoints <= 0) continue;

            int32 sampleOffset;
            ParamValue normValue;
            if (queue->getPoint(numPoints - 1, sampleOffset, normValue) == kResultOk) {
                // Convert normalized (0-1) to plain using stored ranges
                float range = mParamRanges[paramId].max - mParamRanges[paramId].min;
                float plain = mParamRanges[paramId].min + (float)normValue * range;
                wrapper_set_param(mGenState, (int)paramId, plain);
            }
        }
    }

    int32 nframes = data.numSamples;
    if (nframes <= 0) return kResultOk;

    // Zero-copy audio -- channelBuffers32 is float**, same as gen~
    float** ins = nullptr;
    if (VST3_NUM_INPUTS > 0 && data.numInputs > 0 && data.inputs) {
        ins = data.inputs[0].channelBuffers32;
    }

    float** outs = nullptr;
    if (data.numOutputs > 0 && data.outputs) {
        outs = data.outputs[0].channelBuffers32;
    }

    if (!outs) return kResultOk;

    wrapper_perform(mGenState,
                    ins, VST3_NUM_INPUTS,
                    outs, VST3_NUM_OUTPUTS,
                    (long)nframes);

    return kResultOk;
}

tresult PLUGIN_API GenVst3Plugin::setState(IBStream* state) {
    if (!state) return kResultFalse;

    IBStreamer streamer(state, kLittleEndian);

    // Read parameters
    for (int i = 0; i < mNumParams; i++) {
        float value = 0.0f;
        if (!streamer.readFloat(value)) break;
        if (mGenState) {
            wrapper_set_param(mGenState, i, value);
        }
        // Normalize and update controller
        float range = mParamRanges[i].max - mParamRanges[i].min;
        double normValue = 0.0;
        if (range > 0.0f) {
            normValue = (double)(value - mParamRanges[i].min) / (double)range;
        }
        setParamNormalized((ParamID)i, normValue);
    }

    return kResultOk;
}

tresult PLUGIN_API GenVst3Plugin::getState(IBStream* state) {
    if (!state) return kResultFalse;

    IBStreamer streamer(state, kLittleEndian);

    // Write current parameter values (plain, not normalized)
    for (int i = 0; i < mNumParams; i++) {
        float value = 0.0f;
        if (mGenState) {
            value = wrapper_get_param(mGenState, i);
        } else {
            value = mParamRanges[i].defaultVal;
        }
        streamer.writeFloat(value);
    }

    return kResultOk;
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

BEGIN_FACTORY_DEF("gen-dsp",
                  "https://github.com/samesimilar/gen_dsp",
                  "")

    DEF_CLASS2(INLINE_UID_FROM_FUID(kProcessorUID),
               PClassInfo::kManyInstances,
               kVstAudioEffectClass,
               GSTR(VST3_EXT_NAME),
               Vst::kDistributable,
               kSubCategories,
               GEN_EXT_VERSION,
               kVstVersionString,
               GenVst3Plugin::createInstance)

END_FACTORY
