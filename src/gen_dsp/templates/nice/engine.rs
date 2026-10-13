//! Safe wrapper over the C ABI in `gen_ext_nice.cpp`.
//!
//! `Engine` owns one gen~ instance (or `NUM_VOICES` of them when polyphony is
//! enabled). It allocates only in `Engine::new`.

use std::ffi::c_int;
use std::ptr::NonNull;

/// Most channels `Engine::process` accepts per direction (matches the C++ side).
pub const MAX_CHANNELS: usize = 64;

#[repr(C)]
struct GenDspEngine {
    _private: [u8; 0],
}

unsafe extern "C" {
    fn gendsp_create(sr: f32, max_frames: c_int) -> *mut GenDspEngine;
    fn gendsp_destroy(e: *mut GenDspEngine);
    fn gendsp_reset(e: *mut GenDspEngine);
    fn gendsp_perform(
        e: *mut GenDspEngine,
        ins: *mut *mut f32,
        num_ins: c_int,
        outs: *mut *mut f32,
        num_outs: c_int,
        n: c_int,
    );
    fn gendsp_set_param(e: *mut GenDspEngine, index: c_int, value: f32);
    fn gendsp_get_param(e: *mut GenDspEngine, index: c_int) -> f32;
    fn gendsp_note_on(e: *mut GenDspEngine, note: c_int, velocity: f32);
    fn gendsp_note_off(e: *mut GenDspEngine, note: c_int);
    fn gendsp_num_inputs() -> c_int;
    fn gendsp_num_outputs() -> c_int;
    fn gendsp_num_params() -> c_int;
}

pub struct Engine {
    ptr: NonNull<GenDspEngine>,
    max_frames: usize,
}

// The engine is used from one thread at a time; nice-plug moves the plugin
// between threads, which requires Send.
unsafe impl Send for Engine {}

impl Engine {
    /// Create an engine; `None` if the C++ side failed to allocate.
    pub fn new(sample_rate: f32, max_frames: usize) -> Option<Self> {
        let frames = c_int::try_from(max_frames).ok()?;
        let ptr = NonNull::new(unsafe { gendsp_create(sample_rate, frames) })?;
        Some(Self { ptr, max_frames })
    }

    /// Clear delay lines, histories and other DSP state.
    pub fn reset(&mut self) {
        unsafe { gendsp_reset(self.ptr.as_ptr()) }
    }

    /// Set parameter `index` (gen~ order) to a plain value.
    pub fn set_param(&mut self, index: usize, value: f32) {
        if index < num_params() {
            unsafe { gendsp_set_param(self.ptr.as_ptr(), index as c_int, value) }
        }
    }

    /// Read parameter `index` (gen~ order) back from the gen~ state.
    pub fn param(&self, index: usize) -> f32 {
        if index < num_params() {
            unsafe { gendsp_get_param(self.ptr.as_ptr(), index as c_int) }
        } else {
            0.0
        }
    }

    /// Note on: sets the gate/freq/vel parameters chosen at generation time.
    /// A no-op unless the project was generated with MIDI enabled.
    pub fn note_on(&mut self, note: u8, velocity: f32) {
        unsafe { gendsp_note_on(self.ptr.as_ptr(), note as c_int, velocity) }
    }

    /// Note off. Monophonic projects close the gate whatever `note` is.
    pub fn note_off(&mut self, note: u8) {
        unsafe { gendsp_note_off(self.ptr.as_ptr(), note as c_int) }
    }

    /// Run the gen~ code over one block.
    ///
    /// Every slice must have the same length, at most the `max_frames` given
    /// to `new`. `outputs` must not alias `inputs`.
    ///
    /// # Panics
    ///
    /// On a length mismatch or more than `MAX_CHANNELS` channels.
    pub fn process(&mut self, inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
        let n = outputs.first().map_or(0, |o| o.len());
        assert!(n <= self.max_frames, "block of {n} exceeds max_frames");
        assert!(inputs.len() <= MAX_CHANNELS && outputs.len() <= MAX_CHANNELS);
        assert!(inputs.iter().all(|c| c.len() == n));
        assert!(outputs.iter().all(|c| c.len() == n));
        if n == 0 {
            return;
        }
        let mut ins = [std::ptr::null_mut::<f32>(); MAX_CHANNELS];
        let mut outs = [std::ptr::null_mut::<f32>(); MAX_CHANNELS];
        for (p, c) in ins.iter_mut().zip(inputs) {
            // gen~ reads inputs only; the C signature is not const-correct.
            *p = c.as_ptr() as *mut f32;
        }
        for (p, c) in outs.iter_mut().zip(outputs.iter_mut()) {
            *p = c.as_mut_ptr();
        }
        unsafe {
            gendsp_perform(
                self.ptr.as_ptr(),
                ins.as_mut_ptr(),
                inputs.len() as c_int,
                outs.as_mut_ptr(),
                outputs.len() as c_int,
                n as c_int,
            )
        }
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        unsafe { gendsp_destroy(self.ptr.as_ptr()) }
    }
}

/// Signal inputs the gen~ code reads, after any `--inputs-as-params` remapping.
pub fn num_inputs() -> usize {
    unsafe { gendsp_num_inputs() as usize }
}

/// Signal outputs the gen~ code writes.
pub fn num_outputs() -> usize {
    unsafe { gendsp_num_outputs() as usize }
}

/// Parameters, including any remapped inputs.
pub fn num_params() -> usize {
    unsafe { gendsp_num_params() as usize }
}
