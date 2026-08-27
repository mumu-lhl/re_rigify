"""3D View sidebar for Re-Rigify."""

from __future__ import annotations

import json

import bpy

from .core import (
    ConfigError,
    EXPLICIT_CHAIN_MIN_LENGTHS,
    preview_bone_rule,
    resolve_bone_rules,
)
from .rigify_adapter import (
    RigifyParameterLayout,
    apply_parameters,
    draw_parameters,
    parameter_json,
)
from .translations import format_iface, iface_


HELPER_NAME = "__ReRigify_Parameter_Carrier__"
RULE_HELPER_NAME = "__ReRigify_Rule_Parameter_Carrier__"
_bound_armature_name = None
_bound_armature_pointer = 0
_bound_kind = None
_bound_key = None
_bound_source_bone_name = None
_bound_bindings = {}
_pending_binding = None


def refresh_rigify_types(context):
    """Populate Rigify's search collection exactly as its native panel does."""
    from rigify.ui import build_type_list
    build_type_list(context, context.window_manager.rigify_types)


def _carrier_key(source, target_kind, target_key, bone_name, rigify_type):
    return (
        f"{source.data.name}:{target_kind}:{target_key}:"
        f"{bone_name}:{rigify_type}"
    )


def _parameter_carrier_name(target_kind):
    return RULE_HELPER_NAME if target_kind == "RULE" else HELPER_NAME


def _get_parameter_carrier(
    source, target_kind, target_key, source_bone_name, rigify_type,
):
    obj = bpy.data.objects.get(_parameter_carrier_name(target_kind))
    if (
        obj is None
        or obj.get("re_rigify_source")
        != f"{source.data.name}:{len(source.data.bones)}"
    ):
        return None
    if obj.get("re_rigify_key") != _carrier_key(
        source, target_kind, target_key, source_bone_name, rigify_type,
    ):
        return None
    return obj.pose.bones.get(source_bone_name) if obj.pose else None


def get_parameter_carrier(source, item, index):
    return _get_parameter_carrier(
        source, "BONE", index, item.bone_name, item.rigify_type,
    )


def _rule_source_bone(source, rule_index):
    from .rules import armature_rule_topology, rule_dicts

    rules = rule_dicts(source.data.re_rigify)
    parents, aligned_edges = armature_rule_topology(source.data)
    preview = preview_bone_rule(
        source.data.bones.keys(),
        rules,
        rules[rule_index]["rule_id"],
        parents,
        aligned_edges,
    )
    return preview["bone_names"][0]


def get_rule_parameter_carrier(source, rule, rule_index):
    try:
        source_bone_name = _rule_source_bone(source, rule_index)
    except (ConfigError, IndexError, StopIteration, json.JSONDecodeError):
        return None
    return _get_parameter_carrier(
        source, "RULE", rule.rule_id, source_bone_name, rule.rigify_type,
    )


def _prepare_parameter_carrier(
    context, source, target, target_kind, target_key, source_bone_name,
):
    """Create/sync the helper from an operator or RNA update, never from Panel.draw."""
    try:
        if bpy.data.objects.get(source.name) != source or source.as_pointer() == 0:
            return None
    except ReferenceError:
        return None
    flush_parameter_carrier(target_kind)
    helper_name = _parameter_carrier_name(target_kind)
    obj = bpy.data.objects.get(helper_name)
    source_key = f"{source.data.name}:{len(source.data.bones)}"
    if obj is not None and (
        obj.get("re_rigify_source") != source_key
        or source_bone_name not in obj.pose.bones
    ):
        _remove_parameter_carrier(target_kind)
        obj = None
    if obj is None:
        armature = source.data.copy()
        armature.name = helper_name
        obj = bpy.data.objects.new(helper_name, armature)
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
        "visible_after_generation": collection.visible_after_generation,
        "rules": [{"kind": rule.kind, "pattern": rule.pattern} for rule in collection.rules],
    } for collection in settings.collections])
    pose_bone = obj.pose.bones[source_bone_name]
    key = _carrier_key(
        source, target_kind, target_key, source_bone_name, target.rigify_type,
    )
    if obj.get("re_rigify_key") != key:
        pose_bone.rigify_type = target.rigify_type
        apply_parameters(
            pose_bone.rigify_parameters,
            json.loads(target.parameters_json or "{}"),
        )
        obj["re_rigify_key"] = key
    global _pending_binding
    _bound_bindings[target_kind] = (
        source.data.name,
        source.data.as_pointer(),
        str(target_key),
        source_bone_name,
    )
    _sync_legacy_binding(target_kind)
    _pending_binding = None
    return pose_bone


