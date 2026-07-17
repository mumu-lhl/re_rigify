import unittest

from re_rigify.core import (
    ConfigError,
    DEFAULT_COMPATIBILITY,
    choose_drive_spec,
    choose_drive_target,
    infer_rigify_topology,
    mirror_compatibility,
    normalize_config,
    mirror_parameter_value,
    remove_collection_references,
    resolve_collection_rules,
    validate_config,
    unique_blender_name,
    unique_child_chain,
)


class ResolveCollectionRulesTests(unittest.TestCase):
    def setUp(self):
        self.bones = ["spine", "upper_arm.L", "upper_arm.R", "hand.L", "hand.R"]

    def test_exact_and_glob_rules_accumulate_memberships(self):
        collections = [
            {"name": "Arms", "rules": [{"kind": "GLOB", "pattern": "upper_arm.?’"}]},
            {"name": "Left", "rules": [{"kind": "GLOB", "pattern": "*.L"}]},
            {"name": "Core", "rules": [{"kind": "EXACT", "pattern": "spine"}]},
        ]
        collections[0]["rules"][0]["pattern"] = "upper_arm.?"

        resolved = resolve_collection_rules(self.bones, collections)

        self.assertEqual(resolved["Arms"], ["upper_arm.L", "upper_arm.R"])
        self.assertEqual(resolved["Left"], ["upper_arm.L", "hand.L"])
        self.assertEqual(resolved["Core"], ["spine"])

    def test_empty_glob_is_an_error(self):
        collections = [{"name": "Feet", "rules": [{"kind": "GLOB", "pattern": "foot.*"}]}]

        with self.assertRaisesRegex(ConfigError, "matched no bones"):
            resolve_collection_rules(self.bones, collections)


