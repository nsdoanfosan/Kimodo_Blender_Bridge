"""Blender background regression test for frozen Full-Body pose references.

Run with:

    blender --factory-startup --background --python tests/blender_fullbody_constraint_smoke.py
"""

import importlib
import json

import addon_utils
import bpy


ADDON = "kimodo_blender_bridge"
TOLERANCE = 1.0e-5


def _matrix_delta(left, right):
    return max(
        abs(left[row][column] - right[row][column])
        for row in range(4)
        for column in range(4)
    )


def _pose_snapshot(obj):
    return {
        bone.name: bone.matrix.copy()
        for bone in obj.pose.bones
    }


def _max_pose_delta(obj, expected):
    return max(
        (_matrix_delta(obj.pose.bones[name].matrix, matrix)
         for name, matrix in expected.items()),
        default=0.0,
    )


def _animation_counts(owner):
    animation = owner.animation_data
    if animation is None:
        return {"action": 0, "nla": 0, "drivers": 0}
    return {
        "action": int(animation.action is not None),
        "nla": len(animation.nla_tracks),
        "drivers": len(animation.drivers),
    }


def _create_animated_armature(scene):
    armature_data = bpy.data.armatures.new("FullBody_Source_Data")
    source = bpy.data.objects.new("FullBody_Source", armature_data)
    scene.collection.objects.link(source)

    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    hips = armature_data.edit_bones.new("Hips")
    hips.head = (0.0, 0.0, 0.0)
    hips.tail = (0.0, 0.0, 1.0)

    spine = armature_data.edit_bones.new("Spine1")
    spine.head = hips.tail
    spine.tail = (0.0, 0.0, 1.8)
    spine.parent = hips

    arm = armature_data.edit_bones.new("LeftArm")
    arm.head = spine.tail
    arm.tail = (0.8, 0.0, 1.8)
    arm.parent = spine

    bpy.ops.object.mode_set(mode="OBJECT")

    parent = bpy.data.objects.new("Animated_Source_Parent", None)
    scene.collection.objects.link(parent)
    parent.location = (0.25, -0.5, 0.1)
    source.parent = parent
    source.matrix_parent_inverse = parent.matrix_world.inverted()

    target = bpy.data.objects.new("Animated_Constraint_Target", None)
    scene.collection.objects.link(target)
    target.location = (0.15, 0.2, 0.05)

    object_constraint = source.constraints.new("COPY_LOCATION")
    object_constraint.target = target
    object_constraint.use_offset = True

    pose_constraint = source.pose.bones["LeftArm"].constraints.new("COPY_ROTATION")
    pose_constraint.target = target

    for frame, location in ((1, (0.0, 0.0, 0.0)),
                            (10, (1.0, -0.25, 0.5)),
                            (20, (2.0, 0.5, 0.25))):
        source.location = location
        source.keyframe_insert(data_path="location", frame=frame)

    hips_pose = source.pose.bones["Hips"]
    hips_pose.rotation_mode = "XYZ"
    arm_pose = source.pose.bones["LeftArm"]
    arm_pose.rotation_mode = "XYZ"
    for frame, hips_x, arm_z in ((1, 0.0, -0.2),
                                 (10, 0.35, 0.65),
                                 (20, -0.25, 1.1)):
        hips_pose.rotation_euler.x = hips_x
        hips_pose.keyframe_insert(data_path="rotation_euler", frame=frame)
        arm_pose.rotation_euler.z = arm_z
        arm_pose.keyframe_insert(data_path="rotation_euler", frame=frame)

    # Exercise every dynamic path the pose copy must detach from.
    action = source.animation_data.action
    nla_track = source.animation_data.nla_tracks.new()
    nla_track.name = "Muted source motion"
    nla_track.strips.new("Source strip", int(action.frame_range[0]), action)
    nla_track.mute = True

    driver = hips_pose.driver_add("scale", 0).driver
    driver.expression = "1.0 + frame / 100.0"

    armature_data["animated_value"] = 0.0
    data_driver = armature_data.driver_add('["animated_value"]').driver
    data_driver.expression = "frame"

    source["kimodo_source"] = True
    source["kimodo_creation_time"] = 123.0
    return source


