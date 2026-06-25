/*
 * Minimal hand-authored gen~-style export for parser/manifest shape tests.
 *
 * NOT a real Max/gen~ export and not buildable (no genlib sources). It
 * exercises a high channel count (8-in/8-out) that the existing stereo/mono
 * fixtures do not, alongside a couple of ranged parameters.
 */

#include "octoverb.h"

namespace octoverb {

void reset(CommonState *__commonstate) {
	m_mix_1 = ((t_sample)0.5);
	m_size_2 = ((t_sample)0.7);
}

int gen_kernel_numins = 8;
int gen_kernel_numouts = 8;

int num_inputs() { return gen_kernel_numins; }
int num_outputs() { return gen_kernel_numouts; }
int num_params() { return 2; }

const char *gen_kernel_innames[] = {
	"in1", "in2", "in3", "in4", "in5", "in6", "in7", "in8"
};
const char *gen_kernel_outnames[] = {
	"out1", "out2", "out3", "out4", "out5", "out6", "out7", "out8"
};

void setupparams(CommonState *self) {
	ParamInfo *pi;
	self->__commonstate.numins = gen_kernel_numins;
	self->__commonstate.numouts = gen_kernel_numouts;

	// initialize parameter 0 ("m_mix_1")
	pi = self->__commonstate.params + 0;
	pi->name = "mix";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_mix_1;
	pi->hasminmax = true;
	pi->outputmin = 0;
	pi->outputmax = 1;

	// initialize parameter 1 ("m_size_2")
	pi = self->__commonstate.params + 1;
	pi->name = "size";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_size_2;
	pi->hasminmax = true;
	pi->outputmin = 0;
	pi->outputmax = 1;
}

} // namespace octoverb
