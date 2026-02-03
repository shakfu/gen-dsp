# Makefile for my_pd_external_name

# change this to match the name of the .cpp / .h file that were exported by gen~
gen.name = RamplePlayer

# change this to match the name of the external you would like to generate
# (do not add a ~ suffix to the name here)
lib.name = RamplePlayer

# Don't forget to edit gen_buffer.h if your gen~ object references buffers in max.

genext.version = 0.7.0

$(lib.name)~.class.sources = gen_ext.cpp _ext.cpp ./gen/gen_dsp/genlib.cpp 
cflags = -I ./gen -I./gen/gen_dsp -DGEN_EXT_VERSION=$(genext.version) -DPD_EXT_NAME=$(lib.name) -DGEN_EXPORTED_NAME=$(gen.name) -DGEN_EXPORTED_HEADER=\"$(gen.name).h\" -DGEN_EXPORTED_CPP=\"$(gen.name).cpp\"
suppress-wunused = yes

define forDarwin
  cflags += -DMSP_ON_CLANG -DGENLIB_USE_FLOAT32 -mmacosx-version-min=10.9
endef

define forLinux
  $(lib.name)~.class.sources += ./gen/gen_dsp/json.c ./gen/gen_dsp/json_builder.c
endef

# datafiles =
# datafiles and datadirs:
# All extra files you want to include in binary distributions of the
# library: abstractions and help patches, example patches, meta patch, readme
# and license texts, manuals, sound files, etcetera. Use 'datafiles' for all
# files that should go into your lib rootdir and 'datadirs' for complete
# directories you want to copy from source to distribution.

include ./pd-lib-builder/Makefile.pdlibbuilder