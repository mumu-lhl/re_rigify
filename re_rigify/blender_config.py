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
    FORMAT_NAME,
    SCHEMA_VERSION,
    normalize_compatibility,
    normalize_config,
)


_carrier_updates_suspended = 0


@contextmanager
def suspend_carrier_updates():
    global _carrier_updates_suspended
    _carrier_updates_suspended += 1
    try:
        yield
    finally:
        _carrier_updates_suspended -= 1


def _refresh_parameter_carrier(item, context):
    if _carrier_updates_suspended:
        return
    obj = getattr(context, "object", None)
    if not obj or obj.type != "ARMATURE" or obj.data != item.id_data:
        return
    settings = obj.data.re_rigify
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


class RERIGIFY_PG_BoneConfig(bpy.types.PropertyGroup):
    collection_selected: BoolProperty(name="Select for Collection", default=False)
    bone_name: StringProperty(name="Bone", update=_refresh_parameter_carrier)
    rigify_type: StringProperty(name="Rigify Type", update=_refresh_parameter_carrier)
    parameters_json: StringProperty(name="Parameters", default="{}")
    force_connect_chain: BoolProperty(name="Force Connected Chain", default=False)
    skin_eye_compatibility: BoolProperty(name="Build Skin Eye Topology", default=False)
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


class RERIGIFY_PG_CollectionRule(bpy.types.PropertyGroup):
    kind: EnumProperty(
        name="Match",
        items=(("EXACT", "Exact", "Match one complete bone name"),
               ("GLOB", "Glob", "Case-sensitive *, ? and [] pattern")),
        default="EXACT",
    )
    pattern: StringProperty(name="Bone Pattern")


class RERIGIFY_PG_CollectionConfig(bpy.types.PropertyGroup):
    name: StringProperty(name="Collection")
    ui_title: StringProperty(name="Button Title")
    ui_row: IntProperty(name="UI Row", min=0, default=0)
    row_order: IntProperty(name="Order", min=0, default=0)
    color_set_name: StringProperty(name="Color Set")
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
    collections: CollectionProperty(type=RERIGIFY_PG_CollectionConfig)
    active_collection_index: IntProperty(default=0)
    color_sets: CollectionProperty(type=RERIGIFY_PG_ColorSet)
    active_color_index: IntProperty(default=0)
    validation_message: StringProperty(default="")


CLASSES = (
    RERIGIFY_PG_BoneConfig,
    RERIGIFY_PG_CollectionRule,
    RERIGIFY_PG_CollectionConfig,
    RERIGIFY_PG_ColorSet,
    RERIGIFY_PG_ArmatureConfig,
)


def _compatibility_from_item(item) -> dict:
    return normalize_compatibility({
        "force_connect_chain": item.force_connect_chain,
        "skin_eye_compatibility": item.skin_eye_compatibility,
        "eye_forward_axis": item.eye_forward_axis,
        "upper_lid_pattern": item.upper_lid_pattern,
        "lower_lid_pattern": item.lower_lid_pattern,
        "synthetic_lids_fallback": item.synthetic_lids_fallback,
    })


def _apply_compatibility_to_item(item, source: dict) -> None:
    source = normalize_compatibility(source)
    for name, value in source.items():
        setattr(item, name, value)


def armature_to_payload(armature: bpy.types.Armature) -> dict:
    settings = armature.re_rigify
    return {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "bones": [{
            "bone_name": item.bone_name,
            "rigify_type": item.rigify_type,
            "parameters": json.loads(item.parameters_json or "{}"),
            "compatibility": _compatibility_from_item(item),
        } for item in settings.bones],
        "collections": [{
            "name": item.name,
            "ui_title": item.ui_title,
            "ui_row": item.ui_row,
            "row_order": item.row_order,
            "color_set": item.color_set_name,
            "rules": [{"kind": rule.kind, "pattern": rule.pattern} for rule in item.rules],
        } for item in settings.collections],
        "color_sets": [{
            "name": item.name,
            "active": list(item.active),
            "normal": list(item.normal),
            "select": list(item.select),
            "standard_colors_lock": item.standard_colors_lock,
        } for item in settings.color_sets],
    }


def payload_to_armature(armature: bpy.types.Armature, payload: dict) -> None:
    """Replace stored configuration only after the whole payload is normalized."""
    payload = normalize_config(payload)
    settings = armature.re_rigify
    settings.bones.clear()
    settings.collections.clear()
    settings.color_sets.clear()
    for source in payload["bones"]:
        item = settings.bones.add()
        item.bone_name = source["bone_name"]
        item.rigify_type = source["rigify_type"]
        item.parameters_json = json.dumps(source["parameters"], ensure_ascii=False, sort_keys=True)
        _apply_compatibility_to_item(item, source["compatibility"])
    for source in payload["collections"]:
        item = settings.collections.add()
        item.name = source["name"]
        item.ui_title = source["ui_title"]
        item.ui_row = source["ui_row"]
        item.row_order = source["row_order"]
        item.color_set_name = source["color_set"]
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
    settings.active_bone_index = min(settings.active_bone_index, max(0, len(settings.bones) - 1))
    settings.active_collection_index = min(
        settings.active_collection_index, max(0, len(settings.collections) - 1)
    )
    settings.active_color_index = min(settings.active_color_index, max(0, len(settings.color_sets) - 1))


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
