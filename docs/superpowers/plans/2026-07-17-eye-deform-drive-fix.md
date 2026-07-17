# Eye Deform Drive Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make generated Rigify eye target controls drive the original `Eye_L` and `Eye_R` bones without changing the source rest pose.

**Architecture:** Resolve compatibility-specific drive targets in the Blender-independent compatibility module. Eyelids retain their generated helper resolution, while each configured `face.skin_eye` explicitly selects its generated `DEF-<eye>` bone; the generator stores the combined map for the existing pose-preserving drive bridge.

**Tech Stack:** Python 3, Blender 5.2/Rigify, `unittest`, Blender background integration tests.

## Global Constraints

- Support Blender 4.2 or newer.
- Do not change the global `ORG-*`, `DEF-*`, same-name drive-target preference.
- Do not mutate source bone rest transforms.
- Scope the eye override to configured `face.skin_eye` compatibility plans.
- Preserve existing explicit eyelid mappings.

---

### Task 1: Resolve Eye Deform Targets Explicitly

**Files:**
- Modify: `re_rigify/compatibility.py`
- Modify: `re_rigify/generate.py`
- Test: `tests/test_compatibility.py`

**Interfaces:**
- Consumes: `EyePlan`, `choose_drive_target(source_bone_name, target_bone_names)`.
- Produces: `resolve_compatibility_drive_map(source_to_helper: dict[str, str], eye_plans: list[EyePlan], target_bone_names: Iterable[str]) -> dict[str, str]`.

- [ ] **Step 1: Write the failing mapping test**

Add this import and test to `tests/test_compatibility.py`:

```python
from re_rigify.compatibility import resolve_compatibility_drive_map


def test_eye_drive_map_targets_generated_deform_bone(self):
    eye_plan = plan_eye_landmarks(
        "Eye_L", (0.0, 0.0, 0.0), 1.0,
        self.upper, self.lower, "-Y",
    )

    result = resolve_compatibility_drive_map(
        {"Eye_up_01_L": "RR-lid01.T.L"},
        [eye_plan],
        {"ORG-Eye_L", "DEF-Eye_L", "ORG-RR-lid01.T.L"},
    )

    self.assertEqual(result["Eye_L"], "DEF-Eye_L")
    self.assertEqual(result["Eye_up_01_L"], "ORG-RR-lid01.T.L")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
rtk python3 -m unittest tests.test_compatibility.EyePlanningTests.test_eye_drive_map_targets_generated_deform_bone -v
```

Expected: `ImportError` because `resolve_compatibility_drive_map` does not exist.

- [ ] **Step 3: Implement the pure resolver**

In `re_rigify/compatibility.py`, import `Iterable` and `choose_drive_target`, then add:

```python
def resolve_compatibility_drive_map(
    source_to_helper: dict[str, str],
    eye_plans: list[EyePlan],
    target_bone_names: Iterable[str],
) -> dict[str, str]:
    target_names = set(target_bone_names)
    result = {
        source_name: target_name
        for source_name, helper_name in source_to_helper.items()
        if (target_name := choose_drive_target(helper_name, target_names)) is not None
    }
    for eye_plan in eye_plans:
        deform_name = f"DEF-{eye_plan.eye_name}"
        if deform_name in target_names:
            result[eye_plan.eye_name] = deform_name
    return result
```

In `re_rigify/generate.py`, import the resolver and replace the local `choose_drive_target` comprehension with:

```python
explicit_drive_map = resolve_compatibility_drive_map(
    source_to_helper,
    compatibility_plan.eye_plans,
    result_obj.pose.bones.keys(),
)
```

- [ ] **Step 4: Run unit tests and verify GREEN**

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the mapping fix**

```bash
git add re_rigify/compatibility.py re_rigify/generate.py tests/test_compatibility.py
git commit -m "fix(eye): drive source from deform bones"
```

### Task 2: Verify Rigify Eye Control Motion End to End

**Files:**
- Create: `tests/blender_eye_drive.py`

