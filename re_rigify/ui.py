"""3D View sidebar for Re-Rigify."""

from __future__ import annotations

import json

import bpy

from .rigify_adapter import apply_parameters, draw_parameters, parameter_json


HELPER_NAME = "__ReRigify_Parameter_Carrier__"
_bound_armature_name = None
_bound_armature_pointer = 0
_bound_index = -1
_bound_bone_name = None
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
    try:
        if bpy.data.objects.get(source.name) != source or source.as_pointer() == 0:
            return None
    except ReferenceError:
        return None
    flush_parameter_carrier()
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
    settings = source.data.re_rigify
    managed_names = {collection.name for collection in settings.collections}
    for collection in list(obj.data.collections_all):
        if collection.name not in managed_names:
            obj.data.collections.remove(collection)
    from .generate import apply_collection_config
    apply_collection_config(obj, [{
        "name": collection.name,
        "ui_title": collection.ui_title,
        "ui_row": collection.ui_row,
        "row_order": collection.row_order,
        "rules": [{"kind": rule.kind, "pattern": rule.pattern} for rule in collection.rules],
    } for collection in settings.collections])
    pose_bone = obj.pose.bones[item.bone_name]
    key = _carrier_key(source, item, index)
    if obj.get("re_rigify_key") != key:
        pose_bone.rigify_type = item.rigify_type
        apply_parameters(pose_bone.rigify_parameters, json.loads(item.parameters_json or "{}"))
        obj["re_rigify_key"] = key
    global _bound_armature_name, _bound_armature_pointer, _bound_index
    global _bound_bone_name, _pending_binding
    _bound_armature_name = source.data.name
    _bound_armature_pointer = source.data.as_pointer()
    _bound_index = index
    _bound_bone_name = item.bone_name
    _pending_binding = None
    return pose_bone


def request_parameter_carrier(source, item, index):
    """Queue helper creation so Panel.draw never writes Blender ID data."""
    global _pending_binding
    try:
        _pending_binding = (
            source.name,
            source.as_pointer(),
            source.data.name,
            source.data.as_pointer(),
            index,
        )
    except ReferenceError:
        _pending_binding = None
        return
    if not bpy.app.timers.is_registered(_load_pending_parameter_carrier):
        bpy.app.timers.register(_load_pending_parameter_carrier, first_interval=0.0)


def _load_pending_parameter_carrier():
    global _pending_binding
    if _pending_binding is not None:
        object_name, object_pointer, armature_name, armature_pointer, index = _pending_binding
        _pending_binding = None
        try:
            source = bpy.data.objects.get(object_name)
            armature = bpy.data.armatures.get(armature_name)
            if (
                source is None or source.as_pointer() != object_pointer
                or armature is None or armature.as_pointer() != armature_pointer
                or source.type != "ARMATURE" or source.data != armature
            ):
                return None
            if index < len(armature.re_rigify.bones):
                item = armature.re_rigify.bones[index]
                if item.bone_name in armature.bones:
                    prepare_parameter_carrier(bpy.context, source, item, index)
        except ReferenceError:
            remove_parameter_carrier()
    return None


def flush_parameter_carrier():
    """Persist the active helper on explicit workflow events, without polling."""
    armature = bpy.data.armatures.get(_bound_armature_name) if _bound_armature_name else None
    if armature and armature.as_pointer() != _bound_armature_pointer:
        armature = None
    if armature is None and _bound_armature_name is not None:
        remove_parameter_carrier()
    elif armature is not None and _bound_index < len(armature.re_rigify.bones):
        item = armature.re_rigify.bones[_bound_index]
        helper = bpy.data.objects.get(HELPER_NAME)
        carrier = helper.pose.bones.get(_bound_bone_name) if helper and helper.pose else None
        if carrier:
            item.parameters_json = parameter_json(carrier)


def _save_pre(_filepath):
    flush_parameter_carrier()


