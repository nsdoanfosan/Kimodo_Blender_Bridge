"""Restricted one-way Kimodo motion receiver for iClone 8."""

rl_plugin_info = {"ap": "iClone", "ap_version": "8.0"}

import datetime
from contextlib import contextmanager
import hashlib
import json
import math
import os
import queue
import secrets
import socket
import sys
import threading
import uuid

import RLPy
from PySide2.QtCore import QTimer


SCHEMA_VERSION = 1
PROTOCOL_VERSION = 1
BRIDGE_VERSION = "0.6.3"
HOST = "127.0.0.1"
PORT = 18732
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_QUEUE = 4
MAX_FRAMES = 1800
MAX_TRACKS = 64
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Kimodo Blender Bridge",
)
TOKEN_FILE = os.path.join(CONFIG_DIR, "bridge-token.txt")
LOG_FILE = os.path.join(CONFIG_DIR, "receiver.log")

_server = None
_timer = None


def _log(message):
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 256 * 1024:
            backup = LOG_FILE + ".1"
            if os.path.exists(backup):
                os.remove(backup)
            os.replace(LOG_FILE, backup)
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(LOG_FILE, "a", encoding="utf-8") as stream:
            stream.write("{} {}\n".format(stamp, message))
    except Exception:
        pass


def _ensure_token():
    if not os.path.isdir(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
    if not os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "x", encoding="ascii") as stream:
            stream.write(secrets.token_urlsafe(48))
    with open(TOKEN_FILE, "r", encoding="ascii") as stream:
        token = stream.read().strip()
    if len(token) < 32:
        raise RuntimeError("Receiver token is missing or too short")
    return token


def _object_id(obj):
    for method in ("GetID", "GetObjectID"):
        try:
            return str(getattr(obj, method)())
        except Exception:
            pass
    return None


def _time_value(value):
    for method in ("ToInt64", "ToLong", "ToInt", "GetValue"):
        try:
            return int(getattr(value, method)())
        except Exception:
            pass
    return None


def _fps_value(fps):
    try:
        return float(fps.ToFloat())
    except Exception:
        return 60.0


def _status_succeeded(status):
    if status is None:
        return True
    if isinstance(status, bool):
        return status
    try:
        return not bool(status.IsError())
    except Exception:
        return "Success" in repr(status)


def _session_identity():
    product = str(RLPy.RApplication.GetProductName())
    version = str(RLPy.RApplication.GetProductVersion())
    project_path = ""
    try:
        project_path = str(RLPy.RApplication.GetCurrentProjectPath() or "")
    except Exception:
        pass
    fingerprint = hashlib.sha256(
        "{}|{}|{}|{}".format(product, version, os.getpid(), project_path).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "product": product,
        "version": version,
        "process_id": os.getpid(),
        "project_path": project_path or None,
        "project_fingerprint": fingerprint,
    }


def _validate_session(expected):
    if not isinstance(expected, dict):
        raise ValueError("A live iClone session identity is required")
    live = _session_identity()
    for key in ("product", "process_id", "project_fingerprint"):
        if str(expected.get(key)) != str(live.get(key)):
            raise RuntimeError("Live iClone session mismatch: {}".format(key))


def _selected_avatar():
    avatars = list(RLPy.RScene.GetAvatars())
    selected = [obj for obj in RLPy.RScene.GetSelectedObjects() if obj in avatars]
    if len(selected) != 1:
        raise ValueError("Select exactly one iClone avatar")
    return selected[0]


def _target_avatar(object_id=None):
    avatar = _selected_avatar()
    if object_id and _object_id(avatar) != str(object_id):
        raise RuntimeError("The selected iClone avatar changed")
    return avatar


def _vector(value):
    return [float(value.x), float(value.y), float(value.z)]


def _quaternion(value):
    return [float(value.x), float(value.y), float(value.z), float(value.w)]


