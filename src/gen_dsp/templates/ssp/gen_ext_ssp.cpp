// gen_ext_ssp.cpp - Percussa SSP module for a gen~ export
// Includes Percussa.h and _ext_ssp.h only, never genlib headers.
//
// Controls: the four encoders edit a page of four parameters (Shift L/R held:
// fine steps; encoder press: reset to default). Left/Up and Right/Down change
// page; soft key N jumps to page N. Each gen~ buffer loads <buffer>.wav from the
// module's folder on the card (see ssp_buffer_dir).

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "Percussa.h"
#include "_ext_ssp.h"
#include "_ext_ssp_buffers.h"
#include "ssp_font.h"

using namespace WRAPPER_NAMESPACE;

namespace {

constexpr int ENCODERS = 4;
constexpr float STEPS = 100.0f;  // encoder pulses across a parameter's range
constexpr float FINE = 10.0f;    // step divisor while a shift key is held
constexpr double DEFAULT_SR = 48000.0;
constexpr int DEFAULT_BLOCK = 128;

enum Button { SOFT_LAST = 7, LEFT = 8, RIGHT = 9, UP = 10, DOWN = 11, SHIFT_L = 12, SHIFT_R = 13 };

const char* const STATE_MAGIC = "gen-dsp-ssp 1";

// 0xAARRGGBB, as PluginDescriptor::colour
constexpr unsigned COLOUR = 0xFFFF8C00;

struct Param {
    std::string name;
    float min = 0.0f;
    float max = 1.0f;
    float def = 0.0f;
};

#if defined(__arm__)
// Flush denormals to zero: VFP handles them in slow microcode.
struct ScopedFlushToZero {
    uint32_t saved;
    ScopedFlushToZero() {
        asm volatile("vmrs %0, fpscr" : "=r"(saved));
        asm volatile("vmsr fpscr, %0" : : "r"(saved | (1u << 24)));
    }
    ~ScopedFlushToZero() { asm volatile("vmsr fpscr, %0" : : "r"(saved)); }
};
#else
struct ScopedFlushToZero {};
#endif

class Plugin;

class Editor : public Percussa::SSP::PluginEditorInterface {
public:
    explicit Editor(const Plugin& p) : p_(p) {}
    void renderToImage(unsigned char* buffer, int width, int height) override;

private:
    const Plugin& p_;
};

class Plugin : public Percussa::SSP::PluginInterface {
public:
    Plugin()
        : nIn_(wrapper_num_inputs()),
          nOut_(wrapper_num_outputs()),
          params_(size_t(wrapper_num_params())),
          values_(params_.size()),
          applied_(params_.size()) {
        // eager, so parameter metadata exists before prepare()
        state_ = wrapper_create(float(sr_), block_);
        for (size_t i = 0; i < params_.size(); i++) {
            int idx = int(i);
            Param& p = params_[i];
            const char* name = wrapper_param_name(state_, idx);
            p.name = name ? name : "p" + std::to_string(i + 1);
            p.min = wrapper_param_min(state_, idx);
            p.max = wrapper_param_max(state_, idx);
            if (p.max < p.min) std::swap(p.min, p.max);
            // gen~ initial values can exceed the declared range
            p.def = clamp(p, wrapper_get_param(state_, idx));
            values_[i].store(p.def);
        }
        allocate();
        loadBuffers();
    }

    ~Plugin() override {
        delete editor_;
        wrapper_destroy(state_);
    }

    Percussa::SSP::PluginEditorInterface* getEditor() override {
        if (editor_ == nullptr) editor_ = new Editor(*this);
        return editor_;
    }

    void prepare(double sampleRate, int samplesPerBlock) override {
        if (sampleRate <= 0.0) sampleRate = DEFAULT_SR;
        if (samplesPerBlock <= 0) samplesPerBlock = DEFAULT_BLOCK;
        if (sampleRate != sr_ || samplesPerBlock != block_) {
            sr_ = sampleRate;
            block_ = samplesPerBlock;
            wrapper_destroy(state_);
            state_ = wrapper_create(float(sr_), block_);
            allocate();
            loadBuffers();  // a new instance starts with empty buffers
        }
    }

