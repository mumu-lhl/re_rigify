# UI-configurable Super Finger Axis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-bone Compatibility-panel setting for `limbs.super_finger` primary rotation axis with `Automatic` and all six signed cardinal axes, eliminating bone-name-based inference.

**Architecture:** Store the setting as normalized compatibility data and a Blender RNA enum on each configured bone. The compatibility value is authoritative during generation: `AUTO` maps to Rigify's native `automatic`, while explicit values override the temporary metarig's `primary_rotation_axis`. Keep terminal-marker geometry correction separate and geometry-driven, then verify persistence, mirroring, unit behavior, and the current Blender scene through MCP.

**Tech Stack:** Python 3, Blender RNA (`bpy.props.EnumProperty`), Rigify metarig parameters, `unittest`, Blender MCP.

## Global Constraints

- Store compatibility axis values as `AUTO`, `+X`, `-X`, `+Y`, `-Y`, `+Z`, or `-Z`; map `AUTO` to Rigify's lowercase `automatic` and map positive UI values to Rigify's `X`, `Y`, or `Z` identifiers.
- Never inspect `Thumb`, `_L`, `_R`, or another bone-name pattern to select an axis.
- Preserve geometry-based terminal-marker correction and keep it independent from axis selection.
- Preserve unrelated worktree changes; stage only files belonging to the task when committing.
- Do not save or overwrite the user's `.blend` file during Blender MCP verification.
- Follow TDD: each behavior change starts with a failing test and is verified after the minimal implementation.

---

### Task 1: Add the normalized compatibility axis field

**Files:**
- Modify: `re_rigify/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Produces `DEFAULT_COMPATIBILITY["super_finger_primary_axis"] == "AUTO"`.
- `normalize_compatibility(value, path)` accepts exactly `AUTO`, `+X`, `-X`, `+Y`, `-Y`, `+Z`, and `-Z` for the new field and raises `ConfigError` for another value.
- `mirror_compatibility(value, name_mapper)` leaves `AUTO` unchanged and swaps each signed pair.

- [ ] **Step 1: Write the failing tests**

Add tests to `tests/test_core.py` covering defaulting, invalid values, and all mirror mappings:

```python
def test_super_finger_axis_defaults_to_auto(self):
    result = normalize_compatibility({})
    self.assertEqual(result["super_finger_primary_axis"], "AUTO")

def test_super_finger_axis_rejects_unknown_value(self):
    with self.assertRaisesRegex(ConfigError, "super_finger_primary_axis"):
        normalize_compatibility({"super_finger_primary_axis": "Q"})

def test_mirror_compatibility_swaps_every_super_finger_axis(self):
    expected = {
        "AUTO": "AUTO", "+X": "-X", "-X": "+X",
        "+Y": "-Y", "-Y": "+Y", "+Z": "-Z", "-Z": "+Z",
    }
    for source, target in expected.items():
        result = mirror_compatibility(
            {"super_finger_primary_axis": source}, lambda value: value,
        )
        self.assertEqual(result["super_finger_primary_axis"], target)
```

- [ ] **Step 2: Run the focused tests and verify they fail for the missing field**

Run: `rtk python3 -m unittest tests.test_core -v`

Expected: failures because the normalized compatibility result has no
`super_finger_primary_axis` field and mirroring has no signed-axis mapping.

- [ ] **Step 3: Implement the minimal schema behavior**

In `re_rigify/core.py`:

```python
SUPER_FINGER_PRIMARY_AXES = frozenset(
    {"AUTO", "+X", "-X", "+Y", "-Y", "+Z", "-Z"}
)

