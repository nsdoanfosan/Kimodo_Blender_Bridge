"""Blender background smoke test for Kimodo's built-in retarget profiles.

Run with a blend file containing a Kimodo SOMA v1.1 armature, for example:

    blender --background motion.blend --python tests/blender_retarget_smoke.py
"""

import importlib
import json

import addon_utils
import bpy
from mathutils import Matrix


ADDON = "kimodo_blender_bridge"


def _matrix_delta(first, second):
    return max(
        abs(first[row][column] - second[row][column])
        for row in range(4)
        for column in range(4)
    )


def _create_target(name, bone_names, offset):
    armature_data = bpy.data.armatures.new(name + "_Data")
    armature = bpy.data.objects.new(name, armature_data)
    bpy.context.scene.collection.objects.link(armature)
    armature.matrix_world = Matrix.Translation(offset)

    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for index, bone_name in enumerate(sorted(bone_names)):
        bone = armature_data.edit_bones.new(bone_name)
        x = (index % 8) * 0.04
        z = (index // 8) * 0.12
        bone.head = (x, 0.0, z)
        bone.tail = (x, 0.08, z + 0.04)
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    return armature


def _run_profile(source, presets, retarget, profile_id, name, offset, bake=False):
    profile = presets.PROFILES[profile_id]
    target_names = {item["tgt"] for item in profile["mappings"]}
    target_names.update(profile["markers"])
    target = _create_target(name, target_names, offset)
    preserved_constraint = None
    if bake:
        preserved_bone = target.pose.bones.get("spine_05") or target.pose.bones[0]
        preserved_constraint = preserved_bone.constraints.new("LIMIT_ROTATION")
        preserved_constraint.name = "USER_KEEP_ME"

    settings = bpy.context.scene.kimodo
    settings.source_armature = source
    settings.target_armature = target
    settings.retarget_profile = profile_id
    map_result = bpy.ops.kimodo.auto_map_bones()

    before = {
        bone.name: (target.matrix_world @ bone.matrix).copy()
        for bone in target.pose.bones
    }
    apply_result = bpy.ops.kimodo.apply_retargeting()
    bpy.context.view_layer.update()
    after = {
        bone.name: (target.matrix_world @ bone.matrix).copy()
        for bone in target.pose.bones
    }
    deltas = {name: _matrix_delta(before[name], after[name]) for name in before}
    translation_deltas = {
        name: (before[name].translation - after[name].translation).length
        for name in before
    }
    worst_bone = max(deltas, key=deltas.get)
    rest_delta = deltas[worst_bone]
    worst_constraint = next(
        constraint
        for constraint in target.pose.bones[worst_bone].constraints
        if constraint.name.startswith(retarget.CONSTRAINT_PREFIX)
    )
    inverse_translation = (
        list(worst_constraint.inverse_matrix.translation)
        if hasattr(worst_constraint, "inverse_matrix")
        else None
    )
    inverse_pending = getattr(worst_constraint, "set_inverse_pending", None)
    constraint_count = sum(
        1
        for bone in target.pose.bones
        for constraint in bone.constraints
        if constraint.name.startswith(retarget.CONSTRAINT_PREFIX)
    )

    source_matrix = source.matrix_world.copy()
    root_name = settings.retarget_root_bone
    driven_before = (target.matrix_world @ target.pose.bones[root_name].matrix).copy()
    source.matrix_world = Matrix.Translation((0.25, 0.0, 0.0)) @ source.matrix_world
    bpy.context.view_layer.update()
    driven_after = target.matrix_world @ target.pose.bones[root_name].matrix
    driven_delta = _matrix_delta(driven_before, driven_after)
    source.matrix_world = source_matrix
    bpy.context.view_layer.update()

    target_head_name = next(
        item.target_bone
        for item in settings.bone_mappings
        if item.source_bone == "Head"
    )
    source_head = source.pose.bones["Head"]
    source_head_basis = source_head.matrix_basis.copy()
    head_before = target.pose.bones[target_head_name].matrix.to_quaternion()
    source_head.matrix_basis = (
        source_head.matrix_basis @ Matrix.Rotation(0.2, 4, "Z")
    )
    bpy.context.view_layer.update()
    head_after = target.pose.bones[target_head_name].matrix.to_quaternion()
    rotation_driven_angle = head_before.rotation_difference(head_after).angle
    source_head.matrix_basis = source_head_basis
    bpy.context.view_layer.update()

    baked = None
    remaining_constraints = constraint_count
    if bake:
        settings.bake_start_frame = 1
        settings.bake_end_frame = 3
        baked = sorted(bpy.ops.kimodo.bake_retargeting())
        remaining_constraints = sum(
            1
            for bone in target.pose.bones
            for constraint in bone.constraints
            if constraint.name.startswith(retarget.CONSTRAINT_PREFIX)
        )
    else:
        retarget.remove_retargeting_constraints(target)

    user_constraint_preserved = (
        preserved_constraint is None
        or any(
            constraint.name == "USER_KEEP_ME"
            for bone in target.pose.bones
            for constraint in bone.constraints
        )
    )

    root_mode = next(
        item.retarget_mode
        for item in settings.bone_mappings
        if item.source_bone == "Root"
    )
    return {
        "map_result": sorted(map_result),
        "apply_result": sorted(apply_result),
        "mapping_count": len(settings.bone_mappings),
        "root": root_name,
        "root_mode": root_mode,
        "constraint_count": constraint_count,
        "rest_max_delta": rest_delta,
        "translation_max_delta": max(translation_deltas.values()),
        "rest_worst_bone": worst_bone,
        "rest_before_translation": list(before[worst_bone].translation),
        "rest_after_translation": list(after[worst_bone].translation),
        "inverse_translation": inverse_translation,
        "inverse_pending": inverse_pending,
        "driven_delta": driven_delta,
        "rotation_driven_angle": rotation_driven_angle,
        "bake_result": baked,
        "remaining_constraints": remaining_constraints,
        "has_baked_action": target.animation_data is not None
        and target.animation_data.action is not None,
        "user_constraint_preserved": user_constraint_preserved,
    }


def main():
    addon_utils.enable(ADDON, default_set=False, persistent=False)
    presets = importlib.import_module(ADDON + ".retarget_presets")
    retarget = importlib.import_module(ADDON + ".retarget")

    source = bpy.data.objects.get("Kimodo_Source")
    if source is None:
        source = next((obj for obj in bpy.data.objects if obj.type == "ARMATURE"), None)
    if source is None:
        raise AssertionError("A Kimodo source armature is required")

    ue5 = _run_profile(
        source,
        presets,
        retarget,
        presets.PROFILE_UNREAL_UE5,
        "Smoke_UE5",
        (3.0, 1.0, 0.0),
        bake=True,
    )
    cc = _run_profile(
        source,
        presets,
        retarget,
        presets.PROFILE_REALLUSION_CC,
        "Smoke_CC",
        (-3.0, 1.0, 0.0),
    )

    payload = {
        "blender": bpy.app.version_string,
        "source": source.name,
        "source_bones": len(source.data.bones),
        "ue5": ue5,
        "cc": cc,
    }
    print("KIMODO_RETARGET_DIAGNOSTIC=" + json.dumps(payload, sort_keys=True))

    assert ue5["mapping_count"] == 62
    assert cc["mapping_count"] == 57
    assert ue5["root"] == "root"
    assert cc["root"] == "CC_Base_BoneRoot"
    assert ue5["root_mode"] == presets.MODE_ROOT
    assert cc["root_mode"] == presets.MODE_ROOT
    assert ue5["constraint_count"] == 62
    assert cc["constraint_count"] == 57
    assert ue5["translation_max_delta"] < 1e-5
    assert cc["translation_max_delta"] < 1e-5
    assert ue5["driven_delta"] > 0.1
    assert cc["driven_delta"] > 0.1
    assert ue5["rotation_driven_angle"] > 0.1
    assert cc["rotation_driven_angle"] > 0.1
    assert ue5["bake_result"] == ["FINISHED"]
    assert ue5["remaining_constraints"] == 0
    assert ue5["has_baked_action"]
    assert ue5["user_constraint_preserved"]

    print("KIMODO_RETARGET_SMOKE=" + json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
