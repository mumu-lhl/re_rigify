# Bone Rules and Collection Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent bone matching rules, safe collection-reference lifecycle, generated collection visibility, and repair the confirmed FK/Tweak parameter-loss defect.

**Architecture:** Pure schema and rule resolution remain in `core.py`; Blender-specific incremental materialization lives in a new `rules.py`. RNA stores canonical rules plus expanded managed rows, while export filters managed rows and generation consumes them. Parameter-carrier binding is generalized to write either a bone row or a rule without changing Rigify's native UI.

**Tech Stack:** Python 3, Blender 5.2 RNA/operators/UI, Rigify, `unittest`, Blender MCP, jj.

## Global Constraints

- Rule kinds are `EXACT` and case-sensitive `GLOB`.
- Rules apply top to bottom; the last matching rule wins.
- Expanded managed rows preserve position, checked state, and active bone.
- Managed bone name, type, chain, compatibility, and parameters are read-only in the bone editor.
- Import, validation, export, and generation synchronize rules.
- Schema remains version 1.
- Missing `bone_rules` defaults to `[]`.
- Missing `visible_after_generation` defaults to `true`.
- Do not launch a Blender process; use the connected Blender MCP for Blender integration.
- Prefix every shell command with `rtk`.
- Use jj commits.

---

### Task 1: Stop Parameter References from Being Overwritten

**Files:**
- Modify: `re_rigify/blender_config.py`
- Test: `tests/blender_integration.py`

**Interfaces:**
- Consumes: existing `suspend_carrier_updates`, `flush_parameter_carrier`, and `remove_parameter_carrier`.
- Produces: `payload_to_armature` that leaves imported `parameters_json` unchanged and leaves no carrier bound.

- [ ] **Step 1: Add the failing multi-row reference regression**

Add a temporary two-bone payload test to `tests/blender_integration.py`:

```python
reference_source = make_armature("Reference Import", ["A", "B"])
reference_payload = {
    "format": "re-rigify",
    "schema_version": 1,
    "bones": [{
        "bone_name": name,
        "rigify_type": "basic.super_copy",
        "chain_bones": [],
        "parameters": {
            "fk_layers_extra": True,
            "fk_coll_refs": ["FK"],
            "tweak_layers_extra": True,
            "tweak_coll_refs": ["Tweaks"],
        },
        "compatibility": DEFAULT_COMPATIBILITY,
    } for name in ("A", "B")],
    "collections": [
        {
            "name": "FK", "ui_title": "FK", "ui_row": 1, "row_order": 0,
            "color_set": "", "rules": [],
        },
        {
            "name": "Tweaks", "ui_title": "Tweaks", "ui_row": 1, "row_order": 1,
            "color_set": "", "rules": [],
        },
    ],
    "color_sets": [],
}
payload_to_armature(reference_source.data, reference_payload)
flush_parameter_carrier()
for item in reference_source.data.re_rigify.bones:
    parameters = json.loads(item.parameters_json)
    assert parameters["fk_coll_refs"] == ["FK"]
    assert parameters["tweak_coll_refs"] == ["Tweaks"]
assert bpy.data.objects.get(re_rigify.ui.HELPER_NAME) is None
```

Import `json` normally at the top of the test file instead of using
`__import__`.

- [ ] **Step 2: Reproduce RED through Blender MCP**

Run the same two-bone scenario in the connected Blender session. Expected:
`fk_coll_refs` and `tweak_coll_refs` become `[]`, proving the callback overwrite.

- [ ] **Step 3: Make payload replacement carrier-safe**

Change `payload_to_armature` so its body follows this structure:

```python
def payload_to_armature(armature: bpy.types.Armature, payload: dict) -> None:
    payload = normalize_config(payload)
    from .ui import flush_parameter_carrier, remove_parameter_carrier
    flush_parameter_carrier()
    remove_parameter_carrier()
    settings = armature.re_rigify
    with suspend_carrier_updates():
        settings.bones.clear()
        settings.collections.clear()
        settings.color_sets.clear()
        for source in payload["bones"]:
            item = settings.bones.add()
            item.bone_name = source["bone_name"]
            item.rigify_type = source["rigify_type"]
            apply_chain_bones_to_item(item, source["chain_bones"])
            item.parameters_json = json.dumps(
                source["parameters"], ensure_ascii=False, sort_keys=True,
            )
            _apply_compatibility_to_item(item, source["compatibility"])
        for source in payload["collections"]:
            item = settings.collections.add()
            item.name = source["name"]
            item.ui_title = source["ui_title"]
            item.ui_row = source["ui_row"]
            item.row_order = source["row_order"]
            item.color_set_name = source["color_set"]
            for source_rule in source["rules"]:
                rule = item.rules.add()
                rule.kind = source_rule["kind"]
                rule.pattern = source_rule["pattern"]
        for source in payload["color_sets"]:
            item = settings.color_sets.add()
            item.name = source["name"]
            item.active = source["active"]
            item.normal = source["normal"]
            item.select = source["select"]
            item.standard_colors_lock = source["standard_colors_lock"]
        settings.active_bone_index = min(
            settings.active_bone_index, max(0, len(settings.bones) - 1)
        )
        settings.active_collection_index = min(
            settings.active_collection_index,
            max(0, len(settings.collections) - 1),
        )
        settings.active_color_index = min(
            settings.active_color_index, max(0, len(settings.color_sets) - 1)
        )
```

Do not recreate a carrier at the end.

- [ ] **Step 4: Verify GREEN**

Reload `blender_config` through a full add-on unregister/reload/register cycle
using payload snapshots, then repeat the MCP scenario. Expected references:
`["FK"]` and `["Tweaks"]` before and after `flush_parameter_carrier`.

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk git diff --check
```

Expected: all pure tests pass and diff check is empty.

- [ ] **Step 5: Commit**

```bash
rtk jj commit -m "fix(config): preserve collection references"
```

---

### Task 2: Rule Schema, Resolution, Rename Helper, and Visibility Field

**Files:**
- Modify: `re_rigify/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Produces:
  - `resolve_bone_rules(bone_names, rules) -> dict[str, dict]`
  - `materialize_bone_rules(payload, bone_names) -> dict`
  - `rename_collection_references(parameters, old_name, new_name) -> dict`
  - normalized top-level `bone_rules`
  - normalized collection `visible_after_generation: bool`
