# Rigify Chain and Skin Eye Compatibility Design

## Goal

Allow production armatures with disconnected chains and vertically oriented facial
bones to use Rigify chain rigs without permanently editing the source armature.

The first supported cases are:

- `limbs.super_finger` on a parented but disconnected finger chain.
- `face.skin_eye` on an eye bone accompanied by independent upper and lower
  eyelid bones.

Generated eye and eyelid controls must drive the corresponding bones on the
source armature.

## User-facing configuration

Each Re-Rigify bone configuration gains a `Compatibility` group. These values
belong to Re-Rigify and are not copied into `rigify_parameters`.

### Force Connected Chain

`force_connect_chain` is available for Rigify types that consume a connected
chain. When enabled, Re-Rigify follows the unique child path starting at the
configured bone and marks that path connected in the temporary metarig.

It does not connect every descendant:

- A single child continues the chain.
- No child ends the chain.
- Multiple children are ambiguous and stop generation with a diagnostic that
  lists the candidate bones.
- A chain shorter than the Rigify type minimum is rejected before Rigify runs.

This converts the current
`Thumb_01_R -> Thumb_02_R -> Thumb_03_R` hierarchy into a connected temporary
metarig chain without changing the source bones.

### Skin Eye Compatibility

`skin_eye_compatibility` is available when the Rigify type is
`face.skin_eye`. Enabling it exposes:

- `eye_forward_axis`: `AUTO`, `+X`, `-X`, `+Y`, or `-Y`.
- `upper_lid_pattern`: a glob matching the source upper-eyelid landmarks.
- `lower_lid_pattern`: a glob matching the source lower-eyelid landmarks.
- `synthetic_lids_fallback`: generate temporary landmarks when either real
  eyelid set cannot form a valid chain. It defaults to disabled because
  synthetic segments cannot drive real eyelid bones.

For the current armature the expected patterns are `Eye_up_*_L` and
`Eye_bottom_*_L`, mirrored for the right side. `AUTO` evaluates the horizontal
axes and chooses the direction facing away from the head center. If the result
is ambiguous, validation asks the user to choose an explicit axis.

## Temporary metarig adaptation

All compatibility changes occur after duplicating the source armature and before
calling Rigify.

### Chain adaptation

The adapter resolves a unique child chain from source parenting, then changes
`parent` and `use_connect` only on edit bones in the temporary metarig. Bone
names and positions remain unchanged, so the existing generated-rig drive
mapping continues to work.

### Eye adaptation

The eye adapter performs these steps independently for each configured eye:

1. Reorient the temporary eye bone along the resolved forward axis while
   preserving its head position and length.
2. Resolve upper and lower eyelid landmark bones with the configured globs.
3. Sort each landmark set around the eye center from one corner to the other.
4. Create two Rigify-compatible connected chains from those landmarks. The
   temporary names use Rigify top/bottom and side suffixes so shared corner
   nodes merge correctly.
5. Assign `skin.stretchy_chain` to the two chain roots and parent those roots
   to the eye rig.
6. Record which generated deform bone corresponds to every original eyelid
   bone.

The source eyelid bones are not renamed, reparented, reoriented, or connected.
If synthetic fallback is used, synthetic segments have no source drive target;
they exist only to let Rigify construct the Skin Eye controls.

## Generated-to-source drive mapping

The current name-based mapping remains the default. Eye adaptation adds
explicit mappings for the eye deform bone and temporary eyelid segment names:

```
source eye bone -> generated DEF eye bone
source eyelid bone -> generated DEF temporary-segment bone
```

This eye mapping is necessary because Rigify aims the generated `DEF` eye
through its target control, while the same-named `ORG` eye only follows the
eye-master parent. Changing the global `ORG`/`DEF` preference would affect
unrelated rig types, so the override is scoped to configured `face.skin_eye`
plans.

The mapping is stored on the generated rig as Re-Rigify metadata so it survives
metarig cleanup and can be reused when updating an existing generated rig.
`connect_source_to_rig` checks this explicit mapping before its normal
`DEF-`, `ORG-`, and same-name candidates.

Copy Transforms constraints remain in local owner orientation, matching the
existing Re-Rigify drive behavior. Moving a generated eyelid control must move
the generated deform segment and therefore the mapped source eyelid bone.

## Configuration format

Bone entries gain an optional `compatibility` object while the unpublished
format remains at schema version 1. Files without the object load with
compatibility disabled, and export writes the normalized object.

Compatibility state is included in copy, mirror, import, and export operations.
Mirroring also mirrors eye patterns and the explicit horizontal axis.

## Validation and errors

Validation runs before generation and reports errors against the configured
source bone:

- Connected-chain option reaches an ambiguous branch.
- Connected-chain result is shorter than the Rigify minimum.
- Eye forward direction is parallel to world Z or cannot be inferred.
- A real eyelid glob matches too few usable landmarks.
- Upper and lower landmark geometry cannot produce two shared corners.
- An eyelid source bone would be claimed by more than one eye adapter.

When synthetic fallback is enabled, insufficient real landmarks become a
warning that lists the unmatched patterns. Unexpected Rigify exceptions still
propagate, but known topology problems no longer appear as division-by-zero or
generic generation failures.

## Testing

Pure tests cover:

- Unique-chain traversal and branch rejection.
- Compatibility serialization and version-1 default handling.
- Mirroring compatibility settings and glob patterns.
- Eyelid landmark ordering and temporary-name/source-name mapping.
- Forward-axis inference and ambiguous cases.

Blender MCP integration tests use temporary copies of the current armature to
verify:

- `Thumb_01_R` generates as a three-bone `limbs.super_finger` chain.
- Both `Eye_L` and `Eye_R` generate as `face.skin_eye`.
- Generated eyelid controls affect generated deform bones.
- Generated `Eye_common`, `Eye_L`, and `Eye_R` controls drive the corresponding
  source eye bones through generated `DEF-Eye_L` and `DEF-Eye_R`.
- Re-Rigify constraints transfer those transforms to the matching
  `Eye_up_*` and `Eye_bottom_*` source bones.
- Regeneration preserves the explicit eyelid mapping.
- The source armature's bone parenting, connection flags, names, and rest
  transforms are unchanged.
- All temporary metarigs, helpers, and test objects are removed.

No standalone Blender process is used for integration verification.
