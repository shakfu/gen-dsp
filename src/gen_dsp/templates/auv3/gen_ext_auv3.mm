// gen_ext_auv3.mm - Audio Unit v3 wrapper for gen~ exports
// This file includes ONLY system/AU headers -- genlib is isolated in _ext_auv3.cpp
//
// Implements AUv3 via AUAudioUnit subclass (Objective-C++).
// The plugin is packaged as an App Extension (.appex) inside a host app (.app).

#import <AudioToolbox/AudioToolbox.h>
#import <AVFoundation/AVFoundation.h>
#import <Foundation/Foundation.h>

#include "gen_ext_common_auv3.h"
#include "_ext_auv3.h"

using namespace WRAPPER_NAMESPACE;

#ifndef AUV3_NUM_INPUTS
#define AUV3_NUM_INPUTS 0
#endif
#ifndef AUV3_NUM_OUTPUTS
#define AUV3_NUM_OUTPUTS 1
#endif

// ---------------------------------------------------------------------------
// AUAudioUnit subclass
// ---------------------------------------------------------------------------

@interface GenDspAudioUnit : AUAudioUnit
@end

@implementation GenDspAudioUnit {
    AUAudioUnitBusArray *_inputBusArray;
    AUAudioUnitBusArray *_outputBusArray;
    GenState            *_genState;
    float               *_paramValues;
    int                  _numParams;
    float               *_inBuf;   // deinterleave scratch
    float               *_outBuf;
    long                 _blockSize;
}

- (instancetype)initWithComponentDescription:(AudioComponentDescription)desc
                                     options:(AudioComponentInstantiationOptions)options
                                       error:(NSError **)error {
    self = [super initWithComponentDescription:desc options:options error:error];
    if (!self) return nil;

    // Default format: 44100 Hz, float32, non-interleaved
    AVAudioFormat *fmt = [[AVAudioFormat alloc]
        initWithCommonFormat:AVAudioPCMFormatFloat32
                  sampleRate:44100.0
                    channels:(AUV3_NUM_OUTPUTS > 0 ? AUV3_NUM_OUTPUTS : 1)
                 interleaved:NO];

    NSError *busErr = nil;
    AUAudioUnitBus *outBus = [[AUAudioUnitBus alloc] initWithFormat:fmt error:&busErr];
    if (busErr) { if (error) *error = busErr; return nil; }
    _outputBusArray = [[AUAudioUnitBusArray alloc]
        initWithAudioUnit:self busType:AUAudioUnitBusTypeOutput busses:@[outBus]];

    if (AUV3_NUM_INPUTS > 0) {
        AVAudioFormat *inFmt = [[AVAudioFormat alloc]
            initWithCommonFormat:AVAudioPCMFormatFloat32
                      sampleRate:44100.0
                        channels:AUV3_NUM_INPUTS
                     interleaved:NO];
        AUAudioUnitBus *inBus = [[AUAudioUnitBus alloc] initWithFormat:inFmt error:&busErr];
        if (busErr) { if (error) *error = busErr; return nil; }
        _inputBusArray = [[AUAudioUnitBusArray alloc]
            initWithAudioUnit:self busType:AUAudioUnitBusTypeInput busses:@[inBus]];
    } else {
        _inputBusArray = [[AUAudioUnitBusArray alloc]
            initWithAudioUnit:self busType:AUAudioUnitBusTypeInput busses:@[]];
    }

    // Create gen~ state eagerly for parameter metadata
    _genState = wrapper_create(44100.0f, 512);
    _numParams = wrapper_num_params();
    _paramValues = (float *)calloc(_numParams, sizeof(float));
    _blockSize = 0;
    _inBuf = nullptr;
    _outBuf = nullptr;

    // Read default values
    for (int i = 0; i < _numParams; i++) {
        _paramValues[i] = wrapper_get_param(_genState, i);
    }

    // Build parameter tree
    [self _buildParameterTree];

    return self;
}