- Consumes: existing `normalize_config`, `ConfigError`, `fnmatchcase`, and collection-reference validation.

- [ ] **Step 1: Add failing schema and resolution tests**

Add imports and tests:

```python
from re_rigify.core import (
    materialize_bone_rules,
    rename_collection_references,
    resolve_bone_rules,
)


class BoneRuleTests(unittest.TestCase):
    @staticmethod
    def valid_payload():
        return {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [{
                "bone_name": "spine",
                "rigify_type": "basic.raw_copy",
                "chain_bones": [],
                "parameters": {},
                "compatibility": DEFAULT_COMPATIBILITY,
            }],
            "collections": [{
                "name": "Controls",
                "ui_title": "Controls",
                "ui_row": 1,
                "row_order": 0,
                "color_set": "",
                "rules": [],
            }],
            "color_sets": [],
        }

    def test_schema_defaults_rules_and_visibility(self):
        payload = self.valid_payload()
        result = normalize_config(payload)
        self.assertEqual(result["bone_rules"], [])
        self.assertTrue(result["collections"][0]["visible_after_generation"])

    def test_later_rule_wins_and_result_follows_bone_order(self):
        rules = [
            {
                "rule_id": "all-fingers", "kind": "GLOB", "pattern": "Finger_*",
                "rigify_type": "limbs.super_finger",
                "parameters": {"segments": 2},
            },
            {
                "rule_id": "index", "kind": "EXACT", "pattern": "Finger_Index",
                "rigify_type": "basic.super_copy",
                "parameters": {"make_control": True},
            },
        ]
        result = resolve_bone_rules(
            ["Root", "Finger_Index", "Finger_Middle"], rules,
        )
        self.assertEqual(list(result), ["Finger_Index", "Finger_Middle"])
        self.assertEqual(result["Finger_Index"]["rule_id"], "index")
        self.assertEqual(
            result["Finger_Middle"]["rule_id"], "all-fingers",
        )

    def test_rule_with_no_match_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "matched no bones"):
            resolve_bone_rules(
                ["Root"],
                [{
                    "rule_id": "missing", "kind": "GLOB", "pattern": "Finger_*",
                    "rigify_type": "basic.super_copy", "parameters": {},
                }],
            )

    def test_materialization_overrides_manual_rows_and_appends_new_matches(self):
        payload = self.valid_payload()
        payload["bones"][0]["bone_name"] = "Finger_Index"
        payload["bone_rules"] = [{
            "rule_id": "fingers", "kind": "GLOB", "pattern": "Finger_*",
            "rigify_type": "basic.super_copy",
            "parameters": {"make_control": False},
        }]
        result = materialize_bone_rules(
            payload, ["Root", "Finger_Index", "Finger_Middle"],
        )
        self.assertEqual(
            [item["bone_name"] for item in result["bones"]],
            ["Finger_Index", "Finger_Middle"],
        )
        self.assertTrue(all(
            item["rigify_type"] == "basic.super_copy"
            and item["parameters"] == {"make_control": False}
            for item in result["bones"]
        ))

    def test_rename_updates_only_collection_reference_lists(self):
        parameters = {
            "fk_coll_refs": ["Old", "Other"],
            "tweak_coll_refs": ["Old"],
            "ordinary_list": ["Old"],
            "label": "Old",
        }
        self.assertEqual(
            rename_collection_references(parameters, "Old", "New"),
            {
                "fk_coll_refs": ["New", "Other"],
                "tweak_coll_refs": ["New"],
                "ordinary_list": ["Old"],
                "label": "Old",
            },
        )
```

- [ ] **Step 2: Verify RED**

Run:

```bash
rtk python3 -m unittest tests.test_core.BoneRuleTests -v
```

Expected: import failures for the two new functions.

- [ ] **Step 3: Normalize rules and visibility**

In `normalize_config`:

```python
bone_rules = _require_type(payload.get("bone_rules", []), list, "bone_rules")
normalized_bone_rules = []
for index, item in enumerate(bone_rules):
    item = _require_type(item, dict, f"bone_rules[{index}]")
    rule_id = _require_type(item.get("rule_id"), str, f"bone_rules[{index}].rule_id")
    kind = _require_type(item.get("kind"), str, f"bone_rules[{index}].kind")
    pattern = _require_type(item.get("pattern"), str, f"bone_rules[{index}].pattern")
    rigify_type = _require_type(
        item.get("rigify_type"), str, f"bone_rules[{index}].rigify_type"
    )
    parameters = _require_type(
        item.get("parameters", {}), dict, f"bone_rules[{index}].parameters"
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
    })
```

Normalize each collection visibility with:

```python
visible_after_generation = _require_type(
    item.get("visible_after_generation", True),
    bool,
    f"collections[{index}].visible_after_generation",
)
```

Return `bone_rules` and the visibility field in the normalized payload.

- [ ] **Step 4: Implement pure rule and rename helpers**

Add:

```python
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


def materialize_bone_rules(
    payload: dict[str, Any],
    bone_names: Iterable[str],
) -> dict[str, Any]:
    config = normalize_config(payload)
    names = list(bone_names)
    winners = resolve_bone_rules(names, config["bone_rules"])
    resolved = []
    seen = set()
    for item in config["bones"]:
        name = item["bone_name"]
        seen.add(name)
        rule = winners.get(name)
        resolved.append({
            "bone_name": name,
            "rigify_type": rule["rigify_type"],
            "chain_bones": [],
            "parameters": dict(rule["parameters"]),
            "compatibility": dict(DEFAULT_COMPATIBILITY),
        } if rule else item)
    for name in names:
        if name in winners and name not in seen:
            rule = winners[name]
            resolved.append({
                "bone_name": name,
                "rigify_type": rule["rigify_type"],
                "chain_bones": [],
                "parameters": dict(rule["parameters"]),
                "compatibility": dict(DEFAULT_COMPATIBILITY),
            })
    return {**config, "bones": resolved}


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
```

