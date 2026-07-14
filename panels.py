"""
Kimodo Blender Bridge — Panels
All N-panel UI panels in the 3D Viewport → Kimodo tab.
"""

import os
import textwrap

import bpy
import json
from bpy.types import Panel


# ---------------------------------------------------------------------------
# Base class — common settings
# ---------------------------------------------------------------------------

class KIMODO_PanelBase:
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'Kimodo'


# ---------------------------------------------------------------------------
# Generation history (shared by Quick Generate + Motion Segments panels)
# ---------------------------------------------------------------------------

def _label_wrapped(col, text, context, icon='NONE'):
    """Labels don't wrap on their own, so long prompts (e.g. 5+ joined
    segment prompts) were cut off. Emit the text as multiple labels sized
    to the panel width instead."""
    try:
        ui_scale = context.preferences.system.ui_scale
    except Exception:
        ui_scale = 1.0
    width_px = context.region.width if context.region else 320
    chars = max(24, int(width_px / (7 * ui_scale)) - 4)
    for i, line in enumerate(textwrap.wrap(text, width=chars) or [""]):
        col.label(text=line, icon=icon if i == 0 else 'BLANK1')


def _draw_history_detail(layout, context, entry):
    """Selected entry: full wrapped prompt(s) with the seed(s) used."""
    col = layout.column(align=True)
    prompts = [p.strip() for p in entry.prompt.split(" | ")] if entry.prompt else [""]
    seed_list = [x.strip() for x in entry.seeds.split(",") if x.strip()] if entry.seeds else []

    if len(prompts) > 1:
        # Multi-segment generation: one line per segment with its own seed
        for i, p in enumerate(prompts):
            seed_txt = f"   (seed {seed_list[i]})" if i < len(seed_list) else ""
            _label_wrapped(col, f"{i + 1}.  {p}{seed_txt}", context,
                           icon='TEXT' if i == 0 else 'BLANK1')
        meta = f"{entry.duration:.1f}s total  ·  {entry.timestamp.replace('T', ' ')}"
        if not seed_list:  # entry from a version that only stored the first seed
            meta = f"Seed: {entry.seed}  ·  {meta}"
    else:
        _label_wrapped(col, entry.prompt, context, icon='TEXT')
        meta = f"Seed: {entry.seed}  ·  {entry.duration:.1f}s  ·  {entry.timestamp.replace('T', ' ')}"

    meta_col = layout.column(align=True)
    _label_wrapped(meta_col, meta, context, icon='TIME')


def _draw_history(layout, context, s):
    layout.separator()
    hist_header = layout.row(align=True)
    hist_header.prop(
        s, "history_expanded",
        icon='DISCLOSURE_TRI_DOWN' if s.history_expanded else 'DISCLOSURE_TRI_RIGHT',
        icon_only=True, emboss=False,
    )
    hist_header.label(
        text=f"History ({len(s.generation_history)})", icon='TIME'
    )
    if not s.history_expanded:
        return
    if not s.generation_history:
        layout.label(text="No generations yet.", icon='INFO')
    else:
        layout.template_list(
            "KIMODO_UL_History", "",
            s, "generation_history",
            s, "history_index",
            rows=min(len(s.generation_history), 5),
        )
        if 0 <= s.history_index < len(s.generation_history):
            entry = s.generation_history[s.history_index]
            detail = layout.box()
            _draw_history_detail(detail, context, entry)
            op_row = detail.row(align=True)
            reimport_op = op_row.operator(
                "kimodo.reimport_from_history",
                text="Re-import BVH", icon='IMPORT',
            )
            reimport_op.index = s.history_index
    layout.operator("kimodo.clear_history", text="Clear History", icon='TRASH')


# ---------------------------------------------------------------------------
# Panel 1: Connection
# ---------------------------------------------------------------------------