def prepare_parameter_carrier(context, source, item, index):
    return _prepare_parameter_carrier(
        context, source, item, "BONE", index, item.bone_name,
    )


def prepare_rule_parameter_carrier(context, source, rule, rule_index):
    try:
        source_bone_name = _rule_source_bone(source, rule_index)
    except (ConfigError, IndexError, StopIteration, json.JSONDecodeError):
        return None
    return _prepare_parameter_carrier(
        context, source, rule, "RULE", rule.rule_id, source_bone_name,
    )


def request_parameter_carrier(source, item, index):
    """Queue helper creation so Panel.draw never writes Blender ID data."""
    global _pending_binding
    try:
        _pending_binding = (
            source.name,
            source.as_pointer(),
            source.data.name,
            source.data.as_pointer(),
            "BONE",
            str(index),
            item.bone_name,
        )
    except ReferenceError:
        _pending_binding = None
        return
    if not bpy.app.timers.is_registered(_load_pending_parameter_carrier):
        bpy.app.timers.register(_load_pending_parameter_carrier, first_interval=0.0)


def request_rule_parameter_carrier(source, rule, rule_index):
    global _pending_binding
    try:
        source_bone_name = _rule_source_bone(source, rule_index)
        _pending_binding = (
            source.name,
            source.as_pointer(),
            source.data.name,
            source.data.as_pointer(),
            "RULE",
            rule.rule_id,
            source_bone_name,
        )
    except (
        ConfigError, IndexError, StopIteration, ReferenceError,
        json.JSONDecodeError,
    ):
        _pending_binding = None
        return False
    if not bpy.app.timers.is_registered(_load_pending_parameter_carrier):
        bpy.app.timers.register(_load_pending_parameter_carrier, first_interval=0.0)
    return True


def _load_pending_parameter_carrier():
    global _pending_binding
    if _pending_binding is not None:
        (
            object_name, object_pointer, armature_name, armature_pointer,
            target_kind, target_key, source_bone_name,
        ) = _pending_binding
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
            settings = armature.re_rigify
            target = None
            if target_kind == "BONE":
                index = int(target_key)
                if 0 <= index < len(settings.bones):
                    target = settings.bones[index]
            elif target_kind == "RULE":
                target = next(
                    (
                        rule for rule in settings.bone_rules
                        if rule.rule_id == target_key
                    ),
                    None,
                )
            if target is not None and source_bone_name in armature.bones:
                _prepare_parameter_carrier(
                    bpy.context, source, target, target_kind,
                    target_key, source_bone_name,
                )
        except ReferenceError:
            remove_parameter_carrier()
    return None


def _sync_legacy_binding(preferred_kind=None):
    global _bound_armature_name, _bound_armature_pointer
    global _bound_kind, _bound_key, _bound_source_bone_name
    kind = (
        preferred_kind
        if preferred_kind in _bound_bindings
        else next(reversed(_bound_bindings), None)
    )
    if kind is None:
        _bound_armature_name = None
        _bound_armature_pointer = 0
        _bound_kind = None
        _bound_key = None
        _bound_source_bone_name = None
        return
    (
        _bound_armature_name,
        _bound_armature_pointer,
        _bound_key,
        _bound_source_bone_name,
    ) = _bound_bindings[kind]
    _bound_kind = kind


def _remove_parameter_carrier(target_kind):
    obj = bpy.data.objects.get(_parameter_carrier_name(target_kind))
    if obj:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            bpy.data.armatures.remove(data)
    _bound_bindings.pop(target_kind, None)
    _sync_legacy_binding()


