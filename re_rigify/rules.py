"""Materialize persistent bone rules into configured bone rows."""

from __future__ import annotations

import json

from .blender_config import (
    _apply_compatibility_to_item,
    apply_chain_bones_to_item,
    suspend_carrier_updates,
)
from .core import DEFAULT_COMPATIBILITY, resolve_bone_rules


def rule_dicts(settings) -> list[dict]:
    return [{
        "rule_id": rule.rule_id,
        "kind": rule.kind,
        "pattern": rule.pattern,
        "rigify_type": rule.rigify_type,
        "parameters": json.loads(rule.parameters_json or "{}"),
    } for rule in settings.bone_rules]


def sync_bone_rules(armature) -> tuple[int, int, int]:
    settings = armature.re_rigify
    winners = (
        resolve_bone_rules(armature.bones.keys(), rule_dicts(settings))
        if settings.bone_rules else {}
    )
    active_name = (
        settings.bones[settings.active_bone_index].bone_name
        if settings.bones else None
    )
    remove_indices = [
        index for index, item in enumerate(settings.bones)
        if item.managed_rule_id and item.bone_name not in winners
    ]
    added = updated = 0
    with suspend_carrier_updates():
        for index in reversed(remove_indices):
            settings.bones.remove(index)
        for bone_name, rule in winners.items():
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
            apply_chain_bones_to_item(item, [])
            _apply_compatibility_to_item(item, DEFAULT_COMPATIBILITY)
        if active_name:
            settings.active_bone_index = next(
                (
                    index for index, item in enumerate(settings.bones)
                    if item.bone_name == active_name
                ),
                min(
                    settings.active_bone_index,
                    max(0, len(settings.bones) - 1),
                ),
            )
    return added, updated, len(remove_indices)
