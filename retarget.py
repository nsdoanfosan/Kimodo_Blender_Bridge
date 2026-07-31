"""
Kimodo Blender Bridge — Retargeting
Constraint-based motion retargeting from Kimodo armature → user's rig.

Three modes per bone pair
--------------------------
COPY_ROTATION   Copy Rotation in WORLD space.
                Root bone additionally gets Copy Location.
                Good for rigs with the same rest pose as Kimodo.

COPY_TRANSFORMS Copy Transforms in LOCAL space (loc + rot + scale together).
                Simpler than the split loc/rot approach; useful when the
                target rig's bone lengths don't match the source.

CHILD_OF        Full parent-child relationship via a Child Of constraint.
                Set Inverse is calculated automatically so applying the
                constraint does not snap an offset target armature.

CHILD_OF_ROTATION  Backward-compatible id for Local Rotation. Uses Copy
                Rotation in LOCAL_OWNER_ORIENT space to compensate bone-axis
                differences without changing location or scale.

Baking
-------
Blender's NLA bake (visual_keying=True) is used to push the constraint-
driven animation into actual keyframes; the constraints are cleared
afterwards so the rig is fully self-contained.
"""

import bpy
import json
import mathutils
import re

from . import retarget_presets


CONSTRAINT_PREFIX = "KIMODO_"   # prefix for all constraints we add


# ---------------------------------------------------------------------------
# Bone name auto-matching
# ---------------------------------------------------------------------------

# Common bone name pairs: (kimodo/bvh_name, common_rig_names...)
# Kimodo SOMA skeleton uses these bone names (based on BVH output conventions).
# These are heuristic — the user can always override in the UI.
_SOMA_BONE_MAP_HINTS = [
    # Kimodo name        # common alternatives in user rigs
    ("Root",            ["root", "CC_Base_BoneRoot", "RL_BoneRoot"]),
    ("Hips",            ["hips", "pelvis", "Hip", "Pelvis", "CC_Base_Hip", "mixamorig:Hips"]),
    ("Spine1",          ["spine", "spine_01", "CC_Base_Waist", "mixamorig:Spine"]),
    ("Spine2",          ["spine1", "spine_02", "CC_Base_Spine01", "mixamorig:Spine1"]),
    ("Chest",           ["spine2", "spine_03", "chest", "CC_Base_Spine02", "mixamorig:Spine2"]),
    ("Neck1",           ["neck", "neck_01", "CC_Base_NeckTwist01", "mixamorig:Neck"]),
    ("Neck2",           ["neck1", "neck_02", "CC_Base_NeckTwist02"]),
    ("Head",            ["head", "Head", "mixamorig:Head"]),
    ("LeftShoulder",    ["l_shoulder", "shoulder.L", "mixamorig:LeftShoulder", "LeftShoulder"]),
    ("LeftArm",         ["upper_arm.L", "l_arm", "mixamorig:LeftArm", "LeftUpArm"]),
    ("LeftForeArm",     ["forearm.L", "l_forearm", "mixamorig:LeftForeArm"]),
    ("LeftHand",        ["hand.L", "l_hand", "mixamorig:LeftHand"]),
    ("RightShoulder",   ["r_shoulder", "shoulder.R", "mixamorig:RightShoulder", "RightShoulder"]),
    ("RightArm",        ["upper_arm.R", "r_arm", "mixamorig:RightArm", "RightUpArm"]),
    ("RightForeArm",    ["forearm.R", "r_forearm", "mixamorig:RightForeArm"]),
    ("RightHand",       ["hand.R", "r_hand", "mixamorig:RightHand"]),
    ("LeftLeg",         ["thigh.L", "l_thigh", "thigh_l", "CC_Base_L_Thigh", "mixamorig:LeftUpLeg", "LeftThigh"]),
    ("LeftShin",        ["shin.L", "l_shin", "calf_l", "CC_Base_L_Calf", "mixamorig:LeftLeg", "LeftShin"]),
    ("LeftFoot",        ["foot.L", "l_foot", "mixamorig:LeftFoot"]),
    ("LeftToeBase",     ["toe.L", "l_toe", "mixamorig:LeftToeBase"]),
    ("RightLeg",        ["thigh.R", "r_thigh", "thigh_r", "CC_Base_R_Thigh", "mixamorig:RightUpLeg", "RightThigh"]),
    ("RightShin",       ["shin.R", "r_shin", "calf_r", "CC_Base_R_Calf", "mixamorig:RightLeg", "RightShin"]),
    ("RightFoot",       ["foot.R", "r_foot", "mixamorig:RightFoot"]),
    ("RightToeBase",    ["toe.R", "r_toe", "mixamorig:RightToeBase"]),
]

