// gen_ext_chuck.cpp - ChucK chugin wrapper for gen~ exports
// This file includes ONLY ChucK headers - genlib is isolated in _ext_chuck.cpp

#include "chuck/include/chugin.h"

#include "gen_ext_common_chuck.h"
#include "_ext_chuck.h"

#include <cstring>
#include <cstdlib>
#include <cstdio>

using namespace WRAPPER_NAMESPACE;

// Internal data structure for the chugin instance
struct GenExtData {
    GenState* gen_state;
    float samplerate;
    int num_inputs;
    int num_outputs;
    // Pre-allocated per-channel I/O buffers for deinterleaving
    float** in_buffers;
    float** out_buffers;
};

// Data offset for storing our internal data pointer
static t_CKINT genext_data_offset = 0;


// Forward declarations
CK_DLL_CTOR(genext_ctor);
CK_DLL_DTOR(genext_dtor);
CK_DLL_TICKF(genext_tickf);
CK_DLL_MFUN(genext_param_set);
CK_DLL_MFUN(genext_param_get);
CK_DLL_MFUN(genext_num_params);
CK_DLL_MFUN(genext_param_name);
CK_DLL_MFUN(genext_load_buffer);
CK_DLL_MFUN(genext_info);
CK_DLL_MFUN(genext_reset);


//-----------------------------------------------------------------------------
// info function
//-----------------------------------------------------------------------------
CK_DLL_INFO(CHUCK_EXT_NAME)
{
    QUERY->setinfo(QUERY, CHUGIN_INFO_CHUGIN_VERSION, STR(GEN_EXT_VERSION));
    QUERY->setinfo(QUERY, CHUGIN_INFO_DESCRIPTION, "gen~ DSP export wrapped as ChucK chugin");
    QUERY->setinfo(QUERY, CHUGIN_INFO_URL, "");
    QUERY->setinfo(QUERY, CHUGIN_INFO_EMAIL, "");
}


//-----------------------------------------------------------------------------
// query function: called by ChucK when loading the chugin
//-----------------------------------------------------------------------------
CK_DLL_QUERY(CHUCK_EXT_NAME)
{
    QUERY->setname(QUERY, STR(CHUCK_EXT_NAME));

    // Begin class definition, extending UGen
    QUERY->begin_class(QUERY, STR(CHUCK_EXT_NAME), "UGen");

    // Register constructor and destructor
    QUERY->add_ctor(QUERY, genext_ctor);
    QUERY->add_dtor(QUERY, genext_dtor);

    // Register multi-channel tick function
    int num_in = wrapper_num_inputs();
    int num_out = wrapper_num_outputs();
    QUERY->add_ugen_funcf(QUERY, genext_tickf, NULL, num_in, num_out);

    // param(string, float) -> float : set parameter by name
    QUERY->add_mfun(QUERY, genext_param_set, "float", "param");
    QUERY->add_arg(QUERY, "string", "name");
    QUERY->add_arg(QUERY, "float", "value");

    // param(string) -> float : get parameter by name
    QUERY->add_mfun(QUERY, genext_param_get, "float", "param");
    QUERY->add_arg(QUERY, "string", "name");

    // numParams() -> int
    QUERY->add_mfun(QUERY, genext_num_params, "int", "numParams");

    // paramName(int) -> string
    QUERY->add_mfun(QUERY, genext_param_name, "string", "paramName");
    QUERY->add_arg(QUERY, "int", "index");

    // loadBuffer(string, string) -> int : load WAV file into named buffer
    QUERY->add_mfun(QUERY, genext_load_buffer, "int", "loadBuffer");
    QUERY->add_arg(QUERY, "string", "name");
    QUERY->add_arg(QUERY, "string", "path");

    // info() -> void : print info
    QUERY->add_mfun(QUERY, genext_info, "void", "info");

    // reset() -> void : reset gen~ state
    QUERY->add_mfun(QUERY, genext_reset, "void", "reset");

    // Reserve data offset for internal data
    genext_data_offset = QUERY->add_mvar(QUERY, "int", "@genext_data", false);

    // End class definition
    QUERY->end_class(QUERY);

    return TRUE;
}


