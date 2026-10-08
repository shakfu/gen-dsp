// PluginProcessor.cpp - JUCE-format Percussa SSP module for a gen~ export
// Encoders edit pages of four parameters, 1% of the range per step (0.1% fine).
#include "PluginProcessor.h"

#include <cmath>

#include "engine/EngineEditor.h"
#include "ssp/EditorHost.h"

using namespace WRAPPER_NAMESPACE;

namespace {

constexpr int ENCODERS = 4;
constexpr float COARSE = 0.01f;  // fraction of a parameter's range per encoder step
constexpr float FINE = 0.001f;
const juce::Colour colour(0xFFFF8C00);

struct ParamInfo {
    juce::String name;
    float min, max, def;
};

// Metadata from a temporary instance; gen~ initial values can exceed the declared range.
std::vector<ParamInfo> paramInfo() {
    std::vector<ParamInfo> info;
    GenState* s = wrapper_create(48000.0f, 128);
    for (int i = 0; i < wrapper_num_params(); i++) {
        const char* name = wrapper_param_name(s, i);
        float lo = wrapper_param_min(s, i), hi = wrapper_param_max(s, i);
        if (hi < lo) std::swap(lo, hi);
        if (!(hi > lo)) hi = lo + 1.0f;  // JUCE ranges must not be empty
        float def = juce::jlimit(lo, hi, wrapper_get_param(s, i));
        info.push_back({ name ? juce::String(name) : "p" + juce::String(i + 1), lo, hi, def });
    }
    wrapper_destroy(s);
    return info;
}

}  // namespace

// -- GenEngine ----------------------------------------------------------------------

GenEngine::GenEngine()
    : applied_(size_t(wrapper_num_params()), NAN), ins_(size_t(wrapper_num_inputs()), nullptr) {
}

GenEngine::~GenEngine() {
    if (state_) wrapper_destroy(state_);
}

void GenEngine::prepare(float sampleRate, int maxBlock) {
    if (state_) wrapper_destroy(state_);
    state_ = wrapper_create(sampleRate, maxBlock);
    std::fill(applied_.begin(), applied_.end(), NAN);  // a new instance starts at its defaults
}

void GenEngine::process(const float* const* in, float* const* out, int n) {
    // genlib takes non-const input pointers but does not write through them
    for (size_t c = 0; c < ins_.size(); c++) ins_[c] = const_cast<float*>(in[c]);
    wrapper_perform(state_, ins_.data(), long(ins_.size()), const_cast<float**>(out), wrapper_num_outputs(), n);
}

void GenEngine::setParam(int i, float v) {
    if (applied_[size_t(i)] == v) return;
    wrapper_set_param(state_, i, v);
    applied_[size_t(i)] = v;
}

// -- PluginProcessor ----------------------------------------------------------------

PluginProcessor::PluginProcessor()
    : EngineProcessor(getBusesProperties(), createParameterLayout(), std::make_unique<GenEngine>()) {
    init();
    for (auto& p : paramInfo()) params_.push_back(vts().getParameter(p.name));
}

juce::AudioProcessorValueTreeState::ParameterLayout PluginProcessor::createParameterLayout() {
    juce::AudioProcessorValueTreeState::ParameterLayout layout;
    // gen~ parameter names are unique, so they serve as ids: presets match by name
    for (auto& p : paramInfo())
        layout.add(std::make_unique<ssp::BaseFloatParameter>(p.name, p.name, p.min, p.max, p.def));
    return layout;
}

PluginProcessor::BusesProperties PluginProcessor::getBusesProperties() {
    BusesProperties props;
    for (int c = 0; c < wrapper_num_inputs(); c++)
        props.addBus(true, "In " + juce::String(c + 1), juce::AudioChannelSet::mono());
    for (int c = 0; c < wrapper_num_outputs(); c++)
        props.addBus(false, "Out " + juce::String(c + 1), juce::AudioChannelSet::mono());
    return props;
}

void PluginProcessor::control(const float* const*, int) {
    for (size_t i = 0; i < params_.size(); i++) {
        auto* p = params_[i];
        gen().setParam(int(i), p->convertFrom0to1(p->getValue()));
    }
}

juce::AudioProcessorEditor* PluginProcessor::createEditor() {
    std::vector<ssp::engine::ParamPage> pages;
    for (size_t i = 0; i < params_.size(); i++) {
        if (i % ENCODERS == 0) {
            pages.emplace_back();
            pages.back().name = "page " + juce::String(pages.size());
            pages.back().colour = colour;
        }
        auto* p = params_[i];
        float range = p->getNormalisableRange().getRange().getLength();
        pages.back().c[i % ENCODERS] = { p, range * COARSE, range * FINE };
    }
    if (useCompactUI())
        return new ssp::EditorHost(this, new ssp::engine::EngineMiniEditor(*this, pages, {}), true);
    return new ssp::EditorHost(this, new ssp::engine::EngineEditor(*this, pages, {}, {}), false);
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() {
    return new PluginProcessor();
}