def flush_parameter_carrier(target_kind=None):
    """Persist the active helper on explicit workflow events, without polling."""
    kinds = (
        [target_kind]
        if target_kind is not None
        else list(_bound_bindings)
    )
    for kind in kinds:
        binding = _bound_bindings.get(kind)
        if binding is None:
            continue
        armature_name, armature_pointer, target_key, source_bone_name = binding
        armature = bpy.data.armatures.get(armature_name)
        if armature and armature.as_pointer() != armature_pointer:
            armature = None
        if armature is None:
            _remove_parameter_carrier(kind)
            continue
        settings = armature.re_rigify
        target = None
        if kind == "BONE":
            index = int(target_key)
            if 0 <= index < len(settings.bones):
                target = settings.bones[index]
        elif kind == "RULE":
            target = next(
                (
                    rule for rule in settings.bone_rules
                    if rule.rule_id == target_key
                ),
                None,
            )
        helper = bpy.data.objects.get(_parameter_carrier_name(kind))
        carrier = (
            helper.pose.bones.get(source_bone_name)
            if helper and helper.pose else None
        )
        if target is not None and carrier is not None:
            target.parameters_json = parameter_json(carrier)


def _save_pre(_filepath):
    flush_parameter_carrier()
    remove_parameter_carrier()


def remove_parameter_carrier():
    global _pending_binding
    for target_kind in ("BONE", "RULE"):
        _remove_parameter_carrier(target_kind)
    _pending_binding = None


class RERIGIFY_UL_Bones(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "collection_selected", text="")
        layout.label(text=item.bone_name, icon="BONE_DATA", translate=False)
        layout.label(
            text=item.rigify_type or iface_("No type"),
            translate=False,
        )

    def filter_items(self, _context, data, property_name):
        from .rules import rule_dicts

        items = getattr(data, property_name)
        claimed = set()
        if data.bone_rules:
            try:
                claimed = set(resolve_bone_rules(
                    data.id_data.bones.keys(),
                    rule_dicts(data),
                ))
            except (ConfigError, ValueError, json.JSONDecodeError):
                pass
        flags = [
            (
                0
                if item.managed_rule_id or item.bone_name in claimed
                else self.bitflag_filter_item
            )
            for item in items
        ]
        return flags, []


class RERIGIFY_UL_BoneRules(bpy.types.UIList):
    def draw_item(
        self, _context, layout, _data, item, _icon,
        _active_data, _active_propname, _index,
    ):
        layout.label(
            text=item.pattern or iface_("Empty"),
            icon="FILTER",
            translate=False,
        )
        layout.label(
            text=item.rigify_type or iface_("No type"),
            translate=False,
        )


class RERIGIFY_UL_BoneRulePreview(bpy.types.UIList):
    def draw_item(
        self, _context, layout, _data, item, _icon,
        _active_data, _active_propname, _index,
    ):
        layout.label(
            text=item.name, icon="BONE_DATA", translate=False,
        )

    def filter_items(self, _context, data, property_name):
        from .rules import active_bone_rule_preview

        items = getattr(data, property_name)
        try:
            preview = active_bone_rule_preview(data)
        except (ConfigError, ValueError, json.JSONDecodeError):
            return [0] * len(items), []
        rank = {
            name: index
            for index, name in enumerate(preview["bone_names"])
        }
        flags = [
            self.bitflag_filter_item if item.name in rank else 0
            for item in items
        ]
        desired = sorted(
            range(len(items)),
            key=lambda index: (
                items[index].name not in rank,
                rank.get(items[index].name, index),
            ),
        )
        new_order = [0] * len(items)
        for new_index, old_index in enumerate(desired):
            new_order[old_index] = new_index
        return flags, new_order