- (void)dealloc {
    if (_genState) wrapper_destroy(_genState);
    if (_paramValues) free(_paramValues);
    if (_inBuf) free(_inBuf);
    if (_outBuf) free(_outBuf);
}

- (AUAudioUnitBusArray *)inputBusses  { return _inputBusArray; }
- (AUAudioUnitBusArray *)outputBusses { return _outputBusArray; }

// ---------------------------------------------------------------------------
// Parameter tree
// ---------------------------------------------------------------------------

- (void)_buildParameterTree {
    NSMutableArray<AUParameter *> *params = [NSMutableArray new];
    for (int i = 0; i < _numParams; i++) {
        const char *cname = wrapper_param_name(_genState, i);
        NSString *name = cname ? [NSString stringWithUTF8String:cname] : [NSString stringWithFormat:@"param%d", i];
        NSString *ident = [name stringByReplacingOccurrencesOfString:@" " withString:@"_"];

        float pmin = wrapper_param_min(_genState, i);
        float pmax = wrapper_param_max(_genState, i);
        float pdef = _paramValues[i];
        // Clamp default to range
        if (pdef < pmin) pdef = pmin;
        if (pdef > pmax) pdef = pmax;

        AUParameter *p = [AUParameterTree
            createParameterWithIdentifier:ident
                                     name:name
                                  address:(AUParameterAddress)i
                                      min:pmin
                                      max:pmax
                                     unit:kAudioUnitParameterUnit_Generic
                                 unitName:nil
                                    flags:kAudioUnitParameterFlag_IsWritable |
                                          kAudioUnitParameterFlag_IsReadable
                             valueStrings:nil
                      dependentParameters:nil];
        p.value = pdef;
        [params addObject:p];
    }

    self.parameterTree = [AUParameterTree createTreeWithChildren:params];

    // Wire up value observation (host -> DSP)
    __unsafe_unretained GenDspAudioUnit *weakSelf = self;
    self.parameterTree.implementorValueObserver = ^(AUParameter *param, AUValue value) {
        weakSelf->_paramValues[param.address] = value;
    };
    self.parameterTree.implementorValueProvider = ^AUValue(AUParameter *param) {
        return weakSelf->_paramValues[param.address];
    };
    self.parameterTree.implementorStringFromValueCallback = ^NSString *(AUParameter *param,
                                                                        const AUValue *value) {
        AUValue v = value ? *value : param.value;
        return [NSString stringWithFormat:@"%.3f", v];
    };
}

// ---------------------------------------------------------------------------
// Render resources
// ---------------------------------------------------------------------------

- (BOOL)allocateRenderResourcesAndReturnError:(NSError **)outError {
    if (![super allocateRenderResourcesAndReturnError:outError]) return NO;

    double sr = self.outputBusses[0].format.sampleRate;
    long maxFrames = (long)self.maximumFramesToRender;

    // Recreate gen~ state at the correct sample rate
    if (_genState) wrapper_destroy(_genState);
    _genState = wrapper_create((float)sr, maxFrames);

    // Restore parameter values
    for (int i = 0; i < _numParams; i++) {
        wrapper_set_param(_genState, i, _paramValues[i]);
    }

    // Allocate scratch buffers
    _blockSize = maxFrames;
    if (_inBuf) free(_inBuf);
    if (_outBuf) free(_outBuf);
    int maxCh = AUV3_NUM_INPUTS > AUV3_NUM_OUTPUTS ? AUV3_NUM_INPUTS : AUV3_NUM_OUTPUTS;
    if (maxCh < 1) maxCh = 1;
    _inBuf  = (float *)calloc(maxCh * maxFrames, sizeof(float));
    _outBuf = (float *)calloc(maxCh * maxFrames, sizeof(float));

    return YES;
}

- (void)deallocateRenderResources {
    [super deallocateRenderResources];
    // Keep _genState alive for parameter queries; just free scratch
    if (_inBuf) { free(_inBuf); _inBuf = nullptr; }
    if (_outBuf) { free(_outBuf); _outBuf = nullptr; }
}

