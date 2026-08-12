# Bone List Multi-Reorder Design

## Goal

Let users reorder configured bones with up/down buttons. The operation supports
either the active row or all rows marked by the existing checkboxes.

## Interaction

Two arrow buttons appear below Add and Remove beside the bone list.

- If one or more rows are checked, the arrows move all checked rows.
- If no row is checked, the arrows move only the active row.
- Each click moves each selected block by one position.
- Selected rows keep their relative order and checked state.
- Rows at the relevant list boundary remain in place.
- The active row follows the same bone after reordering.

For example, moving `B` and `C` upward:

```text
A        B checked
B  ->    C checked
C        A
D        D
```

Separated checked rows remain separated unless normal one-step movement closes
the gap. The command does not compact every checked row into one block.

## Implementation

Add a pure ordering helper that accepts the row count, selected indices, and a
direction. Moving upward processes indices from low to high; moving downward
processes them from high to low. A row swaps with its adjacent unselected row,
which moves contiguous selected blocks without reversing them.

Add `RERIGIFY_OT_BoneMove` with a `direction` integer property:

1. Flush and remove the temporary Rigify parameter carrier.
2. Determine checked indices, falling back to `active_bone_index`.
3. Apply the helper's adjacent moves with Blender collection `move`.
4. Resolve the active bone's new index by bone name.
5. Recreate the parameter carrier for the active row.

The operator is undoable. It cancels safely when there is no active armature,
no configured bone, or no movement is possible.

## Persistence

No schema change is required. Bone order already comes from the RNA collection
order, and `armature_to_payload` exports rows in that order. Import restores the
same order.

## Tests

Pure tests cover:

- Active-row fallback.
- A contiguous checked block moving up and down.
- Separated checked rows moving without reordering each other.
- Top and bottom boundary behavior.

Source/UI tests require operator registration and both arrow buttons. Blender
integration verifies collection order, active-row tracking, checked-state
preservation, and parameter-carrier rebinding.
