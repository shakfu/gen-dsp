/*
 * Minimal hand-authored gen~-style export for parser/manifest shape tests.
 *
 * NOT a real Max/gen~ export and not buildable (no genlib sources). It
 * exercises two distinct shapes the existing fixtures do not combine: more
 * than one buffer (detected via the local-variable .dim/.read() access idiom,
 * as in the RamplePlayer fixture) together with zero parameters.
 */

#include "multitap.h"

namespace multitap {

int gen_kernel_numins = 2;
int gen_kernel_numouts = 2;

int num_inputs() { return gen_kernel_numins; }
int num_outputs() { return gen_kernel_numouts; }
int num_params() { return 0; }

const char *gen_kernel_innames[] = { "in1", "in2" };
const char *gen_kernel_outnames[] = { "out1", "out2" };

void perform(CommonState *self, t_sample **ins, t_sample **outs, long n) {
	int tapA_dim = tapA.dim;
	int tapA_channels = tapA.channels;
	int tapB_dim = tapB.dim;
	int tapB_channels = tapB.channels;
	for (long i = 0; i < n; i++) {
		double a = tapA.read(i, 0);
		double b = tapB.read(i, 0);
		outs[0][i] = a;
		outs[1][i] = b;
	}
}

} // namespace multitap
