// ssp_host.cpp - drives an SSP module through the Percussa API, as Synthor does.
// Usage: ssp_host MODULE.so CMD...  (see main() for the commands)

#include <dlfcn.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "Percussa.h"

using namespace Percussa::SSP;

static std::string getState(PluginInterface* p) {
    void* buf = nullptr;
    size_t size = 0;
    p->getState(&buf, &size);
    std::string s(static_cast<char*>(buf), size);
    delete[] static_cast<char*>(buf);  // the host frees with delete[]
    return s;
}

int main(int argc, char** argv) {
    if (argc < 2) return 2;
    void* so = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (so == nullptr) {
        std::fprintf(stderr, "%s\n", dlerror());
        return 1;
    }
    auto version = reinterpret_cast<VersionFun>(dlsym(so, getApiVersionName));
    auto descFun = reinterpret_cast<DescriptorFun>(dlsym(so, createDescriptorName));
    auto instFun = reinterpret_cast<InstantiateFun>(dlsym(so, createInstanceName));
    if (!version || !descFun || !instFun) {
        std::fprintf(stderr, "missing entry point\n");
        return 1;
    }
    PluginDescriptor* desc = descFun();
    PluginInterface* p = instFun();
    int nIn = int(desc->inputChannelNames.size()), nOut = int(desc->outputChannelNames.size());
    int nCh = std::max(nIn, nOut);  // one in-place buffer, as Synthor and rack pass
    std::string saved;

    for (int a = 2; a < argc; a++) {
        std::string cmd = argv[a];
        if (cmd == "desc") {
            unsigned major = 0, minor = 0;
            version(major, minor);
            std::printf("api %u.%u\n", major, minor);
            std::printf("name %s\n", desc->name.c_str());
            std::printf("uid %08x\n", unsigned(desc->uid));
            std::printf("io %d %d\n", nIn, nOut);
        } else if (cmd == "prepare") {  // prepare SR BLOCK
            p->prepare(std::atof(argv[a + 1]), std::atoi(argv[a + 2]));
            a += 2;
        } else if (cmd == "run") {  // run BLOCKS SAMPLES: impulse into every input, then silence
            int blocks = std::atoi(argv[a + 1]), n = std::atoi(argv[a + 2]);
            a += 2;
            std::vector<std::vector<float>> buf(static_cast<size_t>(nCh), std::vector<float>(static_cast<size_t>(n)));
            std::vector<float*> ptrs(static_cast<size_t>(nCh));
            std::vector<double> level(static_cast<size_t>(nOut), 0.0);
            bool finite = true;
            for (int b = 0; b < blocks; b++) {
                for (int c = 0; c < nCh; c++) {
                    std::fill(buf[size_t(c)].begin(), buf[size_t(c)].end(), 0.0f);
                    if (b == 0 && c < nIn) buf[size_t(c)][0] = 1.0f;
                    ptrs[size_t(c)] = buf[size_t(c)].data();
                }
                p->process(ptrs.data(), nCh, n);
                for (int c = 0; c < nOut; c++)
                    for (float v : buf[size_t(c)]) {
                        finite = finite && std::isfinite(v);
                        level[size_t(c)] += std::fabs(v);
                    }
            }
            for (int c = 0; c < nOut; c++) std::printf("level %d %g\n", c, level[size_t(c)]);
            std::printf("finite %d\n", finite ? 1 : 0);
        } else if (cmd == "turn") {  // turn ENCODER PULSES
            p->encoderTurned(std::atoi(argv[a + 1]), std::atoi(argv[a + 2]));
            a += 2;
        } else if (cmd == "press") {  // press ENCODER
            p->encoderPressed(std::atoi(argv[a + 1]), true);
            p->encoderPressed(std::atoi(argv[a + 1]), false);
            a += 1;
        } else if (cmd == "down" || cmd == "up") {  // down|up BUTTON
            p->buttonPressed(std::atoi(argv[a + 1]), cmd == "down");
            a += 1;
        } else if (cmd == "state") {
            std::string s = getState(p);
            size_t pos = 0, nl;
            while ((nl = s.find('\n', pos)) != std::string::npos) {
                std::printf("state %s\n", s.substr(pos, nl - pos).c_str());
                pos = nl + 1;
            }
        } else if (cmd == "save") {
            saved = getState(p);
        } else if (cmd == "load") {
            p->setState(saved.data(), saved.size());
        } else if (cmd == "render") {  // render W H OUT.ppm
            int w = std::atoi(argv[a + 1]), h = std::atoi(argv[a + 2]);
            const char* path = argv[a + 3];
            a += 3;
            std::vector<unsigned char> img(size_t(w) * size_t(h) * 4, 0x55);  // not cleared by the host
            p->getEditor()->renderToImage(img.data(), w, h);
            FILE* f = std::fopen(path, "wb");
            if (f == nullptr) return 1;
            std::fprintf(f, "P6\n%d %d\n255\n", w, h);
            for (size_t i = 0; i < size_t(w) * size_t(h); i++) {
                unsigned char rgb[3] = { img[i * 4 + 2], img[i * 4 + 1], img[i * 4] };
                std::fwrite(rgb, 1, 3, f);
            }
            std::fclose(f);
        } else {
            std::fprintf(stderr, "unknown command %s\n", cmd.c_str());
            return 2;
        }
    }
    delete p;  // the host owns the instance and descriptor
    delete desc;
    return 0;
}
