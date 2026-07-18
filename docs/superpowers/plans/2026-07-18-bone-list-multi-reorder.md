# Bone List Multi-Reorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add up/down controls that move either the active configured bone or every checked configured bone while preserving relative order.

**Architecture:** A Blender-independent helper computes stable adjacent collection moves. A Blender operator handles parameter-carrier lifecycle, applies those moves to the RNA collection, and restores the active row by bone name. Existing collection order remains the exported preset order, so no schema migration is needed.

**Tech Stack:** Python 3, Blender 5.2 RNA/operators/UI, Rigify, `unittest`, Blender MCP, jj.

## Global Constraints

- Reuse `RERIGIFY_PG_BoneConfig.collection_selected` as the multi-selection state.
- No checked rows means the active row is the sole move target.
- Each click moves selected blocks exactly one position without reversing or compacting separated rows.
- Keep schema version 1.
- Do not launch a Blender process; all Blender integration checks use the connected Blender MCP.
- Prefix shell commands with `rtk`.
- Use jj for commits.

---

### Task 1: Stable Reorder Planning

**Files:**
- Modify: `re_rigify/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `item_count: int`, `selected_indices: Iterable[int]`, and `direction: int`.
- Produces: `move_selected_indices(item_count, selected_indices, direction) -> tuple[tuple[int, int], ...]`, where each pair is a sequential Blender collection `move(source, target)` operation.

- [ ] **Step 1: Write failing ordering tests**

Add the import and tests:

```python
from re_rigify.core import move_selected_indices


class MoveSelectedIndicesTests(unittest.TestCase):
    @staticmethod
    def apply(values, operations):
        values = list(values)
        for source, target in operations:
            values.insert(target, values.pop(source))
        return values

    def test_moves_contiguous_block_up_without_reversing(self):
        operations = move_selected_indices(4, {1, 2}, -1)
        self.assertEqual(
            self.apply(["A", "B", "C", "D"], operations),
            ["B", "C", "A", "D"],
        )

    def test_moves_contiguous_block_down_without_reversing(self):
        operations = move_selected_indices(4, {1, 2}, 1)
        self.assertEqual(
            self.apply(["A", "B", "C", "D"], operations),
            ["A", "D", "B", "C"],
        )

    def test_moves_separated_rows_one_step_without_compacting(self):
        operations = move_selected_indices(5, {1, 3}, -1)
        self.assertEqual(
            self.apply(["A", "B", "C", "D", "E"], operations),
            ["B", "A", "D", "C", "E"],
        )

    def test_boundary_blocks_do_not_move(self):
        self.assertEqual(move_selected_indices(4, {0, 1}, -1), ())
        self.assertEqual(move_selected_indices(4, {2, 3}, 1), ())

    def test_rejects_invalid_direction(self):
        with self.assertRaisesRegex(ValueError, "direction"):
            move_selected_indices(4, {1}, 0)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
rtk python3 -m unittest tests.test_core.MoveSelectedIndicesTests -v
```

Expected: import failure because `move_selected_indices` does not exist.

- [ ] **Step 3: Implement the pure move planner**

Add to `re_rigify/core.py`:

```python
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
```

- [ ] **Step 4: Run focused and full pure tests**

Run:

```bash
rtk python3 -m unittest tests.test_core.MoveSelectedIndicesTests -v
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
rtk jj commit -m "feat(core): plan stable multi-row moves"
```

---

### Task 2: Bone Move Operator and UI

**Files:**
- Modify: `re_rigify/operators.py`
- Modify: `re_rigify/ui.py`
- Modify: `tests/test_ui_source.py`
- Modify: `tests/blender_integration.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `move_selected_indices` from Task 1 and the existing `collection_selected`, `active_bone_index`, parameter-carrier, and RNA collection APIs.
- Produces: registered `RERIGIFY_OT_BoneMove` / `re_rigify.bone_move`, plus up/down buttons in `RERIGIFY_PT_Bones`.

- [ ] **Step 1: Write failing registration and UI-source tests**

Extend `tests/test_ui_source.py`:

```python
def test_bone_move_operator_and_buttons_are_registered(self):
    operator_source = Path("re_rigify/operators.py").read_text(encoding="utf-8")
    operator_tree = ast.parse(operator_source)
    operator_classes = {
        node.name for node in operator_tree.body if isinstance(node, ast.ClassDef)
    }
    self.assertIn("RERIGIFY_OT_BoneMove", operator_classes)

    ui_source = Path("re_rigify/ui.py").read_text(encoding="utf-8")
    self.assertEqual(ui_source.count('"re_rigify.bone_move"'), 2)
    self.assertIn('icon="TRIA_UP"', ui_source)
    self.assertIn('icon="TRIA_DOWN"', ui_source)
```

- [ ] **Step 2: Write failing Blender integration assertions**

After the three bone rows are added to `batch` in `tests/blender_integration.py`, add:

