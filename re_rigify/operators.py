"""UI operators for configuration editing, files, validation and generation."""

from __future__ import annotations

import json
import re
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .blender_config import (
    _apply_compatibility_to_item,
    _compatibility_from_item,
    apply_chain_bones_to_item,
    armature_to_payload,
    chain_bones_from_item,
    payload_to_armature,
    suspend_carrier_updates,
    suspend_collection_rename_updates,
)
from .core import (
    ConfigError,
    RIGIFY_DEFAULT_COLOR_SETS,
    arrange_collection_layout,
    materialize_bone_rules,
    mirror_compatibility,
    mirror_parameter_value,
    move_selected_indices,
    normalize_config,
    remove_collection_references,
    rerigify_mirror_name,
    unique_blender_name,
    validate_config,
)
from .generate import generate_rig, validate_bone_parameters
from .compatibility import validate_compatibility
from .drive import connect_source_to_rig, remove_drive_constraints
from .rigify_adapter import available_rig_types, is_rigify_enabled
from .presets import build_preset_payload, preset_enum_items
from .translations import format_iface, iface_


def active_armature(context):
    obj = context.object
    return obj if obj and obj.type == "ARMATURE" else None


def select_only(context, obj):
    """Select one object without invoking context-sensitive selection operators."""
    for candidate in context.view_layer.objects:
        if candidate is not None:
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
    from .rules import armature_rule_topology

    obj = active_armature(context)
    if not obj:
        return None, (iface_("Select an armature object"),)
    if not is_rigify_enabled():
        return obj, (iface_("Rigify is not enabled"),)
    try:
        payload = synchronized_payload(obj, include_managed=True)
    except (ConfigError, ValueError, json.JSONDecodeError) as exc:
        return obj, (
            format_iface(
                "Invalid stored parameter JSON: {error}",
                error=exc,
            ),
        )
    parents, aligned_edges = armature_rule_topology(obj.data)
    result = validate_config(
        payload,
        obj.data.bones.keys(),
        available_rig_types(),
        parents,
        aligned_edges,
    )
    errors = list(result.errors)
    if not errors:
        errors.extend(validate_compatibility(obj, payload["bones"]))
    if not errors:
        errors.extend(validate_bone_parameters(context, obj, payload["bones"], payload["collections"]))
    return obj, tuple(errors)


def synchronized_payload(obj, include_managed=True):
    from .rules import armature_rule_topology, cleanup_bone_rule_rows
    from .ui import flush_parameter_carrier, remove_parameter_carrier

    flush_parameter_carrier()
    remove_parameter_carrier()
    cleanup_bone_rule_rows(obj.data)
    payload = armature_to_payload(
        obj.data, include_managed=False,
    )
    if not include_managed:
        return payload
    parents, aligned_edges = armature_rule_topology(obj.data)
    return materialize_bone_rules(
        payload,
        obj.data.bones.keys(),
        parents,
        aligned_edges,
    )


class RERIGIFY_OT_BoneAdd(bpy.types.Operator):
    bl_idname = "re_rigify.bone_add"
    bl_label = "Add Selected Bones"
    bl_description = "Add all selected Pose/Edit Mode bones, or the active bone as a fallback"
    bl_options = {"UNDO"}

    def execute(self, context):
        from .ui import flush_parameter_carrier, prepare_parameter_carrier, remove_parameter_carrier

        obj = active_armature(context)
        if not obj:
            self.report({"ERROR"}, iface_("Select an armature"))
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
            self.report(
                {"ERROR"},
                iface_("Select one or more armature bones"),
            )
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
        self.report(
            {"INFO"},
            format_iface(
                "Added {added} bone(s); skipped {skipped} existing",
                added=len(added_indices),
                skipped=skipped,
            ),
        )
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


class RERIGIFY_OT_BoneMove(bpy.types.Operator):
    bl_idname = "re_rigify.bone_move"
    bl_label = "Move Bone Configuration"
    bl_description = "Move checked configurations, or the active configuration if none are checked"
    bl_options = {"UNDO"}

    direction: IntProperty()

    def execute(self, context):
        from .ui import (
            flush_parameter_carrier,
            prepare_parameter_carrier,
            remove_parameter_carrier,
        )

        obj = active_armature(context)
        if obj is None:
            return {"CANCELLED"}
        settings = obj.data.re_rigify
        if not settings.bones:
            return {"CANCELLED"}
        selected = {
            index for index, item in enumerate(settings.bones)
            if item.collection_selected
        }
        if not selected:
            selected = {settings.active_bone_index}
        operations = move_selected_indices(
            len(settings.bones), selected, self.direction,
        )
        if not operations:
            return {"CANCELLED"}

        active_name = settings.bones[settings.active_bone_index].bone_name
        flush_parameter_carrier()
        remove_parameter_carrier()
        with suspend_carrier_updates():
            for source, target in operations:
                settings.bones.move(source, target)
            settings.active_bone_index = next(
                index for index, item in enumerate(settings.bones)
                if item.bone_name == active_name
            )
        active_index = settings.active_bone_index
        prepare_parameter_carrier(
            context, obj, settings.bones[active_index], active_index,
        )
        return {"FINISHED"}


class RERIGIFY_OT_BoneRuleAdd(bpy.types.Operator):
    bl_idname = "re_rigify.bone_rule_add"
    bl_label = "Add Bone Matching Rule"
    bl_options = {"UNDO"}

    def execute(self, context):
        import uuid
        from .ui import flush_parameter_carrier, remove_parameter_carrier

        obj = active_armature(context)
        if obj is None:
            return {"CANCELLED"}
        flush_parameter_carrier()
        remove_parameter_carrier()
        settings = obj.data.re_rigify
        rule = settings.bone_rules.add()
        rule.rule_id = uuid.uuid4().hex
        rule.kind = "GLOB"
        rule.pattern = "*"
        types = available_rig_types()
        rule.rigify_type = (
            "basic.raw_copy" if "basic.raw_copy" in types
            else (types[0] if types else "")
        )
        settings.active_bone_rule_index = len(settings.bone_rules) - 1
        return {"FINISHED"}