//-----------------------------------------------------------------------------
// constructor
//-----------------------------------------------------------------------------
CK_DLL_CTOR(genext_ctor)
{
    OBJ_MEMBER_INT(SELF, genext_data_offset) = 0;

    GenExtData* data = new GenExtData();
    data->samplerate = (float)API->vm->srate(VM);
    data->num_inputs = wrapper_num_inputs();
    data->num_outputs = wrapper_num_outputs();

    // Create gen~ state (block size 1 since we process per-frame)
    data->gen_state = wrapper_create(data->samplerate, 1);

    // Allocate per-channel I/O buffers
    data->in_buffers = new float*[data->num_inputs > 0 ? data->num_inputs : 1];
    for (int i = 0; i < data->num_inputs; i++) {
        data->in_buffers[i] = new float[1];
        data->in_buffers[i][0] = 0.0f;
    }

    data->out_buffers = new float*[data->num_outputs > 0 ? data->num_outputs : 1];
    for (int i = 0; i < data->num_outputs; i++) {
        data->out_buffers[i] = new float[1];
        data->out_buffers[i][0] = 0.0f;
    }

    OBJ_MEMBER_INT(SELF, genext_data_offset) = (t_CKINT)data;
}


//-----------------------------------------------------------------------------
// destructor
//-----------------------------------------------------------------------------
CK_DLL_DTOR(genext_dtor)
{
    GenExtData* data = (GenExtData*)OBJ_MEMBER_INT(SELF, genext_data_offset);
    if (data) {
        if (data->gen_state) {
            wrapper_destroy(data->gen_state);
        }
        if (data->in_buffers) {
            for (int i = 0; i < data->num_inputs; i++) {
                delete[] data->in_buffers[i];
            }
            delete[] data->in_buffers;
        }
        if (data->out_buffers) {
            for (int i = 0; i < data->num_outputs; i++) {
                delete[] data->out_buffers[i];
            }
            delete[] data->out_buffers;
        }
        delete data;
    }
    OBJ_MEMBER_INT(SELF, genext_data_offset) = 0;
}


//-----------------------------------------------------------------------------
// multi-channel tick function
// ChucK provides interleaved I/O: [in0_ch0, in0_ch1, ..., in1_ch0, ...]
// gen~ expects per-channel buffers: ins[0][sample], ins[1][sample], ...
//-----------------------------------------------------------------------------
CK_DLL_TICKF(genext_tickf)
{
    GenExtData* data = (GenExtData*)OBJ_MEMBER_INT(SELF, genext_data_offset);
    if (!data || !data->gen_state) {
        // Zero output
        for (t_CKUINT f = 0; f < nframes; f++) {
            for (int ch = 0; ch < data->num_outputs; ch++) {
                out[f * data->num_outputs + ch] = 0.0f;
            }
        }
        return TRUE;
    }

    int num_in = data->num_inputs;
    int num_out = data->num_outputs;

    // Process frame by frame
    for (t_CKUINT f = 0; f < nframes; f++) {
        // Deinterleave input: ChucK interleaved -> gen~ per-channel
        for (int ch = 0; ch < num_in; ch++) {
            data->in_buffers[ch][0] = in[f * num_in + ch];
        }

        // Call gen~ perform with block size 1
        wrapper_perform(data->gen_state,
                        data->in_buffers, num_in,
                        data->out_buffers, num_out,
                        1);

        // Interleave output: gen~ per-channel -> ChucK interleaved
        for (int ch = 0; ch < num_out; ch++) {
            out[f * num_out + ch] = data->out_buffers[ch][0];
        }
    }

    return TRUE;
}


//-----------------------------------------------------------------------------
// param(string, float) -> float : set parameter by name
//-----------------------------------------------------------------------------
CK_DLL_MFUN(genext_param_set)
{
    GenExtData* data = (GenExtData*)OBJ_MEMBER_INT(SELF, genext_data_offset);
    Chuck_String* name = GET_NEXT_STRING(ARGS);
    t_CKFLOAT value = GET_NEXT_FLOAT(ARGS);

    RETURN->v_float = value;

    if (!data || !data->gen_state || !name) return;

    const char* param_name = API->object->str(name);
    int num_params = wrapper_num_params();

    for (int i = 0; i < num_params; i++) {
        const char* pname = wrapper_param_name(data->gen_state, i);
        if (pname && strcmp(pname, param_name) == 0) {
            wrapper_set_param(data->gen_state, i, (float)value);
            return;
        }
    }
}


//-----------------------------------------------------------------------------
// param(string) -> float : get parameter by name
//-----------------------------------------------------------------------------
CK_DLL_MFUN(genext_param_get)
{
    GenExtData* data = (GenExtData*)OBJ_MEMBER_INT(SELF, genext_data_offset);
    Chuck_String* name = GET_NEXT_STRING(ARGS);

    RETURN->v_float = 0;

    if (!data || !data->gen_state || !name) return;

    const char* param_name = API->object->str(name);
    int num_params = wrapper_num_params();

    for (int i = 0; i < num_params; i++) {
        const char* pname = wrapper_param_name(data->gen_state, i);
        if (pname && strcmp(pname, param_name) == 0) {
            RETURN->v_float = (t_CKFLOAT)wrapper_get_param(data->gen_state, i);
            return;
        }
    }
}


