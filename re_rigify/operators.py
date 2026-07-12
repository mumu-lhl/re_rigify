"""UI operators for configuration editing, files, validation and generation."""

from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .blender_config import armature_to_payload, payload_to_armature
from .core import (
    ConfigError,
    mirror_parameter_value,
    normalize_config,
    validate_config,
)
from .generate import generate_rig, validate_bone_parameters
from .drive import connect_source_to_rig, remove_drive_constraints
from .rigify_adapter import available_rig_types, is_rigify_enabled


def active_armature(context):
    obj = context.object
    return obj if obj and obj.type == "ARMATURE" else None


def select_only(context, obj):
    """Select one object without invoking context-sensitive selection operators."""
    for candidate in context.view_layer.objects:
        candidate.select_set(False)
    obj.hide_set(False)
    obj.hide_select = False
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _add_selected_bones_to_active_collection(settings):
    marked = [item for item in settings.bones if item.collection_selected]
    if not marked and settings.bones:
        marked = [settings.bones[settings.active_bone_index]]
    if not marked:
        return 0
    collection = settings.collections[settings.active_collection_index]
    existing = {rule.pattern for rule in collection.rules if rule.kind == "EXACT"}
    added = 0
    for item in marked:
        if item.bone_name not in existing:
            rule = collection.rules.add()
            rule.kind = "EXACT"
            rule.pattern = item.bone_name
            existing.add(item.bone_name)
            added += 1
    collection.active_rule_index = max(0, len(collection.rules) - 1)
    return added


def validate_active(context):
    from .ui import flush_parameter_carrier
    flush_parameter_carrier()
    obj = active_armature(context)
    if not obj:
        return None, ("Select an armature object",)
    if not is_rigify_enabled():
        return obj, ("Rigify is not enabled",)
    try:
        payload = armature_to_payload(obj.data)
    except (ValueError, json.JSONDecodeError) as exc:
        return obj, (f"Invalid stored parameter JSON: {exc}",)
    result = validate_config(payload, obj.data.bones.keys(), available_rig_types())
    errors = list(result.errors)
    if not errors:
        errors.extend(validate_bone_parameters(context, obj, payload["bones"]))
    return obj, tuple(errors)


class RERIGIFY_OT_BoneAdd(bpy.types.Operator):
    bl_idname = "re_rigify.bone_add"
    bl_label = "Add Selected Bone"
    bl_options = {"UNDO"}

    def execute(self, context):
        obj = active_armature(context)
        bone = obj.data.bones.active if obj else None
        if not bone:
            self.report({"ERROR"}, "Select an armature bone")
            return {"CANCELLED"}
        settings = obj.data.re_rigify
        if any(item.bone_name == bone.name for item in settings.bones):
            self.report({"ERROR"}, "The active bone is already configured")
            return {"CANCELLED"}
        item = settings.bones.add()
        item.bone_name = bone.name
        types = available_rig_types()
        item.rigify_type = "basic.raw_copy" if "basic.raw_copy" in types else (types[0] if types else "")
        settings.active_bone_index = len(settings.bones) - 1
        return {"FINISHED"}


class RERIGIFY_OT_BoneRemove(bpy.types.Operator):
    bl_idname = "re_rigify.bone_remove"
    bl_label = "Remove Bone Configuration"
    bl_options = {"UNDO"}

    def execute(self, context):
        from .ui import flush_parameter_carrier, remove_parameter_carrier
        flush_parameter_carrier()
        remove_parameter_carrier()
        settings = active_armature(context).data.re_rigify
        if settings.bones:
            settings.bones.remove(settings.active_bone_index)
            settings.active_bone_index = min(settings.active_bone_index, len(settings.bones) - 1)
        return {"FINISHED"}


