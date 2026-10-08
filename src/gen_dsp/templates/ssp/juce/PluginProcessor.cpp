// PluginProcessor.cpp - JUCE-format Percussa SSP module for a gen~ export
// Encoders edit pages of four parameters, 1% of the range per step (0.1% fine).
// gen~ buffers load <buffer>.wav from the module's folder at start, or a file
// chosen with Load; presets keep the paths.
#include "PluginProcessor.h"

#include <cmath>

#include "_ext_ssp_buffers.h"
#include "engine/EngineEditor.h"
#include "ssp/EditorHost.h"

using namespace WRAPPER_NAMESPACE;

namespace {

constexpr int ENCODERS = 4;
constexpr float COARSE = 0.01f;  // fraction of a parameter's range per encoder step
constexpr float FINE = 0.001f;
const juce::Colour colour(0xFFFF8C00);
const char* const LOAD_INTO = "load into";

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

juce::String bufferAttribute(int i) {
    return "buffer_" + juce::String(wrapper_buffer_name(i));
}

}  // namespace

// -- GenEngine ----------------------------------------------------------------------

GenEngine::GenEngine()
    : applied_(size_t(wrapper_num_params()), NAN),
      ins_(size_t(wrapper_num_inputs()), nullptr),
      requested_(size_t(wrapper_num_buffers())),
      buffers_(size_t(wrapper_num_buffers())) {
}

GenEngine::~GenEngine() {
    if (state_) wrapper_destroy(state_);
}

// Message thread, with audio and idle() stopped.
void GenEngine::prepare(float sampleRate, int maxBlock) {
    if (state_) wrapper_destroy(state_);
    state_ = wrapper_create(sampleRate, maxBlock);
    std::fill(applied_.begin(), applied_.end(), NAN);  // a new instance starts at its defaults
    // and with empty buffers: reload what was loaded, unless a newer load is pending
    std::lock_guard<std::mutex> lock(bufferLock_);
    for (size_t i = 0; i < buffers_.size(); i++)
        if (requested_[i].empty()) requested_[i] = buffers_[i].path;
}

void GenEngine::process(const float* const* in, float* const* out, int n) {
    // genlib takes non-const input pointers but does not write through them
    for (size_t c = 0; c < ins_.size(); c++) ins_[c] = const_cast<float*>(in[c]);
    wrapper_perform(state_, ins_.data(), long(ins_.size()), const_cast<float**>(out), wrapper_num_outputs(), n);
}

// Worker thread, after prepare(): file reads stay off the audio thread.
void GenEngine::idle() {
    for (size_t i = 0; i < requested_.size(); i++) {
        std::string path;
        {
            std::lock_guard<std::mutex> lock(bufferLock_);
            path.swap(requested_[i]);
        }
        if (path.empty()) continue;
#if WRAPPER_BUFFER_COUNT > 0
        long frames = wrapper_buffer_load(state_, int(i), path.c_str());
#else
        long frames = -1;
#endif
        std::lock_guard<std::mutex> lock(bufferLock_);
        buffers_[i] = { path, frames };
    }
}

void GenEngine::setParam(int i, float v) {
    if (applied_[size_t(i)] == v) return;
    wrapper_set_param(state_, i, v);
    applied_[size_t(i)] = v;
}

void GenEngine::loadBuffer(int i, const std::string& path) {
    if (i < 0 || i >= int(requested_.size())) return;
    std::lock_guard<std::mutex> lock(bufferLock_);
    requested_[size_t(i)] = path;
}

GenEngine::BufferInfo GenEngine::bufferInfo(int i) {
    std::lock_guard<std::mutex> lock(bufferLock_);
    return buffers_[size_t(i)];
}

// -- Editor -------------------------------------------------------------------------

namespace {

// The parameter pages, plus what each buffer holds; Load fills the target buffer.
class GenEditor : public ssp::engine::EngineEditor {
public:
    GenEditor(PluginProcessor& p, std::vector<ssp::engine::ParamPage> pages)
        : EngineEditor(p, std::move(pages), {}, p.bufferDir()), processor_(p) {}

protected:
    void loaded(const juce::String& file, const juce::String&) override {
        if (file.isNotEmpty()) processor_.gen().loadBuffer(processor_.loadTarget(), file.toStdString());
    }