    // In-place buffer: channel c is input c on entry and output c on return.
    void process(float** channelData, int numChannels, int numSamples) override {
        ScopedFlushToZero ftz;
        applyParams();
        // the host may exceed the block size it announced
        for (int pos = 0; pos < numSamples; pos += block_) {
            int len = std::min(block_, numSamples - pos);
            for (int c = 0; c < nIn_; c++) {
                float* dst = inPtrs_[size_t(c)];
                if (c < numChannels && channelData[c])
                    std::memcpy(dst, channelData[c] + pos, size_t(len) * sizeof(float));
                else
                    std::memset(dst, 0, size_t(len) * sizeof(float));
            }
            for (int c = 0; c < nOut_; c++) {
                bool host = c < numChannels && channelData[c];
                outPtrs_[size_t(c)] = host ? channelData[c] + pos : spare_.data() + size_t(c) * size_t(block_);
            }
            wrapper_perform(state_, inPtrs_.data(), nIn_, outPtrs_.data(), nOut_, len);
        }
    }

    void encoderTurned(int n, int val) override {
        int i = page_.load() * ENCODERS + n;
        if (n < 0 || n >= ENCODERS || i >= numParams()) return;
        const Param& p = params_[size_t(i)];
        float step = (p.max - p.min) / STEPS;
        if (shift_.load() != 0) step /= FINE;
        set(i, values_[size_t(i)].load() + float(val) * step);
    }

    void encoderPressed(int n, bool val) override {
        int i = page_.load() * ENCODERS + n;
        if (!val || n < 0 || n >= ENCODERS || i >= numParams()) return;
        set(i, params_[size_t(i)].def);
    }

    void buttonPressed(int n, bool val) override {
        if (n == SHIFT_L || n == SHIFT_R) {
            int bit = 1 << (n - SHIFT_L);
            if (val)
                shift_.fetch_or(bit);
            else
                shift_.fetch_and(~bit);
            return;
        }
        if (!val) return;
        int page = page_.load();
        if (n >= 0 && n <= SOFT_LAST)
            page = n;
        else if (n == LEFT || n == UP)
            page--;
        else if (n == RIGHT || n == DOWN)
            page++;
        setPage(page);
    }

    void getState(void** buffer, size_t* size) override {
        std::string s = STATE_MAGIC;
        s += "\npage\t" + std::to_string(page_.load()) + "\n";
        char num[32];
        for (size_t i = 0; i < params_.size(); i++) {
            std::snprintf(num, sizeof(num), "%.9g", double(values_[i].load()));
            s += "param\t" + params_[i].name + "\t" + num + "\n";
        }
        auto* out = new char[s.size()];
        std::memcpy(out, s.data(), s.size());
        *buffer = out;
        *size = s.size();
    }

    // Parameters are matched by name, so presets survive reordering.
    void setState(void* buffer, size_t size) override {
        if (buffer == nullptr) return;
        std::string s(static_cast<const char*>(buffer), size);
        size_t pos = s.find('\n');
        if (s.compare(0, pos, STATE_MAGIC) != 0) return;
        while (pos != std::string::npos && pos < s.size()) {
            size_t start = pos + 1;
            pos = s.find('\n', start);
            std::string line = s.substr(start, pos == std::string::npos ? std::string::npos : pos - start);
            size_t tab1 = line.find('\t');
            if (tab1 == std::string::npos) continue;
            std::string key = line.substr(0, tab1);
            if (key == "page") {
                setPage(std::atoi(line.c_str() + tab1 + 1));
                continue;
            }
            size_t tab2 = line.find('\t', tab1 + 1);
            if (key != "param" || tab2 == std::string::npos) continue;
            std::string name = line.substr(tab1 + 1, tab2 - tab1 - 1);
            float v = std::strtof(line.c_str() + tab2 + 1, nullptr);
            for (size_t i = 0; i < params_.size(); i++)
                if (params_[i].name == name) set(int(i), v);
        }
    }

