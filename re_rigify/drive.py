"""Constraint bridge from a generated Rigify rig to the original deform armature."""

from __future__ import annotations

import json

import bpy

from .core import choose_drive_spec


CONSTRAINT_PREFIX = "Re-Rigify Drive"
DRIVE_MAP_PROPERTY = "re_rigify_drive_map"
ROTATION_DRIVE_MAP_PROPERTY = "re_rigify_rotation_drive_map"
_upgrade_enabled = False


def remove_drive_constraints(source: bpy.types.Object) -> int:
    removed = 0
    for pose_bone in source.pose.bones:
        for constraint in list(pose_bone.constraints):
            if constraint.name.startswith(CONSTRAINT_PREFIX):
                pose_bone.constraints.remove(constraint)
                removed += 1
    return removed


def _load_drive_map(rig: bpy.types.Object, property_name: str) -> dict[str, str]:
    try:
        value = json.loads(rig.get(property_name, "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        source_name: target_name
        for source_name, target_name in value.items()
        if isinstance(source_name, str) and isinstance(target_name, str)
    }


def connect_source_to_rig(source: bpy.types.Object, rig: bpy.types.Object) -> tuple[int, list[str]]:
    if source == rig or source.type != "ARMATURE" or rig.type != "ARMATURE":
        raise ValueError("Source and generated rig must be different armature objects")
    remove_drive_constraints(source)
    target_names = set(rig.pose.bones.keys())
    explicit = _load_drive_map(rig, DRIVE_MAP_PROPERTY)
    rotation_explicit = _load_drive_map(rig, ROTATION_DRIVE_MAP_PROPERTY)
    unmatched: list[str] = []
    mapped = 0
    for pose_bone in source.pose.bones:
        drive_spec = choose_drive_spec(
            pose_bone.name, target_names, explicit, rotation_explicit,
        )
        if drive_spec is None:
            unmatched.append(pose_bone.name)
            continue
        target_name, drive_type = drive_spec
        constraint = pose_bone.constraints.new(
            "COPY_ROTATION" if drive_type == "ROTATION" else "COPY_TRANSFORMS"
        )
        constraint.name = f"{CONSTRAINT_PREFIX}: {target_name}"
        constraint.target = rig
        constraint.subtarget = target_name
        if drive_type == "ROTATION":
            constraint.owner_space = "POSE"
            constraint.target_space = "POSE"
        else:
            # Copy pose deltas relative to each rig's own rest bones. Absolute World/Pose
            # matrices deform the source immediately when metarig topology was adjusted.
            constraint.owner_space = "LOCAL"
            constraint.target_space = "LOCAL_OWNER_ORIENT"
        constraint.mix_mode = "REPLACE"
        mapped += 1
    source.re_rigify_generated_rig = rig
    return mapped, unmatched


def upgrade_drive_constraints() -> int:
    """Migrate existing bridges to orientation-aware local target space."""
    upgraded = 0
    for obj in getattr(bpy.data, "objects", ()):
        if obj.type != "ARMATURE" or not obj.pose:
            continue
        for pose_bone in obj.pose.bones:
            for constraint in pose_bone.constraints:
                if not constraint.name.startswith(CONSTRAINT_PREFIX):
                    continue
                if constraint.type == "COPY_TRANSFORMS":
                    constraint.owner_space = "LOCAL"
                    constraint.target_space = "LOCAL_OWNER_ORIENT"
                    constraint.mix_mode = "REPLACE"
                    upgraded += 1
                elif constraint.type == "COPY_ROTATION":
                    constraint.owner_space = "POSE"
                    constraint.target_space = "POSE"
                    constraint.mix_mode = "REPLACE"
                    upgraded += 1
    return upgraded


def _upgrade_timer():
    if not _upgrade_enabled:
        return None
    if not hasattr(bpy.data, "objects"):
        return 0.1
    upgrade_drive_constraints()
    return None


def register() -> None:
    global _upgrade_enabled
    _upgrade_enabled = True
    if not bpy.app.timers.is_registered(_upgrade_timer):
        bpy.app.timers.register(_upgrade_timer, first_interval=0.0)


def unregister() -> None:
    global _upgrade_enabled
    _upgrade_enabled = False
    if bpy.app.timers.is_registered(_upgrade_timer):
        bpy.app.timers.unregister(_upgrade_timer)