// ---------------------------------------------------------------------------
// Render block
// ---------------------------------------------------------------------------

- (AUInternalRenderBlock)internalRenderBlock {
    // Capture raw pointers for realtime safety (no ObjC messaging in render)
    __unsafe_unretained GenDspAudioUnit *au = self;

    return ^AUAudioUnitStatus(
        AudioUnitRenderActionFlags *actionFlags,
        const AudioTimeStamp      *timestamp,
        AUAudioFrameCount          frameCount,
        NSInteger                  outputBusNumber,
        AudioBufferList           *outputData,
        const AURenderEvent       *realtimeEventListHead,
        AURenderPullInputBlock     pullInputBlock)
    {
        GenState *state = au->_genState;
        float *paramVals = au->_paramValues;
        int numParams = au->_numParams;
        float *inScratch = au->_inBuf;
        float *outScratch = au->_outBuf;
        long bs = au->_blockSize;
        if (!state || !outScratch) return kAudioUnitErr_Uninitialized;

        int numIn = AUV3_NUM_INPUTS;
        int numOut = AUV3_NUM_OUTPUTS;
        long n = (long)frameCount;
        if (n > bs) n = bs;

        // Pull input for effects
        if (numIn > 0 && pullInputBlock) {
            AudioUnitRenderActionFlags pullFlags = 0;
            AUAudioUnitStatus err = pullInputBlock(&pullFlags, timestamp,
                                                    frameCount, 0, outputData);
            if (err != noErr) return err;
        }

        // Process parameter events
        const AURenderEvent *event = realtimeEventListHead;
        while (event) {
            if (event->head.eventType == AURenderEventParameter ||
                event->head.eventType == AURenderEventParameterRamp) {
                AUParameterAddress addr = event->parameter.parameterAddress;
                if (addr < (AUParameterAddress)numParams) {
                    paramVals[addr] = event->parameter.value;
                }
            }
            event = event->head.next;
        }

        // Apply parameters to gen~ state
        for (int i = 0; i < numParams; i++) {
            wrapper_set_param(state, i, paramVals[i]);
        }

        // Set up channel pointers
        float *inPtrs[8] = {};
        float *outPtrs[8] = {};

        // Input: from outputData (in-place for effects) or silence for generators
        for (int ch = 0; ch < numIn && ch < 8; ch++) {
            if (ch < (int)outputData->mNumberBuffers && outputData->mBuffers[ch].mData) {
                inPtrs[ch] = (float *)outputData->mBuffers[ch].mData;
            } else {
                inPtrs[ch] = &inScratch[ch * bs];
                memset(inPtrs[ch], 0, n * sizeof(float));
            }
        }

        // Output: use outputData buffers directly (non-interleaved float32)
        for (int ch = 0; ch < numOut && ch < 8; ch++) {
            if (ch < (int)outputData->mNumberBuffers) {
                if (!outputData->mBuffers[ch].mData) {
                    // Host expects plugin to provide buffer
                    outputData->mBuffers[ch].mData = &outScratch[ch * bs];
                    outputData->mBuffers[ch].mDataByteSize = (UInt32)(n * sizeof(float));
                }
                outPtrs[ch] = (float *)outputData->mBuffers[ch].mData;
            } else {
                outPtrs[ch] = &outScratch[ch * bs];
            }
        }

        // Run DSP
        wrapper_perform(state, inPtrs, (long)numIn, outPtrs, (long)numOut, n);

        return noErr;
    };
}

@end

// ---------------------------------------------------------------------------
// AUAudioUnitFactory -- entry point for App Extension
// ---------------------------------------------------------------------------

@interface GenDspAUv3Factory : NSObject <AUAudioUnitFactory>
@end

@implementation GenDspAUv3Factory

- (AUAudioUnit *)createAudioUnitWithComponentDescription:(AudioComponentDescription)desc
                                                   error:(NSError **)error {
    return [[GenDspAudioUnit alloc] initWithComponentDescription:desc
                                                        options:0
                                                          error:error];
}

@end