DEFAULT_COMPATIBILITY = {
    # existing fields...
    "super_finger_primary_axis": "AUTO",
}
```

Validate the field as a string member of `SUPER_FINGER_PRIMARY_AXES` inside
`normalize_compatibility`, and apply the signed-pair map inside
`mirror_compatibility`.

- [ ] **Step 4: Run the focused and full pure-Python tests**

Run: `rtk python3 -m unittest tests.test_core tests.test_compatibility -v`

Expected: PASS for the new tests and all existing tests. Fix implementation
errors without weakening the assertions.

- [ ] **Step 5: Commit the schema change**

```bash
git add re_rigify/core.py tests/test_core.py
git commit -m "feat(config): add finger axis setting"
```

Do not stage `docs/superpowers/plans/2026-08-09-thumb-axis.md` or unrelated
worktree files in this commit.

### Task 2: Expose the axis in Blender RNA and the Compatibility panel

**Files:**
- Modify: `re_rigify/blender_config.py`
- Modify: `re_rigify/ui.py`
- Modify: `re_rigify/translations.py`
- Test: `tests/test_ui_source.py`
- Test: `tests/test_translations.py`

**Interfaces:**
- `RERIGIFY_PG_BoneConfig.super_finger_primary_axis` is an enum with identifiers
  `AUTO`, `+X`, `-X`, `+Y`, `-Y`, `+Z`, and `-Z`, defaulting to `AUTO`.
- `_compatibility_from_item()` serializes the property and
  `_apply_compatibility_to_item()` restores it through normalized compatibility.
- The Compatibility box draws `item.super_finger_primary_axis` only when
  `item.rigify_type == "limbs.super_finger"`.

- [ ] **Step 1: Write source-level failing tests for the RNA/UI contract**

Add AST/source assertions to `tests/test_ui_source.py` that require
`super_finger_primary_axis` in `blender_config.py`, require the seven enum
identifiers and default `AUTO`, and require the Compatibility section in
`ui.py` to draw that property under the `limbs.super_finger` branch.

Add a translation-catalog assertion in `tests/test_translations.py` for the new
label and descriptions. The test must fail before the RNA and UI strings exist.

- [ ] **Step 2: Run the focused tests and verify the expected failures**

Run: `rtk python3 -m unittest tests.test_ui_source tests.test_translations -v`

Expected: FAIL because the property, enum identifiers, UI draw call, and
translation entries are absent.

- [ ] **Step 3: Add the RNA property and payload conversion**

In `RERIGIFY_PG_BoneConfig`, add the enum with user-facing labels:

```python
super_finger_primary_axis: EnumProperty(
    name="Primary Rotation Axis",
    items=(
        ("AUTO", "Automatic", "Use Rigify's native automatic axis selection"),
        ("+X", "+X", "Use positive X as the primary rotation axis"),
        ("-X", "-X", "Use negative X as the primary rotation axis"),
        ("+Y", "+Y", "Use positive Y as the primary rotation axis"),
        ("-Y", "-Y", "Use negative Y as the primary rotation axis"),
        ("+Z", "+Z", "Use positive Z as the primary rotation axis"),
        ("-Z", "-Z", "Use negative Z as the primary rotation axis"),
    ),
    default="AUTO",
)
```

Include the property in `_compatibility_from_item`; the existing normalized
assignment path will restore imported, copied, and mirrored values.

- [ ] **Step 4: Draw the Compatibility control and add translations**

In the existing `limbs.super_finger` Compatibility branch, draw:

```python
compatibility.prop(item, "super_finger_primary_axis")
```

Add Simplified Chinese catalog entries for `Primary Rotation Axis` and the
three axis-direction descriptions. The `Automatic` label already exists; add
the new automatic description and all six axis descriptions so Blender's
translation registration has complete user-facing coverage.

- [ ] **Step 5: Run the focused and full tests**

Run: `rtk python3 -m unittest tests.test_ui_source tests.test_translations tests.test_core -v`

Expected: PASS with no translation or AST errors.

- [ ] **Step 6: Commit the UI/storage change**

```bash
git add re_rigify/blender_config.py re_rigify/ui.py re_rigify/translations.py tests/test_ui_source.py tests/test_translations.py
git commit -m "feat(ui): expose finger axis setting"
```

### Task 3: Make generation consume the configured axis

**Files:**
- Modify: `re_rigify/compatibility.py`
- Test: `tests/test_compatibility.py`

**Interfaces:**
- `plan_super_finger_axis(obj, config)` reads
  `config["compatibility"]["super_finger_primary_axis"]` and never reads the
  root name to choose an axis.
- `FingerAxisPlan.primary_rotation_axis` contains Rigify's value: lowercase
  `automatic` for `AUTO`, `X`/`Y`/`Z` for positive UI settings, or the selected
  negative axis for `-X`/`-Y`/`-Z`.
- The plan distinguishes axis override from marker correction, for example with
  a boolean `fix_marker` field. An explicit axis must produce a plan even when
  the terminal marker is already aligned; `AUTO` may produce a plan only when
  geometry correction is needed.

- [ ] **Step 1: Replace name-based tests with failing behavior tests**

Update `tests/test_compatibility.py` so the new tests assert:

```python
def test_explicit_axis_is_independent_of_bone_name(self):
    result = plan_super_finger_axis(obj_for("Thumb_01_L"), config_with_axis("+Z"))
    self.assertEqual(result.primary_rotation_axis, "Z")

def test_auto_uses_rigify_automatic_for_thumb_names(self):
    result = plan_super_finger_axis(obj_for("Thumb_01_R"), config_with_axis("AUTO"))
    self.assertEqual(result.primary_rotation_axis, "automatic")

def test_explicit_axis_plan_exists_for_an_aligned_chain(self):
    result = plan_super_finger_axis(aligned_obj, config_with_axis("-Y"))
    self.assertEqual(result.primary_rotation_axis, "-Y")
    self.assertFalse(result.fix_marker)
