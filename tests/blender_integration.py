import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy

import re_rigify
from re_rigify.blender_config import armature_to_payload, payload_to_armature
from re_rigify.generate import apply_collection_config, validate_bone_parameters
from re_rigify.ui import ensure_parameter_carrier


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
    source = make_armature("Source", ["spine", "upper_arm.L", "upper_arm.R"])
    payload = {
        "format": "re-rigify",
        "schema_version": 1,
        "bones": [{
            "bone_name": "spine",
            "rigify_type": "basic.raw_copy",
            "parameters": {},
        }],
        "collections": [{
            "name": "Arms",
            "ui_title": "Arm Controls",
            "ui_row": 1,
            "row_order": 0,
            "rules": [{"kind": "GLOB", "pattern": "upper_arm.*"}],
        }],
    }
    payload_to_armature(source.data, payload)
    assert armature_to_payload(source.data) == payload

    duplicate = source.copy()
    duplicate.data = source.data.copy()
    bpy.context.scene.collection.objects.link(duplicate)
    apply_collection_config(duplicate, payload["collections"])
    collection = duplicate.data.collections_all["Arms"]
    assert collection.rigify_ui_row == 1
    assert collection.rigify_ui_title == "Arm Controls"
    assert {bone.name for bone in collection.bones} == {"upper_arm.L", "upper_arm.R"}

    bpy.context.view_layer.objects.active = source
    item = source.data.re_rigify.bones[0]
    carrier = ensure_parameter_carrier(bpy.context, source, item, 0)
    assert carrier.name == "spine"
    assert bpy.context.view_layer.objects.active == source

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
