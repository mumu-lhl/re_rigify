# Rigify Chain and Skin Eye Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate `limbs.super_finger` and `face.skin_eye` rigs from the current production skeleton while keeping the source rest skeleton unchanged and driving its real eyelid bones.

**Architecture:** Store Re-Rigify-only compatibility settings beside each bone configuration within the unpublished schema version 1, and compile them into a temporary-metarig adaptation plan. A focused `compatibility.py` module builds connected finger chains and Rigify-compatible eyelid chains, while `generate.py` applies that plan and persists explicit generated-to-source drive mappings on the generated rig.

**Tech Stack:** Python 3, Blender 5.2 RNA/API, bundled Rigify, `unittest`, Blender MCP, Jujutsu.

## Global Constraints

- Compatibility changes must only modify the temporary metarig.
- Source bone names, rest transforms, parents, and `use_connect` flags must remain unchanged.
- Real eyelid bones matched by the configured globs take priority.
- Synthetic eyelid fallback defaults to disabled.
- Generated eyelid deform bones must drive the matched source eyelid bones.
- Blender integration tests must use Blender MCP; do not launch a standalone Blender process.
- Prefix shell commands with `rtk`.

---

## File Structure

- `re_rigify/core.py`: compatibility normalization, mirroring, and unique-chain traversal.
- `re_rigify/compatibility.py`: Blender-specific compatibility validation, eyelid landmark planning, temporary edit-bone creation, and drive-map production.
- `re_rigify/blender_config.py`: RNA properties and payload conversion.
- `re_rigify/ui.py`: compatibility controls for the active bone.
- `re_rigify/operators.py`: copy and mirror compatibility settings.
- `re_rigify/generate.py`: apply compatibility plans and store explicit drive metadata.
- `re_rigify/drive.py`: consume explicit mappings before name-based fallback.
- `tests/test_core.py`: schema defaults, mirroring, and chain tests.
- `tests/test_compatibility.py`: pure landmark ordering and eye-plan tests with small vector tuples.
- `tests/blender_integration.py`: Blender-side regression coverage.

---

### Task 1: Compatibility Schema and Pure Chain Planning

**Files:**
- Modify: `re_rigify/core.py`
- Modify: `tests/test_core.py`

**Interfaces:**
- Produces: `DEFAULT_COMPATIBILITY: dict[str, object]`
- Produces: `normalize_compatibility(value: object, path: str) -> dict`
- Produces: `mirror_compatibility(value: dict, name_mapper) -> dict`
- Produces: `unique_child_chain(root: str, parents: dict[str, str | None]) -> list[str]`
- Consumes: existing `ConfigError`, `normalize_config`, and `mirror_parameter_value`

- [ ] **Step 1: Write failing schema and chain tests**

Add tests that require version-1 defaults and round trips, mirrored patterns,
axis mirroring, unique-chain traversal, and branch rejection:

```python
def test_version_one_migrates_with_compatibility_disabled(self):
    payload = self.valid_payload(schema_version=1)
    result = normalize_config(payload)
    self.assertEqual(result["schema_version"], 1)
    self.assertEqual(result["bones"][0]["compatibility"], {
        "force_connect_chain": False,
        "skin_eye_compatibility": False,
        "eye_forward_axis": "AUTO",
        "upper_lid_pattern": "",
        "lower_lid_pattern": "",
        "synthetic_lids_fallback": False,
    })

def test_unique_child_chain_rejects_branches(self):
    parents = {"root": None, "a": "root", "b": "root"}
    with self.assertRaisesRegex(ConfigError, "ambiguous.*a.*b"):
        unique_child_chain("root", parents)

def test_mirror_compatibility_swaps_x_axis_and_patterns(self):
    result = mirror_compatibility({
        **DEFAULT_COMPATIBILITY,
        "eye_forward_axis": "+X",
        "upper_lid_pattern": "Eye_up_*_L",
    }, lambda name: name.replace("_L", "_R"))
    self.assertEqual(result["eye_forward_axis"], "-X")
    self.assertEqual(result["upper_lid_pattern"], "Eye_up_*_R")
```

