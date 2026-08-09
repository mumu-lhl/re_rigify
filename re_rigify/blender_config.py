"""Blender RNA storage and JSON conversion."""

from __future__ import annotations

import json
from contextlib import contextmanager

import bpy
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatVectorProperty, IntProperty,
    PointerProperty, StringProperty,
)

from .core import (
    EXPLICIT_CHAIN_MIN_LENGTHS,
    FORMAT_NAME,
    SCHEMA_VERSION,
    normalize_compatibility,
    normalize_config,
    rename_collection_references,
)


_carrier_updates_suspended = 0
_collection_rename_updates_suspended = 0
FORCE_CONNECT_RIG_TYPES = frozenset((
    "limbs.simple_tentacle",
    "limbs.super_finger",
    "spines.basic_tail",
))


@contextmanager
def suspend_carrier_updates():
    global _carrier_updates_suspended
    _carrier_updates_suspended += 1
    try:
        yield
    finally:
        _carrier_updates_suspended -= 1


@contextmanager
def suspend_collection_rename_updates():
    global _collection_rename_updates_suspended
    _collection_rename_updates_suspended += 1
    try:
        yield
    finally:
        _collection_rename_updates_suspended -= 1


def _rename_collection(item, _context):
    if _collection_rename_updates_suspended:
        return
    settings = item.id_data.re_rigify
    old_name = item.last_valid_name
    new_name = item.name
    if (
        not old_name
        or not new_name
        or old_name == new_name
        or any(
            other != item and other.name == new_name
            for other in settings.collections
        )
    ):
        return
    from .ui import flush_parameter_carrier, remove_parameter_carrier
    flush_parameter_carrier()
    remove_parameter_carrier()
    for bone in settings.bones:
        parameters = json.loads(bone.parameters_json or "{}")
        bone.parameters_json = json.dumps(
            rename_collection_references(parameters, old_name, new_name),
            ensure_ascii=False,
            sort_keys=True,
        )
    for rule in settings.bone_rules:
        parameters = json.loads(rule.parameters_json or "{}")
        rule.parameters_json = json.dumps(
            rename_collection_references(parameters, old_name, new_name),
            ensure_ascii=False,
            sort_keys=True,
        )
    item.last_valid_name = new_name


def _refresh_parameter_carrier(item, context):
    if _carrier_updates_suspended:
        return
    obj = getattr(context, "object", None)
    if not obj or obj.type != "ARMATURE" or obj.data != item.id_data:
        return
    settings = obj.data.re_rigify
    if item.rigify_type not in EXPLICIT_CHAIN_MIN_LENGTHS:
        item.chain_bones.clear()
        item.active_chain_index = 0
    if item.rigify_type not in FORCE_CONNECT_RIG_TYPES:
        item.force_connect_chain = False
    index = next((index for index, candidate in enumerate(settings.bones) if candidate == item), -1)
    if index >= 0 and item.bone_name and item.bone_name in obj.data.bones:
        from .ui import prepare_parameter_carrier
        prepare_parameter_carrier(context, obj, item, index)


def _refresh_active_bone(settings, context):
    if _carrier_updates_suspended:
        return
    obj = getattr(context, "object", None)
    if not obj or obj.type != "ARMATURE" or obj.data != settings.id_data or not settings.bones:
        return
    index = min(settings.active_bone_index, len(settings.bones) - 1)
    item = settings.bones[index]
    if item.bone_name and item.bone_name in obj.data.bones:
        from .ui import prepare_parameter_carrier
        prepare_parameter_carrier(context, obj, item, index)


class RERIGIFY_PG_ChainBone(bpy.types.PropertyGroup):
    bone_name: StringProperty(name="Bone")


class RERIGIFY_PG_BoneConfig(bpy.types.PropertyGroup):
    collection_selected: BoolProperty(name="Select for Collection", default=False)
    managed_rule_id: StringProperty(default="", options={"HIDDEN"})
    bone_name: StringProperty(name="Bone", update=_refresh_parameter_carrier)
    rigify_type: StringProperty(name="Rigify Type", update=_refresh_parameter_carrier)
    parameters_json: StringProperty(name="Parameters", default="{}")
    force_connect_chain: BoolProperty(name="Force Connected Chain", default=False)
    skin_eye_compatibility: BoolProperty(name="Build Skin Eye Topology", default=False)
    roll_bones_enabled: BoolProperty(name="Drive Roll Bones", default=False)
    upper_arm_roll_bone: StringProperty(name="Upper Arm Roll")
    forearm_roll_bone: StringProperty(name="Forearm Roll")
    eye_forward_axis: EnumProperty(
        name="Eye Forward",
        items=(
            ("AUTO", "Automatic", "Infer the horizontal viewing direction from eyelid bones"),
            ("+X", "+X", "Point the temporary eye bone along positive X"),
            ("-X", "-X", "Point the temporary eye bone along negative X"),
            ("+Y", "+Y", "Point the temporary eye bone along positive Y"),
            ("-Y", "-Y", "Point the temporary eye bone along negative Y"),
        ),
        default="AUTO",
    )
    upper_lid_pattern: StringProperty(name="Upper Eyelids")
    lower_lid_pattern: StringProperty(name="Lower Eyelids")
    synthetic_lids_fallback: BoolProperty(name="Synthetic Eyelid Fallback", default=False)
    chain_bones: CollectionProperty(type=RERIGIFY_PG_ChainBone)
    active_chain_index: IntProperty(default=0)


