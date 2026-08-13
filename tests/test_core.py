import unittest

from re_rigify.core import (
    CHAIN_RULE_MIN_LENGTHS,
    ConfigError,
    DEFAULT_COMPATIBILITY,
    EXPLICIT_CHAIN_MIN_LENGTHS,
    choose_drive_spec,
    choose_drive_target,
    configured_drive_bone_names,
    infer_rigify_topology,
    materialize_bone_rules,
    mirror_compatibility,
    move_selected_indices,
    normalize_config,
    normalize_compatibility,
    plan_missing_leg_heels,
    preview_bone_rule,
    mirror_parameter_value,
    rename_collection_references,
    remove_collection_references,
    resolve_bone_rules,
    resolve_bone_rule_rows,
    resolve_collection_rules,
    validate_config,
    unique_blender_name,
    unique_child_chain,
)


class BoneRuleTests(unittest.TestCase):
    @staticmethod
    def valid_payload():
        return {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{
                "bone_name": "spine",
                "rigify_type": "basic.raw_copy",
                "chain_bones": [],
                "parameters": {},
                "compatibility": DEFAULT_COMPATIBILITY,
            }],
            "collections": [{
                "name": "Controls",
                "ui_title": "Controls",
                "ui_row": 1,
                "row_order": 0,
                "color_set": "",
                "rules": [],
            }],
            "color_sets": [],
        }

    def test_schema_defaults_rules_and_visibility(self):
        result = normalize_config(self.valid_payload())

        self.assertEqual(result["bone_rules"], [])
        self.assertTrue(result["collections"][0]["visible_after_generation"])

    def test_super_finger_axis_defaults_to_auto(self):
        result = normalize_compatibility({})
        self.assertEqual(result["super_finger_primary_axis"], "AUTO")

    def test_super_finger_axis_rejects_unknown_value(self):
        with self.assertRaisesRegex(ConfigError, "super_finger_primary_axis"):
            normalize_compatibility({"super_finger_primary_axis": "Q"})

    def test_mirror_compatibility_swaps_every_super_finger_axis(self):
        expected = {
            "AUTO": "AUTO", "+X": "-X", "-X": "+X",
            "+Y": "-Y", "-Y": "+Y", "+Z": "-Z", "-Z": "+Z",
        }
        for source, target in expected.items():
            result = mirror_compatibility(
                {"super_finger_primary_axis": source}, lambda value: value,
            )
            self.assertEqual(result["super_finger_primary_axis"], target)

    def test_non_chain_type_discards_stale_chain_options(self):
        payload = self.valid_payload()
        payload["bones"][0].update({
            "rigify_type": "basic.super_copy",
            "chain_bones": ["spine", "spine_tip"],
            "compatibility": {
                **DEFAULT_COMPATIBILITY,
                "force_connect_chain": True,
            },
        })

        result = normalize_config(payload)

        self.assertEqual(result["bones"][0]["chain_bones"], [])

    def test_later_rule_wins_and_result_follows_bone_order(self):
        rules = [
            {
                "rule_id": "all-fingers", "kind": "GLOB", "pattern": "Finger_*",
                "rigify_type": "limbs.super_finger",
                "parameters": {"segments": 2},
            },
            {
                "rule_id": "index", "kind": "EXACT", "pattern": "Finger_Index",
                "rigify_type": "basic.super_copy",
                "parameters": {"make_control": True},
            },
        ]

        result = resolve_bone_rules(
            ["Root", "Finger_Index", "Finger_Middle"], rules,
        )

        self.assertEqual(list(result), ["Finger_Index", "Finger_Middle"])
        self.assertEqual(result["Finger_Index"]["rule_id"], "index")
        self.assertEqual(result["Finger_Middle"]["rule_id"], "all-fingers")

    def test_rule_with_no_match_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "matched no bones"):
            resolve_bone_rules(
                ["Root"],
                [{
                    "rule_id": "missing", "kind": "GLOB", "pattern": "Finger_*",
                    "rigify_type": "basic.super_copy", "parameters": {},
                }],
            )

    def test_materialization_overrides_manual_rows_and_appends_new_matches(self):
        payload = self.valid_payload()
        payload["bones"][0]["bone_name"] = "Finger_Index"
        payload["bone_rules"] = [{
            "rule_id": "fingers", "kind": "GLOB", "pattern": "Finger_*",
            "rigify_type": "basic.super_copy",
            "parameters": {"make_control": False},
        }]

        result = materialize_bone_rules(
            payload, ["Root", "Finger_Index", "Finger_Middle"],
        )

        self.assertEqual(
            [item["bone_name"] for item in result["bones"]],
            ["Finger_Index", "Finger_Middle"],
        )
        self.assertTrue(all(
            item["rigify_type"] == "basic.super_copy"
            and item["parameters"] == {"make_control": False}
            for item in result["bones"]
        ))

    def test_rename_updates_only_collection_reference_lists(self):
        parameters = {
            "fk_coll_refs": ["Old", "Other"],
            "tweak_coll_refs": ["Old"],
            "ordinary_list": ["Old"],
            "label": "Old",
        }

        self.assertEqual(
            rename_collection_references(parameters, "Old", "New"),
            {
                "fk_coll_refs": ["New", "Other"],
                "tweak_coll_refs": ["New"],
                "ordinary_list": ["Old"],
                "label": "Old",
            },
        )