_SMPLX_EXTRA_HINTS = [
    ("LeftHandIndex1",  ["f_index.01.L", "mixamorig:LeftHandIndex1"]),
    ("RightHandIndex1", ["f_index.01.R", "mixamorig:RightHandIndex1"]),
    ("LeftHandThumb1",  ["thumb.01.L",   "mixamorig:LeftHandThumb1"]),
    ("RightHandThumb1", ["thumb.01.R",   "mixamorig:RightHandThumb1"]),
    ("LeftHandMiddle1", ["f_middle.01.L","mixamorig:LeftHandMiddle1"]),
    ("RightHandMiddle1",["f_middle.01.R","mixamorig:RightHandMiddle1"]),
    ("LeftHandRing1",   ["f_ring.01.L",  "mixamorig:LeftHandRing1"]),
    ("RightHandRing1",  ["f_ring.01.R",  "mixamorig:RightHandRing1"]),
    ("LeftHandPinky1",  ["f_pinky.01.L", "mixamorig:LeftHandPinky1"]),
    ("RightHandPinky1", ["f_pinky.01.R", "mixamorig:RightHandPinky1"]),
]


def _normalize(name: str) -> str:
    """Lowercase, strip prefix up to ':', remove non-alphanumeric."""
    name = name.lower()
    if ":" in name:
        name = name.split(":")[-1]
    return re.sub(r"[^a-z0-9]", "", name)


def auto_build_mapping(source_arm: bpy.types.Object,
                       target_arm: bpy.types.Object,
                       model: str = "smpl") -> list[tuple[str, str]]:
    """
    Attempt to auto-match bones between source (Kimodo) and target (user) armatures.
    Returns list of (source_bone_name, target_bone_name) pairs.
    """
    hints = _SOMA_BONE_MAP_HINTS[:]
    if model == "smplx":
        hints += _SMPLX_EXTRA_HINTS

    src_bones = {b.name for b in source_arm.data.bones}
    tgt_bones = {b.name: _normalize(b.name) for b in target_arm.data.bones}

    result = []
    for src_name, alternatives in hints:
        if src_name not in src_bones:
            continue
        # Try exact match first
        matched = None
        for tgt_name in target_arm.data.bones.keys():
            if tgt_name == src_name:
                matched = tgt_name
                break
        # Try normalized match
        if not matched:
            src_norm = _normalize(src_name)
            for tgt_name, tgt_norm in tgt_bones.items():
                if src_norm == tgt_norm:
                    matched = tgt_name
                    break
        # Try alternatives
        if not matched:
            for alt in alternatives:
                if alt in tgt_bones:
                    matched = alt
                    break
                alt_norm = _normalize(alt)
                for tgt_name, tgt_norm in tgt_bones.items():
                    if alt_norm == tgt_norm:
                        matched = tgt_name
                        break
                if matched:
                    break
        if matched:
            result.append((src_name, matched))

    return result


def build_profile_mapping(source_arm: bpy.types.Object,
                          target_arm: bpy.types.Object,
                          profile_id: str = "AUTO") -> dict:
    """Build an official-profile mapping filtered to bones present in both rigs."""
    return retarget_presets.build_mapping(
        source_arm.data.bones.keys(),
        target_arm.data.bones.keys(),
        profile_id,
    )


def detect_target_profile(target_arm: bpy.types.Object) -> str:
    """Detect CC Base or UE5 from authoritative marker bones."""
    return retarget_presets.detect_profile(target_arm.data.bones.keys())


def profile_label(profile_id: str) -> str:
    profile = retarget_presets.PROFILES.get(profile_id)
    return profile["label"] if profile else "Unknown"


# ---------------------------------------------------------------------------
# Constraint setup
# ---------------------------------------------------------------------------