class KIMODO_PT_Connection(KIMODO_PanelBase, Panel):
    bl_label    = "⚙  Connection"
    bl_idname   = "KIMODO_PT_Connection"
    bl_order    = 10
    

    def draw(self, context):
        layout = self.layout
        s = context.scene.kimodo

        try:
            prefs = context.preferences.addons[__package__].preferences
            persistent_python = (prefs.kimodo_python_executable or "").strip()
        except Exception:
            persistent_python = ""
        scene_python = (s.python_executable or "").strip()
        configured_python = scene_python or persistent_python
        configured_python_valid = bool(
            configured_python and os.path.isfile(configured_python)
        )

        running = s.is_connected

        # --- Auto-install section ---
        from . import setup_operator as so

        if so.is_installing():
            box = layout.box()
            box.label(text="Installing Kimodo…", icon='TIME')
            box.label(text=so.install_status())
            dl_pct = so.download_progress()
            if dl_pct > 0.0:
                label = so.download_label()
                short = label.replace("Downloading ", "").replace(" (attempt 1/3)", "")
                box.progress(factor=dl_pct, text=f"{short}  {int(dl_pct * 100)}%")
            layout.separator(factor=0.5)

        elif so.install_failed() or (
            so.venv_exists()
            and not so.is_installed()
            and not configured_python_valid
        ):
            # install_failed()  → failed this session
            # venv_exists() but not is_installed() → partial venv from a
            # previous session (no sentinel file); treat it the same way.
            box = layout.box()
            if so.needs_python():
                box.label(text="Python 3.10–3.12 required!", icon='ERROR')
                box.separator(factor=0.3)
                box.label(text="No compatible Python was found on your system.")
                box.label(text="Click below to download the Python 3.12 installer (Windows 64-bit).")
                box.label(text='Run it, tick "Add Python to PATH".')
                box.label(text="On Windows: run the installer as Administrator.")
                box.label(text="Then restart Blender before clicking Retry Install.", icon='ERROR')
                box.label(text="On Windows, restart your computer (not just Blender)", icon='BLANK1')
                box.label(text="so the new PATH takes effect.", icon='BLANK1')
                box.separator(factor=0.3)
                box.label(text="Select your Python 3.10–3.12 executable:", icon='FILEBROWSER')
                box.label(text="e.g. /usr/bin/python3.12  or  C:\\Python312\\python.exe",
                          icon='BLANK1')
                try:
                    prefs = context.preferences.addons[__package__].preferences
                    box.prop(prefs, "system_python_override", text="")
                except Exception:
                    pass
                box.separator(factor=0.3)
                box.label(text="Or install Python from python.org:", icon='URL')
                box.operator("kimodo.open_python_download",
                             text="Download Python 3.12 Installer", icon='URL')
                box.separator(factor=0.3)
            else:
                box.label(text="Installation incomplete", icon='ERROR')
                if so.install_status():
                    box.label(text=so.install_status(), icon='BLANK1')
                try:
                    prefs = context.preferences.addons[__package__].preferences
                    box.label(text="Install location (blank = default ~/.kimodo-venv):",
                              icon='FILE_FOLDER')
                    box.prop(prefs, "install_location", text="")
                except Exception:
                    pass
            # Reuse the already-chosen location on retry — no folder prompt.
            op = box.operator("kimodo.install_kimodo",
                              text="Retry Install", icon='FILE_REFRESH')
            op.prompt_location = False
            box.operator("kimodo.reset_venv",
                         text="Reset Venv", icon='TRASH')
            layout.separator(factor=0.5)

        elif (
            not so.is_installed()
            and not configured_python_valid
            and not so.is_kimodo_venv(scene_python)
        ):
            box = layout.box()
            has_gpu = so.has_nvidia_gpu()
            if not has_gpu:
                box.label(text="NVIDIA GPU required!", icon='ERROR')
                box.label(text="Kimodo only works with NVIDIA GPUs (CUDA).")
                box.label(text="AMD and Intel GPUs are not supported.")
                box.separator(factor=0.3)
            else:
                box.label(text="Kimodo not installed", icon='INFO')
            box.label(text="Requires:  Python 3.10 - 3.12, ~8 GB disk, internet")
            box.label(text="Click Install, then pick a folder for the Kimodo venv.",
                      icon='FILE_FOLDER')
            row = box.row()
            row.scale_y = 1.3
            row.enabled = has_gpu
            row.operator("kimodo.install_kimodo", icon='IMPORT')
            # Advanced overrides (Python / HF token / explicit install location).
            self._draw_advanced(box, context, s, show_python=True)
            layout.separator(factor=0.5)

        elif not configured_python_valid and not so.managed_python():
            box = layout.box()
            box.label(text="Kimodo venv ready", icon='CHECKMARK')
            box.operator("kimodo.use_installed_kimodo", icon='CONSOLE')
            self._draw_advanced(box, context, s, show_python=True)
            layout.separator(factor=0.5)
        else:
            # Installed and a Python executable is set — keep overrides one click
            # away under Advanced instead of always on screen.
            box = layout.box()
            self._draw_advanced(box, context, s, show_python=True)
            layout.separator(factor=0.5)

        # --- Model selector ---
        row = layout.row(align=True)
        row.label(text="Model:", icon='ARMATURE_DATA')
        row.prop(s, "kimodo_model", text="")
        row.enabled = not running

        # --- Offload toggle ---
        row = layout.row(align=True)
        row.prop(s, "use_offload", text="Enable Memory Offload")
        row.enabled = not running

        layout.separator(factor=0.5)

        # --- Start / Stop buttons ---
        if running:
            layout.operator("kimodo.stop_kimodo",
                            text="Stop Kimodo", icon='CANCEL')
        else:
            layout.operator("kimodo.start_kimodo",
                            text="Start Kimodo", icon='PLAY')

        # --- Status ---
        status_row = layout.row()
        if running:
            status_row.label(text=s.connection_status, icon='CHECKMARK')
        elif s.connection_status in ("Not started", "Stopped"):
            status_row.label(text=s.connection_status, icon='RADIOBUT_OFF')
        else:
            # Loading or error
            is_err = s.connection_status.startswith("Failed") or \
                     s.connection_status.startswith("Error")
            status_row.label(
                text=s.connection_status,
                icon='ERROR' if is_err else 'TIME',
            )


        # --- Delete venv (always shown when installed) ---
        if so.is_installed() and not so.is_installing():
            layout.separator(factor=0.5)
            row = layout.row()
            row.alignment = 'RIGHT'
            row.operator("kimodo.reset_venv", text="Delete Venv", icon='TRASH', emboss=False)

    def _draw_advanced(self, box, context, s, show_python=False):
        """Collapsible Advanced overrides: Python path, HF token, install location.

        Keeps the default Connection view clean while leaving both override
        capabilities (Python executable + venv install location) one click away.
        """
        expanded = s.show_advanced_connection
        box.prop(
            s, "show_advanced_connection",
            text="Advanced",
            icon='TRIA_DOWN' if expanded else 'TRIA_RIGHT',
            emboss=False,
        )
        if not expanded:
            return

        col = box.column(align=True)
        try:
            prefs = context.preferences.addons[__package__].preferences
        except Exception:
            prefs = None
        if show_python:
            col.label(text="Kimodo Python (persistent):", icon='CONSOLE')
            row = col.row(align=True)
            if prefs is not None:
                row.prop(prefs, "kimodo_python_executable", text="")
            else:
                row.prop(s, "python_executable", text="")
            row.enabled = not s.is_connected
            col.label(text="Leave blank to use the managed install / auto-detect",
                      icon='INFO')
            col.separator(factor=0.5)

        try:
            if prefs is None:
                raise RuntimeError("Kimodo addon preferences are unavailable")
            col.label(text="HF Token (optional — set if model downloads stall):",
                      icon='LOCKED')
            col.prop(prefs, "hf_token", text="")
            col.label(text="HuggingFace cache (optional HF_HOME):",
                      icon='FILE_FOLDER')
            col.prop(prefs, "hf_cache_dir", text="")
            col.label(text="Text encoder:", icon='MEMORY')
            row = col.row(align=True)
            row.prop(prefs, "text_encoder_device", text="Device")
            row.prop(prefs, "text_encoder_mode", text="Mode")
            col.label(text="System Python 3.10–3.12 (override auto-detect):",
                      icon='CONSOLE')
            col.prop(prefs, "system_python_override", text="")
            col.label(text="Install location (blank = default ~/.kimodo-venv):",
                      icon='FILE_FOLDER')
            col.prop(prefs, "install_location", text="")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Panel 2: Motion Segments (timeline bars)
