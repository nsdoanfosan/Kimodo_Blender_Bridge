"""Temporary animator controls for frozen Kimodo Full-Body pose references.

This module deliberately stays independent from Full-Body reference creation.
It adds a small, disposable control rig to an already-created PoseRef, then can
bake the visible pose back to the original Kimodo bones or restore the pose that
existed before the controls were added.
"""

from __future__ import annotations

import json
import math

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator, Panel
from mathutils import Matrix, Vector


CONTROL_PREFIX = "KIMODO_CTRL_"
CONSTRAINT_PREFIX = "KIMODO_POSE_CTRL_"
SNAPSHOT_KEY = "kimodo_pose_control_snapshot"
MANIFEST_KEY = "kimodo_pose_control_manifest"
VERSION_KEY = "kimodo_pose_control_version"
SHOW_SOURCE_KEY = "kimodo_pose_control_show_source"
CONTROL_VERSION = 1
BUILD_TOLERANCE = 2.0e-4

CONTROL_COLLECTION = "Kimodo Pose Controls"
WIDGET_COLLECTION = "Kimodo Control Widgets"
WIDGET_MARKER = "kimodo_pose_control_widget"

CTRL_ROOT = CONTROL_PREFIX + "Root"
CTRL_HIPS = CONTROL_PREFIX + "Hips"
CTRL_SPINE1 = CONTROL_PREFIX + "Spine1"
CTRL_SPINE2 = CONTROL_PREFIX + "Spine2"
CTRL_CHEST = CONTROL_PREFIX + "Chest"
CTRL_HEAD = CONTROL_PREFIX + "Head"
CTRL_HAND_L = CONTROL_PREFIX + "Hand.L"
CTRL_HAND_R = CONTROL_PREFIX + "Hand.R"
CTRL_ELBOW_L = CONTROL_PREFIX + "Elbow.L"
CTRL_ELBOW_R = CONTROL_PREFIX + "Elbow.R"
CTRL_FOOT_L = CONTROL_PREFIX + "Foot.L"
CTRL_FOOT_R = CONTROL_PREFIX + "Foot.R"
CTRL_KNEE_L = CONTROL_PREFIX + "Knee.L"
CTRL_KNEE_R = CONTROL_PREFIX + "Knee.R"

REQUIRED_BONES = (
    "Root", "Hips", "Spine1", "Spine2", "Chest", "Head",
    "LeftArm", "LeftForeArm", "LeftHand",
    "RightArm", "RightForeArm", "RightHand",
    "LeftLeg", "LeftShin", "LeftFoot",
    "RightLeg", "RightShin", "RightFoot",
)

CONTROL_LABELS = (
    (CTRL_ROOT, "Root", 'EMPTY_ARROWS'),
    (CTRL_HIPS, "Hips", 'ORIENTATION_GIMBAL'),
    (CTRL_SPINE1, "Spine 1", 'DRIVER_ROTATIONAL_DIFFERENCE'),
    (CTRL_SPINE2, "Spine 2", 'DRIVER_ROTATIONAL_DIFFERENCE'),
    (CTRL_CHEST, "Chest", 'DRIVER_ROTATIONAL_DIFFERENCE'),
    (CTRL_HEAD, "Head", 'USER'),
    (CTRL_HAND_L, "L.Hand", 'VIEW_PAN'),
    (CTRL_HAND_R, "R.Hand", 'VIEW_PAN'),
    (CTRL_FOOT_L, "L.Foot", 'SNAP_FACE'),
    (CTRL_FOOT_R, "R.Foot", 'SNAP_FACE'),
)


def _is_pose_reference(obj):
    return bool(
        obj
        and obj.type == 'ARMATURE'
        and obj.get("kimodo_constraint")
        and obj.get("kimodo_type") == 'fullbody'
    )


def _resolve_pose_reference(context, target_name=""):
    if target_name:
        obj = bpy.data.objects.get(target_name)
        if _is_pose_reference(obj):
            return obj

    if _is_pose_reference(context.active_object):
        return context.active_object

    settings = getattr(context.scene, "kimodo", None)
    if settings is None:
        return None

    items = list(settings.motion_constraints)
    index = getattr(settings, "constraint_index", -1)
    if 0 <= index < len(items):
        item = items[index]
        if item.constraint_type == 'fullbody' and _is_pose_reference(item.marker_object):
            return item.marker_object

    references = [
        item.marker_object for item in items
        if item.constraint_type == 'fullbody' and _is_pose_reference(item.marker_object)
    ]
    return references[0] if len(references) == 1 else None


def _has_controls(obj):
    return bool(
        _is_pose_reference(obj)
        and obj.get(VERSION_KEY)
        and obj.get(MANIFEST_KEY)
        and CTRL_HIPS in obj.data.bones
    )


