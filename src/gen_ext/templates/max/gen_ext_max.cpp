// gen_ext_max.cpp - Max/MSP wrapper for gen~ exports
// This file includes ONLY Max headers - genlib is isolated in _ext_max.cpp

// Max SDK headers must be included first
#include "ext.h"
#include "ext_obex.h"
#include "z_dsp.h"
#include "ext_buffer.h"

#include "gen_ext_common_max.h"
#include "_ext_max.h"

namespace WRAPPER_NAMESPACE {

static t_class *WRAPPER_CLASS = nullptr;

typedef struct WRAPPER_STRUCT {
    t_pxobject ob;              // MSP object (must be first)

    double x_sr;                // Sample rate
    long x_bs;                  // Block size (vector size)

    GenState* m_genObject;      // gen~ state object (opaque)

    int x_num_inputs;
    int x_num_outputs;

    t_symbol **x_param_symbols;
    int x_num_params;

    // Buffer handling
#if WRAPPER_BUFFER_COUNT > 0
    t_buffer_ref *x_buffer_refs[WRAPPER_BUFFER_COUNT];
    t_symbol *x_buffer_symbols[WRAPPER_BUFFER_COUNT];
#endif
    int x_num_buffers;

} WRAPPER_TYPE;


// Forward declarations
void WRAPPER_DSP64(WRAPPER_TYPE *x, t_object *dsp64, short *count,
                   double samplerate, long maxvectorsize, long flags);
void WRAPPER_PERFORM64(WRAPPER_TYPE *x, t_object *dsp64,
                       double **ins, long numins,
                       double **outs, long numouts,
                       long sampleframes, long flags, void *userparam);
void WRAPPER_ANYTHING(WRAPPER_TYPE *x, t_symbol *s, long argc, t_atom *argv);
void WRAPPER_ASSIST(WRAPPER_TYPE *x, void *b, long io, long idx, char *s);
void WRAPPER_BANG(WRAPPER_TYPE *x);
void WRAPPER_RESET(WRAPPER_TYPE *x);
void WRAPPER_FREE(WRAPPER_TYPE *x);


void *WRAPPER_NEW(t_symbol *s, long argc, t_atom *argv)
{
    WRAPPER_TYPE *x = (WRAPPER_TYPE *)object_alloc(WRAPPER_CLASS);
    if (!x) return nullptr;

    x->x_num_buffers = WRAPPER_BUFFER_COUNT;

#if WRAPPER_BUFFER_COUNT > 0
    // Initialize buffer refs and symbols
    for (int i = 0; i < WRAPPER_BUFFER_COUNT; i++) {
        x->x_buffer_refs[i] = nullptr;
        x->x_buffer_symbols[i] = nullptr;
    }

    // Set default buffer names from macros
#ifdef WRAPPER_BUFFER_NAME_0
    if (WRAPPER_BUFFER_COUNT >= 1) x->x_buffer_symbols[0] = gensym(STR(WRAPPER_BUFFER_NAME_0));
#endif
#ifdef WRAPPER_BUFFER_NAME_1
    if (WRAPPER_BUFFER_COUNT >= 2) x->x_buffer_symbols[1] = gensym(STR(WRAPPER_BUFFER_NAME_1));
#endif
#ifdef WRAPPER_BUFFER_NAME_2
    if (WRAPPER_BUFFER_COUNT >= 3) x->x_buffer_symbols[2] = gensym(STR(WRAPPER_BUFFER_NAME_2));
#endif
#ifdef WRAPPER_BUFFER_NAME_3
    if (WRAPPER_BUFFER_COUNT >= 4) x->x_buffer_symbols[3] = gensym(STR(WRAPPER_BUFFER_NAME_3));
#endif
#ifdef WRAPPER_BUFFER_NAME_4
    if (WRAPPER_BUFFER_COUNT >= 5) x->x_buffer_symbols[4] = gensym(STR(WRAPPER_BUFFER_NAME_4));
#endif
#endif

    x->x_sr = sys_getsr();
    x->x_bs = sys_getblksize();

    // Create gen~ object using wrapper function
    x->m_genObject = wrapper_create(x->x_sr, x->x_bs);

    x->x_num_inputs = wrapper_num_inputs();
    x->x_num_outputs = wrapper_num_outputs();

    // Initialize parameter symbols
    x->x_num_params = wrapper_num_params();
    if (x->x_num_params > 0) {
        x->x_param_symbols = new t_symbol*[x->x_num_params];
        for (int i = 0; i < x->x_num_params; i++) {
            x->x_param_symbols[i] = gensym(wrapper_param_name(x->m_genObject, i));
        }
    } else {
        x->x_param_symbols = nullptr;
    }

    // Set up DSP (creates signal inlets)
    dsp_setup((t_pxobject *)x, x->x_num_inputs);

    // Create signal outlets
    for (int i = 0; i < x->x_num_outputs; i++) {
        outlet_new((t_object *)x, "signal");
    }

    return x;
}


void WRAPPER_FREE(WRAPPER_TYPE *x)
{
    if (!x) return;

    // Free gen~ object
    if (x->m_genObject) {
        wrapper_destroy(x->m_genObject);
    }

    // Free parameter symbols
    if (x->x_param_symbols) {
        delete[] x->x_param_symbols;
    }

#if WRAPPER_BUFFER_COUNT > 0
    // Free buffer references
    for (int i = 0; i < WRAPPER_BUFFER_COUNT; i++) {
        if (x->x_buffer_refs[i]) {
            object_free(x->x_buffer_refs[i]);
        }
    }
#endif

    // Required for signal objects
    dsp_free((t_pxobject *)x);
}


void WRAPPER_DSP64(WRAPPER_TYPE *x, t_object *dsp64, short *count,
                   double samplerate, long maxvectorsize, long flags)
{
    // Update sample rate and block size if changed
    if (x->x_sr != samplerate || x->x_bs != maxvectorsize) {
        if (x->m_genObject) wrapper_destroy(x->m_genObject);
        x->x_sr = samplerate;
        x->x_bs = maxvectorsize;
        x->m_genObject = wrapper_create(x->x_sr, x->x_bs);
    }

#if WRAPPER_BUFFER_COUNT > 0
    // Create/update buffer references
    for (int i = 0; i < x->x_num_buffers; i++) {
        if (x->x_buffer_symbols[i]) {
            if (x->x_buffer_refs[i]) {
                buffer_ref_set(x->x_buffer_refs[i], x->x_buffer_symbols[i]);
            } else {
                x->x_buffer_refs[i] = buffer_ref_new((t_object *)x, x->x_buffer_symbols[i]);
            }
        }
    }
#endif

    // Register perform routine
    object_method(dsp64, gensym("dsp_add64"), x, WRAPPER_PERFORM64, 0, nullptr);
}


void WRAPPER_PERFORM64(WRAPPER_TYPE *x, t_object *dsp64,
                       double **ins, long numins,
                       double **outs, long numouts,
                       long sampleframes, long flags, void *userparam)
{
#if WRAPPER_BUFFER_COUNT > 0
    // Lock buffers and pass data to gen~ side
    for (int i = 0; i < x->x_num_buffers; i++) {
        if (x->x_buffer_refs[i]) {
            t_buffer_obj *bufobj = buffer_ref_getobject(x->x_buffer_refs[i]);
            if (bufobj) {
                float *samples = buffer_locksamples(bufobj);
                if (samples) {
                    t_buffer_info info;
                    buffer_getinfo(bufobj, &info);
                    wrapper_set_buffer(i, samples, info.b_frames, info.b_nchans);
                } else {
                    wrapper_set_buffer(i, nullptr, 0, 1);
                }
            } else {
                wrapper_set_buffer(i, nullptr, 0, 1);
            }
        }
    }
#endif

    // Call gen~ perform (t_sample is double, matching Max)
    wrapper_perform(x->m_genObject, ins, (long)numins, outs, (long)numouts, sampleframes);

#if WRAPPER_BUFFER_COUNT > 0
    // Unlock buffers
    for (int i = 0; i < x->x_num_buffers; i++) {
        if (x->x_buffer_refs[i]) {
            t_buffer_obj *bufobj = buffer_ref_getobject(x->x_buffer_refs[i]);
            if (bufobj) {
                buffer_unlocksamples(bufobj);
            }
        }
        wrapper_set_buffer(i, nullptr, 0, 1);  // Clear gen~ side reference
    }
#endif
}


void WRAPPER_ANYTHING(WRAPPER_TYPE *x, t_symbol *s, long argc, t_atom *argv)
{
    // Look up parameter by name
    for (int i = 0; i < x->x_num_params; i++) {
        if (s == x->x_param_symbols[i]) {
            if (argc > 0) {
                double value = atom_getfloat(argv);
                wrapper_set_param(x->m_genObject, i, value);
            }
            return;
        }
    }

#if WRAPPER_BUFFER_COUNT > 0
    // Check if it's a buffer set message
    for (int i = 0; i < x->x_num_buffers; i++) {
        const char *bufname = wrapper_buffer_name(i);
        if (bufname && s == gensym(bufname)) {
            if (argc > 0 && atom_gettype(argv) == A_SYM) {
                x->x_buffer_symbols[i] = atom_getsym(argv);
                if (x->x_buffer_refs[i]) {
                    buffer_ref_set(x->x_buffer_refs[i], x->x_buffer_symbols[i]);
                }
            }
            return;
        }
    }
#endif

    object_error((t_object *)x, "%s~ does not recognize: %s",
                 STR(MAX_EXT_NAME), s->s_name);
}


void WRAPPER_ASSIST(WRAPPER_TYPE *x, void *b, long io, long idx, char *s)
{
    if (io == ASSIST_INLET) {
        if (idx < x->x_num_inputs) {
            snprintf(s, 256, "(signal) audio input %ld", idx + 1);
        }
    } else if (io == ASSIST_OUTLET) {
        if (idx < x->x_num_outputs) {
            snprintf(s, 256, "(signal) audio output %ld", idx + 1);
        }
    }
}


void WRAPPER_BANG(WRAPPER_TYPE *x)
{
    object_post((t_object *)x, "gen-ext wrapper v%s (Max)", STR(GEN_EXT_VERSION));
    object_post((t_object *)x, "%s~ samplerate: %g, blocksize: %ld",
                STR(MAX_EXT_NAME), x->x_sr, x->x_bs);
    object_post((t_object *)x, "signal inputs: %d", x->x_num_inputs);
    object_post((t_object *)x, "signal outputs: %d", x->x_num_outputs);
    object_post((t_object *)x, "parameters: %d", x->x_num_params);

    for (int i = 0; i < x->x_num_params; i++) {
        const char *name = wrapper_param_name(x->m_genObject, i);
        const char *units = wrapper_param_units(x->m_genObject, i);
        char hasMinMax = wrapper_param_hasminmax(x->m_genObject, i);

        if (hasMinMax) {
            double minp = wrapper_param_min(x->m_genObject, i);
            double maxp = wrapper_param_max(x->m_genObject, i);
            if (units && units[0]) {
                object_post((t_object *)x, "  %s: min=%g, max=%g, units=%s",
                           name, minp, maxp, units);
            } else {
                object_post((t_object *)x, "  %s: min=%g, max=%g", name, minp, maxp);
            }
        } else {
            if (units && units[0]) {
                object_post((t_object *)x, "  %s: units=%s", name, units);
            } else {
                object_post((t_object *)x, "  %s", name);
            }
        }
    }

#if WRAPPER_BUFFER_COUNT > 0
    object_post((t_object *)x, "buffers: %d", x->x_num_buffers);
    for (int i = 0; i < x->x_num_buffers; i++) {
        const char *name = wrapper_buffer_name(i);
        if (name) {
            if (x->x_buffer_symbols[i]) {
                object_post((t_object *)x, "  %s -> %s", name, x->x_buffer_symbols[i]->s_name);
            } else {
                object_post((t_object *)x, "  %s (unassigned)", name);
            }
        }
    }
#endif
}


void WRAPPER_RESET(WRAPPER_TYPE *x)
{
    if (x->m_genObject) {
        wrapper_reset(x->m_genObject);
    }
}


} // namespace WRAPPER_NAMESPACE


// Entry point - must be extern "C" and named ext_main
extern "C" void ext_main(void *r)
{
    using namespace WRAPPER_NAMESPACE;

    t_class *c = class_new(STR(MAX_EXT_NAME) "~",
                           (method)WRAPPER_NEW,
                           (method)WRAPPER_FREE,
                           sizeof(WRAPPER_TYPE),
                           0L,
                           A_GIMME,
                           0);

    // DSP method (required for signal objects)
    class_addmethod(c, (method)WRAPPER_DSP64, "dsp64", A_CANT, 0);

    // Utility methods
    class_addmethod(c, (method)WRAPPER_ASSIST, "assist", A_CANT, 0);
    class_addmethod(c, (method)WRAPPER_BANG, "bang", 0);
    class_addmethod(c, (method)WRAPPER_RESET, "reset", 0);

    // Generic message handler for parameters
    class_addmethod(c, (method)WRAPPER_ANYTHING, "anything", A_GIMME, 0);

    // Initialize DSP (CRITICAL - marks class as signal processor)
    class_dspinit(c);

    // Register the class
    class_register(CLASS_BOX, c);
    WRAPPER_CLASS = c;
}
