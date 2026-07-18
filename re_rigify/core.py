"""Blender-independent configuration validation and bone matching."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fnmatch import fnmatchcase
import re
from typing import Any, Iterable


FORMAT_NAME = "re-rigify"
SCHEMA_VERSION = 1

DEFAULT_COMPATIBILITY = {
    "force_connect_chain": False,
    "skin_eye_compatibility": False,
    "roll_bones_enabled": False,
    "upper_arm_roll_bone": "",
    "forearm_roll_bone": "",
    "eye_forward_axis": "AUTO",
    "upper_lid_pattern": "",
    "lower_lid_pattern": "",
    "synthetic_lids_fallback": False,
}

EXPLICIT_CHAIN_MIN_LENGTHS = {
    "limbs.arm": 3,
    "limbs.super_finger": 2,
    "limbs.spline_tentacle": 2,
    "spines.basic_spine": 3,
    "spines.super_head": 2,
}

CHAIN_RULE_MIN_LENGTHS = {
    "limbs.super_finger": 2,
    "limbs.spline_tentacle": 2,
}

RIGIFY_DEFAULT_COLOR_SETS = (
    ("Root", (0.5490, 1.0, 1.0), (0.4353, 0.1843, 0.4157), (0.3140, 0.7840, 1.0)),
    ("IK", (0.5490, 1.0, 1.0), (0.6039, 0.0, 0.0), (0.3140, 0.7840, 1.0)),
    ("Special", (0.5490, 1.0, 1.0), (0.9569, 0.7882, 0.0471), (0.3140, 0.7840, 1.0)),
    ("Tweak", (0.5490, 1.0, 1.0), (0.0392, 0.2118, 0.5804), (0.3140, 0.7840, 1.0)),
    ("FK", (0.5490, 1.0, 1.0), (0.1176, 0.5686, 0.0353), (0.3140, 0.7840, 1.0)),
    ("Extra", (0.5490, 1.0, 1.0), (0.9686, 0.2510, 0.0941), (0.3140, 0.7840, 1.0)),
)


def move_selected_indices(
    item_count: int,
    selected_indices: Iterable[int],
    direction: int,
) -> tuple[tuple[int, int], ...]:
    if direction not in {-1, 1}:
        raise ValueError("direction must be -1 or 1")
    selected = {
        index for index in selected_indices
        if 0 <= index < item_count
    }
    operations = []
    ordered = sorted(selected, reverse=direction > 0)
    for source in ordered:
        target = source + direction
        if not 0 <= target < item_count or target in selected:
            continue
        operations.append((source, target))
        selected.remove(source)
        selected.add(target)
    return tuple(operations)


class ConfigError(ValueError):
    pass


def unique_blender_name(name: str, existing_names: Iterable[str]) -> str:
    existing = set(existing_names)
    if name not in existing:
        return name
    match = re.fullmatch(r"(.*?)(?:\.(\d{3}))?", name)
    base = match.group(1) if match else name
    index = 1
    while f"{base}.{index:03d}" in existing:
        index += 1
    return f"{base}.{index:03d}"


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def choose_drive_target(
    source_bone_name: str,
    target_bone_names: Iterable[str],
    explicit: dict[str, str] | None = None,
) -> str | None:
    names = set(target_bone_names)
    explicit_target = (explicit or {}).get(source_bone_name)
    if explicit_target in names:
        return explicit_target
    for candidate in (f"ORG-{source_bone_name}", f"DEF-{source_bone_name}", source_bone_name):
        if candidate in names:
            return candidate
    return None


def choose_drive_spec(
    source_bone_name: str,
    target_bone_names: Iterable[str],
    transform_explicit: dict[str, str] | None = None,
    rotation_explicit: dict[str, str] | None = None,
) -> tuple[str, str] | None:
    names = set(target_bone_names)
    rotation_target = (rotation_explicit or {}).get(source_bone_name)
    if rotation_target in names:
        return rotation_target, "ROTATION"
    target = choose_drive_target(source_bone_name, names, transform_explicit)
    return (target, "TRANSFORM") if target is not None else None


def mirror_parameter_value(value: Any, name_mapper) -> Any:
    """Recursively mirror bone-name strings inside Rigify parameter values."""
    if isinstance(value, dict):
        return {key: mirror_parameter_value(item, name_mapper) for key, item in value.items()}
    if isinstance(value, list):
        return [mirror_parameter_value(item, name_mapper) for item in value]
    if isinstance(value, str):
        return name_mapper(value)
    return value


def normalize_compatibility(value: object, path: str = "compatibility") -> dict[str, Any]:
    value = _require_type(value, dict, path)
    result = dict(DEFAULT_COMPATIBILITY)
    for name in (
        "force_connect_chain", "skin_eye_compatibility", "synthetic_lids_fallback",
        "roll_bones_enabled",
    ):
        if name in value:
            result[name] = _require_type(value[name], bool, f"{path}.{name}")
    for name in (
        "upper_lid_pattern", "lower_lid_pattern",
        "upper_arm_roll_bone", "forearm_roll_bone",
    ):
        if name in value:
            result[name] = _require_type(value[name], str, f"{path}.{name}")
    if "eye_forward_axis" in value:
        axis = _require_type(value["eye_forward_axis"], str, f"{path}.eye_forward_axis")
        if axis not in {"AUTO", "+X", "-X", "+Y", "-Y"}:
            raise ConfigError(f"{path}.eye_forward_axis is invalid")
        result["eye_forward_axis"] = axis
    return result


def mirror_compatibility(value: dict[str, Any], name_mapper) -> dict[str, Any]:
    result = normalize_compatibility(value)
    result["upper_lid_pattern"] = name_mapper(result["upper_lid_pattern"])
    result["lower_lid_pattern"] = name_mapper(result["lower_lid_pattern"])
    result["upper_arm_roll_bone"] = name_mapper(result["upper_arm_roll_bone"])
    result["forearm_roll_bone"] = name_mapper(result["forearm_roll_bone"])
    result["eye_forward_axis"] = {
        "+X": "-X",
        "-X": "+X",
    }.get(result["eye_forward_axis"], result["eye_forward_axis"])
    return result


def unique_child_chain(root: str, parents: dict[str, str | None]) -> list[str]:
    if root not in parents:
        raise ConfigError(f"bone does not exist: {root!r}")
    children: dict[str, list[str]] = {name: [] for name in parents}
    for child, parent in parents.items():
        if parent:
            children.setdefault(parent, []).append(child)
    chain = [root]
    while True:
        candidates = sorted(children.get(chain[-1], ()))
        if not candidates:
            return chain
        if len(candidates) > 1:
            raise ConfigError(
                f"{chain[-1]!r} has ambiguous child chain: {', '.join(candidates)}"
            )
        chain.append(candidates[0])


def remove_collection_references(parameters: dict[str, Any], collection_name: str) -> dict[str, Any]:
    result = dict(parameters)
    for name, value in parameters.items():
        if name.endswith("_coll_refs") and isinstance(value, list):
            result[name] = [item for item in value if item != collection_name]
    return result


def rename_collection_references(
    parameters: dict[str, Any],
    old_name: str,
    new_name: str,
) -> dict[str, Any]:
    result = dict(parameters)
    for name, value in parameters.items():
        if name.endswith("_coll_refs") and isinstance(value, list):
            result[name] = [
                new_name if item == old_name else item for item in value
            ]
    return result


def resolve_bone_rules(
    bone_names: Iterable[str],
    rules: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    names = list(bone_names)
    winners: dict[str, dict[str, Any]] = {}
    for rule in rules:
        if rule["kind"] == "EXACT":
            matches = [rule["pattern"]] if rule["pattern"] in names else []
        else:
            matches = [
                name for name in names if fnmatchcase(name, rule["pattern"])
            ]
        if not matches:
            raise ConfigError(
                f"{rule['kind']} bone rule {rule['pattern']!r} matched no bones"
            )
        for name in matches:
            winners[name] = rule
    return {name: winners[name] for name in names if name in winners}


def resolve_bone_rule_rows(
    bone_names: Iterable[str],
    rules: Iterable[dict[str, Any]],
    parents: dict[str, str | None] | None = None,
    aligned_edges: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    names = list(bone_names)
    rule_list = list(rules)
    winners = resolve_bone_rules(names, rule_list)
    if not any(rule.get("apply_as_chain", False) for rule in rule_list):
        return [{
            "bone_name": name,
            "rule": winners[name],
            "chain_bones": [],
        } for name in names if name in winners]
    if parents is None or aligned_edges is None:
        raise ConfigError("chain bone rules require source bone topology")

    children: dict[str, list[str]] = {name: [] for name in names}
    for child in names:
        parent = parents.get(child)
        if parent in children:
            children[parent].append(child)

    def same_winner(left: str, right: str) -> bool:
        return (
            left in winners
            and right in winners
            and winners[left]["rule_id"] == winners[right]["rule_id"]
        )

    rows = []
    claimed = set()
    for name in names:
        rule = winners.get(name)
        if rule is None:
            continue
        if not rule.get("apply_as_chain", False):
            rows.append({
                "bone_name": name,
                "rule": rule,
                "chain_bones": [],
            })
            claimed.add(name)
            continue
        minimum = CHAIN_RULE_MIN_LENGTHS.get(rule["rigify_type"])
        if minimum is None:
            raise ConfigError(
                f"bone rule {rule['pattern']!r} Rigify type "
                f"{rule['rigify_type']!r} does not support chain rules"
            )
        parent = parents.get(name)
        if parent is not None and same_winner(parent, name):
            continue
        chain = [name]
        current = name
        while True:
            matched_children = [
                child for child in children.get(current, ())
                if same_winner(current, child)
            ]
            if len(matched_children) > 1:
                raise ConfigError(
                    f"bone rule {rule['pattern']!r} chain branches "
                    f"at {current!r}"
                )
            if not matched_children:
                break
            child = matched_children[0]
            if (current, child) not in aligned_edges:
                raise ConfigError(
                    f"bone rule {rule['pattern']!r} has disjoint edge "
                    f"{current!r} -> {child!r}"
                )
            chain.append(child)
            current = child
        if len(chain) < minimum:
            raise ConfigError(
                f"bone rule {rule['pattern']!r} chain at {name!r} "
                f"requires at least {minimum} bones"
            )
        claimed.update(chain)
        rows.append({
            "bone_name": name,
            "rule": rule,
            "chain_bones": chain,
        })

    expected = {
        name for name, rule in winners.items()
        if rule.get("apply_as_chain", False)
    }
    unreachable = expected - claimed
    if unreachable:
        raise ConfigError(
            "chain bone rule topology has no reachable root for "
            f"{sorted(unreachable)!r}"
        )
    return rows


def materialize_bone_rules(
    payload: dict[str, Any],
    bone_names: Iterable[str],
    parents: dict[str, str | None] | None = None,
    aligned_edges: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    config = normalize_config(payload)
    names = list(bone_names)
    winners = resolve_bone_rules(names, config["bone_rules"])
    rows = resolve_bone_rule_rows(
        names, config["bone_rules"], parents, aligned_edges,
    )
    rows_by_name = {row["bone_name"]: row for row in rows}
    resolved = []
    emitted = set()

    def materialized(row):
        rule = row["rule"]
        return {
            "bone_name": row["bone_name"],
            "rigify_type": rule["rigify_type"],
            "chain_bones": list(row["chain_bones"]),
            "parameters": deepcopy(rule["parameters"]),
            "compatibility": deepcopy(DEFAULT_COMPATIBILITY),
        }

    for item in config["bones"]:
        name = item["bone_name"]
        if name not in winners:
            resolved.append(item)
        elif name in rows_by_name:
            resolved.append(materialized(rows_by_name[name]))
            emitted.add(name)
    for row in rows:
        if row["bone_name"] not in emitted:
            resolved.append(materialized(row))
    return {**config, "bones": resolved}


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
        explicit_chain = config.get("chain_bones", [])
        if explicit_chain:
            operations.extend(
                (parent, child, True)
                for parent, child in zip(explicit_chain, explicit_chain[1:])
            )
            continue
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
            if parent := parents.get(root):
                operations.append((parent, root, False))
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
    bone_rules = _require_type(payload.get("bone_rules", []), list, "bone_rules")
    collections = _require_type(payload.get("collections"), list, "collections")
    color_sets = _require_type(payload.get("color_sets", []), list, "color_sets")
    normalized_bones: list[dict[str, Any]] = []
    normalized_bone_rules: list[dict[str, Any]] = []
    normalized_collections: list[dict[str, Any]] = []
    normalized_color_sets: list[dict[str, Any]] = []

    for index, item in enumerate(bones):
        item = _require_type(item, dict, f"bones[{index}]")
        bone_name = _require_type(item.get("bone_name"), str, f"bones[{index}].bone_name")
        rigify_type = _require_type(item.get("rigify_type"), str, f"bones[{index}].rigify_type")
        chain_bones = _require_type(
            item.get("chain_bones", []), list, f"bones[{index}].chain_bones"
        )
        for chain_index, chain_bone in enumerate(chain_bones):
            _require_type(
                chain_bone,
                str,
                f"bones[{index}].chain_bones[{chain_index}]",
            )
        parameters = _require_type(item.get("parameters", {}), dict, f"bones[{index}].parameters")
        compatibility = normalize_compatibility(
            item.get("compatibility", {}),
            f"bones[{index}].compatibility",
        )
        normalized_bones.append({
            "bone_name": bone_name,
            "rigify_type": rigify_type,
            "chain_bones": list(chain_bones),
            "parameters": parameters,
            "compatibility": compatibility,
        })

    for index, item in enumerate(bone_rules):
        item = _require_type(item, dict, f"bone_rules[{index}]")
        rule_id = _require_type(
            item.get("rule_id"), str, f"bone_rules[{index}].rule_id",
        )
        kind = _require_type(
            item.get("kind"), str, f"bone_rules[{index}].kind",
        )
        pattern = _require_type(
            item.get("pattern"), str, f"bone_rules[{index}].pattern",
        )
        rigify_type = _require_type(
            item.get("rigify_type"), str, f"bone_rules[{index}].rigify_type",
        )
        parameters = _require_type(
            item.get("parameters", {}), dict, f"bone_rules[{index}].parameters",
        )
        apply_as_chain = _require_type(
            item.get("apply_as_chain", False),
            bool,
            f"bone_rules[{index}].apply_as_chain",
        )
        if not rule_id:
            raise ConfigError(f"bone_rules[{index}].rule_id is empty")
        if kind not in {"EXACT", "GLOB"}:
            raise ConfigError(f"bone_rules[{index}].kind is invalid")
        if not pattern:
            raise ConfigError(f"bone_rules[{index}].pattern is empty")
        normalized_bone_rules.append({
            "rule_id": rule_id,
            "kind": kind,
            "pattern": pattern,
            "rigify_type": rigify_type,
            "parameters": parameters,
            "apply_as_chain": apply_as_chain,
        })

    for index, item in enumerate(collections):
        item = _require_type(item, dict, f"collections[{index}]")
        name = _require_type(item.get("name"), str, f"collections[{index}].name")
        ui_title = _require_type(item.get("ui_title", ""), str, f"collections[{index}].ui_title")
        ui_row = _require_type(item.get("ui_row", 0), int, f"collections[{index}].ui_row")
        row_order = _require_type(item.get("row_order", 0), int, f"collections[{index}].row_order")
        color_set = _require_type(item.get("color_set", ""), str, f"collections[{index}].color_set")
        visible_after_generation = _require_type(
            item.get("visible_after_generation", True),
            bool,
            f"collections[{index}].visible_after_generation",
        )
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
            "visible_after_generation": visible_after_generation,
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
        "bone_rules": normalized_bone_rules,
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
    payload: dict[str, Any],
    bone_names: Iterable[str],
    available_rig_types: Iterable[str],
    parents: dict[str, str | None] | None = None,
    aligned_edges: set[tuple[str, str]] | None = None,
) -> ValidationResult:
    try:
        config = normalize_config(payload)
    except ConfigError as exc:
        return ValidationResult((str(exc),))

    errors: list[str] = []
    ordered_names = list(bone_names)
    names = set(ordered_names)
    rig_types = set(available_rig_types)
    seen_bones: set[str] = set()
    seen_collections: set[str] = set()
    managed_collection_names = {item["name"] for item in config["collections"]}
    seen_color_sets: set[str] = set()
    occupied_slots: set[tuple[int, int]] = set()

    def validate_collection_refs(owner, parameters):
        for parameter, references in parameters.items():
            if not parameter.endswith("_coll_refs"):
                continue
            if (
                not isinstance(references, list)
                or any(not isinstance(ref, str) for ref in references)
            ):
                errors.append(
                    f"{owner} parameter {parameter!r} must be a list "
                    "of collection names"
                )
                continue
            for reference in references:
                if reference not in managed_collection_names:
                    errors.append(
                        f"{owner} parameter {parameter!r} references unknown "
                        f"managed collection: {reference!r}"
                    )

    for item in config["color_sets"]:
        name = item["name"]
        if not name:
            errors.append("color set name is empty")
        elif name in seen_color_sets:
            errors.append(f"duplicate color set: {name!r}")
        seen_color_sets.add(name)

    seen_rule_ids = set()
    for rule in config["bone_rules"]:
        if rule["rule_id"] in seen_rule_ids:
            errors.append(f"duplicate bone rule id: {rule['rule_id']!r}")
        seen_rule_ids.add(rule["rule_id"])
        if rule["rigify_type"] not in rig_types:
            errors.append(f"Rigify type is unavailable: {rule['rigify_type']!r}")
        validate_collection_refs(
            f"bone rule {rule['pattern']!r}", rule["parameters"],
        )

    try:
        effective = materialize_bone_rules(
            config, ordered_names, parents, aligned_edges,
        )
    except ConfigError as exc:
        errors.append(str(exc))
        effective = config

    for item in effective["bones"]:
        name = item["bone_name"]
        if name in seen_bones:
            errors.append(f"duplicate bone configuration: {name!r}")
        seen_bones.add(name)
        if name not in names:
            errors.append(f"bone does not exist: {name!r}")
        if item["rigify_type"] not in rig_types:
            errors.append(f"Rigify type is unavailable: {item['rigify_type']!r}")
        chain_bones = item["chain_bones"]
        if chain_bones:
            if chain_bones[0] != name:
                errors.append(
                    f"bone {name!r} explicit chain must start with the configured bone"
                )
            chain_seen: set[str] = set()
            for chain_bone in chain_bones:
                if chain_bone not in names:
                    errors.append(
                        f"bone {name!r} explicit chain bone does not exist: {chain_bone!r}"
                    )
                if chain_bone in chain_seen:
                    errors.append(
                        f"bone {name!r} explicit chain contains duplicate bone: {chain_bone!r}"
                    )
                chain_seen.add(chain_bone)
            minimum = EXPLICIT_CHAIN_MIN_LENGTHS.get(item["rigify_type"])
            if minimum is None:
                errors.append(
                    f"bone {name!r} Rigify type does not support an explicit chain: "
                    f"{item['rigify_type']!r}"
                )
            elif len(chain_bones) < minimum:
                errors.append(
                    f"bone {name!r} explicit chain requires at least {minimum} bones"
                )
        validate_collection_refs(f"bone {name!r}", item["parameters"])

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