- [ ] **Step 2: Run the tests and verify red**

Run:

```bash
rtk python3 -m unittest tests.test_core -v
```

Expected: failures for missing compatibility helpers.

- [ ] **Step 3: Implement schema version 1 compatibility helpers**

Keep `SCHEMA_VERSION = 1` and normalize every bone to this exact shape:

```python
DEFAULT_COMPATIBILITY = {
    "force_connect_chain": False,
    "skin_eye_compatibility": False,
    "eye_forward_axis": "AUTO",
    "upper_lid_pattern": "",
    "lower_lid_pattern": "",
    "synthetic_lids_fallback": False,
}

def unique_child_chain(root, parents):
    children = {name: [] for name in parents}
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
```

`mirror_compatibility` must apply the name mapper to both glob fields and map
`+X <-> -X`; `AUTO`, `+Y`, and `-Y` remain unchanged.

- [ ] **Step 4: Run pure tests**

Run:

```bash
rtk python3 -m unittest tests.test_core -v
```

Expected: all `test_core` tests pass.

- [ ] **Step 5: Commit**

```bash
rtk jj commit -m "feat(config): add compatibility schema"
```

---

### Task 2: RNA Storage, Import/Export, Copy, Mirror, and UI

**Files:**
- Modify: `re_rigify/blender_config.py`
- Modify: `re_rigify/operators.py`
- Modify: `re_rigify/ui.py`
- Modify: `tests/test_ui_source.py`
- Modify: `tests/blender_integration.py`

**Interfaces:**
- Consumes: `normalize_compatibility` and `mirror_compatibility`
- Produces: RNA fields named exactly like the compatibility payload keys
- Produces: `_compatibility_from_item(item) -> dict`
- Produces: `_apply_compatibility_to_item(item, source: dict) -> None`

- [ ] **Step 1: Add failing payload and UI source tests**

Extend the Blender integration payload round-trip with:

```python
"compatibility": {
    "force_connect_chain": True,
    "skin_eye_compatibility": False,
    "eye_forward_axis": "AUTO",
    "upper_lid_pattern": "",
    "lower_lid_pattern": "",
    "synthetic_lids_fallback": False,
}
```

Add an AST source test that requires the Bone Setup panel to draw
`force_connect_chain` and conditionally draw all Skin Eye fields.

- [ ] **Step 2: Run pure UI tests and confirm red**

Run:

```bash
rtk python3 -m unittest tests.test_ui_source -v
```

Expected: failure because the compatibility properties are not drawn.

- [ ] **Step 3: Add RNA fields and payload conversion**

Add these properties to `RERIGIFY_PG_BoneConfig`:

```python
force_connect_chain: BoolProperty(name="Force Connected Chain", default=False)
skin_eye_compatibility: BoolProperty(name="Build Skin Eye Topology", default=False)
eye_forward_axis: EnumProperty(
    name="Eye Forward",
    items=(
        ("AUTO", "Automatic", ""),
        ("+X", "+X", ""),
        ("-X", "-X", ""),
        ("+Y", "+Y", ""),
        ("-Y", "-Y", ""),
    ),
    default="AUTO",
)
upper_lid_pattern: StringProperty(name="Upper Eyelids")
lower_lid_pattern: StringProperty(name="Lower Eyelids")
synthetic_lids_fallback: BoolProperty(name="Synthetic Eyelid Fallback", default=False)
```

Use `_compatibility_from_item` and `_apply_compatibility_to_item` in
`armature_to_payload` and `payload_to_armature`.

- [ ] **Step 4: Copy and mirror compatibility fields**

Change the mirror snapshot to include `_compatibility_from_item(item)`, then assign
`mirror_compatibility(...)` to the target. Change Copy Bone Settings to Checked to
copy all compatibility fields in the same `suspend_carrier_updates()` block as the
Rigify type and parameters.

- [ ] **Step 5: Draw compatibility controls**

In `RERIGIFY_PT_Bones.draw`, add a compact compatibility box below the bone type:

