"""3D View sidebar for Re-Rigify."""

from __future__ import annotations

import json

import bpy

from .rigify_adapter import apply_parameters, draw_parameters, parameter_json


HELPER_NAME = "__ReRigify_Parameter_Carrier__"
SYNC_INTERVAL = 0.25
_sync_enabled = False
_bound_armature_name = None
_bound_armature_pointer = 0
_bound_index = -1
_last_parameter_json = None
_pending_binding = None


def refresh_rigify_types(context):
    """Populate Rigify's search collection exactly as its native panel does."""
    from rigify.ui import build_type_list
    build_type_list(context, context.window_manager.rigify_types)


def _carrier_key(source, item, index):
    return f"{source.data.name}:{index}:{item.bone_name}:{item.rigify_type}"


def get_parameter_carrier(source, item, index):
    obj = bpy.data.objects.get(HELPER_NAME)
    if obj is None or obj.get("re_rigify_source") != f"{source.data.name}:{len(source.data.bones)}":
        return None
    if obj.get("re_rigify_key") != _carrier_key(source, item, index):
        return None
    return obj.pose.bones.get(item.bone_name) if obj.pose else None


def prepare_parameter_carrier(context, source, item, index):
    """Create/sync the helper from an operator or RNA update, never from Panel.draw."""
    obj = bpy.data.objects.get(HELPER_NAME)
    source_key = f"{source.data.name}:{len(source.data.bones)}"
    if obj is not None and (obj.get("re_rigify_source") != source_key or item.bone_name not in obj.pose.bones):
        remove_parameter_carrier()
        obj = None
    if obj is None:
        armature = source.data.copy()
        armature.name = HELPER_NAME
        obj = bpy.data.objects.new(HELPER_NAME, armature)
        context.scene.collection.objects.link(obj)
        obj.hide_render = True
        obj.hide_set(True)
        obj["re_rigify_source"] = source_key
        context.view_layer.update()
    pose_bone = obj.pose.bones[item.bone_name]
    key = _carrier_key(source, item, index)
    if obj.get("re_rigify_key") != key:
        pose_bone.rigify_type = item.rigify_type
        apply_parameters(pose_bone.rigify_parameters, json.loads(item.parameters_json or "{}"))
        obj["re_rigify_key"] = key
    global _bound_armature_name, _bound_armature_pointer, _bound_index
    global _last_parameter_json, _pending_binding
    _bound_armature_name = source.data.name
    _bound_armature_pointer = source.data.as_pointer()
    _bound_index = index
    _last_parameter_json = parameter_json(pose_bone)
    _pending_binding = None
    return pose_bone


def request_parameter_carrier(source, item, index):
    """Queue helper creation so Panel.draw never writes Blender ID data."""
    global _pending_binding
    _pending_binding = (source.data.name, source.data.as_pointer(), index)


def _parameter_sync_timer():
    global _pending_binding, _last_parameter_json
    if not _sync_enabled:
        return None

    if _pending_binding is not None:
        armature_name, armature_pointer, index = _pending_binding
        armature = bpy.data.armatures.get(armature_name)
        if armature and armature.as_pointer() != armature_pointer:
            armature = None
        source = next(
            (obj for obj in bpy.data.objects if armature and obj.type == "ARMATURE" and obj.data == armature),
            None,
        )
        if armature and source and index < len(armature.re_rigify.bones):
            item = armature.re_rigify.bones[index]
            if item.bone_name in armature.bones:
                prepare_parameter_carrier(bpy.context, source, item, index)
        _pending_binding = None

    armature = bpy.data.armatures.get(_bound_armature_name) if _bound_armature_name else None
    if armature and armature.as_pointer() != _bound_armature_pointer:
        armature = None
    if armature is None and _bound_armature_name is not None:
        remove_parameter_carrier()
    elif armature is not None and _bound_index < len(armature.re_rigify.bones):
        item = armature.re_rigify.bones[_bound_index]
        source = next(
            (obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj.data == armature),
            None,
        )
        if source:
            carrier = get_parameter_carrier(source, item, _bound_index)
            if carrier:
                current = parameter_json(carrier)
                if current != _last_parameter_json:
                    item.parameters_json = current
                    _last_parameter_json = current
    return SYNC_INTERVAL


def remove_parameter_carrier():
    global _bound_armature_name, _bound_armature_pointer, _bound_index
    global _last_parameter_json, _pending_binding
    obj = bpy.data.objects.get(HELPER_NAME)
    if obj:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            bpy.data.armatures.remove(data)
    _bound_armature_name = None
    _bound_armature_pointer = 0
    _bound_index = -1
    _last_parameter_json = None
    _pending_binding = None