**Interfaces:**
- Consumes: `generate_rig(context, source, payload)` and `connect_source_to_rig(source, rig)`.
- Produces: a background-Blender regression test proving the stored map and evaluated source-eye motion.

- [ ] **Step 1: Write the Blender regression test**

Create `tests/blender_eye_drive.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy

import re_rigify
from re_rigify.core import DEFAULT_COMPATIBILITY
from re_rigify.drive import DRIVE_MAP_PROPERTY, connect_source_to_rig
from re_rigify.generate import generate_rig


def make_source():
    data = bpy.data.armatures.new("EyeSource")
    source = bpy.data.objects.new("EyeSource", data)
    bpy.context.scene.collection.objects.link(source)
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    eye = data.edit_bones.new("Eye_L")
    eye.head = (0.0, 0.0, 0.0)
    eye.tail = (0.0, -1.0, 0.0)
    landmarks = {
        "Eye_up": [(-1.0, -0.2, 0.0), (0.0, -0.3, 0.6), (1.0, -0.2, 0.0)],
        "Eye_bottom": [
            (-1.0, -0.2, 0.0),
            (0.0, -0.3, -0.6),
            (1.0, -0.2, 0.0),
        ],
    }
    for prefix, points in landmarks.items():
        for index, point in enumerate(points, 1):
            bone = data.edit_bones.new(f"{prefix}_{index:02d}_L")
            bone.head = point
            bone.tail = (point[0], point[1] - 0.1, point[2])
    bpy.ops.object.mode_set(mode="OBJECT")
    return source


def payload():
    return {
        "bones": [{
            "bone_name": "Eye_L",
            "rigify_type": "face.skin_eye",
            "parameters": {},
            "compatibility": {
                **DEFAULT_COMPATIBILITY,
                "skin_eye_compatibility": True,
                "eye_forward_axis": "-Y",
                "upper_lid_pattern": "Eye_up_*_L",
                "lower_lid_pattern": "Eye_bottom_*_L",
            },
        }],
        "collections": [{
            "name": "Face",
            "ui_title": "Face",
            "ui_row": 1,
            "row_order": 0,
            "color_set": "",
            "rules": [{"kind": "GLOB", "pattern": "*"}],
        }],
        "color_sets": [],
    }


bpy.ops.preferences.addon_enable(module="rigify")
re_rigify.register()
try:
    source = make_source()
    rig = generate_rig(bpy.context, source, payload())
    drive_map = json.loads(rig[DRIVE_MAP_PROPERTY])
    assert drive_map["Eye_L"] == "DEF-Eye_L"

    mapped, unmatched = connect_source_to_rig(source, rig)
    assert mapped == len(source.pose.bones)
    assert unmatched == []
    before = source.pose.bones["Eye_L"].matrix.copy()
    rig.pose.bones["Eye_L"].location.x = 0.5
    bpy.context.view_layer.update()
    after = source.pose.bones["Eye_L"].matrix
    assert max(
        abs(after[row][column] - before[row][column])
        for row in range(4)
        for column in range(4)
    ) > 1e-4
finally:
    re_rigify.unregister()
```

- [ ] **Step 2: Run the Blender regression**

Run:

```bash
rtk blender --background --factory-startup --python tests/blender_eye_drive.py
```

Expected: exit code 0 and `Successfully generated: "EyeSource_rig"`.

- [ ] **Step 3: Run the complete verification suite**

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk blender --background --factory-startup --python tests/blender_integration.py
rtk blender --background --factory-startup --python tests/blender_generate.py
rtk blender --background --factory-startup --python tests/blender_extension_entry.py
rtk git diff --check
```

Expected: every command exits 0; unit tests report all tests passing; Blender scripts finish without tracebacks; `git diff --check` prints nothing.

- [ ] **Step 4: Commit the integration regression**

```bash
git add tests/blender_eye_drive.py
git commit -m "test(eye): cover source eye control motion"
```
