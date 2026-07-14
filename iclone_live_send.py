"""Direct Kimodo Action transfer to the selected iClone avatar.

The iClone receiver exposes only bounded target inspection and motion apply
operations. Blender samples the active Kimodo Action, converts each local bone
delta into the selected CC character's rest axes, and sends the complete frame
tracks. iClone then flattens the temporary keys into one Motion Clip.
"""

import datetime
import json
import math
import os
import socket
import uuid

import bpy
from mathutils import Quaternion

from . import retarget_presets


HOST = "127.0.0.1"
PORT = 18732
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
TOKEN_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Kimodo Blender Bridge",
    "bridge-token.txt",
)


class ICloneLiveSendError(RuntimeError):
    pass


def _request(operation, arguments=None, mode="query", dry_run=False, session=None):
    if not os.path.isfile(TOKEN_FILE):
        raise ICloneLiveSendError(
            "Kimodo Motion Receiver is not running. Start or restart iClone first."
        )
    with open(TOKEN_FILE, "r", encoding="ascii") as stream:
        token = stream.read().strip()
    if len(token) < 32:
        raise ICloneLiveSendError("Kimodo Motion Receiver token is invalid")

    deadline = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=160)
    payload = {
        "schema_version": 1,
        "request_id": str(uuid.uuid4()),
        "deadline_utc": deadline.isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "operation": operation,
        "arguments": arguments or {},
        "dry_run": bool(dry_run),
        "token": token,
    }
    if session is not None:
        payload["session"] = session

    try:
        with socket.create_connection((HOST, PORT), timeout=5.0) as connection:
            connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            connection.settimeout(175.0)
            chunks = []
            size = 0
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ICloneLiveSendError("iClone receiver response is too large")
                if b"\n" in chunk:
                    break
    except (ConnectionError, OSError, socket.timeout) as exc:
        raise ICloneLiveSendError(
            "Cannot reach Kimodo Motion Receiver in iClone: {}".format(exc)
        ) from exc

    try:
        response = json.loads(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"))
    except Exception as exc:
        raise ICloneLiveSendError("iClone receiver returned an invalid response") from exc
    if not response.get("ok"):
        error = response.get("error") or {}
        raise ICloneLiveSendError(error.get("message") or "iClone receiver rejected the request")
    return response


def inspect_connection():
    response = _request("target.describe")
    target = response["result"]
    return {
        "avatar_id": target["avatar"]["id"],
        "avatar_name": target["avatar"]["name"],
        "fps": target["fps"],
        "current_frame": target["current_frame"],
        "clip_count": target["clip_count"],
        "bone_count": len(target["bones"]),
    }


def inspect_source(source):
    action = None
    if source and source.type == "ARMATURE" and source.animation_data:
        action = source.animation_data.action
    source_names = set(source.data.bones.keys()) if source and source.type == "ARMATURE" else set()
    required = [name for name in ("Root", "Hips") if name not in source_names]
    if action:
        start = int(math.floor(action.frame_range[0]))
        end = int(math.ceil(action.frame_range[1]))
    else:
        start = end = 0
    return {
        "ready": bool(source and source.type == "ARMATURE" and action and not required and end >= start),
        "action": action.name if action else "",
        "frame_start": start,
        "frame_end": end,
        "frame_count": max(0, end - start + 1),
        "missing_required": required,
    }


def _target_bone_catalog(target):
    # Skin-bone lists can contain RL_BoneRoot twice. Names are stable and the
    # duplicates describe the same node, so a name-keyed catalog is intended.
    return {bone["name"]: bone for bone in target["bones"]}


def _direct_cc_mapping(source_names, target_names):
    mappings = []
    missing = []
    profile = retarget_presets.PROFILES[retarget_presets.PROFILE_REALLUSION_CC]
    for item in profile["mappings"]:
        # The iClone body Motion Layer has no FK channels for facial skin
        # bones. Kimodo SOMA body transfer therefore excludes jaw and eyes.
        if item["src"] in {"Jaw", "LeftEye", "RightEye"}:
            continue
        target_name = "RL_BoneRoot" if item["src"] == "Root" else item["tgt"]
        if item["src"] not in source_names:
            continue
        if target_name not in target_names:
            missing.append(target_name)
            continue
        mappings.append((item["src"], target_name))
    return mappings, sorted(set(missing))


def _target_global_rest_rotations(target_bones):
    result = {}

    def resolve(name, stack=None):
        if name in result:
            return result[name]
        stack = set() if stack is None else stack
        if name in stack:
            raise ICloneLiveSendError("iClone target skeleton contains a parent cycle")
        stack.add(name)
        bone = target_bones[name]
        x, y, z, w = bone["rotation"]
        local = Quaternion((w, x, y, z)).normalized()
        parent = bone.get("parent")
        value = (resolve(parent, stack) @ local).normalized() if parent in target_bones else local
        stack.remove(name)
        result[name] = value
        return value

    for bone_name in target_bones:
        resolve(bone_name)
    return result


def _source_local_delta(source, source_bone_name):
    pose_bone = source.pose.bones[source_bone_name]
    data_bone = source.data.bones[source_bone_name]
    if pose_bone.parent:
        pose_local = pose_bone.parent.matrix.inverted_safe() @ pose_bone.matrix
        rest_local = data_bone.parent.matrix_local.inverted_safe() @ data_bone.matrix_local
    else:
        pose_local = pose_bone.matrix.copy()
        rest_local = data_bone.matrix_local.copy()
    return (rest_local.inverted_safe() @ pose_local).to_quaternion().normalized()


def build_motion_payload(source, target_response):
    state = inspect_source(source)
    if not state["ready"]:
        if state["missing_required"]:
            raise ICloneLiveSendError(
                "Kimodo source is missing: " + ", ".join(state["missing_required"])
            )
        raise ICloneLiveSendError("Choose an animated Kimodo source armature")

    target = target_response["result"]
    target_bones = _target_bone_catalog(target)
    mappings, missing_target = _direct_cc_mapping(
        set(source.data.bones.keys()), set(target_bones)
    )
    if not mappings or ("Root", "RL_BoneRoot") not in mappings:
        raise ICloneLiveSendError("The selected iClone avatar is not a compatible CC Base character")

    target_rest = _target_global_rest_rotations(target_bones)
    frames = list(range(state["frame_start"], state["frame_end"] + 1))
    saved_frame = bpy.context.scene.frame_current
    track_data = {
        target_name: {
            "bone": target_name,
            "rotation_deg": [],
        }
        for _source_name, target_name in mappings
    }
    source_rest = {
        source_name: (
            source.matrix_world.to_quaternion() @
            source.data.bones[source_name].matrix_local.to_quaternion()
        ).normalized()
        for source_name, _target_name in mappings
    }
    previous_eulers = {}
    root_origin = None
    try:
        for frame in frames:
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            for source_name, target_name in mappings:
                source_delta = _source_local_delta(source, source_name)
                rest_rotation = source_rest[source_name]
                world_delta = (
                    rest_rotation @ source_delta @ rest_rotation.inverted()
                ).normalized()
                target_rotation = target_rest[target_name]
                target_delta = (
                    target_rotation.inverted() @ world_delta @ target_rotation
                ).normalized()
                euler = target_delta.to_euler(
                    "XYZ", previous_eulers.get(target_name)
                )
                previous_eulers[target_name] = euler.copy()
                track_data[target_name]["rotation_deg"].append([
                    math.degrees(euler.x),
                    math.degrees(euler.y),
                    math.degrees(euler.z),
                ])

                if source_name == "Root":
                    world_position = (
                        source.matrix_world @ source.pose.bones[source_name].matrix
                    ).translation
                    if root_origin is None:
                        root_origin = world_position.copy()
                        track_data[target_name]["position_cm"] = []
                    delta = (world_position - root_origin) * 100.0
                    track_data[target_name]["position_cm"].append([
                        float(delta.x), float(delta.y), float(delta.z)
                    ])
    finally:
        bpy.context.scene.frame_set(saved_frame)
        bpy.context.view_layer.update()

    tracks = [track_data[target_name] for _source_name, target_name in mappings]

    scene = bpy.context.scene
    source_fps = float(scene.render.fps) / float(scene.render.fps_base or 1.0)
    return {
        "object_id": target["avatar"]["id"],
        "motion_name": state["action"],
        "source_fps": source_fps,
        "frame_count": len(frames),
        "start_frame": target["current_frame"],
        "tracks": tracks,
    }, {
        "source": state,
        "target": target["avatar"],
        "mapped_bones": len(mappings),
        "missing_target": missing_target,
    }


def send_motion(source):
    target_response = _request("target.describe")
    payload, metadata = build_motion_payload(source, target_response)
    session = target_response["session"]
    _request("motion.apply", payload, mode="mutate", dry_run=True, session=session)
    response = _request("motion.apply", payload, mode="mutate", session=session)
    metadata["result"] = response["result"]
    return metadata
