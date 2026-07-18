# Explicit Chain and Drive Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit linear metarig chains, make drive cleanup context-safe, and remove the temporary parameter carrier before saving.

**Architecture:** Schema version 1 stores an optional ordered `chain_bones` list per Rigify root. Core topology planning converts it into the same connection operations already consumed by Blender generation. Blender UI stores ordered chain entries; drive and carrier lifecycle changes remain isolated in their existing modules.

**Tech Stack:** Python 3, Blender 5.2/Rigify, Blender RNA, `unittest`, Blender background integration tests, jj.

## Global Constraints

- Support Blender 4.2 or newer.
- Never mutate source rest transforms or mesh binding.
- Do not import MikuMikuRig presets.
- Empty explicit chains retain current inferred topology.
- Explicit chains are linear and connected.
- Save authoritative parameters in `parameters_json`, never in the carrier.

---

### Task 1: Version and Store Explicit Chains

**Files:**
- Modify: `re_rigify/core.py`
- Modify: `re_rigify/blender_config.py`
- Modify: `re_rigify/operators.py`
- Modify: `re_rigify/ui.py`
- Test: `tests/test_core.py`
- Test: `tests/test_ui_source.py`
- Test: `tests/blender_integration.py`

**Interfaces:**
- Produces: normalized bone field `chain_bones: list[str]`.
- Produces: `RERIGIFY_PG_ChainBone.bone_name`.
- Produces: chain add, remove, and move operators.

- [ ] **Step 1: Add failing schema tests**

```python
def test_version_one_defaults_to_empty_explicit_chain(self):
    result = normalize_config(self.payload(schema_version=1))
    self.assertEqual(result["schema_version"], 1)
    self.assertEqual(result["bones"][0]["chain_bones"], [])

def test_version_one_round_trips_explicit_chain(self):
    payload = self.payload(schema_version=1)
    payload["bones"][0]["chain_bones"] = ["Hip", "Waist", "Spine"]
    self.assertEqual(normalize_config(payload)["bones"][0]["chain_bones"],
                     ["Hip", "Waist", "Spine"])
```

Add validation cases for root mismatch, missing bones, duplicate entries, and fewer than
three bones for `spines.basic_spine`.

- [ ] **Step 2: Verify schema tests fail**

Run:

```bash
rtk python3 -m unittest tests.test_core.ConfigValidationTests -v
```

Expected: failures because `chain_bones` is unsupported.

- [ ] **Step 3: Implement schema normalization and validation**

Keep `SCHEMA_VERSION = 1`, normalize missing lists to `[]`, and validate:

```python
chain_bones = _require_type(item.get("chain_bones", []), list, path)
if any(not isinstance(name, str) for name in chain_bones):
    raise ConfigError(f"{path} must contain bone names")
```

Validation requires chain root equality, unique existing names, supported linear type,
and the type's minimum length.

- [ ] **Step 4: Add failing Blender storage and UI tests**

Extend `tests/blender_integration.py` to load a chain through `payload_to_armature`, inspect
ordered RNA entries, and round-trip through `armature_to_payload`. Extend AST tests to
require chain operator registration and chain UI rendering.

- [ ] **Step 5: Verify Blender/UI tests fail**

Run:

```bash
rtk python3 -m unittest tests.test_ui_source -v
```

Then run the focused storage check through connected Blender MCP
`execute_blender_code`. Expected: missing chain RNA and operator assertions fail.

- [ ] **Step 6: Implement RNA, operators, mirroring, and UI**

Add:

```python
class RERIGIFY_PG_ChainBone(bpy.types.PropertyGroup):
    bone_name: StringProperty(name="Bone")
```

Add `chain_bones`, `active_chain_index` to each bone config. Serialize ordered names.
Import recreates entries. Mirror snapshots and maps every chain name through Rigify
`mirror_name`. Bone Setup shows a list with add-selected, remove, and move buttons.

- [ ] **Step 7: Verify Task 1**

Run the unit command from Step 5 and the connected Blender MCP storage check, then:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
```

- [ ] **Step 8: Commit**

```bash
rtk jj commit -m "feat(config): add explicit bone chains"
```

### Task 2: Generate from Explicit Chain Topology

**Files:**
- Modify: `re_rigify/core.py`
- Modify: `re_rigify/generate.py`
- Test: `tests/test_core.py`
- Test: `tests/blender_generate.py`

**Interfaces:**
- Consumes: normalized `chain_bones`.
- Produces: `explicit_chain_operations(config) -> list[tuple[str, str, bool]]`.

- [ ] **Step 1: Add failing topology test**

```python
def test_explicit_spine_chain_overrides_source_parenting(self):
    configs = [{
        "bone_name": "Hip",
        "rigify_type": "spines.basic_spine",
        "chain_bones": ["Hip", "Waist", "Spine", "Chest"],
    }]
    parents = {"Hip": "Position", "Waist": "UpBody", "Spine": "Waist", "Chest": "Spine"}
    self.assertEqual(infer_rigify_topology(configs, parents), [
        ("Hip", "Waist", True),
        ("Waist", "Spine", True),
        ("Spine", "Chest", True),
    ])
```

- [ ] **Step 2: Verify RED**

```bash
rtk python3 -m unittest tests.test_core.ConfigValidationTests.test_explicit_spine_chain_overrides_source_parenting -v
```

Expected: inferred chain does not start at `Hip`.

- [ ] **Step 3: Implement explicit operation precedence**

At the start of each `infer_rigify_topology` item:

```python
chain = config.get("chain_bones", [])
if chain:
    operations.extend((parent, child, True) for parent, child in zip(chain, chain[1:]))
    continue