```python
compat = layout.box()
compat.label(text="Compatibility")
compat.prop(item, "force_connect_chain")
if item.rigify_type == "face.skin_eye":
    compat.prop(item, "skin_eye_compatibility")
    if item.skin_eye_compatibility:
        compat.prop(item, "eye_forward_axis")
        compat.prop(item, "upper_lid_pattern")
        compat.prop(item, "lower_lid_pattern")
        compat.prop(item, "synthetic_lids_fallback")
```

Do not write ID properties from `draw`.

- [ ] **Step 6: Verify tests**

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk python3 -m compileall -q re_rigify tests
rtk git diff --check
```

Expected: all pure tests pass and no syntax or whitespace errors.

- [ ] **Step 7: Commit**

```bash
rtk jj commit -m "feat(ui): expose rig compatibility settings"
```

---

### Task 3: Temporary Connected-Chain Adapter

**Files:**
- Create: `re_rigify/compatibility.py`
- Modify: `re_rigify/generate.py`
- Create: `tests/test_compatibility.py`
- Modify: `tests/blender_integration.py`

**Interfaces:**
- Consumes: `unique_child_chain`
- Produces: `CompatibilityPlan` containing `connections` and `source_to_helper`
- Produces: `build_compatibility_plan(obj, bone_configs) -> CompatibilityPlan`
- Produces: `apply_compatibility_plan(obj, plan) -> None`

- [ ] **Step 1: Write failing plan tests**

Create `tests/test_compatibility.py` with a pure parent map and assert:

```python
def test_super_finger_force_connect_builds_three_bone_chain(self):
    parents = {
        "Thumb_01_R": "Wrist_R",
        "Thumb_02_R": "Thumb_01_R",
        "Thumb_03_R": "Thumb_02_R",
    }
    result = plan_connected_chain(
        "Thumb_01_R", "limbs.super_finger", parents, enabled=True
    )
    self.assertEqual(result, [
        ("Thumb_01_R", "Thumb_02_R", True),
        ("Thumb_02_R", "Thumb_03_R", True),
    ])
```

Also assert disabled mode returns no operations and a one-bone chain raises
`ConfigError` mentioning the minimum length of 2.

- [ ] **Step 2: Run and confirm red**

Run:

```bash
rtk python3 -m unittest tests.test_compatibility -v
```

Expected: import failure for the new module.

- [ ] **Step 3: Implement chain planning**

Define:

```python
CHAIN_MIN_LENGTHS = {"limbs.super_finger": 2}

@dataclass
class CompatibilityPlan:
    connections: list[tuple[str, str, bool]] = field(default_factory=list)
    eye_plans: list["EyePlan"] = field(default_factory=list)
    source_to_helper: dict[str, str] = field(default_factory=dict)
