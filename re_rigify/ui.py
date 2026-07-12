"""3D View sidebar for Re-Rigify."""

from __future__ import annotations

import json

import bpy

from .rigify_adapter import apply_parameters, draw_parameters, parameter_json


HELPER_NAME = "__ReRigify_Parameter_Carrier__"


def ensure_parameter_carrier(context, source, item, index):
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
    key = f"{source.data.name}:{index}:{item.rigify_type}"
    if obj.get("re_rigify_key") != key:
        pose_bone.rigify_type = item.rigify_type
        apply_parameters(pose_bone.rigify_parameters, json.loads(item.parameters_json or "{}"))
        obj["re_rigify_key"] = key
    else:
        item.parameters_json = parameter_json(pose_bone)
    return pose_bone


def remove_parameter_carrier():
    obj = bpy.data.objects.get(HELPER_NAME)
    if obj:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            bpy.data.armatures.remove(data)


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
            bones_box.prop(item, "bone_name")
            bones_box.prop_search(item, "rigify_type", context.window_manager, "rigify_types", text="Rig Type")
            try:
                carrier = ensure_parameter_carrier(context, obj, item, settings.active_bone_index)
                draw_parameters(bones_box.column(), carrier)
            except Exception as exc:
                bones_box.label(text=f"Parameter UI unavailable: {exc}", icon="ERROR")

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
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    remove_parameter_carrier()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
