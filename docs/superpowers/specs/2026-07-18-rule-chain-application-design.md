# Rule Chain Application Design

## Goal

Allow a bone matching rule to configure multiple disconnected Rigify chain
roots while using all matched bones as chain members. This supports
`limbs.spline_tentacle`, `limbs.super_finger`, and future explicitly supported
linear chain types without assigning the Rigify type to every child bone.

## Confirmed Problem

The current project rule matches 22 `Sp_He_Hair*` bones and assigns
`limbs.spline_tentacle` to every match. All 15 parent-child links inside the
seven hair chains have coincident endpoints but `use_connect` is false.

Rigify's `SimpleChainRig` discovers only connected children. Generation first
reports a one-bone chain at `Sp_He_Hair0_C_00`. Merely connecting the children
then produces overlapping rig claims because every child still owns the same
Rigify type. A temporary Blender MCP test succeeded only when the 15 internal
links were connected and the Rigify type was retained on the seven chain roots:

- `Sp_He_Hair0_C_00`
- `Sp_He_Hair0_L_00`
- `Sp_He_Hair2_L_00`
- `Sp_He_Hair2_R_00`
- `Sp_He_Hair4_C_00`
- `Sp_He_Hair4_L_00`
- `Sp_He_Hair4_R_00`

## Rule Schema and UI

Each bone rule gains one Boolean field:

```json
{
  "apply_as_chain": true
}
```

The field defaults to `false`, so existing presets retain per-bone rule
behavior. The rule panel exposes it as **Apply as Chain and Force Connect**.
It is deliberately a rule-level operation rather than a hidden Rigify native
parameter.

When disabled, every winning match materializes as one managed bone row,
unchanged from current behavior.

When enabled, winning matches are grouped into linear chains and only each
chain root materializes as a managed row. The row owns the rule's Rigify type
and native parameters. Its generated explicit chain contains the matched
members in parent-to-child order. Managed rows remain read-only for type,
parameters, chain, and compatibility.

Rule parameter editing uses the first resolved chain root as its carrier bone.

## Resolution and Precedence

Rules retain ordered, last-match-wins precedence. Resolution first determines
the winning rule for every source bone. Chain grouping then uses only adjacent
bones won by the same chain-enabled rule.

This ordering is important: a later rule may split an earlier rule's match into
separate components. Each remaining component is independently validated.

For each chain-enabled rule:

1. Select source bones for which that rule is the final winner.
2. Build the parent-child graph restricted to those bones.
3. Treat a bone whose parent is outside the winning set as a chain root.
4. Walk each root through its unique matched child.
5. Materialize only roots and store the ordered members as `chain_bones`.

The source armature is never modified. Connection operations run only on the
temporary Metarig.

## Validation

Validation rejects a chain-enabled result before Rigify generation when:

- a component has fewer than the supported minimum number of bones;
- a matched bone has more than one matched child;
- a component contains a cycle or cannot be fully reached from one root;
- an internal child's head does not coincide with its parent's tail within the
  existing geometry tolerance;
- the selected Rigify type is not in the supported chain-type registry.

Errors identify the rule pattern and the relevant source bone or component.

The initial supported registry includes:

- `limbs.super_finger`, minimum 2;
- `limbs.spline_tentacle`, minimum 2.

The registry is isolated so more Rigify chain types can be added without
changing rule serialization or UI behavior.

## Data Flow

Canonical export stores manual rows plus the rules and `apply_as_chain`; it
does not export materialized managed roots.

Import, manual synchronization, validation, export, and generation resolve
rules with source topology. For a chain-enabled rule they produce managed root
rows whose `chain_bones` contain the exact matched chain.

Metarig preparation applies those explicit chain operations before Rigify
initialization. It reparents only when required, enables `use_connect` for each
internal child, and leaves the chain root's external parent relationship
unchanged.

Collection matching continues to operate on all source/metarig bone names,
independently of whether a child has a configured bone row.

## Error Handling

Invalid rule JSON, unmatched rules, topology errors, or unsupported chain types
cancel synchronization-dependent workflows with actionable validation text.
No source bones are connected or repositioned. Existing target-rig generation
and cleanup behavior is unchanged by this feature.

## Testing

Pure tests cover:

- default normalization and JSON round trip;
- last-match precedence before chain grouping;
- seven independent chains from the current 22-name topology;
- root-only materialization and ordered `chain_bones`;
- branch, disjoint endpoint, short component, cycle, and unsupported-type
  errors.

Blender MCP tests cover:

- RNA persistence and rule UI state;
- synchronization producing seven managed roots;
- the source armature remaining disconnected;
- the temporary Metarig connecting 15 internal children;
- successful `limbs.spline_tentacle` generation without rig ownership
  conflicts;
- full cleanup of temporary objects and the parameter carrier.