# ---------------------------------------------------------------------------

class KIMODO_PT_Segments(KIMODO_PanelBase, Panel):
    bl_label  = "🏞  Motion Segments"
    bl_idname = "KIMODO_PT_Segments"
    bl_order  = 15
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s      = context.scene.kimodo

        # --- Toolbar ---
        row = layout.row(align=True)
        row.operator("kimodo.add_segment",    text="Add",       icon='ADD')
        row.operator("kimodo.remove_segment", text="Remove",    icon='REMOVE')
        row.separator()
        row.operator("kimodo.duplicate_segment", text="", icon='DUPLICATE')
        row.operator("kimodo.move_segment_up",   text="", icon='TRIA_UP')
        row.operator("kimodo.move_segment_down", text="", icon='TRIA_DOWN')

        layout.separator(factor=0.5)


        row = layout.row(align=True)
        row.label(text="Model:")
        row.prop(s, "model_type", expand=True)

        # --- FPS warning ---
        scene_fps = context.scene.render.fps / context.scene.render.fps_base
        if abs(scene_fps - 30.0) > 0.01:
            fps_box = layout.box()
            fps_box.alert = True
            fps_box.label(text=f"Scene is {scene_fps:.4g} FPS — Kimodo needs 30 FPS", icon='ERROR')
            fps_box.operator("kimodo.set_to_30fps", text="Set to 30 FPS", icon='RECOVER_LAST')

        # --- Segment list ---
        if not s.motion_segments:
            col = layout.column()
            col.label(text="No segments yet.", icon='INFO')
            col.label(text="Click Add to create one.")
            return

        for i, seg in enumerate(s.motion_segments):
            is_active     = (i == s.segment_index)
            is_generating = (i == s.generating_segment_index)

            box = layout.box()
            #box.alert = is_active   # blue highlight on active segment

            # --- Header row: [enabled] [color] [label] [select] [generate] ---
            header = box.row(align=True)

            header.prop(seg, "enabled", text="", emboss=False,
                        icon='CHECKBOX_HLT' if seg.enabled else 'CHECKBOX_DEHLT')

            # Segment title: prompt preview + frame range
            title = f"  {seg.prompt[:28]}{'…' if len(seg.prompt) > 28 else ''}"
            header.label(text=title)

            frames_label = f"{seg.start_frame}–{seg.end_frame}"
            header.label(text=frames_label)

            if is_generating:
                header.label(text="", icon='TIME')
            elif seg.generated:
                header.label(text="", icon='CHECKMARK')

            # Select button — sets this as the active segment
            #select_icon = 'RADIOBUT_ON' if is_active else 'RADIOBUT_OFF'
            #op_sel = header.operator("kimodo.select_segment", text="", icon=select_icon, emboss=False)
            #op_sel.index = i

            # Remove button
            op_rem = header.operator("kimodo.remove_segment_by_index", text="", icon='X', emboss=False)
            op_rem.index = i

            # --- Body: always visible ---
            col = box.column(align=True)
            col.prop(seg, "prompt", text="")

            row2 = col.row(align=True)
            start_sub = row2.row(align=True)
            start_sub.enabled = (i == 0)
            start_sub.prop(seg, "start_frame", text="Start")
            row2.prop(seg, "end_frame",   text="End")

            fps = context.scene.render.fps / context.scene.render.fps_base
            dur = (seg.end_frame - seg.start_frame + 1) / fps
            
            row3 = col.row(align=True)
            row3.label(text=f"  {dur:.1f}s · {seg.end_frame - seg.start_frame + 1} frames",
                      icon='TIME')
            seed_field = row3.row(align=True)
            seed_field.enabled = seg.seed_mode != 'RANDOM'
            seed_field.prop(seg, "seed", text="Seed")
            seed_modes = row3.row(align=True)
            seed_modes.alignment = 'RIGHT'
            seed_modes.prop(seg, "seed_mode", expand=True)



        layout.separator()

        # --- Generate buttons ---
        layout.prop(s, "bvh_standard_tpose", icon='ARMATURE_DATA')

        # Reuse armature eyedropper + auto-pick button
        reuse_row = layout.row(align=True)
        reuse_row.prop(s, "reuse_armature", text="Reuse", icon='ARMATURE_DATA')
        reuse_row.operator("kimodo.pick_latest_armature", text="", icon='SORTTIME')

        # Transition frames control
        trans_row = layout.row(align=True)
        trans_row.enabled = s.is_connected and not s.is_generating
        trans_row.label(text="Transition Frames:")
        trans_row.prop(s, "num_transition_frames", text="")

        gen_row = layout.row(align=True)
        gen_row.enabled = s.is_connected and not s.is_generating
        #gen_row.operator("kimodo.generate_segment",      text="Generate Selected", icon='PLAY')
        #use tpose button below

        gen_row.scale_y = 2
        gen_row.operator("kimodo.generate_all_segments", text="Generate Motion",icon='PLAY')

        if s.is_generating:
            box2 = layout.box()
            box2.label(text=s.generation_progress or "Working…", icon='TIME')
            box2.operator("kimodo.cancel_generation", text="Cancel", icon='X')

        # --- Generation History ---
        _draw_history(layout, context, s)