    // read by the editor
    int numParams() const { return int(params_.size()); }
    int numPages() const { return std::max(1, (numParams() + ENCODERS - 1) / ENCODERS); }
    int page() const { return page_.load(); }
    const Param& param(int i) const { return params_[size_t(i)]; }
    float value(int i) const { return values_[size_t(i)].load(); }
    const std::vector<std::string>& bufferStatus() const { return bufferStatus_; }

private:
    static float clamp(const Param& p, float v) { return std::min(p.max, std::max(p.min, v)); }

    void set(int i, float v) { values_[size_t(i)].store(clamp(params_[size_t(i)], v)); }

    void setPage(int page) { page_.store(std::min(numPages() - 1, std::max(0, page))); }

    // Called with the audio thread stopped: buffers for one block, all params re-applied.
    void allocate() {
        inBuf_.assign(size_t(nIn_) * size_t(block_), 0.0f);
        spare_.assign(size_t(nOut_) * size_t(block_), 0.0f);
        inPtrs_.resize(size_t(nIn_));
        outPtrs_.resize(size_t(nOut_));
        for (int c = 0; c < nIn_; c++) inPtrs_[size_t(c)] = inBuf_.data() + size_t(c) * size_t(block_);
        dirty_.assign(params_.size(), true);
    }

    // UI thread (constructor, prepare): reads each buffer's file, if there is one.
    void loadBuffers() {
        bufferStatus_.clear();
        std::string dir = ssp_buffer_dir(SSP_MODULE_NAME);
        for (int i = 0; i < wrapper_num_buffers(); i++) {
            std::string name = wrapper_buffer_name(i);
#if WRAPPER_BUFFER_COUNT > 0
            long frames = wrapper_buffer_load(state_, i, (dir + "/" + name + ".wav").c_str());
#else
            long frames = -1;
#endif
            bufferStatus_.push_back(name + ": " + (frames < 0 ? "no " SSP_MODULE_NAME "/" + name + ".wav" : std::to_string(frames) + " frames"));
        }
    }

    // Audio thread: genlib parameter state is only touched here.
    void applyParams() {
        for (size_t i = 0; i < params_.size(); i++) {
            float v = values_[i].load(std::memory_order_relaxed);
            if (dirty_[i] || v != applied_[i]) {
                wrapper_set_param(state_, int(i), v);
                applied_[i] = v;
                dirty_[i] = false;
            }
        }
    }

    GenState* state_ = nullptr;
    Editor* editor_ = nullptr;
    double sr_ = DEFAULT_SR;
    int block_ = DEFAULT_BLOCK;
    const int nIn_;
    const int nOut_;

    std::vector<Param> params_;
    std::vector<std::atomic<float>> values_;  // written by UI and encoder threads
    std::vector<float> applied_;              // audio thread
    std::vector<bool> dirty_;                 // audio thread
    std::atomic<int> page_{ 0 };
    std::atomic<int> shift_{ 0 };  // bit 0: Shift L, bit 1: Shift R

    std::vector<float> inBuf_;  // input copies: outputs overwrite the host buffer
    std::vector<float> spare_;  // outputs the host buffer lacks
    std::vector<float*> inPtrs_;
    std::vector<float*> outPtrs_;
    std::vector<std::string> bufferStatus_;  // UI thread
};

// -- Display --------------------------------------------------------------------

struct Canvas {
    uint32_t* px;
    int w, h;

    void fill(int x, int y, int rw, int rh, uint32_t c) {
        int x0 = std::max(0, x), y0 = std::max(0, y);
        int x1 = std::min(w, x + rw), y1 = std::min(h, y + rh);
        for (int j = y0; j < y1; j++)
            for (int i = x0; i < x1; i++) px[size_t(j) * size_t(w) + size_t(i)] = c;
    }

