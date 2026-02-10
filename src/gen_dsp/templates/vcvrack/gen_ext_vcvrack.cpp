// gen_ext_vcvrack.cpp - VCV Rack module wrapper for gen~ exports
// This file includes ONLY VCV Rack headers - genlib is isolated in _ext_vcvrack.cpp
//
// Implements a VCV Rack Module with knobs (parameters) and ports (audio I/O).
// Calls gen~'s perform() with n=1 each sample for zero-latency processing.

#include "plugin.hpp"

#include "gen_ext_common_vcvrack.h"
#include "_ext_vcvrack.h"

using namespace WRAPPER_NAMESPACE;

// ---------------------------------------------------------------------------
// Constants from compile-time defines
// ---------------------------------------------------------------------------

#define VCR_TOTAL_COMPONENTS (VCR_NUM_PARAMS + VCR_NUM_INPUTS + VCR_NUM_OUTPUTS)

// Maximum channel count for static arrays
#define VCR_MAX_CHANNELS 64

// Voltage scaling: gen~ uses [-1, 1], VCV Rack uses +/-5V
static const float VCR_VOLTAGE_SCALE = 5.0f;

// ---------------------------------------------------------------------------
// GenModule - VCV Rack Module wrapping a gen~ export
// ---------------------------------------------------------------------------

struct GenModule : Module {
    GenState* genState = nullptr;

    float inBuf[VCR_MAX_CHANNELS];
    float outBuf[VCR_MAX_CHANNELS];
    float* inPtrs[VCR_MAX_CHANNELS];
    float* outPtrs[VCR_MAX_CHANNELS];

    GenModule() {
        config(VCR_NUM_PARAMS, VCR_NUM_INPUTS, VCR_NUM_OUTPUTS, 0);

        // Set up buffer pointer arrays
        for (int i = 0; i < VCR_MAX_CHANNELS; i++) {
            inPtrs[i] = &inBuf[i];
            outPtrs[i] = &outBuf[i];
        }

        // Query gen~ for parameter metadata using a temporary state
        GenState* tmp = wrapper_create(44100.0f, 1);
        for (int i = 0; i < VCR_NUM_PARAMS; i++) {
            const char* name = wrapper_param_name(tmp, i);
            float pmin = 0.f, pmax = 1.f;
            if (wrapper_param_hasminmax(tmp, i)) {
                pmin = wrapper_param_min(tmp, i);
                pmax = wrapper_param_max(tmp, i);
            }
            configParam(i, pmin, pmax, pmin, name ? name : "");
        }
        wrapper_destroy(tmp);

        // Configure audio inputs
        for (int i = 0; i < VCR_NUM_INPUTS; i++) {
            std::string label = "Input " + std::to_string(i + 1);
            configInput(i, label);
        }

        // Configure audio outputs
        for (int i = 0; i < VCR_NUM_OUTPUTS; i++) {
            std::string label = "Output " + std::to_string(i + 1);
            configOutput(i, label);
        }
    }

    ~GenModule() {
        if (genState) {
            wrapper_destroy(genState);
            genState = nullptr;
        }
    }

    void onSampleRateChange() override {
        // Destroy current state; process() will recreate at new rate
        if (genState) {
            wrapper_destroy(genState);
            genState = nullptr;
        }
    }

    void onReset() override {
        if (genState) {
            wrapper_reset(genState);
        }
    }

    void process(const ProcessArgs& args) override {
        // Lazy-create gen~ state at current sample rate
        if (!genState) {
            genState = wrapper_create(args.sampleRate, 1);
        }

        // Read VCV inputs -> gen~ input buffers (scale +/-5V -> +/-1)
        for (int i = 0; i < VCR_NUM_INPUTS; i++) {
            inBuf[i] = inputs[i].getVoltage() / VCR_VOLTAGE_SCALE;
        }

        // Set parameters from knobs
        for (int i = 0; i < VCR_NUM_PARAMS; i++) {
            wrapper_set_param(genState, i, params[i].getValue());
        }

        // gen~ perform with n=1 (per-sample processing)
        wrapper_perform(genState, inPtrs, VCR_NUM_INPUTS,
                        outPtrs, VCR_NUM_OUTPUTS, 1);

        // Write gen~ outputs -> VCV outputs (scale +/-1 -> +/-5V)
        for (int i = 0; i < VCR_NUM_OUTPUTS; i++) {
            outputs[i].setVoltage(outBuf[i] * VCR_VOLTAGE_SCALE);
        }
    }
};

// ---------------------------------------------------------------------------
// GenModuleWidget - Panel layout with auto-positioned components
// ---------------------------------------------------------------------------

struct GenModuleWidget : ModuleWidget {
    GenModuleWidget(GenModule* module) {
        setModule(module);

        // Load panel SVG
        setPanel(createPanel(asset::plugin(pluginInstance, "res/" STR(VCR_EXT_NAME) ".svg")));

        // Corner screws
        addChild(createWidget<ScrewSilver>(Vec(0, 0)));
        addChild(createWidget<ScrewSilver>(Vec(box.size.x - RACK_GRID_WIDTH, 0)));
        addChild(createWidget<ScrewSilver>(Vec(0, RACK_GRID_HEIGHT - RACK_GRID_WIDTH)));
        addChild(createWidget<ScrewSilver>(Vec(box.size.x - RACK_GRID_WIDTH, RACK_GRID_HEIGHT - RACK_GRID_WIDTH)));

        // Auto-layout: components in columns, max 9 per column
        const int maxPerCol = 9;
        const float colWidth = RACK_GRID_WIDTH * 2.5f;
        const float startX = RACK_GRID_WIDTH * 1.25f;
        const float startY = RACK_GRID_WIDTH * 2.5f;
        const float rowHeight = (RACK_GRID_HEIGHT - startY - RACK_GRID_WIDTH * 1.5f) / (float)maxPerCol;

        int slot = 0;

        // Knobs for parameters
        for (int i = 0; i < VCR_NUM_PARAMS; i++) {
            int col = slot / maxPerCol;
            int row = slot % maxPerCol;
            float x = startX + col * colWidth;
            float y = startY + row * rowHeight;
            addParam(createParamCentered<RoundBlackKnob>(Vec(x, y), module, i));
            slot++;
        }

        // Input ports
        for (int i = 0; i < VCR_NUM_INPUTS; i++) {
            int col = slot / maxPerCol;
            int row = slot % maxPerCol;
            float x = startX + col * colWidth;
            float y = startY + row * rowHeight;
            addInput(createInputCentered<PJ301MPort>(Vec(x, y), module, i));
            slot++;
        }

        // Output ports
        for (int i = 0; i < VCR_NUM_OUTPUTS; i++) {
            int col = slot / maxPerCol;
            int row = slot % maxPerCol;
            float x = startX + col * colWidth;
            float y = startY + row * rowHeight;
            addOutput(createOutputCentered<PJ301MPort>(Vec(x, y), module, i));
            slot++;
        }
    }
};

// ---------------------------------------------------------------------------
// Model registration
// ---------------------------------------------------------------------------

Model* modelGenModule = createModel<GenModule, GenModuleWidget>(STR(VCR_EXT_NAME));
