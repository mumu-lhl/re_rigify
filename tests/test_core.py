import unittest

from re_rigify.core import (
    ConfigError,
    normalize_config,
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
                "rules": [{"kind": "EXACT", "pattern": "spine"}],
            }],
        }

        self.assertEqual(normalize_config(payload), payload)

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
