// PluginProcessor.h - JUCE-format Percussa SSP module for a gen~ export
// Built on the ssp::engine layer of the SSP plugin framework (plugins/common).
// Includes JUCE and _ext_ssp.h only, never genlib headers.
#pragma once

#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "_ext_ssp.h"
#include "engine/EngineEditor.h"

// Runs the gen~ patch through the opaque wrapper_* interface.
class GenEngine : public ssp::engine::Engine {
public:
    GenEngine();
    ~GenEngine() override;

    void prepare(float sampleRate, int maxBlock) override;
    void process(const float* const* in, float* const* out, int n) override;
    void idle() override;

    // Audio thread: applies a value that changed since the last call.
    void setParam(int i, float v);

    struct BufferInfo {
        std::string path;  // empty: nothing loaded
        long frames = -1;  // -1: the file could not be read
    };
    // Not the audio thread. Reads `path` into buffer `i` on the worker thread.
    void loadBuffer(int i, const std::string& path);
    BufferInfo bufferInfo(int i);

private:
    GenState* state_ = nullptr;
    std::vector<float> applied_;
    std::vector<float*> ins_;

    std::mutex bufferLock_;
    std::vector<std::string> requested_;  // empty: no load pending
    std::vector<BufferInfo> buffers_;
};

class PluginProcessor : public ssp::engine::EngineProcessor {
public:
    PluginProcessor();

    const juce::String getName() const override { return JucePlugin_Name; }
    juce::AudioProcessorEditor* createEditor() override;

    static BusesProperties getBusesProperties();

    GenEngine& gen() { return static_cast<GenEngine&>(engine()); }
    // the buffer Load fills: the "load into" choice, or the only buffer
    int loadTarget();
    // the folder of files loaded at start: <buffer>.wav beside plugins/, in <module>/
    const juce::String& bufferDir() const { return bufferDir_; }

protected:
    void control(const float* const* in, int n) override;
    void customToXml(juce::XmlElement* xml) override;
    void customFromXml(juce::XmlElement* xml) override;

private:
    static juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
    std::vector<ssp::engine::ParamPage> pages();

    std::vector<juce::RangedAudioParameter*> params_;
    juce::RangedAudioParameter* loadInto_ = nullptr;
    juce::String bufferDir_;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(PluginProcessor)
};
