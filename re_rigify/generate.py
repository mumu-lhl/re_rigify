"""Apply a stored configuration to a copy and invoke Rigify."""

from __future__ import annotations

import json

import bpy

from .core import (
    ConfigError,
    infer_rigify_topology,
    plan_missing_leg_heels,
    resolve_collection_rules,
)
from .compatibility import (
    apply_compatibility_plan,
    apply_connection_operations,
    apply_roll_helpers,
    build_compatibility_plan,
    resolve_compatibility_drive_map,
)
from .drive import DRIVE_MAP_PROPERTY, ROTATION_DRIVE_MAP_PROPERTY
from .rigify_adapter import apply_parameters
from .translations import format_iface


def apply_bone_config(obj: bpy.types.Object, bones: list[dict]) -> None:
    for item in bones:
        pose_bone = obj.pose.bones.get(item["bone_name"])
        if pose_bone is None:
            raise ConfigError(
                format_iface(
                    "bone does not exist: {bone_name!r}",
                    bone_name=item["bone_name"],
                )
            )
        pose_bone.rigify_type = item["rigify_type"]
        errors = apply_parameters(pose_bone.rigify_parameters, item.get("parameters", {}))
        if errors:
            raise ConfigError("; ".join(errors))


def validate_bone_parameters(
    context, source: bpy.types.Object, bones: list[dict], collections: list[dict] = ()
) -> tuple[str, ...]:
    """Validate against the active Rigify RNA without touching the source armature."""
    previous_active = context.view_layer.objects.active
    previous_selected = [obj for obj in context.view_layer.objects if obj.select_get()]
    try:
        infer_rigify_topology(
            bones,
            {bone.name: bone.parent.name if bone.parent else None for bone in source.data.bones},
        )
    except ConfigError as exc:
        return (str(exc),)
    duplicate = source.copy()
    duplicate.data = source.data.copy()
    duplicate.name = "__ReRigify_Validation__"
    context.scene.collection.objects.link(duplicate)
    context.view_layer.update()
    try:
        # Match generation: temporary heels may exist only on the validation copy.
        ensure_synthetic_leg_heels(duplicate, bones)
        apply_collection_config(duplicate, collections)
        apply_bone_config(duplicate, bones)
    except ConfigError as exc:
        return (str(exc),)
    finally:
        data = duplicate.data
        bpy.data.objects.remove(duplicate, do_unlink=True)
        if data.users == 0:
            bpy.data.armatures.remove(data)
        for obj in context.view_layer.objects:
            if obj.select_get():
                obj.select_set(False)
        for obj in previous_selected:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        if (
            previous_active is not None
            and previous_active.name in context.view_layer.objects
        ):
            context.view_layer.objects.active = previous_active
        elif source.name in context.view_layer.objects:
            source.select_set(True)
            context.view_layer.objects.active = source
    return ()


