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
            and call.func.attr == "prop"
            and len(call.args) >= 2
            and isinstance(call.args[1], ast.Constant)
        }
        self.assertTrue({
            "force_connect_chain",
            "skin_eye_compatibility",
            "eye_forward_axis",
            "upper_lid_pattern",
            "lower_lid_pattern",
            "synthetic_lids_fallback",
        }.issubset(drawn_properties))


if __name__ == "__main__":
    unittest.main()