# ---------------------------------------------------------------------------
# Panel 3: Generate (single prompt, kept for quick use)
# ---------------------------------------------------------------------------

class KIMODO_PT_Generate(KIMODO_PanelBase, Panel):
    bl_label   = "🎬  Quick Generate"
    bl_idname  = "KIMODO_PT_Generate"
    bl_order   = 14
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = context.scene.kimodo

        # Disable panel while generating
        layout.enabled = not s.is_generating

        # Model selector
        row = layout.row(align=True)
        row.label(text="Model:")
        row.prop(s, "model_type", expand=True)

        # Prompt
        layout.label(text="Prompt:")
        layout.prop(s, "prompt", text="")

        # Duration + Seed
        layout.prop(s, "duration", slider=True)
        seed_row = layout.row(align=True)
        seed_field = seed_row.row(align=True)
        seed_field.enabled = s.seed_mode != 'RANDOM'
        seed_field.prop(s, "seed")
        seed_modes = seed_row.row(align=True)
        seed_modes.alignment = 'RIGHT'
        seed_modes.prop(s, "seed_mode", expand=True)

        # Output format
        row = layout.row(align=True)
        row.label(text="Output:")
        row.prop(s, "output_format", expand=True)

        # BVH T-pose option (only show for BVH format)
        if s.output_format == "bvh":
            layout.prop(s, "bvh_standard_tpose", icon='ARMATURE_DATA')

        layout.separator()

        # Reuse armature eyedropper + auto-pick button
        reuse_row = layout.row(align=True)
        reuse_row.prop(s, "reuse_armature", text="Reuse", icon='ARMATURE_DATA')
        reuse_row.operator("kimodo.pick_latest_armature", text="", icon='SORTTIME')

        layout.separator()

        # Generate / Cancel button
        if s.is_generating:
            col = layout.column()
            col.enabled = True   # re-enable for cancel
            col.operator("kimodo.cancel_generation", text="⏹  Cancel", icon='X')
            # Progress
            box = layout.box()
            box.label(text=s.generation_progress or "Working…", icon='TIME')
        else:
            connected_icon = 'PLAY' if s.is_connected else 'UNLINKED'
            row = layout.column()
            
            row.enabled = s.is_connected
            
            scene_fps = context.scene.render.fps / context.scene.render.fps_base
            
            if abs(scene_fps - 30.0) > 0.01:
                fps_box = row.box()
                fps_box.alert = True
                fps_box.label(text=f"Scene is {scene_fps:.4g} FPS — Kimodo needs 30 FPS", icon='ERROR')
                fps_box.operator("kimodo.set_to_30fps", text="Set to 30 FPS", icon='RECOVER_LAST')

            row.scale_y = 2
            row.operator("kimodo.generate", text="Generate Motion", icon=connected_icon)
            if s.generation_progress:
                layout.label(text=s.generation_progress,
                             icon='CHECKMARK' if "Done" in s.generation_progress else 'ERROR')

        # --- Generate N Variations ---
        layout.separator()
        var_row = layout.row(align=True)
        var_row.enabled = s.is_connected and not s.is_generating
        var_row.prop(s, "num_variations", text="Variations")
        var_row.operator(
            "kimodo.generate_variations",
            text=f"Generate {s.num_variations} Variations",
            icon='DUPLICATE',
        )

        # --- Generation History ---
        _draw_history(layout, context, s)

        # Manual import fallback
        layout.separator()
        box = layout.box()
        box.label(text="Manual Import", icon='IMPORT')
        row = box.row()
        row.prop(s, "last_bvh_path", text="BVH Path")
        row.operator("kimodo.import_bvh", text="", icon='FILE_FOLDER').filepath = ""


