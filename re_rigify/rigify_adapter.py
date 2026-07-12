"""Small compatibility boundary around Rigify's public RNA and rig registry."""

from __future__ import annotations

import json
from typing import Any

import addon_utils
import bpy


def is_rigify_enabled() -> bool:
    return bool(addon_utils.check("rigify")[1])


def available_rig_types() -> tuple[str, ...]:
    if not is_rigify_enabled():
        return ()
    from rigify import rig_lists
    return tuple(sorted(rig_lists.rigs))


def serialize_parameters(params: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for prop in params.bl_rna.properties:
        if prop.identifier == "rna_type" or prop.is_readonly:
            continue
        if prop.type in {"POINTER", "COLLECTION"}:
            continue
        value = getattr(params, prop.identifier)
        if hasattr(value, "to_list"):
            value = value.to_list()
        elif not isinstance(value, (bool, int, float, str, list, tuple)):
            continue
        values[prop.identifier] = list(value) if isinstance(value, tuple) else value
    return values


def apply_parameters(params: Any, values: dict[str, Any]) -> list[str]:
    errors = []
    properties = params.bl_rna.properties
    for name, value in values.items():
        if name not in properties or properties[name].is_readonly:
            errors.append(f"unknown or read-only Rigify parameter: {name!r}")
            continue
        try:
            setattr(params, name, value)
        except (AttributeError, TypeError, ValueError) as exc:
            errors.append(f"invalid Rigify parameter {name!r}: {exc}")
    return errors


def draw_parameters(layout, pose_bone: bpy.types.PoseBone) -> None:
    from rigify import rig_lists
    info = rig_lists.rigs.get(pose_bone.rigify_type)
    if not info:
        return
    module = info["module"]
    callback = getattr(getattr(module, "Rig", None), "parameters_ui", None)
    if callback is None:
        callback = getattr(module, "parameters_ui", None)
    if callback:
        callback(layout, pose_bone.rigify_parameters)


def parameter_json(pose_bone: bpy.types.PoseBone) -> str:
    return json.dumps(serialize_parameters(pose_bone.rigify_parameters), sort_keys=True)
