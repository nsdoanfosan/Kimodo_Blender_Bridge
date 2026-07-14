"""Built-in Kimodo SOMA v1.1 retarget profiles.

The profile boundaries follow the official workflows rather than treating all
humanoid rigs as one naming convention:

* Epic IK Rig: retarget root is normally pelvis/hip and major limbs are chains.
  https://dev.epicgames.com/documentation/unreal-engine/retargeting-bipeds-with-ik-rig-in-unreal-engine
* Reallusion's Unreal (UE5 Skeleton) export and native CC/iClone
  ``CC_Base_*`` hierarchy are treated as separate target profiles.
  https://manual.reallusion.com/CC-iC-Auto-Setup/All-in-One/1.2/02_for_Unreal/Exporting-Characters-from-iC-or-CC.htm

Kimodo v1.1 adds metacarpal joints as digit ``1`` for index/middle/ring/pinky.
UE5 receives those joints directly; CC Base starts its three finger
phalanges at Kimodo digit ``2``.
"""

PROFILE_AUTO = "AUTO"
PROFILE_REALLUSION_CC = "REALLUSION_CC_BASE"
PROFILE_UNREAL_UE5 = "UNREAL_UE5"

MODE_ROOT = "CHILD_OF"
MODE_ROTATION = "CHILD_OF_ROTATION"


def _entry(source, target, mode=MODE_ROTATION):
    return {
        "src": source,
        "tgt": target,
        "mode": mode,
        "inherit_rot": True,
    }


def _reallusion_cc_mapping():
    result = [
        _entry("Root", "CC_Base_BoneRoot", MODE_ROOT),
        _entry("Hips", "CC_Base_Hip"),
        _entry("Spine1", "CC_Base_Waist"),
        _entry("Spine2", "CC_Base_Spine01"),
        _entry("Chest", "CC_Base_Spine02"),
        _entry("Neck1", "CC_Base_NeckTwist01"),
        _entry("Neck2", "CC_Base_NeckTwist02"),
        _entry("Head", "CC_Base_Head"),
        _entry("Jaw", "CC_Base_JawRoot"),
        _entry("LeftEye", "CC_Base_L_Eye"),
        _entry("RightEye", "CC_Base_R_Eye"),
    ]

    for side, cc_side in (("Left", "L"), ("Right", "R")):
        result.extend([
            _entry(f"{side}Shoulder", f"CC_Base_{cc_side}_Clavicle"),
            _entry(f"{side}Arm", f"CC_Base_{cc_side}_Upperarm"),
            _entry(f"{side}ForeArm", f"CC_Base_{cc_side}_Forearm"),
            _entry(f"{side}Hand", f"CC_Base_{cc_side}_Hand"),
            _entry(f"{side}Leg", f"CC_Base_{cc_side}_Thigh"),
            _entry(f"{side}Shin", f"CC_Base_{cc_side}_Calf"),
            _entry(f"{side}Foot", f"CC_Base_{cc_side}_Foot"),
            _entry(f"{side}ToeBase", f"CC_Base_{cc_side}_ToeBase"),
        ])

        for index in range(1, 4):
            result.append(_entry(
                f"{side}HandThumb{index}",
                f"CC_Base_{cc_side}_Thumb{index}",
            ))

        for source_digit, target_digit in (("Index", "Index"),
                                            ("Middle", "Mid"),
                                            ("Ring", "Ring"),
                                            ("Pinky", "Pinky")):
            for source_index, target_index in ((2, 1), (3, 2), (4, 3)):
                result.append(_entry(
                    f"{side}Hand{source_digit}{source_index}",
                    f"CC_Base_{cc_side}_{target_digit}{target_index}",
                ))
    return tuple(result)


