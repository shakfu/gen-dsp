// PluginProcessor.h - JUCE-format Percussa SSP module for a gen~ export
// Built on the ssp::engine layer of the SSP plugin framework (plugins/common).
// Includes JUCE and _ext_ssp.h only, never genlib headers.
#pragma once

#include <memory>
#include <vector>

#include "_ext_ssp.h"
#include "engine/EngineProcessor.h"

// Runs the gen~ patch through the opaque wrapper_* interface.
class GenEngine : public ssp::engine::Engine {
public:
    GenEngine();
    ~GenEngine() override;

    void prepare(float sampleRate, int maxBlock) override;
    void process(const float* const* in, float* const* out, int n) override;

    // Audio thread: applies a value that changed since the last call.
    void setParam(int i, float v);

private:
    GenState* state_ = nullptr;
    std::vector<float> applied_;
    std::vector<float*> ins_;
};

class PluginProcessor : public ssp::engine::EngineProcessor {
public:
    PluginProcessor();

    const juce::String getName() const override { return JucePlugin_Name; }
    juce::AudioProcessorEditor* createEditor() override;

    static BusesProperties getBusesProperties();

protected:
    void control(const float* const* in, int n) override;

private:
    static juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();

    GenEngine& gen() { return static_cast<GenEngine&>(engine()); }

    std::vector<juce::RangedAudioParameter*> params_;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(PluginProcessor)
};