```python
batch_settings = batch.data.re_rigify
batch_settings.bones[1].collection_selected = True
batch_settings.bones[2].collection_selected = True
batch_settings.active_bone_index = 2
assert bpy.ops.re_rigify.bone_move(direction=-1) == {"FINISHED"}
assert [item.bone_name for item in batch_settings.bones] == ["three", "two", "one"]
assert batch_settings.active_bone_index == 1
assert [item.collection_selected for item in batch_settings.bones] == [True, True, False]

assert bpy.ops.re_rigify.bone_move(direction=1) == {"FINISHED"}
assert [item.bone_name for item in batch_settings.bones] == ["one", "three", "two"]
assert batch_settings.active_bone_index == 2

for item in batch_settings.bones:
    item.collection_selected = False
assert bpy.ops.re_rigify.bone_move(direction=-1) == {"FINISHED"}
assert [item.bone_name for item in batch_settings.bones] == ["one", "two", "three"]
assert batch_settings.active_bone_index == 1
assert get_parameter_carrier(
    batch,
    batch_settings.bones[1],
    1,
) is not None
```

- [ ] **Step 3: Run the pure UI test and verify RED**

Run:

```bash
rtk python3 -m unittest tests.test_ui_source.PanelStructureTests.test_bone_move_operator_and_buttons_are_registered -v
```

Expected: failure because the operator and buttons do not exist.

- [ ] **Step 4: Implement the operator**

Import `move_selected_indices` in `re_rigify/operators.py`, then add:

```python
class RERIGIFY_OT_BoneMove(bpy.types.Operator):
    bl_idname = "re_rigify.bone_move"
    bl_label = "Move Bone Configuration"
    bl_description = "Move checked configurations, or the active configuration if none are checked"
    bl_options = {"UNDO"}

    direction: IntProperty()

    def execute(self, context):
        from .ui import (
            flush_parameter_carrier,
            prepare_parameter_carrier,
            remove_parameter_carrier,
        )

        obj = active_armature(context)
        if obj is None:
            return {"CANCELLED"}
        settings = obj.data.re_rigify
        if not settings.bones:
            return {"CANCELLED"}
        selected = {
            index for index, item in enumerate(settings.bones)
            if item.collection_selected
        }
        if not selected:
            selected = {settings.active_bone_index}
        operations = move_selected_indices(
            len(settings.bones), selected, self.direction,
        )
        if not operations:
            return {"CANCELLED"}

        active_name = settings.bones[settings.active_bone_index].bone_name
        flush_parameter_carrier()
        remove_parameter_carrier()
        with suspend_carrier_updates():
            for source, target in operations:
                settings.bones.move(source, target)
            settings.active_bone_index = next(
                index for index, item in enumerate(settings.bones)
                if item.bone_name == active_name
            )
        active_index = settings.active_bone_index
        prepare_parameter_carrier(
            context, obj, settings.bones[active_index], active_index,
        )
        return {"FINISHED"}
```

Register `RERIGIFY_OT_BoneMove` immediately after the Add/Remove operators in
`CLASSES`.

- [ ] **Step 5: Add the two UI buttons**

Below Add and Remove in `RERIGIFY_PT_Bones.draw`, add:

```python
up = buttons.operator("re_rigify.bone_move", text="", icon="TRIA_UP")
up.direction = -1
down = buttons.operator("re_rigify.bone_move", text="", icon="TRIA_DOWN")
down.direction = 1
```

- [ ] **Step 6: Run focused and full pure tests**

Run:

```bash
rtk python3 -m unittest tests.test_ui_source.PanelStructureTests.test_bone_move_operator_and_buttons_are_registered -v
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk git diff --check
```

Expected: all tests pass and diff check emits no output.

- [ ] **Step 7: Reload and verify through Blender MCP**

Use the connected Blender MCP to reload the extension while snapshotting and
restoring every Re-Rigify armature payload. Create a temporary four-bone
armature/configuration and verify:

```python
assert bpy.ops.re_rigify.bone_move(direction=-1) == {"FINISHED"}
assert names == ["B", "C", "A", "D"]
assert active_name == "C"
assert checked_names == ["B", "C"]
assert get_parameter_carrier(source, active_item, active_index) is not None
```

Then move down, verify the original order, clear all checks, and verify the
active-row fallback. Delete only temporary test datablocks. Do not launch a
Blender process.

- [ ] **Step 8: Document the control**

Add to `README.md`:

```markdown
The bone list arrows move all checked configurations by one position while
preserving their relative order. With no checked rows, they move only the
active configuration. Preset export preserves the displayed order.
```

- [ ] **Step 9: Run final verification**

Run:

```bash
rtk python3 -m py_compile re_rigify/*.py tests/*.py
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk git diff --check
```

Repeat the Blender MCP temporary-armature test after the final reload. Expected:
all pure tests pass, Blender returns `FINISHED`, carrier binding follows the
active bone, and the current project remains otherwise unchanged.

- [ ] **Step 10: Commit**

```bash
rtk jj commit -m "feat(ui): reorder configured bones"
```