```

Continue using `apply_connection_operations`, which preserves child heads and aligns
parent tails.

- [ ] **Step 4: Add Blender MCP UMA regression**

Through connected Blender MCP, create a temporary armature in a temporary collection with
disconnected `Hip`, `Waist`, `Spine`, `Chest` bones, configure `Hip` as
`spines.basic_spine`, generate, connect, and assert:

```python
before = source.pose.bones["Hip"].matrix.copy()
rig.pose.bones["hips"].rotation_mode = "XYZ"
rig.pose.bones["hips"].rotation_euler.z = 0.25
bpy.context.view_layer.update()
assert matrix_delta(source.pose.bones["Hip"].matrix, before) > 1e-4
```

Also assert all source bind matrices remain unchanged immediately after connection.

- [ ] **Step 5: Verify Task 2**

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Run the UMA check through connected Blender MCP and remove all temporary datablocks in a
`finally` block.

- [ ] **Step 6: Commit**

```bash
rtk jj commit -m "feat(rig): generate explicit metarig chains"
```

### Task 3: Make Drive Helper Removal Context-Safe

**Files:**
- Modify: `re_rigify/drive.py`
- Modify: `re_rigify/generate.py`
- Modify: `re_rigify/operators.py`
- Test: `tests/blender_integration.py`

**Interfaces:**
- Produces: context-safe `remove_drive_helpers(rig) -> int`.
- Produces: Remove Drive operator error reporting.

- [ ] **Step 1: Add failing context regression**

Through connected Blender MCP, create temporary source and rig objects, create helpers,
leave the source in Pose Mode, deselect the generated rig, clear the view-layer active
object, call `remove_drive_constraints(source)`, and assert helper bones are removed and
prior valid state restored.

Add a pure helper test or focused MCP check proving `generate_rig` context restoration
skips stale `StructRNA` references after temporary metarigs are deleted.

- [ ] **Step 2: Verify RED**

Run through connected Blender MCP. Expected: `bpy.ops.object.mode_set.poll()` failure,
failed context restoration, or stale `StructRNA` `ReferenceError`.

- [ ] **Step 3: Implement explicit edit context**

Validate view-layer membership, unhide the rig, set selection, then wrap mode operators:

```python
with context.temp_override(
    object=rig,
    active_object=rig,
    selected_objects=[rig],
    selected_editable_objects=[rig],
):
    bpy.ops.object.mode_set(mode="EDIT")
    # remove MCH-RR-Drive-* edit bones
    bpy.ops.object.mode_set(mode="OBJECT")
```

Harden `_restore_object_context` against removed objects, excluded objects, and invalid
non-Object modes. Store previous selection by object name in `generate_rig` so deleted
metarig references are never dereferenced. Catch operator failures in
`RERIGIFY_OT_RemoveDrive`, report the error, and return `CANCELLED`.

- [ ] **Step 4: Verify Task 3**

Run the focused cleanup checks through connected Blender MCP.

- [ ] **Step 5: Commit**

```bash
rtk jj commit -m "fix(drive): stabilize helper cleanup context"
```

### Task 4: Remove Parameter Carrier Before Save

**Files:**
- Modify: `re_rigify/ui.py`
- Test: `tests/blender_integration.py`

**Interfaces:**
- Produces: `_save_pre(_filepath)` that flushes and removes the carrier.

- [ ] **Step 1: Add failing lifecycle test**

Create a carrier, mutate one Rigify parameter, invoke `_save_pre("")`, then assert its
JSON changed and `HELPER_NAME` no longer exists. Recreate it and assert the parameter
matches serialized JSON.

- [ ] **Step 2: Verify RED**

Run through connected Blender MCP. Expected: carrier still exists after `_save_pre`.

- [ ] **Step 3: Implement save cleanup**

```python
def _save_pre(_filepath):
    flush_parameter_carrier()
    remove_parameter_carrier()
```

Keep on-demand recreation unchanged.

- [ ] **Step 4: Verify Task 4**

Run the carrier lifecycle check through connected Blender MCP.

- [ ] **Step 5: Commit**

```bash
rtk jj commit -m "fix(ui): drop parameter carrier before save"
```

### Task 5: Documentation and Live UMA Verification

**Files:**
- Modify: `README.md`
- Modify in Blender: current UMA source configuration only

**Interfaces:**
- Consumes: explicit chain UI and generation.
- Produces: current open project with `Hip` spine root and working `hips`.

- [ ] **Step 1: Update README**

Document schema 1 explicit linear chains, carrier lifecycle, and context-safe
drive removal. Correct obsolete local-drive text to describe world-space adapter helpers.

- [ ] **Step 2: Run full fresh verification**

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk git diff --check
```

Run storage, UMA generation, drive cleanup, stale-selection, carrier lifecycle, and
extension-entry checks through connected Blender MCP. Expected: all checks pass.

- [ ] **Step 3: Apply current UMA configuration through Blender MCP**

Replace the source armature's `Waist = spines.basic_spine` row with
`Hip = spines.basic_spine`, populate `Hip, Waist, Spine, Chest`, regenerate, and verify:

- source bind pose unchanged after connection
- Rigify `hips` rotation changes source `Hip`
- Remove Drive succeeds from Pose Mode
- no parameter carrier remains after save-handler simulation

- [ ] **Step 4: Commit docs**

```bash
rtk jj commit -m "docs: explain explicit chain workflow"
```

- [ ] **Step 5: Inspect final state**

```bash
rtk jj status
rtk jj log -r '@-|@--|@---|@----|@-----' --no-graph
```

Expected: empty working copy and four focused implementation commits after the plan.
