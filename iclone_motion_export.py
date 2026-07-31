"""Standalone Kimodo motion export for Reallusion iClone.

iClone 8 can import external biped motion from FBX or BVH.  This module
exports the active Kimodo Action as an armature-only FBX and writes a matching
``.3dxProfile`` so iClone can characterize the SOMA skeleton without Data Link,
Rigify, or the Reallusion Blender add-on.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import bpy


class ICloneMotionExportError(RuntimeError):
    """An actionable motion-export error."""


# iClone/HIK human-bone semantics for Kimodo SOMA v1.1.  Kimodo's non-thumb
# digit 1 joints are metacarpals, so phalanges 2/3/4 map to HIK 1/2/3.
HIK_BONE_MAP = {
    "Hips": "Hips",
    "Spine1": "Spine",
    "Spine2": "Spine1",
    "Chest": "Spine2",
    "Neck1": "Neck",
    "Neck2": "Neck1",
    "Head": "Head",
    "LeftShoulder": "LeftShoulder",
    "LeftArm": "LeftArm",
    "LeftForeArm": "LeftForeArm",
    "LeftHand": "LeftHand",
    "LeftLeg": "LeftUpLeg",
    "LeftShin": "LeftLeg",
    "LeftFoot": "LeftFoot",
    "LeftToeBase": "LeftToeBase",
    "RightShoulder": "RightShoulder",
    "RightArm": "RightArm",
    "RightForeArm": "RightForeArm",
    "RightHand": "RightHand",
    "RightLeg": "RightUpLeg",
    "RightShin": "RightLeg",
    "RightFoot": "RightFoot",
    "RightToeBase": "RightToeBase",
}

for _side in ("Left", "Right"):
    for _index in range(1, 4):
        HIK_BONE_MAP[f"{_side}HandThumb{_index}"] = f"{_side}HandThumb{_index}"
    for _digit in ("Index", "Middle", "Ring", "Pinky"):
        for _source_index, _target_index in ((2, 1), (3, 2), (4, 3)):
            HIK_BONE_MAP[
                f"{_side}Hand{_digit}{_source_index}"
            ] = f"{_side}Hand{_digit}{_target_index}"


REQUIRED_BONES = {
    "Hips", "Spine1", "Head",
    "LeftArm", "LeftForeArm", "LeftHand",
    "RightArm", "RightForeArm", "RightHand",
    "LeftLeg", "LeftShin", "LeftFoot",
    "RightLeg", "RightShin", "RightFoot",
}


def _active_action(source):
    animation_data = source.animation_data
    return animation_data.action if animation_data else None


def inspect_source(source=None):
    """Return UI-safe readiness information for a Kimodo source armature."""
    result = {
        "ready": False,
        "source": "",
        "action": "",
        "frame_start": 0,
        "frame_end": 0,
        "mapped_bones": 0,
        "missing_required": [],
        "has_root": False,
    }
    if source is None or source.type != "ARMATURE":
        return result

    names = set(source.data.bones.keys())
    action = _active_action(source)
    missing = sorted(REQUIRED_BONES - names)
    result.update({
        "source": source.name,
        "action": action.name if action else "",
        "frame_start": math.floor(action.frame_range[0]) if action else 0,
        "frame_end": math.ceil(action.frame_range[1]) if action else 0,
        "mapped_bones": sum(name in names for name in HIK_BONE_MAP),
        "missing_required": missing,
        "has_root": "Root" in names,
        "ready": bool(action and not missing),
    })
    return result


def _pack_rotation(name, quaternion):
    return (
        f"{name} = {quaternion.x:.9g},{quaternion.y:.9g},"
        f"{quaternion.z:.9g},{quaternion.w:.9g},"
    )


def build_hik_profile(source, armature_node_name=None):
    """Build a 3DX motion profile from the armature's rest-pose rotations."""
    armature_node_name = armature_node_name or source.name
    names = set(source.data.bones.keys())
    mapping_lines = [
        f"{source_name} = {human_name}"
        for source_name, human_name in HIK_BONE_MAP.items()
        if source_name in names
    ]

    rotation_lines = [
        _pack_rotation(armature_node_name, source.matrix_world.to_quaternion())
    ]
    for bone in source.data.bones:
        matrix = bone.matrix_local
        if bone.parent:
            matrix = bone.parent.matrix_local.inverted_safe() @ matrix
        rotation_lines.append(_pack_rotation(bone.name, matrix.to_quaternion()))

    facial_lines = []
    if "LeftEye" in names:
        facial_lines.extend(("", "[FacialMap_LEye]", "Bone0 = LeftEye"))
    if "RightEye" in names:
        facial_lines.extend(("", "[FacialMap_REye]", "Bone0 = RightEye"))

    under_head = []
    for bone_name in ("Jaw", "LeftEye", "RightEye"):
        if bone_name in names:
            under_head.append(f"{bone_name} = Facial")

    lines = [
        "[BoneMapOption]",
        "Prefix =",
        "",
        "[BoneMap]",
        *mapping_lines,
        "",
        "[BoneRotate]",
        *rotation_lines,
        "",
        "[RootTransform]",
        "Value = 1.,1.,1.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,",
        *facial_lines,
    ]
    if under_head:
        lines.extend(("", "[BoneTypeOfBonesUnderHead]", *under_head))
    return "\n".join(lines) + "\n"


