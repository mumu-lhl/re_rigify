"""UI operators for configuration editing, files, validation and generation."""

from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .blender_config import (
    _apply_compatibility_to_item,
    _compatibility_from_item,
    armature_to_payload,
    payload_to_armature,
    suspend_carrier_updates,
)
from .core import (
    ConfigError,
    RIGIFY_DEFAULT_COLOR_SETS,
    mirror_compatibility,
    mirror_parameter_value,
    normalize_config,
    remove_collection_references,
    unique_blender_name,
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


def _normalize_collection_orders(settings):
    rows = {}
    for index, collection in enumerate(settings.collections):
        rows.setdefault(collection.ui_row, []).append((collection.row_order, index, collection))
    for items in rows.values():
        for order, (_old_order, _index, collection) in enumerate(sorted(items)):
            collection.row_order = order


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
        errors.extend(validate_bone_parameters(context, obj, payload["bones"], payload["collections"]))
    return obj, tuple(errors)


class RERIGIFY_OT_BoneAdd(bpy.types.Operator):
    bl_idname = "re_rigify.bone_add"
    bl_label = "Add Selected Bones"
    bl_description = "Add all selected Pose/Edit Mode bones, or the active bone as a fallback"
    bl_options = {"UNDO"}

    def execute(self, context):
        from .ui import flush_parameter_carrier, prepare_parameter_carrier, remove_parameter_carrier

        obj = active_armature(context)
        if not obj:
            self.report({"ERROR"}, "Select an armature")
            return {"CANCELLED"}

        if obj.mode == "EDIT":
            ordered_bones = list(obj.data.edit_bones)
            selected_names = {bone.name for bone in ordered_bones if bone.select}
            active = obj.data.edit_bones.active
        elif obj.mode == "POSE":
            ordered_bones = list(obj.data.bones)
            selected_names = {
                bone.name for bone in (context.selected_pose_bones or ())
                if bone.id_data == obj
            }
            active = context.active_pose_bone
        else:
            ordered_bones = list(obj.data.bones)
            selected_names = set()
            active = obj.data.bones.active

        if not selected_names and active is not None:
            selected_names = {active.name}
        selected = [bone.name for bone in ordered_bones if bone.name in selected_names]
        if not selected:
            self.report({"ERROR"}, "Select one or more armature bones")
            return {"CANCELLED"}

        settings = obj.data.re_rigify
        existing_indices = {
            item.bone_name: index for index, item in enumerate(settings.bones)
        }
        types = available_rig_types()
        default_type = "basic.raw_copy" if "basic.raw_copy" in types else (types[0] if types else "")
        flush_parameter_carrier()
        remove_parameter_carrier()
        added_indices = []
        with suspend_carrier_updates():
            for bone_name in selected:
                if bone_name in existing_indices:
                    continue
                item = settings.bones.add()
                item.bone_name = bone_name
                item.rigify_type = default_type
                index = len(settings.bones) - 1
                existing_indices[bone_name] = index
                added_indices.append(index)

        active_name = active.name if active is not None and active.name in selected_names else selected[-1]
        settings.active_bone_index = existing_indices[active_name]
        active_item = settings.bones[settings.active_bone_index]
        prepare_parameter_carrier(context, obj, active_item, settings.active_bone_index)
        skipped = len(selected) - len(added_indices)
        self.report({"INFO"}, f"Added {len(added_indices)} bone(s); skipped {skipped} existing")
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
    bl_description = "Mirror checked configurations, or the active configuration if none are checked"
    bl_options = {"UNDO"}

    def execute(self, context):
        from rigify.utils.naming import mirror_name
        from .ui import flush_parameter_carrier, prepare_parameter_carrier, remove_parameter_carrier

        obj = active_armature(context)
        settings = obj.data.re_rigify
        if not settings.bones:
            return {"CANCELLED"}
        flush_parameter_carrier()
        selected = [item for item in settings.bones if item.collection_selected]
        if not selected:
            selected = [settings.bones[settings.active_bone_index]]
        snapshots = [
            (
                item.bone_name,
                item.rigify_type,
                item.parameters_json,
                _compatibility_from_item(item),
            )
            for item in selected
        ]
        source_names = {bone_name for bone_name, _rig_type, _parameters, _compat in snapshots}
        for bone_name, _rig_type, _parameters, _compat in snapshots:
            target_name = mirror_name(bone_name)
            if target_name == bone_name:
                self.report({"ERROR"}, f"{bone_name!r} has no L/R side suffix")
                return {"CANCELLED"}
            if target_name not in obj.data.bones:
                self.report({"ERROR"}, f"Mirrored bone {target_name!r} does not exist")
                return {"CANCELLED"}
            if target_name in source_names:
                self.report({"ERROR"}, "Do not select both sides of the same mirrored pair")
                return {"CANCELLED"}

        remove_parameter_carrier()
        last_target_index = settings.active_bone_index
        with suspend_carrier_updates():
            for bone_name, rig_type, parameters_json, compatibility in snapshots:
                target_name = mirror_name(bone_name)
                target_index = next(
                    (index for index, item in enumerate(settings.bones) if item.bone_name == target_name),
                    -1,
                )
                target = settings.bones[target_index] if target_index >= 0 else settings.bones.add()
                if target_index < 0:
                    target_index = len(settings.bones) - 1
                target.bone_name = target_name
                target.rigify_type = rig_type
                target.parameters_json = json.dumps(
                    mirror_parameter_value(json.loads(parameters_json or "{}"), mirror_name),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                _apply_compatibility_to_item(
                    target, mirror_compatibility(compatibility, mirror_name)
                )
                last_target_index = target_index
        for item in settings.bones:
            item.collection_selected = False
        settings.active_bone_index = last_target_index
        target = settings.bones[last_target_index]
        prepare_parameter_carrier(context, obj, target, last_target_index)
        self.report({"INFO"}, f"Mirrored {len(snapshots)} configuration(s)")
        return {"FINISHED"}


class RERIGIFY_OT_CopyParametersToSelected(bpy.types.Operator):
    bl_idname = "re_rigify.copy_parameters_to_selected"
    bl_label = "Copy Bone Settings to Checked"
    bl_description = "Copy the active bone's Rigify type and all parameters to checked bones"
    bl_options = {"UNDO"}

    def execute(self, context):
        from .ui import flush_parameter_carrier, prepare_parameter_carrier, remove_parameter_carrier

        obj = active_armature(context)
        settings = obj.data.re_rigify
        if not settings.bones:
            return {"CANCELLED"}
        flush_parameter_carrier()
        source_index = settings.active_bone_index
        source = settings.bones[source_index]
        targets = [
            item for index, item in enumerate(settings.bones)
            if index != source_index and item.collection_selected
        ]
        if not targets:
            self.report({"ERROR"}, "Check at least one target bone")
            return {"CANCELLED"}
        parameters_json = source.parameters_json
        compatibility = _compatibility_from_item(source)
        with suspend_carrier_updates():
            for target in targets:
                target.rigify_type = source.rigify_type
                target.parameters_json = parameters_json
                _apply_compatibility_to_item(target, compatibility)
        for item in settings.bones:
            item.collection_selected = False
        remove_parameter_carrier()
        prepare_parameter_carrier(context, obj, source, source_index)
        self.report({"INFO"}, f"Copied bone settings to {len(targets)} bone(s)")
        return {"FINISHED"}


class RERIGIFY_OT_CollectionAdd(bpy.types.Operator):
    bl_idname = "re_rigify.collection_add"
    bl_label = "Add Collection Configuration"
    bl_options = {"UNDO"}

    def execute(self, context):
        from .ui import flush_parameter_carrier, remove_parameter_carrier
        flush_parameter_carrier()
        remove_parameter_carrier()
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
        from .ui import flush_parameter_carrier, remove_parameter_carrier
        flush_parameter_carrier()
        remove_parameter_carrier()
        settings = active_armature(context).data.re_rigify
        if settings.collections:
            name = settings.collections[settings.active_collection_index].name
            for bone in settings.bones:
                parameters = json.loads(bone.parameters_json or "{}")
                bone.parameters_json = json.dumps(
                    remove_collection_references(parameters, name),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            settings.collections.remove(settings.active_collection_index)
            settings.active_collection_index = min(settings.active_collection_index, len(settings.collections) - 1)
        return {"FINISHED"}


class RERIGIFY_OT_CollectionMove(bpy.types.Operator):
    bl_idname = "re_rigify.collection_move"
    bl_label = "Move Collection in List"
    bl_options = {"UNDO"}
    direction: IntProperty()

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        index = settings.active_collection_index
        target = index + self.direction
        if not 0 <= target < len(settings.collections):
            return {"CANCELLED"}
        settings.collections.move(index, target)
        settings.active_collection_index = target
        return {"FINISHED"}


class RERIGIFY_OT_CollectionDuplicate(bpy.types.Operator):
    bl_idname = "re_rigify.collection_duplicate"
    bl_label = "Duplicate Collection Configuration"
    bl_options = {"UNDO"}

    def execute(self, context):
        from .ui import flush_parameter_carrier, remove_parameter_carrier
        flush_parameter_carrier()
        remove_parameter_carrier()
        settings = active_armature(context).data.re_rigify
        if not settings.collections:
            return {"CANCELLED"}
        source_index = settings.active_collection_index
        source = settings.collections[source_index]
        source_name = source.name
        source_title = source.ui_title
        source_row = source.ui_row
        source_order = source.row_order
        source_color = source.color_set_name
        source_active_rule = source.active_rule_index
        source_rules = [(rule.kind, rule.pattern) for rule in source.rules]
        for collection in settings.collections:
            if collection.ui_row == source_row and collection.row_order > source_order:
                collection.row_order += 1
        duplicate = settings.collections.add()
        duplicate.name = unique_blender_name(
            source_name,
            (
                collection.name for index, collection in enumerate(settings.collections)
                if index < len(settings.collections) - 1
            ),
        )
        duplicate.ui_title = source_title
        duplicate.ui_row = source_row
        duplicate.row_order = source_order + 1
        duplicate.color_set_name = source_color
        for kind, pattern in source_rules:
            rule = duplicate.rules.add()
            rule.kind = kind
            rule.pattern = pattern
        duplicate.active_rule_index = min(source_active_rule, max(0, len(duplicate.rules) - 1))
        end_index = len(settings.collections) - 1
        target_index = source_index + 1
        settings.collections.move(end_index, target_index)
        settings.active_collection_index = target_index
        _normalize_collection_orders(settings)
        return {"FINISHED"}


class RERIGIFY_OT_CollectionSelect(bpy.types.Operator):
    bl_idname = "re_rigify.collection_select"
    bl_label = "Select Collection"
    bl_options = {"UNDO_GROUPED"}
    index: IntProperty()

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if 0 <= self.index < len(settings.collections):
            settings.active_collection_index = self.index
        return {"FINISHED"}


class RERIGIFY_OT_CollectionSetUIRow(bpy.types.Operator):
    bl_idname = "re_rigify.collection_set_ui_row"
    bl_label = "Move Collection to UI Row"
    bl_options = {"UNDO"}
    index: IntProperty()
    row: IntProperty(min=0)

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if not 0 <= self.index < len(settings.collections):
            return {"CANCELLED"}
        collection = settings.collections[self.index]
        collection.ui_row = self.row
        collection.row_order = sum(
            1 for index, other in enumerate(settings.collections)
            if index != self.index and other.ui_row == self.row
        )
        settings.active_collection_index = self.index
        _normalize_collection_orders(settings)
        return {"FINISHED"}


class RERIGIFY_OT_CollectionMoveInRow(bpy.types.Operator):
    bl_idname = "re_rigify.collection_move_in_row"
    bl_label = "Move Collection Within UI Row"
    bl_options = {"UNDO"}
    direction: IntProperty()

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if not settings.collections:
            return {"CANCELLED"}
        active = settings.collections[settings.active_collection_index]
        row_items = sorted(
            (item for item in settings.collections if item.ui_row == active.ui_row),
            key=lambda item: (item.row_order, item.name),
        )
        position = row_items.index(active)
        target_position = position + self.direction
        if not 0 <= target_position < len(row_items):
            return {"CANCELLED"}
        other = row_items[target_position]
        active.row_order, other.row_order = other.row_order, active.row_order
        _normalize_collection_orders(settings)
        return {"FINISHED"}


class RERIGIFY_OT_CollectionEditUIRow(bpy.types.Operator):
    bl_idname = "re_rigify.collection_edit_ui_row"
    bl_label = "Insert or Remove UI Row"
    bl_options = {"UNDO"}
    row: IntProperty(min=1)
    add: BoolProperty(default=True)

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if self.add:
            for collection in settings.collections:
                if collection.ui_row >= self.row:
                    collection.ui_row += 1
        else:
            for collection in settings.collections:
                if collection.ui_row >= self.row:
                    collection.ui_row = max(1, collection.ui_row - 1)
        _normalize_collection_orders(settings)
        return {"FINISHED"}


class RERIGIFY_OT_ColorSetAdd(bpy.types.Operator):
    bl_idname = "re_rigify.color_set_add"
    bl_label = "Add Color Set"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        item = settings.color_sets.add()
        item.name = f"Color Set {len(settings.color_sets)}"
        item.active = (0.55, 1.0, 1.0)
        item.normal = (0.25, 0.25, 0.25)
        item.select = (0.31, 0.78, 1.0)
        settings.active_color_index = len(settings.color_sets) - 1
        return {"FINISHED"}


class RERIGIFY_OT_ColorSetRemove(bpy.types.Operator):
    bl_idname = "re_rigify.color_set_remove"
    bl_label = "Remove Color Set"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if settings.color_sets:
            name = settings.color_sets[settings.active_color_index].name
            for collection in settings.collections:
                if collection.color_set_name == name:
                    collection.color_set_name = ""
            settings.color_sets.remove(settings.active_color_index)
            settings.active_color_index = min(settings.active_color_index, len(settings.color_sets) - 1)
        return {"FINISHED"}


class RERIGIFY_OT_ColorSetAddDefaults(bpy.types.Operator):
    bl_idname = "re_rigify.color_set_add_defaults"
    bl_label = "Add Rigify Default Color Sets"
    bl_description = "Add missing default Rigify color sets without replacing existing sets"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        existing = {item.name for item in settings.color_sets}
        added = 0
        for name, active, normal, select in RIGIFY_DEFAULT_COLOR_SETS:
            if name in existing:
                continue
            item = settings.color_sets.add()
            item.name = name
            item.active = active
            item.normal = normal
            item.select = select
            item.standard_colors_lock = True
            existing.add(name)
            added += 1
        if added:
            settings.active_color_index = len(settings.color_sets) - 1
        self.report({"INFO"}, f"Added {added} Rigify default color set(s)")
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


class RERIGIFY_OT_CollectionAddViewportBones(bpy.types.Operator):
    bl_idname = "re_rigify.collection_add_viewport_bones"
    bl_label = "Add Selected Viewport Bones"
    bl_description = "Add bones selected in the 3D View while in Pose or Edit Mode"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        obj = active_armature(context)
        return bool(obj and obj.mode in {"EDIT", "POSE"} and obj.data.re_rigify.collections)

    def execute(self, context):
        obj = active_armature(context)
        settings = obj.data.re_rigify
        collection = settings.collections[settings.active_collection_index]
        if obj.mode == "EDIT":
            selected = [bone.name for bone in obj.data.edit_bones if bone.select]
        else:
            selected = [
                bone.name for bone in (context.selected_pose_bones or ()) if bone.id_data == obj
            ]
        if not selected:
            self.report({"ERROR"}, "Select one or more bones in the 3D View")
            return {"CANCELLED"}
        existing = {rule.pattern for rule in collection.rules if rule.kind == "EXACT"}
        added = 0
        for name in selected:
            if name in existing:
                continue
            rule = collection.rules.add()
            rule.kind = "EXACT"
            rule.pattern = name
            existing.add(name)
            added += 1
        collection.active_rule_index = max(0, len(collection.rules) - 1)
        self.report({"INFO"}, f"Added {added} selected bone(s) to {collection.name}")
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
            errors.extend(validate_bone_parameters(context, obj, payload["bones"], payload["collections"]))
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
    RERIGIFY_OT_BoneAdd, RERIGIFY_OT_BoneRemove,
    RERIGIFY_OT_MirrorBoneConfig, RERIGIFY_OT_CopyParametersToSelected,
    RERIGIFY_OT_CollectionAdd, RERIGIFY_OT_CollectionRemove,
    RERIGIFY_OT_CollectionMove, RERIGIFY_OT_CollectionDuplicate,
    RERIGIFY_OT_CollectionSelect, RERIGIFY_OT_CollectionSetUIRow,
    RERIGIFY_OT_CollectionMoveInRow, RERIGIFY_OT_CollectionEditUIRow,
    RERIGIFY_OT_ColorSetAdd, RERIGIFY_OT_ColorSetRemove,
    RERIGIFY_OT_ColorSetAddDefaults,
    RERIGIFY_OT_MarkAllBones, RERIGIFY_OT_CollectionAddMarkedBones,
    RERIGIFY_OT_CollectionAddViewportBones,
    RERIGIFY_OT_RuleAdd, RERIGIFY_OT_RuleRemove,
    RERIGIFY_OT_Validate, RERIGIFY_OT_Export, RERIGIFY_OT_Import,
    RERIGIFY_OT_Generate, RERIGIFY_OT_RemoveDrive,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