class RERIGIFY_OT_MirrorBoneConfig(bpy.types.Operator):
    bl_idname = "re_rigify.mirror_bone_config"
    bl_label = "Mirror Configuration to Opposite Side"
    bl_description = "Copy the active Rigify type and mirrored parameters to the L/R counterpart"
    bl_options = {"UNDO"}

    def execute(self, context):
        from rigify.utils.naming import mirror_name
        from .ui import flush_parameter_carrier, prepare_parameter_carrier, remove_parameter_carrier

        obj = active_armature(context)
        settings = obj.data.re_rigify
        if not settings.bones:
            return {"CANCELLED"}
        source = settings.bones[settings.active_bone_index]
        flush_parameter_carrier()
        target_name = mirror_name(source.bone_name)
        if target_name == source.bone_name:
            self.report({"ERROR"}, f"{source.bone_name!r} has no L/R side suffix")
            return {"CANCELLED"}
        if target_name not in obj.data.bones:
            self.report({"ERROR"}, f"Mirrored bone {target_name!r} does not exist")
            return {"CANCELLED"}

        target_index = next(
            (index for index, item in enumerate(settings.bones) if item.bone_name == target_name),
            -1,
        )
        target = settings.bones[target_index] if target_index >= 0 else settings.bones.add()
        if target_index < 0:
            target_index = len(settings.bones) - 1
        target.bone_name = target_name
        target.rigify_type = source.rigify_type
        target.parameters_json = json.dumps(
            mirror_parameter_value(json.loads(source.parameters_json or "{}"), mirror_name),
            ensure_ascii=False,
            sort_keys=True,
        )
        remove_parameter_carrier()
        settings.active_bone_index = target_index
        prepare_parameter_carrier(context, obj, target, target_index)
        self.report({"INFO"}, f"Mirrored configuration to {target_name}")
        return {"FINISHED"}


class RERIGIFY_OT_CollectionAdd(bpy.types.Operator):
    bl_idname = "re_rigify.collection_add"
    bl_label = "Add Collection Configuration"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        item = settings.collections.add()
        item.name = f"Collection {len(settings.collections)}"
        item.ui_row = 1
        item.row_order = sum(1 for collection in list(settings.collections)[:-1] if collection.ui_row == 1)
        settings.active_collection_index = len(settings.collections) - 1
        return {"FINISHED"}


class RERIGIFY_OT_CollectionRemove(bpy.types.Operator):
    bl_idname = "re_rigify.collection_remove"
    bl_label = "Remove Collection Configuration"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if settings.collections:
            settings.collections.remove(settings.active_collection_index)
            settings.active_collection_index = min(settings.active_collection_index, len(settings.collections) - 1)
        return {"FINISHED"}


class RERIGIFY_OT_MarkAllBones(bpy.types.Operator):
    bl_idname = "re_rigify.mark_all_bones"
    bl_label = "Select All Configured Bones"

    selected: BoolProperty(default=True)

    def execute(self, context):
        for item in active_armature(context).data.re_rigify.bones:
            item.collection_selected = self.selected
        return {"FINISHED"}


class RERIGIFY_OT_CollectionAddMarkedBones(bpy.types.Operator):
    bl_idname = "re_rigify.collection_add_marked_bones"
    bl_label = "Add Selected Bones to Active Collection"
    bl_description = "Add checked bones, or the active list bone if none are checked"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if not settings.collections:
            self.report({"ERROR"}, "Create a bone collection configuration first")
            return {"CANCELLED"}
        if not settings.bones:
            self.report({"ERROR"}, "No configured bones to add")
            return {"CANCELLED"}
        collection = settings.collections[settings.active_collection_index]
        added = _add_selected_bones_to_active_collection(settings)
        for item in settings.bones:
            item.collection_selected = False
        self.report({"INFO"}, f"Added {added} bone(s) to {collection.name}")
        return {"FINISHED"}


class RERIGIFY_OT_RuleAdd(bpy.types.Operator):
    bl_idname = "re_rigify.rule_add"
    bl_label = "Add Bone Matching Rule"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if not settings.collections:
            return {"CANCELLED"}
        _add_selected_bones_to_active_collection(settings)
        return {"FINISHED"}


class RERIGIFY_OT_RuleRemove(bpy.types.Operator):
    bl_idname = "re_rigify.rule_remove"
    bl_label = "Remove Bone Matching Rule"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if settings.collections:
            collection = settings.collections[settings.active_collection_index]
            if collection.rules:
                collection.rules.remove(collection.active_rule_index)
                collection.active_rule_index = min(collection.active_rule_index, len(collection.rules) - 1)
        return {"FINISHED"}


class RERIGIFY_OT_Validate(bpy.types.Operator):
    bl_idname = "re_rigify.validate"
    bl_label = "Validate Configuration"

    def execute(self, context):
        obj, errors = validate_active(context)
        if errors:
            if obj:
                obj.data.re_rigify.validation_message = "\n".join(errors)
            self.report({"ERROR"}, f"Validation failed with {len(errors)} error(s)")
            return {"CANCELLED"}
        obj.data.re_rigify.validation_message = "Configuration is valid"
        self.report({"INFO"}, "Configuration is valid")
        return {"FINISHED"}


