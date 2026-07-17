"""Constraint bridge from a generated Rigify rig to the original deform armature."""

from __future__ import annotations

import json

import bpy

from .core import choose_drive_spec


CONSTRAINT_PREFIX = "Re-Rigify Drive"
DRIVER_BONE_PREFIX = "MCH-RR-Drive-"
DRIVER_COLLECTION_NAME = "Re-Rigify Drivers"
DRIVE_MAP_PROPERTY = "re_rigify_drive_map"
ROTATION_DRIVE_MAP_PROPERTY = "re_rigify_rotation_drive_map"
DISCONNECTED_BONES_PROPERTY = "re_rigify_drive_disconnected_bones"
_upgrade_enabled = False


def _restore_object_context(active, selected, mode) -> None:
    context = bpy.context
    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in context.selected_objects:
        obj.select_set(False)
    for obj in selected:
        if obj.name in bpy.data.objects:
            obj.select_set(True)
    if active is not None and active.name in bpy.data.objects:
        context.view_layer.objects.active = active
        if mode != "OBJECT":
            bpy.ops.object.mode_set(mode=mode)


def _set_bone_connections(
    source: bpy.types.Object,
    bone_names: set[str],
    connected: bool,
) -> None:
    if not bone_names:
        return
    context = bpy.context
    previous_active = context.view_layer.objects.active
    previous_selected = list(context.selected_objects)
    previous_mode = context.object.mode if context.object else "OBJECT"
    try:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in context.selected_objects:
            obj.select_set(False)
        source.select_set(True)
        context.view_layer.objects.active = source
        bpy.ops.object.mode_set(mode="EDIT")
        for bone_name in bone_names:
            bone = source.data.edit_bones.get(bone_name)
            if bone is not None and bone.parent is not None:
                bone.use_connect = connected
        bpy.ops.object.mode_set(mode="OBJECT")
    finally:
        _restore_object_context(previous_active, previous_selected, previous_mode)


def _restore_source_connections(source: bpy.types.Object) -> None:
    try:
        bone_names = set(json.loads(source.get(DISCONNECTED_BONES_PROPERTY, "[]")))
    except (TypeError, json.JSONDecodeError):
        bone_names = set()
    _set_bone_connections(source, bone_names, True)
    if DISCONNECTED_BONES_PROPERTY in source:
        del source[DISCONNECTED_BONES_PROPERTY]


def _disconnect_driven_bones(
    source: bpy.types.Object,
    driven_bone_names: set[str],
) -> None:
    bone_names = {
        bone_name
        for bone_name in driven_bone_names
        if bone_name in source.data.bones
        and source.data.bones[bone_name].use_connect
    }
    if not bone_names:
        return
    source[DISCONNECTED_BONES_PROPERTY] = json.dumps(sorted(bone_names))
    try:
        _set_bone_connections(source, bone_names, False)
    except Exception:
        if DISCONNECTED_BONES_PROPERTY in source:
            del source[DISCONNECTED_BONES_PROPERTY]
        raise


def remove_drive_helpers(rig: bpy.types.Object | None) -> int:
    if rig is None or rig.type != "ARMATURE":
        return 0
    context = bpy.context
    previous_active = context.view_layer.objects.active
    previous_selected = list(context.selected_objects)
    previous_mode = context.object.mode if context.object else "OBJECT"
    removed = 0
    try:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in context.selected_objects:
            obj.select_set(False)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode="EDIT")
        for bone in list(rig.data.edit_bones):
            if bone.name.startswith(DRIVER_BONE_PREFIX):
                rig.data.edit_bones.remove(bone)
                removed += 1
        bpy.ops.object.mode_set(mode="OBJECT")
        collection = rig.data.collections_all.get(DRIVER_COLLECTION_NAME)
        if collection is not None and not collection.bones:
            rig.data.collections.remove(collection)
    finally:
        _restore_object_context(previous_active, previous_selected, previous_mode)
    return removed


def _build_drive_helpers(
    source: bpy.types.Object,
    rig: bpy.types.Object,
    targets: dict[str, str],
) -> dict[str, str]:
    remove_drive_helpers(rig)
    if not targets:
        return {}

    context = bpy.context
    previous_active = context.view_layer.objects.active
    previous_selected = list(context.selected_objects)
    previous_mode = context.object.mode if context.object else "OBJECT"
    helper_names: dict[str, str] = {}
    source_to_rig = rig.matrix_world.inverted_safe() @ source.matrix_world
    try:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in context.selected_objects:
            obj.select_set(False)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode="EDIT")

        for source_name, target_name in targets.items():
            source_bone = source.data.bones[source_name]
            helper = rig.data.edit_bones.new(f"{DRIVER_BONE_PREFIX}{source_name}")
            helper.matrix = source_to_rig @ source_bone.matrix_local
            helper.length = (
                source_to_rig @ source_bone.tail_local
                - source_to_rig @ source_bone.head_local
            ).length
            helper.parent = rig.data.edit_bones[target_name]
            helper.use_connect = False
            helper.use_deform = False
            helper_names[source_name] = helper.name

        bpy.ops.object.mode_set(mode="OBJECT")
        collection = rig.data.collections_all.get(DRIVER_COLLECTION_NAME)
        if collection is None:
            collection = rig.data.collections.new(DRIVER_COLLECTION_NAME)
        collection.is_visible = False
        for helper_name in helper_names.values():
            collection.assign(rig.data.bones[helper_name])

        context.view_layer.update()
        bpy.ops.object.mode_set(mode="POSE")
        for source_name, helper_name in helper_names.items():
            # Keep the source rest transform as the constant offset from the selected
            # Rigify target. Parent motion then drives the adapter without assuming that
            # the generated and production skeleton hierarchies are identical.
            rig.pose.bones[helper_name].matrix = (
                source_to_rig @ source.data.bones[source_name].matrix_local
            )
        context.view_layer.update()
    finally:
        _restore_object_context(previous_active, previous_selected, previous_mode)
    return helper_names