```

Retain a geometry test that uses a non-thumb name with a misaligned terminal
marker and asserts `fix_marker` is true. Remove assertions expecting `Z` or
`-Z` solely because a name contains `Thumb` or a side suffix.

- [ ] **Step 2: Run the focused tests and verify they fail for the old heuristic**

Run: `rtk python3 -m unittest tests.test_compatibility.ConnectedChainPlanningTests -v`

Expected: FAIL because the current implementation returns name-derived axes,
does not create an explicit-axis plan for an aligned chain, and has no separate
marker-correction state.

- [ ] **Step 3: Implement the minimal planning refactor**

In `re_rigify/compatibility.py`:

1. Delete `_automatic_super_finger_axis`.
2. Read and map `super_finger_primary_axis` from normalized compatibility,
   defaulting only for direct callers to `AUTO`.
3. Compute marker misalignment exactly from chain geometry, without using names.
4. Return a plan for every explicit axis and for `AUTO` only when marker
   correction is required.
5. In `apply_compatibility_plan`, edit and call `align_chain_x_axis` only when
   `fix_marker` is true, then set the temporary metarig's
   `primary_rotation_axis` to the plan's Rigify value when the property exists.

Do not modify the unrelated eye or roll compatibility paths.

- [ ] **Step 4: Run the focused tests and then the full unit suite**

Run: `rtk python3 -m unittest tests.test_compatibility -v`

Expected: PASS, including explicit `+Z`, `-Y`, and `AUTO` cases. Then run:
`rtk python3 -m unittest discover -s tests -p 'test_*.py'`.

Expected: all tests PASS.

- [ ] **Step 5: Commit the generation change**

```bash
git add re_rigify/compatibility.py tests/test_compatibility.py
git commit -m "fix(fingers): use configured rotation axis"
```

### Task 4: Verify Blender integration and the current project scene

**Files:**
- Modify: `tests/blender_integration.py`
- Verify with: Blender MCP connected to the current user scene

**Interfaces:**
- Blender integration coverage constructs super-finger payloads with explicit
  `+Z` and `-Z` compatibility values and confirms the compatibility plan writes
  those values to the temporary metarig without changing the source armature.
- A second case uses `AUTO` with thumb-like names and confirms the planned axis
  is `automatic`, not `Z` or `-Z`.

- [ ] **Step 1: Add the integration assertions before implementation-dependent changes are finalized**

Extend the existing finger integration block with explicit compatibility data,
inspect `finger_plan.finger_axis_plans`, and assert the selected axis and marker
flag. Keep the source/metarig cleanup in a `finally` path so the test leaves no
temporary objects.

- [ ] **Step 2: Run the Blender integration test**

Run the repository's existing Blender integration command for
`tests/blender_integration.py` with Rigify enabled. Expected: the script exits
successfully and leaves no helper armature or generated test object.

- [ ] **Step 3: Reload the addon through Blender MCP and inspect the UI property**

Use `mcp__blender_mcp__execute_blender_code` to reload the addon modules and
inspect the current source armature's configured super-finger entries. Confirm
that each entry has `super_finger_primary_axis` and that the enum contains
`AUTO`, `+X`, `-X`, `+Y`, `-Y`, `+Z`, and `-Z`.

- [ ] **Step 4: Generate an unsaved explicit-axis regression check through Blender MCP**

Use a temporary payload or duplicate of the current source armature, set the
left and right thumb compatibility values explicitly, generate and connect the
rig, and inspect the generated `MCH-Thumb_03_drv_L/R` drivers. Confirm the
expected driver channels and that the generation result reports all source
bones mapped. Remove only uniquely prefixed temporary objects and unused meshes;
do not save the user `.blend`.

- [ ] **Step 5: Verify `AUTO` does not reintroduce name inference**

Regenerate the temporary test setup with `AUTO`, inspect the compatibility plan
or metarig parameter before generation, and confirm it is `automatic` for both
left and right thumb-like names. Confirm no temporary objects remain.

### Task 5: Final verification and handoff

**Files:**
- Verify: all feature files from Tasks 1–4
- Preserve: unrelated worktree changes and the approved design document commit

- [ ] **Step 1: Run the complete automated verification**

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py'
rtk python3 -m py_compile re_rigify/*.py tests/*.py
rtk git diff --check
```

Expected: all tests pass, compilation exits 0, and `git diff --check` reports no
whitespace errors.

- [ ] **Step 2: Inspect the final diff for prohibited inference**

Run:

```bash
rtk git diff -- re_rigify/core.py re_rigify/blender_config.py re_rigify/ui.py re_rigify/compatibility.py re_rigify/translations.py tests
```

Confirm `_automatic_super_finger_axis` and any `Thumb`/side-name axis branch are
gone, while marker correction remains based only on measured bone geometry.

- [ ] **Step 3: Commit only the finished feature changes**

```bash
git add re_rigify/core.py re_rigify/blender_config.py re_rigify/ui.py re_rigify/compatibility.py re_rigify/translations.py tests
git commit -m "feat(fingers): configure super finger axis"
```

Do not stage unrelated user files. Report the final commit, test output, Blender
MCP result, and the fact that the `.blend` file was not saved.