//-----------------------------------------------------------------------------
// numParams() -> int
//-----------------------------------------------------------------------------
CK_DLL_MFUN(genext_num_params)
{
    RETURN->v_int = wrapper_num_params();
}


//-----------------------------------------------------------------------------
// paramName(int) -> string
//-----------------------------------------------------------------------------
CK_DLL_MFUN(genext_param_name)
{
    GenExtData* data = (GenExtData*)OBJ_MEMBER_INT(SELF, genext_data_offset);
    t_CKINT index = GET_NEXT_INT(ARGS);

    RETURN->v_string = NULL;

    if (!data || !data->gen_state) return;

    const char* pname = wrapper_param_name(data->gen_state, (int)index);
    if (pname) {
        RETURN->v_string = (Chuck_String*)API->object->create_string(VM, pname, false);
    }
}


//-----------------------------------------------------------------------------
// loadBuffer(string, string) -> int : load WAV file into named buffer
//-----------------------------------------------------------------------------
CK_DLL_MFUN(genext_load_buffer)
{
    Chuck_String* name = GET_NEXT_STRING(ARGS);
    Chuck_String* path = GET_NEXT_STRING(ARGS);

    RETURN->v_int = -1;

    if (!name || !path) return;

    const char* buf_name = API->object->str(name);
    const char* file_path = API->object->str(path);

    // Find buffer index by name
    int num_bufs = wrapper_num_buffers();
    for (int i = 0; i < num_bufs; i++) {
        const char* bname = wrapper_buffer_name(i);
        if (bname && strcmp(bname, buf_name) == 0) {
            RETURN->v_int = wrapper_load_buffer(i, file_path);
            return;
        }
    }
}


//-----------------------------------------------------------------------------
// info() -> void : print gen~ export info
//-----------------------------------------------------------------------------
CK_DLL_MFUN(genext_info)
{
    GenExtData* data = (GenExtData*)OBJ_MEMBER_INT(SELF, genext_data_offset);
    if (!data || !data->gen_state) return;

    char buf[256];

    snprintf(buf, sizeof(buf), "[%s] gen-dsp wrapper v%s (ChucK chugin)",
             STR(CHUCK_EXT_NAME), STR(GEN_EXT_VERSION));
    API->vm->em_log(3, buf);

    snprintf(buf, sizeof(buf), "[%s] samplerate: %.0f",
             STR(CHUCK_EXT_NAME), data->samplerate);
    API->vm->em_log(3, buf);

    snprintf(buf, sizeof(buf), "[%s] signal inputs: %d, outputs: %d",
             STR(CHUCK_EXT_NAME), data->num_inputs, data->num_outputs);
    API->vm->em_log(3, buf);

    int num_params = wrapper_num_params();
    snprintf(buf, sizeof(buf), "[%s] parameters: %d", STR(CHUCK_EXT_NAME), num_params);
    API->vm->em_log(3, buf);

    for (int i = 0; i < num_params; i++) {
        const char* pname = wrapper_param_name(data->gen_state, i);
        char hasMinMax = wrapper_param_hasminmax(data->gen_state, i);
        if (hasMinMax) {
            float minp = wrapper_param_min(data->gen_state, i);
            float maxp = wrapper_param_max(data->gen_state, i);
            snprintf(buf, sizeof(buf), "[%s]   %s: min=%.4f, max=%.4f",
                     STR(CHUCK_EXT_NAME), pname, minp, maxp);
        } else {
            snprintf(buf, sizeof(buf), "[%s]   %s", STR(CHUCK_EXT_NAME), pname);
        }
        API->vm->em_log(3, buf);
    }

    int num_bufs = wrapper_num_buffers();
    if (num_bufs > 0) {
        snprintf(buf, sizeof(buf), "[%s] buffers: %d", STR(CHUCK_EXT_NAME), num_bufs);
        API->vm->em_log(3, buf);
        for (int i = 0; i < num_bufs; i++) {
            const char* bname = wrapper_buffer_name(i);
            if (bname) {
                snprintf(buf, sizeof(buf), "[%s]   %s", STR(CHUCK_EXT_NAME), bname);
                API->vm->em_log(3, buf);
            }
        }
    }
}


//-----------------------------------------------------------------------------
// reset() -> void : reset gen~ state
//-----------------------------------------------------------------------------
CK_DLL_MFUN(genext_reset)
{
    GenExtData* data = (GenExtData*)OBJ_MEMBER_INT(SELF, genext_data_offset);
    if (data && data->gen_state) {
        wrapper_reset(data->gen_state);
    }
}
