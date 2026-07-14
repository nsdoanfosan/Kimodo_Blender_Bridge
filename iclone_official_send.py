"""Retarget Kimodo motion onto an imported CC rig and use Reallusion Data Link."""

from __future__ import annotations

import importlib

import bpy
from mathutils import Matrix

from . import retarget_presets


class ICloneOfficialSendError(RuntimeError):
    pass


def _official_modules():
    addon_key = next(
        (
            key for key in bpy.context.preferences.addons.keys()
            if key.startswith("cc_blender_tools")
        ),
        None,
    )
    if not addon_key:
        raise ICloneOfficialSendError("Reallusion Blender Auto Setup 2.4.0 is not enabled")
    try:
        return (
            importlib.import_module(addon_key + ".link"),
            importlib.import_module(addon_key + ".vars"),
            importlib.import_module(addon_key + ".kimodo_integration"),
        )
    except Exception as exc:
        raise ICloneOfficialSendError("Reallusion Data Link modules could not be loaded") from exc


def _is_cc_armature(obj):
    return bool(
        obj
        and obj.type == "ARMATURE"
        and {"RL_BoneRoot", "CC_Base_Hip", "CC_Base_L_Upperarm", "CC_Base_R_Upperarm"}
        <= set(obj.data.bones.keys())
    )


def find_cc_target(source, preferred=None):
    if preferred is not source and _is_cc_armature(preferred):
        return preferred
    candidates = [
        obj for obj in bpy.context.scene.objects
        if obj is not source and _is_cc_armature(obj)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ICloneOfficialSendError(
            "Import the selected iClone character with Reallusion Data Link first"
        )
    raise ICloneOfficialSendError("Choose the imported CC armature as Target")


def find_available_target(source, preferred=None):
    """Find a reusable CC target without requiring a manual import first."""
    if preferred is not source and _is_cc_armature(preferred):
        return preferred
    candidates = [
        obj for obj in bpy.context.scene.objects
        if obj is not source and _is_cc_armature(obj)
    ]
    return candidates[0] if len(candidates) == 1 else None


def begin_one_click_session():
    """Start Data Link and clear any previous automatic target request."""
    _link, _vars_module, integration = _official_modules()
    integration.reset_request()
    integration.start_link()


def is_link_connected():
    _link, _vars_module, integration = _official_modules()
    return integration.is_connected()


def request_selected_iclone_target():
    _link, _vars_module, integration = _official_modules()
    integration.request_selected_avatar()


def requested_target_state():
    _link, _vars_module, integration = _official_modules()
    state = integration.request_state()
    state["target"] = integration.find_requested_target()
    return state


def _mapping(source, target):
    profile = retarget_presets.PROFILES[retarget_presets.PROFILE_REALLUSION_CC]
    result = {}
    for item in profile["mappings"]:
        if item["src"] in {"Jaw", "LeftEye", "RightEye"}:
            continue
        target_name = "RL_BoneRoot" if item["src"] == "Root" else item["tgt"]
        if item["src"] in source.pose.bones and target_name in target.pose.bones:
            result[target_name] = item["src"]
    if not result or "RL_BoneRoot" not in result:
        raise ICloneOfficialSendError("The source/target skeleton mapping is incomplete")
    return result


def _hierarchy_order(armature):
    order = []
    pending = set(armature.data.bones.keys())
    while pending:
        progressed = False
        for name in list(pending):
            parent = armature.data.bones[name].parent
            if parent and parent.name not in order:
                continue
            order.append(name)
            pending.remove(name)
            progressed = True
        if not progressed:
            raise ICloneOfficialSendError("The CC armature contains a parent cycle")
    return order


def retarget_action(source, target):
    if not source or source.type != "ARMATURE":
        raise ICloneOfficialSendError("Choose the animated Kimodo source armature")
    if not source.animation_data or not source.animation_data.action:
        raise ICloneOfficialSendError("The Kimodo source has no active Action")

    mapping = _mapping(source, target)
    source_action = source.animation_data.action
    start = int(round(source_action.frame_range[0]))
    end = int(round(source_action.frame_range[1]))
    if end <= start:
        raise ICloneOfficialSendError("The Kimodo Action has no usable frame range")

    scene = bpy.context.scene
    action = bpy.data.actions.new(source_action.name + "_CC")
    if target.animation_data is None:
        target.animation_data_create()
    target.animation_data.action = action
    for pose_bone in target.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"

    hierarchy = _hierarchy_order(target)
    source_object_rotation = source.matrix_world.to_quaternion()
    target_object_rotation = target.matrix_world.to_quaternion()
    target_world_inverse = target.matrix_world.inverted_safe().to_3x3()
    target_rest_world = {
        name: (target_object_rotation @ target.data.bones[name].matrix_local.to_quaternion()).normalized()
        for name in mapping
    }
    source_rest_world = {
        source_name: (
            source_object_rotation @ source.data.bones[source_name].matrix_local.to_quaternion()
        ).normalized()
        for source_name in mapping.values()
    }

    hips_origin = None
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        hips_world = source.matrix_world @ source.pose.bones["Hips"].matrix.translation
        if hips_origin is None:
            hips_origin = hips_world.copy()
        root_delta = target_world_inverse @ (hips_world - hips_origin)

        desired = {}
        for name in hierarchy:
            data_bone = target.data.bones[name]
            if data_bone.parent:
                rest_local = data_bone.parent.matrix_local.inverted_safe() @ data_bone.matrix_local
                matrix = desired[data_bone.parent.name] @ rest_local
            else:
                matrix = data_bone.matrix_local.copy()

            source_name = mapping.get(name)
            if source_name:
                source_pose_world = (
                    source_object_rotation @ source.pose.bones[source_name].matrix.to_quaternion()
                ).normalized()
                target_pose_world = (
                    source_pose_world
                    @ source_rest_world[source_name].inverted()
                    @ target_rest_world[name]
                ).normalized()
                target_pose_local = (
                    target_object_rotation.inverted() @ target_pose_world
                ).normalized()
                location, _rotation, scale = matrix.decompose()
                if name == "RL_BoneRoot":
                    location += root_delta
                matrix = Matrix.LocRotScale(location, target_pose_local, scale)
            desired[name] = matrix

        for name, matrix in desired.items():
            target.pose.bones[name].matrix = matrix
        bpy.context.view_layer.update()
        for name in mapping:
            pose_bone = target.pose.bones[name]
            pose_bone.keyframe_insert("location", frame=frame, group=name)
            pose_bone.keyframe_insert("rotation_quaternion", frame=frame, group=name)
            pose_bone.keyframe_insert("scale", frame=frame, group=name)

    scene.render.fps = 30
    scene.render.fps_base = 1.0
    scene.frame_start = start
    scene.frame_end = end
    scene.frame_set(start)
    bpy.context.view_layer.update()
    return {
        "action": action.name,
        "source_frames": end - start + 1,
        "mapped_bones": len(mapping),
        "start_frame": start,
        "end_frame": end,
    }


def send_motion(source, preferred_target=None):
    link, vars_module, _integration = _official_modules()
    service = link.LINK_SERVICE
    if not service or not service.is_connected:
        raise ICloneOfficialSendError("Start Reallusion Data Link in iClone and Blender")

    target = find_cc_target(source, preferred_target)
    result = retarget_action(source, target)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    operator_result = bpy.ops.ccic.datalink(param="SEND_ANIM")
    if "FINISHED" not in operator_result:
        raise ICloneOfficialSendError("Reallusion Data Link rejected the animation request")
    result.update({
        "target": target.name,
        "status": vars_module.link_props().link_status,
    })
    return result