def _store_context():
    active = bpy.context.view_layer.objects.active
    return {
        "active": active,
        "selected": list(bpy.context.selected_objects),
        "mode": active.mode if active else "OBJECT",
        "frame": bpy.context.scene.frame_current,
        "frame_start": bpy.context.scene.frame_start,
        "frame_end": bpy.context.scene.frame_end,
    }


def _object_mode():
    active = bpy.context.view_layer.objects.active
    if active and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _restore_context(state):
    _object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    for obj in state["selected"]:
        if obj and obj.name in bpy.data.objects:
            try:
                obj.select_set(True)
            except RuntimeError:
                pass
    active = state["active"]
    if active and active.name in bpy.data.objects:
        bpy.context.view_layer.objects.active = active
        if state["mode"] != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode=state["mode"])
            except RuntimeError:
                pass
    scene = bpy.context.scene
    scene.frame_start = state["frame_start"]
    scene.frame_end = state["frame_end"]
    scene.frame_set(state["frame"])


def export_motion(source, filepath, frame_start=None, frame_end=None):
    """Export one active Kimodo Action as FBX plus a matching 3DX profile."""
    state = inspect_source(source)
    if source is None or source.type != "ARMATURE":
        raise ICloneMotionExportError("Choose a Kimodo source armature.")
    if not state["action"]:
        raise ICloneMotionExportError("The Kimodo source has no active Action.")
    if state["missing_required"]:
        raise ICloneMotionExportError(
            "The source is not a complete Kimodo SOMA skeleton. Missing: "
            + ", ".join(state["missing_required"])
        )
    if not hasattr(bpy.types, "EXPORT_SCENE_OT_fbx"):
        raise ICloneMotionExportError(
            "Blender's FBX exporter is unavailable. Enable Import-Export: FBX."
        )

    fbx_path = Path(bpy.path.abspath(filepath)).with_suffix(".fbx")
    fbx_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path = fbx_path.with_suffix(".3dxProfile")
    start = state["frame_start"] if frame_start is None else int(frame_start)
    end = state["frame_end"] if frame_end is None else int(frame_end)
    if start > end:
        raise ICloneMotionExportError("Export start frame must not exceed end frame.")

    context_state = _store_context()
    hide_viewport = source.hide_viewport
    hidden = source.hide_get()
    try:
        _object_mode()
        source.hide_viewport = False
        source.hide_set(False)
        bpy.ops.object.select_all(action="DESELECT")
        source.select_set(True)
        bpy.context.view_layer.objects.active = source
        bpy.context.scene.frame_start = start
        bpy.context.scene.frame_end = end

        result = bpy.ops.export_scene.fbx(
            filepath=os.fspath(fbx_path),
            check_existing=True,
            use_selection=True,
            object_types={'ARMATURE'},
            global_scale=1.0,
            apply_unit_scale=True,
            apply_scale_options='FBX_SCALE_UNITS',
            use_space_transform=True,
            bake_space_transform=False,
            use_armature_deform_only=False,
            add_leaf_bones=False,
            bake_anim=True,
            bake_anim_use_all_bones=True,
            bake_anim_use_nla_strips=False,
            bake_anim_use_all_actions=False,
            bake_anim_force_startend_keying=True,
            bake_anim_step=1.0,
            bake_anim_simplify_factor=0.0,
            path_mode='AUTO',
        )
        if "FINISHED" not in result or not fbx_path.is_file():
            raise ICloneMotionExportError("Blender did not create the FBX motion file.")

        profile_path.write_text(
            build_hik_profile(source, source.name),
            encoding="utf-8",
            newline="\n",
        )
    except ICloneMotionExportError:
        raise
    except Exception as exc:
        raise ICloneMotionExportError(f"iClone motion export failed: {exc}") from exc
    finally:
        source.hide_viewport = hide_viewport
        source.hide_set(hidden)
        _restore_context(context_state)

    return {
        "fbx_path": os.fspath(fbx_path),
        "profile_path": os.fspath(profile_path),
        "source": source.name,
        "action": state["action"],
        "frame_start": start,
        "frame_end": end,
        "mapped_bones": state["mapped_bones"],
        "root_bone": "Root" if state["has_root"] else "Hips",
        "fbx_bytes": fbx_path.stat().st_size,
    }
