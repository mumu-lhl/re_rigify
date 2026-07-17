"""Temporary metarig adaptations for production skeleton topology."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import re

from .core import ConfigError, unique_child_chain


CHAIN_MIN_LENGTHS = {
    "limbs.super_finger": 2,
}


@dataclass
class CompatibilityPlan:
    connections: list[tuple[str, str, bool]] = field(default_factory=list)
    eye_plans: list[object] = field(default_factory=list)
    source_to_helper: dict[str, str] = field(default_factory=dict)


Point = tuple[float, float, float]


@dataclass(frozen=True)
class EyeLandmark:
    name: str | None
    point: Point


@dataclass(frozen=True)
class EyeSegment:
    source_name: str | None
    helper_name: str
    head: Point
    tail: Point


@dataclass(frozen=True)
class EyePlan:
    eye_name: str
    forward_axis: Point
    upper: list[EyeSegment]
    lower: list[EyeSegment]


def plan_connected_chain(
    root: str,
    rigify_type: str,
    parents: dict[str, str | None],
    *,
    enabled: bool,
) -> list[tuple[str, str, bool]]:
    if not enabled:
        return []
    minimum = CHAIN_MIN_LENGTHS.get(rigify_type)
    if minimum is None:
        raise ConfigError(f"{rigify_type!r} does not support forced chain connection")
    chain = unique_child_chain(root, parents)
    if len(chain) < minimum:
        raise ConfigError(f"{root!r} ({rigify_type}) requires at least {minimum} connected bones")
    return [(parent, child, True) for parent, child in zip(chain, chain[1:])]


def _add(a: Point, b: Point) -> Point:
    return tuple(x + y for x, y in zip(a, b))


def _subtract(a: Point, b: Point) -> Point:
    return tuple(x - y for x, y in zip(a, b))


def _scale(value: Point, factor: float) -> Point:
    return tuple(component * factor for component in value)


def _average(points: list[Point]) -> Point:
    return tuple(sum(point[index] for point in points) / len(points) for index in range(3))


def _midpoint(a: Point, b: Point) -> Point:
    return _scale(_add(a, b), 0.5)


def _axis_vector(axis: str, eye_head: Point, landmarks: list[EyeLandmark]) -> Point:
    explicit = {
        "+X": (1.0, 0.0, 0.0),
        "-X": (-1.0, 0.0, 0.0),
        "+Y": (0.0, 1.0, 0.0),
        "-Y": (0.0, -1.0, 0.0),
    }
    if axis in explicit:
        return explicit[axis]
    if axis != "AUTO":
        raise ConfigError(f"invalid eye forward axis: {axis!r}")
    offset = _subtract(_average([landmark.point for landmark in landmarks]), eye_head)
    if max(abs(offset[0]), abs(offset[1])) < 1e-6:
        raise ConfigError("AUTO forward axis is ambiguous; choose ±X or ±Y")
    if abs(offset[0]) > abs(offset[1]):
        return (1.0 if offset[0] > 0 else -1.0, 0.0, 0.0)
    return (0.0, 1.0 if offset[1] > 0 else -1.0, 0.0)


def _side_suffix(name: str) -> str:
    match = re.search(r"(?:[._-])([LR])$", name, re.IGNORECASE)
    return f".{match.group(1).upper()}" if match else ""


def _synthetic_landmarks(
    eye_head: Point, eye_length: float, forward: Point, *, upper: bool
) -> list[EyeLandmark]:
    horizontal = (1.0, 0.0, 0.0) if forward[1] else (0.0, 1.0, 0.0)
    radius = max(eye_length, 1e-4) * 0.6
    height = radius * (0.5 if upper else -0.5)
    forward_offset = _scale(forward, radius * 0.15)
    return [
        EyeLandmark(
            None,
            _add(
                _add(eye_head, forward_offset),
                _add(_scale(horizontal, offset * radius), (0.0, 0.0, height)),
            ),
        )
        for offset in (-1.0, 0.0, 1.0)
    ]


def _segments(
    eye_name: str,
    landmarks: list[EyeLandmark],
    other: list[EyeLandmark],
    *,
    top: bool,
    horizontal_axis: int,
) -> list[EyeSegment]:
    ordered = sorted(landmarks, key=lambda landmark: landmark.point[horizontal_axis])
    other_ordered = sorted(other, key=lambda landmark: landmark.point[horizontal_axis])
    nodes = [_midpoint(ordered[0].point, other_ordered[0].point)]
    nodes.extend(
        _midpoint(first.point, second.point)
        for first, second in zip(ordered, ordered[1:])
    )
    nodes.append(_midpoint(ordered[-1].point, other_ordered[-1].point))
    vertical = "T" if top else "B"
    side = _side_suffix(eye_name)
    return [
        EyeSegment(
            landmark.name,
            f"RR-lid{index:02d}.{vertical}{side}",
            nodes[index - 1],
            nodes[index],
        )
        for index, landmark in enumerate(ordered, 1)
    ]


def plan_eye_landmarks(
    eye_name: str,
    eye_head: Point,
    eye_length: float,
    upper: list[EyeLandmark],
    lower: list[EyeLandmark],
    forward_axis: str,
    *,
    synthetic_fallback: bool = False,
) -> EyePlan:
    available = upper + lower
    if forward_axis == "AUTO" and not available:
        raise ConfigError("AUTO forward axis is ambiguous; choose ±X or ±Y")
    forward = _axis_vector(forward_axis, eye_head, available)
    if len(upper) < 2:
        if not synthetic_fallback:
            raise ConfigError("upper eyelid pattern must match at least 2 bones")
        upper = _synthetic_landmarks(eye_head, eye_length, forward, upper=True)
    if len(lower) < 2:
        if not synthetic_fallback:
            raise ConfigError("lower eyelid pattern must match at least 2 bones")
        lower = _synthetic_landmarks(eye_head, eye_length, forward, upper=False)
    horizontal_axis = 0 if forward[1] else 1
    return EyePlan(
        eye_name,
        forward,
        _segments(eye_name, upper, lower, top=True, horizontal_axis=horizontal_axis),
        _segments(eye_name, lower, upper, top=False, horizontal_axis=horizontal_axis),
    )


def build_compatibility_plan(obj, bone_configs: list[dict]) -> CompatibilityPlan:
    parents = {
        bone.name: bone.parent.name if bone.parent else None
        for bone in obj.data.bones
    }
    plan = CompatibilityPlan()
    for config in bone_configs:
        compatibility = config.get("compatibility", {})
        plan.connections.extend(plan_connected_chain(
            config["bone_name"],
            config["rigify_type"],
            parents,
            enabled=compatibility.get("force_connect_chain", False),
        ))
        if (
            config["rigify_type"] == "face.skin_eye"
            and compatibility.get("skin_eye_compatibility", False)
        ):
            eye_bone = obj.data.bones.get(config["bone_name"])
            if eye_bone is None:
                raise ConfigError(f"bone does not exist: {config['bone_name']!r}")
            upper_pattern = compatibility.get("upper_lid_pattern", "")
            lower_pattern = compatibility.get("lower_lid_pattern", "")
            upper = [
                EyeLandmark(bone.name, tuple(bone.head_local))
                for bone in obj.data.bones
                if upper_pattern and fnmatchcase(bone.name, upper_pattern)
            ]
            lower = [
                EyeLandmark(bone.name, tuple(bone.head_local))
                for bone in obj.data.bones
                if lower_pattern and fnmatchcase(bone.name, lower_pattern)
            ]
            plan.eye_plans.append(plan_eye_landmarks(
                eye_bone.name,
                tuple(eye_bone.head_local),
                eye_bone.length,
                upper,
                lower,
                compatibility.get("eye_forward_axis", "AUTO"),
                synthetic_fallback=compatibility.get("synthetic_lids_fallback", False),
            ))
    return plan


def apply_compatibility_plan(obj, plan: CompatibilityPlan) -> dict[str, str]:
    if not plan.connections and not plan.eye_plans:
        return dict(plan.source_to_helper)
    import bpy
    from mathutils import Vector

    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit_bones = obj.data.edit_bones
        for parent_name, child_name, connected in plan.connections:
            child = edit_bones[child_name]
            child.parent = edit_bones[parent_name]
            child.use_connect = connected
        for eye_plan in plan.eye_plans:
            eye = edit_bones[eye_plan.eye_name]
            eye.tail = eye.head + Vector(eye_plan.forward_axis) * eye.length
            for chain in (eye_plan.upper, eye_plan.lower):
                previous = None
                for segment in chain:
                    helper = edit_bones.new(segment.helper_name)
                    helper.head = segment.head
                    helper.tail = segment.tail
                    helper.parent = previous or eye
                    helper.use_connect = previous is not None
                    previous = helper
                    if segment.source_name:
                        plan.source_to_helper[segment.source_name] = helper.name
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    for eye_plan in plan.eye_plans:
        eye_bone = obj.data.bones[eye_plan.eye_name]
        for chain in (eye_plan.upper, eye_plan.lower):
            root = obj.pose.bones[chain[0].helper_name]
            root.rigify_type = "skin.stretchy_chain"
            if hasattr(root.rigify_parameters, "skin_chain_pivot_pos"):
                root.rigify_parameters.skin_chain_pivot_pos = max(1, len(chain) // 2)
            if hasattr(root.rigify_parameters, "bbones"):
                root.rigify_parameters.bbones = 5
            for segment in chain:
                helper_bone = obj.data.bones[segment.helper_name]
                for collection in eye_bone.collections:
                    collection.assign(helper_bone)
    return dict(plan.source_to_helper)
