# Bone Rules and Collection Lifecycle Design

## Goal

Add persistent bone matching rules that assign one Rigify type and parameter set
to every matched bone. Keep generated rule rows visible in the normal bone list,
preserve collection references across import, save, and generation, propagate
collection renames into parameters, and configure generated collection
visibility.

## Confirmed Behavior

- Rules support `EXACT` and case-sensitive `GLOB` matching.
- Rules apply from top to bottom; the last matching rule wins.
- Existing ordinary rows become rule-managed when matched.
- Rule-managed rows are expanded in the normal bone list.
- Rule-managed bone name, Rigify type, and parameters are read-only there.
- Checked state, list order, collection assignment actions, and bone-list moves
  remain available for managed rows.
- A later exact rule provides a per-bone override.
- Rules can be added, removed, and moved up or down.
- A manual Sync Rules action is available.
- Import, validation, export, and generation synchronize rules automatically.
- Editing a pattern does not rebuild the list after every typed character.
- Rule parameters use Rigify's native parameter UI and the first matched source
  bone as the temporary carrier.
- Schema remains version 1 because the extension has not been distributed.

## Configuration Model

Add a top-level `bone_rules` list:

```json
{
  "rule_id": "stable-id",
  "kind": "GLOB",
  "pattern": "Finger_*_L",
  "rigify_type": "limbs.super_finger",
  "parameters": {
    "fk_layers_extra": true,
    "fk_coll_refs": ["Fingers"]
  }
}
```

Each RNA bone row gains an internal `managed_rule_id`. An empty value means the
row is manual. A non-empty value identifies the winning rule.

The canonical exported preset contains manual rows plus `bone_rules`; it does
not duplicate expanded managed rows. This prevents stale matches from one model
from breaking import on another model. Generation and validation use a resolved
payload containing both manual and materialized rule rows.

Rules receive stable IDs when created. IDs are exported so reimport and rule
reordering can update existing managed rows in place.

## Rule Resolution

A Blender-independent resolver:

1. Normalizes and validates all rules.
2. Matches each source bone against rules in list order.
3. Records only the last matching rule for each bone.
4. Produces the final type and deep-copied parameters for each match.

Rule sync updates the RNA list incrementally:

- Existing matched rows stay at their current positions and keep checked state.
- Their type, parameters, and winning rule ID are updated.
- Newly matched bones append in source-armature order.
- Previously managed rows with no winning rule are removed.
- The active bone is restored by bone name when it still exists.
- New managed rows use an empty explicit chain and default compatibility fields.

No-match patterns are validation errors. Duplicate rule IDs, empty patterns,
unknown match kinds, and unavailable Rigify types are also errors.

## Rule Parameter Editing

Add a Bone Matching Rules panel with a rule list, add/remove/move buttons,
matching controls, Rigify type search, Sync Rules button, and a nested Rule
Parameters panel.

The parameter carrier binding state is extended with a target kind:

- `BONE`: current behavior; flushes into a bone row.
- `RULE`: flushes into the rule identified by stable ID.

For a rule binding, the first matched source bone supplies the pose bone used by
Rigify's native parameter UI. The carrier reads the rule's type and JSON, but
writes changes back to the rule. If a rule has no match, the parameter panel
shows a validation message and does not create a carrier.

Switching rules, synchronizing, importing, exporting, validating, generating,
saving, and disabling the extension flushes the current binding first.

## Collection Rename Propagation

Add a pure `rename_collection_references(parameters, old_name, new_name)`
function. It replaces exact string entries in every list parameter whose name
ends in `_coll_refs`; other parameters remain unchanged.

Each collection keeps a hidden last valid name. When the user enters a new
non-empty, unique name:

1. Flush and remove the parameter carrier while its old collections still
   exist.
2. Rename references in every manual bone, managed bone, and bone rule.
3. Store the new valid name.
4. Recreate the active carrier on demand.

Empty or duplicate names do not rewrite references. Validation reports them,
and the last valid name remains the rename source for the next valid edit.
Bulk import runs with rename callbacks suspended and initializes the hidden
name after all collections are loaded.

Deleting a collection retains the existing behavior of removing its references
from both bone and rule parameters.

## Generated Collection Visibility

Each collection gains:

```json
"visible_after_generation": true
```

The field defaults to `true` when missing. The collection panel exposes it as
`Visible After Generation`.

Collection application copies the value to temporary metarig and parameter
carrier collections. After Rigify finishes, Re-Rigify explicitly applies the
configured value to same-named collections on the generated rig. This controls
only initial post-generation visibility; users may change visibility normally
afterward.

## Parameter Reference Loss Bug

### Observed State

Blender MCP inspection of the current project found:

- All stored `fk_coll_refs` and `tweak_coll_refs` are empty.
- Their corresponding `*_layers_extra` flags remain enabled.
- Generated Arm/Leg FK and Tweak collections exist but contain zero bones.

### Root Cause

`payload_to_armature` currently assigns `bone_name` and `rigify_type` without
suspending RNA update callbacks. Those assignments create a parameter carrier
with default empty collection references. Moving to the next row flushes those
defaults over the newly imported `parameters_json`. Generation then consumes
the empty references.

### Fix

- Flush and remove any existing carrier before bulk replacement.
- Wrap all payload-to-RNA assignments in `suspend_carrier_updates`.
- Load collections before any carrier can be recreated.
- Leave the carrier absent after import; the UI recreates it on demand.
- Add a two-bone regression test whose FK and Tweak references survive payload
  load, carrier creation, flush, export, and generation.

## Current Project Repair

After the code fix, restore the unambiguous current-model mappings:

- `Arm_L`: FK `Arm FK Left`, tweaks `Arm Tweaks Left`
- `Arm_R`: FK `Arm FK Right`, tweaks `Arm Tweaks Right`
- `Thigh_L`: FK `Leg FK Left`, tweaks `Leg Tweaks Left`
- `Thigh_R`: FK `Leg FK Right`, tweaks `Leg Tweaks Right`

Do not infer other empty collection references. Regenerate the current rig and
verify these eight generated collections contain bones. Restore the generated
rig pose and remove the temporary parameter carrier after testing. Leave saving
the `.blend` file to the user.

## Error Handling

- Synchronization is atomic at the payload-planning stage: invalid rules do not
  partially alter RNA rows.
- Invalid rule JSON, parameters, patterns, and Rigify types are reported before
  generation.
- Missing referenced collections reject validation rather than silently
  dropping names.
- Collection rename never rewrites references for an invalid destination name.
- Carrier cleanup remains safe without an active Blender object.

## Testing

Pure tests cover:

- Rule normalization and schema defaults.
- Exact and glob matching.
- Later-rule precedence.
- Managed-row planning for additions, updates, removals, and stable order.
- Collection reference rename/removal.
- Collection visibility round trip.

Blender integration and MCP checks cover:

- Rule RNA/preset round trip and incremental synchronization.
- Rule parameter carrier flush and rebinding.
- Rule-managed row read-only UI and normal selection/reordering.
- Collection rename propagation through bone and rule parameters.
- Multi-row payload loading without FK/Tweak reference loss.
- Generated FK/Tweak bone membership.
- Generated collection initial visibility.
- Current project repair and regeneration.
