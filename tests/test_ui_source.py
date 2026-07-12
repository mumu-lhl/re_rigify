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


if __name__ == "__main__":
    unittest.main()