class RERIGIFY_OT_BoneRuleRemove(bpy.types.Operator):
    bl_idname = "re_rigify.bone_rule_remove"
    bl_label = "Remove Bone Matching Rule"
    bl_options = {"UNDO"}

    def execute(self, context):
        from .ui import flush_parameter_carrier, remove_parameter_carrier

        obj = active_armature(context)
        if obj is None:
            return {"CANCELLED"}
        settings = obj.data.re_rigify
        if not settings.bone_rules:
            return {"CANCELLED"}
        flush_parameter_carrier()
        remove_parameter_carrier()
        settings.bone_rules.remove(settings.active_bone_rule_index)
        settings.active_bone_rule_index = min(
            settings.active_bone_rule_index,
            max(0, len(settings.bone_rules) - 1),
        )
        return {"FINISHED"}


class RERIGIFY_OT_BoneRuleMove(bpy.types.Operator):
    bl_idname = "re_rigify.bone_rule_move"
    bl_label = "Move Bone Matching Rule"
    bl_options = {"UNDO"}

    direction: IntProperty()

    def execute(self, context):
        from .ui import flush_parameter_carrier, remove_parameter_carrier

        obj = active_armature(context)
        if obj is None:
            return {"CANCELLED"}
        settings = obj.data.re_rigify
        source = settings.active_bone_rule_index
        target = source + self.direction
        if not 0 <= source < len(settings.bone_rules):
            return {"CANCELLED"}
        if not 0 <= target < len(settings.bone_rules):
            return {"CANCELLED"}
        flush_parameter_carrier()
        remove_parameter_carrier()
        settings.bone_rules.move(source, target)
        settings.active_bone_rule_index = target
        return {"FINISHED"}


class RERIGIFY_OT_ChainAddSelected(bpy.types.Operator):
    bl_idname = "re_rigify.chain_add_selected"
    bl_label = "Add Selected Bones to Explicit Chain"
    bl_options = {"UNDO"}

    def execute(self, context):
        obj = active_armature(context)
        settings = obj.data.re_rigify
        if not settings.bones:
            return {"CANCELLED"}
        item = settings.bones[settings.active_bone_index]
        if obj.mode == "EDIT":
            selected_names = {
                bone.name for bone in obj.data.edit_bones
                if bone.select or bone.select_head or bone.select_tail
            }
        elif obj.mode == "POSE":
            selected_names = {
                bone.name for bone in (context.selected_pose_bones or ())
                if bone.id_data == obj
            }
        else:
            selected_names = {
                bone.name for bone in obj.data.bones if bone.select
            }
        if not selected_names:
            active = (
                obj.data.edit_bones.active if obj.mode == "EDIT"
                else obj.data.bones.active
            )
            if active is not None:
                selected_names = {active.name}
        if not selected_names:
            self.report(
                {"ERROR"},
                iface_("Select one or more armature bones"),
            )
            return {"CANCELLED"}

        existing = set(chain_bones_from_item(item))
        ordered = []
        if not existing and item.bone_name in obj.data.bones:
            ordered.append(item.bone_name)
            existing.add(item.bone_name)
        ordered.extend(
            bone.name for bone in obj.data.bones
            if bone.name in selected_names and bone.name not in existing
        )
        for bone_name in ordered:
            entry = item.chain_bones.add()
            entry.bone_name = bone_name
        item.active_chain_index = max(0, len(item.chain_bones) - 1)
        self.report(
            {"INFO"},
            format_iface(
                "Added {count} explicit chain bone(s)",
                count=len(ordered),
            ),
        )
        return {"FINISHED"}


class RERIGIFY_OT_ChainRemove(bpy.types.Operator):
    bl_idname = "re_rigify.chain_remove"
    bl_label = "Remove Explicit Chain Bone"
    bl_options = {"UNDO"}

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if not settings.bones:
            return {"CANCELLED"}
        item = settings.bones[settings.active_bone_index]
        if not item.chain_bones:
            return {"CANCELLED"}
        item.chain_bones.remove(item.active_chain_index)
        item.active_chain_index = min(
            item.active_chain_index,
            max(0, len(item.chain_bones) - 1),
        )
        return {"FINISHED"}


