"""Temporary metarig adaptations for production skeleton topology."""

from __future__ import annotations

from dataclasses import dataclass, field

from .core import ConfigError, unique_child_chain


CHAIN_MIN_LENGTHS = {
    "limbs.super_finger": 2,
}


@dataclass
class CompatibilityPlan:
    connections: list[tuple[str, str, bool]] = field(default_factory=list)
    eye_plans: list[object] = field(default_factory=list)
    source_to_helper: dict[str, str] = field(default_factory=dict)


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
    return plan


def apply_compatibility_plan(obj, plan: CompatibilityPlan) -> dict[str, str]:
    if not plan.connections:
        return dict(plan.source_to_helper)
    import bpy

    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit_bones = obj.data.edit_bones
        for parent_name, child_name, connected in plan.connections:
            child = edit_bones[child_name]
            child.parent = edit_bones[parent_name]
            child.use_connect = connected
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    return dict(plan.source_to_helper)
