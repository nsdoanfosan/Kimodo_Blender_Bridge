"""Blender 5.x smoke test for disposable Kimodo PoseRef controls.

Run with:

    blender --factory-startup --background --python tests/blender_pose_control_smoke.py
"""

import json

import addon_utils
import bpy
from mathutils import Vector


ADDON = "kimodo_blender_bridge"
TOLERANCE = 2.0e-4


def _matrix_delta(left, right):
    return max(
        abs(left[row][column] - right[row][column])
        for row in range(4)
        for column in range(4)
    )


def _evaluated_pose(obj, names):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return {name: evaluated.pose.bones[name].matrix.copy() for name in names}


def _max_delta(obj, expected):
    actual = _evaluated_pose(obj, expected.keys())
    return max(
        (_matrix_delta(actual[name], matrix) for name, matrix in expected.items()),
        default=0.0,
    )


def _new_bone(armature, name, head, tail, parent=None):
    bone = armature.edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = False
    return bone


def _new_finger(armature, side, finger, segment_count, hand, direction, y_offset):
    parent = hand
    start = Vector(hand.tail) + Vector((0.0, y_offset, 0.0))
    for index in range(1, segment_count + 1):
        end = start + Vector((direction * 0.035, 0.0, 0.0))
        parent = _new_bone(
            armature, f"{side}Hand{finger}{index}", start, end, parent)
        start = end
    end = start + Vector((direction * 0.025, 0.0, 0.0))
    _new_bone(armature, f"{side}Hand{finger}End", start, end, parent)


