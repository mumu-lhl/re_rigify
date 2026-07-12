"""Blender-independent configuration validation and bone matching."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any, Iterable


FORMAT_NAME = "re-rigify"
SCHEMA_VERSION = 1


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


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
    normalized_bones: list[dict[str, Any]] = []
    normalized_collections: list[dict[str, Any]] = []

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
            "rules": normalized_rules,
        })

    return {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "bones": normalized_bones,
        "collections": normalized_collections,
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
    occupied_slots: set[tuple[int, int]] = set()

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