class RERIGIFY_UL_ChainBones(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(
            text=item.bone_name or iface_("No bone"),
            icon="BONE_DATA",
            translate=False,
        )


class RERIGIFY_UL_Collections(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(
            text=item.name or iface_("Unnamed"),
            icon="GROUP_BONE",
            translate=False,
        )
        layout.label(
            text=format_iface(
                "Row {row} / {order}",
                row=item.ui_row,
                order=item.row_order,
            ),
            translate=False,
        )


class RERIGIFY_UL_Rules(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        kind = item.bl_rna.properties["kind"].enum_items[item.kind].name
        layout.label(text=iface_(kind), translate=False)
        layout.label(
            text=item.pattern or iface_("Empty"),
            translate=False,
        )


class RERIGIFY_UL_ColorSets(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "normal", text="")
        layout.label(
            text=item.name or iface_("Unnamed"),
            translate=False,
        )


def _active_parameter_refs(context, prop_name):
    obj = context.object
    if obj is None or obj.type != "ARMATURE":
        return None
    if obj.name == RULE_HELPER_NAME:
        target_kind = "RULE"
    elif obj.name == HELPER_NAME:
        target_kind = "BONE"
    else:
        target_kind = _bound_kind
    binding = _bound_bindings.get(target_kind)
    if binding is None:
        return None
    armature_name, armature_pointer, _target_key, source_bone_name = binding
    helper = bpy.data.objects.get(_parameter_carrier_name(target_kind))
    if obj != helper and (
        obj.data.name != armature_name
        or obj.data.as_pointer() != armature_pointer
    ):
        return None
    carrier = (
        helper.pose.bones.get(source_bone_name)
        if helper and helper.pose else None
    )
    if carrier is None:
        return None
    from rigify.utils.layers import is_collection_ref_list_prop
    refs = getattr(carrier.rigify_parameters, prop_name, None)
    return refs if refs is not None and is_collection_ref_list_prop(refs) else None


class RERIGIFY_OT_parameter_collection_ref_add(bpy.types.Operator):
    bl_idname = "re_rigify.parameter_collection_ref_add"
    bl_label = "Add Bone Collection Reference"
    bl_options = {"UNDO", "INTERNAL"}

    prop_name: bpy.props.StringProperty(name="Property Name")

    def execute(self, context):
        refs = _active_parameter_refs(context, self.prop_name)
        if refs is None:
            return {"CANCELLED"}
        refs.add()
        flush_parameter_carrier()
        return {"FINISHED"}


class RERIGIFY_OT_parameter_collection_ref_remove(bpy.types.Operator):
    bl_idname = "re_rigify.parameter_collection_ref_remove"
    bl_label = "Remove Bone Collection Reference"
    bl_options = {"UNDO", "INTERNAL"}

    prop_name: bpy.props.StringProperty(name="Property Name")
    index: bpy.props.IntProperty(name="Entry Index")

    def execute(self, context):
        refs = _active_parameter_refs(context, self.prop_name)
        if refs is None or not 0 <= self.index < len(refs):
            return {"CANCELLED"}
        refs.remove(self.index)
        flush_parameter_carrier()
        return {"FINISHED"}


class _RERIGIFY_PT_Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Re-Rigify"

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == "ARMATURE"


class RERIGIFY_PT_Main(_RERIGIFY_PT_Base, bpy.types.Panel):
    bl_label = "Re-Rigify"
    bl_idname = "RERIGIFY_PT_main"

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj is None or obj.type != "ARMATURE":
            layout.label(text=iface_("Select an armature"), icon="ARMATURE_DATA")
            return
        settings = obj.data.re_rigify

        summary = layout.row(align=True)
        summary.label(
            text=format_iface(
                "{count} Bones",
                count=len(settings.bones),
            ),
            icon="BONE_DATA",
            translate=False,
        )
        summary.label(
            text=format_iface(
                "{count} Collections",
                count=len(settings.collections),
            ),
            icon="GROUP_BONE",
            translate=False,
        )

        preset_box = layout.box()
        preset_box.label(text="Built-in Preset", icon="PRESET")
        row = preset_box.row(align=True)
        row.prop(context.window_manager, "re_rigify_preset", text="")
        op = row.operator("re_rigify.apply_preset", text="Apply", icon="CHECKMARK")
        op.preset = context.window_manager.re_rigify_preset
        op.generate = False
        op = preset_box.operator(
            "re_rigify.apply_preset",
            text="Apply & Generate",
            icon="ARMATURE_DATA",
        )
        op.preset = context.window_manager.re_rigify_preset
        op.generate = True

        layout.operator(
            "re_rigify.generate", text="Generate & Connect Rigify Rig", icon="ARMATURE_DATA"
        )
        if obj.re_rigify_generated_rig:
            row = layout.row(align=True)
            row.label(
                text=format_iface(
                    "Driven by {rig_name}",
                    rig_name=obj.re_rigify_generated_rig.name,
                ),
                icon="CONSTRAINT_BONE",
                translate=False,
            )
            row.operator("re_rigify.remove_drive", text="", icon="X")


class RERIGIFY_PT_BoneRules(_RERIGIFY_PT_Base, bpy.types.Panel):
    bl_label = "Bone Matching Rules"
    bl_idname = "RERIGIFY_PT_bone_rules"
    bl_parent_id = "RERIGIFY_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        from .rules import active_bone_rule_preview

        layout = self.layout
        settings = context.object.data.re_rigify
        row = layout.row()
        row.template_list(
            "RERIGIFY_UL_BoneRules", "",
            settings, "bone_rules",
            settings, "active_bone_rule_index",
            rows=4,
        )
        buttons = row.column(align=True)
        buttons.operator("re_rigify.bone_rule_add", text="", icon="ADD")
        buttons.operator("re_rigify.bone_rule_remove", text="", icon="REMOVE")
        up = buttons.operator(
            "re_rigify.bone_rule_move", text="", icon="TRIA_UP",
        )
        up.direction = -1
        down = buttons.operator(
            "re_rigify.bone_rule_move", text="", icon="TRIA_DOWN",
        )
        down.direction = 1
        if settings.bone_rules:
            rule = settings.bone_rules[settings.active_bone_rule_index]
            layout.prop(rule, "kind")
            layout.prop(rule, "pattern")
            layout.prop(rule, "apply_as_chain")
            if rule.apply_as_chain:
                layout.label(
                    text="Only chain roots receive the Rigify type",
                    icon="LINKED",
                )
            refresh_rigify_types(context)
            layout.prop_search(
                rule, "rigify_type",
                context.window_manager, "rigify_types",
                text="Rig Type",
            )
            preview_box = layout.box()
            preview_box.label(text="Effective Matches", icon="VIEWZOOM")
            try:
                preview = active_bone_rule_preview(context.object.data)
            except (
                ConfigError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                preview_box.label(
                    text=str(exc), icon="ERROR", translate=False,
                )
            else:
                if rule.apply_as_chain:
                    preview_box.label(
                        text=format_iface(
                            "{bone_count} bones / {chain_count} chains",
                            bone_count=len(preview["bone_names"]),
                            chain_count=preview["chain_count"],
                        ),
                        icon="LINKED",
                        translate=False,
                    )
                else:
                    preview_box.label(
                        text=format_iface(
                            "{bone_count} bones",
                            bone_count=len(preview["bone_names"]),
                        ),
                        icon="BONE_DATA",
                        translate=False,
                    )
                preview_box.template_list(
                    "RERIGIFY_UL_BoneRulePreview", "",
                    context.object.data, "bones",
                    settings, "active_bone_rule_preview_index",
                    rows=5,
                )


class RERIGIFY_PT_BoneRuleParameters(
    _RERIGIFY_PT_Base, bpy.types.Panel,
):
    bl_label = "Rule Parameters"
    bl_idname = "RERIGIFY_PT_bone_rule_parameters"
    bl_parent_id = "RERIGIFY_PT_bone_rules"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.object
        settings = obj.data.re_rigify
        if not settings.bone_rules:
            layout.label(text="No bone rule", icon="INFO")
            return
        index = settings.active_bone_rule_index
        rule = settings.bone_rules[index]
        carrier = get_rule_parameter_carrier(obj, rule, index)
        if carrier is None:
            if not request_rule_parameter_carrier(obj, rule, index):
                layout.label(text="Rule matches no bones", icon="ERROR")
            else:
                layout.label(
                    text="Loading Rigify parameters…", icon="TIME",
                )
            return
        try:
            parameter_layout = RigifyParameterLayout(layout.column())
            draw_parameters(parameter_layout, carrier)
            layout.label(
                text="Parameters save automatically", icon="CHECKMARK",
            )
        except Exception as exc:
            layout.label(
                text=format_iface(
                    "Parameter UI unavailable: {error}",
                    error=exc,
                ),
                icon="ERROR",
                translate=False,
            )


class RERIGIFY_PT_Bones(_RERIGIFY_PT_Base, bpy.types.Panel):
    bl_label = "Bone Setup"
    bl_idname = "RERIGIFY_PT_bones"
    bl_parent_id = "RERIGIFY_PT_main"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        settings = obj.data.re_rigify

        row = layout.row()
        row.template_list("RERIGIFY_UL_Bones", "", settings, "bones", settings, "active_bone_index", rows=4)
        buttons = row.column(align=True)
        buttons.operator("re_rigify.bone_add", text="", icon="ADD")
        buttons.operator("re_rigify.bone_remove", text="", icon="REMOVE")
        up = buttons.operator("re_rigify.bone_move", text="", icon="TRIA_UP")
        up.direction = -1
        down = buttons.operator("re_rigify.bone_move", text="", icon="TRIA_DOWN")
        down.direction = 1
        row = layout.row(align=True)
        op = row.operator("re_rigify.mark_all_bones", text="All")
        op.selected = True
        op = row.operator("re_rigify.mark_all_bones", text="None")
        op.selected = False
        if settings.bones:
            item = settings.bones[settings.active_bone_index]
            managed = bool(item.managed_rule_id)
            layout.use_property_split = True
            layout.use_property_decorate = False
            fields = layout.column()
            fields.enabled = not managed
            fields.prop_search(
                item, "bone_name", obj.data, "bones", text="Bone",
            )
            refresh_rigify_types(context)
            fields.prop_search(
                item, "rigify_type", context.window_manager, "rigify_types", text="Rig Type"
            )
            if managed:
                layout.label(text="Managed by a bone rule", icon="LOCKED")
            if not managed and item.rigify_type in EXPLICIT_CHAIN_MIN_LENGTHS:
                chain = layout.box()
                chain.label(text="Explicit Chain")
                row = chain.row()
                row.template_list(
                    "RERIGIFY_UL_ChainBones", "", item, "chain_bones",
                    item, "active_chain_index", rows=3,
                )
                buttons = row.column(align=True)
                buttons.operator("re_rigify.chain_add_selected", text="", icon="ADD")
                buttons.operator("re_rigify.chain_remove", text="", icon="REMOVE")
                up = buttons.row(align=True)
                up.enabled = item.active_chain_index > 0
                op = up.operator("re_rigify.chain_move", text="", icon="TRIA_UP")
                op.direction = -1
                down = buttons.row(align=True)
                down.enabled = item.active_chain_index < len(item.chain_bones) - 1
                op = down.operator("re_rigify.chain_move", text="", icon="TRIA_DOWN")
                op.direction = 1
            actions = layout.row(align=True)
            actions.enabled = not managed
            actions.operator("re_rigify.mirror_bone_config", icon="MOD_MIRROR")
            actions.operator("re_rigify.copy_parameters_to_selected", icon="DUPLICATE")
            if (
                not managed
                and item.rigify_type
                in {
                    "limbs.arm",
                    "limbs.simple_tentacle",
                    "limbs.super_finger",
                    "spines.basic_tail",
                    "face.skin_eye",
                }
            ):
                compatibility = layout.box()
                compatibility.label(text="Compatibility")
                compatibility.use_property_split = True
                compatibility.use_property_decorate = False
                if item.rigify_type == "limbs.arm":
                    compatibility.prop(item, "roll_bones_enabled")
                    if item.roll_bones_enabled:
                        compatibility.prop_search(
                            item, "upper_arm_roll_bone", obj.data, "bones"
                        )
                        compatibility.prop_search(
                            item, "forearm_roll_bone", obj.data, "bones"
                        )
                if item.rigify_type in {
                    "limbs.simple_tentacle",
                    "limbs.super_finger",
                    "spines.basic_tail",
                }:
                    compatibility.prop(item, "force_connect_chain")
                if item.rigify_type == "limbs.super_finger":
                    compatibility.prop(item, "super_finger_primary_axis")
                    compatibility.prop(item, "super_finger_roll_alignment")
                if item.rigify_type == "face.skin_eye":
                    compatibility.prop(item, "skin_eye_compatibility")
                    if item.skin_eye_compatibility:
                        compatibility.prop(item, "eye_forward_axis")
                        compatibility.prop(item, "upper_lid_pattern")
                        compatibility.prop(item, "lower_lid_pattern")
                        compatibility.prop(item, "synthetic_lids_fallback")


class RERIGIFY_PT_BoneParameters(_RERIGIFY_PT_Base, bpy.types.Panel):
    bl_label = "Active Bone Parameters"
    bl_idname = "RERIGIFY_PT_bone_parameters"
    bl_parent_id = "RERIGIFY_PT_bones"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.object
        settings = obj.data.re_rigify
        if not settings.bones:
            layout.label(text="No configured bone", icon="INFO")
            return
        item = settings.bones[settings.active_bone_index]
        if item.managed_rule_id:
            layout.label(text="Managed by a bone rule", icon="LOCKED")
            return
        carrier = get_parameter_carrier(obj, item, settings.active_bone_index)
        if carrier is not None:
            try:
                parameter_layout = RigifyParameterLayout(layout.column())
                draw_parameters(parameter_layout, carrier)
                layout.label(text="Parameters save automatically", icon="CHECKMARK")
            except Exception as exc:
                layout.label(
                    text=format_iface(
                        "Parameter UI unavailable: {error}",
                        error=exc,
                    ),
                    icon="ERROR",
                    translate=False,
                )
        else:
            request_parameter_carrier(obj, item, settings.active_bone_index)
            layout.label(text="Loading Rigify parameters…", icon="TIME")


class RERIGIFY_PT_Collections(_RERIGIFY_PT_Base, bpy.types.Panel):
    bl_label = "Bone Collections"
    bl_idname = "RERIGIFY_PT_collections"
    bl_parent_id = "RERIGIFY_PT_main"

    def draw(self, context):
        layout = self.layout
        settings = context.object.data.re_rigify

        row = layout.row()
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
            layout.use_property_split = True
            layout.use_property_decorate = False
            layout.prop(collection, "name")
            layout.prop(collection, "visible_after_generation")
            layout.prop(collection, "ui_title")
            layout.prop_search(
                collection, "color_set_name", settings, "color_sets", text="Color Set"
            )
            membership = layout.row(align=True)
            membership.operator(
                "re_rigify.collection_add_viewport_bones",
                text="Add Viewport Selection",
                icon="BONE_DATA",
            )
            membership.operator(
                "re_rigify.collection_add_marked_bones",
                text="Add Checked Configs",
                icon="CHECKBOX_HLT",
            )


class RERIGIFY_PT_CollectionRules(_RERIGIFY_PT_Base, bpy.types.Panel):
    bl_label = "Collection Rules"
    bl_idname = "RERIGIFY_PT_collection_rules"
    bl_parent_id = "RERIGIFY_PT_collections"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.object.data.re_rigify
        if not settings.collections:
            layout.label(text="No collection", icon="INFO")
            return
        collection = settings.collections[settings.active_collection_index]
        row = layout.row()
        row.template_list(
            "RERIGIFY_UL_Rules", "", collection, "rules",
            collection, "active_rule_index", rows=4,
        )
        buttons = row.column(align=True)
        buttons.operator("re_rigify.rule_add", text="", icon="ADD")
        buttons.operator("re_rigify.rule_remove", text="", icon="REMOVE")
        if collection.rules:
            rule = collection.rules[collection.active_rule_index]
            row = layout.row(align=True)
            row.prop(rule, "kind", text="")
            row.prop(rule, "pattern", text="")


class RERIGIFY_PT_Layout(_RERIGIFY_PT_Base, bpy.types.Panel):
    bl_label = "Rig UI Layout"
    bl_idname = "RERIGIFY_PT_layout"
    bl_parent_id = "RERIGIFY_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.object.data.re_rigify
        if not settings.collections:
            layout.label(text="No collection", icon="INFO")
            return
        active_index = settings.active_collection_index
        active_collection = settings.collections[active_index]
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(active_collection, "ui_row", text="Active Row")
        layout.prop(active_collection, "row_order", text="Order in Row")
        visible_rows = [item.ui_row for item in settings.collections if item.ui_row > 0]
        last_row = max(visible_rows, default=0)
        for row_id in range(1, last_row + 2):
            row = layout.row(align=True)
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

        move = layout.row(align=True)
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
            box = layout.box()
            box.label(text="Hidden Collections")
            grid = box.grid_flow(row_major=True, columns=2, even_columns=True)
            for index, item in hidden:
                op = grid.operator(
                    "re_rigify.collection_select", text=item.ui_title or item.name or "Unnamed",
                    depress=index == active_index,
                    translate=False,
                )
                op.index = index


class RERIGIFY_PT_Colors(_RERIGIFY_PT_Base, bpy.types.Panel):
    bl_label = "Color Sets"
    bl_idname = "RERIGIFY_PT_colors"
    bl_parent_id = "RERIGIFY_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.object.data.re_rigify
        row = layout.row()
        row.template_list(
            "RERIGIFY_UL_ColorSets", "", settings, "color_sets",
            settings, "active_color_index", rows=3,
        )
        buttons = row.column(align=True)
        buttons.operator("re_rigify.color_set_add", text="", icon="ADD")
        buttons.operator("re_rigify.color_set_remove", text="", icon="REMOVE")
        layout.operator("re_rigify.color_set_add_defaults", icon="COLOR")
        layout.prop_search(
            settings, "root_color_set_name", settings, "color_sets",
            text="Root Control",
        )
        if settings.color_sets:
            color = settings.color_sets[settings.active_color_index]
            layout.use_property_split = True
            layout.use_property_decorate = False
            layout.prop(color, "name")
            row = layout.row(align=True)
            row.prop(color, "normal")
            row.prop(color, "select")
            row.prop(color, "active")
            layout.prop(color, "standard_colors_lock")


class RERIGIFY_PT_Configuration(_RERIGIFY_PT_Base, bpy.types.Panel):
    bl_label = "Configuration"
    bl_idname = "RERIGIFY_PT_configuration"
    bl_parent_id = "RERIGIFY_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.object.data.re_rigify

        row = layout.row(align=True)
        row.operator("re_rigify.import_config", text="Import", icon="IMPORT")
        row.operator("re_rigify.export_config", text="Export", icon="EXPORT")
        layout.operator("re_rigify.validate", icon="CHECKMARK")
        if settings.validation_message:
            box = layout.box()
            for line in settings.validation_message.splitlines():
                box.label(text=line, icon="INFO")


CLASSES = (
    RERIGIFY_UL_Bones, RERIGIFY_UL_BoneRules,
    RERIGIFY_UL_BoneRulePreview, RERIGIFY_UL_ChainBones,
    RERIGIFY_UL_Collections, RERIGIFY_UL_Rules,
    RERIGIFY_UL_ColorSets,
    RERIGIFY_OT_parameter_collection_ref_add,
    RERIGIFY_OT_parameter_collection_ref_remove,
    RERIGIFY_PT_Main,
    RERIGIFY_PT_BoneRules, RERIGIFY_PT_BoneRuleParameters,
    RERIGIFY_PT_Bones, RERIGIFY_PT_BoneParameters,
    RERIGIFY_PT_Collections, RERIGIFY_PT_CollectionRules,
    RERIGIFY_PT_Layout, RERIGIFY_PT_Colors, RERIGIFY_PT_Configuration,
)


def register():
    from .presets import preset_enum_items

    bpy.types.WindowManager.re_rigify_preset = bpy.props.EnumProperty(
        name="Built-in Preset",
        description="Built-in Re-Rigify configuration preset",
        items=preset_enum_items,
    )
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
    if hasattr(bpy.types.WindowManager, "re_rigify_preset"):
        del bpy.types.WindowManager.re_rigify_preset
