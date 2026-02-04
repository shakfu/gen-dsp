// Basic support for referencing Pd Arrays from gen~.

#include "gen_ext_common.h"

#include "genlib.h"
#include "genlib_exportfunctions.h"
#include "genlib_ops.h"

#include <m_pd.h>

#ifndef PD_BUFFER_ZEROS
// make a small empty buffer to use as a default. This may need
// to be enlarged if the gen~ algorithm assumes a larger buffer
// and one is not assigned in Pd.
	static float pd_buffer_zeros[] = {0,0,0,0,0,0,0,0};
	
#define PD_BUFFER_ZEROS
#endif


typedef struct PdBuffer : public DataInterface<t_sample> {
	
	PdBuffer() : DataInterface<t_sample>() {}
	
	// overriding accessor methods for mData to handle platforms where
	// sizeof(t_word) != sizeof(t_sample)
	
	// raw reading/writing/overdubbing (internal use only, no bounds checking)
	inline t_sample read(long index, long channel=0) const {
		return ((t_word*)mData)[channel+index*channels].w_float;
	}
	
	inline void write(t_sample value, long index, long channel=0) {
		((t_word*)mData)[channel+index*channels].w_float = value;
		modified = 1;
	}
	// NO LONGER USED:
	inline void overdub(t_sample value, long index, long channel=0) {
		((t_word*)mData)[channel+index*channels].w_float += value;
		modified = 1;
	}

	// averaging overdub (used by splat)
	inline void blend(t_sample value, long index, long channel, t_sample alpha) {
		long offset = channel+index*channels;
		const t_sample old = ((t_word*)mData)[offset].w_float;
		mData[offset] = old + alpha * (value - old);
		modified = 1;
	}

	// call this method in the Pd "dsp" method so that it 
	// updates the vector reference if arrays are deleted
	int setarray(t_symbol *s) {

		t_garray *a;

		int size;

		t_word *vec;

		 if (!(a = (t_garray *)pd_findbyclass(s, garray_class)))
		 {
	 		channels = 1;
	 		dim = 8;
	 		mData = &pd_buffer_zeros[0];
			 return 1;
		 }
		 if (!garray_getfloatwords(a, &size, &vec))
		 {
	 		channels = 1;
	 		dim = 8;
	 		mData = &pd_buffer_zeros[0];
		 			return 2;
		 }
		 channels = 1;
		 dim = size;
		 mData = (t_float*)vec;
 		garray_usedindsp(a);
 		return 0;

		
	}
	
} PdBuffer;