- [ ] **Step 5: Extend validation**

In `validate_config`, add this local helper immediately after
`managed_collection_names` is computed:

```python
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
```

Call `resolve_bone_rules(names, config["bone_rules"])` and append its
`ConfigError`. Replace the current per-bone `_coll_refs` loop with:

```python
validate_collection_refs(f"bone {name!r}", item["parameters"])
```

Use `materialize_bone_rules(config, names)` as the source of the bone loop so
rule-derived rows receive the same existence, type, chain, compatibility, and
collection-reference checks as manual rows.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
rtk python3 -m unittest tests.test_core.BoneRuleTests -v
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk git diff --check
rtk jj commit -m "feat(config): add persistent bone rules"
```

Expected: all tests pass.

---

### Task 3: RNA Storage and Incremental Rule Synchronization

**Files:**
- Create: `re_rigify/rules.py`
- Modify: `re_rigify/blender_config.py`
- Modify: `re_rigify/__init__.py`
- Test: `tests/test_ui_source.py`
- Test: `tests/blender_integration.py`

**Interfaces:**
- Produces:
  - `RERIGIFY_PG_BoneRule`
  - `settings.bone_rules`, `settings.active_bone_rule_index`
  - `item.managed_rule_id`
  - `sync_bone_rules(armature) -> tuple[int, int, int]`
  - `armature_to_payload(armature, include_managed=True)`
- Consumes: Task 2 `resolve_bone_rules`, rule schema, default compatibility,
  and existing suspension/config item helpers.

- [ ] **Step 1: Add failing source and Blender integration tests**

Require these names in `tests/test_ui_source.py`:

```python
self.assertIn("RERIGIFY_PG_BoneRule", blender_config_classes)
self.assertTrue(Path("re_rigify/rules.py").exists())
```

Add a Blender scenario:

```python
rule = settings.bone_rules.add()
rule.rule_id = "fingers"
rule.kind = "GLOB"
rule.pattern = "Finger_*"
rule.rigify_type = "basic.super_copy"
rule.parameters_json = '{"make_control": true}'
added, updated, removed = sync_bone_rules(source.data)
assert (added, updated, removed) == (2, 0, 0)
assert [item.bone_name for item in settings.bones][-2:] == [
    "Finger_Index", "Finger_Middle",
]
assert all(item.managed_rule_id == "fingers" for item in settings.bones[-2:])
settings.bones[-2].collection_selected = True
settings.active_bone_index = len(settings.bones) - 2
rule.pattern = "Finger_Index"
added, updated, removed = sync_bone_rules(source.data)
assert (added, removed) == (0, 1)
assert settings.bones[settings.active_bone_index].bone_name == "Finger_Index"
assert settings.bones[settings.active_bone_index].collection_selected
```

Also assert:

```python
canonical = armature_to_payload(source.data, include_managed=False)
resolved = armature_to_payload(source.data, include_managed=True)
assert all("Finger_" not in item["bone_name"] for item in canonical["bones"])
assert {item["bone_name"] for item in resolved["bones"]} >= {
    "Finger_Index",
}
assert canonical["bone_rules"][0]["rule_id"] == "fingers"
```

- [ ] **Step 2: Verify RED**

Run the source test with normal Python. Use Blender MCP for the RNA scenario.
Expected: missing class/module/property failures.

- [ ] **Step 3: Add RNA properties and serialization**

Add:

```python
class RERIGIFY_PG_BoneRule(bpy.types.PropertyGroup):
    rule_id: StringProperty(name="Rule ID")
    kind: EnumProperty(
        name="Match",
        items=(
            ("EXACT", "Exact", "Match one complete bone name"),
            ("GLOB", "Glob", "Case-sensitive *, ? and [] pattern"),
        ),
        default="GLOB",
    )
    pattern: StringProperty(name="Bone Pattern")
    rigify_type: StringProperty(name="Rigify Type")
    parameters_json: StringProperty(name="Parameters", default="{}")


class RERIGIFY_PG_BoneConfig(...):
    managed_rule_id: StringProperty(default="", options={"HIDDEN"})


class RERIGIFY_PG_CollectionConfig(...):
    visible_after_generation: BoolProperty(
        name="Visible After Generation", default=True,
    )


class RERIGIFY_PG_ArmatureConfig(...):
    bone_rules: CollectionProperty(type=RERIGIFY_PG_BoneRule)
    active_bone_rule_index: IntProperty(default=0)
```

Register `RERIGIFY_PG_BoneRule` before the armature config.

Change serialization:

```python
def armature_to_payload(armature, include_managed=True):
    settings = armature.re_rigify
    bones = [
        item for item in settings.bones
        if include_managed or not item.managed_rule_id
    ]
    return {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "bones": [serialize_bone(item) for item in bones],
        "bone_rules": [{
            "rule_id": rule.rule_id,
            "kind": rule.kind,
            "pattern": rule.pattern,
            "rigify_type": rule.rigify_type,
            "parameters": json.loads(rule.parameters_json or "{}"),
        } for rule in settings.bone_rules],
        "collections": [{
            "name": item.name,
            "ui_title": item.ui_title,
            "ui_row": item.ui_row,
            "row_order": item.row_order,
            "color_set": item.color_set_name,
            "visible_after_generation": item.visible_after_generation,
            "rules": [
                {"kind": rule.kind, "pattern": rule.pattern}
                for rule in item.rules
            ],
        } for item in settings.collections],
        "color_sets": [{
            "name": item.name,
            "active": list(item.active),
            "normal": list(item.normal),
            "select": list(item.select),
            "standard_colors_lock": item.standard_colors_lock,
        } for item in settings.color_sets],
    }