def _has_animation(owner):
    animation = getattr(owner, "animation_data", None)
    return bool(
        animation
        and (
            animation.action
            or len(animation.nla_tracks)
            or len(animation.drivers)
        )
    )


def _flat_matrix(matrix):
    return [matrix[row][column] for row in range(4) for column in range(4)]


def _matrix_from_flat(values):
    return Matrix((
        values[0:4], values[4:8], values[8:12], values[12:16],
    ))


def _evaluated_pose_matrices(obj, names=None):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    allowed = set(names) if names is not None else None
    return {
        bone.name: bone.matrix.copy()
        for bone in evaluated.pose.bones
        if allowed is None or bone.name in allowed
    }


def _snapshot_pose_reference(obj):
    matrices = _evaluated_pose_matrices(obj)
    return {
        "matrices": {name: _flat_matrix(matrix) for name, matrix in matrices.items()},
        "bones": {
            bone.name: {
                "hide": bool(bone.hide),
                "lock_location": list(obj.pose.bones[bone.name].lock_location),
                "lock_rotation": list(obj.pose.bones[bone.name].lock_rotation),
                "lock_scale": list(obj.pose.bones[bone.name].lock_scale),
                "ik_stretch": float(obj.pose.bones[bone.name].ik_stretch),
            }
            for bone in obj.data.bones
            if not bone.name.startswith(CONTROL_PREFIX)
        },
        "show_in_front": bool(obj.show_in_front),
    }