class ChainBoneRuleTests(unittest.TestCase):
    NAMES = [
        "HairA_00", "HairA_01",
        "HairB_00", "HairB_01", "HairB_02",
    ]
    PARENTS = {
        "HairA_00": "Head",
        "HairA_01": "HairA_00",
        "HairB_00": "Head",
        "HairB_01": "HairB_00",
        "HairB_02": "HairB_01",
        "Head": None,
    }
    ALIGNED = {
        ("HairA_00", "HairA_01"),
        ("HairB_00", "HairB_01"),
        ("HairB_01", "HairB_02"),
    }

    @staticmethod
    def rule(**overrides):
        return {
            "rule_id": "hair",
            "kind": "GLOB",
            "pattern": "Hair*",
            "rigify_type": "limbs.spline_tentacle",
            "parameters": {},
            "apply_as_chain": True,
            **overrides,
        }

    def test_normalize_defaults_chain_mode_off(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [],
            "bone_rules": [{
                "rule_id": "hair",
                "kind": "GLOB",
                "pattern": "Hair*",
                "rigify_type": "limbs.spline_tentacle",
                "parameters": {},
            }],
            "collections": [],
            "color_sets": [],
        }

        result = normalize_config(payload)

        self.assertFalse(result["bone_rules"][0]["apply_as_chain"])

    def test_preview_contains_only_final_effective_matches(self):
        rules = [
            self.rule(
                rule_id="all",
                apply_as_chain=False,
                rigify_type="basic.raw_copy",
            ),
            self.rule(
                rule_id="tip",
                kind="EXACT",
                pattern="HairB_02",
                apply_as_chain=False,
                rigify_type="basic.raw_copy",
            ),
        ]

        preview = preview_bone_rule(self.NAMES, rules, "all")

        self.assertEqual(preview["bone_names"], self.NAMES[:-1])
        self.assertEqual(preview["chain_count"], 0)

    def test_chain_preview_flattens_root_to_child(self):
        preview = preview_bone_rule(
            self.NAMES,
            [self.rule()],
            "hair",
            self.PARENTS,
            self.ALIGNED,
        )

        self.assertEqual(preview["bone_names"], self.NAMES)
        self.assertEqual(preview["chain_count"], 2)

    def test_fully_overridden_rule_has_empty_preview(self):
        rules = [
            self.rule(
                rule_id="first",
                apply_as_chain=False,
                rigify_type="basic.raw_copy",
            ),
            self.rule(
                rule_id="second",
                apply_as_chain=False,
                rigify_type="basic.raw_copy",
            ),
        ]

        preview = preview_bone_rule(self.NAMES, rules, "first")

        self.assertEqual(preview["bone_names"], [])
        self.assertEqual(preview["rows"], [])

    def test_chain_rule_materializes_only_ordered_roots(self):
        rows = resolve_bone_rule_rows(
            self.NAMES, [self.rule()], self.PARENTS, self.ALIGNED,
        )

        self.assertEqual(
            [(row["bone_name"], row["chain_bones"]) for row in rows],
            [
                ("HairA_00", ["HairA_00", "HairA_01"]),
                ("HairB_00", ["HairB_00", "HairB_01", "HairB_02"]),
            ],
        )

    def test_later_rule_splits_chain_before_grouping(self):
        rows = resolve_bone_rule_rows(
            self.NAMES,
            [
                self.rule(),
                self.rule(
                    rule_id="tail",
                    kind="EXACT",
                    pattern="HairB_02",
                    rigify_type="basic.raw_copy",
                    apply_as_chain=False,
                ),
            ],
            self.PARENTS,
            self.ALIGNED,
        )

        self.assertEqual(
            [(row["bone_name"], row["chain_bones"]) for row in rows],
            [
                ("HairA_00", ["HairA_00", "HairA_01"]),
                ("HairB_00", ["HairB_00", "HairB_01"]),
                ("HairB_02", []),
            ],
        )

    def test_chain_rule_rejects_branch(self):
        parents = {**self.PARENTS, "HairB_X": "HairB_00"}

        with self.assertRaisesRegex(ConfigError, "branches at 'HairB_00'"):
            resolve_bone_rule_rows(
                [*self.NAMES, "HairB_X"],
                [self.rule()],
                parents,
                {*self.ALIGNED, ("HairB_00", "HairB_X")},
            )

    def test_chain_rule_rejects_disjoint_edge(self):
        with self.assertRaisesRegex(
            ConfigError, "disjoint edge 'HairB_01' -> 'HairB_02'",
        ):
            resolve_bone_rule_rows(
                self.NAMES,
                [self.rule()],
                self.PARENTS,
                self.ALIGNED - {("HairB_01", "HairB_02")},
            )

    def test_chain_rule_rejects_cycle_without_a_root(self):
        with self.assertRaisesRegex(ConfigError, "no reachable root"):
            resolve_bone_rule_rows(
                ["HairA_00", "HairA_01"],
                [self.rule()],
                {
                    "HairA_00": "HairA_01",
                    "HairA_01": "HairA_00",
                },
                {
                    ("HairA_00", "HairA_01"),
                    ("HairA_01", "HairA_00"),
                },
            )

    def test_chain_rule_rejects_short_component(self):
        with self.assertRaisesRegex(ConfigError, "requires at least 2 bones"):
            resolve_bone_rule_rows(
                ["HairA_00"],
                [self.rule()],
                self.PARENTS,
                set(),
            )

    def test_chain_rule_rejects_unsupported_type(self):
        with self.assertRaisesRegex(ConfigError, "does not support chain rules"):
            resolve_bone_rule_rows(
                self.NAMES,
                [self.rule(rigify_type="basic.raw_copy")],
                self.PARENTS,
                self.ALIGNED,
            )

    def test_materialization_omits_claimed_children(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [],
            "bone_rules": [self.rule()],
            "collections": [],
            "color_sets": [],
        }

        resolved = materialize_bone_rules(
            payload,
            self.NAMES,
            self.PARENTS,
            self.ALIGNED,
        )

        self.assertEqual(
            [
                (item["bone_name"], item["chain_bones"])
                for item in resolved["bones"]
            ],
            [
                ("HairA_00", ["HairA_00", "HairA_01"]),
                ("HairB_00", ["HairB_00", "HairB_01", "HairB_02"]),
            ],
        )


