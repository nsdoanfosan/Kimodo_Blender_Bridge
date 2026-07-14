"""Blender background smoke test for direct iClone payload sampling."""

import importlib
import json
import math

import addon_utils
import bpy


ADDON = "kimodo_blender_bridge"


def make_source():
    armature = bpy.data.armatures.new("KimodoLiveTest_Data")
    source = bpy.data.objects.new("KimodoLiveTest", armature)
    bpy.context.scene.collection.objects.link(source)
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = armature.edit_bones.new("Root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 0.1, 0.0)
    hips = armature.edit_bones.new("Hips")
    hips.head = (0.0, 0.0, 0.1)
    hips.tail = (0.0, 0.1, 0.1)
    hips.parent = root
    bpy.ops.object.mode_set(mode="POSE")
    for pose_bone in source.pose.bones:
        pose_bone.rotation_mode = "XYZ"
    for frame, angle, root_x in (
        (1, 0.0, 0.0),
        (2, math.radians(5.0), 0.01),
        (3, math.radians(10.0), 0.02),
    ):
        hips_pose = source.pose.bones["Hips"]
        hips_pose.rotation_euler = (angle, 0.0, 0.0)
        hips_pose.keyframe_insert(data_path="rotation_euler", frame=frame)
        root_pose = source.pose.bones["Root"]
        root_pose.location = (root_x, 0.0, 0.0)
        root_pose.keyframe_insert(data_path="location", frame=frame)
        root_pose.keyframe_insert(data_path="rotation_euler", frame=frame)
    bpy.ops.object.mode_set(mode="OBJECT")
    return source


def main():
    addon_utils.enable(ADDON, default_set=False, persistent=False)
    live = importlib.import_module(ADDON + ".iclone_live_send")
    source = make_source()
    target_response = {
        "result": {
            "avatar": {"id": "test-avatar", "name": "Test CC"},
            "fps": 60.0,
            "current_frame": 12,
            "bones": [
                {
                    "name": "RL_BoneRoot",
                    "parent": None,
                    "translation": [0.0, 0.0, 0.0],
                    "rotation": [0.0, 0.0, 0.0, 1.0],
                },
                {
                    "name": "CC_Base_Hip",
                    "parent": "RL_BoneRoot",
                    "translation": [0.0, 0.0, 100.0],
                    "rotation": [0.0, 0.0, 0.0, 1.0],
                },
            ],
        }
    }
    payload, metadata = live.build_motion_payload(source, target_response)
    tracks = {track["bone"]: track for track in payload["tracks"]}
    assert payload["frame_count"] == 3, payload
    assert payload["start_frame"] == 12, payload
    assert set(tracks) == {"RL_BoneRoot", "CC_Base_Hip"}, tracks
    assert tracks["RL_BoneRoot"]["position_cm"] == [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
    ]
    assert abs(tracks["CC_Base_Hip"]["rotation_deg"][2][0] - 10.0) < 0.01
    assert metadata["mapped_bones"] == 2
    print("KIMODO_ICLONE_LIVE_SMOKE=" + json.dumps({
        "frame_count": payload["frame_count"],
        "mapped_bones": metadata["mapped_bones"],
        "root_positions": tracks["RL_BoneRoot"]["position_cm"],
        "hip_last_rotation": tracks["CC_Base_Hip"]["rotation_deg"][2],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