# ---------------------------------------------------------------------------
# Panel 3: Motion Constraints
# ---------------------------------------------------------------------------

class KIMODO_PT_Constraints(KIMODO_PanelBase, Panel):
    bl_label   = "🎯  Motion Constraints"
    bl_idname  = "KIMODO_PT_Constraints"
    bl_order   = 25
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = context.scene.kimodo

        # --- Quick-add buttons ---
        layout.label(text="Add Constraint at Current Frame:", icon='ADD')
        grid = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)

        add_types = [
            ('root2d',      "Root XZ",    'EMPTY_ARROWS'),
            ('fullbody',    "Full-Body",  'ARMATURE_DATA'),
            ('left_hand',   "L.Hand",     'VIEW_PAN'),
            ('right_hand',  "R.Hand",     'VIEW_PAN'),
            ('left_foot',   "L.Foot",     'SNAP_FACE'),
            ('right_foot',  "R.Foot",     'SNAP_FACE'),
        ]
        for ctype, label, icon in add_types:
            op = grid.operator("kimodo.add_constraint", text=label, icon=icon)
            op.constraint_type = ctype

        # Fullbody tip — shown when Full-Body button is in the grid
        has_fullbody = any(ci.constraint_type == 'fullbody' for ci in s.motion_constraints)
        if not has_fullbody:
            tip = layout.box()
            tip.label(text="Full-Body tip:", icon='INFO')
            tip.label(text="Select an armature first, then click Full-Body.")
            tip.label(text="Or generate once — source arm will be duplicated.")

        # --- Curve path waypoint sampler ---
        layout.separator()
        path_box = layout.box()
        path_box.label(text="Sample Curve as Waypoints", icon='CURVE_DATA')
        split = path_box.split(factor=0.8, align=True)
        split.prop(s, "path_curve", text="Curve")
        split.operator("kimodo.draw_freehand_curve", text="Draw", icon='GREASEPENCIL')
        if s.path_curve:
            prow = path_box.row(align=True)
            prow.prop(s, "path_waypoints", text="Points")
            prow.prop(s, "path_start_frame", text="Start F")
            prow.prop(s, "path_end_frame", text="End F")
            path_box.operator(
                "kimodo.sample_curve_as_waypoints",
                text=f"Sample {s.path_waypoints} Waypoints",
                icon='NORMALIZE_FCURVES',
            )

        layout.separator()
        n = len(s.motion_constraints)
        if n:
            layout.label(text=f"{n} constraint{'s' if n != 1 else ''}:", icon='SEQUENCE')
        else:
            layout.label(text="No constraints — motion is unconstrained", icon='INFO')

        for i, ci in enumerate(s.motion_constraints):
            box = layout.box()
            row = box.row(align=True)

            # Enabled toggle
            row.prop(ci, "enabled", text="", emboss=False,
                     icon='CHECKBOX_HLT' if ci.enabled else 'CHECKBOX_DEHLT')

            # Type icon
            type_icons = {
                'root2d': 'EMPTY_ARROWS', 'fullbody': 'ARMATURE_DATA',
                'left_hand': 'VIEW_PAN',  'right_hand': 'VIEW_PAN',
                'left_foot': 'SNAP_FACE', 'right_foot': 'SNAP_FACE',
            }
            row.label(text="", icon=type_icons.get(ci.constraint_type, 'DOT'))

            # Type selector
            row.prop(ci, "constraint_type", text="")

            # Frame
            row.label(text="F:")
            row.prop(ci, "frame", text="")

            # Go to frame
            op_goto = row.operator("kimodo.goto_constraint_frame", text="", icon='TIME')
            op_goto.frame = ci.frame

            # Select object
            op_sel = row.operator("kimodo.select_constraint_object", text="", icon='RESTRICT_SELECT_OFF')
            op_sel.index = i

            # Remove
            op_rem = row.operator("kimodo.remove_constraint", text="", icon='X')
            op_rem.index = i
            op_rem.delete_object = False

            # --- Object picker row — type-aware ---
            sub = box.row(align=True)

            if ci.constraint_type == 'fullbody':
                # Armature picker with validation warning
                obj = ci.marker_object
                if obj and obj.type != 'ARMATURE':
                    # Wrong type — show error
                    sub.alert = True
                    sub.label(text="⚠ Not an armature!", icon='ERROR')
                    sub.prop(ci, "marker_object", text="Fix →")
                elif not obj:
                    # Nothing set — show hint
                    sub.alert = True
                    sub.label(text="Select an armature above then click Full-Body again", icon='INFO')
                    sub.prop(ci, "marker_object", text="Or set →")
                else:
                    # Valid armature — show normally with bone count hint
                    bone_n = len(obj.data.bones)
                    sub.prop(ci, "marker_object", text=f"Pose Ref  ({bone_n} bones)")
                    sub.operator(
                        "kimodo.select_constraint_object",
                        text="", icon='EDITMODE_HLT',
                    ).index = i
            else:
                # Regular Empty picker for all other types
                sub.prop(ci, "marker_object", text="Marker")

            # root2d heading extras
            if ci.constraint_type == 'root2d':
                sub2 = box.row(align=True)
                sub2.prop(ci, "include_heading", text="Heading")
                if ci.include_heading:
                    sub2.prop(ci, "heading_angle", text="")

        layout.separator()

        # --- Settings ---
        box = layout.box()
        box.label(text="Settings", icon='PREFERENCES')
        row = box.row(align=True)
        row.prop(s, "kimodo_fps")
        row.prop(s, "auto_canonicalize", toggle=True, text="Auto-Origin")

        layout.separator()

        # --- Actions ---
        row = layout.row(align=True)
        row.operator("kimodo.preview_constraints_json", icon='TEXT', text="Preview JSON")
        row.operator("kimodo.clear_constraints",        icon='TRASH', text="Clear All")


