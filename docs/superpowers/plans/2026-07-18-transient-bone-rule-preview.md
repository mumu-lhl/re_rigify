# Transient Bone Rule Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove rule-matched bones from the ordinary bone list and show the active rule's final effective matches in a read-only preview.

**Architecture:** Bone rules remain canonical stored data. Core functions resolve effective preview rows and materialize temporary generation rows; Blender-side cleanup removes old managed rows and conflicting manual rows without recreating them. UI preview reads the armature's real bones and resolver output, while driver helpers derive chain members directly from rules.

**Tech Stack:** Python 3, Blender 5.2 RNA/UI API, Rigify, `unittest`, Blender MCP, Jujutsu

## Global Constraints

- Preset schema remains unchanged.
- Later bone rules override earlier rules.
- Ordinary bone configuration stores manual rows only.
- Rule preview displays only the active rule's final effective matches.
- Rule matches are never cached or saved as bone configuration rows.
- Existing `managed_rule_id` rows are treated as migration data and removed.
- Do not launch a Blender process; all Blender runtime verification uses the connected Blender MCP.
- Do not save the user's currently open `.blend`.

---

### Task 1: Pure Effective Preview Resolution

**Files:**
- Modify: `re_rigify/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `resolve_bone_rule_rows(bone_names, rules, parents, aligned_edges) -> list[dict]`
- Produces: `preview_bone_rule(bone_names, rules, rule_id, parents=None, aligned_edges=None) -> dict`
- Return shape: `{"bone_names": list[str], "chain_count": int, "rows": list[dict]}`

- [ ] **Step 1: Write failing preview tests**

Add tests covering final precedence, normal rules, chain flattening, and fully
overridden rules:

```python
def test_preview_contains_only_final_effective_matches(self):
    rules = [
        self.rule(rule_id="all", pattern="Hair*"),
        self.rule(rule_id="tip", kind="EXACT", pattern="Hair_02"),
    ]
    preview = preview_bone_rule(
        ["Root", "Hair_01", "Hair_02"], rules, "all",
    )
    self.assertEqual(preview["bone_names"], ["Hair_01"])
    self.assertEqual(preview["chain_count"], 0)

def test_chain_preview_flattens_root_to_child(self):
    preview = preview_bone_rule(
        ["Head", "Hair_00", "Hair_01", "Hair_02"],
        [self.rule(apply_as_chain=True)],
        "hair",
        {
            "Head": None,
            "Hair_00": "Head",
            "Hair_01": "Hair_00",
            "Hair_02": "Hair_01",
        },
        {("Hair_00", "Hair_01"), ("Hair_01", "Hair_02")},
    )
    self.assertEqual(
        preview["bone_names"], ["Hair_00", "Hair_01", "Hair_02"],
    )
    self.assertEqual(preview["chain_count"], 1)

def test_fully_overridden_rule_has_empty_preview(self):
    rules = [
        self.rule(rule_id="first", pattern="Hair*"),
        self.rule(rule_id="second", pattern="Hair*"),
    ]
    preview = preview_bone_rule(["Hair_00", "Hair_01"], rules, "first")
    self.assertEqual(preview["bone_names"], [])
    self.assertEqual(preview["rows"], [])
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
rtk python3 -m unittest tests.test_core.ChainBoneRuleTests
```

Expected: failure because `preview_bone_rule` does not exist.

- [ ] **Step 3: Implement preview resolution**

Add to `re_rigify/core.py`:

```python
def preview_bone_rule(
    bone_names,
    rules,
    rule_id,
    parents=None,
    aligned_edges=None,
):
    rows = resolve_bone_rule_rows(
        bone_names, rules, parents, aligned_edges,
    )
    selected = [
        row for row in rows
        if row["rule"]["rule_id"] == rule_id
    ]
    bone_names = [
        bone_name
        for row in selected
        for bone_name in (row["chain_bones"] or [row["bone_name"]])
    ]
    return {
        "bone_names": bone_names,
        "chain_count": sum(
            bool(row["chain_bones"]) for row in selected
        ),
        "rows": selected,
    }