class MoveSelectedIndicesTests(unittest.TestCase):
    @staticmethod
    def apply(values, operations):
        values = list(values)
        for source, target in operations:
            values.insert(target, values.pop(source))
        return values

    def test_moves_contiguous_block_up_without_reversing(self):
        operations = move_selected_indices(4, {1, 2}, -1)

        self.assertEqual(
            self.apply(["A", "B", "C", "D"], operations),
            ["B", "C", "A", "D"],
        )

    def test_moves_contiguous_block_down_without_reversing(self):
        operations = move_selected_indices(4, {1, 2}, 1)

        self.assertEqual(
            self.apply(["A", "B", "C", "D"], operations),
            ["A", "D", "B", "C"],
        )

    def test_moves_separated_rows_one_step_without_compacting(self):
        operations = move_selected_indices(5, {1, 3}, -1)

        self.assertEqual(
            self.apply(["A", "B", "C", "D", "E"], operations),
            ["B", "A", "D", "C", "E"],
        )

    def test_boundary_blocks_do_not_move(self):
        self.assertEqual(move_selected_indices(4, {0, 1}, -1), ())
        self.assertEqual(move_selected_indices(4, {2, 3}, 1), ())

    def test_rejects_invalid_direction(self):
        with self.assertRaisesRegex(ValueError, "direction"):
            move_selected_indices(4, {1}, 0)


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
                "chain_bones": [],
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

    def test_version_one_defaults_to_empty_explicit_chain(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{
                "bone_name": "Hip",
                "rigify_type": "spines.basic_spine",
                "parameters": {},
            }],
            "collections": [],
            "color_sets": [],
        }

        result = normalize_config(payload)

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["bones"][0]["chain_bones"], [])

    def test_version_one_round_trips_explicit_chain(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{
                "bone_name": "Hip",
                "rigify_type": "spines.basic_spine",
                "chain_bones": ["Hip", "Waist", "Spine", "Chest"],
                "parameters": {},
            }],
            "collections": [],
            "color_sets": [],
        }

        result = normalize_config(payload)

        self.assertEqual(
            result["bones"][0]["chain_bones"],
            ["Hip", "Waist", "Spine", "Chest"],
        )

    def test_explicit_chain_root_must_match_configured_bone(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{
                "bone_name": "Hip",
                "rigify_type": "spines.basic_spine",
                "chain_bones": ["Waist", "Spine", "Chest"],
                "parameters": {},
            }],
            "collections": [],
            "color_sets": [],
        }

        result = validate_config(
            payload, ["Hip", "Waist", "Spine", "Chest"], ["spines.basic_spine"],
        )

        self.assertTrue(any("must start with" in error for error in result.errors))

    def test_explicit_chain_rejects_missing_and_duplicate_bones(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{
                "bone_name": "Hip",
                "rigify_type": "spines.basic_spine",
                "chain_bones": ["Hip", "Missing", "Hip"],
                "parameters": {},
            }],
            "collections": [],
            "color_sets": [],
        }

        result = validate_config(
            payload, ["Hip", "Waist", "Spine"], ["spines.basic_spine"],
        )

        self.assertTrue(any("does not exist" in error and "Missing" in error for error in result.errors))
        self.assertTrue(any("duplicate" in error and "Hip" in error for error in result.errors))

    def test_explicit_basic_spine_requires_three_bones(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{
                "bone_name": "Hip",
                "rigify_type": "spines.basic_spine",
                "chain_bones": ["Hip", "Waist"],
                "parameters": {},
            }],
            "collections": [],
            "color_sets": [],
        }

        result = validate_config(
            payload, ["Hip", "Waist"], ["spines.basic_spine"],
        )

        self.assertTrue(any("at least 3" in error for error in result.errors))

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

    def test_configured_drive_bones_include_roots_and_chains(self):
        names = configured_drive_bone_names([
            {
                "bone_name": "足.L",
                "rigify_type": "limbs.leg",
                "chain_bones": ["足.L", "ひざ.L", "足首.L", "つま先.L", "Extra.L"],
            },
            {
                "bone_name": "肩.L",
                "rigify_type": "basic.super_copy",
                "chain_bones": [],
            },
        ])
        self.assertEqual(
            names,
            {"足.L", "ひざ.L", "足首.L", "つま先.L", "Extra.L", "肩.L"},
        )

    def test_configured_drive_bones_ignore_collection_only_bones(self):
        names = configured_drive_bone_names([
            {
                "bone_name": "腰",
                "rigify_type": "spines.basic_spine",
                "chain_bones": ["腰", "上半身", "上半身2"],
            },
        ])
        self.assertEqual(names, {"腰", "上半身", "上半身2"})
        self.assertNotIn("センター", names)


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


    def test_infers_japanese_mmd_arm_leg_spine_and_head_topology(self):
        parents = {
            "腰": None,
            "上半身": "腰",
            "上半身2": "上半身",
            "下半身": "腰",
            "首": "上半身2",
            "頭": "首",
            "腕.L": None,
            "ひじ.L": "腕.L",
            "手首.L": "ひじ.L",
            "足.L": None,
            "ひざ.L": "足.L",
            "足首.L": "ひざ.L",
            "つま先.L": "足首.L",
            "Extra.L": "つま先.L",
        }
        configs = [
            {"bone_name": "腰", "rigify_type": "spines.basic_spine"},
            {"bone_name": "首", "rigify_type": "spines.super_head"},
            {"bone_name": "腕.L", "rigify_type": "limbs.arm"},
            {"bone_name": "足.L", "rigify_type": "limbs.leg"},
        ]

        operations = infer_rigify_topology(configs, parents)

        self.assertIn(("腰", "上半身", True), operations)
        self.assertIn(("上半身", "上半身2", True), operations)
        self.assertIn(("上半身2", "首", False), operations)
        self.assertIn(("首", "頭", True), operations)
        self.assertIn(("腕.L", "ひじ.L", True), operations)
        self.assertIn(("ひじ.L", "手首.L", True), operations)
        self.assertIn(("足.L", "ひざ.L", True), operations)
        self.assertIn(("ひざ.L", "足首.L", True), operations)
        self.assertIn(("足首.L", "つま先.L", True), operations)
        self.assertIn(("足首.L", "Extra.L", False), operations)

    def test_explicit_leg_chain_connects_main_and_parents_heel(self):
        parents = {
            "Thigh_L": None,
            "Knee_L": "Thigh_L",
            "Foot_L": "Knee_L",
            "Toe_L": "Foot_L",
            "Heel_L": "Toe_L",
        }
        configs = [{
            "bone_name": "Thigh_L",
            "rigify_type": "limbs.leg",
            "chain_bones": ["Thigh_L", "Knee_L", "Foot_L", "Toe_L", "Heel_L"],
        }]

        operations = infer_rigify_topology(configs, parents)

        self.assertEqual(operations, [
            ("Thigh_L", "Knee_L", True),
            ("Knee_L", "Foot_L", True),
            ("Foot_L", "Toe_L", True),
            ("Foot_L", "Heel_L", False),
        ])
        self.assertEqual(EXPLICIT_CHAIN_MIN_LENGTHS["limbs.leg"], 4)

    def test_explicit_leg_chain_omits_heel_when_not_listed(self):
        parents = {
            "足.L": None,
            "ひざ.L": "足.L",
            "足首.L": "ひざ.L",
            "つま先.L": "足首.L",
            "Extra.L": "つま先.L",
        }
        configs = [{
            "bone_name": "足.L",
            "rigify_type": "limbs.leg",
            "chain_bones": ["足.L", "ひざ.L", "足首.L", "つま先.L"],
        }]

        operations = infer_rigify_topology(configs, parents)

        self.assertEqual(operations, [
            ("足.L", "ひざ.L", True),
            ("ひざ.L", "足首.L", True),
            ("足首.L", "つま先.L", True),
        ])

    def test_inferred_leg_topology_allows_missing_heel(self):
        parents = {
            "Thigh_L": None,
            "Knee_L": "Thigh_L",
            "Foot_L": "Knee_L",
            "Toe_L": "Foot_L",
        }

        operations = infer_rigify_topology(
            [{"bone_name": "Thigh_L", "rigify_type": "limbs.leg"}],
            parents,
        )

        self.assertEqual(operations, [
            ("Thigh_L", "Knee_L", True),
            ("Knee_L", "Foot_L", True),
            ("Foot_L", "Toe_L", True),
        ])

    def test_plan_missing_leg_heels_for_explicit_chain(self):
        bones = {
            "足.L": {"head": (0.1, 0.0, 0.9), "tail": (0.1, 0.0, 0.5)},
            "ひざ.L": {"head": (0.1, 0.0, 0.5), "tail": (0.1, 0.05, 0.12)},
            "足首.L": {"head": (0.1, 0.05, 0.12), "tail": (0.1, -0.05, 0.04)},
            "つま先.L": {"head": (0.1, -0.05, 0.04), "tail": (0.1, -0.12, 0.04)},
        }
        configs = [{
            "bone_name": "足.L",
            "rigify_type": "limbs.leg",
            "chain_bones": ["足.L", "ひざ.L", "足首.L", "つま先.L", "Extra.L"],
        }]

        plans = plan_missing_leg_heels(configs, bones)

        self.assertEqual(len(plans), 1)
        plan = plans[0]
        self.assertEqual(plan["name"], "Extra.L")
        self.assertEqual(plan["parent"], "足首.L")
        self.assertFalse(plan["use_connect"])
        # Marker sits under the foot and points roughly backward (+Y).
        self.assertAlmostEqual(plan["head"][0], 0.1, places=5)
        self.assertLess(plan["head"][2], bones["足首.L"]["head"][2])
        self.assertGreater(plan["tail"][1], plan["head"][1])
        self.assertAlmostEqual(plan["tail"][2], plan["head"][2], places=5)

    def test_plan_missing_leg_heels_skips_existing_heel(self):
        bones = {
            "Thigh_L": {"head": (0.1, 0.0, 1.0), "tail": (0.1, 0.0, 0.6)},
            "Knee_L": {"head": (0.1, 0.0, 0.6), "tail": (0.1, 0.0, 0.2)},
            "Foot_L": {"head": (0.1, 0.0, 0.2), "tail": (0.1, -0.08, 0.05)},
            "Toe_L": {"head": (0.1, -0.08, 0.05), "tail": (0.1, -0.14, 0.05)},
            "Heel_L": {"head": (0.1, 0.02, 0.02), "tail": (0.1, 0.08, 0.02)},
        }
        configs = [{
            "bone_name": "Thigh_L",
            "rigify_type": "limbs.leg",
            "chain_bones": ["Thigh_L", "Knee_L", "Foot_L", "Toe_L", "Heel_L"],
        }]

        self.assertEqual(plan_missing_leg_heels(configs, bones), [])

    def test_plan_missing_leg_heels_for_inferred_leg(self):
        bones = {
            "Thigh_L": {"head": (0.1, 0.0, 1.0), "tail": (0.1, 0.0, 0.6)},
            "Knee_L": {"head": (0.1, 0.0, 0.6), "tail": (0.1, 0.0, 0.2)},
            "Foot_L": {"head": (0.1, 0.0, 0.2), "tail": (0.1, -0.08, 0.05)},
            "Toe_L": {"head": (0.1, -0.08, 0.05), "tail": (0.1, -0.14, 0.05)},
        }
        parents = {
            "Thigh_L": None,
            "Knee_L": "Thigh_L",
            "Foot_L": "Knee_L",
            "Toe_L": "Foot_L",
        }

        plans = plan_missing_leg_heels(
            [{"bone_name": "Thigh_L", "rigify_type": "limbs.leg"}],
            bones,
            parents=parents,
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["name"], "Thigh_L_heel")
        self.assertEqual(plans[0]["parent"], "Foot_L")

    def test_resolve_collection_rules_can_allow_missing_exact(self):
        resolved = resolve_collection_rules(
            ["足.L", "ひざ.L", "足首.L", "つま先.L"],
            [{
                "name": "Leg.L",
                "rules": [
                    {"kind": "EXACT", "pattern": "足.L"},
                    {"kind": "EXACT", "pattern": "Extra.L"},
                ],
            }],
            allow_missing_exact={"Extra.L"},
        )
        self.assertEqual(resolved["Leg.L"], ["足.L"])




    def test_explicit_spine_chain_overrides_source_parenting(self):
        parents = {
            "Position": None,
            "Hip": "Position",
            "UpBody_Ctrl": "Hip",
            "Waist": "UpBody_Ctrl",
            "Spine": "Waist",
            "Chest": "Spine",
        }
        configs = [{
            "bone_name": "Hip",
            "rigify_type": "spines.basic_spine",
            "chain_bones": ["Hip", "Waist", "Spine", "Chest"],
        }]

        operations = infer_rigify_topology(configs, parents)

        self.assertEqual(operations, [
            ("Hip", "Waist", True),
            ("Waist", "Spine", True),
            ("Spine", "Chest", True),
        ])

    def test_super_head_root_is_disconnected_from_parent_rig(self):
        parents = {
            "Waist": None,
            "Spine": "Waist",
            "Chest": "Spine",
            "Neck": "Chest",
            "Head": "Neck",
        }

        operations = infer_rigify_topology(
            [{"bone_name": "Neck", "rigify_type": "spines.super_head"}],
            parents,
        )

        self.assertEqual(
            operations,
            [
                ("Chest", "Neck", False),
                ("Neck", "Head", True),
            ],
        )

    def test_basic_tail_does_not_connect_implicitly(self):
        parents = {
            "EarPhysics": None,
            "Ear_01_L": "EarPhysics",
            "Ear_02_L": "Ear_01_L",
        }

        operations = infer_rigify_topology(
            [{"bone_name": "Ear_01_L", "rigify_type": "spines.basic_tail"}],
            parents,
        )

        self.assertEqual(operations, [])
        self.assertEqual(
            EXPLICIT_CHAIN_MIN_LENGTHS["spines.basic_tail"],
            2,
        )

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
                "chain_bones": [],
                "parameters": {},
                "compatibility": DEFAULT_COMPATIBILITY,
            }],
            "bone_rules": [],
            "collections": [{
                "name": "Controls",
                "ui_title": "Main",
                "ui_row": 1,
                "row_order": 0,
                "color_set": "FK",
                "visible_after_generation": True,
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

    def test_root_color_set_must_exist(self):
        payload = BoneRuleTests.valid_payload()
        payload["root_color_set"] = "Missing"

        result = validate_config(payload, ["spine"], ["basic.raw_copy"])

        self.assertFalse(result.ok)

        payload["root_color_set"] = "Root"
        payload["color_sets"] = [{
            "name": "Root",
            "normal": [0.1, 0.2, 0.3],
            "select": [0.4, 0.5, 0.6],
            "active": [0.7, 0.8, 0.9],
            "standard_colors_lock": False,
        }]
        result = validate_config(payload, ["spine"], ["basic.raw_copy"])
        self.assertTrue(result.ok)
        self.assertEqual(normalize_config(payload)["root_color_set"], "Root")

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


class BuiltInPresetTests(unittest.TestCase):
    def test_mmd_jp_preset_is_valid_for_standard_bone_set(self):
        from re_rigify.presets import build_preset_payload, list_presets

        self.assertEqual(
            list_presets(),
            [("mmd_jp", "MMD", "Standard MMD armature names")],
        )
        payload = build_preset_payload("mmd_jp")
        bone_names = {
            "全ての親", "センター", "グルーブ", "腰", "下半身", "上半身", "上半身2",
            "首", "頭",
            "肩.L", "肩.R", "腕.L", "腕.R", "ひじ.L", "ひじ.R", "手首.L", "手首.R",
            "足.L", "足.R", "ひざ.L", "ひざ.R", "足首.L", "足首.R",
            "つま先.L", "つま先.R",
        }
        for side in ("L", "R"):
            for root, a, b in (
                ("親指０", "親指１", "親指２"),
                ("人指１", "人指２", "人指３"),
                ("中指１", "中指２", "中指３"),
                ("薬指１", "薬指２", "薬指３"),
                ("小指１", "小指２", "小指３"),
            ):
                bone_names.update({f"{root}.{side}", f"{a}.{side}", f"{b}.{side}"})

        result = validate_config(
            payload,
            sorted(bone_names),
            {
                "basic.super_copy",
                "limbs.arm",
                "limbs.leg",
                "limbs.super_finger",
                "spines.basic_spine",
                "spines.super_head",
            },
        )
        self.assertTrue(result.ok, result.errors)

        by_name = {item["bone_name"]: item for item in payload["bones"]}
        self.assertEqual(
            by_name["肩.L"]["parameters"]["super_copy_widget_type"],
            "shoulder",
        )
        self.assertEqual(
            by_name["腕.L"]["parameters"]["fk_coll_refs"],
            ["Arm FK.L"],
        )
        self.assertEqual(
            by_name["足.L"]["chain_bones"],
            ["足.L", "ひざ.L", "足首.L", "つま先.L", "Extra.L"],
        )
        self.assertEqual(
            by_name["腰"]["parameters"]["fk_coll_refs"],
            ["Torso FK"],
        )
        self.assertEqual(by_name["腰"]["parameters"]["pivot_pos"], 1)
        self.assertTrue(
            by_name["人指１.L"]["compatibility"]["force_connect_chain"]
        )

        rows = {}
        for collection in payload["collections"]:
            rows.setdefault(collection["ui_row"], []).append(collection["name"])
        self.assertEqual(rows[3], ["Arm.L", "Arm.R"])
        self.assertEqual(rows[4], ["Arm FK.L", "Arm FK.R"])
        self.assertEqual(rows[5], ["Arm Tweak.L", "Arm Tweak.R"])
        self.assertNotIn(2, rows)
        self.assertNotIn(6, rows)
        self.assertNotIn(10, rows)
        visible = {
            item["name"]
            for item in payload["collections"]
            if item["visible_after_generation"]
        }
        self.assertIn("Arm.L", visible)
        self.assertNotIn("Arm FK.L", visible)
        self.assertNotIn("Fingers Tweak.L", visible)

    def test_mmd_jp_preset_is_valid_without_extra_heels(self):
        from re_rigify.presets import build_preset_payload

        payload = build_preset_payload("mmd_jp")
        bone_names = {
            "全ての親", "センター", "グルーブ", "腰", "下半身", "上半身", "上半身2",
            "首", "頭",
            "肩.L", "肩.R", "腕.L", "腕.R", "ひじ.L", "ひじ.R", "手首.L", "手首.R",
            "足.L", "足.R", "ひざ.L", "ひざ.R", "足首.L", "足首.R",
            "つま先.L", "つま先.R",
        }
        for side in ("L", "R"):
            for root, a, b in (
                ("親指０", "親指１", "親指２"),
                ("人指１", "人指２", "人指３"),
                ("中指１", "中指２", "中指３"),
                ("薬指１", "薬指２", "薬指３"),
                ("小指１", "小指２", "小指３"),
            ):
                bone_names.update({f"{root}.{side}", f"{a}.{side}", f"{b}.{side}"})

        result = validate_config(
            payload,
            sorted(bone_names),
            {
                "basic.super_copy",
                "limbs.arm",
                "limbs.leg",
                "limbs.super_finger",
                "spines.basic_spine",
                "spines.super_head",
            },
        )
        self.assertTrue(result.ok, result.errors)

        plans = plan_missing_leg_heels(
            payload["bones"],
            {
                name: {"head": (0.0, 0.0, 1.0), "tail": (0.0, 0.0, 0.5)}
                for name in bone_names
            } | {
                "足首.L": {"head": (0.1, 0.05, 0.12), "tail": (0.1, -0.05, 0.04)},
                "足首.R": {"head": (-0.1, 0.05, 0.12), "tail": (-0.1, -0.05, 0.04)},
                "つま先.L": {"head": (0.1, -0.05, 0.04), "tail": (0.1, -0.12, 0.04)},
                "つま先.R": {"head": (-0.1, -0.05, 0.04), "tail": (-0.1, -0.12, 0.04)},
            },
        )
        self.assertEqual(
            {(plan["name"], plan["parent"]) for plan in plans},
            {("Extra.L", "足首.L"), ("Extra.R", "足首.R")},
        )


    def test_unknown_preset_is_rejected(self):
        from re_rigify.presets import build_preset_payload

        with self.assertRaisesRegex(ConfigError, "Unknown built-in preset"):
            build_preset_payload("nope")


if __name__ == "__main__":
    unittest.main()