    // Draws at most maxChars glyphs of 6x8 cells scaled by s.
    void text(int x, int y, int s, const std::string& str, int maxChars, uint32_t c) {
        int n = std::min(int(str.size()), maxChars);
        for (int k = 0; k < n; k++) {
            unsigned char ch = static_cast<unsigned char>(str[size_t(k)]);
            if (ch < 0x20 || ch > 0x7E) ch = '?';
            const unsigned char* glyph = ssp_font5x8[ch - 0x20];
            for (int col = 0; col < 5; col++)
                for (int row = 0; row < 8; row++)
                    if (glyph[col] & (1 << row)) fill(x + (k * 6 + col) * s, y + row * s, s, s, c);
        }
    }
};

void Editor::renderToImage(unsigned char* buffer, int width, int height) {
    if (buffer == nullptr || width <= 0 || height <= 0) return;
    Canvas cv{ reinterpret_cast<uint32_t*>(buffer), width, height };
    // 0xAARRGGBB words are B,G,R,A bytes on a little-endian CPU
    const uint32_t black = 0xFF000000, white = 0xFFFFFFFF, grey = 0xFF404040, accent = COLOUR;

    // the host shares this buffer between modules and never clears it
    std::fill(cv.px, cv.px + size_t(width) * size_t(height), black);

    int s = std::max(1, height / 120);
    int colW = width / ENCODERS;
    int maxChars = std::max(1, (colW - 2 * s) / (6 * s));

    char title[64];
    std::snprintf(title, sizeof(title), "%s  %d/%d", SSP_DESCRIPTION, p_.page() + 1, p_.numPages());
    cv.text(2 * s, 2 * s, s, title, width / (6 * s), accent);
    int y = 14 * s;
    for (const std::string& line : p_.bufferStatus()) {
        if (y + 8 * s > height / 2) break;  // above the parameter rows
        cv.text(2 * s, y, s, line, width / (6 * s), white);
        y += 10 * s;
    }

    int yName = height / 2;
    int yValue = yName + 10 * s;
    int yBar = yValue + 10 * s;
    char num[32];
    for (int k = 0; k < ENCODERS; k++) {
        int i = p_.page() * ENCODERS + k;
        if (i >= p_.numParams()) break;
        const Param& p = p_.param(i);
        float v = p_.value(i);
        int x = k * colW + 2 * s;
        cv.text(x, yName, s, p.name, maxChars, white);
        std::snprintf(num, sizeof(num), "%.4g", double(v));
        cv.text(x, yValue, s, num, maxChars, white);
        int barW = colW - 4 * s;
        float norm = p.max > p.min ? (v - p.min) / (p.max - p.min) : 0.0f;
        cv.fill(x, yBar, barW, 3 * s, grey);
        cv.fill(x, yBar, int(norm * float(barW)), 3 * s, accent);
    }
}

}  // namespace

// -- C entry points ---------------------------------------------------------------

extern "C" __attribute__((visibility("default"))) Percussa::SSP::PluginDescriptor* createDescriptor() {
    auto* d = new Percussa::SSP::PluginDescriptor;
    d->name = SSP_MODULE_NAME;
    d->descriptiveName = SSP_DESCRIPTION;
    d->manufacturerName = "gen-dsp";
    d->version = GENDSP_VERSION;
    // the uid spells the name: Synthor lists only modules whose uid matches it
    static_assert(sizeof(SSP_MODULE_NAME) == 5, "SSP_MODULE_NAME must be 4 characters");
    const char* name = SSP_MODULE_NAME;
    int uid = 0;
    for (int k = 0; k < 4; k++) uid = (uid << 8) | std::toupper(static_cast<unsigned char>(name[k]));
    d->uid = uid;
    for (int c = 0; c < wrapper_num_inputs(); c++) d->inputChannelNames.push_back("In " + std::to_string(c + 1));
    for (int c = 0; c < wrapper_num_outputs(); c++) d->outputChannelNames.push_back("Out " + std::to_string(c + 1));
    d->colour = COLOUR;
    return d;
}

extern "C" __attribute__((visibility("default"))) Percussa::SSP::PluginInterface* createInstance() {
    return new Plugin();
}

extern "C" __attribute__((visibility("default"))) void getApiVersion(unsigned& major, unsigned& minor) {
    major = Percussa::SSP::API_MAJOR_VERSION;
    minor = Percussa::SSP::API_MINOR_VERSION;
}