class RERIGIFY_OT_Export(bpy.types.Operator, ExportHelper):
    bl_idname = "re_rigify.export_config"
    bl_label = "Export Re-Rigify Configuration"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        obj, errors = validate_active(context)
        if errors:
            self.report({"ERROR"}, "Fix validation errors before exporting")
            return {"CANCELLED"}
        Path(self.filepath).write_text(
            json.dumps(armature_to_payload(obj.data), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"FINISHED"}


class RERIGIFY_OT_Import(bpy.types.Operator, ImportHelper):
    bl_idname = "re_rigify.import_config"
    bl_label = "Import Re-Rigify Configuration"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        obj = active_armature(context)
        from .ui import flush_parameter_carrier, remove_parameter_carrier
        flush_parameter_carrier()
        remove_parameter_carrier()
        try:
            payload = json.loads(Path(self.filepath).read_text(encoding="utf-8"))
            payload = normalize_config(payload)
        except (OSError, json.JSONDecodeError, ConfigError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        result = validate_config(payload, obj.data.bones.keys(), available_rig_types())
        errors = list(result.errors)
        if not errors:
            errors.extend(validate_bone_parameters(context, obj, payload["bones"]))
        if errors:
            obj.data.re_rigify.validation_message = "\n".join(errors)
            self.report({"ERROR"}, f"Import rejected with {len(errors)} error(s)")
            return {"CANCELLED"}
        payload_to_armature(obj.data, payload)
        return {"FINISHED"}


class RERIGIFY_OT_Generate(bpy.types.Operator):
    bl_idname = "re_rigify.generate"
    bl_label = "Generate Rigify Rig"
    bl_options = {"UNDO"}

    def execute(self, context):
        obj, errors = validate_active(context)
        if errors:
            obj.data.re_rigify.validation_message = "\n".join(errors)
            self.report({"ERROR"}, "Fix validation errors before generating")
            return {"CANCELLED"}
        try:
            generated = generate_rig(context, obj, armature_to_payload(obj.data))
            mapped, unmatched = connect_source_to_rig(obj, generated)
        except Exception as exc:
            self.report({"ERROR"}, f"Rigify generation failed: {exc}")
            return {"CANCELLED"}
        select_only(context, generated)
        self.report(
            {"INFO"},
            f"Generated rig drives {mapped} source bones; {len(unmatched)} unmatched",
        )
        return {"FINISHED"}


class RERIGIFY_OT_ConnectDrive(bpy.types.Operator):
    bl_idname = "re_rigify.connect_drive"
    bl_label = "Connect Generated Rig"
    bl_description = "Drive the original armature from DEF/ORG bones on the generated Rigify rig"
    bl_options = {"UNDO"}

    def execute(self, context):
        source = active_armature(context)
        rig = source.re_rigify_generated_rig
        if not rig:
            self.report({"ERROR"}, "Choose a generated Rigify rig")
            return {"CANCELLED"}
        try:
            mapped, unmatched = connect_source_to_rig(source, rig)
        except (TypeError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Connected {mapped} bones; {len(unmatched)} unmatched")
        return {"FINISHED"}


class RERIGIFY_OT_RemoveDrive(bpy.types.Operator):
    bl_idname = "re_rigify.remove_drive"
    bl_label = "Remove Rigify Drive"
    bl_description = "Remove only the Copy Transforms constraints created by Re-Rigify"
    bl_options = {"UNDO"}

    def execute(self, context):
        removed = remove_drive_constraints(active_armature(context))
        self.report({"INFO"}, f"Removed {removed} Re-Rigify constraints")
        return {"FINISHED"}


CLASSES = (
    RERIGIFY_OT_BoneAdd, RERIGIFY_OT_BoneRemove, RERIGIFY_OT_MirrorBoneConfig,
    RERIGIFY_OT_CollectionAdd, RERIGIFY_OT_CollectionRemove,
    RERIGIFY_OT_MarkAllBones, RERIGIFY_OT_CollectionAddMarkedBones,
    RERIGIFY_OT_RuleAdd, RERIGIFY_OT_RuleRemove,
    RERIGIFY_OT_Validate, RERIGIFY_OT_Export, RERIGIFY_OT_Import,
    RERIGIFY_OT_Generate, RERIGIFY_OT_ConnectDrive, RERIGIFY_OT_RemoveDrive,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
