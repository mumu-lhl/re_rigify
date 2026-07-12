import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import bpy
import re_rigify


bpy.ops.preferences.addon_enable(module="rigify")
re_rigify.register()
try:
    assert hasattr(bpy.types.Armature, "re_rigify")
    assert bpy.types.Panel.bl_rna_get_subclass_py("RERIGIFY_PT_main") is not None
finally:
    re_rigify.unregister()

print("RE_RIGIFY_EXTENSION_ENTRY_OK")