# ---------------------------------------------------------------------------
# Panel 4: Retarget
# ---------------------------------------------------------------------------

class KIMODO_PT_Retarget(KIMODO_PanelBase, Panel):
    bl_label   = "🦴  Retarget"
    bl_idname  = "KIMODO_PT_Retarget"
    bl_order   = 30
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = context.scene.kimodo

        # Armature pickers
        box = layout.box()
        box.label(text="Armatures", icon='ARMATURE_DATA')
        box.prop(s, "source_armature", text="Source (Kimodo)")
        box.prop(s, "target_armature", text="Target (Your Rig)")
        box.prop(s, "retarget_profile", text="Target Profile")
        if s.target_armature and s.retarget_profile == "AUTO":
            try:
                from . import retarget as rt
                detected_id = rt.detect_target_profile(s.target_armature)
                detected_label = rt.profile_label(detected_id) if detected_id else "Unknown humanoid"
            except Exception:
                detected_label = "Unknown humanoid"
            box.label(text=f"Detected: {detected_label}", icon='INFO')
        if s.target_armature:
            box.prop_search(
                s, "retarget_root_bone", s.target_armature.data, "bones",
                text="Root Bone",
            )
        else:
            box.prop(s, "retarget_root_bone", text="Root Bone")

        layout.separator()

        # Bone mapping list
        layout.label(text="Bone Mapping:", icon='BONE_DATA')
        layout.label(text="Link toggle = target bone's Inherit Rotation", icon='LINKED')

        if s.source_armature and s.target_armature:
            # Official target profile first, name heuristics only as fallback.
            layout.operator("kimodo.auto_map_bones",
                            text="Build Profile Mapping", icon='SHADERFX')

        row = layout.row()
        row.template_list(
            "KIMODO_UL_BoneMappings", "",
            s, "bone_mappings",
            s, "bone_mapping_index",
            rows=6,
        )

        col = row.column(align=True)
        col.operator("kimodo.add_bone_mapping",    text="", icon='ADD')
        col.operator("kimodo.remove_bone_mapping", text="", icon='REMOVE')

        layout.separator()

        # Apply / Remove constraints
        row = layout.row(align=True)
        row.operator("kimodo.apply_retargeting",  text="Apply Constraints", icon='CONSTRAINT_BONE')
        row.operator("kimodo.remove_retargeting", text="",                  icon='X')

        layout.separator()

        # Bake section
        box = layout.box()
        box.label(text="Bake Animation", icon='RENDER_ANIMATION')
        row = box.row(align=True)
        row.prop(s, "bake_start_frame", text="Start")
        row.prop(s, "bake_end_frame",   text="End")
        box.operator("kimodo.bake_retargeting",
                     text="Bake & Remove Constraints", icon='NLA_PUSHDOWN')

        layout.separator()

        # Primary workflow: sample the complete Kimodo Action and let the
        # restricted iClone receiver bake it into one Motion Clip.
        live_box = layout.box()
        live_box.label(text="iClone Direct Motion", icon='PLAY')
        live_box.label(text="Select one target character in iClone")
        try:
            from . import iclone_live_send as icsend
            live_state = icsend.inspect_source(s.source_armature)
        except Exception:
            live_state = {"ready": False, "action": "", "frame_count": 0, "missing_required": []}

        if live_state.get("action"):
            live_box.label(
                text=f"Action: {live_state['action']} | {live_state['frame_count']} frames",
                icon='ACTION',
            )
        elif s.source_armature:
            live_box.label(text="Source has no active Action", icon='ERROR')
        else:
            live_box.label(text="Choose Source (Kimodo) above", icon='INFO')
        if live_state.get("missing_required"):
            live_box.label(
                text="Missing: " + ", ".join(live_state["missing_required"]),
                icon='ERROR',
            )

        row = live_box.row(align=True)
        row.operator("kimodo.check_iclone_receiver", text="Check iClone", icon='FILE_REFRESH')
        send_col = row.column()
        send_col.enabled = bool(live_state.get("ready"))
        send_col.operator(
            "kimodo.send_motion_to_iclone",
            text="Send Motion to iClone",
            icon='PLAY',
        )
        live_box.label(text="Result: one Motion Clip; Motion Layer stays editable")
        if s.iclone_live_status:
            _label_wrapped(live_box, s.iclone_live_status, context, icon='INFO')

        layout.separator()

        # Manual file fallback for offline transfer.
        ic_box = layout.box()
        ic_box.label(text="Manual FBX Fallback", icon='EXPORT')
        try:
            from . import iclone_motion_export as icexport
            ic_state = icexport.inspect_source(s.source_armature)
        except Exception:
            ic_state = {"ready": False, "action": "", "missing_required": []}

        if s.source_armature:
            if ic_state.get("action"):
                ic_box.label(text=f"Action: {ic_state['action']}", icon='ACTION')
                ic_box.label(
                    text=(
                        f"Frames: {ic_state['frame_start']}-{ic_state['frame_end']} | "
                        f"HIK bones: {ic_state['mapped_bones']}"
                    )
                )
            else:
                ic_box.label(text="Source has no active Action", icon='ERROR')
            if ic_state.get("missing_required"):
                _label_wrapped(
                    ic_box,
                    "Missing SOMA bones: " + ", ".join(ic_state["missing_required"]),
                    context,
                    icon='ERROR',
                )
        else:
            ic_box.label(text="Choose Source (Kimodo) above", icon='INFO')

        export_col = ic_box.column()
        export_col.enabled = bool(ic_state.get("ready"))
        export_col.operator(
            "kimodo.export_iclone_motion",
            text="Export FBX + 3DX Profile",
            icon='EXPORT',
        )
        ic_box.label(text="Offline fallback: import manually in iClone")
        ic_box.label(text="Load the companion .3dxProfile; Root Bone: Root")

        if s.iclone_last_export_path:
            _label_wrapped(ic_box, s.iclone_last_export_path, context, icon='FILE')
        if s.iclone_export_status:
            _label_wrapped(ic_box, s.iclone_export_status, context, icon='INFO')

        layout.separator()

        # Presets
        box = layout.box()
        box.label(text="Bone Map Presets", icon='PRESET')
        row = box.row(align=True)
        row.prop(s, "preset_name", text="")
        row.operator("kimodo.save_preset", text="", icon='FILE_TICK')
        row.operator("kimodo.load_preset", text="", icon='IMPORT').preset_name = s.preset_name

        # List saved presets
        try:
            prefs = context.preferences.addons[__package__].preferences
            from . import retarget as rt
            preset_names = rt.list_presets(prefs)
        except Exception:
            preset_names = []

        if preset_names:
            col = box.column(align=True)
            for name in preset_names:
                row2 = col.row(align=True)
                op_load = row2.operator("kimodo.load_preset",   text=name, icon='IMPORT')
                op_load.preset_name = name
                op_del  = row2.operator("kimodo.delete_preset", text="",   icon='TRASH')
                op_del.preset_name = name

        # File export / import
        row = box.row(align=True)
        row.operator("kimodo.export_preset_file", text="Export to File", icon='EXPORT')
        row.operator("kimodo.import_preset_file", text="Import from File", icon='IMPORT')