    juce::String browseFrom() override {
        auto path = processor_.gen().bufferInfo(processor_.loadTarget()).path;
        return path.empty() ? processor_.bufferDir() : juce::String(path);
    }

    void drawStatus(juce::Graphics& g, juce::Rectangle<int> area) override {
        static constexpr int lineH = 30;
        for (int i = 0; i < wrapper_num_buffers(); i++) {
            auto b = processor_.gen().bufferInfo(i);
            juce::String what = b.path.empty() ? juce::String("none")
                                : b.frames < 0 ? "cannot read " + juce::File(b.path).getFileName()
                                               : juce::File(b.path).getFileName() + " (" + juce::String(b.frames) + ")";
            g.setColour(i == processor_.loadTarget() ? juce::Colours::white : juce::Colours::grey);
            g.drawText(juce::String(wrapper_buffer_name(i)) + ": " + what, area.removeFromTop(lineH),
                       juce::Justification::left);
        }
    }

private:
    PluginProcessor& processor_;
};

}  // namespace

// -- PluginProcessor ----------------------------------------------------------------

PluginProcessor::PluginProcessor()
    : EngineProcessor(getBusesProperties(), createParameterLayout(), std::make_unique<GenEngine>()) {
    init();
    for (auto& p : paramInfo()) params_.push_back(vts().getParameter(p.name));
    loadInto_ = vts().getParameter(LOAD_INTO);
    bufferDir_ = juce::File(ssp_buffer_dir(SSP_MODULE_NAME)).getFullPathName();
    for (int i = 0; i < wrapper_num_buffers(); i++) {
        auto file = juce::File(bufferDir_).getChildFile(juce::String(wrapper_buffer_name(i)) + ".wav");
        if (file.existsAsFile()) gen().loadBuffer(i, file.getFullPathName().toStdString());
    }
}

juce::AudioProcessorValueTreeState::ParameterLayout PluginProcessor::createParameterLayout() {
    juce::AudioProcessorValueTreeState::ParameterLayout layout;
    // gen~ parameter names are unique, so they serve as ids: presets match by name
    for (auto& p : paramInfo())
        layout.add(std::make_unique<ssp::BaseFloatParameter>(p.name, p.name, p.min, p.max, p.def));
    if (wrapper_num_buffers() > 1) {
        juce::StringArray names;
        for (int i = 0; i < wrapper_num_buffers(); i++) names.add(wrapper_buffer_name(i));
        layout.add(std::make_unique<ssp::BaseChoiceParameter>(LOAD_INTO, LOAD_INTO, names, 0));
    }
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

int PluginProcessor::loadTarget() {
    return loadInto_ ? int(loadInto_->convertFrom0to1(loadInto_->getValue())) : 0;
}

void PluginProcessor::control(const float* const*, int) {
    for (size_t i = 0; i < params_.size(); i++) {
        auto* p = params_[i];
        gen().setParam(int(i), p->convertFrom0to1(p->getValue()));
    }
}

void PluginProcessor::customToXml(juce::XmlElement* xml) {
    for (int i = 0; i < wrapper_num_buffers(); i++)
        xml->setAttribute(bufferAttribute(i), juce::String(gen().bufferInfo(i).path));
}

// A preset without a path for a buffer keeps what the buffer holds.
void PluginProcessor::customFromXml(juce::XmlElement* xml) {
    for (int i = 0; i < wrapper_num_buffers(); i++) {
        auto path = xml->getStringAttribute(bufferAttribute(i));
        if (path.isNotEmpty()) gen().loadBuffer(i, path.toStdString());
    }
}

std::vector<ssp::engine::ParamPage> PluginProcessor::pages() {
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
    if (loadInto_) {
        pages.emplace_back();
        pages.back().name = "buffers";
        pages.back().c[0] = { loadInto_, 1.0f, 1.0f };
    }
    return pages;
}

juce::AudioProcessorEditor* PluginProcessor::createEditor() {
    if (useCompactUI())
        return new ssp::EditorHost(this, new ssp::engine::EngineMiniEditor(*this, pages(), {}), true);
    return new ssp::EditorHost(this, new GenEditor(*this, pages()), false);
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() {
    return new PluginProcessor();
}
