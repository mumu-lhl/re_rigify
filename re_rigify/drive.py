"""Constraint bridge from a generated Rigify rig to the original deform armature."""

from __future__ import annotations

import json

import bpy

from .core import choose_drive_spec, resolve_bone_rule_rows


CONSTRAINT_PREFIX = "Re-Rigify Drive"
DRIVER_BONE_PREFIX = "MCH-RR-Drive-"
DRIVER_COLLECTION_NAME = "Re-Rigify Drivers"
DRIVE_MAP_PROPERTY = "re_rigify_drive_map"
ROTATION_DRIVE_MAP_PROPERTY = "re_rigify_rotation_drive_map"
DISCONNECTED_BONES_PROPERTY = "re_rigify_drive_disconnected_bones"
_upgrade_enabled = False


def _context_state():
    context = bpy.context
    active = context.view_layer.objects.active
    return (
        active.name if active is not None else None,
        [obj.name for obj in context.view_layer.objects if obj.select_get()],
        context.object.mode if context.object else "OBJECT",
    )


def _set_object_mode(obj: bpy.types.Object, mode: str) -> None:
    context = bpy.context
    if obj.name not in context.view_layer.objects:
        raise RuntimeError(f"Armature {obj.name!r} is not in the active view layer")
    obj.hide_set(False)
    obj.hide_select = False
    obj.select_set(True)
    context.view_layer.objects.active = obj
    selected = [
        candidate for candidate in context.view_layer.objects
        if candidate.select_get()
    ]
    with context.temp_override(
        object=obj,
        active_object=obj,
        selected_objects=selected,
        selected_editable_objects=selected,
    ):
        bpy.ops.object.mode_set(mode=mode)


def _restore_object_context(active_name, selected_names, mode) -> None:
    context = bpy.context
    current = context.view_layer.objects.active
    if current is not None and current.mode != "OBJECT":
        _set_object_mode(current, "OBJECT")
    for obj in context.view_layer.objects:
        if obj.select_get():
            obj.select_set(False)
    for name in selected_names:
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.name in context.view_layer.objects:
            obj.select_set(True)
    active = bpy.data.objects.get(active_name) if active_name else None
    if active is None or active.name not in context.view_layer.objects:
        context.view_layer.objects.active = None
        return
    active.select_set(True)
    context.view_layer.objects.active = active
    if mode != "OBJECT":
        try:
            _set_object_mode(active, mode)
        except RuntimeError:
            if active.mode != "OBJECT":
                _set_object_mode(active, "OBJECT")


def _ensure_object_mode(obj: bpy.types.Object) -> None:
    if obj.mode != "OBJECT":
        try:
            _set_object_mode(obj, "OBJECT")
        except RuntimeError:
            pass


def _restore_visibility(obj, hidden, hide_select) -> None:
    try:
        if obj.name in bpy.data.objects:
            obj.hide_select = hide_select
            obj.hide_set(hidden)
    except ReferenceError:
        pass


def _set_bone_connections(
    source: bpy.types.Object,
    bone_names: set[str],
    connected: bool,
) -> None:
    if not bone_names:
        return
    context = bpy.context
    previous_active, previous_selected, previous_mode = _context_state()
    try:
        if context.object and context.object.mode != "OBJECT":
            _set_object_mode(context.object, "OBJECT")
        for obj in context.view_layer.objects:
            if not obj.select_get():
                continue
            obj.select_set(False)
        source.select_set(True)
        context.view_layer.objects.active = source
        _set_object_mode(source, "EDIT")
        for bone_name in bone_names:
            bone = source.data.edit_bones.get(bone_name)
            if bone is not None and bone.parent is not None:
                bone.use_connect = connected
        _set_object_mode(source, "OBJECT")
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
    previous_active, previous_selected, previous_mode = _context_state()
    hidden = rig.hide_get()
    hide_select = rig.hide_select
    removed = 0
    try:
        if context.object and context.object.mode != "OBJECT":
            _set_object_mode(context.object, "OBJECT")
        for obj in context.view_layer.objects:
            if not obj.select_get():
                continue
            obj.select_set(False)
        rig.hide_set(False)
        rig.hide_select = False
        rig.select_set(True)
        context.view_layer.objects.active = rig
        _set_object_mode(rig, "EDIT")
        for bone in list(rig.data.edit_bones):
            if bone.name.startswith(DRIVER_BONE_PREFIX):
                rig.data.edit_bones.remove(bone)
                removed += 1
        _set_object_mode(rig, "OBJECT")
        collection = rig.data.collections_all.get(DRIVER_COLLECTION_NAME)
        if collection is not None and not collection.bones:
            rig.data.collections.remove(collection)
    finally:
        _ensure_object_mode(rig)
        _restore_visibility(rig, hidden, hide_select)
        _restore_object_context(previous_active, previous_selected, previous_mode)
    return removed


def _chain_rule_bone_names(source: bpy.types.Object) -> set[str]:
    from .rules import armature_rule_topology, rule_dicts

    settings = getattr(source.data, "re_rigify", None)
    if settings is None or not settings.bone_rules:
        return set()
    parents, aligned_edges = armature_rule_topology(source.data)
    rows = resolve_bone_rule_rows(
        source.data.bones.keys(),
        rule_dicts(settings),
        parents,
        aligned_edges,
    )
    return {
        bone_name
        for row in rows
        if row["rule"].get("apply_as_chain", False)
        for bone_name in row["chain_bones"]
    }


def _build_drive_helpers(
    source: bpy.types.Object,
    rig: bpy.types.Object,
    targets: dict[str, str],
) -> dict[str, str]:
    remove_drive_helpers(rig)
    if not targets:
        return {}

    context = bpy.context
    previous_active, previous_selected, previous_mode = _context_state()
    helper_names: dict[str, str] = {}
    chain_rule_bones = _chain_rule_bone_names(source)
    source_to_rig = rig.matrix_world.inverted_safe() @ source.matrix_world
    try:
        if context.object and context.object.mode != "OBJECT":
            _set_object_mode(context.object, "OBJECT")
        for obj in context.view_layer.objects:
            if not obj.select_get():
                continue
            obj.select_set(False)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        _set_object_mode(rig, "EDIT")

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
            helper.inherit_scale = (
                "NONE" if source_name in chain_rule_bones else "FULL"
            )
            helper_names[source_name] = helper.name

        _set_object_mode(rig, "OBJECT")
        collection = rig.data.collections_all.get(DRIVER_COLLECTION_NAME)
        if collection is None:
            collection = rig.data.collections.new(DRIVER_COLLECTION_NAME)
        collection.is_visible = False
        for helper_name in helper_names.values():
            collection.assign(rig.data.bones[helper_name])

        context.view_layer.update()
        _set_object_mode(rig, "POSE")
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