def _create_pose_reference(scene):
    data = bpy.data.armatures.new("Kimodo_Test_PoseRef_Data")
    obj = bpy.data.objects.new("Kimodo_Test_PoseRef", data)
    scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    root = _new_bone(data, "Root", (0, 0, 0), (0, 0, 0.15))
    hips = _new_bone(data, "Hips", (0, 0, 1.0), (0, 0, 1.15), root)
    spine1 = _new_bone(data, "Spine1", hips.tail, (0, 0, 1.30), hips)
    spine2 = _new_bone(data, "Spine2", spine1.tail, (0, 0, 1.45), spine1)
    chest = _new_bone(data, "Chest", spine2.tail, (0, 0, 1.62), spine2)
    neck1 = _new_bone(data, "Neck1", chest.tail, (0, 0, 1.70), chest)
    neck2 = _new_bone(data, "Neck2", neck1.tail, (0, 0, 1.77), neck1)
    head = _new_bone(data, "Head", neck2.tail, (0, 0, 1.98), neck2)
    _new_bone(data, "HeadEnd", head.tail, (0, 0, 2.08), head)
    _new_bone(data, "Jaw", (0, -0.03, 1.88), (0, -0.10, 1.82), head)
    _new_bone(data, "LeftEye", (0.035, -0.04, 1.94), (0.035, -0.10, 1.94), head)
    _new_bone(data, "RightEye", (-0.035, -0.04, 1.94), (-0.035, -0.10, 1.94), head)

    left_shoulder = _new_bone(data, "LeftShoulder", chest.tail, (0.15, 0, 1.62), chest)
    left_arm = _new_bone(data, "LeftArm", left_shoulder.tail, (0.45, 0, 1.62), left_shoulder)
    left_forearm = _new_bone(data, "LeftForeArm", left_arm.tail, (0.74, 0, 1.62), left_arm)
    left_hand = _new_bone(
        data, "LeftHand", left_forearm.tail, (0.87, 0, 1.62), left_forearm)
    for finger, count, offset in (
        ("Thumb", 3, -0.055), ("Index", 4, -0.025),
        ("Middle", 4, 0.0), ("Ring", 4, 0.025), ("Pinky", 4, 0.05),
    ):
        _new_finger(data, "Left", finger, count, left_hand, 1.0, offset)

    right_shoulder = _new_bone(data, "RightShoulder", chest.tail, (-0.15, 0, 1.62), chest)
    right_arm = _new_bone(data, "RightArm", right_shoulder.tail, (-0.45, 0, 1.62), right_shoulder)
    right_forearm = _new_bone(data, "RightForeArm", right_arm.tail, (-0.74, 0, 1.62), right_arm)
    right_hand = _new_bone(
        data, "RightHand", right_forearm.tail, (-0.87, 0, 1.62), right_forearm)
    for finger, count, offset in (
        ("Thumb", 3, -0.055), ("Index", 4, -0.025),
        ("Middle", 4, 0.0), ("Ring", 4, 0.025), ("Pinky", 4, 0.05),
    ):
        _new_finger(data, "Right", finger, count, right_hand, -1.0, offset)

    left_leg = _new_bone(data, "LeftLeg", (0.10, 0, 1.0), (0.10, 0, 0.56), hips)
    left_shin = _new_bone(data, "LeftShin", left_leg.tail, (0.10, 0, 0.13), left_leg)
    left_foot = _new_bone(
        data, "LeftFoot", left_shin.tail, (0.10, -0.24, 0.08), left_shin)
    left_toe = _new_bone(
        data, "LeftToeBase", left_foot.tail, (0.10, -0.34, 0.06), left_foot)
    _new_bone(data, "LeftToeEnd", left_toe.tail, (0.10, -0.40, 0.06), left_toe)

    right_leg = _new_bone(data, "RightLeg", (-0.10, 0, 1.0), (-0.10, 0, 0.56), hips)
    right_shin = _new_bone(data, "RightShin", right_leg.tail, (-0.10, 0, 0.13), right_leg)
    right_foot = _new_bone(
        data, "RightFoot", right_shin.tail, (-0.10, -0.24, 0.08), right_shin)
    right_toe = _new_bone(
        data, "RightToeBase", right_foot.tail, (-0.10, -0.34, 0.06), right_foot)
    _new_bone(data, "RightToeEnd", right_toe.tail, (-0.10, -0.40, 0.06), right_toe)

    bpy.ops.object.mode_set(mode='POSE')
    rotations = {
        "Hips": (0.06, -0.04, 0.08),
        "Spine1": (-0.05, 0.03, -0.04),
        "Chest": (0.08, 0.05, 0.06),
        "Head": (-0.04, 0.08, -0.05),
        "LeftArm": (0.18, -0.12, 0.28),
        "LeftForeArm": (0.05, 0.18, -0.65),
        "RightArm": (-0.16, 0.10, -0.24),
        "RightForeArm": (-0.04, -0.15, 0.58),
        "LeftLeg": (0.08, -0.05, 0.06),
        "LeftShin": (0.30, 0.02, -0.03),
        "RightLeg": (-0.06, 0.04, -0.05),
        "RightShin": (0.25, -0.02, 0.04),
        "LeftHandIndex1": (0.02, -0.05, 0.10),
        "LeftHandIndex2": (0.01, -0.03, 0.08),
        "RightHandPinky1": (-0.02, 0.04, -0.09),
        "RightHandPinky2": (-0.01, 0.03, -0.07),
    }
    for name, values in rotations.items():
        pose_bone = obj.pose.bones[name]
        pose_bone.rotation_mode = 'XYZ'
        pose_bone.rotation_euler = values

    bpy.ops.object.mode_set(mode='OBJECT')
    obj["kimodo_constraint"] = True
    obj["kimodo_type"] = "fullbody"
    obj.show_in_front = False
    bpy.context.view_layer.update()
    return obj


