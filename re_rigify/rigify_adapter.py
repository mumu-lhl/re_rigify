"""Small compatibility boundary around Rigify's public RNA and rig registry."""

from __future__ import annotations

import json
from typing import Any

import addon_utils
import bpy


class RigifyParameterLayout:
    """Route carrier-only Rigify operators without replacing the panel context."""

    _CONTAINER_METHODS = {
        "box", "column", "column_flow", "grid_flow", "menu_pie", "row", "split",
    }
    _OPERATOR_MAP = {
        "pose.rigify_collection_ref_add": "re_rigify.parameter_collection_ref_add",
        "pose.rigify_collection_ref_remove": "re_rigify.parameter_collection_ref_remove",
    }

    def __init__(self, layout):
        object.__setattr__(self, "_layout", layout)

    def __getattr__(self, name):
        value = getattr(self._layout, name)
        if name in self._CONTAINER_METHODS:
            return lambda *args, **kwargs: type(self)(value(*args, **kwargs))
        return value

    def __setattr__(self, name, value):
        setattr(self._layout, name, value)

    def operator(self, operator, **kwargs):
        return self._layout.operator(self._OPERATOR_MAP.get(operator, operator), **kwargs)


def is_rigify_enabled() -> bool:
    return bool(addon_utils.check("rigify")[1])


def available_rig_types() -> tuple[str, ...]:
    if not is_rigify_enabled():
        return ()
    from rigify import rig_lists
    return tuple(sorted(rig_lists.rigs))


def serialize_parameters(params: Any) -> dict[str, Any]:
    from rigify.utils.layers import is_collection_ref_list_prop

    values: dict[str, Any] = {}
    for prop in params.bl_rna.properties:
        if prop.identifier == "rna_type" or (prop.is_readonly and prop.type != "COLLECTION"):
            continue
        if prop.type == "POINTER":
            continue
        value = getattr(params, prop.identifier)
        if prop.type == "COLLECTION":
            if is_collection_ref_list_prop(value):
                values[prop.identifier] = [item.name for item in value]
            continue
        if hasattr(value, "to_list"):
            value = value.to_list()
        elif not isinstance(value, (bool, int, float, str, list, tuple)):
            continue
        values[prop.identifier] = list(value) if isinstance(value, tuple) else value
    return values


def apply_parameters(params: Any, values: dict[str, Any]) -> list[str]:
    from rigify.utils.layers import is_collection_ref_list_prop

    errors = []
    properties = params.bl_rna.properties
    for name, value in values.items():
        if name not in properties or (
            properties[name].is_readonly and properties[name].type != "COLLECTION"
        ):
            errors.append(f"unknown or read-only Rigify parameter: {name!r}")
            continue
        try:
            prop = properties[name]
            if prop.type == "COLLECTION":
                refs = getattr(params, name)
                if not is_collection_ref_list_prop(refs) or not isinstance(value, list):
                    raise TypeError("unsupported collection parameter")
                refs.clear()
                for collection_name in value:
                    if not isinstance(collection_name, str):
                        raise TypeError("collection reference name must be a string")
                    collection = params.id_data.data.collections_all.get(collection_name)
                    if collection is None:
                        raise ValueError(f"bone collection {collection_name!r} does not exist")
                    refs.add().set_collection(collection)
                continue
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
