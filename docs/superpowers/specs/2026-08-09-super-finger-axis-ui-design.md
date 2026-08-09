# UI-configurable Super Finger Axis Design

**Status:** Approved direction

## Goal

Move `limbs.super_finger` primary rotation-axis selection from the compatibility
implementation's bone-name heuristic into an explicit per-bone UI setting. The
setting must support Rigify's automatic mode and every signed cardinal axis.

## Current behavior

The Compatibility panel exposes topology and eye/arm compatibility options, but
not the super-finger axis. During generation,
`plan_super_finger_axis()` only handles Rigify's `primary_rotation_axis` value
`automatic`, then `_automatic_super_finger_axis()` selects `-X` for ordinary
fingers and `Z`/`-Z` for roots whose names look like left/right thumbs. This
couples behavior to naming conventions and prevents a user from selecting a
different axis without editing raw Rigify parameter JSON.

## Design

### 1. Compatibility setting and UI

Add `super_finger_primary_axis` to each bone's normalized compatibility object.
The stored values are:

- `AUTO` — use Rigify's native `automatic` value.
- `+X`, `-X`, `+Y`, `-Y`, `+Z`, `-Z` — use the selected explicit axis.

The Blender RNA property is an enum with the same identifiers and a user-facing
label `Primary Rotation Axis`; the `AUTO` item is displayed as `Automatic`.
It is shown only for `limbs.super_finger` in the existing Compatibility box.
The default is `AUTO`, so old payloads remain readable without a schema-version
bump.

The compatibility field is the source of truth at generation time. The generic
Rigify parameter `primary_rotation_axis` is overridden on the temporary
metarig: `AUTO` maps to Rigify's lowercase `automatic`, `+X`/`+Y`/`+Z` map to
Rigify's positive identifiers `X`/`Y`/`Z`, and negative UI values map directly
to `-X`/`-Y`/`-Z`. This matches Rigify's actual RNA enum while keeping the UI
explicit about positive directions. A name change therefore cannot change the
generated result.

### 2. Generation behavior

Refactor the finger compatibility plan to consume the configured compatibility
axis rather than inspecting the root bone name. Remove the name-based axis
helper entirely.

The existing geometry correction for a long, misaligned terminal marker remains
geometry-based and independent of names. It may still make the marker collinear
with the preceding finger chain, but it must not choose an axis. Axis override
and marker correction are separate decisions so an explicit axis also applies
when the chain does not need marker correction.

When `AUTO` is selected, the plugin leaves the metarig parameter as Rigify's
native `automatic` value. When an explicit axis is selected, the plugin writes
that value to the metarig before Rigify generation.

### 3. Mirroring and persistence

Compatibility serialization, import/export, copy, and mirror flows carry the new
field. Mirroring leaves `AUTO` unchanged and swaps every explicit signed pair:

`+X ↔ -X`, `+Y ↔ -Y`, and `+Z ↔ -Z`.

Invalid values are rejected by compatibility normalization with the same error
handling used by the existing compatibility fields.

### 4. Verification

Pure-Python tests will cover:

- default and validation of the new compatibility value;
- all signed-axis mirror pairs and `AUTO` preservation;
- explicit axis selection independent of bone names;
- `AUTO` not producing a thumb-specific axis;
- explicit axis application when marker geometry is already aligned;
- preservation of the existing marker-collinearity behavior.

Blender integration verification will reload the addon, generate the current
scene with explicit left/right thumb settings, inspect the generated drivers,
then repeat with `AUTO` and confirm no temporary test objects remain. The user
blend file will not be saved automatically.

## Non-goals

- No automatic inference from `Thumb`, `_L`, `_R`, or any other bone-name pattern.
- No changes to Rigify's own axis algorithm.
- No changes to unrelated `face.skin_eye` or `limbs.arm` compatibility settings.
- No post-generation driver patching as a substitute for metarig parameters.

## Acceptance criteria

1. The Compatibility panel exposes `Automatic`, `+X`, `-X`, `+Y`, `-Y`, `+Z`, and
   `-Z` for every configured `limbs.super_finger` bone.
2. Generated behavior is determined solely by that selected value and chain
   geometry, never by bone names.
3. Mirroring and configuration export/import preserve the setting with signed
   axes mirrored correctly.
4. Existing automated tests and Blender MCP verification pass.