def _target_description():
    avatar = _selected_avatar()
    skeleton = avatar.GetSkeletonComponent()
    fps = RLPy.RGlobal.GetFps()
    scene_time = RLPy.RGlobal.GetTime()
    active_clip = skeleton.GetClipByTime(scene_time)
    bones = []
    skin_bones = list(skeleton.GetSkinBones())
    skin_ids = {_object_id(bone): str(bone.GetName()) for bone in skin_bones}
    for bone in skin_bones:
        local_transform = bone.LocalTransform()
        basis_transform = bone.BasisTransform()
        world_transform = bone.WorldTransform()
        parent_name = None
        try:
            parent_name = skin_ids.get(_object_id(bone.GetParent()))
        except Exception:
            pass
        bones.append({
            "name": str(bone.GetName()),
            "parent": parent_name,
            "translation": _vector(basis_transform.T()),
            "rotation": _quaternion(basis_transform.R()),
            "local_translation": _vector(local_transform.T()),
            "local_rotation": _quaternion(local_transform.R()),
            "world_translation": _vector(world_transform.T()),
            "world_rotation": _quaternion(world_transform.R()),
            "transform_control_available": bool(
                active_clip and active_clip.GetControl("Transform", bone)
            ),
        })
    return {
        "avatar": {"id": _object_id(avatar), "name": str(avatar.GetName())},
        "fps": _fps_value(fps),
        "current_frame": int(fps.GetFrameIndex(scene_time)),
        "clip_count": int(skeleton.GetClipCount()),
        "clip_at_current_frame": bool(skeleton.GetClipByTime(scene_time)),
        "bones": bones,
    }


def _finite_triplet(value, label, limit):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("{} must be an XYZ triplet".format(label))
    result = [float(number) for number in value]
    if any(not math.isfinite(number) or abs(number) > limit for number in result):
        raise ValueError("{} contains an invalid value".format(label))
    return result


def _finite_quaternion(value, label):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("{} must be an XYZW quaternion".format(label))
    result = [float(number) for number in value]
    length_sq = sum(number * number for number in result)
    if any(not math.isfinite(number) for number in result) or length_sq < 0.25 or length_sq > 2.25:
        raise ValueError("{} contains an invalid quaternion".format(label))
    return result


def _validate_motion(arguments):
    frame_count = int(arguments.get("frame_count", 0))
    source_fps = float(arguments.get("source_fps", 0.0))
    tracks = arguments.get("tracks")
    if frame_count < 2 or frame_count > MAX_FRAMES:
        raise ValueError("frame_count must be between 2 and {}".format(MAX_FRAMES))
    if not math.isfinite(source_fps) or source_fps < 1.0 or source_fps > 240.0:
        raise ValueError("source_fps is invalid")
    if not isinstance(tracks, list) or not tracks or len(tracks) > MAX_TRACKS:
        raise ValueError("tracks must be a non-empty bounded list")
    parsed = []
    seen = set()
    for track in tracks:
        if not isinstance(track, dict) or set(track) - {
            "bone", "rotation_deg", "rotation_xyzw", "position_cm"
        }:
            raise ValueError("A motion track has unknown fields")
        name = str(track.get("bone") or "").strip()
        if not name or len(name) > 128 or name in seen:
            raise ValueError("Motion track bone names must be unique")
        seen.add(name)
        rotations = track.get("rotation_deg")
        if not isinstance(rotations, list) or len(rotations) != frame_count:
            raise ValueError("rotation_deg length does not match frame_count")
        quaternions = track.get("rotation_xyzw")
        if not isinstance(quaternions, list) or len(quaternions) != frame_count:
            raise ValueError("rotation_xyzw length does not match frame_count")
        positions = track.get("position_cm")
        if positions is not None and (not isinstance(positions, list) or len(positions) != frame_count):
            raise ValueError("position_cm length does not match frame_count")
        parsed.append({
            "bone": name,
            "rotation_deg": [
                _finite_triplet(value, name + " rotation", 36000.0) for value in rotations
            ],
            "rotation_xyzw": [
                _finite_quaternion(value, name + " rotation") for value in quaternions
            ],
            "position_cm": None if positions is None else [
                _finite_triplet(value, name + " position", 100000.0) for value in positions
            ],
        })
    motion_name = str(arguments.get("motion_name") or "Kimodo Motion").strip()
    if not motion_name or len(motion_name) > 96:
        raise ValueError("motion_name is invalid")
    return {
        "frame_count": frame_count,
        "source_fps": source_fps,
        "tracks": parsed,
        "motion_name": motion_name,
        "start_frame": arguments.get("start_frame"),
        "reuse_single_frame_clip": bool(arguments.get("reuse_single_frame_clip", True)),
    }


def _clip_length_frames(clip, fps):
    return int(fps.GetFrameIndex(clip.GetClipLength()))


