"""Constraint bridge from a generated Rigify rig to the original deform armature."""

from __future__ import annotations

import bpy

from .core import choose_drive_target


CONSTRAINT_PREFIX = "Re-Rigify Drive"


def remove_drive_constraints(source: bpy.types.Object) -> int:
    removed = 0
    for pose_bone in source.pose.bones:
        for constraint in list(pose_bone.constraints):
            if constraint.name.startswith(CONSTRAINT_PREFIX):
                pose_bone.constraints.remove(constraint)
                removed += 1
    return removed


def connect_source_to_rig(source: bpy.types.Object, rig: bpy.types.Object) -> tuple[int, list[str]]:
    if source == rig or source.type != "ARMATURE" or rig.type != "ARMATURE":
        raise ValueError("Source and generated rig must be different armature objects")
    remove_drive_constraints(source)
    target_names = set(rig.pose.bones.keys())
    unmatched: list[str] = []
    mapped = 0
    for pose_bone in source.pose.bones:
        target_name = choose_drive_target(pose_bone.name, target_names)
        if target_name is None:
            unmatched.append(pose_bone.name)
            continue
        constraint = pose_bone.constraints.new("COPY_TRANSFORMS")
        constraint.name = f"{CONSTRAINT_PREFIX}: {target_name}"
        constraint.target = rig
        constraint.subtarget = target_name
        # Copy pose deltas relative to each rig's own rest bones. Absolute World/Pose
        # matrices deform the source immediately when metarig topology was adjusted.
        constraint.owner_space = "LOCAL"
        constraint.target_space = "LOCAL"
        constraint.mix_mode = "REPLACE"
        mapped += 1
    source.re_rigify_generated_rig = rig
    return mapped, unmatched
