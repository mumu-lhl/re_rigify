import unittest

from re_rigify.core import (
    ConfigError,
    choose_drive_target,
    infer_rigify_topology,
    normalize_config,
    mirror_parameter_value,
    resolve_collection_rules,
    validate_config,
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
    def test_drive_target_prefers_def_then_org_then_same_name(self):
        self.assertEqual(
            choose_drive_target("Arm_L", {"Arm_L", "ORG-Arm_L", "DEF-Arm_L"}),
            "DEF-Arm_L",
        )
        self.assertEqual(choose_drive_target("Arm_L", {"Arm_L", "ORG-Arm_L"}), "ORG-Arm_L")
        self.assertEqual(choose_drive_target("Arm_L", {"Arm_L"}), "Arm_L")
        self.assertIsNone(choose_drive_target("Arm_L", {"DEF-Arm_R"}))

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
            "bones": [{"bone_name": "spine", "rigify_type": "basic.super_copy", "parameters": {}}],
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