def _layer_controls(clip, bone, need_position=False):
    control = clip.GetControl("Layer", bone)
    if not control:
        raise RuntimeError("Motion Layer is unavailable for {}".format(bone.GetName()))
    block = control.GetDataBlock()
    if not block:
        raise RuntimeError("Motion Layer data is unavailable for {}".format(bone.GetName()))
    paths = {
        "rx": "Rotation/RotationX", "ry": "Rotation/RotationY", "rz": "Rotation/RotationZ",
        "px": "Position/PositionX", "py": "Position/PositionY", "pz": "Position/PositionZ",
    }
    result = {name: block.GetControl(path) for name, path in paths.items()}
    required = ("rx", "ry", "rz", "px", "py", "pz") if need_position else ("rx", "ry", "rz")
    if not all(result[name] for name in required):
        channel_kind = "rotation and position" if need_position else "rotation"
        raise RuntimeError("Motion Layer {} channels are unavailable for {}".format(
            channel_kind, bone.GetName()
        ))
    return result


@contextmanager
def _undo_action(name):
    status = RLPy.RGlobal.BeginAction(str(name), False)
    if status is not None and not _status_succeeded(status):
        raise RuntimeError("iClone could not begin the Kimodo action")
    try:
        yield
    finally:
        RLPy.RGlobal.EndAction()