```

Extract the current bone dictionary expression without changing its fields:

```python
def serialize_bone(item):
    return {
        "bone_name": item.bone_name,
        "rigify_type": item.rigify_type,
        "chain_bones": chain_bones_from_item(item),
        "parameters": json.loads(item.parameters_json or "{}"),
        "compatibility": _compatibility_from_item(item),
    }
```

Load `visible_after_generation` for each collection and load rules inside the
carrier-suspension block:

```python
settings.bone_rules.clear()
for source in payload["bone_rules"]:
    rule = settings.bone_rules.add()
    rule.rule_id = source["rule_id"]
    rule.kind = source["kind"]
    rule.pattern = source["pattern"]
    rule.rigify_type = source["rigify_type"]
    rule.parameters_json = json.dumps(
        source["parameters"], ensure_ascii=False, sort_keys=True,
    )
# In the collection loop:
item.visible_after_generation = source["visible_after_generation"]
```

Call `sync_bone_rules(armature)` after leaving the suspension block.

- [ ] **Step 4: Implement `rules.py`**

Create:

```python
"""Materialize persistent bone rules into configured bone rows."""

from __future__ import annotations
import json

from .blender_config import (
    _apply_compatibility_to_item,
    apply_chain_bones_to_item,
    suspend_carrier_updates,
)
from .core import DEFAULT_COMPATIBILITY, resolve_bone_rules


def rule_dicts(settings):
    return [{
        "rule_id": rule.rule_id,
        "kind": rule.kind,
        "pattern": rule.pattern,
        "rigify_type": rule.rigify_type,
        "parameters": json.loads(rule.parameters_json or "{}"),
    } for rule in settings.bone_rules]


def sync_bone_rules(armature) -> tuple[int, int, int]:
    settings = armature.re_rigify
    winners = resolve_bone_rules(
        armature.bones.keys(), rule_dicts(settings),
    ) if settings.bone_rules else {}
    active_name = (
        settings.bones[settings.active_bone_index].bone_name
        if settings.bones else None
    )
    remove_indices = [
        index for index, item in enumerate(settings.bones)
        if item.managed_rule_id and item.bone_name not in winners
    ]
    added = updated = 0
    with suspend_carrier_updates():
        for index in reversed(remove_indices):
            settings.bones.remove(index)
        for bone_name, rule in winners.items():
            item = next(
                (candidate for candidate in settings.bones
                 if candidate.bone_name == bone_name),
                None,
            )
            if item is None:
                item = settings.bones.add()
                item.bone_name = bone_name
                added += 1
            else:
                updated += 1
            item.managed_rule_id = rule["rule_id"]
            item.rigify_type = rule["rigify_type"]
            item.parameters_json = json.dumps(
                rule["parameters"], ensure_ascii=False, sort_keys=True,
            )
            apply_chain_bones_to_item(item, [])
            _apply_compatibility_to_item(item, DEFAULT_COMPATIBILITY)
        if active_name:
            settings.active_bone_index = next(
                (
                    index for index, item in enumerate(settings.bones)
                    if item.bone_name == active_name
                ),
                min(settings.active_bone_index, max(0, len(settings.bones) - 1)),
            )
    return added, updated, len(remove_indices)
```

Registering the new module is unnecessary because it defines no Blender class;
import it locally from workflows. Include it in live reload order during MCP
tests.

- [ ] **Step 5: Verify GREEN and commit**

Run pure tests, then full add-on reload and the MCP scenario. Confirm canonical
export omits managed rows and resolved export includes them.

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk git diff --check
rtk jj commit -m "feat(config): materialize bone rules"
```

---

### Task 4: Rule Operators, Read-Only Managed Rows, and Rule Parameter Carrier

**Files:**
- Modify: `re_rigify/operators.py`
- Modify: `re_rigify/ui.py`
- Modify: `re_rigify/blender_config.py`
- Modify: `tests/test_ui_source.py`
- Modify: `tests/blender_integration.py`

**Interfaces:**
- Produces operators:
  - `re_rigify.bone_rule_add`
  - `re_rigify.bone_rule_remove`
  - `re_rigify.bone_rule_move`
  - `re_rigify.bone_rule_sync`
- Extends carrier functions with:
  - `prepare_rule_parameter_carrier(context, source, rule, rule_index)`
  - `get_rule_parameter_carrier(source, rule, rule_index)`
  - binding target kind `BONE` or `RULE`.

- [ ] **Step 1: Add failing UI and carrier tests**

In `tests/test_ui_source.py`, require:

```python
{
    "RERIGIFY_UL_BoneRules",
    "RERIGIFY_PT_BoneRules",
    "RERIGIFY_PT_BoneRuleParameters",
}.issubset(ui_classes)
```

Require all four operator classes in `operators.py`. In Blender integration:

```python
assert bpy.ops.re_rigify.bone_rule_add() == {"FINISHED"}
rule = settings.bone_rules[settings.active_bone_rule_index]
rule.pattern = "Finger_*"
rule.rigify_type = "basic.super_copy"
carrier = prepare_rule_parameter_carrier(
    bpy.context, source, rule, settings.active_bone_rule_index,
)
carrier.rigify_parameters.make_control = False
flush_parameter_carrier()
assert json.loads(rule.parameters_json)["make_control"] is False
assert get_rule_parameter_carrier(
    source, rule, settings.active_bone_rule_index,
) == carrier
```

- [ ] **Step 2: Verify RED**

Run the source test and use Blender MCP for the carrier test. Expected missing
class/function/operator failures.

- [ ] **Step 3: Generalize carrier binding**

Replace `_bound_index` with:

```python
_bound_kind = None
_bound_key = None
_bound_source_bone_name = None
```

Keep `prepare_parameter_carrier` as the bone wrapper. Extract a shared internal
function:

