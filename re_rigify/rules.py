"""Materialize persistent bone rules into configured bone rows."""

from __future__ import annotations

import json

from .blender_config import (
    _apply_compatibility_to_item,
    apply_chain_bones_to_item,
    suspend_carrier_updates,
)
from .core import (
    DEFAULT_COMPATIBILITY,
    resolve_bone_rule_rows,
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


def sync_bone_rules(armature) -> tuple[int, int, int]:
    settings = armature.re_rigify
    rules = rule_dicts(settings)
    parents, aligned_edges = armature_rule_topology(armature)
    winners = (
        resolve_bone_rules(armature.bones.keys(), rules)
        if rules else {}
    )
    rows = (
        resolve_bone_rule_rows(
            armature.bones.keys(), rules, parents, aligned_edges,
        )
        if rules else []
    )
    desired = {row["bone_name"]: row for row in rows}
    claimed_names = set(winners)
    active_name = (
        settings.bones[settings.active_bone_index].bone_name
        if settings.bones else None
    )
    active_root = next(
        (
            row["bone_name"] for row in rows
            if active_name in row["chain_bones"]
        ),
        active_name,
    )
    remove_indices = [
        index for index, item in enumerate(settings.bones)
        if (
            (item.managed_rule_id and item.bone_name not in desired)
            or (
                item.bone_name in claimed_names
                and item.bone_name not in desired
            )
        )
    ]
    added = updated = 0
    with suspend_carrier_updates():
        for index in reversed(remove_indices):
            settings.bones.remove(index)
        for row in rows:
            bone_name = row["bone_name"]
            rule = row["rule"]
            item = next(
                (
                    candidate for candidate in settings.bones
                    if candidate.bone_name == bone_name
                ),
                None,
            )
            if item is None:
                item = settings.bones.add()
                item.bone_name = bone_name
                added += 1
            else:
                updated += 1
            item.managed_rule_id = rule["rule_id"]
            item.rigify_type = rule["rigify_type"]
            item.parameters_json = json.dumps(
                rule["parameters"], ensure_ascii=False, sort_keys=True,
            )
            apply_chain_bones_to_item(item, row["chain_bones"])
            _apply_compatibility_to_item(item, DEFAULT_COMPATIBILITY)
        if active_root:
            settings.active_bone_index = next(
                (
                    index for index, item in enumerate(settings.bones)
                    if item.bone_name == active_root
                ),
                min(
                    settings.active_bone_index,
                    max(0, len(settings.bones) - 1),
                ),
            )
    return added, updated, len(remove_indices)
