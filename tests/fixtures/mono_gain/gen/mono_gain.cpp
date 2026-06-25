/*
 * Minimal hand-authored gen~-style export for parser/manifest shape tests.
 *
 * This is NOT a real Max/gen~ export and is intentionally not buildable (it
 * carries no genlib sources). It reproduces only the structural idioms the
 * parser and manifest IR read -- gen_kernel_numins/numouts, num_params(),
 * gen_kernel_innames[], the pi-> parameter blocks, and the reset() member
 * initializers -- so tests can exercise a mono (1-in/1-out) shape.
 */

#include "mono_gain.h"

namespace mono_gain {

void reset(CommonState *__commonstate) {
	m_gain_1 = ((t_sample)1);
}

int gen_kernel_numins = 1;
int gen_kernel_numouts = 1;

int num_inputs() { return gen_kernel_numins; }
int num_outputs() { return gen_kernel_numouts; }
int num_params() { return 1; }

const char *gen_kernel_innames[] = { "in1" };
const char *gen_kernel_outnames[] = { "out1" };

void setupparams(CommonState *self) {
	ParamInfo *pi;
	self->__commonstate.numins = gen_kernel_numins;
	self->__commonstate.numouts = gen_kernel_numouts;

	// initialize parameter 0 ("m_gain_1")
	pi = self->__commonstate.params + 0;
	pi->name = "gain";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_gain_1;
	pi->defaultref = 0;
	pi->hasinputminmax = false;
	pi->inputmin = 0;
	pi->inputmax = 1;
	pi->hasminmax = true;
	pi->outputmin = 0;
	pi->outputmax = 2;
	pi->exp = 0;
	pi->units = "";
}

} // namespace mono_gain