```

Export/import the function where tests require it.

- [ ] **Step 4: Run pure tests**

Run:

```bash
rtk python3 -m unittest tests.test_core
```

Expected: all core tests pass.

- [ ] **Step 5: Commit**

```bash
rtk jj commit -m "feat(core): preview effective bone rules"
```

---

### Task 2: Stop Persisting Materialized Rule Rows

**Files:**
- Modify: `re_rigify/rules.py`
- Modify: `re_rigify/operators.py`
- Modify: `re_rigify/drive.py`
- Modify: `tests/blender_integration.py`
- Test: `tests/test_ui_source.py`

**Interfaces:**
- Consumes: `materialize_bone_rules(payload, bone_names, parents, aligned_edges) -> dict`
- Produces: `cleanup_bone_rule_rows(armature) -> int`
- Produces: `resolved_rule_payload(obj) -> dict` through existing `synchronized_payload(obj, include_managed=True)`
- Produces: `_chain_rule_bone_names(source) -> set[str]` without reading `managed_rule_id`

- [ ] **Step 1: Write failing cleanup and payload tests**

Change Blender integration expectations so synchronization never creates rule
rows:

```python
legacy = chain_settings.bones.add()
legacy.bone_name = "HairA_00"
legacy.managed_rule_id = "hair"
manual_claimed = chain_settings.bones.add()
manual_claimed.bone_name = "HairB_00"
manual_claimed.rigify_type = "basic.raw_copy"

removed = cleanup_bone_rule_rows(chain_source.data)
assert removed == 2
assert list(chain_settings.bones) == []

canonical = synchronized_payload(chain_source, include_managed=False)
resolved = synchronized_payload(chain_source, include_managed=True)
assert canonical["bones"] == []
assert [item["bone_name"] for item in resolved["bones"]] == [
    "HairA_00", "HairB_00",
]
assert list(chain_settings.bones) == []
```

Add a source-level regression assertion that `sync_bone_rules` no longer calls
`settings.bones.add()`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
rtk python3 -m unittest tests.test_ui_source
```

Expected: failure because cleanup-only synchronization is not implemented.

Use Blender MCP to run the focused integration block. Expected before the
change: rule rows appear in `settings.bones`.

- [ ] **Step 3: Replace row synchronization with cleanup**

In `re_rigify/rules.py`:

```python
def cleanup_bone_rule_rows(armature) -> int:
    settings = armature.re_rigify
    rules = rule_dicts(settings)
    claimed = set()
    if rules:
        try:
            claimed = set(resolve_bone_rules(armature.bones.keys(), rules))
        except ConfigError:
            claimed = set()
    remove_indices = [
        index
        for index, item in enumerate(settings.bones)
        if item.managed_rule_id or item.bone_name in claimed
    ]
    with suspend_carrier_updates():
        for index in reversed(remove_indices):
            settings.bones.remove(index)
        settings.active_bone_index = min(
            settings.active_bone_index,
            max(0, len(settings.bones) - 1),
        )
    return len(remove_indices)


def sync_bone_rules(armature) -> tuple[int, int, int]:
    removed = cleanup_bone_rule_rows(armature)
    return 0, 0, removed
```

Keep `sync_bone_rules` as a compatibility wrapper for registered operators and
existing callers.

- [ ] **Step 4: Materialize only the returned payload**

Change `synchronized_payload` in `re_rigify/operators.py`:

```python
def synchronized_payload(obj, include_managed=True):
    from .rules import armature_rule_topology, cleanup_bone_rule_rows
    from .ui import flush_parameter_carrier, remove_parameter_carrier

    flush_parameter_carrier()
    remove_parameter_carrier()
    cleanup_bone_rule_rows(obj.data)
    payload = armature_to_payload(obj.data, include_managed=False)
    if not include_managed:
        return payload
    parents, aligned_edges = armature_rule_topology(obj.data)
    return materialize_bone_rules(
        payload,
        obj.data.bones.keys(),
        parents,
        aligned_edges,
    )
```

Rule add, remove, and move operators call `cleanup_bone_rule_rows` after their
mutation. The existing sync button may remain temporarily but must only clean
obsolete rows.

- [ ] **Step 5: Resolve driver chain members directly**

Replace `_chain_rule_bone_names` in `re_rigify/drive.py`:

```python
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
```

Import `resolve_bone_rule_rows` from `core`. Preserve the existing conditional
`inherit_scale` assignment.

