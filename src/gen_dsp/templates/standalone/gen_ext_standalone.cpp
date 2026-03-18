// gen_ext_standalone.cpp - Standalone audio application using miniaudio
// This file includes ONLY host API headers (miniaudio), NO genlib headers

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <csignal>

#include "_ext_standalone.h"

#define MINIAUDIO_IMPLEMENTATION
#include "miniaudio.h"

using namespace WRAPPER_NAMESPACE;

// -- Global state ----------------------------------------------------------

static GenState* g_state = nullptr;
static int g_num_inputs = 0;
static int g_num_outputs = 0;         // gen~ output channel count
static int g_device_out_channels = 0; // actual device playback channels (>= g_num_outputs)
static volatile bool g_running = true;

static void signal_handler(int) {
    g_running = false;
}

// -- miniaudio callback ----------------------------------------------------

// Static buffers for deinterleaving -- audio callback threads have small
// stacks (64-512 KB on macOS), so these must not be stack-allocated.
// Maximum: 64 channels * 1024 frames per channel.
static const int MAX_CHANNELS = 64;
static const int MAX_FRAMES = 1024;
static float s_in_storage[MAX_CHANNELS * MAX_FRAMES];
static float s_out_storage[MAX_CHANNELS * MAX_FRAMES];

static void audio_callback(
    ma_device* device,
    void* output,
    const void* input,
    ma_uint32 frame_count
) {
    (void)device;

    float* out_interleaved = (float*)output;
    const float* in_interleaved = (const float*)input;

    int num_in = g_num_inputs;
    int num_out = g_num_outputs;
    long n = (long)frame_count;
    if (n > MAX_FRAMES) n = MAX_FRAMES;

    // Deinterleave input
    float* in_channels[MAX_CHANNELS] = {};
    if (num_in > 0 && in_interleaved) {
        for (int ch = 0; ch < num_in && ch < MAX_CHANNELS; ch++) {
            in_channels[ch] = &s_in_storage[ch * n];
        }
        for (long i = 0; i < n; i++) {
            for (int ch = 0; ch < num_in && ch < MAX_CHANNELS; ch++) {
                in_channels[ch][i] = in_interleaved[i * num_in + ch];
            }
        }
    }

    // Set up output channel pointers
    float* out_channels[MAX_CHANNELS] = {};
    for (int ch = 0; ch < num_out && ch < MAX_CHANNELS; ch++) {
        out_channels[ch] = &s_out_storage[ch * n];
        for (long i = 0; i < n; i++) out_channels[ch][i] = 0.0f;
    }

    // Process
    wrapper_perform(g_state, in_channels, (long)num_in, out_channels, (long)num_out, n);

    // Interleave output into device channels (may be wider than gen~ outputs)
    int dev_ch = g_device_out_channels;
    for (long i = 0; i < n; i++) {
        for (int ch = 0; ch < dev_ch; ch++) {
            // If device has more channels than gen~, duplicate last gen~ channel
            int src_ch = ch < num_out ? ch : num_out - 1;
            out_interleaved[i * dev_ch + ch] = out_channels[src_ch][i];
        }
    }
}

// -- Usage / help ----------------------------------------------------------

static void print_usage(const char* prog) {
    fprintf(stderr, "Usage: %s [options]\n", prog);
    fprintf(stderr, "Options:\n");
    fprintf(stderr, "  -sr <rate>          Sample rate (default: 44100)\n");
    fprintf(stderr, "  -bs <frames>        Block size (default: 256)\n");
    fprintf(stderr, "  -p <name> <value>   Set parameter value\n");
    fprintf(stderr, "  -l                  List parameters and exit\n");
    fprintf(stderr, "  -h                  Show this help\n");
}

// -- Main ------------------------------------------------------------------