def _read_snapshot(obj):
    raw = obj.get(SNAPSHOT_KEY, "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _control_manifest():
    owners = (
        "Root", "Hips", "Spine1", "Spine2", "Chest", "Head",
        "LeftForeArm", "LeftHand", "RightForeArm", "RightHand",
        "LeftShin", "LeftFoot", "RightShin", "RightFoot",
    )
    controls = (
        CTRL_ROOT, CTRL_HIPS, CTRL_SPINE1, CTRL_SPINE2, CTRL_CHEST,
        CTRL_HEAD, CTRL_HAND_L, CTRL_HAND_R, CTRL_ELBOW_L, CTRL_ELBOW_R,
        CTRL_FOOT_L, CTRL_FOOT_R, CTRL_KNEE_L, CTRL_KNEE_R,
    )
    return {
        "bones": list(controls),
        "constraints": [
            [owner, CONSTRAINT_PREFIX + owner] for owner in owners
        ],
        "bone_collection": CONTROL_COLLECTION,
    }


def _read_manifest(obj):
    raw = obj.get(MANIFEST_KEY, "")
    if not raw:
        return None
    try:
        manifest = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _pose_reference_problem(obj):
    """Return why a PoseRef is unsafe to edit, or an empty string."""
    if obj.data.users != 1:
        return "The Pose Ref must use its own Armature data."
    if obj.parent:
        return "The Pose Ref must not have an object parent."
    if obj.constraints:
        return "The Pose Ref must not have object constraints."
    if obj.modifiers:
        return "The Pose Ref must not have modifiers."
    if _has_animation(obj) or _has_animation(obj.data):
        return "Pose Controls require a frozen Full-Body Pose Ref without animation."
    if any(bone.name.startswith(CONTROL_PREFIX) for bone in obj.data.bones):
        return f"A bone already uses the reserved name prefix {CONTROL_PREFIX}."
    if obj.data.collections.get(CONTROL_COLLECTION):
        return f"A bone collection named {CONTROL_COLLECTION} already exists."
    if any(
        constraint.name.startswith(CONSTRAINT_PREFIX)
        for pose_bone in obj.pose.bones
        for constraint in pose_bone.constraints
    ):
        return f"A constraint already uses the reserved name prefix {CONSTRAINT_PREFIX}."
    if any(pose_bone.constraints for pose_bone in obj.pose.bones):
        return "The frozen Pose Ref must not contain pose-bone constraints."
    if any(key in obj for key in (SNAPSHOT_KEY, MANIFEST_KEY, VERSION_KEY)):
        return "The Pose Ref contains incomplete Pose Control data."
    return ""


def _activate_armature(context, obj, mode='OBJECT'):
    active = context.view_layer.objects.active
    if active and active.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    obj.hide_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    if mode != 'OBJECT':
        bpy.ops.object.mode_set(mode=mode)


def _character_scale(obj, original_names):
    points = []
    for name in original_names:
        bone = obj.pose.bones.get(name)
        if bone:
            points.extend((bone.head.copy(), bone.tail.copy()))
    if not points:
        return 1.0
    minimum = Vector((
        min(point.x for point in points),
        min(point.y for point in points),
        min(point.z for point in points),
    ))
    maximum = Vector((
        max(point.x for point in points),
        max(point.y for point in points),
        max(point.z for point in points),
    ))
    return max((maximum - minimum).length, 0.5)


def _normalized_pose_matrix(matrix, translation=None):
    result = matrix.to_quaternion().to_matrix().to_4x4()
    result.translation = matrix.translation if translation is None else translation
    return result


def _pole_matrix(obj, upper_name, lower_name, fallback_matrix):
    upper = obj.pose.bones[upper_name]
    lower = obj.pose.bones[lower_name]
    start = upper.head.copy()
    joint = lower.head.copy()
    end = lower.tail.copy()
    chain = end - start
    if chain.length_squared < 1.0e-10:
        direction = fallback_matrix.to_3x3() @ Vector((1.0, 0.0, 0.0))
    else:
        projected = start + chain * ((joint - start).dot(chain) / chain.length_squared)
        direction = joint - projected
        if direction.length_squared < 1.0e-10:
            direction = fallback_matrix.to_3x3() @ Vector((1.0, 0.0, 0.0))
    direction.normalize()
    distance = max(upper.length + lower.length, 0.2)
    return _normalized_pose_matrix(fallback_matrix, projected + direction * distance)


def _control_matrices(obj, pose_matrices):
    root_matrix = pose_matrices.get("Root", pose_matrices["Hips"])
    return {
        CTRL_ROOT: _normalized_pose_matrix(root_matrix),
        CTRL_HIPS: _normalized_pose_matrix(pose_matrices["Hips"]),
        CTRL_SPINE1: _normalized_pose_matrix(pose_matrices["Spine1"]),
        CTRL_SPINE2: _normalized_pose_matrix(pose_matrices["Spine2"]),
        CTRL_CHEST: _normalized_pose_matrix(pose_matrices["Chest"]),
        CTRL_HEAD: _normalized_pose_matrix(pose_matrices["Head"]),
        CTRL_HAND_L: _normalized_pose_matrix(pose_matrices["LeftHand"]),
        CTRL_HAND_R: _normalized_pose_matrix(pose_matrices["RightHand"]),
        CTRL_ELBOW_L: _pole_matrix(
            obj, "LeftArm", "LeftForeArm", pose_matrices["LeftForeArm"]),
        CTRL_ELBOW_R: _pole_matrix(
            obj, "RightArm", "RightForeArm", pose_matrices["RightForeArm"]),
        CTRL_FOOT_L: _normalized_pose_matrix(pose_matrices["LeftFoot"]),
        CTRL_FOOT_R: _normalized_pose_matrix(pose_matrices["RightFoot"]),
        CTRL_KNEE_L: _pole_matrix(
            obj, "LeftLeg", "LeftShin", pose_matrices["LeftShin"]),
        CTRL_KNEE_R: _pole_matrix(
            obj, "RightLeg", "RightShin", pose_matrices["RightShin"]),
    }


def _create_edit_control(armature, name, matrix, length):
    bone = armature.edit_bones.new(name)
    bone.matrix = matrix
    bone.length = max(length, 0.01)
    bone.use_deform = False
    bone.use_connect = False
    return bone


def _ensure_widget_collection(scene):
    collection = bpy.data.collections.get(WIDGET_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(WIDGET_COLLECTION)
    if not any(child == collection for child in scene.collection.children):
        try:
            scene.collection.children.link(collection)
        except RuntimeError:
            pass
    collection.hide_render = True
    collection.hide_viewport = True
    return collection


def _ensure_widget(scene, name, vertices, edges):
    obj = bpy.data.objects.get(name)
    if obj and obj.type == 'MESH':
        return obj
    collection = _ensure_widget_collection(scene)
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(vertices, edges, [])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.hide_render = True
    obj.hide_select = True
    obj[WIDGET_MARKER] = True
    return obj


def _widgets(scene):
    circle = []
    circle_edges = []
    for index in range(16):
        angle = math.tau * index / 16
        circle.append((math.cos(angle), 0.0, math.sin(angle)))
        circle_edges.append((index, (index + 1) % 16))

    box_vertices = [
        (-1, -0.35, -0.7), (-1, -0.35, 0.7),
        (-1, 0.35, -0.7), (-1, 0.35, 0.7),
        (1, -0.35, -0.7), (1, -0.35, 0.7),
        (1, 0.35, -0.7), (1, 0.35, 0.7),
    ]
    box_edges = [
        (0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3),
        (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7),
    ]
    diamond_vertices = [
        (0, 0, 1), (1, 0, 0), (0, 0, -1), (-1, 0, 0),
        (0, 0.5, 0), (0, -0.5, 0),
    ]
    diamond_edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (0, 4), (1, 4), (2, 4), (3, 4),
        (0, 5), (1, 5), (2, 5), (3, 5),
    ]
    return {
        "circle": _ensure_widget(
            scene, "WGT_Kimodo_Pose_Circle", circle, circle_edges),
        "box": _ensure_widget(
            scene, "WGT_Kimodo_Pose_Box", box_vertices, box_edges),
        "diamond": _ensure_widget(
            scene, "WGT_Kimodo_Pose_Pole", diamond_vertices, diamond_edges),
    }


def _configure_control_bones(obj, scale):
    widgets = _widgets(bpy.context.scene)
    widget_for = {
        CTRL_ROOT: (widgets["circle"], 0.18),
        CTRL_HIPS: (widgets["box"], 0.13),
        CTRL_SPINE1: (widgets["circle"], 0.105),
        CTRL_SPINE2: (widgets["circle"], 0.11),
        CTRL_CHEST: (widgets["circle"], 0.12),
        CTRL_HEAD: (widgets["circle"], 0.10),
        CTRL_HAND_L: (widgets["box"], 0.075),
        CTRL_HAND_R: (widgets["box"], 0.075),
        CTRL_FOOT_L: (widgets["box"], 0.09),
        CTRL_FOOT_R: (widgets["box"], 0.09),
        CTRL_ELBOW_L: (widgets["diamond"], 0.06),
        CTRL_ELBOW_R: (widgets["diamond"], 0.06),
        CTRL_KNEE_L: (widgets["diamond"], 0.06),
        CTRL_KNEE_R: (widgets["diamond"], 0.06),
    }
    collection = obj.data.collections.get(CONTROL_COLLECTION)
    if collection is None:
        collection = obj.data.collections.new(CONTROL_COLLECTION)
    collection.is_visible = True

    for name, (widget, size_factor) in widget_for.items():
        data_bone = obj.data.bones.get(name)
        pose_bone = obj.pose.bones.get(name)
        if not data_bone or not pose_bone:
            continue
        collection.assign(data_bone)
        try:
            data_bone.color.palette = 'THEME04'
        except (AttributeError, TypeError):
            pass
        pose_bone.custom_shape = widget
        pose_bone.use_custom_shape_bone_size = False
        size = scale * size_factor
        pose_bone.custom_shape_scale_xyz = (size, size, size)
        pose_bone.lock_scale = (True, True, True)

    for name in (CTRL_SPINE1, CTRL_SPINE2, CTRL_CHEST, CTRL_HEAD):
        obj.pose.bones[name].lock_location = (True, True, True)
    for name in (CTRL_ELBOW_L, CTRL_ELBOW_R, CTRL_KNEE_L, CTRL_KNEE_R):
        obj.pose.bones[name].lock_rotation = (True, True, True)


def _add_delta_transform_constraint(obj, owner_name, control_name):
    owner = obj.pose.bones[owner_name]
    constraint = owner.constraints.new('COPY_TRANSFORMS')
    constraint.name = CONSTRAINT_PREFIX + owner_name
    constraint.target = obj
    constraint.subtarget = control_name
    constraint.owner_space = 'LOCAL'
    constraint.target_space = 'LOCAL'
    constraint.mix_mode = 'AFTER_FULL'
    return constraint


def _add_delta_rotation_constraint(obj, owner_name, control_name):
    owner = obj.pose.bones[owner_name]
    constraint = owner.constraints.new('COPY_ROTATION')
    constraint.name = CONSTRAINT_PREFIX + owner_name
    constraint.target = obj
    constraint.subtarget = control_name
    constraint.owner_space = 'LOCAL'
    constraint.target_space = 'LOCAL_OWNER_ORIENT'
    constraint.mix_mode = 'ADD'
    return constraint


def _add_ik_constraint(obj, lower_name, target_name, pole_name):
    owner = obj.pose.bones[lower_name]
    constraint = owner.constraints.new('IK')
    constraint.name = CONSTRAINT_PREFIX + lower_name
    constraint.target = obj
    constraint.subtarget = target_name
    constraint.pole_target = obj
    constraint.pole_subtarget = pole_name
    constraint.chain_count = 2
    constraint.use_tail = True
    if hasattr(constraint, "use_rotation"):
        constraint.use_rotation = False
    if hasattr(constraint, "use_stretch"):
        constraint.use_stretch = False
    return constraint


def _rotation_error(left, right):
    difference = left.to_quaternion().rotation_difference(right.to_quaternion())
    angle = difference.angle
    return min(abs(angle), abs(math.tau - angle))


def _matrix_delta(left, right):
    return max(
        abs(left[row][column] - right[row][column])
        for row in range(4)
        for column in range(4)
    )


def _calibrate_pole(obj, constraint, upper_name, lower_name, expected):
    """Iteratively align the IK bend plane to the captured Kimodo pose."""
    upper = obj.pose.bones[upper_name]
    lower = obj.pose.bones[lower_name]
    target = obj.pose.bones[constraint.subtarget]

    start = upper.head.copy()
    end = target.head.copy()
    axis = end - start
    if axis.length_squared < 1.0e-10:
        return
    axis.normalize()
    original_joint = expected[lower_name].translation
    original_projection = start + axis * (original_joint - start).dot(axis)
    original_bend = original_joint - original_projection
    if original_bend.length_squared < 1.0e-10:
        return
    original_bend.normalize()

    for _ in range(24):
        bpy.context.view_layer.update()
        solved_joint = lower.head.copy()
        solved_projection = start + axis * (solved_joint - start).dot(axis)
        solved_bend = solved_joint - solved_projection
        if solved_bend.length_squared < 1.0e-10:
            break
        solved_bend.normalize()
        correction = math.atan2(
            axis.dot(solved_bend.cross(original_bend)),
            max(-1.0, min(1.0, solved_bend.dot(original_bend))),
        )
        constraint.pole_angle += correction
        if abs(correction) < 1.0e-7:
            break
    constraint.pole_angle = ((constraint.pole_angle + math.pi) % math.tau) - math.pi
    bpy.context.view_layer.update()


def _build_constraints(obj, original_matrices):
    if "Root" in obj.pose.bones:
        _add_delta_transform_constraint(obj, "Root", CTRL_ROOT)
    _add_delta_transform_constraint(obj, "Hips", CTRL_HIPS)
    _add_delta_rotation_constraint(obj, "Spine1", CTRL_SPINE1)
    _add_delta_rotation_constraint(obj, "Spine2", CTRL_SPINE2)
    _add_delta_rotation_constraint(obj, "Chest", CTRL_CHEST)
    _add_delta_rotation_constraint(obj, "Head", CTRL_HEAD)

    chains = (
        ("LeftArm", "LeftForeArm", CTRL_HAND_L, CTRL_ELBOW_L, "LeftHand"),
        ("RightArm", "RightForeArm", CTRL_HAND_R, CTRL_ELBOW_R, "RightHand"),
        ("LeftLeg", "LeftShin", CTRL_FOOT_L, CTRL_KNEE_L, "LeftFoot"),
        ("RightLeg", "RightShin", CTRL_FOOT_R, CTRL_KNEE_R, "RightFoot"),
    )
    for upper, lower, target, pole, end_bone in chains:
        obj.pose.bones[upper].ik_stretch = 0.0
        obj.pose.bones[lower].ik_stretch = 0.0
        ik = _add_ik_constraint(obj, lower, target, pole)
        _calibrate_pole(obj, ik, upper, lower, original_matrices)
        _add_delta_rotation_constraint(obj, end_bone, target)


def _remove_own_constraints(obj):
    manifest = _read_manifest(obj)
    if manifest:
        for owner_name, constraint_name in manifest.get("constraints", ()):
            pose_bone = obj.pose.bones.get(owner_name)
            if not pose_bone:
                continue
            constraint = pose_bone.constraints.get(constraint_name)
            if constraint:
                pose_bone.constraints.remove(constraint)
        return

    # Recovery path for an interrupted build from an older add-on version.
    for pose_bone in obj.pose.bones:
        for constraint in list(pose_bone.constraints):
            if constraint.name.startswith(CONSTRAINT_PREFIX):
                pose_bone.constraints.remove(constraint)


def _apply_pose_matrices(obj, matrices):
    def depth(pose_bone):
        value = 0
        parent = pose_bone.parent
        while parent is not None:
            value += 1
            parent = parent.parent
        return value

    for pose_bone in sorted(obj.pose.bones, key=depth):
        matrix = matrices.get(pose_bone.name)
        if matrix is None or pose_bone.name.startswith(CONTROL_PREFIX):
            continue
        pose_bone.matrix = matrix
        bpy.context.view_layer.update()


def _restore_bone_settings(obj, snapshot):
    for name, values in snapshot.get("bones", {}).items():
        data_bone = obj.data.bones.get(name)
        pose_bone = obj.pose.bones.get(name)
        if not data_bone or not pose_bone:
            continue
        data_bone.hide = bool(values.get("hide", False))
        pose_bone.lock_location = values.get("lock_location", (False, False, False))
        pose_bone.lock_rotation = values.get("lock_rotation", (False, False, False))
        pose_bone.lock_scale = values.get("lock_scale", (False, False, False))
        pose_bone.ik_stretch = float(values.get("ik_stretch", 1.0))
    obj.show_in_front = bool(snapshot.get("show_in_front", True))


def _cleanup_widgets():
    used = {
        pose_bone.custom_shape
        for armature in (obj for obj in bpy.data.objects if obj.type == 'ARMATURE')
        for pose_bone in armature.pose.bones
        if pose_bone.custom_shape
    }
    for obj in list(bpy.data.objects):
        if obj.get(WIDGET_MARKER) and obj not in used:
            mesh = obj.data if obj.type == 'MESH' else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    collection = bpy.data.collections.get(WIDGET_COLLECTION)
    if collection and not collection.objects:
        for scene in bpy.data.scenes:
            if collection in scene.collection.children.values():
                scene.collection.children.unlink(collection)
        for parent in bpy.data.collections:
            if parent != collection and collection in parent.children.values():
                parent.children.unlink(collection)
        if collection.users == 0:
            bpy.data.collections.remove(collection)


def _finish_controls(context, obj, mode):
    snapshot = _read_snapshot(obj)
    if snapshot is None:
        raise RuntimeError("The original PoseRef snapshot is missing.")
    manifest = _read_manifest(obj) or {}

    if mode == 'REVERT':
        desired = {
            name: _matrix_from_flat(values)
            for name, values in snapshot["matrices"].items()
        }
    else:
        original_names = snapshot["matrices"].keys()
        desired = _evaluated_pose_matrices(obj, original_names)

    _activate_armature(context, obj, 'OBJECT')
    _remove_own_constraints(obj)
    bpy.ops.object.mode_set(mode='EDIT')
    control_names = set(manifest.get("bones", ()))
    if not control_names:
        control_names = {
            edit_bone.name for edit_bone in obj.data.edit_bones
            if edit_bone.name.startswith(CONTROL_PREFIX)
        }
    for name in control_names:
        edit_bone = obj.data.edit_bones.get(name)
        if edit_bone:
            obj.data.edit_bones.remove(edit_bone)
    bpy.ops.object.mode_set(mode='OBJECT')

    if obj.animation_data:
        obj.animation_data_clear()
    if obj.data.animation_data:
        obj.data.animation_data_clear()
    _apply_pose_matrices(obj, desired)
    _restore_bone_settings(obj, snapshot)

    collection_name = manifest.get("bone_collection", CONTROL_COLLECTION)
    collection = obj.data.collections.get(collection_name)
    if collection:
        obj.data.collections.remove(collection)
    for key in (SNAPSHOT_KEY, MANIFEST_KEY, VERSION_KEY, SHOW_SOURCE_KEY):
        if key in obj:
            del obj[key]
    _cleanup_widgets()
    _activate_armature(context, obj, 'POSE')


def _set_source_bones_visible(obj, visible):
    snapshot = _read_snapshot(obj)
    if snapshot is None:
        return
    for name, values in snapshot.get("bones", {}).items():
        bone = obj.data.bones.get(name)
        if bone:
            bone.hide = bool(values.get("hide", False)) if visible else True
    for bone in obj.data.bones:
        if bone.name.startswith(CONTROL_PREFIX):
            bone.hide = False
    obj[SHOW_SOURCE_KEY] = bool(visible)


class KIMODO_OT_BuildPoseControls(Operator):
    """Add disposable IK/FK-style controls to a frozen Kimodo PoseRef"""

    bl_idname = "kimodo.build_pose_controls"
    bl_label = "Build Pose Controls"
    bl_options = {'REGISTER', 'UNDO'}

    target_name: StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        obj = _resolve_pose_reference(context)
        return bool(obj and not _has_controls(obj))

    def execute(self, context):
        obj = _resolve_pose_reference(context, self.target_name)
        if not obj:
            self.report({'ERROR'}, "Select a frozen Full-Body Pose Ref first.")
            return {'CANCELLED'}
        if _has_controls(obj):
            self.report({'INFO'}, "Pose controls already exist on this reference.")
            return {'FINISHED'}

        missing = [name for name in REQUIRED_BONES if name not in obj.pose.bones]
        if missing:
            self.report({'ERROR'}, "Missing Kimodo bones: " + ", ".join(missing))
            return {'CANCELLED'}
        problem = _pose_reference_problem(obj)
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}

        snapshot = _snapshot_pose_reference(obj)
        original_matrices = {
            name: _matrix_from_flat(values)
            for name, values in snapshot["matrices"].items()
        }
        obj[SNAPSHOT_KEY] = json.dumps(snapshot, separators=(",", ":"))
        obj[MANIFEST_KEY] = json.dumps(_control_manifest(), separators=(",", ":"))
        obj[VERSION_KEY] = CONTROL_VERSION
        obj[SHOW_SOURCE_KEY] = False

        try:
            _activate_armature(context, obj, 'OBJECT')
            scale = _character_scale(obj, snapshot["matrices"].keys())
            matrices = _control_matrices(obj, original_matrices)
            bpy.ops.object.mode_set(mode='EDIT')
            controls = {}
            for name, matrix in matrices.items():
                controls[name] = _create_edit_control(
                    obj.data, name, matrix, scale * 0.08)

            parents = {
                CTRL_HIPS: CTRL_ROOT,
                CTRL_SPINE1: CTRL_HIPS,
                CTRL_SPINE2: CTRL_SPINE1,
                CTRL_CHEST: CTRL_SPINE2,
                CTRL_HEAD: CTRL_CHEST,
                CTRL_HAND_L: CTRL_ROOT,
                CTRL_HAND_R: CTRL_ROOT,
                CTRL_ELBOW_L: CTRL_ROOT,
                CTRL_ELBOW_R: CTRL_ROOT,
                CTRL_FOOT_L: CTRL_ROOT,
                CTRL_FOOT_R: CTRL_ROOT,
                CTRL_KNEE_L: CTRL_ROOT,
                CTRL_KNEE_R: CTRL_ROOT,
            }
            for child_name, parent_name in parents.items():
                controls[child_name].parent = controls[parent_name]
                controls[child_name].use_connect = False
            # Assigning an EditBone parent changes its armature-space rest
            # matrix. Re-apply every captured absolute matrix after parenting
            # so widgets and IK targets exactly match the frozen PoseRef.
            for name, matrix in matrices.items():
                controls[name].matrix = matrix
                controls[name].length = max(scale * 0.08, 0.01)
            bpy.ops.object.mode_set(mode='POSE')

            _configure_control_bones(obj, scale)
            _build_constraints(obj, original_matrices)

            for name in snapshot["bones"]:
                pose_bone = obj.pose.bones.get(name)
                if pose_bone:
                    pose_bone.lock_location = (True, True, True)
            obj.show_in_front = True
            _set_source_bones_visible(obj, False)

            bpy.ops.pose.select_all(action='DESELECT')
            obj.pose.bones[CTRL_HIPS].select = True
            obj.data.bones.active = obj.data.bones[CTRL_HIPS]
            context.view_layer.update()

            current_matrices = _evaluated_pose_matrices(
                obj, original_matrices.keys())
            build_delta = max(
                (
                    _matrix_delta(current_matrices[name], matrix)
                    for name, matrix in original_matrices.items()
                ),
                default=0.0,
            )
            if build_delta > BUILD_TOLERANCE:
                raise RuntimeError(
                    "Control setup changed the frozen pose "
                    f"(matrix delta {build_delta:.6g})."
                )
        except Exception as exc:
            try:
                _finish_controls(context, obj, 'REVERT')
            except Exception:
                pass
            self.report({'ERROR'}, f"Failed to build Kimodo pose controls: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, "Pose controls created. Move hands/feet; use poles for elbows/knees.")
        return {'FINISHED'}


class KIMODO_OT_EnterPoseControls(Operator):
    bl_idname = "kimodo.enter_pose_controls"
    bl_label = "Enter Pose Controls"
    bl_options = {'REGISTER', 'UNDO'}

    target_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        obj = _resolve_pose_reference(context, self.target_name)
        if not _has_controls(obj):
            self.report({'ERROR'}, "This PoseRef has no Kimodo pose controls.")
            return {'CANCELLED'}
        _activate_armature(context, obj, 'POSE')
        _set_source_bones_visible(obj, bool(obj.get(SHOW_SOURCE_KEY, False)))
        bpy.ops.pose.select_all(action='DESELECT')
        obj.pose.bones[CTRL_HIPS].select = True
        obj.data.bones.active = obj.data.bones[CTRL_HIPS]
        return {'FINISHED'}


class KIMODO_OT_SelectPoseControl(Operator):
    bl_idname = "kimodo.select_pose_control"
    bl_label = "Select Pose Control"
    bl_options = {'REGISTER', 'UNDO'}

    target_name: StringProperty(options={'HIDDEN'})
    control_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        obj = _resolve_pose_reference(context, self.target_name)
        if not _has_controls(obj) or self.control_name not in obj.data.bones:
            return {'CANCELLED'}
        _activate_armature(context, obj, 'POSE')
        bpy.ops.pose.select_all(action='DESELECT')
        obj.data.bones[self.control_name].hide = False
        obj.pose.bones[self.control_name].select = True
        obj.data.bones.active = obj.data.bones[self.control_name]
        return {'FINISHED'}


class KIMODO_OT_TogglePoseSourceBones(Operator):
    bl_idname = "kimodo.toggle_pose_source_bones"
    bl_label = "Toggle Source Bones"
    bl_options = {'REGISTER', 'UNDO'}

    target_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        obj = _resolve_pose_reference(context, self.target_name)
        if not _has_controls(obj):
            return {'CANCELLED'}
        visible = not bool(obj.get(SHOW_SOURCE_KEY, False))
        _set_source_bones_visible(obj, visible)
        context.view_layer.update()
        return {'FINISHED'}


class KIMODO_OT_FinishPoseControls(Operator):
    bl_idname = "kimodo.finish_pose_controls"
    bl_label = "Finish Pose Controls"
    bl_options = {'REGISTER', 'UNDO'}

    target_name: StringProperty(options={'HIDDEN'})
    mode: EnumProperty(
        items=(
            ('BAKE', "Bake", "Keep the visible pose and remove the controls"),
            ('REVERT', "Revert", "Restore the pose from before controls were added"),
        ),
        default='BAKE',
        options={'HIDDEN'},
    )

    def execute(self, context):
        obj = _resolve_pose_reference(context, self.target_name)
        if not _has_controls(obj):
            self.report({'ERROR'}, "This PoseRef has no Kimodo pose controls.")
            return {'CANCELLED'}
        try:
            _finish_controls(context, obj, self.mode)
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to finish Kimodo pose controls: {exc}")
            return {'CANCELLED'}
        message = "Pose baked and controls removed." if self.mode == 'BAKE' else "Original pose restored."
        self.report({'INFO'}, message)
        return {'FINISHED'}


class KIMODO_PT_PoseControls(Panel):
    bl_label = "Pose Controls"
    bl_idname = "KIMODO_PT_PoseControls"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Kimodo'
    bl_parent_id = "KIMODO_PT_Constraints"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _resolve_pose_reference(context) is not None

    def draw(self, context):
        layout = self.layout
        obj = _resolve_pose_reference(context)
        if not obj:
            layout.label(text="Select a Full-Body Pose Ref", icon='INFO')
            return

        layout.label(text=obj.name, icon='ARMATURE_DATA')
        if not _has_controls(obj):
            box = layout.box()
            box.label(text="Create disposable controls for this Pose Ref.")
            box.label(text="The original Kimodo pose is saved first.", icon='INFO')
            op = box.operator(
                "kimodo.build_pose_controls",
                text="Build Pose Controls",
                icon='CONSTRAINT_BONE',
            )
            op.target_name = obj.name
            return

        row = layout.row(align=True)
        op = row.operator("kimodo.enter_pose_controls", text="Pose Mode", icon='POSE_HLT')
        op.target_name = obj.name
        visible = bool(obj.get(SHOW_SOURCE_KEY, False))
        op = row.operator(
            "kimodo.toggle_pose_source_bones",
            text="Hide Bones" if visible else "Show Bones",
            icon='HIDE_OFF' if not visible else 'HIDE_ON',
        )
        op.target_name = obj.name

        layout.label(text="Quick Select:")
        grid = layout.grid_flow(row_major=True, columns=4, even_columns=True, align=True)
        for control_name, label, icon in CONTROL_LABELS:
            op = grid.operator("kimodo.select_pose_control", text=label, icon=icon)
            op.target_name = obj.name
            op.control_name = control_name

        poles = layout.row(align=True)
        for control_name, label in (
            (CTRL_ELBOW_L, "L.Elbow"), (CTRL_ELBOW_R, "R.Elbow"),
            (CTRL_KNEE_L, "L.Knee"), (CTRL_KNEE_R, "R.Knee"),
        ):
            op = poles.operator("kimodo.select_pose_control", text=label)
            op.target_name = obj.name
            op.control_name = control_name

        tip = layout.box()
        tip.label(text="G: move IK / pole controls", icon='INFO')
        tip.label(text="R: rotate hips, chest, head, hands or feet")

        row = layout.row(align=True)
        op = row.operator(
            "kimodo.finish_pose_controls",
            text="Bake Pose & Remove",
            icon='CHECKMARK',
        )
        op.target_name = obj.name
        op.mode = 'BAKE'
        op = row.operator(
            "kimodo.finish_pose_controls",
            text="Revert",
            icon='LOOP_BACK',
        )
        op.target_name = obj.name
        op.mode = 'REVERT'


CLASSES = (
    KIMODO_OT_BuildPoseControls,
    KIMODO_OT_EnterPoseControls,
    KIMODO_OT_SelectPoseControl,
    KIMODO_OT_TogglePoseSourceBones,
    KIMODO_OT_FinishPoseControls,
    KIMODO_PT_PoseControls,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
