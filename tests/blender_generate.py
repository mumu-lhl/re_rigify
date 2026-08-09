import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy

import re_rigify
from re_rigify.generate import generate_rig


bpy.ops.preferences.addon_enable(module="rigify")
re_rigify.register()
try:
    armature = bpy.data.armatures.new("Source")
    source = bpy.data.objects.new("Source", armature)
    bpy.context.scene.collection.objects.link(source)
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.edit_bones.new("root")
    bone.tail = (0, 0, 1)
    bpy.ops.object.mode_set(mode="OBJECT")
    payload = {
        "format": "re-rigify",
        "schema_version": 1,
        "bones": [{"bone_name": "root", "rigify_type": "basic.raw_copy", "parameters": {}}],
        "collections": [{
            "name": "Controls", "ui_title": "Controls", "ui_row": 1, "row_order": 0,
            "rules": [{"kind": "EXACT", "pattern": "root"}],
        }],
        "root_color_set": "Root",
        "color_sets": [{
            "name": "Root",
            "normal": [0.2, 0.8, 0.1],
            "select": [0.9, 0.5, 0.1],
            "active": [1.0, 0.0, 0.0],
            "standard_colors_lock": False,
        }],
    }

    generated = generate_rig(bpy.context, source, payload)
    root_color = generated.pose.bones["root"].color
    assert root_color.palette == "CUSTOM"
    assert all(abs(actual - expected) < 0.01 for actual, expected in zip(
        root_color.custom.normal, (0.2, 0.8, 0.1)
    ))
    assert all(abs(actual - expected) < 0.01 for actual, expected in zip(
        root_color.custom.select, (0.9, 0.5, 0.1)
    ))
    assert all(abs(actual - expected) < 0.01 for actual, expected in zip(
        root_color.custom.active, (1.0, 0.0, 0.0)
    ))
    script_prefix = f"{generated.name}_ui.py"
    assert [
        text.name for text in bpy.data.texts
        if text.name == script_prefix or text.name.startswith(script_prefix + ".")
    ] == [script_prefix]
    extra_metarig = source.copy()
    extra_metarig.data = source.data.copy()
    extra_metarig.name = "Source_metarig.999"
    extra_metarig_name = extra_metarig.name
    extra_metarig.re_rigify_source_armature = source
    bpy.context.scene.collection.objects.link(extra_metarig)
    source.re_rigify_generated_rig = None
    source.re_rigify_metarig = None
    regenerated = generate_rig(bpy.context, source, payload)

    assert generated is not None
    assert generated.type == "ARMATURE"
    assert generated != source
    assert source.pose.bones["root"].rigify_type == ""
    assert regenerated == generated
    assert source.re_rigify_generated_rig == generated
    assert source.re_rigify_metarig is None
    assert extra_metarig_name not in bpy.data.objects
    assert bpy.data.objects.get("Source_metarig") is None
    scripts = [
        text.name for text in bpy.data.texts
        if text.name == script_prefix or text.name.startswith(script_prefix + ".")
    ]
    assert scripts == [script_prefix]
finally:
    if re_rigify.ui.HELPER_NAME in bpy.data.objects:
        re_rigify.ui.remove_parameter_carrier()
    re_rigify.unregister()

print("RE_RIGIFY_GENERATE_OK")
