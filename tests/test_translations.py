import builtins
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