def ensure_synthetic_leg_heels(obj: bpy.types.Object, bones: list[dict]) -> list[str]:
    """Create temporary limbs.leg heel markers on a metarig copy only."""
    bone_data = {
        bone.name: {
            "head": tuple(bone.head_local),
            "tail": tuple(bone.tail_local),
        }
        for bone in obj.data.bones
    }
    parents = {
        bone.name: bone.parent.name if bone.parent else None
        for bone in obj.data.bones
    }
    plans = plan_missing_leg_heels(bones, bone_data, parents)
    if not plans:
        return []

    context = bpy.context
    previous_active = context.view_layer.objects.active
    previous_selected = [candidate for candidate in context.view_layer.objects if candidate.select_get()]
    previous_mode = obj.mode
    changed_active = previous_mode != "EDIT"
    if changed_active:
        for candidate in context.view_layer.objects:
            if candidate.select_get():
                candidate.select_set(False)
        obj.hide_set(False)
        obj.hide_select = False
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = obj.data.edit_bones
    created: list[str] = []
    try:
        for plan in plans:
            if plan["name"] in edit_bones:
                continue
            parent = edit_bones.get(plan["parent"])
            if parent is None:
                raise ConfigError(
                    format_iface(
                        "bone does not exist: {bone_name!r}",
                        bone_name=plan["parent"],
                    )
                )
            heel = edit_bones.new(plan["name"])
            heel.head = plan["head"]
            heel.tail = plan["tail"]
            heel.parent = parent
            heel.use_connect = bool(plan["use_connect"])
            created.append(plan["name"])
    finally:
        if changed_active:
            try:
                if obj.mode != previous_mode:
                    bpy.ops.object.mode_set(mode=previous_mode)
            except RuntimeError:
                pass
            for candidate in context.view_layer.objects:
                if candidate.select_get():
                    candidate.select_set(False)
            for candidate in previous_selected:
                if candidate.name in context.view_layer.objects:
                    candidate.select_set(True)
            if (
                previous_active is not None
                and previous_active.name in context.view_layer.objects
            ):
                context.view_layer.objects.active = previous_active
    return created

def apply_rigify_topology(context, obj: bpy.types.Object, bones: list[dict]) -> None:
    operations = infer_rigify_topology(
        bones,
        {bone.name: bone.parent.name if bone.parent else None for bone in obj.data.bones},
    )
    if not operations:
        return
    bpy.ops.object.mode_set(mode="EDIT")
    apply_connection_operations(obj.data.edit_bones, operations)
    for config in bones:
        explicit_chain = config.get("chain_bones") or []
        if explicit_chain:
            rig_type = config.get("rigify_type")
            term_name = explicit_chain[:4][-1] if rig_type == "limbs.leg" else explicit_chain[-1]
            term_bone = obj.data.edit_bones.get(term_name)
            if term_bone:
                for child in term_bone.children:
                    child.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")


def apply_collection_config(obj: bpy.types.Object, collections: list[dict]) -> None:
    armature = obj.data
    resolved = resolve_collection_rules((bone.name for bone in armature.bones), collections)
    effective = [dict(item) for item in collections]
    if effective and not any(item["ui_row"] > 0 for item in effective):
        # Rigify refuses to generate when no collection has a UI button.
        effective[0]["ui_row"] = 1
        effective[0]["row_order"] = 0
    ordered = sorted(effective, key=lambda item: (item["ui_row"], item["row_order"], item["name"]))
    for source in ordered:
        collection = armature.collections_all.get(source["name"])
        if collection is None:
            collection = armature.collections.new(source["name"])
        collection.is_visible = source.get("visible_after_generation", True)
        collection.rigify_ui_row = source["ui_row"]
        collection.rigify_ui_title = source.get("ui_title", "")
        for name in resolved[source["name"]]:
            collection.assign(armature.bones[name])

    # Rigify derives left-to-right button order from collection traversal order.
    roots = armature.collections
    for target_index, source in enumerate(ordered):
        collection = armature.collections_all[source["name"]
        ]
        current_index = list(roots).index(collection)
        if current_index != target_index:
            roots.move(current_index, target_index)


def apply_generated_collection_visibility(
    rig: bpy.types.Object,
    collections: list[dict],
) -> None:
    for source in collections:
        collection = rig.data.collections_all.get(source["name"])
        if collection is not None:
            collection.is_visible = source.get(
                "visible_after_generation", True,
            )


def apply_generated_root_color(
    rig: bpy.types.Object,
    root_color_set: str,
    color_sets: list[dict],
) -> bool:
    """Apply a configured color set to Rigify's generated root control."""
    if not root_color_set:
        return False
    color = next(
        (item for item in color_sets if item["name"] == root_color_set),
        None,
    )
    root = rig.pose.bones.get("root")
    if color is None or root is None:
        return False
    root.color.palette = "CUSTOM"
    root.color.custom.normal = color["normal"]
    root.color.custom.select = color["select"]
    root.color.custom.active = color["active"]
    return True