```

For enabled chain compatibility, call `unique_child_chain`, validate the minimum,
and return adjacent connection operations. Ignore `force_connect_chain` for types
not present in `CHAIN_MIN_LENGTHS`, with a validation error rather than silently
changing arbitrary branches.

- [ ] **Step 4: Apply connections in the metarig**

Make `apply_compatibility_plan` enter Edit Mode once, assign each child parent and
`use_connect`, then return to Object Mode. In `generate_rig`, build and apply the
compatibility plan after `apply_rigify_topology` and before Pose Mode.

- [ ] **Step 5: Add Blender integration assertion**

On a temporary armature with a parented but disconnected three-bone finger, enable
`force_connect_chain`, prepare the metarig, apply the plan, and assert:

```python
assert metarig.data.bones["Thumb_02_R"].use_connect
assert metarig.data.bones["Thumb_03_R"].use_connect
assert not source.data.bones["Thumb_02_R"].use_connect
assert not source.data.bones["Thumb_03_R"].use_connect
```

- [ ] **Step 6: Run all pure tests and Blender MCP regression**

Run pure tests with the standard unittest command. Reload the extension through the
existing Blender MCP session and execute the disconnected-finger integration case.
Expected: Rigify generates the finger rig and all temporary objects are removed.

- [ ] **Step 7: Commit**

```bash
rtk jj commit -m "feat(rig): adapt disconnected chains"
```

---

### Task 4: Real Eyelid Landmark Planning

**Files:**
- Modify: `re_rigify/compatibility.py`
- Modify: `tests/test_compatibility.py`

**Interfaces:**
- Produces: `EyeLandmark(name: str, point: tuple[float, float, float])`
- Produces: `EyeSegment(source_name: str | None, helper_name: str, head, tail)`
- Produces: `EyePlan(eye_name, forward_axis, upper, lower)`
- Produces: `build_eye_plan(eye_name, compatibility, bones) -> EyePlan`

- [ ] **Step 1: Write failing landmark geometry tests**

Use simplified landmarks shaped like the current model:

```python
upper = [
    EyeLandmark("Eye_up_01_L", (-2, -0.2, 1)),
    EyeLandmark("Eye_up_02_L", (0, -0.3, 2)),
    EyeLandmark("Eye_up_03_L", (2, -0.2, 1)),
]
lower = [
    EyeLandmark("Eye_bottom_01_L", (-2, -0.2, -1)),
    EyeLandmark("Eye_bottom_02_L", (0, -0.3, -2)),
    EyeLandmark("Eye_bottom_03_L", (2, -0.2, -1)),
]
plan = plan_eye_landmarks("Eye_L", (0, 0, 0), upper, lower, "AUTO")
self.assertEqual(plan.forward_axis, (0, -1, 0))
self.assertEqual(len(plan.upper), len(upper))
self.assertEqual(len(plan.lower), len(lower))
self.assertEqual(plan.upper[0].head, plan.lower[0].head)
self.assertEqual(plan.upper[-1].tail, plan.lower[-1].tail)
```

Add tests for explicit axes, too few landmarks, ambiguous automatic direction,
and stable source-to-helper association.

- [ ] **Step 2: Run and confirm red**

Run:

```bash
rtk python3 -m unittest tests.test_compatibility -v
```

Expected: missing eye-planning symbols.

- [ ] **Step 3: Implement pattern resolution and ordering**

Use `fnmatchcase` over source bone names. Convert each matched bone head into an
`EyeLandmark`. Derive AUTO forward from the average eyelid landmark offset from
the eye head projected onto XY; choose the signed dominant axis and reject a
near-zero projection.

Project landmarks into a 2D basis where horizontal is perpendicular to forward
and vertical is world Z. Sort each set by horizontal coordinate.

- [ ] **Step 4: Build paired chains with shared corners**

For N source landmarks, generate N segments centered on those landmarks. Use the
average of the first upper/lower points as corner 1, the average of the last
upper/lower points as corner 2, and adjacent landmark midpoints as internal nodes.
Name segments with Rigify-recognized side markers:

```python
RR-lid01.T.L
RR-lid02.T.L
RR-lid01.B.L
RR-lid02.B.L
```

Use the eye name suffix to select `.L`, `.R`, or no horizontal side. Each segment
retains its exact `source_name`.

- [ ] **Step 5: Implement synthetic fallback**

When enabled and either set has fewer than two landmarks, create three synthetic
landmarks per lid around the eye head using eye length as radius. Set every
synthetic segment `source_name=None`; do not create drive mappings for them.

- [ ] **Step 6: Run pure tests**

Run:

```bash
rtk python3 -m unittest tests.test_compatibility -v
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
rtk jj commit -m "feat(eye): plan real eyelid chains"
```

---

### Task 5: Build Skin Eye Metarig Topology

**Files:**
- Modify: `re_rigify/compatibility.py`
- Modify: `re_rigify/generate.py`
- Modify: `tests/blender_integration.py`

**Interfaces:**
- Consumes: `EyePlan`
- Extends: `apply_compatibility_plan(obj, plan) -> dict[str, str]`
- Produces: source eyelid name to temporary helper bone name mapping

- [ ] **Step 1: Add a failing Blender MCP reproduction**

In the persistent integration script, construct or copy an armature containing:

- `Eye_L` pointing vertically.
- Three `Eye_up_*_L` landmarks.
- Three `Eye_bottom_*_L` landmarks.
- A `face.skin_eye` configuration with compatibility enabled and forward `-Y`.

Assert generation no longer raises the observed `float division by zero`.

- [ ] **Step 2: Confirm the reproduction fails before implementation**

Reload the extension through Blender MCP and execute only the eye case.
Expected: Rigify fails in `face/skin_eye.py:project_rig_control`.

- [ ] **Step 3: Create temporary helper chains**

Within one Edit Mode session:

1. Reorient the temporary eye bone tail to `head + forward_axis * original_length`.
2. Create each `EyeSegment` as a new edit bone.
3. Parent the first top and bottom bones to the eye with `use_connect=False`.
4. Parent subsequent bones to the previous segment with `use_connect=True`.
5. Preserve shared endpoint coordinates exactly.

After returning to Object Mode, set the top and bottom root pose bones to
`skin.stretchy_chain`. Set `skin_chain_pivot_pos` to the middle segment index and
`bbones` to 5 when those Rigify parameters exist.

- [ ] **Step 4: Integrate with generation order**

Change `generate_rig` to use this order:

```python
apply_collection_config(...)
apply_bone_config(...)
apply_color_config(...)
select temporary metarig
apply_rigify_topology(...)
plan = build_compatibility_plan(...)
source_to_helper = apply_compatibility_plan(...)
bpy.ops.object.mode_set(mode="POSE")
bpy.ops.pose.rigify_generate()
```

Applying the base bone config before the eye adapter ensures the eye root already
owns `face.skin_eye`; applying helper rig types after edit mode ensures the new
pose bones exist.

- [ ] **Step 5: Verify Skin Eye generation in Blender MCP**

Run first on the minimal test armature, then on a temporary copy of
`1003_トウカイテイオー_arm` with:

- `Eye_L`: `Eye_up_*_L`, `Eye_bottom_*_L`
- `Eye_R`: `Eye_up_*_R`, `Eye_bottom_*_R`
- explicit `-Y` forward axis

Expected: both Skin Eye rigs generate, no division by zero or missing-corner
error, and the source armature rest topology is unchanged.

- [ ] **Step 6: Commit**

```bash
rtk jj commit -m "feat(eye): build temporary skin eye topology"
```

---

### Task 6: Persist and Consume Explicit Eyelid Drive Mapping

**Files:**
- Modify: `re_rigify/generate.py`
- Modify: `re_rigify/drive.py`
- Modify: `tests/test_core.py`
- Modify: `tests/blender_integration.py`

**Interfaces:**
- Produces: `DRIVE_MAP_PROPERTY = "re_rigify_drive_map"`
- Produces: `store_drive_map(rig, source_to_helper) -> dict[str, str]`
- Extends: `connect_source_to_rig(source, rig)` to prefer explicit targets

- [ ] **Step 1: Write failing explicit-map tests**

Add a pure helper test:

```python
target = choose_drive_target(
    "Eye_up_01_L",
    {"DEF-RR-lid01.T.L"},
    explicit={"Eye_up_01_L": "DEF-RR-lid01.T.L"},
)
self.assertEqual(target, "DEF-RR-lid01.T.L")
```

Add Blender integration assertions that the generated rig metadata contains every
matched real eyelid source bone and no synthetic source entry.

- [ ] **Step 2: Run and confirm red**

Run:

```bash
rtk python3 -m unittest tests.test_core -v
```

Expected: `choose_drive_target` does not accept `explicit`.

- [ ] **Step 3: Extend drive target selection**

Change the core signature:

```python
def choose_drive_target(
    source_bone_name: str,
    target_bone_names: Iterable[str],
    explicit: dict[str, str] | None = None,
) -> str | None:
    target = (explicit or {}).get(source_bone_name)
    if target in set(target_bone_names):
        return target
    ...