def _apply_motion(arguments, dry_run=False):
    request = _validate_motion(arguments)
    avatar = _target_avatar(arguments.get("object_id"))
    skeleton = avatar.GetSkeletonComponent()
    fps = RLPy.RGlobal.GetFps()
    target_fps = _fps_value(fps)
    current_frame = int(fps.GetFrameIndex(RLPy.RGlobal.GetTime()))
    start_frame = current_frame if request["start_frame"] is None else int(request["start_frame"])
    if start_frame < 0:
        raise ValueError("start_frame must not be negative")

    source_last = request["frame_count"] - 1
    last_offset = int(round(source_last * target_fps / request["source_fps"]))
    end_frame = start_frame + last_offset
    start_time = fps.IndexedFrameTime(start_frame)
    existing = skeleton.GetClipByTime(start_time)
    reusable = bool(
        existing and request["reuse_single_frame_clip"]
        and _clip_length_frames(existing, fps) <= 1
    )
    if existing and not reusable:
        raise ValueError("A non-empty motion clip already exists at the insertion frame")

    bone_map = {str(bone.GetName()): bone for bone in skeleton.GetSkinBones()}
    missing = [track["bone"] for track in request["tracks"] if track["bone"] not in bone_map]
    if missing:
        raise ValueError("The selected avatar is missing mapped bones: " + ", ".join(missing[:8]))

    plan = {
        "avatar": {"id": _object_id(avatar), "name": str(avatar.GetName())},
        "motion_name": request["motion_name"],
        "source_fps": request["source_fps"],
        "target_fps": target_fps,
        "source_frames": request["frame_count"],
        "start_frame": start_frame,
        "end_frame": end_frame,
        "track_count": len(request["tracks"]),
        "reuse_single_frame_clip": reusable,
        "create_clip": not bool(existing),
    }
    if dry_run:
        plan["dry_run"] = True
        return plan

    before_count = int(skeleton.GetClipCount())
    with _undo_action("Apply Kimodo Motion"):
        clip = existing
        if clip is None:
            clip = skeleton.AddClip(start_time)
            if not clip:
                raise RuntimeError("iClone failed to create a motion clip")
        if not clip:
            raise RuntimeError("iClone did not return the Kimodo motion clip")
        # iClone clips are end-exclusive. Keep one full frame after the final
        # incoming sample or the last key is discarded during flattening.
        length_status = clip.SetLength(fps.IndexedFrameTime(max(1, last_offset + 1)))
        if not _status_succeeded(length_status):
            raise RuntimeError("iClone failed to size the Kimodo motion clip")

        resolved = [
            (track, _layer_controls(
                clip, bone_map[track["bone"]], track["position_cm"] is not None
            ))
            for track in request["tracks"]
        ]
        unique_key_frames = set()
        for index in range(request["frame_count"]):
            scene_frame = start_frame + int(round(index * target_fps / request["source_fps"]))
            unique_key_frames.add(scene_frame)
            scene_time = fps.IndexedFrameTime(scene_frame)
            clip_time = clip.SceneTimeToClipTime(scene_time)
            for track, controls in resolved:
                rotation = track["rotation_deg"][index]
                for name, value in zip(("rx", "ry", "rz"), rotation):
                    status = controls[name].SetValue(clip_time, math.radians(value))
                    if status is not None and not _status_succeeded(status):
                        raise RuntimeError("iClone rejected a Kimodo rotation key")
                if track["position_cm"] is not None:
                    position = track["position_cm"][index]
                    for name, value in zip(("px", "py", "pz"), position):
                        status = controls[name].SetValue(clip_time, value)
                        if status is not None and not _status_succeeded(status):
                            raise RuntimeError("iClone rejected a Kimodo position key")

            RLPy.RGlobal.SetTime(scene_time)
            RLPy.RGlobal.ForceViewportUpdate()
            bake_status = skeleton.BakeFkToIk(scene_time, False)
            if bake_status is not None and not _status_succeeded(bake_status):
                raise RuntimeError("iClone failed to preserve Kimodo FK at frame {}".format(
                    scene_frame
                ))

        RLPy.RGlobal.SetTime(start_time)
        RLPy.RGlobal.ForceViewportUpdate()
        finalize_status = skeleton.BakeFkToIk(start_time, True)
        if finalize_status is not None and not _status_succeeded(finalize_status):
            raise RuntimeError("iClone failed to finalize Kimodo FK/IK data")

        temporary_key_count = int(resolved[0][1]["rx"].GetKeyCount())
        if temporary_key_count < len(unique_key_frames):
            raise RuntimeError("Kimodo key-count verification failed before flattening")

        flatten_status = skeleton.FlattenMotionClip(clip)
        if not _status_succeeded(flatten_status):
            raise RuntimeError("iClone failed to bake Kimodo keys into the motion clip")

        current_project_end = int(fps.GetFrameIndex(RLPy.RGlobal.GetEndTime()))
        if end_frame > current_project_end:
            RLPy.RGlobal.SetProjectLength(fps.IndexedFrameTime(end_frame + 1))
            RLPy.RGlobal.SetEndTime(fps.IndexedFrameTime(end_frame))

    after_count = int(skeleton.GetClipCount())
    applied = skeleton.GetClipByTime(start_time)
    if not applied:
        raise RuntimeError("Kimodo keys were written but the clip cannot be resolved")
    first_track = request["tracks"][0]
    remaining_controls = _layer_controls(applied, bone_map[first_track["bone"]])
    remaining_key_count = int(remaining_controls["rx"].GetKeyCount())
    if remaining_key_count != 0:
        raise RuntimeError("Kimodo motion was applied but Motion Layer keys remain")
    # Writing the final temporary key can leave iClone's evaluated skeleton
    # cache on that pose even though the playhead never moved. Step once and
    # return to the insertion frame so the newly baked clip displays frame 0.
    preview_frame = min(end_frame, start_frame + 1)
    if preview_frame != start_frame:
        RLPy.RGlobal.SetTime(fps.IndexedFrameTime(preview_frame))
    RLPy.RGlobal.SetTime(start_time)
    RLPy.RGlobal.ForceViewportUpdate()
    plan.update({
        "before_clip_count": before_count,
        "after_clip_count": after_count,
        "verified_bone": first_track["bone"],
        "temporary_rotation_key_count": temporary_key_count,
        "remaining_layer_key_count": remaining_key_count,
        "flattened_to_motion_clip": True,
        "unique_key_frames": len(unique_key_frames),
        "clip_length_frames": _clip_length_frames(applied, fps),
        "_changes": [{
            "entity": "avatar.motion",
            "property": "kimodo_clip",
            "before": {"clip_count": before_count},
            "after": {"clip_count": after_count, "start": start_frame, "end": end_frame},
        }],
    })
    return plan