```python
def _prepare_parameter_carrier(
    context, source, target, target_kind, target_key, source_bone_name,
):
    try:
        if bpy.data.objects.get(source.name) != source or source.as_pointer() == 0:
            return None
    except ReferenceError:
        return None
    flush_parameter_carrier()
    obj = bpy.data.objects.get(HELPER_NAME)
    source_key = f"{source.data.name}:{len(source.data.bones)}"
    if obj is not None and (
        obj.get("re_rigify_source") != source_key
        or source_bone_name not in obj.pose.bones
    ):
        remove_parameter_carrier()
        obj = None
    if obj is None:
        armature = source.data.copy()
        armature.name = HELPER_NAME
        obj = bpy.data.objects.new(HELPER_NAME, armature)
        context.scene.collection.objects.link(obj)
        obj.hide_render = True
        obj.hide_set(True)
        obj["re_rigify_source"] = source_key
        context.view_layer.update()
    settings = source.data.re_rigify
    managed_names = {collection.name for collection in settings.collections}
    for collection in list(obj.data.collections_all):
        if collection.name not in managed_names:
            obj.data.collections.remove(collection)
    from .generate import apply_collection_config
    apply_collection_config(obj, [{
        "name": collection.name,
        "ui_title": collection.ui_title,
        "ui_row": collection.ui_row,
        "row_order": collection.row_order,
        "visible_after_generation": collection.visible_after_generation,
        "rules": [
            {"kind": rule.kind, "pattern": rule.pattern}
            for rule in collection.rules
        ],
    } for collection in settings.collections])
    pose_bone = obj.pose.bones[source_bone_name]
    key = (
        f"{source.data.name}:{target_kind}:{target_key}:"
        f"{source_bone_name}:{target.rigify_type}"
    )
    if obj.get("re_rigify_key") != key:
        pose_bone.rigify_type = target.rigify_type
        apply_parameters(
            pose_bone.rigify_parameters,
            json.loads(target.parameters_json or "{}"),
        )
        obj["re_rigify_key"] = key
    global _bound_armature_name, _bound_armature_pointer
    global _bound_kind, _bound_key, _bound_source_bone_name, _pending_binding
    _bound_armature_name = source.data.name
    _bound_armature_pointer = source.data.as_pointer()
    _bound_kind = target_kind
    _bound_key = str(target_key)
    _bound_source_bone_name = source_bone_name
    _pending_binding = None
    return pose_bone
```

Bone target key is its index. Rule target key is `rule.rule_id`. Implement the
bone wrappers and rule wrapper:

```python
def prepare_parameter_carrier(context, source, item, index):
    return _prepare_parameter_carrier(
        context, source, item, "BONE", index, item.bone_name,
    )


def prepare_rule_parameter_carrier(context, source, rule, rule_index):
    from .rules import rule_dicts
    try:
        matches = resolve_bone_rules(
            source.data.bones.keys(),
            [rule_dicts(source.data.re_rigify)[rule_index]],
        )
    except ConfigError:
        return None
    source_bone_name = next(iter(matches))
    return _prepare_parameter_carrier(
        context, source, rule, "RULE", rule.rule_id, source_bone_name,
    )
```

Generalize `_carrier_key` and both getters:

```python
def _carrier_key(source, target_kind, target_key, bone_name, rigify_type):
    return (
        f"{source.data.name}:{target_kind}:{target_key}:"
        f"{bone_name}:{rigify_type}"
    )


def _get_parameter_carrier(
    source, target_kind, target_key, source_bone_name, rigify_type,
):
    obj = bpy.data.objects.get(HELPER_NAME)
    if (
        obj is None
        or obj.get("re_rigify_source")
        != f"{source.data.name}:{len(source.data.bones)}"
        or obj.get("re_rigify_key") != _carrier_key(
            source, target_kind, target_key, source_bone_name, rigify_type,
        )
    ):
        return None
    return (
        obj.pose.bones.get(source_bone_name) if obj.pose else None
    )


def get_parameter_carrier(source, item, index):
    return _get_parameter_carrier(
        source, "BONE", index, item.bone_name, item.rigify_type,
    )


def get_rule_parameter_carrier(source, rule, rule_index):
    from .rules import rule_dicts
    try:
        matches = resolve_bone_rules(
            source.data.bones.keys(),
            [rule_dicts(source.data.re_rigify)[rule_index]],
        )
    except ConfigError:
        return None
    source_bone_name = next(iter(matches))
    return _get_parameter_carrier(
        source, "RULE", rule.rule_id,
        source_bone_name, rule.rigify_type,
    )
```

`flush_parameter_carrier` resolves a bone by index for `BONE`, or searches
`settings.bone_rules` by stable ID for `RULE`, then assigns
`parameter_json(carrier)`:

```python
settings = armature.re_rigify
target = None
if _bound_kind == "BONE":
    index = int(_bound_key)
    if 0 <= index < len(settings.bones):
        target = settings.bones[index]
elif _bound_kind == "RULE":
    target = next(
        (rule for rule in settings.bone_rules if rule.rule_id == _bound_key),
        None,
    )
helper = bpy.data.objects.get(HELPER_NAME)
carrier = (
    helper.pose.bones.get(_bound_source_bone_name)
    if helper and helper.pose else None
)
if target is not None and carrier is not None:
    target.parameters_json = parameter_json(carrier)
```

Reset the three generalized binding globals in
`remove_parameter_carrier`. Generalize `_pending_binding` to include target
kind/key and source bone. Generalize `_active_parameter_refs` to return the
pose bone named `_bound_source_bone_name` from the helper so Rigify
collection-ref add/remove works in both parameter panels.

Add `request_rule_parameter_carrier(source, rule, rule_index)` as the timer-safe
equivalent of `prepare_rule_parameter_carrier`: resolve the first match, store
`("RULE", rule.rule_id, source_bone_name)` in `_pending_binding`, and let
`_load_pending_parameter_carrier` resolve the rule by ID before calling the
shared prepare function. Return `False` without scheduling when the rule does
not match.

- [ ] **Step 4: Implement rule operators**

Add UUID-backed rule creation:

