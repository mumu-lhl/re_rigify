import ast
import builtins
from pathlib import Path
import string
import unittest
from unittest.mock import patch

from re_rigify import translations


def fields(template):
    return {
        name
        for _literal, name, _format_spec, _conversion
        in string.Formatter().parse(template)
        if name is not None
    }


def literal_assignment(class_node, name):
    for statement in class_node.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            return statement.value.value
    return None


class TranslationCatalogTests(unittest.TestCase):
    def test_simplified_chinese_locale_aliases_share_one_catalog(self):
        self.assertIs(
            translations.TRANSLATIONS["zh_HANS"],
            translations.TRANSLATIONS["zh_CN"],
        )

    def test_catalog_has_valid_blender_key_shape(self):
        catalog = translations.TRANSLATIONS["zh_HANS"]
        self.assertTrue(catalog)
        for key, value in catalog.items():
            self.assertIsInstance(key, tuple)
            self.assertEqual(len(key), 2)
            self.assertIn(
                key[0],
                {
                    translations.DEFAULT_CONTEXT,
                    translations.OPERATOR_CONTEXT,
                },
            )
            self.assertIsInstance(key[1], str)
            self.assertIsInstance(value, str)

    def test_translations_preserve_named_placeholders(self):
        for (_context, source), translated in (
            translations.TRANSLATIONS["zh_HANS"].items()
        ):
            self.assertEqual(fields(source), fields(translated), source)

    def test_helpers_fall_back_to_english_without_blender(self):
        real_import = builtins.__import__

        def reject_bpy(name, *args, **kwargs):
            if name == "bpy" or name.startswith("bpy."):
                raise ModuleNotFoundError(name)
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=reject_bpy):
            self.assertEqual(translations.iface_("Bone"), "Bone")
            self.assertEqual(
                translations.format_iface(
                    "Added {count} bone(s)", count=2,
                ),
                "Added 2 bone(s)",
            )

    def test_domain_is_module_qualified(self):
        self.assertEqual(
            translations.TRANSLATION_DOMAIN,
            f"{translations.__name__}.catalog",
        )


class StaticSourceCoverageTests(unittest.TestCase):
    def test_operator_labels_and_descriptions_are_translated(self):
        tree = ast.parse(Path("re_rigify/operators.py").read_text())
        catalog = translations.TRANSLATIONS["zh_HANS"]
        missing = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            label = literal_assignment(node, "bl_label")
            description = literal_assignment(node, "bl_description")
            if (
                label
                and (translations.OPERATOR_CONTEXT, label) not in catalog
            ):
                missing.append(("operator", label))
            if (
                description
                and (translations.DEFAULT_CONTEXT, description) not in catalog
            ):
                missing.append(("description", description))
        self.assertEqual(missing, [])

    def test_panel_labels_and_literal_layout_text_are_translated(self):
        tree = ast.parse(Path("re_rigify/ui.py").read_text())
        catalog = translations.TRANSLATIONS["zh_HANS"]
        required = set()
        operator_required = set()
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                label = literal_assignment(node, "bl_label")
                if label:
                    target = (
                        operator_required
                        if node.name.startswith("RERIGIFY_OT_")
                        else required
                    )
                    target.add(label)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            for keyword in call.keywords:
                if (
                    keyword.arg == "text"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                    and keyword.value.value
                ):
                    required.add(keyword.value.value)
        missing = sorted(
            source
            for source in required
            if (translations.DEFAULT_CONTEXT, source) not in catalog
        )
        missing.extend(
            source
            for source in sorted(operator_required)
            if (translations.OPERATOR_CONTEXT, source) not in catalog
        )
        self.assertEqual(missing, [])

    def test_rna_names_descriptions_and_enum_text_are_translated(self):
        tree = ast.parse(Path("re_rigify/blender_config.py").read_text())
        catalog = translations.TRANSLATIONS["zh_HANS"]
        required = set()
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            for keyword in call.keywords:
                if (
                    keyword.arg in {"name", "description"}
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                    and keyword.value.value
                ):
                    required.add(keyword.value.value)
                if keyword.arg == "items" and isinstance(
                    keyword.value, (ast.Tuple, ast.List),
                ):
                    for item in keyword.value.elts:
                        if not isinstance(item, (ast.Tuple, ast.List)):
                            continue
                        for value in item.elts[1:3]:
                            if (
                                isinstance(value, ast.Constant)
                                and isinstance(value.value, str)
                                and value.value
                            ):
                                required.add(value.value)
        missing = sorted(
            source
            for source in required
            if (translations.DEFAULT_CONTEXT, source) not in catalog
        )
        self.assertEqual(missing, [])
