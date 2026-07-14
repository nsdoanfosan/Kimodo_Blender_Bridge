"""Blender background smoke test for standalone iClone motion export."""

import importlib
import json
import os
import tempfile

import addon_utils
import bpy


ADDON = "kimodo_blender_bridge"


def main():
    addon_utils.enable(ADDON, default_set=False, persistent=False)
    exporter = importlib.import_module(ADDON + ".iclone_motion_export")

    source = bpy.data.objects.get("TEST_01B_CaneWalk_RightHandConstraints_Rig")
    if source is None:
        source = next(
            (
                obj for obj in bpy.data.objects
                if obj.type == "ARMATURE"
                and obj.animation_data
                and obj.animation_data.action
            ),
            None,
        )
    if source is None:
        raise AssertionError("An animated Kimodo armature is required")

    state = exporter.inspect_source(source)
    assert state["ready"], state
    assert state["has_root"]
    assert state["mapped_bones"] >= 50

    with tempfile.TemporaryDirectory(prefix="kimodo_iclone_") as directory:
        fbx_path = os.path.join(directory, "Kimodo_iClone_Smoke.fbx")
        result = exporter.export_motion(
            source,
            fbx_path,
            state["frame_start"],
            state["frame_end"],
        )
        profile_path = result["profile_path"]
        assert os.path.isfile(fbx_path)
        assert os.path.getsize(fbx_path) > 1024
        assert os.path.isfile(profile_path)

        profile = open(profile_path, encoding="utf-8").read()
        assert "[BoneMap]" in profile
        assert "Hips = Hips" in profile
        assert "Spine1 = Spine" in profile
        assert "LeftHandIndex2 = LeftHandIndex1" in profile
        assert "[BoneRotate]" in profile
        assert source.name + " = " in profile
        assert "Root = " in profile

        before = set(bpy.data.objects.keys())
        # Blender's FBX importer defaults to a +1 frame display offset; disable
        # it so this round-trip check compares the encoded FBX time range.
        import_result = bpy.ops.import_scene.fbx(filepath=fbx_path, anim_offset=0.0)
        imported = [
            obj for obj in bpy.data.objects
            if obj.name not in before and obj.type == "ARMATURE"
        ]
        assert "FINISHED" in import_result
        assert len(imported) == 1
        imported_rig = imported[0]
        assert "Root" in imported_rig.data.bones
        assert "Hips" in imported_rig.data.bones
        assert "LeftHandIndex2" in imported_rig.data.bones
        assert imported_rig.animation_data is not None
        assert imported_rig.animation_data.action is not None
        imported_range = list(imported_rig.animation_data.action.frame_range)
        # FBX time conversion can introduce sub-frame floating-point drift.
        assert imported_range[0] <= state["frame_start"] + 0.001, (
            imported_range, state["frame_start"], state["frame_end"]
        )
        assert imported_range[1] >= state["frame_end"] - 0.001, (
            imported_range, state["frame_start"], state["frame_end"]
        )

        payload = {
            "blender": bpy.app.version_string,
            "source": source.name,
            "action": state["action"],
            "frames": [state["frame_start"], state["frame_end"]],
            "mapped_bones": state["mapped_bones"],
            "fbx_bytes": result["fbx_bytes"],
            "profile_bytes": os.path.getsize(profile_path),
            "imported_bones": len(imported_rig.data.bones),
            "imported_action": imported_rig.animation_data.action.name,
            "imported_range": imported_range,
        }
        print("KIMODO_ICLONE_EXPORT_SMOKE=" + json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