int main(int argc, char* argv[]) {
    float sample_rate = 44100.0f;
    int block_size = 256;
    bool list_params = false;

    // Collect param settings to apply after state creation
    struct ParamSetting { const char* name; float value; };
    ParamSetting param_settings[256];
    int num_settings = 0;

    // Parse arguments
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-sr") == 0 && i + 1 < argc) {
            sample_rate = (float)atof(argv[++i]);
        } else if (strcmp(argv[i], "-bs") == 0 && i + 1 < argc) {
            block_size = atoi(argv[++i]);
        } else if (strcmp(argv[i], "-p") == 0 && i + 2 < argc) {
            if (num_settings < 256) {
                param_settings[num_settings].name = argv[i + 1];
                param_settings[num_settings].value = (float)atof(argv[i + 2]);
                num_settings++;
            }
            i += 2;
        } else if (strcmp(argv[i], "-l") == 0) {
            list_params = true;
        } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 0;
        } else {
            fprintf(stderr, "Unknown option: %s\n", argv[i]);
            print_usage(argv[0]);
            return 1;
        }
    }

    // Create gen~ state
    g_state = wrapper_create(sample_rate, (long)block_size);
    if (!g_state) {
        fprintf(stderr, "Failed to create gen~ state\n");
        return 1;
    }

    g_num_inputs = wrapper_num_inputs();
    g_num_outputs = wrapper_num_outputs();
    g_device_out_channels = g_num_outputs < 2 ? 2 : g_num_outputs;
    int num_params = wrapper_num_params();

    // List parameters mode
    if (list_params) {
        fprintf(stdout, "Parameters (%d):\n", num_params);
        for (int i = 0; i < num_params; i++) {
            const char* name = wrapper_param_name(g_state, i);
            float pmin = wrapper_param_min(g_state, i);
            float pmax = wrapper_param_max(g_state, i);
            float pval = wrapper_get_param(g_state, i);
            fprintf(stdout, "  [%d] %s = %.4f (range: %.4f .. %.4f)\n",
                    i, name ? name : "?", pval, pmin, pmax);
        }
        fprintf(stdout, "Audio I/O: %d inputs, %d outputs\n", g_num_inputs, g_num_outputs);
        wrapper_destroy(g_state);
        return 0;
    }

    // Apply parameter settings
    for (int s = 0; s < num_settings; s++) {
        bool found = false;
        for (int i = 0; i < num_params; i++) {
            const char* name = wrapper_param_name(g_state, i);
            if (name && strcmp(name, param_settings[s].name) == 0) {
                wrapper_set_param(g_state, i, param_settings[s].value);
                found = true;
                break;
            }
        }
        if (!found) {
            fprintf(stderr, "Warning: unknown parameter '%s'\n", param_settings[s].name);
        }
    }

    // Configure miniaudio device
    // Always open at least 2 playback channels -- many devices reject mono
    int device_out_channels = g_num_outputs < 2 ? 2 : g_num_outputs;
    ma_device_config config;
    if (g_num_inputs > 0) {
        config = ma_device_config_init(ma_device_type_duplex);
        config.capture.channels = (ma_uint32)g_num_inputs;
        config.capture.format = ma_format_f32;
    } else {
        config = ma_device_config_init(ma_device_type_playback);
    }
    config.playback.channels = (ma_uint32)device_out_channels;
    config.playback.format = ma_format_f32;
    config.sampleRate = (ma_uint32)sample_rate;
    config.periodSizeInFrames = (ma_uint32)block_size;
    config.dataCallback = audio_callback;

    ma_device device;
    ma_result result = ma_device_init(NULL, &config, &device);
    if (result != MA_SUCCESS) {
        fprintf(stderr, "Failed to initialize audio device (error %d)\n", result);
        wrapper_destroy(g_state);
        return 1;
    }

    // Print info
    fprintf(stderr, "%s (gen-dsp standalone v%s)\n",
            STR(STANDALONE_EXT_NAME), STR(GEN_EXT_VERSION));
    fprintf(stderr, "  Sample rate: %.0f Hz\n", sample_rate);
    fprintf(stderr, "  Block size:  %d frames\n", block_size);
    fprintf(stderr, "  Audio I/O:   %d in, %d out\n", g_num_inputs, g_num_outputs);
    fprintf(stderr, "  Parameters:  %d\n", num_params);
    fprintf(stderr, "Press Ctrl+C to stop.\n");

    // Install signal handler
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    // Start audio
    result = ma_device_start(&device);
    if (result != MA_SUCCESS) {
        fprintf(stderr, "Failed to start audio device (error %d)\n", result);
        ma_device_uninit(&device);
        wrapper_destroy(g_state);
        return 1;
    }

    // Run until interrupted
    while (g_running) {
        ma_sleep(100);
    }

    fprintf(stderr, "\nStopping...\n");

    ma_device_uninit(&device);
    wrapper_destroy(g_state);

    return 0;
}
