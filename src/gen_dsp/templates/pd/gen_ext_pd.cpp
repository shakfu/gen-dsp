// gen_ext_pd.cpp - PD external wrapper for dsp-graph compiled code
// This file includes ONLY PD headers - graph code is isolated in _ext_pd.cpp

#include "gen_ext_common_pd.h"

#include "pd-include/m_pd.h"
#include "_ext_pd.h"

namespace WRAPPER_NAMESPACE {

using namespace WRAPPER_NAMESPACE;

static t_class *WRAPPER_CLASS;

typedef struct WRAPPER_STRUCT {
  t_object  x_obj;

  float x_sr;
  int x_bs;

  t_float f;

  GenState* m_state;

  int x_num_inputs;
  int x_num_outputs;

  t_symbol **x_param_symbols;
  int x_num_params;

} WRAPPER_TYPE;


static void *WRAPPER_NEW(void)
{
  WRAPPER_TYPE *x = (WRAPPER_TYPE *)pd_new(WRAPPER_CLASS);

  x->x_sr = sys_getsr();
  x->x_bs = sys_getblksize();

  x->m_state = wrapper_create(x->x_sr, x->x_bs);

  x->x_num_inputs = wrapper_num_inputs();
  x->x_num_outputs = wrapper_num_outputs();

  x->x_num_params = wrapper_num_params();
  if (x->x_num_params > 0) {
    x->x_param_symbols = (t_symbol **)getbytes(sizeof(t_symbol *) * x->x_num_params);
    for (int i = 0; i < x->x_num_params; i++) {
      x->x_param_symbols[i] = gensym(wrapper_param_name(x->m_state, i));
    }
  }

  int ni = x->x_num_inputs - 1; // first input is created in _create
  if (ni > 0) {
    while(ni--){
      inlet_new(&x->x_obj, &x->x_obj.ob_pd, &s_signal, &s_signal);
    }
  }

  int no = x->x_num_outputs;
  while(no--) {
    outlet_new(&x->x_obj, &s_signal);
  }

  return (void *)x;
}

static void WRAPPER_FREE(WRAPPER_TYPE *x) {
  if (x->m_state) { wrapper_destroy(x->m_state); }
  if (x->x_num_params > 0) {
    freebytes(x->x_param_symbols, sizeof(t_symbol *) * x->x_num_params);
  }
}

static t_int *WRAPPER_PERFORM(t_int *w)
{
  WRAPPER_TYPE *x = (WRAPPER_TYPE *)(w[1]);

  int inputIndex = 2;
  int outputIndex = inputIndex + x->x_num_inputs;
  int sampleCountIndex = outputIndex + x->x_num_outputs;

  int n = (int)(w[sampleCountIndex]);

  wrapper_perform(x->m_state, (float **)(&w[inputIndex]), x->x_num_inputs,
                  (float **)(&w[outputIndex]), x->x_num_outputs, n);

  return (w + sampleCountIndex + 1);
}

static void WRAPPER_DSP(WRAPPER_TYPE *x, t_signal **sp)
{
  int i;
  int inOutCount = x->x_num_inputs + x->x_num_outputs;
  int pointerCount = inOutCount + 2;
  t_int **sigvec = (t_int **)getbytes(sizeof(t_int) * (pointerCount));

  sigvec[0] = (t_int*)x;
  for (i = 0; i < inOutCount; i++) {
    sigvec[1 + i] = (t_int*)sp[i]->s_vec;
  }
  sigvec[1 + inOutCount] = (t_int*)sp[0]->s_n;
  dsp_addv(WRAPPER_PERFORM, pointerCount, (t_int*)sigvec);

  freebytes(sigvec, sizeof(t_int) * (pointerCount));
}


static void WRAPPER_ANY_METHOD(WRAPPER_TYPE *x, t_symbol *s, int argc, t_atom *argv) {
  for (int i = 0; i < x->x_num_params; i++) {
    if (s == x->x_param_symbols[i]) {
      if (argc > 0) {
        t_float f1 = atom_getfloatarg(0, argc, argv);
        wrapper_set_param(x->m_state, i, f1);
      }
      return;
    }
  }
  post("%s~ does not recognize the parameter %s. Send a bang to see recognized parameters.",
       STR(PD_EXT_NAME), s->s_name);
}

static void WRAPPER_BANG(WRAPPER_TYPE *x) {
  post("gen-dsp wrapper v%s", STR(GEN_EXT_VERSION));
  post("%s~ samplerate: %g, blocksize: %d", STR(PD_EXT_NAME), x->x_sr, x->x_bs);
  post("num_audio_rate_inputs: %d", x->x_num_inputs);
  post("num_audio_rate_outputs: %d", x->x_num_outputs);
  post("num params: %d", x->x_num_params);
  post("param: %s: set custom sample rate", STR(MESSAGE_SR));
  post("param: %s: set custom block size", STR(MESSAGE_BS));
  for (int i = 0; i < x->x_num_params; i++) {
    const char *name = wrapper_param_name(x->m_state, i);
    char hasMinMax = wrapper_param_hasminmax(x->m_state, i);
    if (hasMinMax) {
      float minp = wrapper_param_min(x->m_state, i);
      float maxp = wrapper_param_max(x->m_state, i);
      const char *units = wrapper_param_units(x->m_state, i);
      if (units && units[0]) {
        post("param: %s, min: %g, max: %g, units: %s", name, minp, maxp, units);
      } else {
        post("param: %s, min: %g, max: %g", name, minp, maxp);
      }
    } else {
      post("param: %s", name);
    }
  }
}

static void WRAPPER_SR(WRAPPER_TYPE *x, t_float sr) {
  post("%s~ new sample rate: %g", STR(PD_EXT_NAME), sr);
  if (x->x_sr != sr) {
    if (x->m_state) { wrapper_destroy(x->m_state); }
    x->x_sr = sr;
    x->m_state = wrapper_create(x->x_sr, x->x_bs);
  }
}

static void WRAPPER_BS(WRAPPER_TYPE *x, t_float bs) {
  post("%s~ new block size: %g", STR(PD_EXT_NAME), bs);
  if (x->x_bs != bs) {
    if (x->m_state) { wrapper_destroy(x->m_state); }
    x->x_bs = bs;
    x->m_state = wrapper_create(x->x_sr, x->x_bs);
  }
}

static void WRAPPER_RESET(WRAPPER_TYPE *x)
{
  if (x->m_state) {
    wrapper_reset(x->m_state);
  }
}

extern "C" void WRAPPER_SETUP(void) {
  WRAPPER_CLASS = class_new(gensym(STR(PD_EXT_NAME) "~"),
       (t_newmethod)WRAPPER_NEW,
       (t_method)WRAPPER_FREE, sizeof(WRAPPER_TYPE),
       CLASS_DEFAULT, A_NULL);

  class_addbang(WRAPPER_CLASS, WRAPPER_BANG);
  class_addmethod(WRAPPER_CLASS, (t_method)WRAPPER_SR, gensym(STR(MESSAGE_SR)), A_FLOAT, 0);
  class_addmethod(WRAPPER_CLASS, (t_method)WRAPPER_BS, gensym(STR(MESSAGE_BS)), A_FLOAT, 0);
  class_addmethod(WRAPPER_CLASS, (t_method)WRAPPER_RESET, gensym(STR(MESSAGE_RESET)), A_NULL, 0);

  class_addmethod(WRAPPER_CLASS,
          (t_method)WRAPPER_DSP, gensym("dsp"), A_CANT, 0);

  class_addanything(WRAPPER_CLASS, (t_method)WRAPPER_ANY_METHOD);

  if (wrapper_num_inputs() > 0) {
    CLASS_MAINSIGNALIN(WRAPPER_CLASS, WRAPPER_TYPE, f);
  }
}
} // namespace WRAPPER_NAMESPACE
