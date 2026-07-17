import unittest

from re_rigify.compatibility import (
    EyeLandmark,
    apply_connection_operations,
    build_compatibility_plan,
    plan_connected_chain,
    plan_eye_landmarks,
    validate_compatibility,
)
from re_rigify.core import ConfigError, DEFAULT_COMPATIBILITY


class FakeBone:
    def __init__(self, name, parent=None, head=(0.0, 0.0, 0.0), length=1.0):
        self.name = name
        self.parent = parent
        self.head_local = head
        self.length = length


class FakeBones(list):
    def get(self, name):
        return next((bone for bone in self if bone.name == name), None)


class FakeObject:
    def __init__(self, bones):
        self.data = type("Data", (), {"bones": FakeBones(bones)})()


class FakeEditBone:
    def __init__(self, name, head, tail):
        self.name = name
        self.head = head
        self.tail = tail
        self.parent = None
        self.use_connect = False


class ConnectionApplicationTests(unittest.TestCase):
    def test_connection_moves_parent_tail_to_child_head(self):
        parent = FakeEditBone("Elbow_L", (0, 0, 0), (1, 0, 0))
        child = FakeEditBone("Wrist_L", (2, 0, 0), (3, 0, 0))
        bones = {"Elbow_L": parent, "Wrist_L": child}

        apply_connection_operations(bones, [("Elbow_L", "Wrist_L", True)])

        self.assertEqual(parent.tail, (2, 0, 0))
        self.assertEqual(child.head, (2, 0, 0))
        self.assertIs(child.parent, parent)
        self.assertTrue(child.use_connect)

    def test_disconnected_parenting_does_not_move_parent_tail(self):
        parent = FakeEditBone("Foot_L", (0, 0, 0), (1, 0, 0))
        child = FakeEditBone("Heel_L", (2, 0, 0), (3, 0, 0))
        bones = {"Foot_L": parent, "Heel_L": child}

        apply_connection_operations(bones, [("Foot_L", "Heel_L", False)])

        self.assertEqual(parent.tail, (1, 0, 0))
        self.assertIs(child.parent, parent)
        self.assertFalse(child.use_connect)


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


class CompatibilityValidationTests(unittest.TestCase):
    def test_arm_roll_bones_map_to_second_deform_segments(self):
        arm = FakeBone("Arm_L")
        elbow = FakeBone("Elbow_L", arm)
        wrist = FakeBone("Wrist_L", elbow)
        shoulder_roll = FakeBone("ShoulderRoll_L", arm)
        forearm_roll = FakeBone("ArmRoll_L", elbow)
        obj = FakeObject([arm, elbow, wrist, shoulder_roll, forearm_roll])
        config = {
            "bone_name": "Arm_L",
            "rigify_type": "limbs.arm",
            "parameters": {"segments": 2},
            "compatibility": {
                **DEFAULT_COMPATIBILITY,
                "roll_bones_enabled": True,
                "upper_arm_roll_bone": "ShoulderRoll_L",
                "forearm_roll_bone": "ArmRoll_L",
            },
        }

        plan = build_compatibility_plan(obj, [config])

        self.assertEqual(
            [
                (item.source_name, item.target_name, item.helper_name)
                for item in plan.roll_plans
            ],
            [
                ("ShoulderRoll_L", "DEF-Arm_L.001", "MCH-RR-ShoulderRoll_L"),
                ("ArmRoll_L", "DEF-Elbow_L.001", "MCH-RR-ArmRoll_L"),
            ],
        )

    def test_arm_roll_bones_fall_back_to_single_deform_segment(self):
        arm = FakeBone("Arm_L")
        roll = FakeBone("ShoulderRoll_L", arm)
        obj = FakeObject([arm, roll])
        config = {
            "bone_name": "Arm_L",
            "rigify_type": "limbs.arm",
            "parameters": {"segments": 1},
            "compatibility": {
                **DEFAULT_COMPATIBILITY,
                "roll_bones_enabled": True,
                "upper_arm_roll_bone": "ShoulderRoll_L",
            },
        }

        plan = build_compatibility_plan(obj, [config])

        self.assertEqual(
            [(item.source_name, item.target_name) for item in plan.roll_plans],
            [("ShoulderRoll_L", "DEF-Arm_L")],
        )

    def test_reports_ambiguous_forced_chain_with_bone_context(self):
        root = FakeBone("Thumb_01_R")
        obj = FakeObject([
            root,
            FakeBone("Thumb_02_R", root),
            FakeBone("Thumb_alt_R", root),
        ])
        config = {
            "bone_name": root.name,
            "rigify_type": "limbs.super_finger",
            "compatibility": {**DEFAULT_COMPATIBILITY, "force_connect_chain": True},
        }

        errors = validate_compatibility(obj, [config])

        self.assertEqual(len(errors), 1)
        self.assertIn("Bone 'Thumb_01_R'", errors[0])
        self.assertIn("ambiguous", errors[0])

    def test_reports_missing_real_eyelid_pattern_matches(self):
        eye = FakeBone("Eye_L", head=(0.0, 0.0, 0.0))
        obj = FakeObject([
            eye,
            FakeBone("Eye_up_01_L", head=(-1.0, -0.2, 1.0)),
            FakeBone("Eye_bottom_01_L", head=(-1.0, -0.2, -1.0)),
            FakeBone("Eye_bottom_02_L", head=(1.0, -0.2, -1.0)),
        ])
        config = {
            "bone_name": eye.name,
            "rigify_type": "face.skin_eye",
            "compatibility": {
                **DEFAULT_COMPATIBILITY,
                "skin_eye_compatibility": True,
                "eye_forward_axis": "-Y",
                "upper_lid_pattern": "Eye_up_*_L",
                "lower_lid_pattern": "Eye_bottom_*_L",
            },
        }

        errors = validate_compatibility(obj, [config])

        self.assertEqual(len(errors), 1)
        self.assertIn("upper eyelid pattern", errors[0])
        self.assertIn("Eye_up_*_L", errors[0])


if __name__ == "__main__":
    unittest.main()
