#include "gen_exported.h"

namespace gen_exported {

/*******************************************************************************************************************
Cycling '74 License for Max-Generated Code for Export
Copyright (c) 2016 Cycling '74
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
	Delay m_delay_11;
	Delay m_delay_10;
	Delay m_delay_12;
	Delay m_delay_6;
	Delay m_delay_7;
	Delay m_delay_8;
	Delay m_delay_13;
	Delay m_delay_15;
	Delay m_delay_14;
	Delay m_delay_17;
	Delay m_delay_16;
	Delay m_delay_9;
	int __exception;
	int vectorsize;
	t_sample m_revtime_20;
	t_sample m_damping_19;
	t_sample m_dry_24;
	t_sample m_bandwidth_21;
	t_sample m_tail_23;
	t_sample m_spread_22;
	t_sample m_history_5;
	t_sample m_roomsize_18;
	t_sample m_history_1;
	t_sample m_history_4;
	t_sample samplerate;
	t_sample m_history_3;
	t_sample m_history_2;
	t_sample m_early_25;
	// re-initialize all member variables;
	inline void reset(t_param __sr, int __vs) {
		__exception = 0;
		vectorsize = __vs;
		samplerate = __sr;
		m_history_1 = ((int)0);
		m_history_2 = ((int)0);
		m_history_3 = ((int)0);
		m_history_4 = ((int)0);
		m_history_5 = ((int)0);
		m_delay_6.reset("m_delay_6", ((int)5000));
		m_delay_7.reset("m_delay_7", ((int)7000));
		m_delay_8.reset("m_delay_8", ((int)15000));
		m_delay_9.reset("m_delay_9", ((int)16000));
		m_delay_10.reset("m_delay_10", ((int)6000));
		m_delay_11.reset("m_delay_11", ((int)10000));
		m_delay_12.reset("m_delay_12", ((int)12000));
		m_delay_13.reset("m_delay_13", ((int)48000));
		m_delay_14.reset("m_delay_14", ((int)48000));
		m_delay_15.reset("m_delay_15", ((int)48000));
		m_delay_16.reset("m_delay_16", ((int)48000));
		m_delay_17.reset("m_delay_17", ((int)48000));
		m_roomsize_18 = ((int)75);
		m_damping_19 = ((t_sample)0.7);
		m_revtime_20 = ((int)11);
		m_bandwidth_21 = ((t_sample)0.5);
		m_spread_22 = ((int)23);
		m_tail_23 = ((t_sample)0.25);
		m_dry_24 = ((int)1);
		m_early_25 = ((t_sample)0.25);
		genlib_reset_complete(this);
		
	};
	// the signal processing routine;
	inline int perform(t_sample ** __ins, t_sample ** __outs, int __n) {
		vectorsize = __n;
		const t_sample * __in1 = __ins[0];
		const t_sample * __in2 = __ins[1];
		t_sample * __out1 = __outs[0];
		t_sample * __out2 = __outs[1];
		if (__exception) {
			return __exception;
			
		} else if (( (__in1 == 0) || (__in2 == 0) || (__out1 == 0) || (__out2 == 0) )) {
			__exception = GENLIB_ERR_NULL_BUFFER;
			return __exception;
			
		};
		t_sample expr_235 = ((m_roomsize_18 * samplerate) * ((t_sample)0.0029411764705882));
		t_sample expr_234 = safepow(((t_sample)0.001), safediv(((int)1), (m_revtime_20 * samplerate)));
		t_sample add_139 = (expr_235 + ((int)5));
		t_sample expr_229 = safepow(expr_234, add_139);
		t_sample mul_213 = (expr_235 * ((t_sample)0.63245));
		t_sample expr_226 = (-safepow(expr_234, mul_213));
		t_sample mul_214 = (expr_235 * ((t_sample)0.7071));
		t_sample expr_227 = (-safepow(expr_234, mul_214));
		t_sample mul_216 = (expr_235 * ((int)1));
		t_sample expr_233 = (-safepow(expr_234, mul_216));
		t_sample mul_215 = (expr_235 * ((t_sample)0.81649));
		t_sample expr_228 = (-safepow(expr_234, mul_215));
		t_sample mul_143 = (expr_235 * ((t_sample)0.155));
		t_sample add_140 = (mul_143 + ((int)5));
		t_sample expr_230 = safepow(expr_234, add_140);
		t_sample mul_145 = (expr_235 * ((t_sample)0.41));
		t_sample add_142 = (mul_145 + ((int)5));
		t_sample expr_232 = safepow(expr_234, add_142);
		t_sample rsub_224 = (((int)1) - m_bandwidth_21);
		t_sample mul_144 = (expr_235 * ((t_sample)0.3));
		t_sample add_141 = (mul_144 + ((int)5));
		t_sample expr_231 = safepow(expr_234, add_141);
		t_sample mul_210 = (expr_235 * ((t_sample)0.000527));
		int int_209 = int(mul_210);
		t_sample mul_150 = (m_spread_22 * (-0.380445));
		t_sample add_149 = (mul_150 + ((int)931));
		t_sample rsub_146 = (((int)1341) - add_149);
		t_sample mul_159 = (int_209 * rsub_146);
		t_sample mul_178 = (m_spread_22 * ((t_sample)0.376623));
		t_sample add_177 = (mul_178 + ((int)931));
		t_sample rsub_174 = (((int)1341) - add_177);
		t_sample mul_185 = (int_209 * rsub_174);
		t_sample mul_208 = (expr_235 * ((t_sample)0.110732));
		t_sample mul_152 = (m_spread_22 * (-0.568366));
		t_sample add_148 = (mul_152 + ((int)369));
		t_sample rsub_147 = (add_149 - add_148);
		t_sample mul_166 = (int_209 * rsub_147);
		t_sample mul_194 = (m_spread_22 * ((t_sample)0.125541));
		t_sample add_176 = (mul_194 + ((int)369));
		t_sample rsub_175 = (add_177 - add_176);
		t_sample mul_192 = (int_209 * rsub_175);
		t_sample add_151 = (mul_152 + ((int)159));
		t_sample mul_173 = (int_209 * add_151);
		t_sample add_193 = (mul_194 + ((int)159));
		t_sample mul_201 = (int_209 * add_193);
		// the main sample loop;
		while ((__n--)) {
			const t_sample in1 = (*(__in1++));
			const t_sample in2 = (*(__in2++));
			t_sample mul_71 = (in2 * m_dry_24);
			t_sample mul_83 = (in1 * m_dry_24);
			t_sample mul_73 = ((in1 + in2) * ((t_sample)0.707));
			t_sample mix_257 = (mul_73 + (rsub_224 * (m_history_5 - mul_73)));
			t_sample mix_223 = mix_257;
			t_sample tap_119 = m_delay_17.read_linear(mul_214);
			t_sample mul_115 = (tap_119 * expr_227);
			t_sample mix_258 = (mul_115 + (m_damping_19 * (m_history_4 - mul_115)));
			t_sample mix_117 = mix_258;
			t_sample tap_221 = m_delay_16.read_linear(mul_216);
			t_sample mul_212 = (tap_221 * expr_233);
			t_sample mix_259 = (mul_212 + (m_damping_19 * (m_history_3 - mul_212)));
			t_sample mix_219 = mix_259;
			t_sample tap_125 = m_delay_15.read_linear(mul_215);
			t_sample mul_121 = (tap_125 * expr_228);
			t_sample mix_260 = (mul_121 + (m_damping_19 * (m_history_2 - mul_121)));
			t_sample mix_123 = mix_260;
			t_sample tap_113 = m_delay_14.read_linear(mul_213);
			t_sample mul_109 = (tap_113 * expr_226);
			t_sample mix_261 = (mul_109 + (m_damping_19 * (m_history_1 - mul_109)));
			t_sample mix_111 = mix_261;
			t_sample tap_127 = m_delay_13.read_linear(add_142);
			t_sample tap_128 = m_delay_13.read_linear(add_141);
			t_sample tap_129 = m_delay_13.read_linear(add_140);
			t_sample tap_130 = m_delay_13.read_linear(add_139);
			t_sample mul_133 = (tap_129 * expr_230);
			t_sample mul_137 = (tap_127 * expr_232);
			t_sample mul_135 = (tap_128 * expr_231);
			t_sample mul_131 = (tap_130 * expr_229);
			t_sample tap_158 = m_delay_12.read_linear(mul_159);
			t_sample mul_156 = (tap_158 * ((t_sample)0.625));
			t_sample tap_184 = m_delay_11.read_linear(mul_185);
			t_sample mul_182 = (tap_184 * ((t_sample)0.625));
			t_sample add_103 = (mix_219 + mix_123);
			t_sample add_101 = (mix_117 + mix_111);
			t_sample sub_100 = (add_103 - add_101);
			t_sample mul_82 = (sub_100 * ((t_sample)0.5));
			t_sample add_107 = (mul_82 + mul_137);
			t_sample add_96 = (add_103 + add_101);
			t_sample mul_79 = (add_96 * ((t_sample)0.5));
			t_sample add_104 = (mul_79 + mul_131);
			t_sample sub_102 = (mix_219 - mix_123);
			t_sample sub_99 = (mix_117 - mix_111);
			t_sample sub_98 = (sub_102 - sub_99);
			t_sample mul_81 = (sub_98 * ((t_sample)0.5));
			t_sample add_106 = (mul_81 + mul_135);
			t_sample add_97 = (sub_102 + sub_99);
			t_sample rsub_95 = (((int)0) - add_97);
			t_sample mul_80 = (rsub_95 * ((t_sample)0.5));
			t_sample add_105 = (mul_80 + mul_133);
			t_sample tap_207 = m_delay_10.read_linear(mul_208);
			t_sample tap_165 = m_delay_9.read_linear(mul_166);
			t_sample mul_163 = (tap_165 * ((t_sample)0.625));
			t_sample tap_191 = m_delay_8.read_linear(mul_192);
			t_sample mul_189 = (tap_191 * ((t_sample)0.625));
			t_sample mul_205 = (tap_207 * ((t_sample)0.75));
			t_sample sub_204 = (mix_223 - mul_205);
			t_sample mul_203 = (sub_204 * ((t_sample)0.75));
			t_sample add_202 = (mul_203 + tap_207);
			t_sample tap_172 = m_delay_7.read_linear(mul_173);
			t_sample mul_170 = (tap_172 * ((t_sample)0.75));
			t_sample tap_200 = m_delay_6.read_linear(mul_201);
			t_sample mul_198 = (tap_200 * ((t_sample)0.75));
			t_sample mul_94 = (mul_82 * m_tail_23);
			t_sample mul_92 = (mul_80 * m_tail_23);
			t_sample add_78 = (mul_94 + mul_92);
			t_sample mul_93 = (mul_81 * m_tail_23);
			t_sample mul_91 = (mul_79 * m_tail_23);
			t_sample add_77 = (mul_93 + mul_91);
			t_sample sub_86 = (add_78 - add_77);
			t_sample mul_90 = (mul_137 * m_early_25);
			t_sample mul_88 = (mul_133 * m_early_25);
			t_sample add_76 = (mul_90 + mul_88);
			t_sample mul_89 = (mul_135 * m_early_25);
			t_sample mul_87 = (mul_131 * m_early_25);
			t_sample add_75 = (mul_89 + mul_87);
			t_sample sub_85 = (add_76 - add_75);
			t_sample add_72 = (sub_86 + sub_85);
			t_sample add_74 = (add_72 + in2);
			t_sample sub_169 = (add_74 - mul_170);
			t_sample mul_168 = (sub_169 * ((t_sample)0.75));
			t_sample add_167 = (mul_168 + tap_172);
			t_sample sub_162 = (add_167 - mul_163);
			t_sample mul_161 = (sub_162 * ((t_sample)0.625));
			t_sample add_160 = (mul_161 + tap_165);
			t_sample sub_155 = (add_160 - mul_156);
			t_sample mul_154 = (sub_155 * ((t_sample)0.625));
			t_sample add_153 = (mul_154 + tap_158);
			t_sample out2 = (mul_71 + add_153);
			t_sample add_84 = (add_72 + in1);
			t_sample sub_197 = (add_84 - mul_198);
			t_sample mul_196 = (sub_197 * ((t_sample)0.75));
			t_sample add_195 = (mul_196 + tap_200);
			t_sample sub_188 = (add_195 - mul_189);
			t_sample mul_187 = (sub_188 * ((t_sample)0.625));
			t_sample add_186 = (mul_187 + tap_191);
			t_sample sub_181 = (add_186 - mul_182);
			t_sample mul_180 = (sub_181 * ((t_sample)0.625));
			t_sample add_179 = (mul_180 + tap_184);
			t_sample out1 = (mul_83 + add_179);
			t_sample history_222_next_236 = fixdenorm(mix_223);
			t_sample history_116_next_237 = fixdenorm(mix_117);
			t_sample history_218_next_238 = fixdenorm(mix_219);
			t_sample history_122_next_239 = fixdenorm(mix_123);
			t_sample history_110_next_240 = fixdenorm(mix_111);
			m_delay_17.write(add_105);
			m_delay_16.write(add_107);
			m_delay_15.write(add_106);
			m_delay_14.write(add_104);
			m_delay_13.write(add_202);
			m_delay_12.write(sub_155);
			m_delay_11.write(sub_181);
			m_delay_10.write(sub_204);
			m_delay_9.write(sub_162);
			m_delay_8.write(sub_188);
			m_delay_7.write(sub_169);
			m_delay_6.write(sub_197);
			m_history_5 = history_222_next_236;
			m_history_4 = history_116_next_237;
			m_history_3 = history_218_next_238;
			m_history_2 = history_122_next_239;
			m_history_1 = history_110_next_240;
			m_delay_6.step();
			m_delay_7.step();
			m_delay_8.step();
			m_delay_9.step();
			m_delay_10.step();
			m_delay_11.step();
			m_delay_12.step();
			m_delay_13.step();
			m_delay_14.step();
			m_delay_15.step();
			m_delay_16.step();
			m_delay_17.step();
			// assign results to output buffer;
			(*(__out1++)) = out1;
			(*(__out2++)) = out2;
			
		};
		return __exception;
		
	};
	inline void set_roomsize(t_param _value) {
		m_roomsize_18 = (_value < 0.1 ? 0.1 : (_value > 300 ? 300 : _value));
	};
	inline void set_damping(t_param _value) {
		m_damping_19 = (_value < 0 ? 0 : (_value > 1 ? 1 : _value));
	};
	inline void set_revtime(t_param _value) {
		m_revtime_20 = (_value < 0.1 ? 0.1 : (_value > 1 ? 1 : _value));
	};
	inline void set_bandwidth(t_param _value) {
		m_bandwidth_21 = (_value < 0 ? 0 : (_value > 1 ? 1 : _value));
	};
	inline void set_spread(t_param _value) {
		m_spread_22 = (_value < 0 ? 0 : (_value > 100 ? 100 : _value));
	};
	inline void set_tail(t_param _value) {
		m_tail_23 = (_value < 0 ? 0 : (_value > 1 ? 1 : _value));
	};
	inline void set_dry(t_param _value) {
		m_dry_24 = (_value < 0 ? 0 : (_value > 1 ? 1 : _value));
	};
	inline void set_early(t_param _value) {
		m_early_25 = (_value < 0 ? 0 : (_value > 1 ? 1 : _value));
	};
	
} State;


///
///	Configuration for the genlib API
///

/// Number of signal inputs and outputs

int gen_kernel_numins = 2;
int gen_kernel_numouts = 2;

int num_inputs() { return gen_kernel_numins; }
int num_outputs() { return gen_kernel_numouts; }
int num_params() { return 8; }

/// Assistive lables for the signal inputs and outputs

const char *gen_kernel_innames[] = { "in1", "in2" };
const char *gen_kernel_outnames[] = { "out1", "out2" };

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
		case 0: self->set_bandwidth(value); break;
		case 1: self->set_damping(value); break;
		case 2: self->set_dry(value); break;
		case 3: self->set_early(value); break;
		case 4: self->set_revtime(value); break;
		case 5: self->set_roomsize(value); break;
		case 6: self->set_spread(value); break;
		case 7: self->set_tail(value); break;
		
		default: break;
	}
}

/// Get the value of a parameter of a State object

void getparameter(CommonState *cself, long index, t_param *value) {
	State *self = (State *)cself;
	switch (index) {
		case 0: *value = self->m_bandwidth_21; break;
		case 1: *value = self->m_damping_19; break;
		case 2: *value = self->m_dry_24; break;
		case 3: *value = self->m_early_25; break;
		case 4: *value = self->m_revtime_20; break;
		case 5: *value = self->m_roomsize_18; break;
		case 6: *value = self->m_spread_22; break;
		case 7: *value = self->m_tail_23; break;
		
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
	self->__commonstate.params = (ParamInfo *)genlib_sysmem_newptr(8 * sizeof(ParamInfo));
	self->__commonstate.numparams = 8;
	// initialize parameter 0 ("m_bandwidth_21")
	pi = self->__commonstate.params + 0;
	pi->name = "bandwidth";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_bandwidth_21;
	pi->defaultref = 0;
	pi->hasinputminmax = false;
	pi->inputmin = 0;
	pi->inputmax = 1;
	pi->hasminmax = true;
	pi->outputmin = 0;
	pi->outputmax = 1;
	pi->exp = 0;
	pi->units = "";		// no units defined
	// initialize parameter 1 ("m_damping_19")
	pi = self->__commonstate.params + 1;
	pi->name = "damping";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_damping_19;
	pi->defaultref = 0;
	pi->hasinputminmax = false;
	pi->inputmin = 0;
	pi->inputmax = 1;
	pi->hasminmax = true;
	pi->outputmin = 0;
	pi->outputmax = 1;
	pi->exp = 0;
	pi->units = "";		// no units defined
	// initialize parameter 2 ("m_dry_24")
	pi = self->__commonstate.params + 2;
	pi->name = "dry";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_dry_24;
	pi->defaultref = 0;
	pi->hasinputminmax = false;
	pi->inputmin = 0;
	pi->inputmax = 1;
	pi->hasminmax = true;
	pi->outputmin = 0;
	pi->outputmax = 1;
	pi->exp = 0;
	pi->units = "";		// no units defined
	// initialize parameter 3 ("m_early_25")
	pi = self->__commonstate.params + 3;
	pi->name = "early";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_early_25;
	pi->defaultref = 0;
	pi->hasinputminmax = false;
	pi->inputmin = 0;
	pi->inputmax = 1;
	pi->hasminmax = true;
	pi->outputmin = 0;
	pi->outputmax = 1;
	pi->exp = 0;
	pi->units = "";		// no units defined
	// initialize parameter 4 ("m_revtime_20")
	pi = self->__commonstate.params + 4;
	pi->name = "revtime";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_revtime_20;
	pi->defaultref = 0;
	pi->hasinputminmax = false;
	pi->inputmin = 0;
	pi->inputmax = 1;
	pi->hasminmax = true;
	pi->outputmin = 0.1;
	pi->outputmax = 1;
	pi->exp = 0;
	pi->units = "";		// no units defined
	// initialize parameter 5 ("m_roomsize_18")
	pi = self->__commonstate.params + 5;
	pi->name = "roomsize";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_roomsize_18;
	pi->defaultref = 0;
	pi->hasinputminmax = false;
	pi->inputmin = 0;
	pi->inputmax = 1;
	pi->hasminmax = true;
	pi->outputmin = 0.1;
	pi->outputmax = 300;
	pi->exp = 0;
	pi->units = "";		// no units defined
	// initialize parameter 6 ("m_spread_22")
	pi = self->__commonstate.params + 6;
	pi->name = "spread";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_spread_22;
	pi->defaultref = 0;
	pi->hasinputminmax = false;
	pi->inputmin = 0;
	pi->inputmax = 1;
	pi->hasminmax = true;
	pi->outputmin = 0;
	pi->outputmax = 100;
	pi->exp = 0;
	pi->units = "";		// no units defined
	// initialize parameter 7 ("m_tail_23")
	pi = self->__commonstate.params + 7;
	pi->name = "tail";
	pi->paramtype = GENLIB_PARAMTYPE_FLOAT;
	pi->defaultvalue = self->m_tail_23;
	pi->defaultref = 0;
	pi->hasinputminmax = false;
	pi->inputmin = 0;
	pi->inputmax = 1;
	pi->hasminmax = true;
	pi->outputmin = 0;
	pi->outputmax = 1;
	pi->exp = 0;
	pi->units = "";		// no units defined
	
	return self;
}

/// Release all resources and memory used by a State object:

void destroy(CommonState *cself) {
	State *self = (State *)cself;
	genlib_sysmem_freeptr(cself->params);
		
	delete self;
}


} // gen_exported::