def fix_generated_control_display(rig: bpy.types.Object) -> dict[str, int]:
    """Correct display-only quirks on a freshly generated Rigify rig.

    - Shoulder widgets bulge along the bone +Z axis. Mirrored MMD shoulders often
      have -Z world-up on the right side, so the widget looks upside-down. Flip
      custom-shape Z scale when the bone Z axis points downward.
    - hips/chest control bones are intentionally Y-aligned by Rigify; do not
      rewrite those rest orientations here (constraints depend on them).
    """
    if rig is None or rig.type != "ARMATURE":
        return {"shoulders_flipped": 0, "synthetic_lids_hidden": 0}
    flipped = 0
    world_up = (0.0, 0.0, 1.0)
    for pose_bone in rig.pose.bones:
        shape = pose_bone.custom_shape
        if shape is None:
            continue
        shape_name = shape.name.lower()
        # Generated widgets are named like WGT-<rig>_肩.L; type is only known
        # from the mesh/name convention used by Rigify shoulder widgets.
        if "shoulder" not in shape_name and "肩" not in pose_bone.name:
            # Only touch controls that still use the stock shoulder mesh bbox
            # (y from 0..1, z from 0..+). Avoid flipping unrelated shapes.
            if shape.type == "MESH" and shape.data and shape.data.vertices:
                ys = [v.co.y for v in shape.data.vertices]
                zs = [v.co.z for v in shape.data.vertices]
                if not (min(ys) >= -1e-4 and max(ys) <= 1.0 + 1e-3 and min(zs) >= -1e-4):
                    continue
            else:
                continue
        bone = pose_bone.bone
        z_axis = bone.matrix_local.to_3x3().col[2].normalized()
        if z_axis.dot(world_up) >= 0.0:
            continue
        scale = list(pose_bone.custom_shape_scale_xyz)
        if scale[2] > 0.0:
            scale[2] = -scale[2]
            pose_bone.custom_shape_scale_xyz = scale
            flipped += 1
    return {
        "shoulders_flipped": flipped,
        "synthetic_lids_hidden": hide_synthetic_eyelid_controls(rig),
    }


def hide_synthetic_eyelid_controls(rig: bpy.types.Object) -> int:
    """Hide Rigify eyelid scaffolding created for eyes without real lids.

    ``face.skin_eye`` requires upper/lower child chains. Re-Rigify may inject
    temporary ``RR-lid*`` bones so the eye target/master still generate. Those
    controls cannot drive source eyelids, so hide them on the finished rig.
    """
    if rig is None or rig.type != "ARMATURE":
        return 0
    hidden = 0
    collection = rig.data.collections_all.get("Re-Rigify Hidden Lids")
    for pose_bone in rig.pose.bones:
        name = pose_bone.name
        # Match helper, deform, and control derivatives of synthetic lid chains.
        if "RR-lid" not in name and "rr-lid" not in name.lower():
            continue
        bone = pose_bone.bone
        bone.hide = True
        if collection is None:
            collection = rig.data.collections.new("Re-Rigify Hidden Lids")
            collection.is_visible = False
            if hasattr(collection, "rigify_ui_row"):
                collection.rigify_ui_row = 0
        for existing in list(bone.collections):
            existing.unassign(bone)
        collection.assign(bone)
        if pose_bone.custom_shape is not None:
            pose_bone.custom_shape = None
        hidden += 1
    if collection is not None:
        collection.is_visible = False
    return hidden




def apply_color_config(obj: bpy.types.Object, color_sets: list[dict], collections: list[dict]) -> None:
    armature = obj.data
    armature.rigify_colors.clear()
    color_ids = {}
    for index, source in enumerate(color_sets, 1):
        color = armature.rigify_colors.add()
        color.name = source["name"]
        color.active = source["active"]
        color.normal = source["normal"]
        color.select = source["select"]
        color.standard_colors_lock = source["standard_colors_lock"]
        color_ids[source["name"]] = index
    for source in collections:
        collection = armature.collections_all.get(source["name"])
        if collection is not None:
            collection.rigify_color_set_id = color_ids.get(source.get("color_set", ""), 0)


