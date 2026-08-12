# Explicit Chain and Drive Lifecycle Design

## Goal

Generate Rigify controls from production skeletons whose useful deform chain does not
match their parent hierarchy. For the current UMA skeleton, `hips` must drive the real
`Hip` deform bone through the explicit chain `Hip, Waist, Spine, Chest`.

Also make drive removal independent of transient Blender UI context and keep
`__ReRigify_Parameter_Carrier__` out of saved files.

## Reference Behavior

MikuMikuRig uses a prebuilt standard metarig. `BIG_UMA.json` maps:

- `Hip` to `spine`
- `Waist` to `spine.001`
- `Spine` to `spine.002`
- `Chest` to `spine.003`

Re-Rigify will not import or depend on MikuMikuRig presets. It will provide equivalent
behavior through its own explicit-chain configuration.

## Configuration Model

Each configured Rigify root gains an optional ordered `chain_bones` list:

```json
{
  "bone_name": "Hip",
  "rigify_type": "spines.basic_spine",
  "chain_bones": ["Hip", "Waist", "Spine", "Chest"],
  "parameters": {},
  "compatibility": {}
}
```

Rules:

- Empty `chain_bones` preserves current inferred-topology behavior.
- First entry must equal `bone_name`.
- Every entry must name an existing source bone.
- Entries must be unique.
- The list must meet the selected Rigify type's minimum chain length.
- Explicit chains describe linear connected chains only. Branched topology keeps existing
  inference and compatibility mechanisms.

Configuration remains schema version 1 because the extension has not been distributed.
Input without `chain_bones` receives an empty list; export writes the field.

## Blender Storage and UI

`RERIGIFY_PG_BoneConfig` owns an ordered collection of chain-bone entries and an active
index. Bone Setup shows this editor for supported linear Rigify types.

Actions:

- Add selected pose/edit bones, preserving source armature order.
- Remove active entry.
- Move active entry up or down.
- Reject duplicate entries in validation rather than silently rewriting user data.

Import, export, mirroring, duplication, and parameter-copy workflows preserve and mirror
the ordered list.

## Temporary Metarig Generation

Explicit topology is applied only to the temporary metarig copy:

1. Read the ordered chain.
2. For each adjacent parent and child, preserve the child's original head.
3. Set the parent's tail to that head.
4. Set the child's parent and enable `use_connect`.
5. Let Rigify generate from the resulting connected chain.

The source armature's rest bones and parenting remain unchanged.

For the UMA configuration, replace `Waist = spines.basic_spine` with
`Hip = spines.basic_spine` and the four-bone explicit chain. The existing adapter helper
keeps the source `Hip` rest transform as an offset under generated `ORG-Hip`. Rotating
Rigify `hips` therefore changes source `Hip`, while the model remains undeformed at bind
pose.

## Drive Removal

Edit-mode operations on generated rigs must use an explicit Blender context:

- Verify the generated rig still exists and belongs to the current view layer.
- Normalize the current active object to Object Mode when possible.
- Unhide and make the generated rig selectable.
- Use `context.temp_override` with `object`, `active_object`, selected objects, and
  selected editable objects while entering Edit Mode.
- Remove only bones prefixed `MCH-RR-Drive-`.
- Restore the previous active object, selection, and mode when those objects remain valid.

The Remove Drive operator reports a clear error and returns `CANCELLED` when no source
armature is active or helper cleanup cannot obtain a valid editable context.

## Parameter Carrier Lifecycle

The parameter carrier remains a temporary adapter for Rigify's pose-bone parameter RNA.
It is not authoritative configuration.

Lifecycle:

1. Opening Active Bone Parameters creates it on demand.
2. Parameter edits are serialized to `parameters_json`.
3. Save, generation, import, export, and add-on unload flush pending values.
4. Save removes the carrier before Blender serializes the file.
5. A later panel draw recreates it from stored JSON.

Deleting the carrier must never delete source armature data because it always owns a copied
armature datablock.

## Errors

Validation messages identify the configured root and exact bad chain condition:

- missing root entry
- missing source bone
- duplicate source bone
- unsupported Rigify type
- insufficient chain length

Generation does not guess a replacement chain after explicit-chain validation fails.

## Testing

Pure Python tests cover:

- version 1 defaults and round-trip
- root mismatch, missing bone, duplicates, and minimum length
- explicit operations overriding inferred hierarchy
- mirrored chain names

Connected Blender MCP integration checks cover:

- UI storage and JSON round-trip
- explicit `Hip, Waist, Spine, Chest` temporary topology
- generated `hips` changing source `Hip`
- unchanged source bind matrices immediately after connection
- drive removal from Object and Pose Mode with unstable prior selection
- context restoration after helper removal
- save handler flushing and deleting the parameter carrier
- carrier recreation from serialized parameters

Full existing unit and Blender integration suites remain required.

## Out of Scope

- Importing `BIG_UMA.json` or other MikuMikuRig presets
- Automatic bone-name detection
- Replacing the source armature or transferring mesh weights
- General branched metarig graph authoring