def main():
    addon_utils.enable(ADDON, default_set=False, persistent=False)
    from kimodo_blender_bridge import constraints, panels, pose_control

    scene = bpy.context.scene
    obj = _create_pose_reference(scene)
    original_names = [
        bone.name for bone in obj.data.bones
        if not bone.name.startswith(pose_control.CONTROL_PREFIX)
    ]
    assert len(original_names) == 78, len(original_names)
    before = _evaluated_pose(obj, original_names)

    build_result = sorted(bpy.ops.kimodo.build_pose_controls(target_name=obj.name))
    assert build_result == ["FINISHED"]
    assert obj.get(pose_control.VERSION_KEY) == pose_control.CONTROL_VERSION
    assert all(name in obj.pose.bones for name, _, _ in pose_control.CONTROL_LABELS)
    assert pose_control.CTRL_ELBOW_L in obj.pose.bones
    assert pose_control.CTRL_KNEE_R in obj.pose.bones
    hidden_failures = [name for name in original_names if not obj.data.bones[name].hide]
    assert not hidden_failures, hidden_failures
    assert not obj.data.bones[pose_control.CTRL_HIPS].hide
    assert all(obj.pose.bones[name].lock_location[:] == (True, True, True)
               for name in original_names)
    assert not panels._is_dynamic_pose_reference(obj)

    build_delta = _max_delta(obj, before)
    assert build_delta <= TOLERANCE, build_delta

    left_hand_before = obj.pose.bones["LeftHand"].head.copy()
    controller = obj.pose.bones[pose_control.CTRL_HAND_L]
    controller.location += Vector((0.12, -0.06, 0.10))
    controller.rotation_mode = 'XYZ'
    controller.rotation_euler.z += 0.25
    controller.keyframe_insert(data_path="location", frame=1)
    bpy.context.view_layer.update()
    left_hand_after = obj.pose.bones["LeftHand"].head.copy()
    assert (left_hand_after - left_hand_before).length > 0.03
    assert (obj.pose.bones["LeftForeArm"].tail - obj.pose.bones["LeftHand"].head).length < 1.0e-5
    assert obj.animation_data and obj.animation_data.action
    assert panels._is_dynamic_pose_reference(obj)

    toggled = sorted(bpy.ops.kimodo.toggle_pose_source_bones(target_name=obj.name))
    assert toggled == ["FINISHED"]
    assert not obj.data.bones["Hips"].hide

    baked_expected = _evaluated_pose(obj, original_names)
    bake_result = sorted(bpy.ops.kimodo.finish_pose_controls(
        target_name=obj.name, mode='BAKE'))
    assert bake_result == ["FINISHED"]
    assert not any(bone.name.startswith(pose_control.CONTROL_PREFIX) for bone in obj.data.bones)
    assert not any(
        constraint.name.startswith(pose_control.CONSTRAINT_PREFIX)
        for bone in obj.pose.bones for constraint in bone.constraints
    )
    assert pose_control.VERSION_KEY not in obj
    assert pose_control.MANIFEST_KEY not in obj
    assert obj.animation_data is None or obj.animation_data.action is None
    assert bpy.data.collections.get(pose_control.WIDGET_COLLECTION) is None
    assert not panels._is_dynamic_pose_reference(obj)
    bake_delta = _max_delta(obj, baked_expected)
    assert bake_delta <= TOLERANCE, bake_delta
    assert obj.show_in_front is False
    assert all(obj.pose.bones[name].lock_location[:] == (False, False, False)
               for name in original_names)

    # A second control session can be cancelled back to its own starting pose.
    baseline = _evaluated_pose(obj, original_names)
    rebuild_result = sorted(bpy.ops.kimodo.build_pose_controls(target_name=obj.name))
    assert rebuild_result == ["FINISHED"]
    obj.pose.bones[pose_control.CTRL_HAND_R].location += Vector((-0.15, 0.08, 0.06))
    obj.pose.bones[pose_control.CTRL_HIPS].rotation_mode = 'XYZ'
    obj.pose.bones[pose_control.CTRL_HIPS].rotation_euler.y += 0.2
    bpy.context.view_layer.update()
    assert _max_delta(obj, baseline) > 0.02
    revert_result = sorted(bpy.ops.kimodo.finish_pose_controls(
        target_name=obj.name, mode='REVERT'))
    assert revert_result == ["FINISHED"]
    revert_delta = _max_delta(obj, baseline)
    assert revert_delta <= TOLERANCE, revert_delta

    joint_rots = constraints.get_armature_joint_rots(obj, constraints.SOMA_JOINT_ORDER)
    assert len(joint_rots) == len(constraints.SOMA_JOINT_ORDER)

    payload = {
        "blender": bpy.app.version_string,
        "build_result": build_result,
        "build_delta": build_delta,
        "hand_move": (left_hand_after - left_hand_before).length,
        "bake_result": bake_result,
        "bake_delta": bake_delta,
        "rebuild_result": rebuild_result,
        "revert_result": revert_result,
        "revert_delta": revert_delta,
        "joint_count": len(joint_rots),
        "original_bone_count": len(original_names),
    }
    print("KIMODO_POSE_CONTROL_SMOKE=" + json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