def _unreal_ue5_mapping():
    result = [
        _entry("Root", "root", MODE_ROOT),
        _entry("Hips", "pelvis"),
        _entry("Spine1", "spine_01"),
        _entry("Spine2", "spine_02"),
        _entry("Chest", "spine_03"),
    ]

    result.extend([
        _entry("Neck1", "neck_01"),
        _entry("Neck2", "neck_02"),
    ])
    result.append(_entry("Head", "head"))

    for source_side, suffix in (("Left", "l"), ("Right", "r")):
        result.extend([
            _entry(f"{source_side}Shoulder", f"clavicle_{suffix}"),
            _entry(f"{source_side}Arm", f"upperarm_{suffix}"),
            _entry(f"{source_side}ForeArm", f"lowerarm_{suffix}"),
            _entry(f"{source_side}Hand", f"hand_{suffix}"),
            _entry(f"{source_side}Leg", f"thigh_{suffix}"),
            _entry(f"{source_side}Shin", f"calf_{suffix}"),
            _entry(f"{source_side}Foot", f"foot_{suffix}"),
            _entry(f"{source_side}ToeBase", f"ball_{suffix}"),
        ])

        for index in range(1, 4):
            result.append(_entry(
                f"{source_side}HandThumb{index}",
                f"thumb_0{index}_{suffix}",
            ))

        for digit in ("index", "middle", "ring", "pinky"):
            source_digit = digit.title()
            result.append(_entry(
                f"{source_side}Hand{source_digit}1",
                f"{digit}_metacarpal_{suffix}",
            ))
            for source_index, target_index in ((2, 1), (3, 2), (4, 3)):
                result.append(_entry(
                    f"{source_side}Hand{source_digit}{source_index}",
                    f"{digit}_0{target_index}_{suffix}",
                ))
    return tuple(result)


PROFILES = {
    PROFILE_REALLUSION_CC: {
        "label": "Reallusion CC / iClone (CC Base)",
        "root": "CC_Base_BoneRoot",
        "markers": (
            "CC_Base_BoneRoot", "CC_Base_Hip", "CC_Base_Waist",
            "CC_Base_L_Upperarm", "CC_Base_L_Thigh",
        ),
        "mappings": _reallusion_cc_mapping(),
    },
    PROFILE_UNREAL_UE5: {
        "label": "Unreal UE5 Manny / Reallusion UE5 Export",
        "root": "root",
        "markers": (
            "root", "pelvis", "spine_01", "spine_05", "neck_02",
            "upperarm_l", "thigh_l", "index_metacarpal_l",
        ),
        "mappings": _unreal_ue5_mapping(),
    },
}


def detect_profile(target_bone_names):
    """Return the best built-in profile id, or an empty string."""
    names = set(target_bone_names)
    if all(name in names for name in PROFILES[PROFILE_REALLUSION_CC]["markers"]):
        return PROFILE_REALLUSION_CC
    if all(name in names for name in PROFILES[PROFILE_UNREAL_UE5]["markers"]):
        return PROFILE_UNREAL_UE5
    return ""


def build_mapping(source_bone_names, target_bone_names, profile_id=PROFILE_AUTO):
    """Build a filtered mapping and return metadata for UI/reporting."""
    source_names = set(source_bone_names)
    target_names = set(target_bone_names)
    resolved_id = profile_id
    if resolved_id == PROFILE_AUTO:
        resolved_id = detect_profile(target_names)
    profile = PROFILES.get(resolved_id)
    if profile is None:
        return {
            "profile_id": "",
            "label": "",
            "root": "",
            "mappings": [],
            "missing_source": [],
            "missing_target": [],
        }

    mappings = []
    missing_source = []
    missing_target = []
    for item in profile["mappings"]:
        if item["src"] not in source_names:
            missing_source.append(item["src"])
            continue
        if item["tgt"] not in target_names:
            missing_target.append(item["tgt"])
            continue
        mappings.append(dict(item))

    return {
        "profile_id": resolved_id,
        "label": profile["label"],
        "root": profile["root"] if profile["root"] in target_names else "",
        "mappings": mappings,
        "missing_source": sorted(set(missing_source)),
        "missing_target": sorted(set(missing_target)),
    }
