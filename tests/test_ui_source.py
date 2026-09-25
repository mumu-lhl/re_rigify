import ast
import unittest
from pathlib import Path


class UIListTranslationTests(unittest.TestCase):
    def test_all_ui_list_labels_disable_translation(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        missing = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or "_UL_" not in node.name:
                continue
            for call in (child for child in ast.walk(node) if isinstance(child, ast.Call)):
                function = call.func
                if not isinstance(function, ast.Attribute) or function.attr != "label":
                    continue
                translate = next((item.value for item in call.keywords if item.arg == "translate"), None)
                if not isinstance(translate, ast.Constant) or translate.value is not False:
                    missing.append((node.name, call.lineno))
        self.assertEqual(missing, [], f"UIList labels missing translate=False: {missing}")


class PanelStructureTests(unittest.TestCase):
    def test_super_finger_compatibility_exposes_primary_axis(self):
        config_source = Path("re_rigify/blender_config.py").read_text(encoding="utf-8")
        ui_source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        self.assertIn("super_finger_primary_axis:", config_source)
        self.assertIn('default="AUTO"', config_source)
        for axis in ("AUTO", "+X", "-X", "+Y", "-Y", "+Z", "-Z"):
            self.assertIn(f'("{axis}"', config_source)
        self.assertIn(
            'compatibility.prop(item, "super_finger_primary_axis")',
            ui_source,
        )
        self.assertIn("super_finger_roll_alignment:", config_source)
        for alignment in ("AUTO", "GLOBAL_POS_Z", "GLOBAL_NEG_Y"):
            self.assertIn(f'"{alignment}"', config_source)
        self.assertIn(
            'compatibility.prop(item, "super_finger_roll_alignment")',
            ui_source,
        )

    def test_main_panel_is_available_without_an_armature(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        main = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "RERIGIFY_PT_Main"
        )
        methods = {
            node.name: node
            for node in main.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("poll", methods)
        self.assertIn("return True", ast.unparse(methods["poll"]))
        self.assertIn("Select an armature", ast.unparse(methods["draw"]))

    def test_main_panel_exposes_builtin_preset_controls(self):
        ui_source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        operator_source = Path("re_rigify/operators.py").read_text(encoding="utf-8")
        self.assertIn("Built-in Preset", ui_source)
        self.assertIn('re_rigify.apply_preset', ui_source)
        self.assertIn("Apply & Generate", ui_source)
        self.assertIn("re_rigify_preset", ui_source)
        self.assertIn('bl_idname = "re_rigify.apply_preset"', operator_source)
        self.assertIn("RERIGIFY_OT_ApplyPreset", operator_source)
        self.assertTrue(Path("re_rigify/presets.py").exists())

    def test_apply_preset_operator_keeps_source_selected(self):
        operator_source = Path("re_rigify/operators.py").read_text(encoding="utf-8")
        apply_idx = operator_source.index("class RERIGIFY_OT_ApplyPreset")
        generate_idx = operator_source.index("class RERIGIFY_OT_Generate")
        body = operator_source[apply_idx:generate_idx]
        self.assertIn("if not self.generate:", body)
        self.assertIn("select_only(context, obj)", body)
        # Generate path may still focus the new rig; apply-only must not.
        before_generate = body.split("if not self.generate:", 1)[1].split(
            "obj, errors = validate_active", 1
        )[0]
        self.assertIn("select_only(context, obj)", before_generate)



    def test_color_panel_exposes_root_color_set(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        panel = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "RERIGIFY_PT_Colors"
        )
        self.assertIn("root_color_set_name", ast.unparse(panel))

    def test_bone_and_rule_parameters_use_distinct_carriers(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("_parameter_carrier_name", functions)
        helper_source = ast.unparse(functions["_parameter_carrier_name"])
        self.assertIn("target_kind", helper_source)
        self.assertIn("RULE_HELPER_NAME", helper_source)
        refs_source = ast.unparse(functions["_active_parameter_refs"])
        self.assertIn("_bound_bindings", refs_source)
        self.assertIn("RULE_HELPER_NAME", refs_source)

    def test_rule_preview_ui_is_registered(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        classes = {
            node.name for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        self.assertIn("RERIGIFY_UL_BoneRulePreview", classes)
        self.assertIn('"RERIGIFY_UL_BoneRulePreview"', source)
        self.assertIn("active_bone_rule_preview_index", source)

    def test_bone_list_filters_rule_managed_rows(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        bone_list = next(
            node for node in tree.body
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "RERIGIFY_UL_Bones"
            )
        )
        methods = {
            node.name: node
            for node in bone_list.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("filter_items", methods)
        self.assertIn("managed_rule_id", ast.unparse(methods["filter_items"]))

    def test_rule_sync_only_cleans_persistent_bone_rows(self):
        source = Path("re_rigify/rules.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("cleanup_bone_rule_rows", functions)
        sync_source = ast.unparse(functions["sync_bone_rules"])
        self.assertNotIn(".bones.add(", sync_source)

    def test_chain_rule_drive_helpers_disable_scale_inheritance(self):
        source = Path("re_rigify/drive.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("_chain_rule_bone_names", functions)
        self.assertNotIn(
            "managed_rule_id",
            ast.unparse(functions["_chain_rule_bone_names"]),
        )
        helper_builder = functions["_build_drive_helpers"]
        assignments = [
            node
            for node in ast.walk(helper_builder)
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Attribute)
                    and target.attr == "inherit_scale"
                    for target in node.targets
                )
            )
        ]
        self.assertTrue(assignments)
        self.assertTrue(any(
            isinstance(node, ast.Constant) and node.value == "NONE"
            for node in ast.walk(assignments[0].value)
        ))

    def test_bone_rule_rna_and_sync_module_exist(self):
        source = Path("re_rigify/blender_config.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        classes = {
            node.name for node in tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertIn("RERIGIFY_PG_BoneRule", classes)
        self.assertIn("apply_as_chain", source)
        self.assertTrue(Path("re_rigify/rules.py").exists())

    def test_bone_rule_panels_and_operators_are_registered(self):
        ui_source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        ui_tree = ast.parse(ui_source)
        ui_classes = {
            node.name for node in ui_tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertTrue({
            "RERIGIFY_UL_BoneRules",
            "RERIGIFY_PT_BoneRules",
            "RERIGIFY_PT_BoneRuleParameters",
        }.issubset(ui_classes))

        operator_source = Path("re_rigify/operators.py").read_text(encoding="utf-8")
        operator_tree = ast.parse(operator_source)
        operator_classes = {
            node.name for node in operator_tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertTrue({
            "RERIGIFY_OT_BoneRuleAdd",
            "RERIGIFY_OT_BoneRuleRemove",
            "RERIGIFY_OT_BoneRuleMove",
            "RERIGIFY_OT_BoneRuleSync",
        }.issubset(operator_classes))

    def test_bone_rule_panel_draws_chain_mode(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        panel = next(
            node for node in tree.body
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "RERIGIFY_PT_BoneRules"
            )
        )
        properties = {
            call.args[1].value
            for call in ast.walk(panel)
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "prop"
                and len(call.args) > 1
                and isinstance(call.args[1], ast.Constant)
            )
        }
        self.assertIn("apply_as_chain", properties)

    def test_bone_move_operator_and_buttons_are_registered(self):
        operator_source = Path("re_rigify/operators.py").read_text(encoding="utf-8")
        operator_tree = ast.parse(operator_source)
        operator_classes = {
            node.name for node in operator_tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertIn("RERIGIFY_OT_BoneMove", operator_classes)

        ui_source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        self.assertEqual(ui_source.count('"re_rigify.bone_move"'), 2)
        self.assertIn('icon="TRIA_UP"', ui_source)
        self.assertIn('icon="TRIA_DOWN"', ui_source)

    def test_save_flushes_and_removes_parameter_carrier(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        handler = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_save_pre"
        )
        calls = [
            node.value.func.id
            for node in handler.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ]
        self.assertEqual(
            calls,
            ["flush_parameter_carrier", "remove_parameter_carrier"],
        )

    def test_workflow_uses_nested_panels(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        classes = {
            node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
        }
        expected_parents = {
            "RERIGIFY_PT_Bones": "RERIGIFY_PT_main",
            "RERIGIFY_PT_BoneParameters": "RERIGIFY_PT_bones",
            "RERIGIFY_PT_Collections": "RERIGIFY_PT_main",
            "RERIGIFY_PT_CollectionRules": "RERIGIFY_PT_collections",
            "RERIGIFY_PT_Layout": "RERIGIFY_PT_main",
            "RERIGIFY_PT_Colors": "RERIGIFY_PT_main",
            "RERIGIFY_PT_Configuration": "RERIGIFY_PT_main",
        }
        for class_name, parent_id in expected_parents.items():
            self.assertIn(class_name, classes)
            assignments = {
                statement.targets[0].id: statement.value.value
                for statement in classes[class_name].body
                if isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and isinstance(statement.value, ast.Constant)
                for target in statement.targets
            }
            self.assertEqual(assignments.get("bl_parent_id"), parent_id)

    def test_secondary_panels_default_closed(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        default_closed = {
            "RERIGIFY_PT_BoneParameters",
            "RERIGIFY_PT_CollectionRules",
            "RERIGIFY_PT_Layout",
            "RERIGIFY_PT_Colors",
            "RERIGIFY_PT_Configuration",
        }
        found = set()
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name not in default_closed:
                continue
            found.add(node.name)
            options = next(
                (
                    statement.value
                    for statement in node.body
                    if isinstance(statement, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "bl_options"
                        for target in statement.targets
                    )
                ),
                None,
            )
            self.assertIsInstance(options, ast.Set)
            self.assertIn("DEFAULT_CLOSED", {item.value for item in options.elts})
        self.assertEqual(found, default_closed)

    def test_bone_panel_draws_compatibility_settings(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        panel = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "RERIGIFY_PT_Bones"
        )
        drawn_properties = {
            call.args[1].value
            for call in ast.walk(panel)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in {"prop", "prop_search"}
            and len(call.args) >= 2
            and isinstance(call.args[1], ast.Constant)
        }
        self.assertTrue({
            "force_connect_chain",
            "skin_eye_compatibility",
            "roll_bones_enabled",
            "upper_arm_roll_bone",
            "forearm_roll_bone",
            "eye_forward_axis",
            "upper_lid_pattern",
            "lower_lid_pattern",
            "synthetic_lids_fallback",
        }.issubset(drawn_properties))
        self.assertIn("spines.basic_tail", ast.unparse(panel))

    def test_parameter_panel_routes_rigify_operators_to_carrier(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        panel = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "RERIGIFY_PT_BoneParameters"
        )
        calls = [
            call for call in ast.walk(panel)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "RigifyParameterLayout"
        ]
        self.assertEqual(len(calls), 1)
        self.assertFalse(any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "context_pointer_set"
            for call in ast.walk(panel)
        ))

    def test_parameter_collection_operators_are_registered(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        classes = {
            node.name for node in tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertTrue({
            "RERIGIFY_OT_parameter_collection_ref_add",
            "RERIGIFY_OT_parameter_collection_ref_remove",
        }.issubset(classes))

    def test_explicit_chain_ui_and_operators_are_registered(self):
        source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        classes = {
            node.name for node in tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertTrue({
            "RERIGIFY_UL_ChainBones",
        }.issubset(classes))

        operator_source = Path("re_rigify/operators.py").read_text(encoding="utf-8")
        operator_tree = ast.parse(operator_source)
        operator_classes = {
            node.name for node in operator_tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertTrue({
            "RERIGIFY_OT_ChainAddSelected",
            "RERIGIFY_OT_ChainRemove",
            "RERIGIFY_OT_ChainMove",
        }.issubset(operator_classes))

    def test_quick_human_setup_and_arrange_ui_buttons_and_operators(self):
        operator_source = Path("re_rigify/operators.py").read_text(encoding="utf-8")
        operator_tree = ast.parse(operator_source)
        operator_classes = {
            node.name for node in operator_tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertIn("RERIGIFY_OT_QuickSetupBones", operator_classes)
        self.assertIn("RERIGIFY_OT_ArrangeCollectionUI", operator_classes)
        self.assertIn("finger_preset:", operator_source)
        self.assertIn("enable_finger_ik:", operator_source)
        self.assertIn("thumb_roll_alignment:", operator_source)
        self.assertIn("eye_forward_axis:", operator_source)

        ui_source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
        self.assertIn('"re_rigify.quick_setup_bones"', ui_source)
        self.assertGreaterEqual(ui_source.count('"re_rigify.arrange_collection_ui"'), 2)


if __name__ == "__main__":
    unittest.main()