```python
class RERIGIFY_OT_BoneRuleAdd(bpy.types.Operator):
    bl_idname = "re_rigify.bone_rule_add"
    bl_label = "Add Bone Matching Rule"
    bl_options = {"UNDO"}

    def execute(self, context):
        import uuid
        from .ui import flush_parameter_carrier, remove_parameter_carrier
        flush_parameter_carrier()
        remove_parameter_carrier()
        settings = active_armature(context).data.re_rigify
        rule = settings.bone_rules.add()
        rule.rule_id = uuid.uuid4().hex
        rule.kind = "GLOB"
        rule.pattern = "*"
        types = available_rig_types()
        rule.rigify_type = (
            "basic.raw_copy" if "basic.raw_copy" in types
            else (types[0] if types else "")
        )
        settings.active_bone_rule_index = len(settings.bone_rules) - 1
        return {"FINISHED"}
```

Add the remaining operators:

```python
class RERIGIFY_OT_BoneRuleRemove(bpy.types.Operator):
    bl_idname = "re_rigify.bone_rule_remove"
    bl_label = "Remove Bone Matching Rule"
    bl_options = {"UNDO"}

    def execute(self, context):
        from .rules import sync_bone_rules
        from .ui import flush_parameter_carrier, remove_parameter_carrier
        settings = active_armature(context).data.re_rigify
        if not settings.bone_rules:
            return {"CANCELLED"}
        flush_parameter_carrier()
        remove_parameter_carrier()
        settings.bone_rules.remove(settings.active_bone_rule_index)
        settings.active_bone_rule_index = min(
            settings.active_bone_rule_index,
            max(0, len(settings.bone_rules) - 1),
        )
        sync_bone_rules(settings.id_data)
        return {"FINISHED"}


class RERIGIFY_OT_BoneRuleMove(bpy.types.Operator):
    bl_idname = "re_rigify.bone_rule_move"
    bl_label = "Move Bone Matching Rule"
    bl_options = {"UNDO"}
    direction: IntProperty()

    def execute(self, context):
        from .ui import flush_parameter_carrier, remove_parameter_carrier
        settings = active_armature(context).data.re_rigify
        source = settings.active_bone_rule_index
        target = source + self.direction
        if not 0 <= source < len(settings.bone_rules):
            return {"CANCELLED"}
        if not 0 <= target < len(settings.bone_rules):
            return {"CANCELLED"}
        flush_parameter_carrier()
        remove_parameter_carrier()
        settings.bone_rules.move(source, target)
        settings.active_bone_rule_index = target
        return {"FINISHED"}


class RERIGIFY_OT_BoneRuleSync(bpy.types.Operator):
    bl_idname = "re_rigify.bone_rule_sync"
    bl_label = "Sync Bone Matching Rules"
    bl_options = {"UNDO"}

    def execute(self, context):
        from .rules import sync_bone_rules
        from .ui import flush_parameter_carrier, remove_parameter_carrier
        obj = active_armature(context)
        flush_parameter_carrier()
        remove_parameter_carrier()
        try:
            added, updated, removed = sync_bone_rules(obj.data)
        except (ConfigError, json.JSONDecodeError) as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Rules added {added}, updated {updated}, removed {removed} bones",
        )
        return {"FINISHED"}
```

Register all four classes in `CLASSES`.

- [ ] **Step 5: Implement rule UI and managed-row locking**

Add the list and panels:

```python
class RERIGIFY_UL_BoneRules(bpy.types.UIList):
    def draw_item(
        self, _context, layout, _data, item, _icon,
        _active_data, _active_propname, _index,
    ):
        layout.label(
            text=item.pattern or "Empty",
            icon="FILTER",
            translate=False,
        )
        layout.label(
            text=item.rigify_type or "No type",
            translate=False,
        )


class RERIGIFY_PT_BoneRules(_RERIGIFY_PT_Base, bpy.types.Panel):
    bl_label = "Bone Matching Rules"
    bl_idname = "RERIGIFY_PT_bone_rules"
    bl_parent_id = "RERIGIFY_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.object.data.re_rigify
        row = layout.row()
        row.template_list(
            "RERIGIFY_UL_BoneRules", "",
            settings, "bone_rules",
            settings, "active_bone_rule_index",
            rows=4,
        )
        buttons = row.column(align=True)
        buttons.operator("re_rigify.bone_rule_add", text="", icon="ADD")
        buttons.operator("re_rigify.bone_rule_remove", text="", icon="REMOVE")
        up = buttons.operator(
            "re_rigify.bone_rule_move", text="", icon="TRIA_UP",
        )
        up.direction = -1
        down = buttons.operator(
            "re_rigify.bone_rule_move", text="", icon="TRIA_DOWN",
        )
        down.direction = 1
        if settings.bone_rules:
            rule = settings.bone_rules[settings.active_bone_rule_index]
            layout.prop(rule, "kind")
            layout.prop(rule, "pattern")
            refresh_rigify_types(context)
            layout.prop_search(
                rule, "rigify_type",
                context.window_manager, "rigify_types",
                text="Rig Type",
            )
        layout.operator("re_rigify.bone_rule_sync", icon="FILE_REFRESH")


class RERIGIFY_PT_BoneRuleParameters(
    _RERIGIFY_PT_Base, bpy.types.Panel,
):
    bl_label = "Rule Parameters"
    bl_idname = "RERIGIFY_PT_bone_rule_parameters"
    bl_parent_id = "RERIGIFY_PT_bone_rules"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.object
        settings = obj.data.re_rigify
        if not settings.bone_rules:
            layout.label(text="No bone rule", icon="INFO")
            return
        index = settings.active_bone_rule_index
        rule = settings.bone_rules[index]
        carrier = get_rule_parameter_carrier(obj, rule, index)
        if carrier is None:
            if not request_rule_parameter_carrier(obj, rule, index):
                layout.label(text="Rule matches no bones", icon="ERROR")
            else:
                layout.label(text="Loading Rigify parameters…", icon="TIME")
            return
        parameter_layout = RigifyParameterLayout(layout.column())
        draw_parameters(parameter_layout, carrier)
        layout.label(text="Parameters save automatically", icon="CHECKMARK")
```