# ---------------------------------------------------------------------------
# Panel 4: Help / About
# ---------------------------------------------------------------------------

class KIMODO_PT_Help(KIMODO_PanelBase, Panel):
    bl_label   = "ℹ  Help"
    bl_idname  = "KIMODO_PT_Help"
    bl_order   = 90
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Quick Start:", icon='QUESTION')
        col.separator()
        col.label(text="1. Click 'Install Kimodo (Auto)' in the Connection panel")
        col.label(text="   (or point Kimodo Python at your own venv)")
        col.label(text="2. Start Kimodo")
        col.label(text="   (model loads once, stays loaded)")
        col.separator()
        col.label(text="3. Enter prompt → Generate Motion")
        col.label(text="4. In Retarget tab, Pick source + target rigs")
        col.label(text="5. Auto-Match → Apply Constraints")
        col.label(text="6. If it does not match, manually add your control bones")
        col.label(text="7. Click Apply Constraints")
        col.label(text="8. Bake when satisfied")
        col.separator()
        col.label(text="Docs & Source:", icon='URL')
        col.label(text="github.com/nv-tlabs/kimodo")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = [
    KIMODO_PT_Connection,
    KIMODO_PT_Segments,
    KIMODO_PT_Generate,
    KIMODO_PT_Constraints,
    KIMODO_PT_Retarget,
    KIMODO_PT_Help,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