def chain_bones_from_item(item) -> list[str]:
    return [entry.bone_name for entry in item.chain_bones]


def apply_chain_bones_to_item(item, bone_names) -> None:
    item.chain_bones.clear()
    for bone_name in bone_names:
        entry = item.chain_bones.add()
        entry.bone_name = bone_name
    item.active_chain_index = min(
        item.active_chain_index,
        max(0, len(item.chain_bones) - 1),
    )


class RERIGIFY_PG_CollectionRule(bpy.types.PropertyGroup):
    kind: EnumProperty(
        name="Match",
        items=(("EXACT", "Exact", "Match one complete bone name"),
               ("GLOB", "Glob", "Case-sensitive *, ? and [] pattern")),
        default="EXACT",
    )
    pattern: StringProperty(name="Bone Pattern")


class RERIGIFY_PG_BoneRule(bpy.types.PropertyGroup):
    rule_id: StringProperty(name="Rule ID")
    kind: EnumProperty(
        name="Match",
        items=(
            ("EXACT", "Exact", "Match one complete bone name"),
            ("GLOB", "Glob", "Case-sensitive *, ? and [] pattern"),
        ),
        default="GLOB",
    )
    pattern: StringProperty(name="Bone Pattern")
    rigify_type: StringProperty(name="Rigify Type")
    apply_as_chain: BoolProperty(
        name="Apply as Chain and Force Connect",
        default=False,
    )
    parameters_json: StringProperty(name="Parameters", default="{}")


class RERIGIFY_PG_CollectionConfig(bpy.types.PropertyGroup):
    name: StringProperty(name="Collection", update=_rename_collection)
    last_valid_name: StringProperty(default="", options={"HIDDEN"})
    ui_title: StringProperty(name="Button Title")
    ui_row: IntProperty(name="UI Row", min=0, default=0)
    row_order: IntProperty(name="Order", min=0, default=0)
    color_set_name: StringProperty(name="Color Set")
    visible_after_generation: BoolProperty(
        name="Visible After Generation", default=True,
    )
    rules: CollectionProperty(type=RERIGIFY_PG_CollectionRule)
    active_rule_index: IntProperty(default=0)


class RERIGIFY_PG_ColorSet(bpy.types.PropertyGroup):
    name: StringProperty(name="Color Set")
    active: FloatVectorProperty(name="Active", subtype="COLOR", size=3, min=0.0, max=1.0)
    normal: FloatVectorProperty(name="Normal", subtype="COLOR", size=3, min=0.0, max=1.0)
    select: FloatVectorProperty(name="Select", subtype="COLOR", size=3, min=0.0, max=1.0)
    standard_colors_lock: BoolProperty(name="Standard Colors Lock", default=False)


class RERIGIFY_PG_ArmatureConfig(bpy.types.PropertyGroup):
    bones: CollectionProperty(type=RERIGIFY_PG_BoneConfig)
    active_bone_index: IntProperty(default=0, update=_refresh_active_bone)
    bone_rules: CollectionProperty(type=RERIGIFY_PG_BoneRule)
    active_bone_rule_index: IntProperty(default=0)
    active_bone_rule_preview_index: IntProperty(default=0)
    collections: CollectionProperty(type=RERIGIFY_PG_CollectionConfig)
    active_collection_index: IntProperty(default=0)
    color_sets: CollectionProperty(type=RERIGIFY_PG_ColorSet)
    active_color_index: IntProperty(default=0)
    root_color_set_name: StringProperty(name="Root Control Color Set", default="")
    validation_message: StringProperty(default="")


CLASSES = (
    RERIGIFY_PG_ChainBone,
    RERIGIFY_PG_BoneConfig,
    RERIGIFY_PG_BoneRule,
    RERIGIFY_PG_CollectionRule,
    RERIGIFY_PG_CollectionConfig,
    RERIGIFY_PG_ColorSet,
    RERIGIFY_PG_ArmatureConfig,
)


def _compatibility_from_item(item) -> dict:
    return normalize_compatibility({
        "force_connect_chain": item.force_connect_chain,
        "skin_eye_compatibility": item.skin_eye_compatibility,
        "roll_bones_enabled": item.roll_bones_enabled,
        "upper_arm_roll_bone": item.upper_arm_roll_bone,
        "forearm_roll_bone": item.forearm_roll_bone,
        "eye_forward_axis": item.eye_forward_axis,
        "upper_lid_pattern": item.upper_lid_pattern,
        "lower_lid_pattern": item.lower_lid_pattern,
        "synthetic_lids_fallback": item.synthetic_lids_fallback,
    })


def _apply_compatibility_to_item(item, source: dict) -> None:
    source = normalize_compatibility(source)
    for name, value in source.items():
        setattr(item, name, value)