Register the list before panels and register both panels with the other panel
classes.

In the bone panel:

```python
managed = bool(item.managed_rule_id)
fields = layout.column()
fields.enabled = not managed
fields.prop_search(item, "bone_name", obj.data, "bones", text="Bone")
fields.prop_search(
    item, "rigify_type", context.window_manager, "rigify_types",
    text="Rig Type",
)
if managed:
    layout.label(text="Managed by a bone rule", icon="LOCKED")
```

Hide chain and compatibility editors for managed rows. In the ordinary Bone
Parameters panel, show the lock message instead of creating a bone carrier.
The Rule Parameters panel uses the rule carrier and existing
`RigifyParameterLayout`.

- [ ] **Step 6: Verify GREEN and commit**

Run pure tests and the Blender MCP rule add/move/sync/carrier scenario.

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk git diff --check
rtk jj commit -m "feat(ui): edit persistent bone rules"
```

---

### Task 5: Collection Rename Propagation and Generated Visibility

**Files:**
- Modify: `re_rigify/blender_config.py`
- Modify: `re_rigify/operators.py`
- Modify: `re_rigify/ui.py`
- Modify: `re_rigify/generate.py`
- Test: `tests/test_core.py`
- Test: `tests/blender_integration.py`

**Interfaces:**
- Produces:
  - `collection.visible_after_generation`
  - hidden `collection.last_valid_name`
  - `apply_generated_collection_visibility(rig, collections)`
- Consumes: Task 2 `rename_collection_references`.

- [ ] **Step 1: Add failing rename and visibility integration tests**

Add:

```python
bone.parameters_json = json.dumps({
    "fk_coll_refs": ["Old FK"],
    "tweak_coll_refs": ["Old FK"],
})
rule.parameters_json = json.dumps({"fk_coll_refs": ["Old FK"]})
collection.last_valid_name = "Old FK"
collection.name = "Renamed FK"
assert json.loads(bone.parameters_json)["fk_coll_refs"] == ["Renamed FK"]
assert json.loads(rule.parameters_json)["fk_coll_refs"] == ["Renamed FK"]
```

Add a generation helper assertion:

```python
apply_generated_collection_visibility(rig, [
    {"name": "Visible", "visible_after_generation": True},
    {"name": "Hidden", "visible_after_generation": False},
])
assert rig.data.collections_all["Visible"].is_visible
assert not rig.data.collections_all["Hidden"].is_visible
```

- [ ] **Step 2: Verify RED through Blender MCP**

Expected: references retain `Old FK`; visibility helper is missing.

- [ ] **Step 3: Add rename callback with suspension**

Add `_collection_rename_updates_suspended` and a context manager parallel to
carrier suspension. Import `rename_collection_references` from `.core`. Define:

```python
def _rename_collection(item, context):
    if _collection_rename_updates_suspended:
        return
    settings = item.id_data.re_rigify
    old_name = item.last_valid_name
    new_name = item.name
    if (
        not old_name or not new_name or old_name == new_name
        or any(other != item and other.name == new_name
               for other in settings.collections)
    ):
        return
    from .ui import flush_parameter_carrier, remove_parameter_carrier
    flush_parameter_carrier()
    remove_parameter_carrier()
    for bone in settings.bones:
        parameters = json.loads(bone.parameters_json or "{}")
        bone.parameters_json = json.dumps(
            rename_collection_references(parameters, old_name, new_name),
            ensure_ascii=False, sort_keys=True,
        )
    for rule in settings.bone_rules:
        parameters = json.loads(rule.parameters_json or "{}")
        rule.parameters_json = json.dumps(
            rename_collection_references(parameters, old_name, new_name),
            ensure_ascii=False, sort_keys=True,
        )
    item.last_valid_name = new_name
```

Attach the rename callback and hidden valid-name field to the collection class;
keep the visibility property added in Task 3:

```python
name: StringProperty(name="Collection", update=_rename_collection)
last_valid_name: StringProperty(default="", options={"HIDDEN"})
```

Bulk loading uses both suspension context managers and assigns
`last_valid_name = source["name"]` after `name`.

Collection add initializes `last_valid_name`. Duplicate copies visibility and
sets its new last-valid name. Extend collection removal after its existing bone
loop:

```python
for rule in settings.bone_rules:
    parameters = json.loads(rule.parameters_json or "{}")
    rule.parameters_json = json.dumps(
        remove_collection_references(parameters, name),
        ensure_ascii=False,
        sort_keys=True,
    )
```

- [ ] **Step 4: Apply visibility**

In `apply_collection_config`, after creating/getting each collection:

```python
collection.is_visible = source.get("visible_after_generation", True)
```

Add:

```python
def apply_generated_collection_visibility(rig, collections):
    for source in collections:
        collection = rig.data.collections_all.get(source["name"])
        if collection is not None:
            collection.is_visible = source.get(
                "visible_after_generation", True,
            )
```

Call it in `generate_rig` immediately after Rigify returns and `result_obj` is
resolved, before drive-map helpers are built. Add the checkbox below the
collection name:

```python
layout.prop(collection, "visible_after_generation")
```

- [ ] **Step 5: Verify GREEN and commit**

Run pure tests and an MCP armature rename/visibility test. Confirm invalid
duplicate rename leaves references unchanged.

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk git diff --check
rtk jj commit -m "feat(collections): track rename and visibility"
```

---

### Task 6: Workflow Synchronization, Canonical Export, and Full Generation

**Files:**
- Modify: `re_rigify/operators.py`
- Modify: `re_rigify/ui.py`
- Modify: `re_rigify/blender_config.py`
- Modify: `tests/blender_integration.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `sync_bone_rules`, `armature_to_payload(include_managed=...)`,
  safe payload loading, collection rename, and visibility.
- Produces: synchronized import/validate/export/generate workflows.

- [ ] **Step 1: Add failing workflow assertions**

In Blender integration, create one rule and assert:

```python
obj, errors = validate_active(bpy.context)
assert not errors
assert any(item.managed_rule_id for item in obj.data.re_rigify.bones)

