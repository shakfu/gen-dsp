// remap_instances_test.cpp - two instances of one gen~ export built with --inputs-as-params:
// each keeps its own remapped values, both perform at once on two threads, and a block
// longer than the size given at creation still sees its values.
// Compiled against any backend's _ext_<platform>.cpp; EXT_HEADER names its header.
// Expects an export whose inputs are all remapped, with at least one remapped input.

#include <cmath>
#include <cstdio>
#include <thread>
#include <vector>

#include EXT_HEADER

using namespace WRAPPER_NAMESPACE;

constexpr long BLOCK = 64;
constexpr int BLOCKS = 400;

static int remapParam() {
    return wrapper_num_params() - 1;  // remapped inputs follow gen~'s own parameters
}

// Runs `blocks` blocks of `n` samples, returning output 1.
static std::vector<float> run(GenState* s, int blocks, long n) {
    std::vector<float> out(size_t(blocks) * size_t(n));
    std::vector<std::vector<float>> bufs{ size_t(wrapper_num_outputs()), std::vector<float>(size_t(n)) };
    std::vector<float*> outs;
    for (auto& b : bufs) outs.push_back(b.data());
    for (int b = 0; b < blocks; b++) {
        wrapper_perform(s, nullptr, 0, outs.data(), long(outs.size()), n);
        std::copy(bufs[0].begin(), bufs[0].end(), out.begin() + b * n);
    }
    return out;
}

static GenState* make(float value, long bs = BLOCK) {
    GenState* s = wrapper_create(48000.0f, bs);
    wrapper_set_param(s, remapParam(), value);
    return s;
}

#define CHECK(c)                                                   \
    if (!(c)) {                                                    \
        std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #c); \
        return 1;                                                  \
    }

int main() {
    CHECK(wrapper_num_inputs() == 0);  // every input is a parameter

    // references, one instance at a time
    GenState* r1 = make(0.2f);
    std::vector<float> want1 = run(r1, BLOCKS, BLOCK);
    GenState* r2 = make(0.8f);
    std::vector<float> want2 = run(r2, BLOCKS, BLOCK);
    CHECK(want1 != want2);  // the value reaches the output
    wrapper_destroy(r1);
    wrapper_destroy(r2);

    // each instance keeps its own value
    GenState* a = make(0.2f);
    GenState* b = make(0.8f);
    CHECK(wrapper_get_param(a, remapParam()) == 0.2f);
    CHECK(wrapper_get_param(b, remapParam()) == 0.8f);

    // both at once, on two threads
    std::vector<float> gotA, gotB;
    std::thread ta([&] { gotA = run(a, BLOCKS, BLOCK); });
    std::thread tb([&] { gotB = run(b, BLOCKS, BLOCK); });
    ta.join();
    tb.join();
    CHECK(gotA == want1);
    CHECK(gotB == want2);
    wrapper_destroy(a);
    wrapper_destroy(b);

    // a block longer than the creation size equals the same samples in creation-size blocks
    GenState* small = make(0.2f, BLOCK);
    GenState* whole = make(0.2f, BLOCK);
    std::vector<float> chunked = run(small, 5, BLOCK);
    std::vector<float> oneBlock = run(whole, 1, 5 * BLOCK);
    CHECK(chunked == oneBlock);
    wrapper_destroy(small);
    wrapper_destroy(whole);

    std::puts("ok");
    return 0;
}