def apply_retargeting_constraints(
    source_arm: bpy.types.Object,
    target_arm: bpy.types.Object,
    bone_pairs: "list[tuple]",  # (src, tgt, enabled, mode[, inherit_rotation])
    root_bone: str = "",
) -> "tuple[int, list[str]]":
    """
    Add retargeting constraints to each enabled bone pair.
    Returns (n_applied, [warning_messages]).

    bone_pairs tuples: (source_bone, target_bone, enabled, retarget_mode
                        [, inherit_rotation])
    retarget_mode:  'COPY_ROTATION' | 'COPY_TRANSFORMS' | 'CHILD_OF'
                    | 'CHILD_OF_ROTATION'
    inherit_rotation (optional bool): when provided, sets the target bone's
                    'Inherit Rotation' (use_inherit_rotation) property.
    """
    source_arm.hide_viewport = False
    target_arm.hide_viewport = False

    tgt_pose = target_arm.pose
    applied  = 0
    warnings = []

    for entry in bone_pairs:
        # Accept 3-tuples (legacy), 4-tuples (with mode) and 5-tuples
        # (with an inherit-rotation override).
        inherit_rotation = None
        if len(entry) == 5:
            src_name, tgt_name, enabled, mode, inherit_rotation = entry
        elif len(entry) == 4:
            src_name, tgt_name, enabled, mode = entry
        else:
            src_name, tgt_name, enabled = entry
            mode = "COPY_ROTATION"

        if not enabled:
            continue

        tgt_pbone = tgt_pose.bones.get(tgt_name)
        if not tgt_pbone:
            warnings.append(f"Target bone '{tgt_name}' not found — skipped.")
            continue
        if src_name not in source_arm.data.bones:
            warnings.append(f"Source bone '{src_name}' not in Kimodo armature — skipped.")
            continue

        # Apply the per-bone 'Inherit Rotation' override on the armature data.
        if inherit_rotation is not None:
            data_bone = target_arm.data.bones.get(tgt_name)
            if data_bone is not None:
                data_bone.use_inherit_rotation = inherit_rotation

        # Clear previous Kimodo constraints on this bone
        for c in list(tgt_pbone.constraints):
            if c.name.startswith(CONSTRAINT_PREFIX):
                tgt_pbone.constraints.remove(c)

        is_root = (tgt_name == root_bone) or (src_name.lower() in ("hips", "pelvis", "root"))

        if mode == "COPY_ROTATION":
            _add_copy_rotation(tgt_pbone, source_arm, src_name, is_root)

        elif mode == "COPY_TRANSFORMS":
            _add_copy_transforms(tgt_pbone, source_arm, src_name)

        elif mode == "CHILD_OF":
            _add_child_of(tgt_pbone, source_arm, src_name)

        elif mode == "CHILD_OF_ROTATION":
            _add_child_of(tgt_pbone, source_arm, src_name, rotation_only=True)

        else:
            warnings.append(f"Unknown retarget mode '{mode}' for '{tgt_name}' — using Copy Rotation.")
            _add_copy_rotation(tgt_pbone, source_arm, src_name, is_root)

        applied += 1

    return applied, warnings


# ---------------------------------------------------------------------------
# Per-mode helpers
# ---------------------------------------------------------------------------

def _add_copy_rotation(pbone, source_arm, src_name: str, is_root: bool = False) -> None:
    """Copy Rotation in local space; root bone also gets Copy Location."""
    if is_root:
        loc = pbone.constraints.new("COPY_LOCATION")
        loc.name          = CONSTRAINT_PREFIX + "Location"
        loc.target        = source_arm
        loc.subtarget     = src_name
        loc.use_offset    = False

    rot = pbone.constraints.new("COPY_ROTATION")
    rot.name         = CONSTRAINT_PREFIX + "Rotation"
    rot.target       = source_arm
    rot.subtarget    = src_name
    rot.mix_mode     = 'REPLACE'
    rot.owner_space  = 'WORLD'
    rot.target_space = 'WORLD'


def _add_copy_transforms(pbone, source_arm, src_name: str) -> None:
    """Copy Transforms in local space (location + rotation + scale)."""
    ct = pbone.constraints.new("COPY_TRANSFORMS")
    ct.name         = CONSTRAINT_PREFIX + "CopyTransforms"
    ct.target       = source_arm
    ct.subtarget    = src_name
    ct.mix_mode     = 'REPLACE'
    ct.owner_space  = 'LOCAL'
    ct.target_space = 'LOCAL'