def remove_parameter_carrier():
    global _bound_armature_name, _bound_armature_pointer, _bound_index
    global _bound_bone_name, _pending_binding
    obj = bpy.data.objects.get(HELPER_NAME)
    if obj:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            bpy.data.armatures.remove(data)
    _bound_armature_name = None
    _bound_armature_pointer = 0
    _bound_index = -1
    _bound_bone_name = None
    _pending_binding = None


class RERIGIFY_UL_Bones(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "collection_selected", text="")
        layout.label(text=item.bone_name, icon="BONE_DATA", translate=False)
        layout.label(text=item.rigify_type or "No type", translate=False)


class RERIGIFY_UL_Collections(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.name or "Unnamed", icon="GROUP_BONE", translate=False)
        layout.label(text=f"Row {item.ui_row} / {item.row_order}", translate=False)


class RERIGIFY_UL_Rules(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.kind, translate=False)
        layout.label(text=item.pattern or "Empty", translate=False)


class RERIGIFY_UL_ColorSets(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "normal", text="")
        layout.label(text=item.name or "Unnamed", translate=False)


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
        row = bones_box.row(align=True)
        op = row.operator("re_rigify.mark_all_bones", text="All")
        op.selected = True
        op = row.operator("re_rigify.mark_all_bones", text="None")
        op.selected = False
        if settings.collections:
            target = settings.collections[settings.active_collection_index].name or "Unnamed"
            bones_box.operator(
                "re_rigify.collection_add_marked_bones",
                text=f"Add to Collection: {target}",
                icon="GROUP_BONE",
            )
        else:
            row = bones_box.row()
            row.enabled = False
            row.operator("re_rigify.collection_add_marked_bones", text="Create a Collection First")
        if settings.bones:
            item = settings.bones[settings.active_bone_index]
            bones_box.prop_search(item, "bone_name", obj.data, "bones", text="Bone")
            refresh_rigify_types(context)
            bones_box.prop_search(item, "rigify_type", context.window_manager, "rigify_types", text="Rig Type")
            bones_box.operator("re_rigify.mirror_bone_config", icon="MOD_MIRROR")
            bones_box.operator("re_rigify.copy_parameters_to_selected", icon="DUPLICATE")
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
            buttons.separator()
            buttons.operator("re_rigify.collection_duplicate", text="", icon="DUPLICATE")
            up = buttons.row(align=True)
            up.enabled = settings.active_collection_index > 0
            op = up.operator("re_rigify.collection_move", text="", icon="TRIA_UP")
            op.direction = -1
            down = buttons.row(align=True)
            down.enabled = settings.active_collection_index < len(settings.collections) - 1
            op = down.operator("re_rigify.collection_move", text="", icon="TRIA_DOWN")
            op.direction = 1
        if settings.collections:
            collection = settings.collections[settings.active_collection_index]
            collection_box.prop(collection, "name")
            collection_box.prop(collection, "ui_title")
            row = collection_box.row(align=True)
            row.prop(collection, "ui_row")
            row.prop(collection, "row_order")
            collection_box.prop_search(
                collection, "color_set_name", settings, "color_sets", text="Color Set"
            )
            collection_box.operator("re_rigify.collection_add_viewport_bones", icon="BONE_DATA")
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

        if settings.collections:
            layout_box = collection_box.box()
            layout_box.label(text="Rigify UI Layout")
            active_index = settings.active_collection_index
            visible_rows = [item.ui_row for item in settings.collections if item.ui_row > 0]
            last_row = max(visible_rows, default=0)
            for row_id in range(1, last_row + 2):
                row = layout_box.row(align=True)
                row_items = sorted(
                    (
                        (index, item) for index, item in enumerate(settings.collections)
                        if item.ui_row == row_id
                    ),
                    key=lambda pair: (pair[1].row_order, pair[1].name),
                )
                grid = row.grid_flow(
                    row_major=True, columns=max(1, len(row_items)), even_columns=True,
                )
                if row_items:
                    for index, item in row_items:
                        title = item.ui_title or item.name or "Unnamed"
                        if item.color_set_name:
                            title = f"{title} · {item.color_set_name}"
                        op = grid.operator(
                            "re_rigify.collection_select", text=title,
                            icon="COLOR" if item.color_set_name else "GROUP_BONE",
                            depress=index == active_index,
                            translate=False,
                        )
                        op.index = index
                else:
                    grid.label(text="Empty Row")
                controls = row.row(align=True)
                op = controls.operator(
                    "re_rigify.collection_set_ui_row", text="", icon="TRIA_LEFT"
                )
                op.index = active_index
                op.row = row_id
                if row_id <= last_row:
                    op = controls.operator(
                        "re_rigify.collection_edit_ui_row", text="", icon="ADD"
                    )
                    op.row = row_id
                    op.add = True
                else:
                    controls.label(text="", icon="BLANK1")
                if (not row_items or row_id > 1) and row_id <= last_row:
                    op = controls.operator(
                        "re_rigify.collection_edit_ui_row", text="", icon="REMOVE"
                    )
                    op.row = row_id
                    op.add = False
                else:
                    controls.label(text="", icon="BLANK1")

            active_collection = settings.collections[active_index]
            move = layout_box.row(align=True)
            move.enabled = active_collection.ui_row > 0
            op = move.operator("re_rigify.collection_move_in_row", text="Move Left", icon="TRIA_LEFT")
            op.direction = -1
            op = move.operator("re_rigify.collection_move_in_row", text="Move Right", icon="TRIA_RIGHT")
            op.direction = 1
            op = move.operator("re_rigify.collection_set_ui_row", text="Hide", icon="X")
            op.index = active_index
            op.row = 0

            hidden = [
                (index, item) for index, item in enumerate(settings.collections) if item.ui_row == 0
            ]
            if hidden:
                hidden_box = layout_box.box()
                hidden_box.label(text="Hidden Collections")
                grid = hidden_box.grid_flow(row_major=True, columns=2, even_columns=True)
                for index, item in hidden:
                    op = grid.operator(
                        "re_rigify.collection_select", text=item.ui_title or item.name or "Unnamed",
                        depress=index == active_index,
                        translate=False,
                    )
                    op.index = index

        color_box = layout.box()
        color_box.label(text="Rigify Color Sets")
        row = color_box.row()
        row.template_list(
            "RERIGIFY_UL_ColorSets", "", settings, "color_sets",
            settings, "active_color_index", rows=3,
        )
        buttons = row.column(align=True)
        buttons.operator("re_rigify.color_set_add", text="", icon="ADD")
        buttons.operator("re_rigify.color_set_remove", text="", icon="REMOVE")
        color_box.operator("re_rigify.color_set_add_defaults", icon="COLOR")
        if settings.color_sets:
            color = settings.color_sets[settings.active_color_index]
            color_box.prop(color, "name")
            row = color_box.row(align=True)
            row.prop(color, "normal")
            row.prop(color, "select")
            row.prop(color, "active")
            color_box.prop(color, "standard_colors_lock")

        row = layout.row(align=True)
        row.operator("re_rigify.import_config", text="Import", icon="IMPORT")
        row.operator("re_rigify.export_config", text="Export", icon="EXPORT")
        layout.operator("re_rigify.validate", icon="CHECKMARK")
        layout.operator("re_rigify.generate", text="Generate & Connect Rigify Rig", icon="ARMATURE_DATA")
        if obj.re_rigify_generated_rig:
            drive_box = layout.box()
            drive_box.label(text=f"Driving from: {obj.re_rigify_generated_rig.name}", icon="CONSTRAINT_BONE")
            drive_box.operator("re_rigify.remove_drive", icon="X")
        if settings.validation_message:
            box = layout.box()
            for line in settings.validation_message.splitlines():
                box.label(text=line, icon="INFO")


CLASSES = (
    RERIGIFY_UL_Bones, RERIGIFY_UL_Collections, RERIGIFY_UL_Rules,
    RERIGIFY_UL_ColorSets, RERIGIFY_PT_Main,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if _save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_save_pre)


def unregister():
    flush_parameter_carrier()
    if bpy.app.timers.is_registered(_load_pending_parameter_carrier):
        bpy.app.timers.unregister(_load_pending_parameter_carrier)
    if _save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_save_pre)
    remove_parameter_carrier()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