def _serialize_bone(item) -> dict:
    return {
        "bone_name": item.bone_name,
        "rigify_type": item.rigify_type,
        "chain_bones": chain_bones_from_item(item),
        "parameters": json.loads(item.parameters_json or "{}"),
        "compatibility": _compatibility_from_item(item),
    }


def armature_to_payload(
    armature: bpy.types.Armature,
    include_managed: bool = True,
) -> dict:
    settings = armature.re_rigify
    bones = [
        item for item in settings.bones
        if include_managed or not item.managed_rule_id
    ]
    return {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "bones": [_serialize_bone(item) for item in bones],
        "bone_rules": [{
            "rule_id": rule.rule_id,
            "kind": rule.kind,
            "pattern": rule.pattern,
            "rigify_type": rule.rigify_type,
            "apply_as_chain": rule.apply_as_chain,
            "parameters": json.loads(rule.parameters_json or "{}"),
        } for rule in settings.bone_rules],
        "collections": [{
            "name": item.name,
            "ui_title": item.ui_title,
            "ui_row": item.ui_row,
            "row_order": item.row_order,
            "color_set": item.color_set_name,
            "visible_after_generation": item.visible_after_generation,
            "rules": [{"kind": rule.kind, "pattern": rule.pattern} for rule in item.rules],
        } for item in settings.collections],
        "color_sets": [{
            "name": item.name,
            "active": list(item.active),
            "normal": list(item.normal),
            "select": list(item.select),
            "standard_colors_lock": item.standard_colors_lock,
        } for item in settings.color_sets],
        **({"root_color_set": settings.root_color_set_name}
           if settings.root_color_set_name else {}),
    }


def payload_to_armature(armature: bpy.types.Armature, payload: dict) -> None:
    """Replace stored configuration only after the whole payload is normalized."""
    payload = normalize_config(payload)
    from .ui import flush_parameter_carrier, remove_parameter_carrier
    flush_parameter_carrier()
    remove_parameter_carrier()
    settings = armature.re_rigify
    with suspend_carrier_updates(), suspend_collection_rename_updates():
        settings.bones.clear()
        settings.bone_rules.clear()
        settings.collections.clear()
        settings.color_sets.clear()
        settings.root_color_set_name = payload.get("root_color_set", "")
        for source in payload["bones"]:
            item = settings.bones.add()
            item.bone_name = source["bone_name"]
            item.rigify_type = source["rigify_type"]
            apply_chain_bones_to_item(item, source["chain_bones"])
            item.parameters_json = json.dumps(
                source["parameters"], ensure_ascii=False, sort_keys=True,
            )
            _apply_compatibility_to_item(item, source["compatibility"])
        for source in payload["bone_rules"]:
            rule = settings.bone_rules.add()
            rule.rule_id = source["rule_id"]
            rule.kind = source["kind"]
            rule.pattern = source["pattern"]
            rule.rigify_type = source["rigify_type"]
            rule.apply_as_chain = source["apply_as_chain"]
            rule.parameters_json = json.dumps(
                source["parameters"], ensure_ascii=False, sort_keys=True,
            )
        for source in payload["collections"]:
            item = settings.collections.add()
            item.name = source["name"]
            item.last_valid_name = source["name"]
            item.ui_title = source["ui_title"]
            item.ui_row = source["ui_row"]
            item.row_order = source["row_order"]
            item.color_set_name = source["color_set"]
            item.visible_after_generation = source["visible_after_generation"]
            for source_rule in source["rules"]:
                rule = item.rules.add()
                rule.kind = source_rule["kind"]
                rule.pattern = source_rule["pattern"]
        for source in payload["color_sets"]:
            item = settings.color_sets.add()
            item.name = source["name"]
            item.active = source["active"]
            item.normal = source["normal"]
            item.select = source["select"]
            item.standard_colors_lock = source["standard_colors_lock"]
        settings.active_bone_index = min(
            settings.active_bone_index, max(0, len(settings.bones) - 1),
        )
        settings.active_collection_index = min(
            settings.active_collection_index,
            max(0, len(settings.collections) - 1),
        )
        settings.active_color_index = min(
            settings.active_color_index, max(0, len(settings.color_sets) - 1),
        )
        settings.active_bone_rule_index = min(
            settings.active_bone_rule_index,
            max(0, len(settings.bone_rules) - 1),
        )
    from .rules import sync_bone_rules
    sync_bone_rules(armature)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Armature.re_rigify = bpy.props.PointerProperty(type=RERIGIFY_PG_ArmatureConfig)
    bpy.types.Object.re_rigify_generated_rig = PointerProperty(
        name="Generated Rigify Rig",
        type=bpy.types.Object,
    )
    bpy.types.Object.re_rigify_metarig = PointerProperty(
        name="Re-Rigify Metarig",
        type=bpy.types.Object,
    )
    bpy.types.Object.re_rigify_source_armature = PointerProperty(
        name="Re-Rigify Source Armature",
        type=bpy.types.Object,
    )


def unregister() -> None:
    del bpy.types.Object.re_rigify_source_armature
    del bpy.types.Object.re_rigify_metarig
    del bpy.types.Object.re_rigify_generated_rig
    del bpy.types.Armature.re_rigify
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