def _add_child_of(pbone, source_arm, src_name: str, rotation_only: bool = False) -> None:
    """
    Child Of constraint with the inverse matrix set automatically.
    Equivalent to clicking 'Set Inverse' in the UI: stores the inverse of
    the source bone's current world matrix so the target bone doesn't jump
    when the constraint activates.

    When *rotation_only* is True, use Copy Rotation in
    ``LOCAL_OWNER_ORIENT`` space. Blender's Child Of location-axis toggles
    can still offset a pose bone when its armature object is away from the
    world origin; Local Owner Orientation maps bone axes without changing
    location.
    """
    if rotation_only:
        rotation = pbone.constraints.new("COPY_ROTATION")
        rotation.name = CONSTRAINT_PREFIX + "LocalOwnerRotation"
        rotation.target = source_arm
        rotation.subtarget = src_name
        rotation.mix_mode = "REPLACE"
        rotation.owner_space = "LOCAL"
        rotation.target_space = "LOCAL_OWNER_ORIENT"
        return

    # Capture the evaluated source transform before adding the constraint.
    # Blender's Set Inverse for a pose-bone owner is the source bone's world
    # inverse multiplied by the owning armature object's world matrix.  The
    # pose channel applies the target bone's rest/local matrix separately.
    owner_arm = pbone.id_data
    src_pbone = source_arm.pose.bones.get(src_name)
    src_world = (
        source_arm.matrix_world @ src_pbone.matrix
        if src_pbone else None
    )

    co = pbone.constraints.new("CHILD_OF")
    co.name           = CONSTRAINT_PREFIX + "ChildOf"
    co.target         = source_arm
    co.subtarget      = src_name
    co.use_location_x = True
    co.use_location_y = True
    co.use_location_z = True
    co.use_rotation_x = True
    co.use_rotation_y = True
    co.use_rotation_z = True
    co.use_scale_x    = False
    co.use_scale_y    = False
    co.use_scale_z    = False

    # Set Inverse: invert the source bone's current world matrix so the
    # target bone stays exactly where it is when the constraint first fires.
    if src_world is not None:
        co.inverse_matrix = src_world.inverted() @ owner_arm.matrix_world
    else:
        co.inverse_matrix = mathutils.Matrix.Identity(4)
    # Blender 5.x creates Child Of constraints with this flag enabled.  If it
    # remains pending, dependency-graph evaluation overwrites the matrix above
    # and the target can jump when its armature object is offset from origin.
    if hasattr(co, "set_inverse_pending"):
        co.set_inverse_pending = False


def remove_retargeting_constraints(target_arm: bpy.types.Object) -> int:
    """Removes all Kimodo constraints from target armature. Returns count removed."""
    removed = 0
    for pbone in target_arm.pose.bones:
        for c in list(pbone.constraints):
            if c.name.startswith(CONSTRAINT_PREFIX):
                pbone.constraints.remove(c)
                removed += 1
    return removed


# ---------------------------------------------------------------------------
# Baking
# ---------------------------------------------------------------------------

def bake_retargeted_animation(
    target_arm: bpy.types.Object,
    frame_start: int,
    frame_end: int,
) -> bool:
    """
    Bakes the driven (constraint) animation into actual keyframes,
    then removes the retargeting constraints.
    Returns True on success.
    """
    try:
        # Select only target armature
        bpy.ops.object.select_all(action='DESELECT')
        target_arm.select_set(True)
        bpy.context.view_layer.objects.active = target_arm

        # Enter pose mode for baking
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.select_all(action='SELECT')

        bpy.ops.nla.bake(
            frame_start=frame_start,
            frame_end=frame_end,
            only_selected=False,
            visual_keying=True,
            clear_constraints=False,
            clear_parents=False,
            use_current_action=True,
            bake_types={'POSE'},
        )

        # Keep facial, control-rig, and user-authored constraints intact.
        # NLA bake's clear_constraints option removes every constraint on the
        # selected bones, not just the ones created by Kimodo.
        remove_retargeting_constraints(target_arm)

        bpy.ops.object.mode_set(mode='OBJECT')
        return True

    except Exception as e:
        print(f"[Kimodo] Bake error: {e}")
        return False


# ---------------------------------------------------------------------------
# Preset save / load
# ---------------------------------------------------------------------------

def save_preset(prefs, preset_name: str, bone_pairs: list[dict]) -> None:
    """Save bone mapping to addon preferences."""
    import json
    try:
        presets = json.loads(prefs.saved_presets)
    except Exception:
        presets = {}
    presets[preset_name] = bone_pairs
    prefs.saved_presets = json.dumps(presets)


def load_preset(prefs, preset_name: str) -> list[dict] | None:
    """Load bone mapping from addon preferences. Returns None if not found."""
    import json
    try:
        presets = json.loads(prefs.saved_presets)
        return presets.get(preset_name)
    except Exception:
        return None


def list_presets(prefs) -> list[str]:
    """Returns list of saved preset names."""
    import json
    try:
        return list(json.loads(prefs.saved_presets).keys())
    except Exception:
        return []