```

In `connect_source_to_rig`, parse a JSON object from `rig[DRIVE_MAP_PROPERTY]`;
invalid metadata becomes an empty mapping and does not abort normal drive setup.

- [ ] **Step 4: Store resolved generated targets**

After Rigify generation, resolve each helper through the generated rig's
`DEF-`, `ORG-`, and same-name candidates. Store only valid results:

```python
resolved[source_name] = choose_drive_target(helper_name, generated.pose.bones.keys())
generated[DRIVE_MAP_PROPERTY] = json.dumps(resolved, ensure_ascii=False, sort_keys=True)
```

Overwrite the property on every regeneration so removed eyelid matches do not
leave stale mappings.

- [ ] **Step 5: Verify real source eyelid motion**

Through Blender MCP:

1. Generate and connect the rig from a temporary copy of the current source.
2. Record the source eyelid pose matrix.
3. Move one generated Skin Eye eyelid control.
4. Update the dependency graph.
5. Assert the mapped generated DEF bone changes and the source
   `Eye_up_*`/`Eye_bottom_*` pose matrix follows it.
6. Restore transforms and remove all temporary test objects.

- [ ] **Step 6: Run regression suite**

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk python3 -m compileall -q re_rigify tests
rtk git diff --check
```

Expected: all pure tests pass. Blender MCP integration must report no unmatched
real eyelid bones covered by the explicit map.

