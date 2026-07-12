"""Re-Rigify Blender extension."""

bl_info = {
    "name": "Re-Rigify",
    "author": "Re-Rigify Contributors",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D View > Sidebar > Re-Rigify",
    "description": "Reusable Rigify bone, parameter, collection and UI configurations",
    "category": "Rigging",
}

def register():
    from . import blender_config, drive, operators, ui
    blender_config.register()
    drive.register()
    operators.register()
    ui.register()


def unregister():
    from . import blender_config, drive, operators, ui
    ui.unregister()
    operators.unregister()
    drive.unregister()
    blender_config.unregister()