class ConfigValidationTests(unittest.TestCase):
    def test_version_one_defaults_compatibility_to_disabled(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{
                "bone_name": "spine",
                "rigify_type": "basic.super_copy",
                "parameters": {},
            }],
            "collections": [],
            "color_sets": [],
        }

        result = normalize_config(payload)

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["bones"][0]["compatibility"], DEFAULT_COMPATIBILITY)

    def test_version_one_round_trips_compatibility(self):
        compatibility = {
            **DEFAULT_COMPATIBILITY,
            "force_connect_chain": True,
            "skin_eye_compatibility": True,
            "roll_bones_enabled": True,
            "upper_arm_roll_bone": "ShoulderRoll_L",
            "forearm_roll_bone": "ArmRoll_L",
            "eye_forward_axis": "-Y",
            "upper_lid_pattern": "Eye_up_*_L",
            "lower_lid_pattern": "Eye_bottom_*_L",
        }
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{
                "bone_name": "Eye_L",
                "rigify_type": "face.skin_eye",
                "parameters": {},
                "compatibility": compatibility,
            }],
            "collections": [],
            "color_sets": [],
        }

        result = normalize_config(payload)

        self.assertEqual(result["bones"][0]["compatibility"], compatibility)

    def test_unique_child_chain_rejects_branches(self):
        parents = {"root": None, "a": "root", "b": "root"}

        with self.assertRaisesRegex(ConfigError, "ambiguous.*a.*b"):
            unique_child_chain("root", parents)

    def test_unique_child_chain_returns_ordered_path(self):
        parents = {"root": None, "middle": "root", "tip": "middle"}

        self.assertEqual(unique_child_chain("root", parents), ["root", "middle", "tip"])

    def test_mirror_compatibility_swaps_x_axis_and_patterns(self):
        result = mirror_compatibility({
            **DEFAULT_COMPATIBILITY,
            "eye_forward_axis": "+X",
            "upper_lid_pattern": "Eye_up_*_L",
        }, lambda name: name.replace("_L", "_R"))

        self.assertEqual(result["eye_forward_axis"], "-X")
        self.assertEqual(result["upper_lid_pattern"], "Eye_up_*_R")

    def test_mirror_compatibility_maps_roll_bones(self):
        result = mirror_compatibility({
            **DEFAULT_COMPATIBILITY,
            "roll_bones_enabled": True,
            "upper_arm_roll_bone": "ShoulderRoll_L",
            "forearm_roll_bone": "ArmRoll_L",
        }, lambda name: name.replace("_L", "_R"))

        self.assertEqual(result["upper_arm_roll_bone"], "ShoulderRoll_R")
        self.assertEqual(result["forearm_roll_bone"], "ArmRoll_R")

    def test_unique_blender_name_increments_numeric_suffix(self):
        names = {"Arm", "Arm.001", "Arm.003", "Leg"}

        self.assertEqual(unique_blender_name("Arm", names), "Arm.002")
        self.assertEqual(unique_blender_name("Arm.001", names), "Arm.002")
        self.assertEqual(unique_blender_name("Hand", names), "Hand")

    def test_remove_collection_references_only_changes_reference_lists(self):
        parameters = {
            "fk_coll_refs": ["FK", "Main"],
            "tweak_coll_refs": ["FK"],
            "unrelated": "FK",
        }

        result = remove_collection_references(parameters, "FK")

        self.assertEqual(result, {
            "fk_coll_refs": ["Main"], "tweak_coll_refs": [], "unrelated": "FK",
        })

    def test_drive_target_prefers_org_then_def_then_same_name(self):
        self.assertEqual(
            choose_drive_target("Arm_L", {"Arm_L", "ORG-Arm_L", "DEF-Arm_L"}),
            "ORG-Arm_L",
        )
        self.assertEqual(choose_drive_target("Arm_L", {"Arm_L", "ORG-Arm_L"}), "ORG-Arm_L")
        self.assertEqual(choose_drive_target("Arm_L", {"Arm_L", "DEF-Arm_L"}), "DEF-Arm_L")
        self.assertEqual(choose_drive_target("Arm_L", {"Arm_L"}), "Arm_L")
        self.assertIsNone(choose_drive_target("Arm_L", {"DEF-Arm_R"}))

    def test_drive_target_prefers_explicit_mapping(self):
        self.assertEqual(
            choose_drive_target(
                "Eye_up_01_L",
                {"DEF-RR-lid01.T.L", "Eye_up_01_L"},
                explicit={"Eye_up_01_L": "DEF-RR-lid01.T.L"},
            ),
            "DEF-RR-lid01.T.L",
        )

    def test_rotation_drive_mapping_overrides_transform_mapping(self):
        self.assertEqual(
            choose_drive_spec(
                "ShoulderRoll_L",
                {"ORG-ShoulderRoll_L", "MCH-RR-ShoulderRoll_L"},
                {"ShoulderRoll_L": "ORG-ShoulderRoll_L"},
                {"ShoulderRoll_L": "MCH-RR-ShoulderRoll_L"},
            ),
            ("MCH-RR-ShoulderRoll_L", "ROTATION"),
        )

    def test_infers_common_disconnected_arm_leg_spine_and_head_topology(self):
        parents = {
            "Spine": "Waist", "Chest": "Spine", "Neck": "Chest", "Head": "Neck",
            "Elbow_L": "Arm_L", "Wrist_L": "Elbow_L", "ArmRoll_L": "Elbow_L",
            "Knee_L": "Thigh_L", "Ankle_L": "Knee_L",
            "Ankle_offset_L": "Ankle_L", "Toe_L": "Ankle_offset_L",
        }
        configs = [
            {"bone_name": "Waist", "rigify_type": "spines.basic_spine"},
            {"bone_name": "Neck", "rigify_type": "spines.super_head"},
            {"bone_name": "Arm_L", "rigify_type": "limbs.arm"},
            {"bone_name": "Thigh_L", "rigify_type": "limbs.leg"},
        ]

        operations = infer_rigify_topology(configs, parents)

        self.assertIn(("Waist", "Spine", True), operations)
        self.assertIn(("Spine", "Chest", True), operations)
        self.assertIn(("Neck", "Head", True), operations)
        self.assertIn(("Arm_L", "Elbow_L", True), operations)
        self.assertIn(("Elbow_L", "Wrist_L", True), operations)
        self.assertIn(("Thigh_L", "Knee_L", True), operations)
        self.assertIn(("Knee_L", "Ankle_offset_L", True), operations)
        self.assertIn(("Ankle_offset_L", "Toe_L", True), operations)
        self.assertIn(("Ankle_offset_L", "Ankle_L", False), operations)

    def test_mirror_parameter_value_recursively_maps_bone_names(self):
        value = {"target": "Arm_L", "nested": ["Hand_L", 3, True]}

        mirrored = mirror_parameter_value(value, lambda name: name.replace("_L", "_R"))

        self.assertEqual(mirrored, {"target": "Arm_R", "nested": ["Hand_R", 3, True]})

    def test_normalize_round_trip_shape(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{
                "bone_name": "spine",
                "rigify_type": "basic.super_copy",
                "parameters": {},
                "compatibility": DEFAULT_COMPATIBILITY,
            }],
            "collections": [{
                "name": "Controls",
                "ui_title": "Main",
                "ui_row": 1,
                "row_order": 0,
                "color_set": "FK",
                "rules": [{"kind": "EXACT", "pattern": "spine"}],
            }],
            "color_sets": [{
                "name": "FK",
                "active": [0.55, 1.0, 1.0],
                "normal": [0.12, 0.57, 0.04],
                "select": [0.31, 0.78, 1.0],
                "standard_colors_lock": True,
            }],
        }

        self.assertEqual(normalize_config(payload), payload)

    def test_collection_color_set_must_exist(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [],
            "collections": [{"name": "Controls", "color_set": "Missing", "rules": []}],
            "color_sets": [],
        }

        result = validate_config(payload, [], [])

        self.assertFalse(result.ok)
        self.assertTrue(any("unknown color set" in error for error in result.errors))

    def test_duplicate_color_set_is_rejected(self):
        color = {
            "name": "FK", "active": [1.0, 1.0, 1.0],
            "normal": [0.0, 0.0, 0.0], "select": [0.5, 0.5, 0.5],
            "standard_colors_lock": False,
        }
        payload = {
            "format": "re-rigify", "schema_version": 1,
            "bones": [], "collections": [], "color_sets": [color, dict(color)],
        }

        result = validate_config(payload, [], [])

        self.assertFalse(result.ok)
        self.assertTrue(any("duplicate color set" in error for error in result.errors))

    def test_rigify_collection_references_must_use_managed_collections(self):
        payload = {
            "format": "re-rigify", "schema_version": 1,
            "bones": [{
                "bone_name": "arm", "rigify_type": "limbs.arm",
                "parameters": {"fk_coll_refs": ["FK"], "tweak_coll_refs": ["Missing"]},
            }],
            "collections": [{"name": "FK", "rules": []}],
            "color_sets": [],
        }

        result = validate_config(payload, ["arm"], ["limbs.arm"])

        self.assertFalse(result.ok)
        self.assertTrue(any("tweak_coll_refs" in error and "Missing" in error for error in result.errors))

    def test_duplicate_row_order_is_rejected(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [],
            "collections": [
                {"name": "A", "ui_row": 1, "row_order": 0, "rules": []},
                {"name": "B", "ui_row": 1, "row_order": 0, "rules": []},
            ],
        }

        result = validate_config(payload, ["spine"], {"basic.super_copy"})

        self.assertFalse(result.ok)
        self.assertTrue(any("row_order" in error for error in result.errors))

    def test_missing_bone_and_unknown_rig_type_are_reported(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{"bone_name": "missing", "rigify_type": "unknown.type", "parameters": {}}],
            "collections": [],
        }

        result = validate_config(payload, ["spine"], {"basic.super_copy"})

        self.assertFalse(result.ok)
        self.assertEqual(len(result.errors), 2)


if __name__ == "__main__":
    unittest.main()
