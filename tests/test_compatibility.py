import unittest

from re_rigify.compatibility import plan_connected_chain
from re_rigify.core import ConfigError


class ConnectedChainPlanningTests(unittest.TestCase):
    def test_super_finger_force_connect_builds_three_bone_chain(self):
        parents = {
            "Wrist_R": None,
            "Thumb_01_R": "Wrist_R",
            "Thumb_02_R": "Thumb_01_R",
            "Thumb_03_R": "Thumb_02_R",
        }

        result = plan_connected_chain(
            "Thumb_01_R", "limbs.super_finger", parents, enabled=True
        )

        self.assertEqual(result, [
            ("Thumb_01_R", "Thumb_02_R", True),
            ("Thumb_02_R", "Thumb_03_R", True),
        ])

    def test_disabled_chain_returns_no_operations(self):
        parents = {"root": None, "child": "root"}

        self.assertEqual(
            plan_connected_chain("root", "limbs.super_finger", parents, enabled=False),
            [],
        )

    def test_super_finger_requires_two_bones(self):
        with self.assertRaisesRegex(ConfigError, "requires at least 2"):
            plan_connected_chain(
                "Thumb_01_R",
                "limbs.super_finger",
                {"Thumb_01_R": None},
                enabled=True,
            )

    def test_force_connect_rejects_unsupported_type(self):
        with self.assertRaisesRegex(ConfigError, "does not support"):
            plan_connected_chain(
                "root",
                "basic.super_copy",
                {"root": None, "child": "root"},
                enabled=True,
            )


if __name__ == "__main__":
    unittest.main()