def main():
    addon_utils.enable(ADDON, default_set=False, persistent=False)
    constraints = importlib.import_module(ADDON + ".constraints")
    operators = importlib.import_module(ADDON + ".operators")
    assert "UNDO" in operators.KIMODO_OT_AddConstraint.bl_options

    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = 20
    settings = scene.kimodo

    source = _create_animated_armature(scene)
    settings.source_armature = source

    scene.frame_set(10)
    bpy.context.view_layer.update()
    expected_world = source.matrix_world.copy()
    expected_pose = _pose_snapshot(source)

    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    bpy.context.view_layer.objects.active = source

    armatures_before = {obj.as_pointer() for obj in bpy.data.objects if obj.type == "ARMATURE"}
    result = sorted(bpy.ops.kimodo.add_constraint(constraint_type="fullbody"))
    item = settings.motion_constraints[-1]
    marker = item.marker_object
    source_name = source.name
    marker_name = marker.name
    armatures_after = {obj.as_pointer() for obj in bpy.data.objects if obj.type == "ARMATURE"}

    assert result == ["FINISHED"]
    assert item.constraint_type == "fullbody"
    assert item.frame == 10
    assert marker is not source
    assert marker.as_pointer() not in armatures_before
    assert len(armatures_after - armatures_before) == 1
    assert marker.data is not source.data
    assert marker.name.startswith("Kimodo_PoseRef_0010")
    assert marker.get("kimodo_constraint") is True
    assert marker.get("kimodo_type") == "fullbody"
    assert not marker.get("kimodo_source")
    assert "kimodo_creation_time" not in marker

    assert marker.parent is None
    assert len(marker.constraints) == 0
    assert sum(len(pb.constraints) for pb in marker.pose.bones) == 0
    assert _animation_counts(marker) == {"action": 0, "nla": 0, "drivers": 0}
    assert _animation_counts(marker.data) == {"action": 0, "nla": 0, "drivers": 0}
    assert _matrix_delta(marker.matrix_world, expected_world) <= TOLERANCE
    assert _max_pose_delta(marker, expected_pose) <= TOLERANCE

    frozen_world = marker.matrix_world.copy()
    frozen_pose = _pose_snapshot(marker)
    frame_deltas = {}
    source_changed = False
    for frame in (1, 20, 10):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        frame_deltas[str(frame)] = max(
            _matrix_delta(marker.matrix_world, frozen_world),
            _max_pose_delta(marker, frozen_pose),
        )
        source_changed = source_changed or (
            _max_pose_delta(source, expected_pose) > 1.0e-4
            or _matrix_delta(source.matrix_world, expected_world) > 1.0e-4
        )

    assert max(frame_deltas.values()) <= TOLERANCE
    assert source_changed
    assert _animation_counts(source)["action"] == 1
    assert _animation_counts(source)["nla"] == 1
    assert _animation_counts(source)["drivers"] >= 1
    assert _animation_counts(source.data)["drivers"] >= 1

    scene.frame_set(10)
    constraint_json = constraints.build_constraints_json(
        settings.motion_constraints,
        scene,
        kimodo_fps=30.0,
        auto_canonicalize=False,
    )
    assert constraint_json[0]["type"] == "fullbody"
    assert constraint_json[0]["frame_indices"] == [9]
    assert len(constraint_json[0]["local_joints_rot"][0]) == len(constraints.SOMA_JOINT_ORDER)

    # The first PoseRef remains selected after creation. Advancing the frame and
    # clicking Full-Body again must sample the animated source at the new frame,
    # not clone the already-frozen reference.
    assert bpy.context.view_layer.objects.active is marker
    scene.frame_set(20)
    bpy.context.view_layer.update()
    expected_second_world = source.matrix_world.copy()
    expected_second_pose = _pose_snapshot(source)

    second_result = sorted(bpy.ops.kimodo.add_constraint(constraint_type="fullbody"))
    second_marker = settings.motion_constraints[-1].marker_object
    second_marker_name = second_marker.name
    assert second_result == ["FINISHED"]
    assert settings.motion_constraints[-1].frame == 20
    assert second_marker is not source
    assert second_marker is not marker
    assert second_marker.data is not source.data
    assert second_marker.data is not marker.data
    assert _animation_counts(second_marker) == {"action": 0, "nla": 0, "drivers": 0}
    assert _matrix_delta(second_marker.matrix_world, expected_second_world) <= TOLERANCE
    assert _max_pose_delta(second_marker, expected_second_pose) <= TOLERANCE

    payload = {
        "blender": bpy.app.version_string,
        "first_result": result,
        "second_result": second_result,
        "source": source_name,
        "pose_reference": marker_name,
        "second_pose_reference": second_marker_name,
        "undo_enabled": "UNDO" in operators.KIMODO_OT_AddConstraint.bl_options,
        "independent_object": marker is not source,
        "independent_data": marker.data is not source.data,
        "animation_free": _animation_counts(marker),
        "data_animation_free": _animation_counts(marker.data),
        "frame_deltas": frame_deltas,
        "source_animation_preserved": _animation_counts(source),
        "constraint_frame_indices": constraint_json[0]["frame_indices"],
    }
    print("KIMODO_FULLBODY_CONSTRAINT_SMOKE=" + json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
