"""Blender smoke test for Kimodo -> native CC Data Link retargeting.

Run with Blender 5.1+ and the junctioned add-on enabled::

    blender --factory-startup --background --python tests/blender_iclone_official_send_smoke.py
"""

import importlib
import json
import math

import addon_utils
import bpy
from mathutils import Vector


ADDON = "kimodo_blender_bridge"


def _make_armature(name, bones, scale=1.0):
    data = bpy.data.armatures.new(name + "_Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.scale = (scale, scale, scale)

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    created = {}
    for bone_name, parent_name, head, tail in bones:
        bone = data.edit_bones.new(bone_name)
        bone.head = head
        bone.tail = tail
        if parent_name:
            bone.parent = created[parent_name]
        created[bone_name] = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _make_source():
    source = _make_armature(
        "Official_Source",
        [
            ("Root", None, (0, 0, 0), (0, 0, 1)),
            ("Hips", "Root", (0, 0, 1), (0, 0, 1.2)),
            ("LeftArm", "Hips", (0, 0, 1.2), (0.4, 0, 1.2)),
            ("RightArm", "Hips", (0, 0, 1.2), (-0.4, 0, 1.2)),
        ],
    )
    for pose_bone in source.pose.bones:
        pose_bone.rotation_mode = "XYZ"

    for frame, travel, arm_angle in (
        (1, 0.0, 0.0),
        (2, -1.0, 0.3),
        (3, -2.0, 0.6),
    ):
        hips = source.pose.bones["Hips"]
        hips.location = (0.0, 0.0, travel)
        hips.keyframe_insert("location", frame=frame)
        left_arm = source.pose.bones["LeftArm"]
        left_arm.rotation_euler = (0.0, 0.0, arm_angle)
        left_arm.keyframe_insert("rotation_euler", frame=frame)
        root = source.pose.bones["Root"]
        root.location = (0.0, 0.0, 0.0)
        root.keyframe_insert("location", frame=frame)
        root.keyframe_insert("rotation_euler", frame=frame)

    source.animation_data.action.name = "Official_Source_Action"
    return source


def _make_native_cc_target(
    name="Official_CC_Target", scale=0.01, root_name="CC_Base_BoneRoot"
):
    return _make_armature(
        name,
        [
            (root_name, None, (0, 0, 0), (0, 80, 0)),
            ("CC_Base_Hip", root_name, (0, 0, 80), (0, 0, 100)),
            # Native CC Base uses an A-pose while the Kimodo source above is
            # authored in a T-pose.  This 30-degree mismatch reproduces the
            # arm folding regression from the real Data Link character.
            (
                "CC_Base_L_Upperarm",
                "CC_Base_Hip",
                (0, 0, 110),
                (34.641016, 0, 90),
            ),
            (
                "CC_Base_R_Upperarm",
                "CC_Base_Hip",
                (0, 0, 110),
                (-34.641016, 0, 90),
            ),
        ],
        scale=scale,
    )


def _world_bone_transform(obj, bone_name, frame):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    return obj.matrix_world @ obj.pose.bones[bone_name].matrix


def _bone_y_direction(matrix):
    return (matrix.to_quaternion() @ Vector((0.0, 1.0, 0.0))).normalized()


def _initial_frame_stability(target, root_name):
    previous = {}
    max_rotation_step = 0.0
    max_non_root_location = 0.0
    max_scale_error = 0.0
    negative_quaternion_dots = 0
    for sample in (1.0, 1.5, 2.0, 2.5, 3.0):
        frame = math.floor(sample)
        bpy.context.scene.frame_set(frame, subframe=sample - frame)
        bpy.context.view_layer.update()
        for pose_bone in target.pose.bones:
            rotation = pose_bone.rotation_quaternion.normalized()
            prior = previous.get(pose_bone.name)
            if prior is not None:
                dot = prior.dot(rotation)
                if dot < 0.0:
                    negative_quaternion_dots += 1
                max_rotation_step = max(
                    max_rotation_step,
                    2.0 * math.acos(min(1.0, abs(dot))),
                )
            previous[pose_bone.name] = rotation.copy()
            if pose_bone.name != root_name:
                max_non_root_location = max(
                    max_non_root_location,
                    pose_bone.location.length,
                )
            max_scale_error = max(
                max_scale_error,
                max(abs(value - 1.0) for value in pose_bone.scale),
            )

    assert negative_quaternion_dots == 0, negative_quaternion_dots
    assert max_rotation_step < math.radians(45.0), math.degrees(max_rotation_step)
    assert max_non_root_location < 1e-4, max_non_root_location
    assert max_scale_error < 1e-6, max_scale_error
    return {
        "max_rotation_step_degrees": math.degrees(max_rotation_step),
        "max_non_root_location": max_non_root_location,
        "negative_quaternion_dots": negative_quaternion_dots,
    }


def main():
    addon_utils.enable(ADDON, default_set=False, persistent=False)
    official = importlib.import_module(ADDON + ".iclone_official_send")

    source = _make_source()
    target = _make_native_cc_target()
    assert "RL_BoneRoot" not in target.pose.bones
    assert official._is_cc_armature(target)
    assert official._target_root_bone(target) == "CC_Base_BoneRoot"

    source_start = _world_bone_transform(source, "Hips", 1)
    source_end = _world_bone_transform(source, "Hips", 3)
    source_travel = (source_end.translation - source_start.translation).length
    source_arm_rest = (
        source.matrix_world.to_quaternion()
        @ source.data.bones["LeftArm"].matrix_local.to_quaternion()
    ).normalized()
    target_arm_rest = (
        target.matrix_world.to_quaternion()
        @ target.data.bones["CC_Base_L_Upperarm"].matrix_local.to_quaternion()
    ).normalized()
    rest_pose_arm_delta = (
        (source_arm_rest @ Vector((0.0, 1.0, 0.0))).angle(
            target_arm_rest @ Vector((0.0, 1.0, 0.0))
        )
    )
    assert rest_pose_arm_delta > math.radians(25.0), rest_pose_arm_delta

    result = official.retarget_action(source, target)
    initial_stability = _initial_frame_stability(
        target, result["root_bone"]
    )
    target_start = _world_bone_transform(target, "CC_Base_BoneRoot", 1)
    target_arm_start = _world_bone_transform(target, "CC_Base_L_Upperarm", 1)
    target_end = _world_bone_transform(target, "CC_Base_BoneRoot", 3)
    target_arm_end = _world_bone_transform(target, "CC_Base_L_Upperarm", 3)
    target_travel = (target_end.translation - target_start.translation).length
    arm_change = target_arm_start.to_quaternion().rotation_difference(
        target_arm_end.to_quaternion()
    ).angle
    source_arm_start = _world_bone_transform(source, "LeftArm", 1)
    arm_direction_error = _bone_y_direction(source_arm_start).angle(
        _bone_y_direction(target_arm_start)
    )

    assert result["root_bone"] == "CC_Base_BoneRoot", result
    assert result["source_frames"] == 3, result
    assert target.animation_data.action.name.startswith("Official_Source_Action_CC")
    assert math.isclose(target_travel, source_travel, rel_tol=1e-5, abs_tol=1e-5), (
        source_travel,
        target_travel,
    )
    assert arm_change > 0.5, arm_change
    assert arm_direction_error < math.radians(0.01), math.degrees(
        arm_direction_error
    )

    # Re-baking the same target used to retain evaluated channels from the
    # previous Action and amplify the first few frames into a stretched rig.
    repeated_result = official.retarget_action(source, target)
    repeated_stability = _initial_frame_stability(
        target, repeated_result["root_bone"]
    )

    # Reallusion's successful import processing applies the FBX object's 0.01
    # scale, but keeps the CC bone coordinate system in centimeters.  Data Link
    # sends those non-rigified bone translations unchanged, so 2 source meters
    # must become 200 target coordinate units.
    processed_target = _make_native_cc_target(
        name="Official_CC_Processed_Target", scale=1.0
    )
    processed_result = official.retarget_action(source, processed_target)
    processed_start = _world_bone_transform(
        processed_target, "CC_Base_BoneRoot", 1
    )
    processed_end = _world_bone_transform(
        processed_target, "CC_Base_BoneRoot", 3
    )
    processed_travel_cm = (
        processed_end.translation - processed_start.translation
    ).length
    assert processed_result["root_bone"] == "CC_Base_BoneRoot", processed_result
    assert math.isclose(
        processed_travel_cm,
        source_travel * official.METERS_TO_CENTIMETERS,
        rel_tol=1e-5,
        abs_tol=1e-5,
    ), (source_travel, processed_travel_cm)

    alias_target = _make_native_cc_target(
        name="Official_RL_Alias_Target",
        scale=0.01,
        root_name="RL_BoneRoot",
    )
    alias_result = official.retarget_action(source, alias_target)
    alias_start = _world_bone_transform(alias_target, "RL_BoneRoot", 1)
    alias_end = _world_bone_transform(alias_target, "RL_BoneRoot", 3)
    alias_travel = (alias_end.translation - alias_start.translation).length
    assert alias_result["root_bone"] == "RL_BoneRoot", alias_result
    assert math.isclose(
        alias_travel, source_travel, rel_tol=1e-5, abs_tol=1e-5
    ), (source_travel, alias_travel)

    class _StandardCharacterCache:
        rigified = False

    processed_target.location = (12.0, -34.0, 56.0)
    processed_target.rotation_euler = (
        math.radians(-90.0),
        math.radians(3.0),
        math.radians(2.0),
    )
    processed_target.scale = (1.0, 1.0, 1.0)
    official._normalize_data_link_target(processed_target, _StandardCharacterCache())
    assert processed_target.location.length < 1e-8
    assert processed_target.matrix_world.to_quaternion().angle < 1e-8
    assert all(
        math.isclose(value, official.DATA_LINK_TARGET_SCALE, abs_tol=1e-8)
        for value in processed_target.scale
    )

    class _CharacterCache:
        link_id = "EXACT_ICLONE_LINK_ID"

        @staticmethod
        def get_armature():
            return processed_target

    class _Props:
        def get_character_cache(self, obj, _material):
            return _CharacterCache() if obj == processed_target else None

    class _Vars:
        @staticmethod
        def props():
            return _Props()

    original_modules = official._official_modules
    try:
        official._official_modules = lambda: (None, _Vars(), None)
        assert official.find_registered_target(
            source, "EXACT_ICLONE_LINK_ID", processed_target
        ) == processed_target
        assert official.find_registered_target(
            source, "WRONG_LINK_ID", processed_target
        ) is None
    finally:
        official._official_modules = original_modules

    payload = {
        "blender": bpy.app.version_string,
        "root_bone": result["root_bone"],
        "mapped_bones": result["mapped_bones"],
        "source_travel_m": source_travel,
        "target_travel_m": target_travel,
        "processed_target_travel_cm": processed_travel_cm,
        "rl_alias_target_travel_m": alias_travel,
        "registered_target_reused": True,
        "normalized_target_scale": list(processed_target.scale),
        "arm_change_degrees": math.degrees(arm_change),
        "arm_rest_pose_delta_degrees": math.degrees(rest_pose_arm_delta),
        "arm_direction_error_degrees": math.degrees(arm_direction_error),
        "initial_stability": initial_stability,
        "repeated_stability": repeated_stability,
        "action": target.animation_data.action.name,
    }
    print("KIMODO_ICLONE_OFFICIAL_SMOKE=" + json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
