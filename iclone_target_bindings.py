"""Small per-project iClone target registry stored in Blender's user config."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import tempfile

import bpy


SCHEMA_VERSION = 1
FILE_NAME = "iclone_target_bindings.json"
_session_bindings = {}


def binding_path():
    directory = bpy.utils.user_resource(
        "CONFIG",
        path="kimodo_blender_bridge",
        create=True,
    )
    return os.path.join(directory, FILE_NAME)


def _empty_document():
    return {"schema_version": SCHEMA_VERSION, "bindings": {}}


def _load_document():
    path = binding_path()
    if not os.path.isfile(path):
        return _empty_document()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return _empty_document()
    if data.get("schema_version") != SCHEMA_VERSION:
        return _empty_document()
    if not isinstance(data.get("bindings"), dict):
        return _empty_document()
    return data


def _save_document(data):
    path = binding_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            prefix=FILE_NAME + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = handle.name
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def get_binding(project):
    project_key = str(project.get("key") or "")
    if not project_key:
        return None
    if project.get("session_only"):
        value = _session_bindings.get(project_key)
    else:
        value = _load_document()["bindings"].get(project_key)
    return dict(value) if isinstance(value, dict) else None


def set_binding(project, avatar):
    project_key = str(project.get("key") or "")
    link_id = str(avatar.get("link_id") or "")
    if not project_key or not link_id:
        raise ValueError("Project key and avatar Link ID are required")
    value = {
        "project_name": str(project.get("name") or ""),
        "project_path": str(project.get("path") or ""),
        "avatar_name": str(avatar.get("name") or ""),
        "link_id": link_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if project.get("session_only"):
        _session_bindings[project_key] = value
    else:
        document = _load_document()
        document["bindings"][project_key] = value
        _save_document(document)
    return dict(value)