def duplicate_as_metarig(source: bpy.types.Object) -> bpy.types.Object:
    duplicate = source.copy()
    duplicate.data = source.data.copy()
    duplicate.name = f"{source.name}_metarig"
    for collection in source.users_collection:
        collection.objects.link(duplicate)
    from .drive import remove_drive_constraints
    remove_drive_constraints(duplicate)
    return duplicate


def resolve_existing_target_rig(source: bpy.types.Object) -> bpy.types.Object | None:
    """Return a reusable generated rig, or drop stale unlinked leftovers.

    Users often delete the generated rig from the outliner/view layer while the
    Object datablock remains. Rigify then fails with "not in view layer". Treat
    unlinked leftovers as deleted so generation can create a fresh target.
    """
    candidates: list[bpy.types.Object] = []
    linked = source.re_rigify_generated_rig
    if linked is not None:
        candidates.append(linked)
    by_name = bpy.data.objects.get(f"{source.name}_rig")
    if by_name is not None and by_name not in candidates:
        candidates.append(by_name)

    for target in candidates:
        if target == source or target.type != "ARMATURE":
            if source.re_rigify_generated_rig == target:
                source.re_rigify_generated_rig = None
            continue
        if target.users_collection:
            return target
        # Unlinked leftover: clear pointer and remove if possible.
        if source.re_rigify_generated_rig == target:
            source.re_rigify_generated_rig = None
        try:
            bpy.data.objects.remove(target, do_unlink=True)
        except RuntimeError:
            pass
    return None


def ensure_object_in_source_collections(
    obj: bpy.types.Object,
    source: bpy.types.Object,
) -> None:
    """Link obj into the source's collections so the active view layer can see it."""
    if obj.users_collection:
        return
    linked = False
    for collection in source.users_collection:
        if obj.name not in collection.objects:
            collection.objects.link(obj)
            linked = True
    if not linked and obj.name not in bpy.context.scene.collection.objects:
        bpy.context.scene.collection.objects.link(obj)


def prepare_metarig(source: bpy.types.Object) -> bpy.types.Object:
    """Create a temporary metarig that targets the existing generated rig."""
    target_rig = resolve_existing_target_rig(source)
    cleanup_metarigs(source)
    metarig = duplicate_as_metarig(source)
    source.re_rigify_metarig = metarig
    metarig.re_rigify_source_armature = source
    metarig.hide_viewport = False
    metarig.hide_select = False
    metarig.hide_set(False)
    if target_rig is not None:
        ensure_object_in_source_collections(target_rig, source)
        target_rig.hide_viewport = False
        target_rig.hide_select = False
        target_rig.hide_set(False)
        # Final gate: Rigify must be able to select the target in this view layer.
        if target_rig.name in bpy.context.view_layer.objects:
            metarig.data.rigify_target_rig = target_rig
        else:
            if source.re_rigify_generated_rig == target_rig:
                source.re_rigify_generated_rig = None
            metarig.data.rigify_target_rig = None
    return metarig


def cleanup_metarigs(source: bpy.types.Object, keep: bpy.types.Object | None = None) -> int:
    removed = 0
    exact_name = f"{source.name}_metarig"
    numbered_prefix = f"{source.name}_metarig."
    for obj in list(bpy.data.objects):
        if obj == keep or obj.type != "ARMATURE":
            continue
        marked = obj.re_rigify_source_armature == source
        if marked or obj.name == exact_name or obj.name.startswith(numbered_prefix):
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
    return removed