- [ ] **Step 7: Commit**

```bash
rtk jj commit -m "feat(drive): map generated eyelid deforms"
```

---

### Task 7: Pre-generation Validation and Current-project Acceptance

**Files:**
- Modify: `re_rigify/compatibility.py`
- Modify: `re_rigify/generate.py`
- Modify: `re_rigify/operators.py`
- Modify: `tests/test_compatibility.py`
- Modify: `tests/blender_integration.py`

**Interfaces:**
- Produces: `validate_compatibility(source, bone_configs) -> tuple[str, ...]`
- Consumes: `build_compatibility_plan`
- Extends: `validate_active` to report compatibility errors before Rigify

- [ ] **Step 1: Write failing diagnostics tests**

Require exact actionable messages for:

```python
"Bone 'Thumb_01_R': forced chain branches at 'Thumb_01_R': A, B"
"Bone 'Thumb_01_R': limbs.super_finger requires at least 2 connected bones"
"Bone 'Eye_L': AUTO forward axis is ambiguous; choose ±X or ±Y"
"Bone 'Eye_L': upper eyelid pattern 'Eye_up_*_L' matched fewer than 2 bones"
"Bone 'Eye_L': eyelid bone 'Shared_Lid' is claimed by multiple eye rigs"
```

- [ ] **Step 2: Run and confirm red**

Run:

```bash
rtk python3 -m unittest tests.test_compatibility -v
```

Expected: missing `validate_compatibility`.

- [ ] **Step 3: Implement non-mutating validation**

Build the same compatibility plan used for generation from source bone parenting,
head positions, and glob matches, but do not enter Edit Mode. Collect `ConfigError`
messages per configured bone and detect duplicate source eyelid claims across all
eye plans.

Call this from `validate_active` after schema/type validation and before
`validate_bone_parameters`.

- [ ] **Step 4: Run current-project acceptance through Blender MCP**

On the currently open armature, set only the required compatibility fields:

- `Thumb_01_R.force_connect_chain = True`
- `Eye_L/Eye_R.skin_eye_compatibility = True`
- matching upper/lower patterns for each side
- `eye_forward_axis = "-Y"`
- synthetic fallback disabled

Generate on a temporary copy first. If all assertions pass, run the normal
Generate & Connect operator only after preserving the user's current generated
rig target and selection state.

Acceptance criteria:

- No `float division by zero`.
- No “chain of 2 or more bones” error.
- Both eye rigs and the right thumb rig exist.
- Moving an eye/eyelid control drives the expected source eye and eyelid bones.
- Moving the finger controls drives `Thumb_01_R`, `Thumb_02_R`, and `Thumb_03_R`.
- Source rest topology remains unchanged.
- Regeneration updates the existing generated rig and explicit mapping.

- [ ] **Step 5: Final verification**

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk python3 -m compileall -q re_rigify tests
rtk git diff --check
rtk jj status
```

Then use Blender MCP to verify there are no objects whose names begin with
`__RR_`, no extra metarig, and no parameter carrier left from testing.

- [ ] **Step 6: Commit**

```bash
rtk jj commit -m "fix(validation): reject incompatible rig topology"
```
