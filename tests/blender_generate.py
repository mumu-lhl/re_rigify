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
    }

    generated = generate_rig(bpy.context, source, payload)
    first_metarig = source.re_rigify_metarig
    source.re_rigify_generated_rig = None
    source.re_rigify_metarig = None
    regenerated = generate_rig(bpy.context, source, payload)

    assert generated is not None
    assert generated.type == "ARMATURE"
    assert generated != source
    assert source.pose.bones["root"].rigify_type == ""
    assert bpy.data.objects.get("Source_metarig") is not None
    assert regenerated == generated
    assert source.re_rigify_generated_rig == generated
    assert source.re_rigify_metarig == first_metarig
finally:
    if re_rigify.ui.HELPER_NAME in bpy.data.objects:
        re_rigify.ui.remove_parameter_carrier()
    re_rigify.unregister()

print("RE_RIGIFY_GENERATE_OK")