def cleanup_rigify_ui_scripts(rig: bpy.types.Object | None) -> int:
    """Remove stale Rigify UI scripts belonging to a generated rig."""
    if rig is None or rig.type != "ARMATURE":
        return 0
    script_name = f"{rig.name}_ui.py"
    removed = 0
    for text in list(bpy.data.texts):
        if text.name == script_name or text.name.startswith(script_name + "."):
            bpy.data.texts.remove(text)
            removed += 1
    return removed


def generate_rig(context: bpy.types.Context, source: bpy.types.Object, payload: dict) -> bpy.types.Object:
    previous_active = context.view_layer.objects.active
    previous_active_name = previous_active.name if previous_active else None
    previous_selected_names = [obj.name for obj in context.selected_objects]
    previous_mode = source.mode
    duplicate = None
    before = set(bpy.data.objects)
    try:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        previous_rig = resolve_existing_target_rig(source)
        cleanup_rigify_ui_scripts(previous_rig)
        duplicate = prepare_metarig(source)
        # Heel markers required by Rigify limbs.leg live only on the metarig.
        ensure_synthetic_leg_heels(duplicate, payload["bones"])
        apply_collection_config(duplicate, payload["collections"])
        apply_bone_config(duplicate, payload["bones"])
        apply_color_config(duplicate, payload.get("color_sets", []), payload["collections"])
        bpy.ops.object.select_all(action="DESELECT")
        duplicate.select_set(True)
        context.view_layer.objects.active = duplicate
        apply_rigify_topology(context, duplicate, payload["bones"])
        compatibility_plan = build_compatibility_plan(duplicate, payload["bones"])
        source_to_helper = apply_compatibility_plan(duplicate, compatibility_plan)
        bpy.ops.object.mode_set(mode="POSE")
        result = bpy.ops.pose.rigify_generate()
        if "FINISHED" not in result:
            raise RuntimeError(
                format_iface(
                    "Rigify generation returned {result}",
                    result=result,
                )
            )
        created = [obj for obj in bpy.data.objects if obj not in before and obj != duplicate]
        rigs = [obj for obj in created if obj.type == "ARMATURE"]
        result_obj = context.view_layer.objects.active
        if result_obj == duplicate and rigs:
            result_obj = rigs[-1]
        apply_generated_collection_visibility(
            result_obj, payload["collections"],
        )
        apply_generated_root_color(
            result_obj,
            payload.get("root_color_set", ""),
            payload.get("color_sets", []),
        )
        fix_generated_control_display(result_obj)
        rotation_drive_map = apply_roll_helpers(
            context, source, result_obj, compatibility_plan.roll_plans,
        )
        explicit_drive_map = resolve_compatibility_drive_map(
            source_to_helper,
            compatibility_plan.eye_plans,
            result_obj.pose.bones.keys(),
        )
        result_obj[DRIVE_MAP_PROPERTY] = json.dumps(
            explicit_drive_map, ensure_ascii=False, sort_keys=True,
        )
        result_obj[ROTATION_DRIVE_MAP_PROPERTY] = json.dumps(
            rotation_drive_map, ensure_ascii=False, sort_keys=True,
        )
        source.re_rigify_generated_rig = result_obj
        cleanup_metarigs(source)
        source.re_rigify_metarig = None
        return result_obj
    except Exception:
        for obj in list(bpy.data.objects):
            if obj not in before:
                bpy.data.objects.remove(obj, do_unlink=True)
        raise
    finally:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in context.selected_objects:
            obj.select_set(False)
        for name in previous_selected_names:
            obj = bpy.data.objects.get(name)
            if obj is not None and obj.name in context.view_layer.objects:
                obj.select_set(True)
        previous_active = (
            bpy.data.objects.get(previous_active_name)
            if previous_active_name else None
        )
        if previous_active and previous_active.name in context.view_layer.objects:
            context.view_layer.objects.active = previous_active
            if previous_mode != "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode=previous_mode)
                except RuntimeError:
                    pass
