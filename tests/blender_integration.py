import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy

import re_rigify
from re_rigify.blender_config import armature_to_payload, payload_to_armature
from re_rigify.compatibility import apply_compatibility_plan, build_compatibility_plan
from re_rigify.core import DEFAULT_COMPATIBILITY
from re_rigify.generate import apply_collection_config, validate_bone_parameters
from re_rigify.operators import select_only
from re_rigify.drive import (
    DRIVE_MAP_PROPERTY,
    ROTATION_DRIVE_MAP_PROPERTY,
    connect_source_to_rig,
    remove_drive_constraints,
)
from re_rigify.ui import (
    _load_pending_parameter_carrier,
    flush_parameter_carrier,
    get_parameter_carrier,
    prepare_parameter_carrier,
    refresh_rigify_types,
    request_parameter_carrier,
)


def make_armature(name, bones):
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for index, name in enumerate(bones):
        bone = data.edit_bones.new(name)
        bone.head = (0, 0, index)
        bone.tail = (0, 0, index + 0.5)
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


bpy.ops.preferences.addon_enable(module="rigify")
re_rigify.register()
try:
    batch = make_armature("Batch Add", ["one", "two", "three"])
    bpy.ops.object.mode_set(mode="EDIT")
    for bone in batch.data.edit_bones:
        bone.select = bone.name in {"one", "three"}
        bone.select_head = bone.select
        bone.select_tail = bone.select
    batch.data.edit_bones.active = batch.data.edit_bones["three"]
    assert bpy.ops.re_rigify.bone_add() == {"FINISHED"}
    assert [item.bone_name for item in batch.data.re_rigify.bones] == ["one", "three"]
    assert batch.data.re_rigify.active_bone_index == 1

    bpy.ops.object.mode_set(mode="POSE")
    for bone in batch.pose.bones:
        bone.select = bone.name == "two"
    batch.data.bones.active = batch.data.bones["two"]
    assert bpy.ops.re_rigify.bone_add() == {"FINISHED"}
    assert [item.bone_name for item in batch.data.re_rigify.bones] == ["one", "three", "two"]
    assert batch.data.re_rigify.active_bone_index == 2
    bpy.ops.object.mode_set(mode="OBJECT")
    batch_data = batch.data
    bpy.data.objects.remove(batch, do_unlink=True)
    bpy.data.armatures.remove(batch_data)

    source = make_armature("Source", ["spine", "upper_arm.L", "upper_arm.R"])
    payload = {
        "format": "re-rigify",
        "schema_version": 1,
        "bones": [{
            "bone_name": "spine",
            "rigify_type": "basic.raw_copy",
            "parameters": {},
            "compatibility": DEFAULT_COMPATIBILITY,
        }],
        "collections": [{
            "name": "Arms",
            "ui_title": "Arm Controls",
            "ui_row": 1,
            "row_order": 0,
            "color_set": "",
            "rules": [{"kind": "GLOB", "pattern": "upper_arm.*"}],
        }],
        "color_sets": [],
    }
    payload_to_armature(source.data, payload)
    assert armature_to_payload(source.data) == payload

    finger_source = make_armature(
        "Finger Source", ["Wrist_R", "Thumb_01_R", "Thumb_02_R", "Thumb_03_R"]
    )
    bpy.ops.object.mode_set(mode="EDIT")
    finger_source.data.edit_bones["Thumb_01_R"].parent = finger_source.data.edit_bones["Wrist_R"]
    finger_source.data.edit_bones["Thumb_02_R"].parent = finger_source.data.edit_bones["Thumb_01_R"]
    finger_source.data.edit_bones["Thumb_03_R"].parent = finger_source.data.edit_bones["Thumb_02_R"]
    bpy.ops.object.mode_set(mode="OBJECT")
    finger_metarig = finger_source.copy()
    finger_metarig.data = finger_source.data.copy()
    bpy.context.scene.collection.objects.link(finger_metarig)
    select_only(bpy.context, finger_metarig)
    finger_plan = build_compatibility_plan(finger_metarig, [{
        "bone_name": "Thumb_01_R",
        "rigify_type": "limbs.super_finger",
        "compatibility": {**DEFAULT_COMPATIBILITY, "force_connect_chain": True},
    }])
    apply_compatibility_plan(finger_metarig, finger_plan)
    assert finger_metarig.data.bones["Thumb_02_R"].use_connect
    assert finger_metarig.data.bones["Thumb_03_R"].use_connect
    assert not finger_source.data.bones["Thumb_02_R"].use_connect
    assert not finger_source.data.bones["Thumb_03_R"].use_connect
    for temp in (finger_metarig, finger_source):
        temp_data = temp.data
        bpy.data.objects.remove(temp, do_unlink=True)
        bpy.data.armatures.remove(temp_data)
    select_only(bpy.context, source)

    settings = source.data.re_rigify
    settings.bones[0].collection_selected = True
    second = settings.bones.add()
    second.bone_name = "upper_arm.L"
    second.rigify_type = "basic.raw_copy"
    second.collection_selected = True
    settings.active_collection_index = 0
    assert bpy.ops.re_rigify.collection_add_marked_bones() == {"FINISHED"}
    exact_rules = {
        rule.pattern for rule in settings.collections[0].rules if rule.kind == "EXACT"
    }
    assert exact_rules == {"spine", "upper_arm.L"}
    assert not settings.bones[0].collection_selected
    assert not settings.bones[1].collection_selected

    settings.bones[0].parameters_json = '{"relink_constraints": false}'
    settings.bones[1].rigify_type = "basic.super_copy"
    settings.bones[1].collection_selected = True
    settings.active_bone_index = 0
    assert bpy.ops.re_rigify.copy_parameters_to_selected() == {"FINISHED"}
    assert settings.bones[1].rigify_type == "basic.raw_copy"
    assert settings.bones[1].parameters_json == settings.bones[0].parameters_json

    settings.active_collection_index = 0
    bpy.context.view_layer.objects.active = source
    bpy.ops.object.mode_set(mode="EDIT")
    for bone in source.data.edit_bones:
        bone.select = False
        bone.select_head = False
        bone.select_tail = False
    source.data.edit_bones["upper_arm.R"].select = True
    assert bpy.ops.re_rigify.collection_add_viewport_bones() == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    assert {
        rule.pattern for rule in settings.collections[0].rules if rule.kind == "EXACT"
    } == {"upper_arm.R"}

    settings.active_collection_index = 0
    assert bpy.ops.re_rigify.collection_duplicate() == {"FINISHED"}
    copied_collection = settings.collections[1]
    assert copied_collection.name == "Arms.001"
    assert copied_collection.ui_title == settings.collections[0].ui_title
    assert copied_collection.color_set_name == settings.collections[0].color_set_name
    assert [(rule.kind, rule.pattern) for rule in copied_collection.rules] == [
        (rule.kind, rule.pattern) for rule in settings.collections[0].rules
    ]
    assert copied_collection.row_order == settings.collections[0].row_order + 1
    assert bpy.ops.re_rigify.collection_move(direction=-1) == {"FINISHED"}
    assert settings.collections[0].name == "Arms.001"
    assert bpy.ops.re_rigify.collection_move(direction=1) == {"FINISHED"}
    assert settings.collections[1].name == "Arms.001"
    assert bpy.ops.re_rigify.collection_remove() == {"FINISHED"}

    second_collection = settings.collections.add()
    second_collection.name = "Secondary"
    second_collection.ui_row = 1
    second_collection.row_order = 1
    settings.active_collection_index = 1
    assert bpy.ops.re_rigify.collection_move_in_row(direction=-1) == {"FINISHED"}
    assert second_collection.row_order == 0
    assert bpy.ops.re_rigify.collection_set_ui_row(index=1, row=2) == {"FINISHED"}
    assert second_collection.ui_row == 2
    assert bpy.ops.re_rigify.collection_edit_ui_row(row=2, add=True) == {"FINISHED"}
    assert second_collection.ui_row == 3

    duplicate = source.copy()
    duplicate.data = source.data.copy()
    bpy.context.scene.collection.objects.link(duplicate)
    select_only(bpy.context, duplicate)
    assert bpy.context.view_layer.objects.active == duplicate
    assert list(bpy.context.selected_objects) == [duplicate]
    apply_collection_config(duplicate, payload["collections"])
    collection = duplicate.data.collections_all["Arms"]
    assert collection.rigify_ui_row == 1
    assert collection.rigify_ui_title == "Arm Controls"
    assert {bone.name for bone in collection.bones} == {"upper_arm.L", "upper_arm.R"}

    mapped, unmatched = connect_source_to_rig(source, duplicate)
    assert mapped == len(source.pose.bones)
    assert unmatched == []
    constraint = source.pose.bones["spine"].constraints[-1]
    assert constraint.name.startswith("Re-Rigify Drive")
    assert constraint.target == duplicate
    assert constraint.subtarget == "spine"
    assert constraint.owner_space == "LOCAL"
    assert constraint.target_space == "LOCAL_OWNER_ORIENT"
    assert remove_drive_constraints(source) == mapped
    duplicate[DRIVE_MAP_PROPERTY] = '{"spine": "upper_arm.L"}'
    connect_source_to_rig(source, duplicate)
    assert source.pose.bones["spine"].constraints[-1].subtarget == "upper_arm.L"
    remove_drive_constraints(source)
    duplicate[ROTATION_DRIVE_MAP_PROPERTY] = '{"spine": "upper_arm.L"}'
    connect_source_to_rig(source, duplicate)
    constraint = source.pose.bones["spine"].constraints[-1]
    assert constraint.type == "COPY_ROTATION"
    assert constraint.owner_space == "POSE"
    assert constraint.target_space == "POSE"
    remove_drive_constraints(source)

    bpy.context.view_layer.objects.active = source
    item = source.data.re_rigify.bones[0]
    refresh_rigify_types(bpy.context)
    assert "basic.raw_copy" in {item.name for item in bpy.context.window_manager.rigify_types}

    carrier = prepare_parameter_carrier(bpy.context, source, item, 0)
    assert carrier.name == "spine"
    assert bpy.context.view_layer.objects.active == source
    assert get_parameter_carrier(source, item, 0) == carrier
    before = item.parameters_json
    carrier.rigify_parameters.relink_constraints = not carrier.rigify_parameters.relink_constraints
    flush_parameter_carrier()
    assert item.parameters_json != before

    ref_item = settings.bones[1]
    ref_item.rigify_type = "limbs.arm"
    ref_carrier = prepare_parameter_carrier(bpy.context, source, ref_item, 1)
    arms = ref_carrier.id_data.data.collections_all["Arms"]
    ref_carrier.rigify_parameters.fk_layers_extra = True
    ref_carrier.rigify_parameters.tweak_layers_extra = True
    with bpy.context.temp_override(
        object=ref_carrier.id_data,
        active_object=ref_carrier.id_data,
        active_pose_bone=ref_carrier,
    ):
        assert bpy.ops.pose.rigify_collection_ref_add(prop_name="fk_coll_refs") == {"FINISHED"}
        assert bpy.ops.pose.rigify_collection_ref_add(prop_name="tweak_coll_refs") == {"FINISHED"}
    ref_carrier.rigify_parameters.fk_coll_refs[-1].set_collection(arms)
    ref_carrier.rigify_parameters.tweak_coll_refs[-1].set_collection(arms)
    flush_parameter_carrier()
    saved_refs = __import__("json").loads(ref_item.parameters_json)
    assert saved_refs["fk_coll_refs"] == ["Arms"]
    assert saved_refs["tweak_coll_refs"] == ["Arms"]
    re_rigify.ui.remove_parameter_carrier()
    restored = prepare_parameter_carrier(bpy.context, source, ref_item, 1)
    assert [ref.name for ref in restored.rigify_parameters.fk_coll_refs] == ["Arms"]
    assert [ref.name for ref in restored.rigify_parameters.tweak_coll_refs] == ["Arms"]

    re_rigify.ui.remove_parameter_carrier()
    request_parameter_carrier(source, item, 0)
    _load_pending_parameter_carrier()
    assert get_parameter_carrier(source, item, 0) is not None

    removed = source.copy()
    removed.data = source.data.copy()
    bpy.context.scene.collection.objects.link(removed)
    removed_settings = removed.data.re_rigify
    removed_settings.bones.clear()
    removed_item = removed_settings.bones.add()
    removed_item.bone_name = removed.data.bones[0].name
    removed_item.rigify_type = "basic.raw_copy"
    prepare_parameter_carrier(bpy.context, removed, removed_item, 0)
    removed_data = removed.data
    bpy.data.objects.remove(removed, do_unlink=True)
    bpy.data.armatures.remove(removed_data)
    flush_parameter_carrier()
    assert re_rigify.ui._bound_armature_name is None

    pending = source.copy()
    pending.data = source.data.copy()
    bpy.context.scene.collection.objects.link(pending)
    pending_settings = pending.data.re_rigify
    pending_settings.bones.clear()
    pending_item = pending_settings.bones.add()
    pending_item.bone_name = pending.data.bones[0].name
    pending_item.rigify_type = "basic.raw_copy"
    request_parameter_carrier(pending, pending_item, 0)
    pending_data = pending.data
    bpy.data.objects.remove(pending, do_unlink=True)
    bpy.data.armatures.remove(pending_data)
    assert _load_pending_parameter_carrier() is None

    errors = validate_bone_parameters(bpy.context, source, [{
        "bone_name": "spine",
        "rigify_type": "basic.raw_copy",
        "parameters": {"definitely_not_a_rigify_parameter": True},
    }])
    assert len(errors) == 1
    assert "unknown" in errors[0]
finally:
    re_rigify.unregister()

print("RE_RIGIFY_INTEGRATION_OK")
