// ssp_buffers_test.cpp - drives the genlib side of an SSP project directly: per-instance
// buffers, instances on two threads, and loads while another thread performs.
// Built against a generated RamplePlayer project, whose out1 plays its buffer `sample`
// at the input's position: with silent input, the buffer's first value.
// Usage: ssp_buffers_test A.wav B.wav  (1000 frames each, constant 0.5 and 0.25)

#include <atomic>
#include <cmath>
#include <cstdio>
#include <thread>

#include "_ext_ssp_buffers.h"

using namespace WRAPPER_NAMESPACE;

static float run(GenState* s) {
    constexpr int n = 64;
    float in[n] = {}, out1[n], out2[n];
    float* ins[] = { in };
    float* outs[] = { out1, out2 };
    wrapper_perform(s, ins, 1, outs, 2, n);
    return out1[n - 1];
}

static bool is(float v, float want) {
    return std::fabs(v - want) < 1e-6f;
}

#define CHECK(c)                                                   \
    if (!(c)) {                                                    \
        std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #c); \
        return 1;                                                  \
    }

int main(int argc, char** argv) {
    if (argc < 3) return 2;
    const char* files[] = { argv[1], argv[2] };
    GenState* a = wrapper_create(48000.0f, 64);
    GenState* b = wrapper_create(48000.0f, 64);

    CHECK(is(run(a), 0.0f));  // empty until a load
    CHECK(wrapper_buffer_load(a, 0, files[0]) == 1000);
    CHECK(wrapper_buffer_load(b, 0, files[1]) == 1000);
    CHECK(wrapper_buffer_load(a, 0, "/nonexistent.wav") == -1);
    CHECK(wrapper_buffer_load(a, 1, files[0]) == -1);  // no such buffer
    CHECK(is(run(a), 0.5f));
    CHECK(is(run(b), 0.25f));  // instances keep their own data

    // one instance per thread, at the same time
    std::atomic<int> bad{ 0 };
    std::thread ta([&] {
        for (int i = 0; i < 20000; i++)
            if (!is(run(a), 0.5f)) bad++;
    });
    std::thread tb([&] {
        for (int i = 0; i < 20000; i++)
            if (!is(run(b), 0.25f)) bad++;
    });
    ta.join();
    tb.join();
    CHECK(bad == 0);

    // loads while another thread performs: every block sees one whole file
    std::atomic<bool> stop{ false };
    std::thread audio([&] {
        while (!stop)
            if (float v = run(a); !is(v, 0.5f) && !is(v, 0.25f)) bad++;
    });
    for (int i = 0; i < 500; i++) wrapper_buffer_load(a, 0, files[i % 2]);
    stop = true;
    audio.join();
    CHECK(bad == 0);
    CHECK(is(run(a), 0.25f));  // the last load

    wrapper_destroy(a);
    wrapper_destroy(b);
    std::puts("ok");
    return 0;
}