- [ ] **Step 6: Run local tests**

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py'
rtk python3 -m py_compile re_rigify/*.py tests/*.py
rtk git diff --check
```

Expected: all local tests pass; compilation and whitespace checks are clean.

- [ ] **Step 7: Commit**

```bash
rtk jj commit -m "refactor(rules): materialize matches transiently"
```

---

### Task 3: Add Stateless Effective-Match Preview UI

**Files:**
- Modify: `re_rigify/blender_config.py`
- Modify: `re_rigify/rules.py`
- Modify: `re_rigify/ui.py`
- Modify: `re_rigify/operators.py`
- Modify: `README.md`
- Test: `tests/test_ui_source.py`

**Interfaces:**
- Consumes: `preview_bone_rule(...) -> dict`
- Produces: `active_bone_rule_preview(armature) -> dict`
- Produces: `RERIGIFY_UL_BoneRulePreview`
- Adds: `RERIGIFY_PG_ArmatureConfig.active_bone_rule_preview_index: IntProperty`

- [ ] **Step 1: Write failing UI structure tests**

Add AST/source tests:

```python
def test_rule_preview_ui_is_registered(self):
    source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = {
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    }
    self.assertIn("RERIGIFY_UL_BoneRulePreview", classes)
    self.assertIn('"RERIGIFY_UL_BoneRulePreview"', source)
    self.assertIn("active_bone_rule_preview_index", source)

def test_bone_list_filters_managed_rows(self):
    source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    bone_list = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "RERIGIFY_UL_Bones"
    )
    self.assertTrue(any(
        isinstance(node, ast.FunctionDef) and node.name == "filter_items"
        for node in bone_list.body
    ))
    self.assertIn("managed_rule_id", ast.unparse(bone_list))
```

- [ ] **Step 2: Run UI tests and verify RED**

Run:

```bash
rtk python3 -m unittest tests.test_ui_source
```

Expected: failure because the preview UI list and managed-row filter do not
exist.

- [ ] **Step 3: Add active-preview adapter**

In `re_rigify/rules.py`:

```python
def active_bone_rule_preview(armature) -> dict:
    settings = armature.re_rigify
    if not settings.bone_rules:
        return {"bone_names": [], "chain_count": 0, "rows": []}
    index = min(
        settings.active_bone_rule_index,
        len(settings.bone_rules) - 1,
    )
    parents, aligned_edges = armature_rule_topology(armature)
    return preview_bone_rule(
        armature.bones.keys(),
        rule_dicts(settings),
        settings.bone_rules[index].rule_id,
        parents,
        aligned_edges,
    )
```

Update `_rule_source_bone` in `ui.py` to use the active rule's effective
preview instead of resolving that rule in isolation. A fully overridden rule
therefore has no parameter carrier.

- [ ] **Step 4: Filter the ordinary bone list**

Add `filter_items` to `RERIGIFY_UL_Bones`:

```python
def filter_items(self, _context, data, property_name):
    items = getattr(data, property_name)
    flags = [
        0 if item.managed_rule_id else self.bitflag_filter_item
        for item in items
    ]
    return flags, []
```

This hides migration rows immediately while cleanup removes them from stored
configuration.

- [ ] **Step 5: Add the preview UI list**

Register `RERIGIFY_UL_BoneRulePreview`. Its `filter_items` calls
`active_bone_rule_preview(data)` and includes only returned bone names. Build
the reorder array from the returned name order so chain members appear
root-to-child. `draw_item` renders only the actual armature bone name with
`icon="BONE_DATA"` and `translate=False`.

```python
class RERIGIFY_UL_BoneRulePreview(bpy.types.UIList):
    def draw_item(
        self, _context, layout, _data, item, _icon,
        _active_data, _active_propname, _index,
    ):
        layout.label(
            text=item.name, icon="BONE_DATA", translate=False,
        )

    def filter_items(self, _context, data, property_name):
        items = getattr(data, property_name)
        try:
            preview = active_bone_rule_preview(data)
        except (ConfigError, ValueError, json.JSONDecodeError):
            return [0] * len(items), []
        rank = {
            name: index
            for index, name in enumerate(preview["bone_names"])
        }
        flags = [
            self.bitflag_filter_item if item.name in rank else 0
            for item in items
        ]
        desired = sorted(
            range(len(items)),
            key=lambda index: (
                items[index].name not in rank,
                rank.get(items[index].name, index),
            ),
        )
        new_order = [0] * len(items)
        for new_index, old_index in enumerate(desired):
            new_order[old_index] = new_index
        return flags, new_order
```

Add `active_bone_rule_preview_index` to armature settings. In
`RERIGIFY_PT_BoneRules.draw`:

```python
try:
    preview = active_bone_rule_preview(context.object.data)
except (ConfigError, ValueError, json.JSONDecodeError) as exc:
    layout.label(text=str(exc), icon="ERROR", translate=False)
else:
    if rule.apply_as_chain:
        layout.label(
            text=(
                f"{len(preview['bone_names'])} bones / "
                f"{preview['chain_count']} chains"
            ),
            icon="LINKED",
            translate=False,
        )
    else:
        layout.label(
            text=f"{len(preview['bone_names'])} bones",
            icon="BONE_DATA",
            translate=False,
        )
    layout.template_list(
        "RERIGIFY_UL_BoneRulePreview", "",
        context.object.data, "bones",
        settings, "active_bone_rule_preview_index",
        rows=5,
    )
```

Remove the old synchronization button because preview and resolved payloads
are automatic.

- [ ] **Step 6: Update documentation**

Change README rule workflow text to state:

```markdown
Rule matches stay out of the manual bone list. The active rule preview shows
only final matches after later-rule precedence. Validation and generation
materialize those matches temporarily.
```

- [ ] **Step 7: Run local tests**

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py'
rtk python3 -m py_compile re_rigify/*.py tests/*.py
rtk git diff --check
```

Expected: all tests pass and checks produce no errors.

- [ ] **Step 8: Commit**

```bash
rtk jj commit -m "feat(ui): preview effective bone rule matches"
```

---

### Task 4: Migrate and Verify the Current Blender Project

**Files:**
- Verify: current Blender scene through Blender MCP
- Test: `tests/blender_integration.py`

**Interfaces:**
- Consumes: live extension modules and current source
  `1003_トウカイテイオー_arm`
- Verifies: generated rig `1003_トウカイテイオー_arm_rig`

- [ ] **Step 1: Reload the live extension safely**

Through Blender MCP, snapshot only the current source armature's canonical
payload and object pointers. Unregister the extension, reload its package
modules, register it again, then restore that source payload. Do not restore
orphan armature datablocks and do not save the file.

Expected: source still has the `Sp_He_Hair*` spline-tentacle chain rule with
`apply_as_chain=True`.

- [ ] **Step 2: Verify migration and preview**

Through Blender MCP:

```python
settings = source.data.re_rigify
preview = active_bone_rule_preview(source.data)
result = {
    "stored_bones": len(settings.bones),
    "managed_rows": sum(bool(item.managed_rule_id) for item in settings.bones),
    "preview_bones": len(preview["bone_names"]),
    "preview_chains": preview["chain_count"],
}
```

Expected:

```python
{
    "stored_bones": 20,
    "managed_rows": 0,
    "preview_bones": 22,
    "preview_chains": 7,
}
```

- [ ] **Step 3: Validate and regenerate**

Use the add-on's validation and generation functions through Blender MCP.

Expected:

- no validation errors;
- 277 source bones mapped;
- no unmatched bones;
- all seven `Sp_He_Hair*_master` controls exist;
- source hair children remain disconnected;
- ordinary stored bone count remains 20 after generation.

- [ ] **Step 4: Verify bind pose and driver inheritance**

Through Blender MCP, compare every source pose matrix with its rest matrix.

Expected:

- `Sp_He_Hair4_L_02` maximum component delta remains below `1e-5`;
- all 22 chain-rule helpers use `inherit_scale == "NONE"`;
- `MCH-RR-Drive-Hip` uses `inherit_scale == "FULL"`;
- no parameter carrier object remains.

- [ ] **Step 5: Run final verification**

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py'
rtk python3 -m py_compile re_rigify/*.py tests/*.py
rtk git diff --check
rtk jj status
```

Expected: all tests and checks pass; working copy contains only intended
changes before the final commit.

- [ ] **Step 6: Commit any final integration adjustments**

If Task 4 required source or test changes, commit them:

```bash
rtk jj commit -m "test: verify transient bone rule workflow"
```

If no files changed, do not create an empty commit.
