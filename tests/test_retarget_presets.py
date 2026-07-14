import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import retarget_presets as presets


SOURCE_BONES = {
    "Root", "Hips", "Spine1", "Spine2", "Chest", "Neck1", "Neck2",
    "Head", "Jaw", "LeftEye", "RightEye",
}
for side in ("Left", "Right"):
    SOURCE_BONES.update({
        f"{side}Shoulder", f"{side}Arm", f"{side}ForeArm", f"{side}Hand",
        f"{side}Leg", f"{side}Shin", f"{side}Foot", f"{side}ToeBase",
    })
    SOURCE_BONES.update(f"{side}HandThumb{i}" for i in range(1, 4))
    for digit in ("Index", "Middle", "Ring", "Pinky"):
        SOURCE_BONES.update(f"{side}Hand{digit}{i}" for i in range(1, 5))


UE5_BONES = {
    "root", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04",
    "spine_05", "neck_01", "neck_02", "head",
}
for suffix in ("l", "r"):
    UE5_BONES.update({
        f"clavicle_{suffix}", f"upperarm_{suffix}", f"lowerarm_{suffix}",
        f"hand_{suffix}", f"thigh_{suffix}", f"calf_{suffix}",
        f"foot_{suffix}", f"ball_{suffix}",
    })
    UE5_BONES.update(f"thumb_0{i}_{suffix}" for i in range(1, 4))
    for digit in ("index", "middle", "ring", "pinky"):
        UE5_BONES.add(f"{digit}_metacarpal_{suffix}")
        UE5_BONES.update(f"{digit}_0{i}_{suffix}" for i in range(1, 4))


CC_BONES = {
    "CC_Base_BoneRoot", "CC_Base_Hip", "CC_Base_Waist",
    "CC_Base_Spine01", "CC_Base_Spine02", "CC_Base_NeckTwist01",
    "CC_Base_NeckTwist02", "CC_Base_Head", "CC_Base_JawRoot",
    "CC_Base_L_Eye", "CC_Base_R_Eye",
}
for side in ("L", "R"):
    CC_BONES.update({
        f"CC_Base_{side}_Clavicle", f"CC_Base_{side}_Upperarm",
        f"CC_Base_{side}_Forearm", f"CC_Base_{side}_Hand",
        f"CC_Base_{side}_Thigh", f"CC_Base_{side}_Calf",
        f"CC_Base_{side}_Foot", f"CC_Base_{side}_ToeBase",
    })
    CC_BONES.update(f"CC_Base_{side}_Thumb{i}" for i in range(1, 4))
    for digit in ("Index", "Mid", "Ring", "Pinky"):
        CC_BONES.update(f"CC_Base_{side}_{digit}{i}" for i in range(1, 4))


class RetargetPresetTests(unittest.TestCase):
    def test_detects_unreal_ue5_and_builds_full_map(self):
        result = presets.build_mapping(SOURCE_BONES, UE5_BONES)
        self.assertEqual(result["profile_id"], presets.PROFILE_UNREAL_UE5)
        self.assertEqual(result["root"], "root")
        self.assertEqual(len(result["mappings"]), 62)
        self.assertFalse(result["missing_source"])
        self.assertFalse(result["missing_target"])

        pairs = {(item["src"], item["tgt"]): item for item in result["mappings"]}
        self.assertEqual(pairs[("Root", "root")]["mode"], presets.MODE_ROOT)
        self.assertEqual(
            pairs[("LeftHandIndex1", "index_metacarpal_l")]["mode"],
            presets.MODE_ROTATION,
        )
        self.assertIn(("LeftHandIndex2", "index_01_l"), pairs)

    def test_detects_reallusion_cc_base_and_skips_metacarpals(self):
        result = presets.build_mapping(SOURCE_BONES, CC_BONES)
        self.assertEqual(result["profile_id"], presets.PROFILE_REALLUSION_CC)
        self.assertEqual(result["root"], "CC_Base_BoneRoot")
        self.assertEqual(len(result["mappings"]), 57)
        self.assertFalse(result["missing_source"])
        self.assertFalse(result["missing_target"])

        pairs = {(item["src"], item["tgt"]): item for item in result["mappings"]}
        self.assertIn(("LeftHandIndex2", "CC_Base_L_Index1"), pairs)
        self.assertNotIn(("LeftHandIndex1", "CC_Base_L_Index1"), pairs)

    def test_unknown_humanoid_does_not_claim_an_official_profile(self):
        result = presets.build_mapping(SOURCE_BONES, {"root", "hips", "head"})
        self.assertEqual(result["profile_id"], "")
        self.assertFalse(result["mappings"])


if __name__ == "__main__":
    unittest.main()
