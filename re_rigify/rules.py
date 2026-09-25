"""Resolve bone rules without persisting their derived bone rows."""

from __future__ import annotations

import json

from .blender_config import (
    suspend_carrier_updates,
)
from .core import (
    ConfigError,
    preview_bone_rule,
    resolve_bone_rules,
)


TOPOLOGY_EPSILON = 1e-6


def rule_dicts(settings) -> list[dict]:
    return [{
        "rule_id": rule.rule_id,
        "kind": rule.kind,
        "pattern": rule.pattern,
        "rigify_type": rule.rigify_type,
        "apply_as_chain": rule.apply_as_chain,
        "parameters": json.loads(rule.parameters_json or "{}"),
    } for rule in settings.bone_rules]


def armature_rule_topology(armature) -> tuple[
    dict[str, str | None],
    set[tuple[str, str]],
]:
    parents = {
        bone.name: bone.parent.name if bone.parent else None
        for bone in armature.bones
    }
    aligned_edges = {
        (bone.parent.name, bone.name)
        for bone in armature.bones
        if (
            bone.parent
            and (bone.head_local - bone.parent.tail_local).length
            <= TOPOLOGY_EPSILON
        )
    }
    return parents, aligned_edges


def active_bone_rule_preview(armature) -> dict:
    settings = armature.re_rigify
    if not settings.bone_rules:
        return {"bone_names": [], "chain_count": 0, "rows": []}
    index = min(
        settings.active_bone_rule_index,
        len(settings.bone_rules) - 1,
    )
    rules = rule_dicts(settings)
    parents, aligned_edges = armature_rule_topology(armature)
    return preview_bone_rule(
        armature.bones.keys(),
        rules,
        rules[index]["rule_id"],
        parents,
        aligned_edges,
    )


def cleanup_bone_rule_rows(armature) -> int:
    settings = armature.re_rigify
    rules = rule_dicts(settings)
    claimed_names = set()
    if rules:
        try:
            claimed_names = set(resolve_bone_rules(
                armature.bones.keys(), rules,
            ))
        except ConfigError:
            pass
    remove_indices = [
        index for index, item in enumerate(settings.bones)
        if item.bone_name in claimed_names
    ]
    with suspend_carrier_updates():
        for index in reversed(remove_indices):
            settings.bones.remove(index)
        settings.active_bone_index = min(
            settings.active_bone_index,
            max(0, len(settings.bones) - 1),
        )
    return len(remove_indices)
