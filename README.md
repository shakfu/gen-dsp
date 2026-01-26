# gen_ext

## A template for generating PureData externals from exported gen~ code.

gen_ext is a wrapper that lets you compile code exported from a Max gen~ object into an "external" object that can be loaded into a PureData patch.

This project is intended to generate externals for use on the [Organelle](https://www.critterandguitari.com/organelle) synth, however it is not customized specifically for this platform. Simply, thus far I have limited my testing to the Organelle. But! That said, I have not had any trouble at all getting my `gen` externals for `pd` to compile natively on macOS 12 (both on Intel and Apple Silicon). See the note below for details.

At this stage, gen_ext is still an experimental project. My knowledge of gen~ is fairly naive and limited, so there may be some things that don't work. 

### Things that don't work

* Buffers are supported but only for 1 channel (each). Multi-channel buffers are not supported. Workaround: Use one buffer/array per channel.

This has been tested with gen~ code exported from Max 8.3.2.

### How to use gen_ext

1. In Max 8, send an `exportcode` message to your `gen~` object, to generate your c++ dsp code-base.
	- If your gen~ patcher uses `buffer` objects, a message will be printed in the Max console warning that buffers are not supported by `exportcode`. Your code will still be exported and you can ignore this warning. See the section below for details on how to enable buffer objects in your exported code.
2. Create a new project folder and then copy the contents of this repository's `template` into it.
3. Copy the exported `gen~` dsp code, (including the `gen_dsp` folder) into the `gen` folder in the template. Make a note of the .cpp file that `gen~` exported.
4. Open `Makefile` in your project folder and edit the two variables at the top.
	- Make sure gen.name matches the name of the exported `.cpp` file. E.g. if the file was exported as `gen_exported.cpp`, then set `gen.name = gen_exported`.
	- Set lib.name to the name you would like for your new pd external object. E.g. if you set the name as `lib.name = myObject` then you can create your object in pd as `myObject~`.
5. If your gen~ object references buffers, see the section below to edit `gen_buffer.h`.
6. Copy your project folder to a folder on your Organelle.
7. On your Organelle, go to the project folder in your terminal and run `make all`.
8. Copy the generated `.pd_linux` to a patch folder or install it in the shared pd library.
9. Now you can use the new object in your pd patch.

#### Tip
If you send a `bang` to the new object, it will print out information about the gen~ parameters it accepts. To set a parameter on the object, send a `<symbol> <float>` to the first inlet, with `<symbol>` matching the parameter name.
	
#### Using buffers referenced in your gen~ object

If your gen~ object references a buffers, you need to define them so that they can be connected to arrays in Pd.

_Note: The names of your buffers must not contain spaces or non-alphanumeric characters, and must start with a letter. i.e. they must be valid C/C++ variable names._

1. Open the `gen_buffer.h` file.
2. Set the `WRAPPER_BUFFER_COUNT` macro to the number of buffers you wish to use. You can use up to 5.
3. Uncomment the `WRAPPER_BUFFER_NAME_x` macro definitions and set the name for each to the unique name referenced by gen~. 
	- The order doesn't matter but do not set greater or fewer buffer names then the number defined for `WRAPPER_BUFFER_COUNT`.
4. You can compile your external now and it will look for arrays in PureData with the given names.

_Tip: Send a `pdset originalname newname` message to the your object to switch in a Pd array with a different name for a buffer._

#### Setting a custom sample rate and block size

The compiled external will accept a `pdsr` or a `pdbs` message that lets you reset the wrapped gen~ object with a new sample rate (or block size, respectively). This is useful if you are using the object in a sub-patch with a block~ object. A typical use would be to oversample the dsp in the sub-patch, or to use it to process output from an rfft~ object in Pd (see the spectraldelayfb example).

If no `pdsr` or `pdbs` messages are sent to the wrapped gen~ object, it will default to assuming the global sample rate and block size for the system, even in a subpatch.

_Note: If you don't want the `pdsr`, `pdbs` or `pdset` messages to override other previoiusly-defined parameters (coincidentally of the same name) in your gen~ object, you can change the names in `gen_ext_common.h`._

#### Simulating the Max pfft~ environment in Pd

See the `main.pd` file in the spectral delay example for an idea of how it can work. 
	
#### Compiling on macOS

It's convenient to be able to build and test your externals on a Mac before copying over to the Organelle, so here is one way you can do that.

I already have a lot of dev tools installed on my Mac here, so I can't confirm that the method below is totally sufficient (or even necessary) for compiling on a Mac. The following steps are based on my best guess of what would be required to get a 'totally new' Mac ready to compile your externals:

1. Install `Xcode` from the Mac App Store. It is a free download (but it is several GB in size). The purpose is to make sure the necessary command-line compilation tools are installed on your Mac.
2. Run the `Xcode` app at least once so that it can complete the installation of its developer environment during its "first run" process. You can close it when it is done. The rest is done in Terminal.
3. Proceed as above to export your `gen~` code and copy it into the `gen_ext` wrapper.
4. To compile your code, open your terminal to the project folder and run `make all`. 
5. If you are like me, you will get a compilation error in the file `gen/gen_dsp/genlib_ops.h`. It complains that it can't find the function `exp2f` in the following line: 
	`static const t_sample EXP2_NEG23 = exp2f(-23.f);`
	The solution that works for me is to simply edit this line and change the function name to `exp2`.
	
Note that this compilation process generates intermediate files that are incompatible with the Organelle. So if you copy your project to the Organelle, remember to run `make clean` to delete those files before running `make all`.

#### Attribution

The _gigaverb_ example included in this repository includes code exported from the _gen~.gigaverb_ example code included in Max 8.3.2. Cycling '74 attributes this implementation as being ported from an implementation by Juhana Sadeharju (kouhia@nic.funet.fi).

The _spectraldelayfb_ example included in this repository includes code exported from the _gen~.spectraldelay_feedback_ example code included in Max 8.5.0.