class RERIGIFY_OT_ChainMove(bpy.types.Operator):
    bl_idname = "re_rigify.chain_move"
    bl_label = "Move Explicit Chain Bone"
    bl_options = {"UNDO"}

    direction: IntProperty()

    def execute(self, context):
        settings = active_armature(context).data.re_rigify
        if not settings.bones:
            return {"CANCELLED"}
        item = settings.bones[settings.active_bone_index]
        source = item.active_chain_index
        target = source + self.direction
        if not 0 <= source < len(item.chain_bones) or not 0 <= target < len(item.chain_bones):
            return {"CANCELLED"}
        item.chain_bones.move(source, target)
        item.active_chain_index = target
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
                chain_bones_from_item(item),
                item.parameters_json,
                _compatibility_from_item(item),
            )
            for item in selected
        ]
        source_names = {
            bone_name
            for bone_name, _rig_type, _chain_bones, _parameters, _compat in snapshots
        }
        for bone_name, _rig_type, _chain_bones, _parameters, _compat in snapshots:
            target_name = rerigify_mirror_name(bone_name)
            if target_name == bone_name:
                self.report(
                    {"ERROR"},
                    format_iface(
                        "{bone_name!r} has no L/R side suffix",
                        bone_name=bone_name,
                    ),
                )
                return {"CANCELLED"}
            if target_name not in obj.data.bones:
                self.report(
                    {"ERROR"},
                    format_iface(
                        "Mirrored bone {bone_name!r} does not exist",
                        bone_name=target_name,
                    ),
                )
                return {"CANCELLED"}
            if target_name in source_names:
                self.report(
                    {"ERROR"},
                    iface_(
                        "Do not select both sides of the same mirrored pair"
                    ),
                )
                return {"CANCELLED"}

        remove_parameter_carrier()
        last_target_index = settings.active_bone_index
        with suspend_carrier_updates():
            for bone_name, rig_type, chain_bones, parameters_json, compatibility in snapshots:
                target_name = rerigify_mirror_name(bone_name)
                target_index = next(
                    (index for index, item in enumerate(settings.bones) if item.bone_name == target_name),
                    -1,
                )
                target = settings.bones[target_index] if target_index >= 0 else settings.bones.add()
                if target_index < 0:
                    target_index = len(settings.bones) - 1
                target.bone_name = target_name
                target.rigify_type = rig_type
                apply_chain_bones_to_item(
                    target,
                    [rerigify_mirror_name(chain_bone) for chain_bone in chain_bones],
                )
                target.parameters_json = json.dumps(
                    mirror_parameter_value(json.loads(parameters_json or "{}"), rerigify_mirror_name),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                _apply_compatibility_to_item(
                    target, mirror_compatibility(compatibility, rerigify_mirror_name)
                )
                last_target_index = target_index
        for item in settings.bones:
            item.collection_selected = False
        settings.active_bone_index = last_target_index
        target = settings.bones[last_target_index]
        prepare_parameter_carrier(context, obj, target, last_target_index)
        self.report(
            {"INFO"},
            format_iface(
                "Mirrored {count} configuration(s)",
                count=len(snapshots),
            ),
        )
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
            self.report(
                {"ERROR"},
                iface_("Check at least one target bone"),
            )
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
        self.report(
            {"INFO"},
            format_iface(
                "Copied bone settings to {count} bone(s)",
                count=len(targets),
            ),
        )
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
        item.last_valid_name = item.name
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
            for rule in settings.bone_rules:
                parameters = json.loads(rule.parameters_json or "{}")
                rule.parameters_json = json.dumps(
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
        source_visibility = source.visible_after_generation
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
        duplicate.last_valid_name = duplicate.name
        duplicate.ui_title = source_title
        duplicate.ui_row = source_row
        duplicate.row_order = source_order + 1
        duplicate.color_set_name = source_color
        duplicate.visible_after_generation = source_visibility
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
        self.report(
            {"INFO"},
            format_iface(
                "Added {count} Rigify default color set(s)",
                count=added,
            ),
        )
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
            self.report(
                {"ERROR"},
                iface_("Create a bone collection configuration first"),
            )
            return {"CANCELLED"}
        if not settings.bones:
            self.report(
                {"ERROR"},
                iface_("No configured bones to add"),
            )
            return {"CANCELLED"}
        collection = settings.collections[settings.active_collection_index]
        added = _add_selected_bones_to_active_collection(settings)
        for item in settings.bones:
            item.collection_selected = False
        self.report(
            {"INFO"},
            format_iface(
                "Added {count} bone(s) to {collection}",
                count=added,
                collection=collection.name,
            ),
        )
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
            self.report(
                {"ERROR"},
                iface_("Select one or more bones in the 3D View"),
            )
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
        self.report(
            {"INFO"},
            format_iface(
                "Added {count} selected bone(s) to {collection}",
                count=added,
                collection=collection.name,
            ),
        )
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
            self.report(
                {"ERROR"},
                format_iface(
                    "Validation failed with {count} error(s)",
                    count=len(errors),
                ),
            )
            return {"CANCELLED"}
        message = iface_("Configuration is valid")
        obj.data.re_rigify.validation_message = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


class RERIGIFY_OT_Export(bpy.types.Operator, ExportHelper):
    bl_idname = "re_rigify.export_config"
    bl_label = "Export Re-Rigify Configuration"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        obj, errors = validate_active(context)
        if errors:
            self.report(
                {"ERROR"},
                iface_("Fix validation errors before exporting"),
            )
            return {"CANCELLED"}
        Path(self.filepath).write_text(
            json.dumps(
                synchronized_payload(obj, include_managed=False),
                ensure_ascii=False,
                indent=2,
            ) + "\n",
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
        from .rules import armature_rule_topology
        from .ui import flush_parameter_carrier, remove_parameter_carrier
        flush_parameter_carrier()
        remove_parameter_carrier()
        try:
            payload = json.loads(Path(self.filepath).read_text(encoding="utf-8"))
            payload = normalize_config(payload)
            parents, aligned_edges = armature_rule_topology(obj.data)
            resolved = materialize_bone_rules(
                payload,
                obj.data.bones.keys(),
                parents,
                aligned_edges,
            )
        except (OSError, json.JSONDecodeError, ConfigError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        result = validate_config(
            payload,
            obj.data.bones.keys(),
            available_rig_types(),
            parents,
            aligned_edges,
        )
        errors = list(result.errors)
        if not errors:
            errors.extend(validate_compatibility(obj, resolved["bones"]))
        if not errors:
            errors.extend(validate_bone_parameters(
                context, obj, resolved["bones"], resolved["collections"],
            ))
        if errors:
            obj.data.re_rigify.validation_message = "\n".join(errors)
            self.report(
                {"ERROR"},
                format_iface(
                    "Import rejected with {count} error(s)",
                    count=len(errors),
                ),
            )
            return {"CANCELLED"}
        payload_to_armature(obj.data, payload)
        return {"FINISHED"}


def _apply_preset_payload(context, obj, preset_id: str):
    """Validate and write a built-in preset onto the active armature."""
    from .rules import armature_rule_topology
    from .ui import flush_parameter_carrier, remove_parameter_carrier
    from .presets import adapt_mmd_jp_payload

    flush_parameter_carrier()
    remove_parameter_carrier()
    payload = build_preset_payload(preset_id)
    if preset_id == "mmd_jp":
        payload = adapt_mmd_jp_payload(payload, obj.data.bones.keys())
    parents, aligned_edges = armature_rule_topology(obj.data)
    resolved = materialize_bone_rules(
        payload,
        obj.data.bones.keys(),
        parents,
        aligned_edges,
    )
    result = validate_config(
        payload,
        obj.data.bones.keys(),
        available_rig_types(),
        parents,
        aligned_edges,
    )
    errors = list(result.errors)
    if not errors:
        errors.extend(validate_compatibility(obj, resolved["bones"]))
    if not errors:
        errors.extend(
            validate_bone_parameters(
                context, obj, resolved["bones"], resolved["collections"],
            )
        )
    if errors:
        obj.data.re_rigify.validation_message = "\n".join(errors)
        raise ConfigError(
            format_iface(
                "Preset rejected with {count} error(s)",
                count=len(errors),
            )
        )
    payload_to_armature(obj.data, payload)
    obj.data.re_rigify.validation_message = iface_("Built-in preset applied")
    return payload


class RERIGIFY_OT_ApplyPreset(bpy.types.Operator):
    bl_idname = "re_rigify.apply_preset"
    bl_label = "Apply Built-in Preset"
    bl_description = "Replace the armature Re-Rigify configuration with a built-in preset"
    bl_options = {"UNDO"}

    preset: EnumProperty(
        name="Preset",
        items=preset_enum_items,
    )
    generate: BoolProperty(
        name="Generate After Apply",
        description="Generate and connect the Rigify rig immediately after applying the preset",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        obj = active_armature(context)
        if obj is None:
            self.report({"ERROR"}, iface_("Select an armature"))
            return {"CANCELLED"}
        try:
            _apply_preset_payload(context, obj, self.preset)
        except ConfigError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        if not self.generate:
            select_only(context, obj)
            self.report(
                {"INFO"},
                format_iface(
                    "Applied built-in preset {preset}",
                    preset=self.preset,
                ),
            )
            return {"FINISHED"}

        obj, errors = validate_active(context)
        if errors:
            obj.data.re_rigify.validation_message = "\n".join(errors)
            self.report(
                {"ERROR"},
                iface_("Preset applied, but generation was blocked by validation errors"),
            )
            return {"CANCELLED"}
        try:
            generated = generate_rig(
                context,
                obj,
                synchronized_payload(obj, include_managed=True),
            )
            mapped, unmatched = connect_source_to_rig(obj, generated)
        except Exception as exc:
            self.report(
                {"ERROR"},
                format_iface(
                    "Rigify generation failed: {error}",
                    error=exc,
                ),
            )
            return {"CANCELLED"}
        select_only(context, generated)
        self.report(
            {"INFO"},
            format_iface(
                "Applied preset and generated rig ({mapped} driven, {unmatched} unmatched)",
                mapped=mapped,
                unmatched=len(unmatched),
            ),
        )
        return {"FINISHED"}



class RERIGIFY_OT_Generate(bpy.types.Operator):
    bl_idname = "re_rigify.generate"
    bl_label = "Generate Rigify Rig"
    bl_options = {"UNDO"}

    def execute(self, context):
        obj, errors = validate_active(context)
        if errors:
            obj.data.re_rigify.validation_message = "\n".join(errors)
            self.report(
                {"ERROR"},
                iface_("Fix validation errors before generating"),
            )
            return {"CANCELLED"}
        try:
            generated = generate_rig(
                context, obj,
                synchronized_payload(obj, include_managed=True),
            )
            mapped, unmatched = connect_source_to_rig(obj, generated)
        except Exception as exc:
            self.report(
                {"ERROR"},
                format_iface(
                    "Rigify generation failed: {error}",
                    error=exc,
                ),
            )
            return {"CANCELLED"}
        select_only(context, generated)
        self.report(
            {"INFO"},
            format_iface(
                "Generated rig drives {mapped} source bones; {unmatched} unmatched",
                mapped=mapped,
                unmatched=len(unmatched),
            ),
        )
        return {"FINISHED"}


class RERIGIFY_OT_RemoveDrive(bpy.types.Operator):
    bl_idname = "re_rigify.remove_drive"
    bl_label = "Remove Rigify Drive"
    bl_description = "Remove only the Copy Transforms constraints created by Re-Rigify"
    bl_options = {"UNDO"}

    def execute(self, context):
        source = active_armature(context)
        if source is None:
            self.report(
                {"WARNING"},
                iface_("Select the source armature"),
            )
            return {"CANCELLED"}
        try:
            removed = remove_drive_constraints(source)
        except Exception as exc:
            self.report(
                {"WARNING"},
                format_iface(
                    "Failed to remove Rigify drive: {error}",
                    error=exc,
                ),
            )
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            format_iface(
                "Removed {count} Re-Rigify constraints",
                count=removed,
            ),
        )
        return {"FINISHED"}


def _get_selected_bones(context, obj) -> list[str]:
    if not obj or obj.type != "ARMATURE":
        return []
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
    return [bone.name for bone in ordered_bones if bone.name in selected_names]


def _topological_sort_bones(bone_names: list[str], parents: dict[str, str | None]) -> list[str]:
    def get_depth(name: str) -> int:
        depth = 0
        curr = parents.get(name)
        seen = {name}
        while curr and curr not in seen:
            seen.add(curr)
            depth += 1
            curr = parents.get(curr)
        return depth

    return sorted(bone_names, key=lambda b: (get_depth(b), b))


def _partition_finger_chains(bone_names: list[str], parents: dict[str, str | None]) -> list[list[str]]:
    names_set = set(bone_names)
    roots = [b for b in bone_names if parents.get(b) not in names_set]
    chains = []
    for root in roots:
        chain = [root]
        curr = root
        while True:
            children = [b for b in bone_names if parents.get(b) == curr and b in names_set]
            if not children:
                break
            curr = children[0]
            chain.append(curr)
        chains.append(chain)
    return chains


def _detect_bone_side(bone_names: list[str]) -> str | None:
    for b in bone_names:
        m = rerigify_mirror_name(b)
        if m != b:
            upper = b.upper()
            if (
                re.search(r"(?:^|[\s._-])L(?:$|[\s._-])", upper)
                or "左" in b
                or "LEFT" in upper
                or re.match(r"^L(?=[A-Z_])", b)
            ):
                return "L"
            elif (
                re.search(r"(?:^|[\s._-])R(?:$|[\s._-])", upper)
                or "右" in b
                or "RIGHT" in upper
                or re.match(r"^R(?=[A-Z_])", b)
            ):
                return "R"
    return None


def _ensure_default_color_sets(settings):
    if not settings.color_sets:
        for name, active, normal, select in RIGIFY_DEFAULT_COLOR_SETS:
            item = settings.color_sets.add()
            item.name = name
            item.active = active
            item.normal = normal
            item.select = select
            item.standard_colors_lock = True
        settings.root_color_set_name = "Root"


def _ensure_collection_config(
    settings,
    name: str,
    color_set: str,
    visible: bool = True,
    bone_names: list[str] | None = None,
):
    coll = next((c for c in settings.collections if c.name == name), None)
    if coll is None:
        coll = settings.collections.add()
        coll.name = name
        coll.last_valid_name = name
        coll.color_set_name = color_set
        coll.visible_after_generation = visible
    elif not coll.color_set_name:
        coll.color_set_name = color_set
    if bone_names:
        existing = {r.pattern for r in coll.rules if r.kind == "EXACT"}
        for b in bone_names:
            if b not in existing:
                r = coll.rules.add()
                r.kind = "EXACT"
                r.pattern = b
                existing.add(b)
    return coll


def _set_bone_configuration(
    settings,
    bone_name: str,
    rigify_type: str,
    chain: list[str] | None = None,
    parameters: dict | None = None,
    **compat,
):
    item = next((b for b in settings.bones if b.bone_name == bone_name), None)
    if item is None:
        item = settings.bones.add()
        item.bone_name = bone_name
    item.rigify_type = rigify_type
    if chain:
        apply_chain_bones_to_item(item, chain)
    else:
        item.chain_bones.clear()
    if parameters:
        item.parameters_json = json.dumps(parameters, ensure_ascii=False, sort_keys=True)
    if compat:
        _apply_compatibility_to_item(item, compat)
    return item


class RERIGIFY_OT_QuickSetupBones(bpy.types.Operator):
    bl_idname = "re_rigify.quick_setup_bones"
    bl_label = "Quick Setup Bone Configuration"
    bl_description = "Quickly configure human armature bones (Head, Torso, Arm, Leg, Fingers, Eyes) with collections and mirroring"
    bl_options = {"UNDO"}

    body_part: EnumProperty(
        name="Body Part",
        items=(
            ("HEAD", "Head", "Head & neck chain"),
            ("TORSO", "Torso", "Spine & chest chain"),
            ("ARM", "Arm / Hand", "Shoulder (super_copy) + arm chain (limbs.arm)"),
            ("LEG", "Leg", "Thigh, calf, foot... (limbs.leg, supports 3/4/5 bones)"),
            ("FINGER", "Fingers", "Finger chains (limbs.super_finger)"),
            ("EYE", "Eyes", "Eye controllers (face.skin_eye)"),
        ),
        default="ARM",
    )
    mirror_symmetric: BoolProperty(
        name="Mirror to Opposite Side",
        description="Automatically configure opposite side if symmetric (.L/.R)",
        default=True,
    )
    eye_forward_axis: EnumProperty(
        name="Eye Forward Axis",
        description="Forward gazing direction of the eye bone",
        items=(
            ("-Y", "-Y (MMD / Standard Front)", "Point the temporary eye bone along negative Y"),
            ("+Y", "+Y", "Point the temporary eye bone along positive Y"),
            ("+X", "+X", "Point the temporary eye bone along positive X"),
            ("-X", "-X", "Point the temporary eye bone along negative X"),
            ("AUTO", "Auto", "Infer the horizontal viewing direction from eyelid bones"),
        ),
        default="-Y",
    )
    finger_preset: EnumProperty(
        name="Finger Curl Preset",
        items=(
            ("MMR", "MMR Style (-X Curl)", "Align rolls to Global +Z/-Y with -X primary axis for natural fist curling on scale down"),
            ("AUTO", "Keep Original (AUTO)", "Keep original bone rolls and automatic rotation axis"),
        ),
        default="MMR",
    )
    enable_finger_ik: BoolProperty(
        name="Enable Finger IK",
        description="Generate fingertip IK controls with FK/IK sliders and snapping",
        default=True,
    )
    thumb_roll_alignment: EnumProperty(
        name="Thumb Roll Alignment",
        items=(
            ("GLOBAL_NEG_Y", "Global -Y (MMR Default)", "Align thumb roll to Global -Y for natural inward opposition curl"),
            ("GLOBAL_POS_Z", "Global +Z", "Align thumb roll to Global +Z (same as other fingers)"),
        ),
        default="GLOBAL_NEG_Y",
    )

    def invoke(self, context, _event):
        obj = active_armature(context)
        if not obj:
            self.report({"ERROR"}, iface_("Select an armature"))
            return {"CANCELLED"}
        selected = _get_selected_bones(context, obj)
        if not selected:
            self.report(
                {"ERROR"},
                iface_("Select one or more bones in Pose or Edit Mode"),
            )
            return {"CANCELLED"}

        names_lower = " ".join(selected).lower()
        if any(k in names_lower for k in ("eye", "pupil", "目", "瞳")):
            self.body_part = "EYE"
        elif any(k in names_lower for k in ("arm", "hand", "shoulder", "wrist", "elbow", "肩", "腕", "手首", "ひじ")):
            self.body_part = "ARM"
        elif any(k in names_lower for k in ("leg", "foot", "thigh", "knee", "shin", "toe", "ankle", "足", "ひざ", "足首", "つま先")):
            self.body_part = "LEG"
        elif any(k in names_lower for k in ("finger", "thumb", "index", "pinky", "ring", "指")):
            self.body_part = "FINGER"
        elif any(k in names_lower for k in ("head", "neck", "face", "首", "頭")):
            self.body_part = "HEAD"
        elif any(k in names_lower for k in ("spine", "torso", "hips", "chest", "pelvis", "腰", "上半身", "下半身")):
            self.body_part = "TORSO"
        else:
            self.body_part = "ARM"

        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "body_part")
        if self.body_part in {"ARM", "LEG", "FINGER", "EYE"}:
            layout.prop(self, "mirror_symmetric")
        if self.body_part == "EYE":
            box = layout.box()
            box.label(text=iface_("Eye Options"), icon="HIDE_OFF")
            box.prop(self, "eye_forward_axis")
        elif self.body_part == "FINGER":
            box = layout.box()
            box.label(text=iface_("Finger Options"), icon="HAND")
            box.prop(self, "finger_preset")
            if self.finger_preset == "MMR":
                box.prop(self, "thumb_roll_alignment")
            box.prop(self, "enable_finger_ik")
        obj = active_armature(context)
        selected = _get_selected_bones(context, obj) if obj else []
        box = layout.box()
        box.label(
            text=format_iface(
                "Selected Bones: {count}",
                count=len(selected),
            ),
            icon="BONE_DATA",
            translate=False,
        )

    def execute(self, context):
        from rigify.utils.naming import mirror_name
        from .ui import flush_parameter_carrier, prepare_parameter_carrier, remove_parameter_carrier

        obj = active_armature(context)
        if not obj:
            self.report({"ERROR"}, iface_("Select an armature"))
            return {"CANCELLED"}
        selected = _get_selected_bones(context, obj)
        if not selected:
            self.report(
                {"ERROR"},
                iface_("Select one or more bones in Pose or Edit Mode"),
            )
            return {"CANCELLED"}

        flush_parameter_carrier()
        remove_parameter_carrier()

        settings = obj.data.re_rigify
        _ensure_default_color_sets(settings)

        parents = {b.name: b.parent.name if b.parent else None for b in obj.data.bones}
        selected_sorted = _topological_sort_bones(selected, parents)
        side = _detect_bone_side(selected_sorted)
        side_tag = side or "L"
        opp_side = "R" if side_tag == "L" else "L"

        with suspend_carrier_updates(), suspend_collection_rename_updates():
            if self.body_part == "HEAD":
                chain = selected_sorted
                root = chain[0]
                _set_bone_configuration(
                    settings,
                    root,
                    "spines.super_head",
                    chain=chain,
                    parameters={"tweak_coll_refs": ["Head Tweak"], "tweak_layers_extra": True},
                )
                _ensure_collection_config(settings, "Head", "Special", visible=True, bone_names=chain)
                _ensure_collection_config(settings, "Head Tweak", "Tweak", visible=False)

            elif self.body_part == "TORSO":
                chain = selected_sorted
                root = chain[0]
                params = {
                    "make_fk_controls": True,
                    "fk_coll_refs": ["Torso FK"],
                    "fk_layers_extra": True,
                    "tweak_coll_refs": ["Torso Tweak"],
                    "tweak_layers_extra": True,
                }
                if len(chain) == 3:
                    params["pivot_pos"] = 1
                _set_bone_configuration(
                    settings,
                    root,
                    "spines.basic_spine",
                    chain=chain,
                    parameters=params,
                )
                _ensure_collection_config(settings, "Torso", "Special", visible=True, bone_names=chain)
                _ensure_collection_config(settings, "Torso FK", "FK", visible=False)
                _ensure_collection_config(settings, "Torso Tweak", "Tweak", visible=False)

            elif self.body_part == "ARM":
                has_shoulder = len(selected_sorted) >= 4
                if has_shoulder:
                    shoulder = selected_sorted[0]
                    arm_chain = selected_sorted[1:]
                    _set_bone_configuration(
                        settings,
                        shoulder,
                        "basic.super_copy",
                        parameters={"super_copy_widget_type": "shoulder", "make_control": True, "make_widget": True},
                    )
                else:
                    shoulder = None
                    arm_chain = selected_sorted

                _set_bone_configuration(
                    settings,
                    arm_chain[0],
                    "limbs.arm",
                    chain=arm_chain,
                    parameters={
                        "fk_coll_refs": [f"Arm FK.{side_tag}"],
                        "fk_layers_extra": True,
                        "tweak_coll_refs": [f"Arm Tweak.{side_tag}"],
                        "tweak_layers_extra": True,
                    },
                )
                _ensure_collection_config(settings, f"Arm.{side_tag}", "IK", visible=True, bone_names=selected_sorted)
                _ensure_collection_config(settings, f"Arm FK.{side_tag}", "FK", visible=False)
                _ensure_collection_config(settings, f"Arm Tweak.{side_tag}", "Tweak", visible=False)

                if self.mirror_symmetric and side:
                    mirrored_all = [rerigify_mirror_name(b) for b in selected_sorted]
                    if all(b in obj.data.bones for b in mirrored_all):
                        if has_shoulder:
                            opp_shoulder = rerigify_mirror_name(shoulder)
                            opp_arm_chain = [rerigify_mirror_name(b) for b in arm_chain]
                            _set_bone_configuration(
                                settings,
                                opp_shoulder,
                                "basic.super_copy",
                                parameters={"super_copy_widget_type": "shoulder", "make_control": True, "make_widget": True},
                            )
                        else:
                            opp_arm_chain = mirrored_all

                        _set_bone_configuration(
                            settings,
                            opp_arm_chain[0],
                            "limbs.arm",
                            chain=opp_arm_chain,
                            parameters={
                                "fk_coll_refs": [f"Arm FK.{opp_side}"],
                                "fk_layers_extra": True,
                                "tweak_coll_refs": [f"Arm Tweak.{opp_side}"],
                                "tweak_layers_extra": True,
                            },
                        )
                        _ensure_collection_config(settings, f"Arm.{opp_side}", "IK", visible=True, bone_names=mirrored_all)
                        _ensure_collection_config(settings, f"Arm FK.{opp_side}", "FK", visible=False)
                        _ensure_collection_config(settings, f"Arm Tweak.{opp_side}", "Tweak", visible=False)

            elif self.body_part == "LEG":
                chain = list(selected_sorted)
                if len(chain) == 3:
                    foot_bone = chain[2]
                    toe_candidates = [
                        name for name, parent in parents.items()
                        if parent == foot_bone and any(k in name.lower() for k in ("toe", "つま先"))
                    ]
                    if toe_candidates:
                        chain.append(toe_candidates[0])

                root = chain[0]
                _set_bone_configuration(
                    settings,
                    root,
                    "limbs.leg",
                    chain=chain,
                    parameters={
                        "fk_coll_refs": [f"Leg FK.{side_tag}"],
                        "fk_layers_extra": True,
                        "tweak_coll_refs": [f"Leg Tweak.{side_tag}"],
                        "tweak_layers_extra": True,
                    },
                )
                _ensure_collection_config(settings, f"Leg.{side_tag}", "IK", visible=True, bone_names=chain)
                _ensure_collection_config(settings, f"Leg FK.{side_tag}", "FK", visible=False)
                _ensure_collection_config(settings, f"Leg Tweak.{side_tag}", "Tweak", visible=False)

                if self.mirror_symmetric and side:
                    opp_chain = [rerigify_mirror_name(b) for b in chain]
                    if all(b in obj.data.bones for b in opp_chain):
                        _set_bone_configuration(
                            settings,
                            opp_chain[0],
                            "limbs.leg",
                            chain=opp_chain,
                            parameters={
                                "fk_coll_refs": [f"Leg FK.{opp_side}"],
                                "fk_layers_extra": True,
                                "tweak_coll_refs": [f"Leg Tweak.{opp_side}"],
                                "tweak_layers_extra": True,
                            },
                        )
                        _ensure_collection_config(settings, f"Leg.{opp_side}", "IK", visible=True, bone_names=opp_chain)
                        _ensure_collection_config(settings, f"Leg FK.{opp_side}", "FK", visible=False)
                        _ensure_collection_config(settings, f"Leg Tweak.{opp_side}", "Tweak", visible=False)

            elif self.body_part == "FINGER":
                chains = _partition_finger_chains(selected_sorted, parents)
                for fchain in chains:
                    froot = fchain[0]
                    is_thumb = "親指" in froot or "thumb" in froot.lower() or "拇指" in froot
                    if self.finger_preset == "MMR":
                        roll_align = self.thumb_roll_alignment if is_thumb else "GLOBAL_POS_Z"
                        primary_axis = "-X"
                    else:
                        roll_align = "AUTO"
                        primary_axis = "AUTO"

                    params = {
                        "tweak_coll_refs": [f"Fingers Tweak.{side_tag}"],
                        "tweak_layers_extra": True,
                    }
                    if self.enable_finger_ik:
                        params["make_extra_ik_control"] = True
                        params["extra_ik_coll_refs"] = [f"Fingers IK.{side_tag}"]
                        params["extra_ik_layers_extra"] = True

                    _set_bone_configuration(
                        settings,
                        froot,
                        "limbs.super_finger",
                        chain=fchain,
                        parameters=params,
                        force_connect_chain=True,
                        super_finger_primary_axis=primary_axis,
                        super_finger_roll_alignment=roll_align,
                    )
                _ensure_collection_config(settings, f"Fingers.{side_tag}", "Extra", visible=True, bone_names=selected_sorted)
                if self.enable_finger_ik:
                    _ensure_collection_config(settings, f"Fingers IK.{side_tag}", "IK", visible=False)
                _ensure_collection_config(settings, f"Fingers Tweak.{side_tag}", "Tweak", visible=False)

                if self.mirror_symmetric and side:
                    mirrored_all = [rerigify_mirror_name(b) for b in selected_sorted]
                    if all(b in obj.data.bones for b in mirrored_all):
                        for fchain in chains:
                            opp_fchain = [rerigify_mirror_name(b) for b in fchain]
                            opp_froot = opp_fchain[0]
                            is_thumb = "親指" in opp_froot or "thumb" in opp_froot.lower() or "拇指" in opp_froot
                            if self.finger_preset == "MMR":
                                roll_align = self.thumb_roll_alignment if is_thumb else "GLOBAL_POS_Z"
                                primary_axis = "-X"
                            else:
                                roll_align = "AUTO"
                                primary_axis = "AUTO"

                            params = {
                                "tweak_coll_refs": [f"Fingers Tweak.{opp_side}"],
                                "tweak_layers_extra": True,
                            }
                            if self.enable_finger_ik:
                                params["make_extra_ik_control"] = True
                                params["extra_ik_coll_refs"] = [f"Fingers IK.{opp_side}"]
                                params["extra_ik_layers_extra"] = True

                            _set_bone_configuration(
                                settings,
                                opp_froot,
                                "limbs.super_finger",
                                chain=opp_fchain,
                                parameters=params,
                                force_connect_chain=True,
                                super_finger_primary_axis=primary_axis,
                                super_finger_roll_alignment=roll_align,
                            )
                        _ensure_collection_config(settings, f"Fingers.{opp_side}", "Extra", visible=True, bone_names=mirrored_all)
                        if self.enable_finger_ik:
                            _ensure_collection_config(settings, f"Fingers IK.{opp_side}", "IK", visible=False)
                        _ensure_collection_config(settings, f"Fingers Tweak.{opp_side}", "Tweak", visible=False)

            elif self.body_part == "EYE":
                configured_eyes = list(selected_sorted)
                if self.mirror_symmetric and side:
                    mirrored_all = [rerigify_mirror_name(b) for b in selected_sorted]
                    for opp_bone in mirrored_all:
                        if opp_bone in obj.data.bones and opp_bone not in configured_eyes:
                            configured_eyes.append(opp_bone)

                for eye_name in configured_eyes:
                    _set_bone_configuration(
                        settings,
                        eye_name,
                        "face.skin_eye",
                        parameters={},
                        skin_eye_compatibility=True,
                        eye_forward_axis=self.eye_forward_axis,
                        synthetic_lids_fallback=True,
                    )
                _ensure_collection_config(settings, "Face", "Special", visible=True, bone_names=configured_eyes)

        active_name = selected_sorted[0]
        settings.active_bone_index = next(
            (idx for idx, b in enumerate(settings.bones) if b.bone_name == active_name),
            0,
        )
        if settings.bones:
            active_item = settings.bones[settings.active_bone_index]
            prepare_parameter_carrier(context, obj, active_item, settings.active_bone_index)

        self.report(
            {"INFO"},
            format_iface(
                "Configured {part} for {count} bone(s)",
                part=self.body_part,
                count=len(selected_sorted),
            ),
        )
        return {"FINISHED"}


class RERIGIFY_OT_ArrangeCollectionUI(bpy.types.Operator):
    bl_idname = "re_rigify.arrange_collection_ui"
    bl_label = "Auto Arrange Collection UI"
    bl_description = "Arrange bone collections into standard categorized UI rows with empty spacing and generation visibility"
    bl_options = {"UNDO"}

    def execute(self, context):
        obj = active_armature(context)
        if not obj:
            self.report({"ERROR"}, iface_("Select an armature"))
            return {"CANCELLED"}
        settings = obj.data.re_rigify
        if not settings.collections:
            self.report({"WARNING"}, iface_("No collections to arrange"))
            return {"CANCELLED"}

        cols_data = [
            {
                "name": c.name,
                "ui_title": c.ui_title,
                "ui_row": c.ui_row,
                "row_order": c.row_order,
                "color_set": c.color_set_name,
                "visible_after_generation": c.visible_after_generation,
                "rules": [{"kind": r.kind, "pattern": r.pattern} for r in c.rules],
            }
            for c in settings.collections
        ]
        arranged = arrange_collection_layout(cols_data)
        arranged_by_name = {c["name"]: c for c in arranged}

        with suspend_collection_rename_updates():
            for item in settings.collections:
                data = arranged_by_name.get(item.name)
                if data:
                    item.ui_row = data["ui_row"]
                    item.row_order = data["row_order"]
                    item.ui_title = data["ui_title"]
                    if data.get("color_set"):
                        item.color_set_name = data["color_set"]
                    item.visible_after_generation = data["visible_after_generation"]

        _normalize_collection_orders(settings)
        self.report(
            {"INFO"},
            format_iface(
                "Arranged UI for {count} collection(s)",
                count=len(settings.collections),
            ),
        )
        return {"FINISHED"}


CLASSES = (
    RERIGIFY_OT_BoneAdd, RERIGIFY_OT_BoneRemove, RERIGIFY_OT_BoneMove,
    RERIGIFY_OT_BoneRuleAdd, RERIGIFY_OT_BoneRuleRemove,
    RERIGIFY_OT_BoneRuleMove,
    RERIGIFY_OT_ChainAddSelected, RERIGIFY_OT_ChainRemove, RERIGIFY_OT_ChainMove,
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
    RERIGIFY_OT_ApplyPreset,
    RERIGIFY_OT_Generate, RERIGIFY_OT_RemoveDrive,
    RERIGIFY_OT_QuickSetupBones, RERIGIFY_OT_ArrangeCollectionUI,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