def remove_drive_constraints(source: bpy.types.Object) -> int:
    removed = 0
    for pose_bone in source.pose.bones:
        for constraint in list(pose_bone.constraints):
            if constraint.name.startswith(CONSTRAINT_PREFIX):
                pose_bone.constraints.remove(constraint)
                removed += 1
    _restore_source_connections(source)
    remove_drive_helpers(getattr(source, "re_rigify_generated_rig", None))
    return removed


def _load_drive_map(rig: bpy.types.Object, property_name: str) -> dict[str, str]:
    try:
        value = json.loads(rig.get(property_name, "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        source_name: target_name
        for source_name, target_name in value.items()
        if isinstance(source_name, str) and isinstance(target_name, str)
    }


def connect_source_to_rig(source: bpy.types.Object, rig: bpy.types.Object) -> tuple[int, list[str]]:
    if source == rig or source.type != "ARMATURE" or rig.type != "ARMATURE":
        raise ValueError("Source and generated rig must be different armature objects")
    remove_drive_constraints(source)
    target_names = set(rig.pose.bones.keys())
    explicit = _load_drive_map(rig, DRIVE_MAP_PROPERTY)
    rotation_explicit = _load_drive_map(rig, ROTATION_DRIVE_MAP_PROPERTY)
    unmatched: list[str] = []
    drive_specs = {}
    for pose_bone in source.pose.bones:
        drive_spec = choose_drive_spec(
            pose_bone.name, target_names, explicit, rotation_explicit,
        )
        if drive_spec is None:
            unmatched.append(pose_bone.name)
            continue
        drive_specs[pose_bone.name] = drive_spec

    helper_names = _build_drive_helpers(
        source,
        rig,
        {
            source_name: target_name
            for source_name, (target_name, drive_type) in drive_specs.items()
            if drive_type == "TRANSFORM"
        },
    )
    mapped = 0
    for pose_bone in source.pose.bones:
        drive_spec = drive_specs.get(pose_bone.name)
        if drive_spec is None:
            continue
        target_name, drive_type = drive_spec
        constraint = pose_bone.constraints.new(
            "COPY_ROTATION" if drive_type == "ROTATION" else "COPY_TRANSFORMS"
        )
        constraint.name = f"{CONSTRAINT_PREFIX}: {target_name}"
        constraint.target = rig
        constraint.subtarget = target_name
        if drive_type == "ROTATION":
            constraint.owner_space = "POSE"
            constraint.target_space = "POSE"
        else:
            constraint.subtarget = helper_names[pose_bone.name]
            constraint.owner_space = "WORLD"
            constraint.target_space = "WORLD"
        constraint.mix_mode = "REPLACE"
        mapped += 1
    _disconnect_driven_bones(
        source,
        {
            source_name
            for source_name, (_target_name, drive_type) in drive_specs.items()
            if drive_type == "TRANSFORM"
        },
    )
    source.re_rigify_generated_rig = rig
    return mapped, unmatched


def upgrade_drive_constraints() -> int:
    """Keep adapter-based bridges in their required spaces after reloading."""
    upgraded = 0
    for obj in getattr(bpy.data, "objects", ()):
        if obj.type != "ARMATURE" or not obj.pose:
            continue
        for pose_bone in obj.pose.bones:
            for constraint in pose_bone.constraints:
                if not constraint.name.startswith(CONSTRAINT_PREFIX):
                    continue
                if constraint.type == "COPY_TRANSFORMS":
                    if not constraint.subtarget.startswith(DRIVER_BONE_PREFIX):
                        continue
                    constraint.owner_space = "WORLD"
                    constraint.target_space = "WORLD"
                    constraint.mix_mode = "REPLACE"
                    upgraded += 1
                elif constraint.type == "COPY_ROTATION":
                    constraint.owner_space = "POSE"
                    constraint.target_space = "POSE"
                    constraint.mix_mode = "REPLACE"
                    upgraded += 1
        _disconnect_driven_bones(
            obj,
            {
                pose_bone.name
                for pose_bone in obj.pose.bones
                if any(
                    constraint.name.startswith(CONSTRAINT_PREFIX)
                    and constraint.type == "COPY_TRANSFORMS"
                    and constraint.subtarget.startswith(DRIVER_BONE_PREFIX)
                    for constraint in pose_bone.constraints
                )
            },
        )
    return upgraded


def _upgrade_timer():
    if not _upgrade_enabled:
        return None
    if not hasattr(bpy.data, "objects"):
        return 0.1
    upgrade_drive_constraints()
    return None


def register() -> None:
    global _upgrade_enabled
    _upgrade_enabled = True
    if not bpy.app.timers.is_registered(_upgrade_timer):
        bpy.app.timers.register(_upgrade_timer, first_interval=0.0)


def unregister() -> None:
    global _upgrade_enabled
    _upgrade_enabled = False
    if bpy.app.timers.is_registered(_upgrade_timer):
        bpy.app.timers.unregister(_upgrade_timer)