canonical = armature_to_payload(obj.data, include_managed=False)
resolved = armature_to_payload(obj.data, include_managed=True)
assert len(canonical["bones"]) < len(resolved["bones"])
assert canonical["bone_rules"]
```

Load the canonical payload into a second compatible armature and assert its
managed rows are regenerated from its bone names.

- [ ] **Step 2: Verify RED through Blender MCP**

Expected: workflows do not yet synchronize or choose canonical/resolved mode.

- [ ] **Step 3: Centralize workflow synchronization**

Add:

```python
def synchronized_payload(obj, include_managed=True):
    from .rules import sync_bone_rules
    from .ui import flush_parameter_carrier, remove_parameter_carrier
    flush_parameter_carrier()
    remove_parameter_carrier()
    sync_bone_rules(obj.data)
    return armature_to_payload(
        obj.data, include_managed=include_managed,
    )
```

In `validate_active`, catch `(ConfigError, ValueError, json.JSONDecodeError)`
from synchronization and return the message as one validation error. Otherwise
use:

```python
payload = synchronized_payload(obj, include_managed=True)
```

Generation uses the same resolved call. Export calls validation first, then
writes:

```python
json.dumps(
    synchronized_payload(obj, include_managed=False),
    ensure_ascii=False,
    indent=2,
) + "\n"
```

Import validates canonical and resolved forms before mutating RNA:

```python
payload = normalize_config(payload)
resolved = materialize_bone_rules(payload, obj.data.bones.keys())
result = validate_config(payload, obj.data.bones.keys(), available_rig_types())
errors = list(result.errors)
if not errors:
    errors.extend(validate_compatibility(obj, resolved["bones"]))
if not errors:
    errors.extend(validate_bone_parameters(
        context, obj, resolved["bones"], resolved["collections"],
    ))
if errors:
    obj.data.re_rigify.validation_message = "\n".join(errors)
    self.report({"ERROR"}, f"Import rejected with {len(errors)} error(s)")
    return {"CANCELLED"}
payload_to_armature(obj.data, payload)
```

Update save-pre to flush/remove only; rule rows are already RNA data and do not
require mutation during Blender serialization.

- [ ] **Step 4: Add README documentation**

Document:

- rule order and last-match precedence;
- manual Sync Rules and automatic workflow synchronization;
- managed-row locks;
- collection rename propagation;
- generated visibility;
- canonical rule export;
- collection-reference preservation.

- [ ] **Step 5: Run full tests**

```bash
rtk python3 -m py_compile re_rigify/*.py tests/*.py
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk git diff --check
```

Expected: all tests pass.

- [ ] **Step 6: Run full Blender MCP integration**

Using only the connected Blender MCP:

1. Snapshot every current Re-Rigify payload canonically.
2. Unregister, reload `core`, `compatibility`, `rigify_adapter`,
   `blender_config`, `rules`, `drive`, `generate`, `operators`, and `ui`.
3. Register and restore snapshots.
4. Run rule precedence, sync, carrier, rename, reference-preservation, and
   visibility tests on temporary datablocks.
5. Generate a temporary two-bone or limb rig with FK/Tweak collection
   references and assert generated same-named collections contain bones.
6. Delete only temporary datablocks and remove the carrier.

- [ ] **Step 7: Commit**

```bash
rtk jj commit -m "feat(config): synchronize persistent rules"
```

---

### Task 7: Repair and Regenerate the Current Project

**Files:**
- No repository file changes unless verification reveals a regression.

**Interfaces:**
- Consumes: all completed functionality.
- Produces: corrected in-memory current Blender project and verification
  evidence.

- [ ] **Step 1: Snapshot current configuration and neutral pose**

Through Blender MCP, capture:

- canonical Re-Rigify payload;
- generated rig object name;
- `matrix_basis` for generated `hips`;
- source bind matrices for all 277 pose bones.

Do not save the `.blend`.

- [ ] **Step 2: Restore the unambiguous four-limb references**

Update only:

```python
repairs = {
    "Arm_L": ("Arm FK Left", "Arm Tweaks Left"),
    "Arm_R": ("Arm FK Right", "Arm Tweaks Right"),
    "Thigh_L": ("Leg FK Left", "Leg Tweaks Left"),
    "Thigh_R": ("Leg FK Right", "Leg Tweaks Right"),
}
```

For each bone, preserve all other parameters and set:

```python
parameters["fk_layers_extra"] = True
parameters["fk_coll_refs"] = [fk_name]
parameters["tweak_layers_extra"] = True
parameters["tweak_coll_refs"] = [tweak_name]
```

Remove the carrier after writing JSON.

- [ ] **Step 3: Validate, generate, and verify**

Use the add-on's resolved payload, `generate_rig`, and
`connect_source_to_rig`. Assert:

```python
assert mapped == 277
assert unmatched == []
assert bind_max_delta < 1e-5
for name in (
    "Arm FK Left", "Arm FK Right", "Arm Tweaks Left", "Arm Tweaks Right",
    "Leg FK Left", "Leg FK Right", "Leg Tweaks Left", "Leg Tweaks Right",
):
    assert len(generated.data.collections_all[name].bones) > 0
```

Also verify every collection's `is_visible` equals its configured
`visible_after_generation`.

- [ ] **Step 4: Restore test pose and clean helper state**

Restore any changed generated pose basis, update the view layer, and remove
`__ReRigify_Parameter_Carrier__`. Confirm the source remains driven and the
explicit torso chain remains:

```python
["Hip", "Waist", "Spine", "Chest"]
```

- [ ] **Step 5: Final repository verification**

```bash
rtk python3 -m py_compile re_rigify/*.py tests/*.py
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk git diff --check
rtk jj status
```

Expected: all tests pass and jj working copy is clean after any final commit.
