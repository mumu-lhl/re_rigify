"""Blender-independent configuration validation and bone matching."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any, Iterable


FORMAT_NAME = "re-rigify"
SCHEMA_VERSION = 1

RIGIFY_DEFAULT_COLOR_SETS = (
    ("Root", (0.5490, 1.0, 1.0), (0.4353, 0.1843, 0.4157), (0.3140, 0.7840, 1.0)),
    ("IK", (0.5490, 1.0, 1.0), (0.6039, 0.0, 0.0), (0.3140, 0.7840, 1.0)),
    ("Special", (0.5490, 1.0, 1.0), (0.9569, 0.7882, 0.0471), (0.3140, 0.7840, 1.0)),
    ("Tweak", (0.5490, 1.0, 1.0), (0.0392, 0.2118, 0.5804), (0.3140, 0.7840, 1.0)),
    ("FK", (0.5490, 1.0, 1.0), (0.1176, 0.5686, 0.0353), (0.3140, 0.7840, 1.0)),
    ("Extra", (0.5490, 1.0, 1.0), (0.9686, 0.2510, 0.0941), (0.3140, 0.7840, 1.0)),
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def choose_drive_target(source_bone_name: str, target_bone_names: Iterable[str]) -> str | None:
    names = set(target_bone_names)
    for candidate in (f"DEF-{source_bone_name}", f"ORG-{source_bone_name}", source_bone_name):
        if candidate in names:
            return candidate
    return None


def mirror_parameter_value(value: Any, name_mapper) -> Any:
    """Recursively mirror bone-name strings inside Rigify parameter values."""
    if isinstance(value, dict):
        return {key: mirror_parameter_value(item, name_mapper) for key, item in value.items()}
    if isinstance(value, list):
        return [mirror_parameter_value(item, name_mapper) for item in value]
    if isinstance(value, str):
        return name_mapper(value)
    return value


def infer_rigify_topology(
    bone_configs: Iterable[dict[str, Any]], parents: dict[str, str | None]
) -> list[tuple[str, str, bool]]:
    """Infer common Rigify chains from disconnected production-skeleton parenting."""
    children: dict[str, list[str]] = {name: [] for name in parents}
    for child, parent in parents.items():
        if parent:
            children.setdefault(parent, []).append(child)

    def normalized(name: str) -> str:
        return name.lower().replace(".", "_").replace("-", "_")

    def descendants(root: str) -> list[str]:
        result, queue = [], list(children.get(root, ()))
        while queue:
            name = queue.pop(0)
            result.append(name)
            queue.extend(children.get(name, ()))
        return result

    def find(root: str, keywords: tuple[str, ...], *, exclude: set[str] | None = None) -> str | None:
        excluded = exclude or set()
        for keyword in keywords:
            for name in descendants(root):
                if name not in excluded and keyword in normalized(name):
                    return name
        return None

    operations: list[tuple[str, str, bool]] = []
    for config in bone_configs:
        root = config["bone_name"]
        rig_type = config["rigify_type"]
        if rig_type == "limbs.arm":
            lower = find(root, ("elbow", "forearm", "lower_arm"))
            hand = find(lower, ("wrist", "hand")) if lower else None
            if not lower or not hand:
                raise ConfigError(
                    f"{root!r} ({rig_type}) requires an upper-arm, forearm/elbow, and hand/wrist chain"
                )
            operations.extend(((root, lower, True), (lower, hand, True)))
        elif rig_type == "limbs.leg":
            knee = find(root, ("knee", "shin", "lower_leg"))
            foot = find(knee, ("ankle_offset", "foot", "ankle")) if knee else None
            toe = find(foot, ("toe",)) if foot else None
            heel = find(knee, ("heel",), exclude={foot, toe} if foot and toe else set()) if knee else None
            if heel is None and knee:
                heel = next(
                    (name for name in descendants(knee)
                     if name not in {foot, toe} and "ankle" in normalized(name)
                     and "offset" not in normalized(name)),
                    None,
                )
            if not knee or not foot or not toe or not heel:
                raise ConfigError(
                    f"{root!r} ({rig_type}) requires thigh, knee/shin, foot, toe, and heel bones"
                )
            operations.extend(
                ((root, knee, True), (knee, foot, True), (foot, toe, True), (foot, heel, False))
            )
        elif rig_type == "spines.basic_spine":
            chain = [root]
            current = root
            while len(chain) < 8:
                direct = children.get(current, [])
                preferred = [
                    name for name in direct
                    if any(key in normalized(name) for key in ("spine", "chest", "torso"))
                ]
                if len(preferred) == 1:
                    current = preferred[0]
                elif len(direct) == 1:
                    current = direct[0]
                else:
                    break
                chain.append(current)
            if len(chain) < 3:
                raise ConfigError(f"{root!r} ({rig_type}) requires a chain of at least 3 bones")
            operations.extend((parent, child, True) for parent, child in zip(chain, chain[1:]))
        elif rig_type == "spines.super_head":
            head = find(root, ("head",))
            if not head:
                raise ConfigError(f"{root!r} ({rig_type}) requires a connected head child")
            operations.append((root, head, True))
    return operations


def _require_type(value: Any, expected: type, path: str) -> Any:
    if not isinstance(value, expected):
        raise ConfigError(f"{path} must be {expected.__name__}")
    return value


def normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    _require_type(payload, dict, "configuration")
    if payload.get("format") != FORMAT_NAME:
        raise ConfigError(f"format must be {FORMAT_NAME!r}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"unsupported schema_version: {payload.get('schema_version')!r}")

    bones = _require_type(payload.get("bones"), list, "bones")
    collections = _require_type(payload.get("collections"), list, "collections")
    color_sets = _require_type(payload.get("color_sets", []), list, "color_sets")
    normalized_bones: list[dict[str, Any]] = []
    normalized_collections: list[dict[str, Any]] = []
    normalized_color_sets: list[dict[str, Any]] = []

    for index, item in enumerate(bones):
        item = _require_type(item, dict, f"bones[{index}]")
        bone_name = _require_type(item.get("bone_name"), str, f"bones[{index}].bone_name")
        rigify_type = _require_type(item.get("rigify_type"), str, f"bones[{index}].rigify_type")
        parameters = _require_type(item.get("parameters", {}), dict, f"bones[{index}].parameters")
        normalized_bones.append({
            "bone_name": bone_name,
            "rigify_type": rigify_type,
            "parameters": parameters,
        })

    for index, item in enumerate(collections):
        item = _require_type(item, dict, f"collections[{index}]")
        name = _require_type(item.get("name"), str, f"collections[{index}].name")
        ui_title = _require_type(item.get("ui_title", ""), str, f"collections[{index}].ui_title")
        ui_row = _require_type(item.get("ui_row", 0), int, f"collections[{index}].ui_row")
        row_order = _require_type(item.get("row_order", 0), int, f"collections[{index}].row_order")
        color_set = _require_type(item.get("color_set", ""), str, f"collections[{index}].color_set")
        if ui_row < 0 or row_order < 0:
            raise ConfigError(f"collections[{index}] row values must be non-negative")
        rules = _require_type(item.get("rules", []), list, f"collections[{index}].rules")
        normalized_rules = []
        for rule_index, rule in enumerate(rules):
            rule = _require_type(rule, dict, f"collections[{index}].rules[{rule_index}]")
            kind = rule.get("kind")
            pattern = rule.get("pattern")
            if kind not in {"EXACT", "GLOB"}:
                raise ConfigError(f"collections[{index}].rules[{rule_index}].kind is invalid")
            _require_type(pattern, str, f"collections[{index}].rules[{rule_index}].pattern")
            if not pattern:
                raise ConfigError(f"collections[{index}].rules[{rule_index}].pattern is empty")
            normalized_rules.append({"kind": kind, "pattern": pattern})
        normalized_collections.append({
            "name": name,
            "ui_title": ui_title,
            "ui_row": ui_row,
            "row_order": row_order,
            "color_set": color_set,
            "rules": normalized_rules,
        })

    for index, item in enumerate(color_sets):
        item = _require_type(item, dict, f"color_sets[{index}]")
        name = _require_type(item.get("name"), str, f"color_sets[{index}].name")
        colors = {}
        for field in ("active", "normal", "select"):
            value = _require_type(item.get(field), list, f"color_sets[{index}].{field}")
            if len(value) != 3 or any(not isinstance(component, (int, float)) for component in value):
                raise ConfigError(f"color_sets[{index}].{field} must contain three numbers")
            if any(component < 0.0 or component > 1.0 for component in value):
                raise ConfigError(f"color_sets[{index}].{field} values must be between 0 and 1")
            colors[field] = [float(component) for component in value]
        standard_colors_lock = _require_type(
            item.get("standard_colors_lock", False), bool,
            f"color_sets[{index}].standard_colors_lock",
        )
        normalized_color_sets.append({
            "name": name,
            **colors,
            "standard_colors_lock": standard_colors_lock,
        })

    return {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "bones": normalized_bones,
        "collections": normalized_collections,
        "color_sets": normalized_color_sets,
    }


def resolve_collection_rules(
    bone_names: Iterable[str], collections: Iterable[dict[str, Any]]
) -> dict[str, list[str]]:
    names = list(bone_names)
    resolved: dict[str, list[str]] = {}
    for collection in collections:
        members: list[str] = []
        for rule in collection.get("rules", []):
            pattern = rule["pattern"]
            if rule["kind"] == "EXACT":
                matches = [pattern] if pattern in names else []
            else:
                matches = [name for name in names if fnmatchcase(name, pattern)]
            if not matches:
                raise ConfigError(
                    f"{rule['kind']} pattern {pattern!r} in collection "
                    f"{collection['name']!r} matched no bones"
                )
            for name in matches:
                if name not in members:
                    members.append(name)
        resolved[collection["name"]] = members
    return resolved


def validate_config(
    payload: dict[str, Any], bone_names: Iterable[str], available_rig_types: Iterable[str]
) -> ValidationResult:
    try:
        config = normalize_config(payload)
    except ConfigError as exc:
        return ValidationResult((str(exc),))

    errors: list[str] = []
    names = set(bone_names)
    rig_types = set(available_rig_types)
    seen_bones: set[str] = set()
    seen_collections: set[str] = set()
    seen_color_sets: set[str] = set()
    occupied_slots: set[tuple[int, int]] = set()

    for item in config["color_sets"]:
        name = item["name"]
        if not name:
            errors.append("color set name is empty")
        elif name in seen_color_sets:
            errors.append(f"duplicate color set: {name!r}")
        seen_color_sets.add(name)

    for item in config["bones"]:
        name = item["bone_name"]
        if name in seen_bones:
            errors.append(f"duplicate bone configuration: {name!r}")
        seen_bones.add(name)
        if name not in names:
            errors.append(f"bone does not exist: {name!r}")
        if item["rigify_type"] not in rig_types:
            errors.append(f"Rigify type is unavailable: {item['rigify_type']!r}")

    for item in config["collections"]:
        name = item["name"]
        if name in seen_collections:
            errors.append(f"duplicate collection: {name!r}")
        seen_collections.add(name)
        if item["color_set"] and item["color_set"] not in seen_color_sets:
            errors.append(
                f"collection {name!r} references unknown color set: {item['color_set']!r}"
            )
        if item["ui_row"] > 0:
            slot = (item["ui_row"], item["row_order"])
            if slot in occupied_slots:
                errors.append(f"duplicate row_order {slot[1]} in UI row {slot[0]}")
            occupied_slots.add(slot)

    try:
        resolve_collection_rules(names, config["collections"])
    except ConfigError as exc:
        errors.append(str(exc))
    return ValidationResult(tuple(errors))
