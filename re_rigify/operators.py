"""UI operators for configuration editing, files, validation and generation."""

from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.props import IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .blender_config import armature_to_payload, payload_to_armature
from .core import ConfigError, normalize_config, validate_config
from .generate import generate_rig, validate_bone_parameters
from .rigify_adapter import available_rig_types, is_rigify_enabled


def active_armature(context):
    obj = context.object
    return obj if obj and obj.type == "ARMATURE" else None


def validate_active(context):
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
        settings = active_armature(context).data.re_rigify
        if settings.bones:
            settings.bones.remove(settings.active_bone_index)
            settings.active_bone_index = min(settings.active_bone_index, len(settings.bones) - 1)
        return {"FINISHED"}


class RERIGIFY_OT_CollectionAdd(bpy.types.Operator):
    bl_idname = "re_rigify.collection_add"
    bl_label = "Add Collection Configuration"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        item = settings.collections.add()
        item.name = f"Collection {len(settings.collections)}"
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


class RERIGIFY_OT_RuleAdd(bpy.types.Operator):
    bl_idname = "re_rigify.rule_add"
    bl_label = "Add Bone Matching Rule"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if not settings.collections:
            return {"CANCELLED"}
        collection = settings.collections[settings.active_collection_index]
        rule = collection.rules.add()
        obj = active_armature(context)
        rule.pattern = obj.data.bones.active.name if obj.data.bones.active else "*"
        collection.active_rule_index = len(collection.rules) - 1
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
        except Exception as exc:
            self.report({"ERROR"}, f"Rigify generation failed: {exc}")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        generated.select_set(True)
        context.view_layer.objects.active = generated
        return {"FINISHED"}


CLASSES = (
    RERIGIFY_OT_BoneAdd, RERIGIFY_OT_BoneRemove,
    RERIGIFY_OT_CollectionAdd, RERIGIFY_OT_CollectionRemove,
    RERIGIFY_OT_RuleAdd, RERIGIFY_OT_RuleRemove,
    RERIGIFY_OT_Validate, RERIGIFY_OT_Export, RERIGIFY_OT_Import, RERIGIFY_OT_Generate,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