class RERIGIFY_UL_Bones(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.bone_name, icon="BONE_DATA")
        layout.label(text=item.rigify_type or "No type")


class RERIGIFY_UL_Collections(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.name or "Unnamed", icon="GROUP_BONE")
        layout.label(text=f"Row {item.ui_row} / {item.row_order}")


class RERIGIFY_UL_Rules(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.kind)
        layout.label(text=item.pattern or "Empty")


class RERIGIFY_PT_Main(bpy.types.Panel):
    bl_label = "Re-Rigify"
    bl_idname = "RERIGIFY_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Re-Rigify"

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == "ARMATURE"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        settings = obj.data.re_rigify

        bones_box = layout.box()
        bones_box.label(text="Rigify Bone Types")
        row = bones_box.row()
        row.template_list("RERIGIFY_UL_Bones", "", settings, "bones", settings, "active_bone_index", rows=4)
        buttons = row.column(align=True)
        buttons.operator("re_rigify.bone_add", text="", icon="ADD")
        buttons.operator("re_rigify.bone_remove", text="", icon="REMOVE")
        if settings.bones:
            item = settings.bones[settings.active_bone_index]
            bones_box.prop_search(item, "bone_name", obj.data, "bones", text="Bone")
            if obj.mode == "OBJECT":
                bones_box.label(text="Pose/Edit Mode enables the bone eyedropper", icon="INFO")
            refresh_rigify_types(context)
            bones_box.prop_search(item, "rigify_type", context.window_manager, "rigify_types", text="Rig Type")
            carrier = get_parameter_carrier(obj, item, settings.active_bone_index)
            if carrier is not None:
                try:
                    draw_parameters(bones_box.column(), carrier)
                    bones_box.label(text="Parameters save automatically", icon="CHECKMARK")
                except Exception as exc:
                    bones_box.label(text=f"Parameter UI unavailable: {exc}", icon="ERROR")
            else:
                request_parameter_carrier(obj, item, settings.active_bone_index)
                bones_box.label(text="Loading Rigify parameters…", icon="TIME")

        collection_box = layout.box()
        collection_box.label(text="Bone Collections and Rig UI")
        row = collection_box.row()
        row.template_list(
            "RERIGIFY_UL_Collections", "", settings, "collections",
            settings, "active_collection_index", rows=3,
        )
        buttons = row.column(align=True)
        buttons.operator("re_rigify.collection_add", text="", icon="ADD")
        buttons.operator("re_rigify.collection_remove", text="", icon="REMOVE")
        if settings.collections:
            collection = settings.collections[settings.active_collection_index]
            collection_box.prop(collection, "name")
            collection_box.prop(collection, "ui_title")
            row = collection_box.row(align=True)
            row.prop(collection, "ui_row")
            row.prop(collection, "row_order")
            row = collection_box.row()
            row.template_list(
                "RERIGIFY_UL_Rules", "", collection, "rules",
                collection, "active_rule_index", rows=3,
            )
            buttons = row.column(align=True)
            buttons.operator("re_rigify.rule_add", text="", icon="ADD")
            buttons.operator("re_rigify.rule_remove", text="", icon="REMOVE")
            if collection.rules:
                rule = collection.rules[collection.active_rule_index]
                row = collection_box.row(align=True)
                row.prop(rule, "kind", text="")
                row.prop(rule, "pattern", text="")

        row = layout.row(align=True)
        row.operator("re_rigify.import_config", text="Import", icon="IMPORT")
        row.operator("re_rigify.export_config", text="Export", icon="EXPORT")
        layout.operator("re_rigify.validate", icon="CHECKMARK")
        layout.operator("re_rigify.generate", icon="ARMATURE_DATA")
        if settings.validation_message:
            box = layout.box()
            for line in settings.validation_message.splitlines():
                box.label(text=line, icon="INFO")


CLASSES = (RERIGIFY_UL_Bones, RERIGIFY_UL_Collections, RERIGIFY_UL_Rules, RERIGIFY_PT_Main)


def register():
    global _sync_enabled
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _sync_enabled = True
    if not bpy.app.timers.is_registered(_parameter_sync_timer):
        bpy.app.timers.register(_parameter_sync_timer, first_interval=0.0, persistent=True)


def unregister():
    global _sync_enabled
    _sync_enabled = False
    if bpy.app.timers.is_registered(_parameter_sync_timer):
        bpy.app.timers.unregister(_parameter_sync_timer)
    remove_parameter_carrier()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
