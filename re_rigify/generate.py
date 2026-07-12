"""Apply a stored configuration to a copy and invoke Rigify."""

from __future__ import annotations

import json

import bpy

from .core import ConfigError, resolve_collection_rules
from .rigify_adapter import apply_parameters


def apply_bone_config(obj: bpy.types.Object, bones: list[dict]) -> None:
    for item in bones:
        pose_bone = obj.pose.bones.get(item["bone_name"])
        if pose_bone is None:
            raise ConfigError(f"bone does not exist: {item['bone_name']!r}")
        pose_bone.rigify_type = item["rigify_type"]
        errors = apply_parameters(pose_bone.rigify_parameters, item.get("parameters", {}))
        if errors:
            raise ConfigError("; ".join(errors))


def validate_bone_parameters(context, source: bpy.types.Object, bones: list[dict]) -> tuple[str, ...]:
    """Validate against the active Rigify RNA without touching the source armature."""
    duplicate = source.copy()
    duplicate.data = source.data.copy()
    duplicate.name = "__ReRigify_Validation__"
    context.scene.collection.objects.link(duplicate)
    context.view_layer.update()
    try:
        apply_bone_config(duplicate, bones)
    except ConfigError as exc:
        return (str(exc),)
    finally:
        data = duplicate.data
        bpy.data.objects.remove(duplicate, do_unlink=True)
        if data.users == 0:
            bpy.data.armatures.remove(data)
    return ()


def apply_collection_config(obj: bpy.types.Object, collections: list[dict]) -> None:
    armature = obj.data
    resolved = resolve_collection_rules((bone.name for bone in armature.bones), collections)
    ordered = sorted(collections, key=lambda item: (item["ui_row"], item["row_order"], item["name"]))
    for source in ordered:
        collection = armature.collections_all.get(source["name"])
        if collection is None:
            collection = armature.collections.new(source["name"])
        collection.rigify_ui_row = source["ui_row"]
        collection.rigify_ui_title = source.get("ui_title", "")
        for name in resolved[source["name"]]:
            collection.assign(armature.bones[name])

    # Rigify derives left-to-right button order from collection traversal order.
    roots = armature.collections
    for target_index, source in enumerate(ordered):
        collection = armature.collections_all[source["name"]
        ]
        current_index = list(roots).index(collection)
        if current_index != target_index:
            roots.move(current_index, target_index)


def duplicate_as_metarig(source: bpy.types.Object) -> bpy.types.Object:
    duplicate = source.copy()
    duplicate.data = source.data.copy()
    duplicate.name = f"{source.name}_metarig"
    for collection in source.users_collection:
        collection.objects.link(duplicate)
    return duplicate


def generate_rig(context: bpy.types.Context, source: bpy.types.Object, payload: dict) -> bpy.types.Object:
    previous_active = context.view_layer.objects.active
    previous_selected = list(context.selected_objects)
    previous_mode = source.mode
    duplicate = None
    before = set(bpy.data.objects)
    try:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        duplicate = duplicate_as_metarig(source)
        apply_bone_config(duplicate, payload["bones"])
        apply_collection_config(duplicate, payload["collections"])
        bpy.ops.object.select_all(action="DESELECT")
        duplicate.select_set(True)
        context.view_layer.objects.active = duplicate
        bpy.ops.object.mode_set(mode="POSE")
        result = bpy.ops.pose.rigify_generate()
        if "FINISHED" not in result:
            raise RuntimeError(f"Rigify generation returned {result}")
        created = [obj for obj in bpy.data.objects if obj not in before and obj != duplicate]
        rigs = [obj for obj in created if obj.type == "ARMATURE"]
        result_obj = context.view_layer.objects.active
        if result_obj == duplicate and rigs:
            result_obj = rigs[-1]
        return result_obj
    except Exception:
        for obj in list(bpy.data.objects):
            if obj not in before:
                bpy.data.objects.remove(obj, do_unlink=True)
        raise
    finally:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in previous_selected:
            if obj.name in bpy.data.objects:
                obj.select_set(True)
        if previous_active and previous_active.name in bpy.data.objects:
            context.view_layer.objects.active = previous_active
            if previous_mode != "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode=previous_mode)
                except RuntimeError:
                    pass
