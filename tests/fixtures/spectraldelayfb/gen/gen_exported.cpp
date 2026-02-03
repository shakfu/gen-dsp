#include "gen_exported.h"

namespace gen_exported {

/*******************************************************************************************************************
Cycling '74 License for Max-Generated Code for Export
Copyright (c) 2022 Cycling '74
The code that Max generates automatically and that end users are capable of exporting and using, and any
  associated documentation files (the “Software”) is a work of authorship for which Cycling '74 is the author
  and owner for copyright purposes.  A license is hereby granted, free of charge, to any person obtaining a
  copy of the Software (“Licensee”) to use, copy, modify, merge, publish, and distribute copies of the Software,
  and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
The Software is licensed to Licensee only for non-commercial use. Users who wish to make commercial use of the
  Software must contact the copyright owner to determine if a license for commercial use is available, and the
  terms and conditions for same, which may include fees or royalties. For commercial use, please send inquiries
  to licensing (at) cycling74.com.  The determination of whether a use is commercial use or non-commercial use is based
  upon the use, not the user. The Software may be used by individuals, institutions, governments, corporations, or
  other business whether for-profit or non-profit so long as the use itself is not a commercialization of the
  materials or a use that generates or is intended to generate income, revenue, sales or profit.
The above copyright notice and this license shall be included in all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
  THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NON-INFRINGEMENT. IN NO EVENT SHALL
  THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
  CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
  DEALINGS IN THE SOFTWARE.
*******************************************************************************************************************/

// global noise generator
Noise noise;
static const int GENLIB_LOOPCOUNT_BAIL = 100000;


// The State struct contains all the state and procedures for the gendsp kernel
typedef struct State {
	CommonState __commonstate;
	Delay m_delay_6;
	Delay m_delay_3;
	Delay m_delay_4;
	Delay m_delay_5;
	Delay m_delay_2;
	Delay m_delay_1;
	int __exception;
	int vectorsize;
	t_sample samplerate;
	// re-initialize all member variables;
	inline void reset(t_param __sr, int __vs) {
		__exception = 0;
		vectorsize = __vs;
		samplerate = __sr;
		m_delay_1.reset("m_delay_1", vectorsize);
		m_delay_2.reset("m_delay_2", samplerate);
		m_delay_3.reset("m_delay_3", samplerate);
		m_delay_4.reset("m_delay_4", vectorsize);
		m_delay_5.reset("m_delay_5", vectorsize);
		m_delay_6.reset("m_delay_6", vectorsize);
		genlib_reset_complete(this);
		
	};
	// the signal processing routine;
	inline int perform(t_sample ** __ins, t_sample ** __outs, int __n) {
		vectorsize = __n;
		const t_sample * __in1 = __ins[0];
		const t_sample * __in2 = __ins[1];
		const t_sample * __in3 = __ins[2];
		t_sample * __out1 = __outs[0];
		t_sample * __out2 = __outs[1];
		if (__exception) {
			return __exception;
			
		} else if (( (__in1 == 0) || (__in2 == 0) || (__in3 == 0) || (__out1 == 0) || (__out2 == 0) )) {
			__exception = GENLIB_ERR_NULL_BUFFER;
			return __exception;
			
		};
		int feedback_dim = feedback.dim;
		int feedback_channels = feedback.channels;
		int min_9 = (-1);
		int delays_dim = delays.dim;
		int delays_channels = delays.channels;
		// the main sample loop;
		while ((__n--)) {
			const t_sample in1 = (*(__in1++));
			const t_sample in2 = (*(__in2++));
			const t_sample in3 = (*(__in3++));
			t_sample cartopol_318 = sqrt(((in1 * in1) + (in2 * in2)));
			t_sample cartopol_319 = atan2(in2, in1);
			t_sample tap_285 = m_delay_6.read_step(vectorsize);
			int index_trunc_7 = fixnan(floor(in3));
			bool index_ignore_8 = ((index_trunc_7 >= feedback_dim) || (index_trunc_7 < 0));
			// samples feedback channel 1;
			t_sample sample_feedback_289 = (index_ignore_8 ? 0 : feedback.read(index_trunc_7, 0));
			t_sample index_feedback_290 = in3;
			t_sample clamp_286 = ((sample_feedback_289 <= min_9) ? min_9 : ((sample_feedback_289 >= ((int)1)) ? ((int)1) : sample_feedback_289));
			t_sample mul_283 = (tap_285 * clamp_286);
			t_sample tap_282 = m_delay_5.read_step(vectorsize);
			t_sample mul_280 = (tap_282 * clamp_286);
			t_sample tap_273 = m_delay_4.read_step(vectorsize);
			t_sample sub_271 = ((cartopol_319 + mul_280) - tap_273);
			int index_trunc_10 = fixnan(floor(in3));
			bool index_ignore_11 = ((index_trunc_10 >= delays_dim) || (index_trunc_10 < 0));
			// samples delays channel 1;
			t_sample sample_delays_296 = (index_ignore_11 ? 0 : delays.read(index_trunc_10, 0));
			t_sample index_delays_297 = in3;
			t_sample clamp_292 = ((sample_delays_296 <= ((int)0)) ? ((int)0) : ((sample_delays_296 >= ((int)1)) ? ((int)1) : sample_delays_296));
			t_sample mul_293 = (clamp_292 * samplerate);
			t_sample div_299 = safediv(mul_293, vectorsize);
			t_sample floor_298 = floor(div_299);
			t_sample add_291 = (floor_298 + ((int)1));
			t_sample mul_300 = (add_291 * vectorsize);
			t_sample tap_304 = m_delay_3.read_step(mul_300);
			t_sample tap_302 = m_delay_2.read_step(mul_300);
			t_sample tap_277 = m_delay_1.read_step(vectorsize);
			t_sample add_275 = (tap_302 + tap_277);
			t_sample phasewrap_278 = phasewrap(add_275);
			t_sample poltocar_320 = (tap_304 * cos(phasewrap_278));
			t_sample poltocar_321 = (tap_304 * sin(phasewrap_278));
			t_sample out1 = poltocar_320;
			t_sample out2 = poltocar_321;
			m_delay_6.write(tap_304);
			m_delay_5.write(phasewrap_278);
			m_delay_4.write(sub_271);
			m_delay_3.write((cartopol_318 + mul_283));
			m_delay_2.write(sub_271);
			m_delay_1.write(phasewrap_278);
			m_delay_1.step();
			m_delay_2.step();
			m_delay_3.step();
			m_delay_4.step();
			m_delay_5.step();
			m_delay_6.step();
			// assign results to output buffer;
			(*(__out1++)) = out1;
			(*(__out2++)) = out2;
			
		};
		return __exception;
		
	};
	
} State;


///
///	Configuration for the genlib API
///

/// Number of signal inputs and outputs

int gen_kernel_numins = 3;
int gen_kernel_numouts = 2;

int num_inputs() { return gen_kernel_numins; }
int num_outputs() { return gen_kernel_numouts; }
int num_params() { return 0; }

/// Assistive lables for the signal inputs and outputs

const char *gen_kernel_innames[] = { "real", "imaginary", "frame" };
const char *gen_kernel_outnames[] = { "real", "imaginary" };

/// Invoke the signal process of a State object

int perform(CommonState *cself, t_sample **ins, long numins, t_sample **outs, long numouts, long n) {
	State* self = (State *)cself;
	return self->perform(ins, outs, n);
}

/// Reset all parameters and stateful operators of a State object

void reset(CommonState *cself) {
	State* self = (State *)cself;
	self->reset(cself->sr, cself->vs);
}

/// Set a parameter of a State object

void setparameter(CommonState *cself, long index, t_param value, void *ref) {
	State *self = (State *)cself;
	switch (index) {
		
		default: break;
	}
}

/// Get the value of a parameter of a State object

void getparameter(CommonState *cself, long index, t_param *value) {
	State *self = (State *)cself;
	switch (index) {
		
		default: break;
	}
}

/// Get the name of a parameter of a State object

const char *getparametername(CommonState *cself, long index) {
	if (index >= 0 && index < cself->numparams) {
		return cself->params[index].name;
	}
	return 0;
}

/// Get the minimum value of a parameter of a State object

t_param getparametermin(CommonState *cself, long index) {
	if (index >= 0 && index < cself->numparams) {
		return cself->params[index].outputmin;
	}
	return 0;
}

/// Get the maximum value of a parameter of a State object

t_param getparametermax(CommonState *cself, long index) {
	if (index >= 0 && index < cself->numparams) {
		return cself->params[index].outputmax;
	}
	return 0;
}

/// Get parameter of a State object has a minimum and maximum value

char getparameterhasminmax(CommonState *cself, long index) {
	if (index >= 0 && index < cself->numparams) {
		return cself->params[index].hasminmax;
	}
	return 0;
}

/// Get the units of a parameter of a State object

const char *getparameterunits(CommonState *cself, long index) {
	if (index >= 0 && index < cself->numparams) {
		return cself->params[index].units;
	}
	return 0;
}

/// Get the size of the state of all parameters of a State object

size_t getstatesize(CommonState *cself) {
	return genlib_getstatesize(cself, &getparameter);
}

/// Get the state of all parameters of a State object

short getstate(CommonState *cself, char *state) {
	return genlib_getstate(cself, state, &getparameter);
}

/// set the state of all parameters of a State object

short setstate(CommonState *cself, const char *state) {
	return genlib_setstate(cself, state, &setparameter);
}

/// Allocate and configure a new State object and it's internal CommonState:

void *create(t_param sr, long vs) {
	State *self = new State;
	self->reset(sr, vs);
	ParamInfo *pi;
	self->__commonstate.inputnames = gen_kernel_innames;
	self->__commonstate.outputnames = gen_kernel_outnames;
	self->__commonstate.numins = gen_kernel_numins;
	self->__commonstate.numouts = gen_kernel_numouts;
	self->__commonstate.sr = sr;
	self->__commonstate.vs = vs;
	self->__commonstate.params = 0;
	self->__commonstate.numparams = 0;
	
	return self;
}

/// Release all resources and memory used by a State object:

void destroy(CommonState *cself) {
	State *self = (State *)cself;
	
	delete self;
}


} // gen_exported::
