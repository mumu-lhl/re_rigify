import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy

import re_rigify
from re_rigify.blender_config import armature_to_payload, payload_to_armature
from re_rigify.compatibility import apply_compatibility_plan, build_compatibility_plan
from re_rigify.core import DEFAULT_COMPATIBILITY
from re_rigify.generate import (
    apply_collection_config,
    apply_generated_collection_visibility,
    generate_rig,
    validate_bone_parameters,
)
from re_rigify.operators import (
    select_only,
    synchronized_payload,
    validate_active,
)
from re_rigify.rules import cleanup_bone_rule_rows, sync_bone_rules
from re_rigify.drive import (
    DRIVE_MAP_PROPERTY,
    DRIVER_BONE_PREFIX,
    ROTATION_DRIVE_MAP_PROPERTY,
    connect_source_to_rig,
    remove_drive_constraints,
)
from re_rigify.ui import (
    _load_pending_parameter_carrier,
    _save_pre,
    flush_parameter_carrier,
    get_parameter_carrier,
    get_rule_parameter_carrier,
    prepare_parameter_carrier,
    prepare_rule_parameter_carrier,
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

    batch_settings = batch.data.re_rigify
    batch_settings.bones[1].collection_selected = True
    batch_settings.bones[2].collection_selected = True
    batch_settings.active_bone_index = 2
    assert bpy.ops.re_rigify.bone_move(direction=-1) == {"FINISHED"}
    assert [item.bone_name for item in batch_settings.bones] == ["three", "two", "one"]
    assert batch_settings.active_bone_index == 1
    assert [item.collection_selected for item in batch_settings.bones] == [True, True, False]

    assert bpy.ops.re_rigify.bone_move(direction=1) == {"FINISHED"}
    assert [item.bone_name for item in batch_settings.bones] == ["one", "three", "two"]
    assert batch_settings.active_bone_index == 2

    for item in batch_settings.bones:
        item.collection_selected = False
    assert bpy.ops.re_rigify.bone_move(direction=-1) == {"FINISHED"}
    assert [item.bone_name for item in batch_settings.bones] == ["one", "two", "three"]
    assert batch_settings.active_bone_index == 1
    assert get_parameter_carrier(
        batch,
        batch_settings.bones[1],
        1,
    ) is not None

    reference_source = make_armature("Reference Import", ["A", "B"])
    reference_payload = {
        "format": "re-rigify",
        "schema_version": 1,
        "bones": [{
            "bone_name": name,
            "rigify_type": "basic.super_copy",
            "chain_bones": [],
            "parameters": {
                "fk_layers_extra": True,
                "fk_coll_refs": ["FK"],
                "tweak_layers_extra": True,
                "tweak_coll_refs": ["Tweaks"],
            },
            "compatibility": DEFAULT_COMPATIBILITY,
        } for name in ("A", "B")],
        "collections": [
            {
                "name": "FK", "ui_title": "FK", "ui_row": 1, "row_order": 0,
                "color_set": "", "rules": [],
            },
            {
                "name": "Tweaks", "ui_title": "Tweaks", "ui_row": 1, "row_order": 1,
                "color_set": "", "rules": [],
            },
        ],
        "color_sets": [],
    }
    payload_to_armature(reference_source.data, reference_payload)
    flush_parameter_carrier()
    for item in reference_source.data.re_rigify.bones:
        parameters = json.loads(item.parameters_json)
        assert parameters["fk_coll_refs"] == ["FK"]
        assert parameters["tweak_coll_refs"] == ["Tweaks"]
    assert bpy.data.objects.get(re_rigify.ui.HELPER_NAME) is None
    reference_data = reference_source.data
    bpy.data.objects.remove(reference_source, do_unlink=True)
    bpy.data.armatures.remove(reference_data)

    chain_source = make_armature(
        "Chain Rule Source",
        ["Head", "HairA_00", "HairA_01", "HairB_00", "HairB_01", "HairB_02"],
    )
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = chain_source.data.edit_bones
    for root_name, x in (("HairA_00", 1.0), ("HairB_00", 2.0)):
        root = edit_bones[root_name]
        root.head = (x, 0, 0)
        root.tail = (x, 1, 0)
        root.parent = edit_bones["Head"]
    for child_name, parent_name, y in (
        ("HairA_01", "HairA_00", 1.0),
        ("HairB_01", "HairB_00", 1.0),
        ("HairB_02", "HairB_01", 2.0),
    ):
        child = edit_bones[child_name]
        child.head = (edit_bones[parent_name].tail)
        child.tail = (child.head.x, y + 1.0, child.head.z)
        child.parent = edit_bones[parent_name]
        child.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    chain_settings = chain_source.data.re_rigify
    chain_rule = chain_settings.bone_rules.add()
    chain_rule.rule_id = "hair"
    chain_rule.kind = "GLOB"
    chain_rule.pattern = "Hair*"
    chain_rule.rigify_type = "limbs.spline_tentacle"
    chain_rule.apply_as_chain = True
    legacy = chain_settings.bones.add()
    legacy.bone_name = "HairA_00"
    legacy.managed_rule_id = "hair"
    manual_claimed = chain_settings.bones.add()
    manual_claimed.bone_name = "HairB_00"
    manual_claimed.rigify_type = "basic.raw_copy"
    assert cleanup_bone_rule_rows(chain_source.data) == 2
    assert list(chain_settings.bones) == []
    assert not any(
        chain_source.data.bones[name].use_connect
        for name in ("HairA_01", "HairB_01", "HairB_02")
    )
    chain_canonical = synchronized_payload(
        chain_source, include_managed=False,
    )
    chain_resolved = synchronized_payload(
        chain_source, include_managed=True,
    )
    assert chain_canonical["bone_rules"][0]["apply_as_chain"] is True
    assert chain_canonical["bones"] == []
    assert [
        item["bone_name"] for item in chain_resolved["bones"]
    ] == ["HairA_00", "HairB_00"]
    assert [
        item["chain_bones"] for item in chain_resolved["bones"]
    ] == [
        ["HairA_00", "HairA_01"],
        ["HairB_00", "HairB_01", "HairB_02"],
    ]
    assert list(chain_settings.bones) == []
    chain_rig = chain_source.copy()
    chain_rig.data = chain_source.data.copy()
    bpy.context.scene.collection.objects.link(chain_rig)
    connect_source_to_rig(chain_source, chain_rig)
    assert all(
        chain_rig.data.bones[f"{DRIVER_BONE_PREFIX}{name}"].inherit_scale
        == "NONE"
        for name in (
            "HairA_00", "HairA_01",
            "HairB_00", "HairB_01", "HairB_02",
        )
    )
    assert (
        chain_rig.data.bones[f"{DRIVER_BONE_PREFIX}Head"].inherit_scale
        == "FULL"
    )
    remove_drive_constraints(chain_source)
    chain_rig_data = chain_rig.data
    bpy.data.objects.remove(chain_rig, do_unlink=True)
    bpy.data.armatures.remove(chain_rig_data)
    chain_data = chain_source.data
    bpy.data.objects.remove(chain_source, do_unlink=True)
    bpy.data.armatures.remove(chain_data)

    rule_source = make_armature(
        "Rule Source", ["Root", "Finger_Index", "Finger_Middle"],
    )
    rule_settings = rule_source.data.re_rigify
    rule = rule_settings.bone_rules.add()
    rule.rule_id = "fingers"
    rule.kind = "GLOB"
    rule.pattern = "Finger_*"
    rule.rigify_type = "basic.super_copy"
    rule.parameters_json = '{"make_control": true}'
    manual_root = rule_settings.bones.add()
    manual_root.bone_name = "Root"
    manual_root.rigify_type = "basic.raw_copy"
    assert sync_bone_rules(rule_source.data) == (0, 0, 0)
    assert [item.bone_name for item in rule_settings.bones] == ["Root"]
    carrier = prepare_rule_parameter_carrier(
        bpy.context, rule_source, rule, 0,
    )
    assert carrier is not None
    carrier.rigify_parameters.make_control = False
    flush_parameter_carrier()
    assert json.loads(rule.parameters_json)["make_control"] is False
    assert get_rule_parameter_carrier(rule_source, rule, 0) == carrier
    manual_carrier = prepare_parameter_carrier(
        bpy.context, rule_source, manual_root, 0,
    )
    assert get_parameter_carrier(rule_source, manual_root, 0) == manual_carrier
    assert get_rule_parameter_carrier(rule_source, rule, 0) == carrier
    assert manual_carrier.id_data != carrier.id_data
    collection = rule_settings.collections.add()
    collection.name = "Old FK"
    collection.last_valid_name = "Old FK"
    manual_root.parameters_json = json.dumps({
        "fk_coll_refs": ["Old FK"],
        "tweak_coll_refs": ["Old FK"],
    })
    rule.parameters_json = json.dumps({"fk_coll_refs": ["Old FK"]})
    collection.name = "Renamed FK"
    bone_parameters = json.loads(manual_root.parameters_json)
    assert bone_parameters["fk_coll_refs"] == ["Renamed FK"]
    assert bone_parameters["tweak_coll_refs"] == ["Renamed FK"]
    assert json.loads(rule.parameters_json)["fk_coll_refs"] == ["Renamed FK"]
    visible = rule_source.data.collections.new("Visible")
    hidden = rule_source.data.collections.new("Hidden")
    apply_generated_collection_visibility(rule_source, [
        {"name": "Visible", "visible_after_generation": True},
        {"name": "Hidden", "visible_after_generation": False},
    ])
    assert visible.is_visible
    assert not hidden.is_visible
    rule.rigify_type = "basic.raw_copy"
    rule.parameters_json = "{}"
    manual_root.collection_selected = True
    rule_settings.active_bone_index = 0
    rule.pattern = "Finger_Index"
    added, _updated, removed = sync_bone_rules(rule_source.data)
    assert (added, removed) == (0, 0)
    active_rule_bone = rule_settings.bones[rule_settings.active_bone_index]
    assert active_rule_bone.bone_name == "Root"
    assert active_rule_bone.collection_selected
    checked, errors = validate_active(bpy.context)
    assert checked == rule_source
    assert not errors
    assert not any(item.managed_rule_id for item in rule_settings.bones)
    canonical = synchronized_payload(rule_source, include_managed=False)
    resolved = synchronized_payload(rule_source, include_managed=True)
    assert [item["bone_name"] for item in canonical["bones"]] == ["Root"]
    assert [item["bone_name"] for item in resolved["bones"]] == [
        "Root", "Finger_Index",
    ]
    assert canonical["bone_rules"][0]["rule_id"] == "fingers"
    rule_import = make_armature(
        "Rule Import", ["Root", "Finger_Index", "Finger_Middle"],
    )
    payload_to_armature(rule_import.data, canonical)
    assert [
        item.bone_name for item in rule_import.data.re_rigify.bones
    ] == ["Root"]
    assert not any(
        item.managed_rule_id
        for item in rule_import.data.re_rigify.bones
    )
    rule_import_data = rule_import.data
    bpy.data.objects.remove(rule_import, do_unlink=True)
    bpy.data.armatures.remove(rule_import_data)
    bpy.context.view_layer.objects.active = rule_source
    rule_source.select_set(True)
    rule_data = rule_source.data
    bpy.data.objects.remove(rule_source, do_unlink=True)
    bpy.data.armatures.remove(rule_data)

    batch_data = batch.data
    bpy.data.objects.remove(batch, do_unlink=True)
    bpy.data.armatures.remove(batch_data)

    source = make_armature("Source", ["spine", "upper_arm.L", "upper_arm.R"])
    bpy.ops.object.mode_set(mode="EDIT")
    source.data.edit_bones["upper_arm.L"].head = source.data.edit_bones["spine"].tail
    source.data.edit_bones["upper_arm.L"].parent = source.data.edit_bones["spine"]
    source.data.edit_bones["upper_arm.L"].use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")
    payload = {
        "format": "re-rigify",
        "schema_version": 1,
        "bones": [{
            "bone_name": "spine",
            "rigify_type": "basic.raw_copy",
            "chain_bones": [],
            "parameters": {},
            "compatibility": DEFAULT_COMPATIBILITY,
        }],
        "bone_rules": [],
        "collections": [{
            "name": "Arms",
            "ui_title": "Arm Controls",
            "ui_row": 1,
            "row_order": 0,
            "color_set": "",
            "visible_after_generation": True,
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

    source_bind_matrix = source.pose.bones["spine"].matrix.copy()
    mapped, unmatched = connect_source_to_rig(source, duplicate)
    bpy.context.view_layer.update()
    assert mapped == len(source.pose.bones)
    assert unmatched == []
    assert not source.data.bones["upper_arm.L"].use_connect
    assert max(
        abs(source.pose.bones["spine"].matrix[row][column] - source_bind_matrix[row][column])
        for row in range(4)
        for column in range(4)
    ) < 1e-5
    duplicate.pose.bones["spine"].location.x = 0.25
    bpy.context.view_layer.update()
    assert max(
        abs(
            source.pose.bones["spine"].matrix[row][column]
            - duplicate.pose.bones[f"{DRIVER_BONE_PREFIX}spine"].matrix[row][column]
        )
        for row in range(4)
        for column in range(4)
    ) < 1e-5
    constraint = source.pose.bones["spine"].constraints[-1]
    assert constraint.name.startswith("Re-Rigify Drive")
    assert constraint.target == duplicate
    assert constraint.subtarget == f"{DRIVER_BONE_PREFIX}spine"
    assert constraint.owner_space == "WORLD"
    assert constraint.target_space == "WORLD"
    helper = duplicate.pose.bones[f"{DRIVER_BONE_PREFIX}spine"]
    assert helper.parent == duplicate.pose.bones["spine"]
    assert duplicate.data.bones[helper.name].inherit_scale == "FULL"
    assert not helper.constraints
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = None
    with bpy.context.temp_override(
        object=None, active_object=None, selected_objects=[]
    ):
        assert remove_drive_constraints(source) == mapped
        assert bpy.ops.re_rigify.remove_drive() == {"CANCELLED"}
    assert bpy.context.view_layer.objects.active is None
    assert source.data.bones["upper_arm.L"].use_connect
    duplicate.pose.bones["spine"].matrix_basis.identity()
    bpy.context.view_layer.update()
    duplicate[DRIVE_MAP_PROPERTY] = '{"spine": "upper_arm.L"}'
    connect_source_to_rig(source, duplicate)
    assert source.pose.bones["spine"].constraints[-1].subtarget == f"{DRIVER_BONE_PREFIX}spine"
    assert duplicate.pose.bones[f"{DRIVER_BONE_PREFIX}spine"].parent == duplicate.pose.bones[
        "upper_arm.L"
    ]
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
    _save_pre("")
    assert item.parameters_json != before
    assert bpy.data.objects.get(re_rigify.ui.HELPER_NAME) is None

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
    saved_refs = json.loads(ref_item.parameters_json)
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

    regen = make_armature("Regenerate Source", ["root"])
    regen_payload = {
        "format": "re-rigify",
        "schema_version": 1,
        "bones": [{
            "bone_name": "root",
            "rigify_type": "basic.raw_copy",
            "chain_bones": [],
            "parameters": {},
            "compatibility": DEFAULT_COMPATIBILITY,
        }],
        "collections": [{
            "name": "Main",
            "ui_title": "Main",
            "ui_row": 1,
            "row_order": 0,
            "color_set": "",
            "rules": [{"kind": "EXACT", "pattern": "root"}],
        }],
        "color_sets": [],
    }
    assert generate_rig(bpy.context, regen, regen_payload) is not None
    stale = regen.copy()
    stale.data = regen.data.copy()
    stale.name = "Regenerate Source_metarig.999"
    bpy.context.scene.collection.objects.link(stale)
    stale.re_rigify_source_armature = regen
    stale_name = stale.name
    regen.re_rigify_generated_rig = None
    regen.re_rigify_metarig = None
    select_only(bpy.context, stale)
    assert generate_rig(bpy.context, regen, regen_payload) is not None
    assert bpy.data.objects.get(stale_name) is None
finally:
    re_rigify.unregister()

print("RE_RIGIFY_INTEGRATION_OK")
