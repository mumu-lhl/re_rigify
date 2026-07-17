import unittest

from re_rigify.compatibility import (
    EyeLandmark,
    plan_connected_chain,
    plan_eye_landmarks,
)
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


class EyePlanningTests(unittest.TestCase):
    def setUp(self):
        self.upper = [
            EyeLandmark("Eye_up_01_L", (-2.0, -0.2, 1.0)),
            EyeLandmark("Eye_up_02_L", (0.0, -0.3, 2.0)),
            EyeLandmark("Eye_up_03_L", (2.0, -0.2, 1.0)),
        ]
        self.lower = [
            EyeLandmark("Eye_bottom_01_L", (-2.0, -0.2, -1.0)),
            EyeLandmark("Eye_bottom_02_L", (0.0, -0.3, -2.0)),
            EyeLandmark("Eye_bottom_03_L", (2.0, -0.2, -1.0)),
        ]

    def test_auto_axis_and_chains_share_both_corners(self):
        plan = plan_eye_landmarks(
            "Eye_L", (0.0, 0.0, 0.0), 1.0,
            self.upper, self.lower, "AUTO",
        )

        self.assertEqual(plan.forward_axis, (0.0, -1.0, 0.0))
        self.assertEqual(len(plan.upper), len(self.upper))
        self.assertEqual(len(plan.lower), len(self.lower))
        self.assertEqual(plan.upper[0].head, plan.lower[0].head)
        self.assertEqual(plan.upper[-1].tail, plan.lower[-1].tail)
        self.assertEqual(
            [segment.source_name for segment in plan.upper],
            [landmark.name for landmark in self.upper],
        )

    def test_explicit_axis_is_preserved(self):
        plan = plan_eye_landmarks(
            "Eye_L", (0.0, 0.0, 0.0), 1.0,
            self.upper, self.lower, "+X",
        )

        self.assertEqual(plan.forward_axis, (1.0, 0.0, 0.0))

    def test_too_few_real_landmarks_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "upper eyelid.*at least 2"):
            plan_eye_landmarks(
                "Eye_L", (0.0, 0.0, 0.0), 1.0,
                self.upper[:1], self.lower, "-Y",
            )

    def test_ambiguous_auto_axis_is_rejected(self):
        centered_upper = [
            EyeLandmark("a", (-1.0, 0.0, 1.0)),
            EyeLandmark("b", (1.0, 0.0, 1.0)),
        ]
        centered_lower = [
            EyeLandmark("c", (-1.0, 0.0, -1.0)),
            EyeLandmark("d", (1.0, 0.0, -1.0)),
        ]
        with self.assertRaisesRegex(ConfigError, "AUTO forward axis is ambiguous"):
            plan_eye_landmarks(
                "Eye_L", (0.0, 0.0, 0.0), 1.0,
                centered_upper, centered_lower, "AUTO",
            )


if __name__ == "__main__":
    unittest.main()
