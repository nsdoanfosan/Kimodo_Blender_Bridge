"""Blender background regression test for bridge state across .blend loads.

Run with:

    blender --factory-startup --background --python tests/blender_connection_load_smoke.py

The test uses a fake ready process; it never loads the Kimodo model.
"""

import importlib
import json
import os
import tempfile

import addon_utils
import bpy


ADDON = "kimodo_blender_bridge"


class _FakeRunningProcess:
    returncode = None

    def poll(self):
        return None


def main():
    addon_utils.enable(ADDON, default_set=False, persistent=False)
    sc = importlib.import_module(ADDON + ".subprocess_client")
    properties = importlib.import_module(ADDON + ".properties")

    original = {
        "proc": sc._proc,
        "ready": sc._ready,
        "status": sc._status,
    }
    fake_proc = _FakeRunningProcess()

    try:
        with tempfile.TemporaryDirectory(prefix="kimodo-load-smoke-") as temp_dir:
            blend_path = os.path.join(temp_dir, "next_file.blend")
            settings = bpy.context.scene.kimodo
            settings.is_connected = False
            settings.connection_status = "Not started"
            settings.is_generating = True
            settings.generation_progress = "Stale generation"
            settings.generating_segment_index = 4
            settings.prompt = "preserve this per-file prompt"
            bpy.ops.wm.save_as_mainfile(filepath=blend_path)

            sc._proc = fake_proc
            sc._ready = True
            sc._status = "Ready - connection load smoke"

            bpy.ops.wm.open_mainfile(filepath=blend_path)

            settings = bpy.context.scene.kimodo
            start_result = sorted(bpy.ops.kimodo.start_kimodo())
            payload = {
                "blender": bpy.app.version_string,
                "same_proc": sc._proc is fake_proc,
                "process_running": sc.is_running(),
                "process_ready": sc.is_ready(),
                "scene_connected": settings.is_connected,
                "scene_status": settings.connection_status,
                "start_result": start_result,
                "generate_ui_enabled": sc.is_ready(),
                "generation_reset": not settings.is_generating,
                "segment_reset": settings.generating_segment_index == -1,
                "prompt_preserved": settings.prompt == "preserve this per-file prompt",
                "load_handler_count": sum(
                    handler is properties._on_load_post
                    for handler in bpy.app.handlers.load_post
                ),
            }

            assert payload["same_proc"]
            assert payload["process_running"]
            assert payload["process_ready"]
            assert payload["scene_connected"]
            assert payload["scene_status"] == "Ready - connection load smoke"
            assert payload["start_result"] == ["FINISHED"]
            assert payload["generate_ui_enabled"]
            assert payload["generation_reset"]
            assert payload["segment_reset"]
            assert payload["prompt_preserved"]
            assert payload["load_handler_count"] == 1

            print("KIMODO_CONNECTION_LOAD_SMOKE=" + json.dumps(payload, sort_keys=True))
    finally:
        sc._proc = original["proc"]
        sc._ready = original["ready"]
        sc._status = original["status"]


if __name__ == "__main__":
    main()