def _dispatch(operation, arguments, mode, dry_run):
    if operation == "bridge.health":
        return {
            "bridge_id": "kimodo.iclone.motion-receiver",
            "bridge_version": BRIDGE_VERSION,
            "protocol_version": PROTOCOL_VERSION,
        }
    if operation == "session.describe":
        return _session_identity()
    if operation == "target.describe":
        return _target_description()
    if operation in {"official_link.status", "official_link.start", "official_link.send_actors"}:
        official_root = r"C:\Program Files\Reallusion\iClone 8\Bin64\OpenPlugin\Blender Pipeline Plugin"
        if official_root not in sys.path:
            sys.path.insert(0, official_root)
        from btp import link as official_link
        data_link = official_link.get_data_link()
        if operation == "official_link.start":
            if mode != "mutate":
                raise ValueError("official_link.start requires mutate mode")
            data_link.link_start()
        elif operation == "official_link.send_actors":
            if mode != "mutate":
                raise ValueError("official_link.send_actors requires mutate mode")
            data_link.send_actors()
        return {
            "listening": bool(data_link.is_listening()),
            "connected": bool(data_link.is_connected()),
        }
    if operation == "motion.apply":
        if mode != "mutate":
            raise ValueError("motion.apply requires mutate mode")
        return _apply_motion(arguments, dry_run)
    raise ValueError("Unknown operation: {}".format(operation))


class _Request(object):
    def __init__(self, payload):
        self.payload = payload
        self.finished = threading.Event()
        self.response = None


class _Server(threading.Thread):
    def __init__(self, token):
        super(_Server, self).__init__(daemon=True)
        self.token = token
        self.pending = queue.Queue(MAX_QUEUE)
        self.stop_event = threading.Event()
        self.sock = None

    def run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((HOST, PORT))
            sock.listen(4)
            sock.settimeout(0.5)
            self.sock = sock
            _log("listening {}:{}".format(HOST, PORT))
            while not self.stop_event.is_set():
                try:
                    conn, _address = sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
        except Exception as exc:
            _log("server failed: {!r}".format(exc))

    def _handle(self, conn):
        conn.settimeout(180.0)
        try:
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
                if len(data) > MAX_MESSAGE_BYTES:
                    raise ValueError("Message too large")
            payload = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
            if not secrets.compare_digest(str(payload.pop("token", "")), self.token):
                raise PermissionError("Authentication failed")
            request = _Request(payload)
            self.pending.put(request, timeout=1.0)
            if not request.finished.wait(170.0):
                raise TimeoutError("iClone main-thread operation timed out")
            response = request.response
        except Exception as exc:
            response = {"schema_version": 1, "ok": False, "error": {"code": exc.__class__.__name__, "message": str(exc)}}
        try:
            conn.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            conn.close()

    def stop(self):
        self.stop_event.set()
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


def _process_requests():
    if _server is None:
        return
    try:
        request = _server.pending.get_nowait()
    except queue.Empty:
        return
    payload = request.payload
    request_id = str(payload.get("request_id") or "")
    try:
        allowed = {"schema_version", "request_id", "deadline_utc", "session", "mode", "operation", "arguments", "dry_run"}
        if set(payload) - allowed:
            raise ValueError("Unknown request fields")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported schema_version")
        uuid.UUID(request_id)
        mode = payload.get("mode", "query")
        if mode not in ("query", "mutate"):
            raise ValueError("Unsupported mode")
        if mode == "mutate":
            _validate_session(payload.get("session"))
        result = _dispatch(
            payload.get("operation"), payload.get("arguments") or {}, mode,
            bool(payload.get("dry_run", False)),
        )
        changes = result.pop("_changes", []) if isinstance(result, dict) else []
        request.response = {
            "schema_version": 1, "request_id": request_id, "ok": True,
            "session": _session_identity(), "result": result,
            "warnings": [], "changes": changes, "error": None,
        }
    except Exception as exc:
        request.response = {
            "schema_version": 1, "request_id": request_id, "ok": False,
            "session": _session_identity(), "result": None,
            "warnings": [], "changes": [],
            "error": {"code": exc.__class__.__name__, "message": str(exc)},
        }
        _log("request error: {!r}".format(exc))
    finally:
        request.finished.set()


def initialize_plugin():
    global _server, _timer
    if _server is not None:
        return
    _server = _Server(_ensure_token())
    _server.start()
    _timer = QTimer()
    _timer.timeout.connect(_process_requests)
    _timer.start(20)
    _log("initialized version={}".format(BRIDGE_VERSION))


def run_script():
    initialize_plugin()


def shutdown_plugin():
    global _server, _timer
    if _timer is not None:
        _timer.stop()
        _timer = None
    if _server is not None:
        _server.stop()
        _server = None
    _log("shutdown")
