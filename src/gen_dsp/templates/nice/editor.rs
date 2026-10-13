//! Generic egui editor: one slider per gen~ parameter (`gui` feature).
//!
//! Replace `GenEditor::ui` to build a custom interface.

use crate::GenParams;
use nice_plug::context::gui::GuiContext;
use nice_plug::editor::dpi::LogicalSize;
use nice_plug_egui::{
    EguiEditor, EguiEditorState, EguiNiceSettings, Frame, NiceEguiApp, RepaintNotifier,
    baseview::HandlerError, create_egui_editor,
};
use std::sync::Arc;

pub struct GenEditor {
    params: Arc<GenParams>,
    gui_ctx: Option<GuiContext>,
}

impl NiceEguiApp for GenEditor {
    fn build(
        &mut self,
        _egui_ctx: egui::Context,
        gui_ctx: GuiContext,
        _frame: &mut Frame,
    ) -> Result<(), HandlerError> {
        self.gui_ctx = Some(gui_ctx);
        Ok(())
    }

    fn editor_closed(&mut self) {
        self.gui_ctx = None;
    }

    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut Frame) {
        let Some(gui_ctx) = &self.gui_ctx else {
            return;
        };
        let setter = gui_ctx.param_setter();
        egui::ScrollArea::vertical().show(ui, |ui| {
            crate::param_widgets(ui, &self.params, &setter);
        });
    }
}

pub fn create(params: Arc<GenParams>) -> Option<EguiEditor<GenEditor>> {
    let height = 24.0 + 44.0 * crate::NUM_PARAMS.clamp(1, 16) as f32;
    create_egui_editor(
        EguiEditorState::from_size(LogicalSize::new(360.0, height), 1.0),
        RepaintNotifier::new(),
        EguiNiceSettings::new(),
        GenEditor {
            params,
            gui_ctx: None,
        },
    )
}
